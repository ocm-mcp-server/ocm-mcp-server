#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Sandeep Bazar
# SPDX-License-Identifier: Apache-2.0
"""Keep the numbers quoted in README/docs/wiki in lockstep with reality.

Docs that quote counts (tools, prompts, policies, test cases) rot silently as
the project grows. This script computes the real numbers from the source of
truth and verifies every quoted occurrence matches:

    python3 hack/docs_stats.py --check    # CI / pre-push: fail on drift
    python3 hack/docs_stats.py --fix      # rewrite the quoted numbers in place

Sources of truth:
- tools / prompts .......... @mcp.tool / @mcp.prompt decorators in server.py
- Kyverno policies ......... *.yaml files in deploy/policies/
- Kyverno test cases ....... resources listed in deploy/policies/tests/kyverno-test.yaml
- unit tests ............... pytest --collect-only
"""

from __future__ import annotations

import argparse
import glob
import os
import re
import subprocess
import sys

import yaml

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def compute() -> dict[str, int]:
    with open(os.path.join(REPO, "src", "ocm_mcp_server", "server.py")) as fh:
        server = fh.read()
    with open(os.path.join(REPO, "deploy", "policies", "tests", "kyverno-test.yaml")) as fh:
        test_spec = yaml.safe_load(fh)
    collected = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q"],
        capture_output=True,
        text=True,
        cwd=REPO,
        check=True,
    )
    m = re.search(r"(\d+) tests collected", collected.stdout)
    assert m, f"could not parse pytest collection output:\n{collected.stdout[-500:]}"
    return {
        "tools": server.count("@mcp.tool("),
        "prompts": server.count("@mcp.prompt("),
        "resources": server.count("@mcp.resource("),
        "policies": len(glob.glob(os.path.join(REPO, "deploy", "policies", "*.yaml"))),
        "policy_cases": sum(len(r["resources"]) for r in test_spec["results"]),
        "unit_tests": int(m.group(1)),
    }


# Every quoted occurrence: (relative file, regex with ONE numeric group, stat key).
# The surrounding text anchors the number so unrelated digits are never touched.
QUOTES: list[tuple[str, str, str]] = [
    ("README.md", r"ships (\d+) `ClusterPolicy` objects", "policies"),
    ("README.md", r"runs a \*\*(\d+)-case offline suite\*\*", "policy_cases"),
    ("README.md", r"`make policy-test` runs (\d+) CLI", "policy_cases"),
    ("README.md", r"The surface is \*\*(\d+) tools", "tools"),
    ("README.md", r"\*\*(\d+) MCP resources\*\*", "resources"),
    ("docs/deployment.md", r"# (\d+) policies, all READY", "policies"),
    ("docs/upstream-notes.md", r"Contribute the (\d+) policies", "policies"),
    ("wiki/Guardrails-Deep-Dive.md", r"The (\d+) policies in `deploy/policies/`", "policies"),
    ("wiki/Guardrails-Deep-Dive.md", r"`make policy-test`, (\d+) cases", "policy_cases"),
    ("wiki/Implementation.md", r"unit tests \((\d+);", "unit_tests"),
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="fail if any quoted number drifted")
    mode.add_argument("--fix", action="store_true", help="rewrite drifted numbers in place")
    args = parser.parse_args()

    stats = compute()
    print("computed: " + ", ".join(f"{k}={v}" for k, v in stats.items()))

    drifted = []
    for rel_path, pattern, key in QUOTES:
        path = os.path.join(REPO, rel_path)
        with open(path) as fh:
            text = fh.read()
        matches = list(re.finditer(pattern, text))
        if not matches:
            drifted.append(f"{rel_path}: pattern not found: {pattern!r}")
            continue
        for m in matches:
            if int(m.group(1)) != stats[key]:
                drifted.append(
                    f"{rel_path}: quotes {key}={m.group(1)}, actual is {stats[key]} "
                    f"(pattern {pattern!r})"
                )
        if args.fix:
            actual = str(stats[key])
            new = re.sub(
                pattern,
                lambda m, actual=actual: m.group(0).replace(m.group(1), actual, 1),
                text,
            )
            if new != text:
                with open(path, "w") as fh:
                    fh.write(new)
                print(f"fixed: {rel_path}")

    if drifted and args.check:
        print("\nDOCS DRIFT - quoted numbers no longer match reality:")
        for line in drifted:
            print(f"- {line}")
        print("\nRun 'python3 hack/docs_stats.py --fix' to update them.")
        return 1
    if not drifted:
        print("docs in sync: every quoted number matches")
    return 0


if __name__ == "__main__":
    sys.exit(main())
