#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Sandeep Bazar
# SPDX-License-Identifier: Apache-2.0
"""Guardrail <-> Kyverno parity contract test.

The project's safety story rests on two independent enforcement layers agreeing:
the Python static guardrails (layer 1) and the Kyverno admission policies
(layer 2). This script makes that claim CI-enforced instead of documentation:
every labelled ManifestWork fixture in deploy/policies/tests/resources.yaml is
run through BOTH layers, and the verdicts must be identical.

    python3 hack/parity_contract.py       (or: make parity-test)

Requires the `kyverno` CLI (same version as CI) and PyYAML. Unlabelled fixtures
are excluded: the policies deliberately do not match them (label scoping), while
the Python guardrails see every proposal, so parity is only defined for the
labelled corpus.
"""

from __future__ import annotations

import glob
import os
import shutil
import subprocess
import sys
import tempfile

import yaml

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "src"))

from ocm_mcp_server.guardrails import GuardrailViolation, validate_manifests

FIXTURES = os.path.join(REPO, "deploy", "policies", "tests", "resources.yaml")
LABEL = "app.kubernetes.io/managed-by"


def python_verdict(manifests: list[dict]) -> tuple[bool, str]:
    try:
        validate_manifests(manifests)
        return True, ""
    except GuardrailViolation as exc:
        return False, str(exc).splitlines()[0]


def kyverno_verdict(policy_files: list[str], fixture: dict) -> tuple[bool, str]:
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as fh:
        yaml.safe_dump(fixture, fh)
        path = fh.name
    try:
        proc = subprocess.run(
            ["kyverno", "apply", *policy_files, "--resource", path],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    finally:
        os.unlink(path)
    out = proc.stdout + proc.stderr
    if proc.returncode == 0:
        return True, ""
    if "fail" in out:
        return False, out.strip().splitlines()[-1]
    raise RuntimeError(f"kyverno apply errored (rc={proc.returncode}):\n{out}")


def main() -> int:
    if not shutil.which("kyverno"):
        print("SKIP: kyverno CLI not found - install it to run the parity contract test")
        return 0

    policy_files = sorted(glob.glob(os.path.join(REPO, "deploy", "policies", "*.yaml")))
    with open(FIXTURES) as fh:
        fixtures = [d for d in yaml.safe_load_all(fh) if d]

    corpus = [
        f
        for f in fixtures
        if f.get("kind") == "ManifestWork"
        and f.get("metadata", {}).get("labels", {}).get(LABEL) == "ocm-mcp-server"
    ]
    if len(corpus) < 10:
        print(f"ERROR: expected a labelled corpus of at least 10 fixtures, found {len(corpus)}")
        return 1

    mismatches = []
    for fixture in corpus:
        name = fixture["metadata"]["name"]
        manifests = fixture["spec"]["workload"]["manifests"]
        py_ok, py_why = python_verdict(manifests)
        kv_ok, kv_why = kyverno_verdict(policy_files, fixture)
        marker = "==" if py_ok == kv_ok else "!!"
        print(
            f"{marker} {name}: python={'pass' if py_ok else 'fail'} "
            f"kyverno={'pass' if kv_ok else 'fail'}"
        )
        if py_ok != kv_ok:
            mismatches.append((name, py_ok, py_why, kv_ok, kv_why))

    if mismatches:
        print(f"\nPARITY BROKEN: {len(mismatches)} fixture(s) got different verdicts:")
        for name, py_ok, py_why, kv_ok, kv_why in mismatches:
            print(f"- {name}: python {'pass' if py_ok else 'fail: ' + py_why}")
            print(f"           kyverno {'pass' if kv_ok else 'fail: ' + kv_why}")
        return 1
    print(f"\nPARITY OK: {len(corpus)} labelled fixtures, identical verdicts in both layers")
    return 0


if __name__ == "__main__":
    sys.exit(main())
