# SPDX-FileCopyrightText: 2026 Sandeep Bazar
# SPDX-License-Identifier: Apache-2.0

"""Tracing/audit outcome classification and the tool wrapper."""

import pytest

from ocm_mcp_server import tracing
from ocm_mcp_server.config import SETTINGS


@pytest.mark.parametrize(
    "result,expected",
    [
        ("REJECTED: nope", "rejected"),
        ("FAILED to apply", "failed"),
        ("ERROR: boom", "error"),
        ("UNAVAILABLE: add-on", "unavailable"),
        ('{"status": "applied"}', "ok"),
        (123, "ok"),
    ],
)
def test_classify_outcome(result, expected):
    assert tracing.classify_outcome(result) == expected


def test_no_otel_endpoint_disables_tracer(monkeypatch):
    monkeypatch.setattr(SETTINGS, "otel_endpoint", "", raising=False)
    tracing._tracer = None
    assert tracing._get_tracer() is False


def test_traced_tool_audits_and_classifies(tmp_home):
    @tracing.traced_tool
    def sample(x):
        return "REJECTED: bad token"

    assert sample(x="approval_token") == "REJECTED: bad token"
    last = SETTINGS.audit_log.read_text().strip().splitlines()[-1]
    import json

    rec = json.loads(last)
    assert rec["tool"] == "sample" and rec["outcome"] == "rejected"


def test_traced_tool_records_exception_outcome(tmp_home):
    @tracing.traced_tool
    def boom():
        raise ValueError("kaboom")

    with pytest.raises(ValueError):
        boom()
    rec = SETTINGS.audit_log.read_text().strip().splitlines()[-1]
    assert '"outcome": "error"' in rec


def test_audit_echo_to_stderr(tmp_home, monkeypatch, capsys):
    monkeypatch.setattr(SETTINGS, "audit_echo_stderr", True, raising=False)
    tracing.audit({"tool": "list_clusters", "outcome": "ok"})
    err = capsys.readouterr().err
    assert '"tool": "list_clusters"' in err
