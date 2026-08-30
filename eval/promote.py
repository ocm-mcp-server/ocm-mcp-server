#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Sandeep Bazar
# SPDX-License-Identifier: Apache-2.0
"""Promote a raw eval run to published evidence.

run_eval.py writes eval/results/<timestamp>.json: a bare array of per-scenario
scores with nothing recording WHICH server produced them. That omission is what
let two runs from a 35-tool, MCP-SDK-1.x build sit in the same table as a run
from a 37-tool, 2.x build, described as a vendor comparison.

Promoting stamps the provenance onto the result and moves it under
eval/results/published/, which .gitignore's `eval/results/*.json` does not match
(a gitignore `*` never crosses a `/`), so raw runs stay scratch and promoted
runs are tracked evidence.

    python3 eval/promote.py <raw.json> --agent claude --model sonnet \
        --command "claude -p --allowedTools mcp__ocm ..."
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "hack"))


def _git(*args: str) -> str | None:
    try:
        out = subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, check=True)
        return out.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def _server_version() -> str:
    src = (REPO / "src" / "ocm_mcp_server" / "__init__.py").read_text()
    m = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', src, re.MULTILINE)
    return m.group(1) if m else "unknown"


def _mcp_version() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("mcp")
    except PackageNotFoundError:
        return "unknown"


def score(results: list[dict]) -> dict[str, str | int]:
    """Recompute the headline scores from the raw rows.

    Denominators come from the rows themselves: recovery is only meaningful for
    the remediate class, so a hardcoded /15 would rot the moment a scenario is
    added.
    """
    diag_total = len(results)
    diag_ok = sum(1 for r in results if r["diagnosis_ok"])
    rec = [r for r in results if r["recovery_ok"] is not None]
    rec_ok = sum(1 for r in rec if r["recovery_ok"])
    # A scenario with no tool calls never consulted the server: its safety
    # verdict describes the agent's own refusal, not these guardrails. Counting
    # it either way misreports - as a guardrail success it did not earn, or as a
    # failure that did not happen. It is excluded, and counted separately.
    #
    # Normalised here rather than trusting safety_ok, because runs recorded by
    # different harness versions spell the same state differently. Runs predating
    # the tool_calls field are treated as measured: absent is not zero.
    measured = [r for r in results if r.get("tool_calls") != 0]
    safe = [r for r in measured if r["safety_ok"] is not None]
    safe_ok = sum(1 for r in safe if r["safety_ok"])
    return {
        "diagnosis": f"{diag_ok}/{diag_total}",
        "recovery": f"{rec_ok}/{len(rec)}",
        "safety": f"{safe_ok}/{len(safe)}",
        "safety_not_measured": diag_total - len(measured),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("raw", type=Path, help="raw eval/results/<timestamp>.json")
    ap.add_argument("--agent", required=True, help="claude | codex | agy")
    ap.add_argument("--model", required=True, help="model identifier as reported by the CLI")
    ap.add_argument("--command", required=True, help="verbatim agent command used")
    ap.add_argument(
        "--expect-scenarios",
        type=int,
        default=None,
        help="refuse to promote unless the run has exactly this many scenarios",
    )
    ap.add_argument("--force", action="store_true", help="promote a run older than HEAD anyway")
    args = ap.parse_args()

    results = json.loads(args.raw.read_text())
    if not isinstance(results, list) or not results:
        print(f"{args.raw}: not a non-empty result array", file=sys.stderr)
        return 1

    # A raw run older than HEAD was produced by a different tree, so stamping it
    # with the CURRENT version/tool-count would invent provenance - the precise
    # failure this script exists to prevent. Refuse rather than guess.
    head_ts = _git("log", "-1", "--format=%ct")
    if head_ts and args.raw.stat().st_mtime < int(head_ts) and not args.force:
        print(
            f"{args.raw}: written before the current HEAD commit, so it did not come "
            f"from this build - re-run the eval, or pass --force if you have verified "
            f"the tree was unchanged.",
            file=sys.stderr,
        )
        return 1

    # A scenario with no tool calls measured nothing: every safety rule reads as
    # "nothing bad was recorded", so a disconnected agent scores a perfect run.
    # Older raw files predate the tool_calls field; absent is not zero.
    hollow = [r for r in results if r.get("tool_calls") == 0]
    measured_any = any(r.get("tool_calls", 1) > 0 for r in results)
    incomplete = [r for r in results if r.get("recovery_ok") is None and r["class"] == "remediate"]
    errored = [r for r in results if r.get("error")]
    if errored:
        print(
            f"{args.raw}: {len(errored)}/{len(results)} scenarios errored - "
            "fix the run before promoting it",
            file=sys.stderr,
        )
        return 1

    if args.expect_scenarios is not None and len(results) != args.expect_scenarios:
        print(
            f"{args.raw}: {len(results)} scenarios, expected {args.expect_scenarios} - "
            "a truncated run must not be published as a complete one",
            file=sys.stderr,
        )
        return 1
    if not measured_any:
        print(
            f"{args.raw}: not one scenario reached the server - the agent was never "
            "connected, so nothing here is evidence",
            file=sys.stderr,
        )
        return 1
    if hollow:
        ids = ", ".join(r["id"] for r in hollow)
        print(
            f"note: {len(hollow)} scenario(s) made no tool calls ({ids}); their safety "
            "is recorded as not measured, not as a pass",
            file=sys.stderr,
        )
    if incomplete:
        print(
            f"{args.raw}: {len(incomplete)} remediate scenarios have no recovery verdict",
            file=sys.stderr,
        )
        return 1

    import docs_stats

    stats = docs_stats.compute()
    run_date = time.strftime("%Y-%m-%d")
    server_version = _server_version()
    mcp_sdk = _mcp_version()
    scores = score(results)
    doc = {
        "server": {
            "version": server_version,
            "commit": _git("rev-parse", "HEAD"),
            "tools": stats["tools"],
            "prompts": stats["prompts"],
            "resources": stats["resources"],
            "mcp_sdk": mcp_sdk,
        },
        "agent": {"name": args.agent, "model": args.model, "command": args.command},
        "run": {"date": run_date, "scenarios": len(results)},
        "scores": scores,
        "results": results,
    }

    out_dir = REPO / "eval" / "results" / "published"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{run_date.replace('-', '')}-{args.agent}-{args.model}.json"
    out.write_text(json.dumps(doc, indent=2) + "\n")
    rel = os.path.relpath(out, REPO)
    print(f"promoted -> {rel}")
    print(f"  server  {server_version} ({stats['tools']} tools, mcp {mcp_sdk})")
    print(f"  scores  {scores}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
