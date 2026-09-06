#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Sandeep Bazar
# SPDX-License-Identifier: Apache-2.0
"""Refuse to ship a credential.

Eval results record what an agent said and did, verbatim, and those results are
committed. An agent that echoes the key it was given would put that key in the
repository as ordinary data, which is why this scans every tracked file rather
than only the ones a person edits.

Usage:  python3 hack/check_secrets.py
"""

from __future__ import annotations

import re
import subprocess
import sys

# Each pattern is anchored on a vendor's own prefix. Generic "looks like base64"
# rules match hashes, lockfile digests and git object ids, and a check that cries
# wolf gets switched off.
RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bbob_prod_[A-Za-z0-9_-]{20,}"), "IBM Bob API key"),
    (re.compile(r"\bsk-ant-(?!mock|test)[A-Za-z0-9_-]{20,}"), "Anthropic API key"),
    (re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9]{32,}"), "OpenAI API key"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}"), "GitHub token"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "AWS access key id"),
    (re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----"), "private key"),
]

SELF = "hack/check_secrets.py"


def main() -> int:
    files = subprocess.run(
        ["git", "ls-files", "-z"], capture_output=True, text=True, check=True
    ).stdout.split("\0")
    findings: list[str] = []
    for name in filter(None, files):
        if name == SELF:  # the patterns below are literals in this file
            continue
        try:
            raw = subprocess.run(
                ["git", "show", f"HEAD:{name}"], capture_output=True, check=True
            ).stdout
        except subprocess.CalledProcessError:
            continue  # not committed yet
        # Read bytes: the tree holds images and archives, and a credential is text.
        # A NUL byte means binary, and decoding it would only produce noise to scan.
        if b"\0" in raw[:8192]:
            continue
        body = raw.decode("utf-8", errors="replace")
        for pattern, what in RULES:
            for m in pattern.finditer(body):
                line = body[: m.start()].count("\n") + 1
                findings.append(f"{name}:{line} {what}: {m.group(0)[:12]}…")

    if findings:
        print("secret scan FAILED", file=sys.stderr)
        print("\n".join(findings), file=sys.stderr)
        return 1
    print(f"no credentials in {len(list(filter(None, files)))} tracked files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
