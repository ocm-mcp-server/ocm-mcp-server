# SPDX-FileCopyrightText: 2026 Sandeep Bazar
# SPDX-License-Identifier: Apache-2.0

"""Atheris fuzz target for the static guardrail layer.

Scorecard detects this file via the `import atheris` pattern and credits the
project under the Fuzzing check. The target exercises validate_manifests with
arbitrary byte sequences, verifying that the parser never crashes (raises
anything other than GuardrailViolation or ValueError), no matter what the
fuzzer feeds it.

Run locally:
    pip install atheris
    python fuzz/fuzz_guardrails.py          # a few seconds of warm-up
    python fuzz/fuzz_guardrails.py -runs=0  # parse check only, exits cleanly

In CI (ClusterFuzzLite or OSS-Fuzz) the binary is invoked with a corpus
and a time limit; the exit code distinguishes clean runs from crashes.
"""

from __future__ import annotations

import json
import sys

import atheris

with atheris.instrument_imports():
    from ocm_mcp_server.guardrails import GuardrailViolation, validate_manifests


def _fuzz_one(data: bytes) -> None:
    """Feed arbitrary bytes to validate_manifests.

    Three legal outcomes:
    1. validate_manifests returns None  — the manifest is well-formed and passes all guardrails.
    2. GuardrailViolation is raised     — expected: malformed or disallowed content.
    3. ValueError / json.JSONDecodeError — expected: the input is not valid JSON at all.

    Any other exception (AttributeError, KeyError, …) is a bug in the parser
    and will be treated as a crash by the fuzzer.
    """
    fdp = atheris.FuzzedDataProvider(data)

    # Generate between 1 and 5 manifests as JSON objects
    try:
        raw = fdp.ConsumeString(len(data))
        manifests = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return  # not valid JSON — skip

    try:
        validate_manifests(manifests)
    except (GuardrailViolation, ValueError):
        pass  # both are expected and safe
    # Any other exception propagates and is caught by atheris as a crash


def main() -> None:
    atheris.Setup(sys.argv, _fuzz_one)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
