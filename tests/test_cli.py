# SPDX-FileCopyrightText: 2026 Sandeep Bazar
# SPDX-License-Identifier: Apache-2.0

"""CLI tests: the human approval side. No cluster required."""

import argparse

import pytest

from ocm_mcp_server import approvals, cli, tracing

MANIFEST = {
    "apiVersion": "apps/v1",
    "kind": "Deployment",
    "metadata": {"name": "payments", "namespace": "shop"},
    "spec": {
        "template": {
            "spec": {
                "automountServiceAccountToken": False,
                "containers": [
                    {
                        "name": "c",
                        "image": "reg/app:1.2.3",
                        "securityContext": {
                            "runAsNonRoot": True,
                            "allowPrivilegeEscalation": False,
                            "seccompProfile": {"type": "RuntimeDefault"},
                            "capabilities": {"drop": ["ALL"]},
                        },
                    }
                ],
            }
        }
    },
}


def ns(**kw):
    return argparse.Namespace(**kw)


def make(tmp_home):
    return approvals.new_proposal("c1", "fix", "add a marker", [MANIFEST])


def test_pending_lists_proposal(tmp_home, capsys):
    p = make(tmp_home)
    assert cli.cmd_pending(ns()) == 0
    assert p.id in capsys.readouterr().out


def test_pending_empty(tmp_home, capsys):
    assert cli.cmd_pending(ns()) == 0
    assert "No pending" in capsys.readouterr().out


def test_show(tmp_home, capsys):
    p = make(tmp_home)
    assert cli.cmd_show(ns(id=p.id)) == 0
    out = capsys.readouterr().out
    assert p.cluster in out and "manifests" in out


def test_approve_yes_mints_verifiable_token(tmp_home, capsys):
    p = make(tmp_home)
    assert cli.cmd_approve(ns(id=p.id, yes=True)) == 0
    token = capsys.readouterr().out.strip().splitlines()[-1]
    # The minted token verifies for this exact proposal and apply operation.
    approvals.verify_token(p, token, operation="apply")


def test_approve_refuses_non_pending(tmp_home, capsys):
    p = make(tmp_home)
    p.set_status("applied")
    assert cli.cmd_approve(ns(id=p.id, yes=True)) == 1


def test_reject_transitions_and_blocks_reapproval(tmp_home, capsys):
    p = make(tmp_home)
    assert cli.cmd_reject(ns(id=p.id)) == 0
    assert approvals.load_proposal(p.id).status == "rejected"
    # A rejected proposal cannot be approved.
    assert cli.cmd_approve(ns(id=p.id, yes=True)) == 1


def test_audit_tail(tmp_home, capsys):
    tracing.audit({"tool": "list_clusters", "outcome": "ok", "duration_ms": 3})
    assert cli.cmd_audit(ns(n=10)) == 0
    assert "list_clusters" in capsys.readouterr().out


def test_audit_verify_ok_then_tamper(tmp_home, capsys):
    tracing.audit({"tool": "a", "outcome": "ok"})
    assert cli.cmd_audit_verify(ns()) == 0
    log = tracing.SETTINGS.audit_log
    log.write_text(log.read_text().replace('"ok"', '"rejected"'))
    assert cli.cmd_audit_verify(ns()) == 1


def test_rotate_secret_invalidates_tokens(tmp_home, capsys):
    p = make(tmp_home)
    token = approvals.mint_token(p, operation="apply")
    approvals.verify_token(p, token, operation="apply")  # valid before rotation
    assert cli.cmd_rotate_secret(ns(yes=True)) == 0
    with pytest.raises(approvals.ApprovalError):
        approvals.verify_token(p, token, operation="apply")
