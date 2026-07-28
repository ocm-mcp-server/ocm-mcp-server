# SPDX-FileCopyrightText: 2026 Sandeep Bazar
# SPDX-License-Identifier: Apache-2.0

"""Server tool tests: the MCP tool entrypoints driven with the OCM API calls mocked, so
the gate (guardrails -> dry-run -> token -> apply) is exercised without a cluster."""

import json

import pytest
from kubernetes.client import ApiException

from ocm_mcp_server import approvals, guardrails, ocm
from ocm_mcp_server import server as srv
from ocm_mcp_server.config import SETTINGS

COMPLIANT = {
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


@pytest.fixture
def mocked_ocm(tmp_home, monkeypatch):
    """No-op the cluster-touching OCM calls so the flow runs offline."""
    monkeypatch.setattr(ocm, "dry_run_manifestwork", lambda cluster, body: {"status": "ok"})
    monkeypatch.setattr(
        ocm,
        "create_manifestwork",
        lambda cluster, body: {"metadata": {"uid": "uid-123", "name": body["metadata"]["name"]}},
    )
    monkeypatch.setattr(ocm, "delete_manifestwork", lambda cluster, name: {"status": "deleted"})
    monkeypatch.setattr(
        ocm,
        "get_manifestwork_object",
        lambda cluster, name: {
            "metadata": {
                "uid": "uid-123",
                "labels": {"app.kubernetes.io/managed-by": "ocm-mcp-server"},
            }
        },
    )
    return monkeypatch


# --------------------------------------------------------------------- read tools


def test_read_tool_returns_json(tmp_home, monkeypatch):
    monkeypatch.setattr(ocm, "list_managed_clusters", lambda: [{"name": "cluster1"}])
    out = json.loads(srv.list_clusters())
    assert out[0]["name"] == "cluster1"


def test_get_fleet_health(tmp_home, monkeypatch):
    monkeypatch.setattr(
        ocm,
        "fleet_health",
        lambda clusters="": {"fleet": {"total": 0}, "clusters": [], "got": clusters},
    )
    out = json.loads(srv.get_fleet_health(clusters="c1"))
    assert out["got"] == "c1"


def test_read_tool_unavailable_message(tmp_home, monkeypatch):
    def boom(*_a, **_k):
        raise ocm.FeatureNotInstalled("policy add-on not installed")

    monkeypatch.setattr(ocm, "list_policies", boom)
    assert srv.list_policies().startswith("UNAVAILABLE")


# --------------------------------------------------------------------- read-only backstop


def test_read_only_blocks_propose(tmp_home, monkeypatch):
    monkeypatch.setattr(SETTINGS, "read_only", True)
    out = srv.propose_manifestwork("cluster1", "x", "s", json.dumps([COMPLIANT]))
    assert out.startswith("REJECTED") and "read-only" in out


# --------------------------------------------------------------------- propose


def test_propose_rejects_bad_manifest(mocked_ocm):
    bad = {**COMPLIANT, "metadata": {"name": "x", "namespace": "kube-system"}}
    out = srv.propose_manifestwork("cluster1", "x", "s", json.dumps([bad]))
    assert out.startswith("REJECTED by static guardrails")


def test_propose_rejects_invalid_json(mocked_ocm):
    out = srv.propose_manifestwork("cluster1", "x", "s", "{not json")
    assert out.startswith("REJECTED") and "not valid JSON" in out


# --------------------------------------------------------------------- full apply flow


def _propose_and_token(cluster="cluster1", name="fix", op="apply"):
    out = json.loads(srv.propose_manifestwork(cluster, name, "s", json.dumps([COMPLIANT])))
    pid = out["proposal_id"]
    token = approvals.mint_token(approvals.load_proposal(pid), operation=op)
    return pid, token


def test_full_propose_approve_apply(mocked_ocm):
    pid, token = _propose_and_token()
    applied = json.loads(srv.apply_manifestwork(pid, token))
    assert applied["status"] == "applied"
    assert approvals.load_proposal(pid).status == "applied"


def test_apply_replay_refused(mocked_ocm):
    pid, token = _propose_and_token()
    srv.apply_manifestwork(pid, token)
    # Same token again -> the proposal is already applied (not pending).
    assert srv.apply_manifestwork(pid, token).startswith("REJECTED")


def test_apply_wrong_token_refused(mocked_ocm):
    pid, _ = _propose_and_token()
    assert srv.apply_manifestwork(pid, "garbage.token").startswith("REJECTED")


def test_rollback_flow(mocked_ocm):
    pid, token = _propose_and_token()
    srv.apply_manifestwork(pid, token)
    rb = json.loads(srv.propose_rollback(pid))
    rid = rb["rollback_proposal_id"]
    rtoken = approvals.mint_token(approvals.load_proposal(rid), operation="rollback")
    out = json.loads(srv.rollback_manifestwork(rid, rtoken))
    assert out["status"] == "rolled_back"
    assert approvals.load_proposal(pid).status == "rolled_back"


def test_rollback_requires_rollback_scoped_token(mocked_ocm):
    pid, token = _propose_and_token()
    srv.apply_manifestwork(pid, token)
    rb = json.loads(srv.propose_rollback(pid))
    rid = rb["rollback_proposal_id"]
    # An apply-scoped token cannot authorize a rollback.
    apply_token = approvals.mint_token(approvals.load_proposal(rid), operation="apply")
    assert srv.rollback_manifestwork(rid, apply_token).startswith("REJECTED")


# --------------------------------------------------------------------- lifecycle actions


def test_propose_action_rejects_unknown(mocked_ocm):
    out = srv.propose_cluster_action("cluster1", "nuke", "s")
    assert out.startswith("REJECTED") and "not an allowed action" in out


def test_set_label_requires_key(mocked_ocm):
    out = srv.propose_cluster_action("cluster1", "set_label", "s", "{}")
    assert out.startswith("REJECTED") and "set_label requires" in out


def test_full_cordon_action_flow(mocked_ocm):
    mocked_ocm.setattr(ocm, "validate_cluster_action", lambda c, a, p: None)
    mocked_ocm.setattr(
        ocm, "apply_cluster_action", lambda c, a, p: {"status": "cordoned", "cluster": c}
    )
    out = json.loads(srv.propose_cluster_action("cluster1", "cordon", "pull out of scheduling"))
    pid = out["proposal_id"]
    token = approvals.mint_token(approvals.load_proposal(pid), operation="apply")
    applied = json.loads(srv.apply_cluster_action(pid, token))
    assert applied["status"] == "cordoned"
    assert approvals.load_proposal(pid).status == "applied"


def test_apply_action_wrong_kind_refused(mocked_ocm):
    # A ManifestWork proposal id passed to apply_cluster_action must be refused.
    pid, token = _propose_and_token()
    assert srv.apply_cluster_action(pid, token).startswith("REJECTED")


# --------------------------------------------------------------------- all read tools + prompts


def test_all_read_tools_and_prompts(tmp_home, monkeypatch):
    # Point every ocm read at empty/benign returns; each tool must return a string.
    for fn in [
        "list_managed_clusters",
        "list_cluster_sets",
        "list_cluster_set_bindings",
        "list_cluster_claims",
        "list_placements",
        "list_addon_placement_scores",
        "list_manifestworks",
        "list_manifestworkreplicasets",
        "list_cluster_management_addons",
        "addon_health",
        "list_addons_for_cluster",
        "list_pending_csrs",
        "list_policies",
        "list_policy_violations",
        "list_hosted_clusters",
        "list_node_pools",
        "list_resources",
        "cluster_events",
    ]:
        monkeypatch.setattr(ocm, fn, lambda *a, **k: [])
    for fn in [
        "get_managed_cluster",
        "cluster_health",
        "get_manifestwork",
        "get_cluster_info",
        "get_placement_decision",
        "get_hosted_cluster",
        "get_resource",
    ]:
        monkeypatch.setattr(ocm, fn, lambda *a, **k: {"ok": True})
    monkeypatch.setattr(ocm, "pod_logs", lambda *a, **k: "some logs")

    reads = [
        srv.list_clusters(),
        srv.get_cluster("c1"),
        srv.list_cluster_sets(),
        srv.list_cluster_set_bindings(),
        srv.list_cluster_claims(),
        srv.get_cluster_info("c1"),
        srv.get_cluster_health("c1"),
        srv.query_events("c1"),
        srv.get_pod_logs("c1", "ns", "p"),
        srv.list_placements(),
        srv.get_placement_decision("p", "ns"),
        srv.list_addon_placement_scores("c1"),
        srv.list_manifestworks("c1"),
        srv.get_manifestwork("c1", "w"),
        srv.list_manifestworkreplicasets(),
        srv.list_cluster_management_addons(),
        srv.get_addon_health(),
        srv.list_addons_for_cluster("c1"),
        srv.list_pending_csrs(),
        srv.list_policies(),
        srv.list_policy_violations(),
        srv.list_hosted_clusters(),
        srv.get_hosted_cluster("h", "ns"),
        srv.list_node_pools(),
        srv.list_resources("managedclusters"),
        srv.get_resource("managedclusters", "c1"),
        srv.list_pending_proposals(),
        srv.get_audit_trail(),
    ]
    assert all(isinstance(r, str) for r in reads)

    prompts = [
        srv.diagnose_fleet(),
        srv.remediate_with_approval("payments down"),
        srv.incident_postmortem(),
        srv.why_not_scheduled("c1", "p", "ns"),
        srv.onboard_cluster("c1"),
        srv.addon_troubleshoot("search"),
        srv.hosted_cluster_health("c1"),
        srv.policy_compliance_report(),
        srv.capacity_report(),
        srv.rollout_status("r", "ns"),
    ]
    assert all(isinstance(p, str) and p for p in prompts)


def test_oversized_manifests_json_rejected(mocked_ocm):
    big = json.dumps([COMPLIANT]) + " " * (300 * 1024)  # pad past the 256 KiB limit
    out = srv.propose_manifestwork("cluster1", "x", "s", big)
    assert out.startswith("REJECTED") and "limit" in out


# --------------------------------------------------------------------- error branches


def _api_exc(body: str = "") -> ApiException:
    exc = ApiException(status=403, reason="Forbidden")
    exc.body = body
    return exc


def test_read_tool_api_error_message(tmp_home, monkeypatch):
    def boom(*_a, **_k):
        raise _api_exc('{"reason": "Forbidden", "message": "clusters is forbidden"}')

    monkeypatch.setattr(ocm, "list_managed_clusters", boom)
    out = srv.list_clusters()
    assert out.startswith("ERROR:") and "forbidden" in out


def test_pod_logs_unavailable_message(tmp_home, monkeypatch):
    def boom(*_a, **_k):
        raise LookupError("no spoke context configured for cluster1")

    monkeypatch.setattr(ocm, "pod_logs", boom)
    out = srv.get_pod_logs("cluster1", "ns", "p")
    assert out.startswith("UNAVAILABLE") and "no spoke context" in out


def test_pod_logs_api_error_message(tmp_home, monkeypatch):
    def boom(*_a, **_k):
        raise _api_exc("pods/log is forbidden")

    monkeypatch.setattr(ocm, "pod_logs", boom)
    out = srv.get_pod_logs("cluster1", "ns", "p")
    assert out.startswith("ERROR:") and "pods/log is forbidden" in out


def test_read_only_blocks_every_write_tool(tmp_home, monkeypatch):
    monkeypatch.setattr(SETTINGS, "read_only", True)
    outputs = [
        srv.apply_manifestwork("0" * 32, "token"),
        srv.propose_rollback("0" * 32),
        srv.rollback_manifestwork("0" * 32, "token"),
        srv.propose_cluster_action("cluster1", "cordon", "s"),
        srv.apply_cluster_action("0" * 32, "token"),
    ]
    for out in outputs:
        assert out.startswith("REJECTED") and "read-only" in out


# --------------------------------------------------------------------- propose branches


def test_propose_single_dict_manifest_is_wrapped(mocked_ocm):
    # A bare object (not an array) is accepted and normalized to a one-element list.
    out = json.loads(srv.propose_manifestwork("cluster1", "one", "s", json.dumps(COMPLIANT)))
    prop = approvals.load_proposal(out["proposal_id"])
    assert prop.manifests == [COMPLIANT]


def test_propose_rejected_by_hub_admission(mocked_ocm):
    def deny(cluster, body):
        raise _api_exc("kyverno: image must be pinned by digest")

    mocked_ocm.setattr(ocm, "dry_run_manifestwork", deny)
    out = srv.propose_manifestwork("cluster1", "x", "s", json.dumps([COMPLIANT]))
    assert out.startswith("REJECTED by hub admission") and "kyverno" in out
    assert approvals.list_proposals(status="pending") == []  # nothing was stored


# --------------------------------------------------------------------- apply branches


def test_apply_manifestwork_refuses_action_proposal(mocked_ocm):
    mocked_ocm.setattr(ocm, "validate_cluster_action", lambda c, a, p: None)
    pid = json.loads(srv.propose_cluster_action("cluster1", "cordon", "s"))["proposal_id"]
    token = approvals.mint_token(approvals.load_proposal(pid), operation="apply")
    out = srv.apply_manifestwork(pid, token)
    assert out.startswith("REJECTED") and "not a ManifestWork" in out


def test_apply_rejects_guardrail_violation_at_apply_time(mocked_ocm):
    pid, token = _propose_and_token()

    def boom(manifests):
        raise guardrails.GuardrailViolation("image is no longer pinned")

    mocked_ocm.setattr(guardrails, "validate_manifests", boom)
    out = srv.apply_manifestwork(pid, token)
    assert out.startswith("REJECTED by static guardrails at apply time")
    assert "image is no longer pinned" in out
    assert approvals.load_proposal(pid).status == "pending"


def test_apply_create_failure_reported_and_proposal_stays_pending(mocked_ocm):
    pid, token = _propose_and_token()

    def boom(cluster, body):
        raise _api_exc("admission webhook denied the request")

    mocked_ocm.setattr(ocm, "create_manifestwork", boom)
    out = srv.apply_manifestwork(pid, token)
    assert out.startswith("FAILED to create ManifestWork")
    assert "admission webhook denied" in out
    assert approvals.load_proposal(pid).status == "pending"


# --------------------------------------------------------------------- rollback branches


def _applied_and_rollback():
    """Propose + apply a ManifestWork, then propose its rollback. -> (origin_id, rollback_id)"""
    pid, token = _propose_and_token()
    srv.apply_manifestwork(pid, token)
    rid = json.loads(srv.propose_rollback(pid))["rollback_proposal_id"]
    return pid, rid


def _rollback_token(rid):
    return approvals.mint_token(approvals.load_proposal(rid), operation="rollback")


def test_propose_rollback_unknown_id(mocked_ocm):
    out = srv.propose_rollback("0" * 32)
    assert out.startswith("REJECTED") and "No proposal" in out


def test_propose_rollback_requires_applied_manifestwork(mocked_ocm):
    pid, _ = _propose_and_token()  # pending, never applied
    out = srv.propose_rollback(pid)
    assert out.startswith("REJECTED") and "not an applied ManifestWork" in out


def test_rollback_refuses_non_rollback_proposal(mocked_ocm):
    pid, token = _propose_and_token()
    out = srv.rollback_manifestwork(pid, token)
    assert out.startswith("REJECTED") and "not a rollback proposal" in out


def test_rollback_refuses_non_pending_rollback(mocked_ocm):
    _, rid = _applied_and_rollback()
    assert json.loads(srv.rollback_manifestwork(rid, _rollback_token(rid)))["status"] == (
        "rolled_back"
    )
    out = srv.rollback_manifestwork(rid, _rollback_token(rid))
    assert out.startswith("REJECTED") and "not pending" in out


def test_rollback_tampered_content_rejected(mocked_ocm):
    _, rid = _applied_and_rollback()
    prop = approvals.load_proposal(rid)
    prop.params["target_work"] = "some-other-work"  # tamper, keep the stored hash field
    prop.save()
    out = srv.rollback_manifestwork(rid, _rollback_token(rid))
    assert out.startswith("REJECTED") and "content hash" in out


def test_rollback_read_failure_reported(mocked_ocm):
    _, rid = _applied_and_rollback()

    def boom(cluster, name):
        raise _api_exc("manifestworks is forbidden")

    mocked_ocm.setattr(ocm, "get_manifestwork_object", boom)
    out = srv.rollback_manifestwork(rid, _rollback_token(rid))
    assert out.startswith("FAILED to read ManifestWork")


def test_rollback_refuses_unmanaged_manifestwork(mocked_ocm):
    _, rid = _applied_and_rollback()
    mocked_ocm.setattr(
        ocm,
        "get_manifestwork_object",
        lambda cluster, name: {"metadata": {"uid": "uid-123", "labels": {}}},
    )
    out = srv.rollback_manifestwork(rid, _rollback_token(rid))
    assert out.startswith("REJECTED") and "not managed by ocm-mcp-server" in out


def test_rollback_refuses_uid_change(mocked_ocm):
    _, rid = _applied_and_rollback()
    mocked_ocm.setattr(
        ocm,
        "get_manifestwork_object",
        lambda cluster, name: {
            "metadata": {
                "uid": "uid-999",  # recreated since approval
                "labels": {"app.kubernetes.io/managed-by": "ocm-mcp-server"},
            }
        },
    )
    out = srv.rollback_manifestwork(rid, _rollback_token(rid))
    assert out.startswith("REJECTED") and "UID changed" in out


def test_rollback_delete_failure_reported(mocked_ocm):
    _, rid = _applied_and_rollback()

    def boom(cluster, name):
        raise _api_exc("delete denied")

    mocked_ocm.setattr(ocm, "delete_manifestwork", boom)
    out = srv.rollback_manifestwork(rid, _rollback_token(rid))
    assert out.startswith("FAILED to delete ManifestWork")
    assert approvals.load_proposal(rid).status == "pending"


def test_rollback_succeeds_when_origin_proposal_missing(mocked_ocm):
    pid, rid = _applied_and_rollback()
    (SETTINGS.proposals_dir / f"{pid}.json").unlink()  # origin vanished; rollback still works
    out = json.loads(srv.rollback_manifestwork(rid, _rollback_token(rid)))
    assert out["status"] == "rolled_back"
    assert approvals.load_proposal(rid).status == "applied"


# --------------------------------------------------------------------- action branches


def _action_and_token(mocked_ocm, action="cordon", params_json="{}"):
    mocked_ocm.setattr(ocm, "validate_cluster_action", lambda c, a, p: None)
    pid = json.loads(srv.propose_cluster_action("cluster1", action, "s", params_json))[
        "proposal_id"
    ]
    return pid, approvals.mint_token(approvals.load_proposal(pid), operation="apply")


def test_propose_action_invalid_params_json(mocked_ocm):
    out = srv.propose_cluster_action("cluster1", "cordon", "s", "{nope")
    assert out.startswith("REJECTED") and "params_json is not valid JSON" in out


def test_addon_actions_require_addon_param(mocked_ocm):
    for action in ("enable_addon", "disable_addon"):
        out = srv.propose_cluster_action("cluster1", action, "s", "{}")
        assert out.startswith("REJECTED") and '{"addon"' in out


def test_accept_captures_pending_csrs_at_propose_time(mocked_ocm):
    csrs = [{"name": "csr-1", "request_sha256": "abc123"}]
    mocked_ocm.setattr(ocm, "validate_cluster_action", lambda c, a, p: None)
    mocked_ocm.setattr(ocm, "pending_csr_identities", lambda c: csrs)
    out = json.loads(srv.propose_cluster_action("cluster1", "accept", "join cluster1"))
    prop = approvals.load_proposal(out["proposal_id"])
    assert prop.params["csrs"] == csrs  # apply will approve exactly these, not "whatever pends"


def test_propose_action_hub_admission_reject(mocked_ocm):
    def deny(cluster, action, params):
        raise _api_exc("denied by validating webhook")

    mocked_ocm.setattr(ocm, "validate_cluster_action", deny)
    out = srv.propose_cluster_action("cluster1", "cordon", "s")
    assert out.startswith("REJECTED by hub admission") and "webhook" in out


def test_propose_action_validation_error(mocked_ocm):
    def boom(cluster, action, params):
        raise ValueError("cluster does not exist")

    mocked_ocm.setattr(ocm, "validate_cluster_action", boom)
    out = srv.propose_cluster_action("cluster1", "cordon", "s")
    assert out == "REJECTED: cluster does not exist"


def test_apply_action_refuses_non_pending(mocked_ocm):
    pid, token = _action_and_token(mocked_ocm)
    mocked_ocm.setattr(ocm, "apply_cluster_action", lambda c, a, p: {"status": "applied"})
    srv.apply_cluster_action(pid, token)
    again = approvals.mint_token(approvals.load_proposal(pid), operation="apply")
    out = srv.apply_cluster_action(pid, again)
    assert out.startswith("REJECTED") and "not pending" in out


def test_apply_action_tampered_params_rejected(mocked_ocm):
    pid, token = _action_and_token(mocked_ocm)
    prop = approvals.load_proposal(pid)
    prop.params["extra"] = "smuggled"  # tamper, keep the stored hash field
    prop.save()
    out = srv.apply_cluster_action(pid, token)
    assert out.startswith("REJECTED") and "content hash" in out


def test_apply_action_failure_reported_and_stays_pending(mocked_ocm):
    pid, token = _action_and_token(mocked_ocm)

    def boom(cluster, action, params):
        raise _api_exc("patch denied")

    mocked_ocm.setattr(ocm, "apply_cluster_action", boom)
    out = srv.apply_cluster_action(pid, token)
    assert out.startswith("FAILED to apply action") and "patch denied" in out
    assert approvals.load_proposal(pid).status == "pending"


def test_apply_action_malformed_token_rejected(mocked_ocm):
    pid, _ = _action_and_token(mocked_ocm)
    out = srv.apply_cluster_action(pid, "garbage.token")
    assert out.startswith("REJECTED") and "token" in out
    assert approvals.load_proposal(pid).status == "pending"


# --------------------------------------------------------------------- audit + main


def test_audit_trail_empty_when_log_missing(tmp_home, monkeypatch):
    missing = tmp_home / "no-audit.jsonl"
    # Bypass the Settings.audit_log property (which touches the file into existence).
    monkeypatch.setattr(type(SETTINGS), "audit_log", property(lambda self: missing))
    assert srv.get_audit_trail() == "[]"


def test_main_starts_metrics_when_port_set(tmp_home, monkeypatch):
    from ocm_mcp_server import metrics

    calls = {}
    monkeypatch.setenv("OCM_MCP_METRICS_PORT", "9109")
    monkeypatch.setattr(srv.mcp, "run", lambda: calls.setdefault("run", True))
    monkeypatch.setattr(
        metrics, "start_metrics_server", lambda port: calls.setdefault("port", port)
    )
    srv.main()
    assert calls == {"port": 9109, "run": True}


def test_main_skips_metrics_without_port(tmp_home, monkeypatch):
    calls = {}
    monkeypatch.delenv("OCM_MCP_METRICS_PORT", raising=False)
    monkeypatch.setattr(srv.mcp, "run", lambda: calls.setdefault("run", True))
    srv.main()
    assert calls == {"run": True}


def test_main_warns_when_private_signer_key_present(tmp_home, monkeypatch, capsys):
    monkeypatch.delenv("OCM_MCP_SIGNER_KEY", raising=False)
    monkeypatch.setattr(srv.mcp, "run", lambda: None)
    SETTINGS.approval_private_key_path.write_text("fake-private-key")

    srv.main()

    err = capsys.readouterr().err
    assert "PRIVATE key" in err
    assert "OCM_MCP_SIGNER_KEY" in err


def test_main_no_signer_warning_when_key_absent(tmp_home, monkeypatch, capsys):
    monkeypatch.delenv("OCM_MCP_SIGNER_KEY", raising=False)
    monkeypatch.setattr(srv.mcp, "run", lambda: None)
    assert not SETTINGS.approval_private_key_path.exists()

    srv.main()

    err = capsys.readouterr().err
    assert "PRIVATE key" not in err


def test_main_warns_when_issuer_and_audience_are_defaults(tmp_home, monkeypatch, capsys):
    monkeypatch.setattr(SETTINGS, "issuer", "ocm-mcp", raising=False)
    monkeypatch.setattr(SETTINGS, "audience", "ocm-mcp-server", raising=False)
    monkeypatch.setattr(srv.mcp, "run", lambda: None)

    srv.main()

    err = capsys.readouterr().err
    assert "OCM_MCP_ISSUER" in err
    assert "OCM_MCP_AUDIENCE" in err


def test_main_no_issuer_warning_when_customized(tmp_home, monkeypatch, capsys):
    monkeypatch.setattr(SETTINGS, "issuer", "my-org-hub", raising=False)
    monkeypatch.setattr(SETTINGS, "audience", "ocm-mcp-server", raising=False)
    monkeypatch.setattr(srv.mcp, "run", lambda: None)

    srv.main()

    err = capsys.readouterr().err
    assert "OCM_MCP_ISSUER" not in err
