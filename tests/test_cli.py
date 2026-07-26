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


# --------------------------------------------------------------------- doctor + dispatch


def test_doctor_all_ok(tmp_home, monkeypatch, capsys):
    from ocm_mcp_server import ocm

    monkeypatch.setattr(ocm, "list_managed_clusters", lambda: [{"name": "c1"}])
    read_fns = [
        "list_cluster_sets",
        "list_cluster_set_bindings",
        "list_cluster_claims",
        "list_placements",
        "list_manifestworkreplicasets",
        "list_cluster_management_addons",
        "addon_health",
        "list_pending_csrs",
        "list_policies",
        "list_policy_violations",
        "list_hosted_clusters",
        "list_node_pools",
    ]
    for fn in read_fns:
        monkeypatch.setattr(ocm, fn, lambda *a, **k: [{"name": "x"}])
    monkeypatch.setattr(ocm, "get_managed_cluster", lambda c: {"name": c})
    monkeypatch.setattr(ocm, "cluster_health", lambda c: {"cluster": c})
    monkeypatch.setattr(ocm, "list_manifestworks", lambda c: [{"name": "w"}])
    monkeypatch.setattr(ocm, "list_addon_placement_scores", lambda c: [{"name": "s"}])
    monkeypatch.setattr(ocm, "get_cluster_info", lambda c: {"name": c})
    monkeypatch.setattr(ocm, "list_addons_for_cluster", lambda c: [{"name": "a"}])
    assert cli.cmd_doctor(ns()) == 0
    assert "doctor" in capsys.readouterr().out


def test_doctor_reports_fail(tmp_home, monkeypatch, capsys):
    from ocm_mcp_server import ocm

    def boom():
        raise RuntimeError("hub unreachable")

    monkeypatch.setattr(ocm, "list_managed_clusters", boom)
    for fn in (
        "list_cluster_sets",
        "list_cluster_set_bindings",
        "list_cluster_claims",
        "list_placements",
        "list_manifestworkreplicasets",
        "list_cluster_management_addons",
        "addon_health",
        "list_pending_csrs",
        "list_policies",
        "list_policy_violations",
        "list_hosted_clusters",
    ):
        monkeypatch.setattr(ocm, fn, lambda *a, **k: [])
    assert cli.cmd_doctor(ns()) == 1  # a FAIL -> non-zero exit


def _run_main(monkeypatch, argv):
    import sys

    monkeypatch.setattr(sys, "argv", ["ocm-mcp", *argv])
    try:
        cli.main()
    except SystemExit as e:
        return e.code
    return 0


def test_main_pending(tmp_home, monkeypatch, capsys):
    assert _run_main(monkeypatch, ["pending"]) == 0


def test_main_show_and_approve(tmp_home, monkeypatch, capsys):
    p = make(tmp_home)
    assert _run_main(monkeypatch, ["show", p.id]) == 0
    assert _run_main(monkeypatch, ["approve", p.id, "-y"]) == 0


def test_main_reject(tmp_home, monkeypatch, capsys):
    p = make(tmp_home)
    assert _run_main(monkeypatch, ["reject", p.id]) == 0
