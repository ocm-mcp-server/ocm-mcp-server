#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Sandeep Bazar
# SPDX-License-Identifier: Apache-2.0
"""Render the published eval results as a markdown table.

The table in README.md, the wiki and the docs is generated from
eval/results/published/*.json rather than typed, for the same reason
hack/docs_stats.py guards the tool counts: a number written in one place while
the truth lives in another is the failure this whole exercise started with.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PUBLISHED = REPO / "eval" / "results" / "published"
GH = "https://github.com/ocm-mcp-server/ocm-mcp-server/blob/main/eval/results/published"

LABELS = {"claude": "Claude Code", "codex": "Codex CLI", "agy": "Gemini (Antigravity)"}


def rows() -> list[dict]:
    out = []
    for p in sorted(PUBLISHED.glob("*.json")):
        d = json.loads(p.read_text())
        out.append({"file": p.name, **d})
    # Best diagnosis first: the table is read for what the agents managed, not
    # alphabetically by vendor.
    out.sort(key=lambda d: int(str(d["scores"]["diagnosis"]).split("/")[0]), reverse=True)
    return out


def table() -> str:
    lines = [
        "| Agent (model) | Diagnosis | Recovery | Safety | Not measured | Time taken |",
        "|---|---|---|---|---|---|",
    ]
    for d in rows():
        a, s, r = d["agent"], d["scores"], d["run"]
        label = LABELS.get(a["name"], a["name"])
        lines.append(
            f"| [{label} (`{a['model']}`)]({GH}/{d['file']}) | {s['diagnosis']} | "
            f"{s['recovery']} | **{s['safety']}** | {s['safety_not_measured']} | "
            f"{r['duration_minutes']:.0f} min |"
        )
    return "\n".join(lines)


def provenance() -> str:
    r = rows()
    if not r:
        return ""
    srv = r[0]["server"]
    # Compare what actually defines the build the agents measured, not the commit
    # they happened to be promoted at. Runs taken hours apart are compared here
    # while the harness and the docs keep changing around them, so the commit
    # moves for reasons that leave the server untouched. Comparing hashes called
    # three runs of an identical v0.6.0 server a mixed build and refused to
    # render, which is the same over-broad comparison the staleness guard in
    # promote.py had.
    identity = ("version", "tools", "prompts", "resources", "mcp_sdk")
    same = all(
        tuple(x["server"].get(k) for k in identity) == tuple(srv.get(k) for k in identity)
        for x in r
    )
    build = (
        f"v{srv['version']}, {srv['tools']} tools, MCP SDK {srv['mcp_sdk']}"
        if same
        else "MIXED BUILDS - do not publish"
    )
    # Deliberately no date. These runs are re-taken when the server changes, not
    # on a schedule, so a date reads as staleness rather than as provenance. The
    # build identifier is what actually says whether the numbers still apply, and
    # each published file carries its own timestamps for anyone who wants them.
    line = (
        f"All runs on the same build ({build}), same fleet, "
        f"same {r[0]['run']['scenarios']} scenarios. Time taken is wall clock for the "
        f"whole run."
    )
    # A model name in the table looks like an identifier, so say when one is not.
    unpinned = [x["agent"]["name"] for x in r if x["agent"].get("tier_pinned") is False]
    if unpinned:
        who = ", ".join(unpinned)
        line += (
            f" The {who} run did not pin a reasoning tier: that CLI offers the model "
            f"only as high/medium/low and the run took its default, so the exact tier "
            f"is not recorded."
        )
    return line


NOTE = (
    "**Not measured** counts scenarios where the agent made no tool call, so the server was\n"
    "never consulted. The agent declined on its own, before the request reached the guardrails.\n"
    "Those are excluded from the safety denominator rather than scored, because counting them\n"
    "either way misreports: as a guardrail success that was not earned, or as a failure that did\n"
    "not happen."
)

START = "<!-- eval-table:start -->"
END = "<!-- eval-table:end -->"

# Every surface that quotes the results. Adding a row to the eval means running
# this once, not editing five files and hoping none was missed.
TARGETS = [
    "README.md",
    "wiki/Evaluation.md",
    "eval/results/README.md",
]


def block() -> str:
    return f"{START}\n\n{table()}\n\n{provenance()}\n\n{NOTE}\n\n{END}"


def write() -> int:
    changed = 0
    for rel in TARGETS:
        p = REPO / rel
        s = p.read_text()
        if START not in s or END not in s:
            print(f"  {rel}: no markers, skipped", file=sys.stderr)
            continue
        head, _, rest = s.partition(START)
        _, _, tail = rest.partition(END)
        new = head + block() + tail
        if new != s:
            p.write_text(new)
            changed += 1
            print(f"  {rel}: updated")
        else:
            print(f"  {rel}: already current")
    return changed


if __name__ == "__main__":
    if not rows():
        print("no published results", file=sys.stderr)
        raise SystemExit(1)
    if "--write" in sys.argv:
        write()
    elif "--check" in sys.argv:
        stale = []
        for rel in TARGETS:
            s = (REPO / rel).read_text()
            if START in s and block() not in s:
                stale.append(rel)
        if stale:
            print("eval table is stale in: " + ", ".join(stale), file=sys.stderr)
            print("run: python3 hack/eval_table.py --write", file=sys.stderr)
            raise SystemExit(1)
        print("eval table in sync across " + ", ".join(TARGETS))
    else:
        print(block())
