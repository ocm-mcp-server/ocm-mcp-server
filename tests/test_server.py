# SPDX-FileCopyrightText: 2026 Sandeep Bazar
# SPDX-License-Identifier: Apache-2.0

"""Server tool tests: the MCP tool entrypoints driven with the OCM API calls mocked, so
the gate (guardrails -> dry-run -> token -> apply) is exercised without a cluster."""

import json

import pytest

from ocm_mcp_server import approvals, ocm
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
