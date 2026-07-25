#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Sandeep Bazar
# SPDX-License-Identifier: Apache-2.0
"""Render a self-contained, graphical HTML report from the e2e results JSONL.

Each JSONL record: {phase, title, why, cmd, output, status, kind?}.
Statuses drive colour: OK/PASS (green), FAIL (red), UNAVAILABLE/SKIP (amber),
INFO (blue), INJECT (purple), FIX (teal). Usage:

    e2e_report.py --results results.jsonl --out e2e-report.html [--title "..."]
"""
from __future__ import annotations

import argparse
import html
import json
from collections import OrderedDict
from datetime import datetime

STATUS = {
    "OK": ("#1a7f37", "#dafbe1"), "PASS": ("#1a7f37", "#dafbe1"),
    "FAIL": ("#cf222e", "#ffebe9"),
    "UNAVAILABLE": ("#9a6700", "#fff8c5"), "SKIP": ("#9a6700", "#fff8c5"),
    "INFO": ("#0969da", "#ddf4ff"),
    "INJECT": ("#8250df", "#fbefff"), "FIX": ("#1b7c83", "#d9f7f5"),
}


def esc(s: str) -> str:
    return html.escape(str(s or ""))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--title", default="ocm-mcp-server - end-to-end test report")
    ap.add_argument("--generated", default=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    args = ap.parse_args()

    records = []
    with open(args.results) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                # a truncated final line from an interrupted run must not kill the report
                continue

    phases: OrderedDict[str, list] = OrderedDict()
    counts: dict[str, int] = {}
    for r in records:
        phases.setdefault(r.get("phase", "Other"), []).append(r)
        counts[r.get("status", "INFO")] = counts.get(r.get("status", "INFO"), 0) + 1

    ok = counts.get("OK", 0) + counts.get("PASS", 0)
    fail = counts.get("FAIL", 0)
    warn = counts.get("UNAVAILABLE", 0) + counts.get("SKIP", 0)
    verdict = "ALL GREEN" if fail == 0 else f"{fail} FAILED"
    verdict_col = "#1a7f37" if fail == 0 else "#cf222e"

    cards = []
    for phase, items in phases.items():
        rows = []
        for r in items:
            fg, bg = STATUS.get(r.get("status", "INFO"), ("#57606a", "#eaeef2"))
            cmd = esc(r.get("cmd", ""))
            out = esc(r.get("output", "")).rstrip()
            why = esc(r.get("why", ""))
            cmd_html = f'<div class="cmd">$ {cmd}</div>' if cmd else ""
            out_html = f'<pre class="out">{out}</pre>' if out else ""
            why_html = f'<div class="why">{why}</div>' if why else ""
            rows.append(f"""
            <div class="card">
              <div class="chead">
                <span class="badge" style="color:{fg};background:{bg}">{esc(r.get('status',''))}</span>
                <span class="ctitle">{esc(r.get('title',''))}</span>
              </div>
              {why_html}{cmd_html}{out_html}
            </div>""")
        cards.append(f'<section><h2>{esc(phase)}</h2>{"".join(rows)}</section>')

    def chip(label: str, n: int, col: str, bg: str) -> str:
        return f'<span class="chip" style="color:{col};background:{bg}"><b>{n}</b> {label}</span>'

    summary = "".join([
        chip("passed", ok, "#1a7f37", "#dafbe1"),
        chip("expected-unavailable", warn, "#9a6700", "#fff8c5"),
        chip("failed", fail, "#cf222e", "#ffebe9"),
        chip("total steps", len(records), "#0969da", "#ddf4ff"),
    ])

    doc = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(args.title)}</title>
<style>
:root{{color-scheme:light}}
*{{box-sizing:border-box}}
body{{margin:0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;
  background:#f6f8fa;color:#1f2328;line-height:1.5}}
header{{background:linear-gradient(135deg,#0b3d91,#1b7c83);color:#fff;padding:32px 24px}}
header h1{{margin:0 0 6px;font-size:24px}}
header .sub{{opacity:.9;font-size:14px}}
.verdict{{display:inline-block;margin-top:14px;padding:6px 16px;border-radius:999px;
  background:#fff;font-weight:800;font-size:15px;color:{verdict_col}}}
.wrap{{max-width:1080px;margin:0 auto;padding:24px}}
.summary{{display:flex;flex-wrap:wrap;gap:10px;margin:-12px 0 20px}}
.chip{{padding:8px 14px;border-radius:999px;font-size:13px}}
.chip b{{font-size:15px}}
section{{background:#fff;border:1px solid #d0d7de;border-radius:12px;padding:18px 18px 6px;margin:0 0 20px}}
section h2{{margin:0 0 14px;font-size:17px;color:#0b3d91;border-bottom:2px solid #eaeef2;padding-bottom:8px}}
.card{{border:1px solid #eaeef2;border-radius:10px;padding:12px 14px;margin:0 0 12px;background:#fbfcfe}}
.chead{{display:flex;align-items:center;gap:10px;margin-bottom:4px}}
.badge{{font-size:11px;font-weight:800;letter-spacing:.03em;padding:3px 9px;border-radius:999px}}
.ctitle{{font-weight:700;font-size:14.5px}}
.why{{color:#57606a;font-size:13.5px;margin:2px 0 8px}}
.cmd{{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12.5px;background:#0d1117;
  color:#c9d1d9;padding:8px 12px;border-radius:8px;overflow-x:auto;white-space:pre;margin:6px 0}}
pre.out{{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px;background:#f6f8fa;
  border:1px solid #eaeef2;border-radius:8px;padding:10px 12px;overflow:auto;max-height:340px;margin:6px 0 4px}}
footer{{text-align:center;color:#8b949e;font-size:12px;padding:18px}}
</style></head><body>
<header><div class="wrap" style="padding-bottom:0">
  <h1>{esc(args.title)}</h1>
  <div class="sub">Generated {esc(args.generated)} - local kind fleet via podman, Open Cluster Management hub</div>
  <span class="verdict">{verdict}</span>
</div></header>
<div class="wrap">
  <div class="summary">{summary}</div>
  {''.join(cards)}
</div>
<footer>Reproduce with <code>./hack/e2e-local.sh</code> - this report is generated, not checked in.</footer>
</body></html>"""

    with open(args.out, "w") as f:
        f.write(doc)
    print(f"report written: {args.out}  ({len(records)} steps, {ok} ok, {warn} unavailable, {fail} failed)")


if __name__ == "__main__":
    main()
