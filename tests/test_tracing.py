# SPDX-FileCopyrightText: 2026 Sandeep Bazar
# SPDX-License-Identifier: Apache-2.0

"""Tracing/audit outcome classification and the tool wrapper."""

import json

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


def test_audit_echo_to_stderr_redacts_free_form_payload(tmp_home, monkeypatch, capsys):
    monkeypatch.setattr(SETTINGS, "audit_echo_stderr", True, raising=False)
    tracing.audit(
        {
            "tool": "propose_manifestwork",
            "args": {
                "cluster": "cluster1",
                "name": "payments",
                "summary": "bump the image tag",
                "manifests_json": '{"kind": "Deployment", "secret": "sh"}',
            },
            "outcome": "ok",
            "error": "some traceback with sensitive detail",
        }
    )
    err = capsys.readouterr().err
    rec = json.loads(err.strip().splitlines()[-1])
    # Structural/identity fields survive untouched.
    assert rec["tool"] == "propose_manifestwork"
    assert rec["outcome"] == "ok"
    assert rec["args"]["cluster"] == "cluster1"
    assert rec["args"]["name"] == "payments"
    # Free-form payload is redacted, in both args and top-level error text.
    assert rec["args"]["summary"] == "[redacted]"
    assert rec["args"]["manifests_json"] == "[redacted]"
    assert rec["error"] == "[redacted]"
    # The audit FILE keeps full fidelity - only the stderr echo is redacted.
    file_rec = json.loads(SETTINGS.audit_log.read_text().strip().splitlines()[-1])
    assert file_rec["args"]["summary"] == "bump the image tag"
    assert file_rec["args"]["manifests_json"] == '{"kind": "Deployment", "secret": "sh"}'
    assert file_rec["error"] == "some traceback with sensitive detail"


def test_echo_safe_is_a_pure_helper():
    entry = {
        "ts": 1.0,
        "seq": 1,
        "prev": "",
        "hash": "abc",
        "actor": "user:123",
        "tool": "apply_cluster_action",
        "outcome": "ok",
        "duration_ms": 12,
        "args": {"proposal_id": "p-1", "operation": "cordon", "reason": "draining for upgrade"},
        "error": "",
    }
    safe = tracing._echo_safe(entry)
    assert safe["args"]["proposal_id"] == "p-1"
    assert safe["args"]["operation"] == "cordon"
    assert safe["args"]["reason"] == "[redacted]"
    # An empty error stays empty rather than being masked as "[redacted]".
    assert safe["error"] == ""
    # The input entry itself is untouched.
    assert entry["args"]["reason"] == "draining for upgrade"


def test_echo_safe_redacts_unrecognized_top_level_field():
    # Any top-level field outside the allowlist (and not "args"/"error") is a
    # defensive default: redact it rather than assume it is safe to forward.
    safe = tracing._echo_safe({"tool": "sample", "some_future_field": "unexpected-detail"})
    assert safe["some_future_field"] == "[redacted]"
