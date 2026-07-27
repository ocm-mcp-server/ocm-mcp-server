# SPDX-FileCopyrightText: 2026 Sandeep Bazar
# SPDX-License-Identifier: Apache-2.0

"""CLI coverage tests: interactive prompts, error exits, and rarely hit branches."""

import argparse
import builtins
import types

from ocm_mcp_server import approvals, cli

from .test_cli import MANIFEST


def ns(**kw):
    return argparse.Namespace(**kw)


def make(tmp_home):
    return approvals.new_proposal("c1", "fix", "add a marker", [MANIFEST])


def make_action(tmp_home):
    return approvals.new_action_proposal("c1", "cordon", "drain for maintenance", {"node": "n1"})


# --------------------------------------------------------------------- show (action kind)


def test_show_action_proposal_prints_action_and_params(tmp_home, capsys):
    p = make_action(tmp_home)
    assert cli.cmd_show(ns(id=p.id)) == 0
    out = capsys.readouterr().out
    assert "action:   cordon" in out
    assert '"node"' in out and "manifests" not in out


# --------------------------------------------------------------------- approve (interactive)


def test_approve_interactive_declined(tmp_home, monkeypatch, capsys):
    p = make(tmp_home)
    monkeypatch.setattr(builtins, "input", lambda _prompt: "n")
    assert cli.cmd_approve(ns(id=p.id, yes=False)) == 1
    out = capsys.readouterr().out
    assert "About to approve" in out and "Not approved." in out


def test_approve_interactive_confirmed_mints_token(tmp_home, monkeypatch, capsys):
    p = make(tmp_home)
    monkeypatch.setattr(builtins, "input", lambda _prompt: "y")
    assert cli.cmd_approve(ns(id=p.id, yes=False)) == 0
    token = capsys.readouterr().out.strip().splitlines()[-1]
    approvals.verify_token(p, token, operation="apply")


# --------------------------------------------------------------------- reject (non-pending)


def test_reject_refuses_non_pending(tmp_home, capsys):
    p = make(tmp_home)
    p.set_status("applied")
    assert cli.cmd_reject(ns(id=p.id)) == 1
    assert "not pending" in capsys.readouterr().err


# --------------------------------------------------------------------- audit (no log yet)


def test_audit_without_log_file(tmp_home, monkeypatch, capsys):
    # SETTINGS.audit_log auto-touches the file, so point the CLI at a path
    # that genuinely does not exist to reach the "no log yet" early exit.
    fake = types.SimpleNamespace(audit_log=tmp_home / "missing" / "audit.jsonl")
    monkeypatch.setattr(cli, "SETTINGS", fake)
    assert cli.cmd_audit(ns(n=20)) == 0
    assert "No audit log yet." in capsys.readouterr().out


# --------------------------------------------------------------------- rotate-secret (interactive)


def test_rotate_secret_interactive_declined(tmp_home, monkeypatch, capsys):
    monkeypatch.setattr(builtins, "input", lambda _prompt: "n")
    assert cli.cmd_rotate_secret(ns(yes=False)) == 1
    out = capsys.readouterr().out
    assert "invalidates ALL" in out and "Not rotated." in out


def test_rotate_secret_interactive_confirmed(tmp_home, monkeypatch, capsys):
    monkeypatch.setattr(builtins, "input", lambda _prompt: "y")
    assert cli.cmd_rotate_secret(ns(yes=False)) == 0
    assert "Rotated." in capsys.readouterr().out


# --------------------------------------------------------------------- doctor branches

HUB_READ_FNS = (
    "list_cluster_sets",
    "list_cluster_set_bindings",
    "list_cluster_claims",
    "list_placements",
    "list_manifestworkreplicasets",
    "list_cluster_management_addons",
    "addon_health",
    "list_pending_csrs",
    "list_policies",
)


def _stub_hub_reads(ocm, monkeypatch):
    for fn in HUB_READ_FNS:
        monkeypatch.setattr(ocm, fn, lambda *a, **k: [{"name": "x"}])


def test_doctor_reports_skip_on_lookup_error(tmp_home, monkeypatch, capsys):
    from ocm_mcp_server import ocm

    _stub_hub_reads(ocm, monkeypatch)
    monkeypatch.setattr(ocm, "list_managed_clusters", list)

    def no_spoke(*a, **k):
        raise LookupError("no spoke context configured")

    monkeypatch.setattr(ocm, "list_pending_csrs", no_spoke)
    for fn in ("list_hosted_clusters", "list_policy_violations"):
        if hasattr(ocm, fn):
            monkeypatch.setattr(ocm, fn, lambda *a, **k: [])
    assert cli.cmd_doctor(ns()) == 0  # SKIP is not a failure
    out = capsys.readouterr().out
    assert "[SKIP]" in out and "1 skipped" in out


def test_doctor_without_optional_hub_and_cluster_attrs(tmp_home, monkeypatch, capsys):
    from ocm_mcp_server import ocm

    _stub_hub_reads(ocm, monkeypatch)
    monkeypatch.setattr(ocm, "list_managed_clusters", lambda: [{"name": "c1"}])
    monkeypatch.setattr(ocm, "get_managed_cluster", lambda c: {"name": c})
    monkeypatch.setattr(ocm, "cluster_health", lambda c: {"cluster": c})
    monkeypatch.setattr(ocm, "list_manifestworks", lambda c: [{"name": "w"}])
    monkeypatch.setattr(ocm, "list_addon_placement_scores", lambda c: [{"name": "s"}])
    for optional in (
        "list_hosted_clusters",
        "list_policy_violations",
        "get_cluster_info",
        "list_addons_for_cluster",
    ):
        monkeypatch.delattr(ocm, optional, raising=False)
    assert cli.cmd_doctor(ns()) == 0
    out = capsys.readouterr().out
    assert "list_hosted_clusters" not in out
    assert "list_policy_violations" not in out
    assert "get_cluster_info" not in out
    assert "list_addons_for_cluster" not in out


def test_doctor_with_only_hosted_clusters_optional(tmp_home, monkeypatch, capsys):
    from ocm_mcp_server import ocm

    _stub_hub_reads(ocm, monkeypatch)
    monkeypatch.setattr(ocm, "list_managed_clusters", lambda: [{"name": "c1"}])
    monkeypatch.setattr(ocm, "get_managed_cluster", lambda c: {"name": c})
    monkeypatch.setattr(ocm, "cluster_health", lambda c: {"cluster": c})
    monkeypatch.setattr(ocm, "list_manifestworks", lambda c: [{"name": "w"}])
    monkeypatch.setattr(ocm, "list_addon_placement_scores", lambda c: [{"name": "s"}])
    monkeypatch.setattr(ocm, "list_hosted_clusters", lambda: [{"name": "h"}], raising=False)
    monkeypatch.setattr(ocm, "get_cluster_info", lambda c: {"name": c}, raising=False)
    for optional in ("list_policy_violations", "list_addons_for_cluster"):
        monkeypatch.delattr(ocm, optional, raising=False)
    assert cli.cmd_doctor(ns()) == 0
    out = capsys.readouterr().out
    assert "list_hosted_clusters" in out and "list_policy_violations" not in out
    assert "get_cluster_info" in out and "list_addons_for_cluster" not in out


# --------------------------------------------------------------------- _detail formatting


def test_detail_dict_without_known_keys():
    assert cli._detail({"a": 1, "b": 2, "c": 3}) == "3 field(s)"


def test_detail_scalar_is_truncated_str():
    assert cli._detail(42) == "42"
    assert cli._detail("x" * 100) == "x" * 60
