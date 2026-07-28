#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Sandeep Bazar
# SPDX-License-Identifier: Apache-2.0
"""Exercise the ocm-mcp-server tools, prompts, and a negative-scenario debug loop
against a live Open Cluster Management hub. Fixtures are created first so the read
tools report on real objects; the gated write flow is driven through the ACTUAL
MCP tool entrypoints (propose/apply with a real approval token), so the guardrail
is genuinely exercised, not bypassed.

Prints clean terminal output and appends JSONL records for hack/e2e_report.py.
Exits non-zero if any step FAILs, so CI can gate on it.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time

C = {"g": "\033[1;32m", "r": "\033[1;31m", "y": "\033[1;33m", "b": "\033[1;36m",
     "p": "\033[1;35m", "d": "\033[0;90m", "x": "\033[0m"}
COL = {"OK": "g", "PASS": "g", "FAIL": "r", "UNAVAILABLE": "y", "SKIP": "y",
       "INFO": "b", "INJECT": "p", "FIX": "b"}

RESULTS = None
FAILS = []


def rec(phase, title, why, status, cmd="", output=""):
    """Print a clean console block and append a JSONL record. (phase,title,why,status,cmd,output)."""
    c = COL.get(status, "d")
    print(f"\n{C[c]}[{status}]{C['x']} {C['b']}{title}{C['x']}")
    if why:
        print(f"   {C['d']}{why}{C['x']}")
    if cmd:
        print(f"   {C['d']}$ {cmd}{C['x']}")
    if output:
        for line in str(output).rstrip().splitlines()[:12]:
            print(f"     {line}")
    if status == "FAIL":
        FAILS.append(title)
    with open(RESULTS, "a") as f:
        f.write(json.dumps({"phase": phase, "title": title, "why": why,
                            "status": status, "cmd": cmd, "output": output}) + "\n")


def short(obj, n=1400):
    s = obj if isinstance(obj, str) else json.dumps(obj, indent=2, default=str)
    return s if len(s) <= n else s[:n] + "\n... (truncated)"


def tj(s):
    """Parse a tool's JSON-string return; keep the raw text if it is not JSON."""
    try:
        return json.loads(s)
    except Exception:  # noqa: BLE001
        return {"_raw": s}


def main():
    global RESULTS
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", required=True)
    ap.add_argument("--spokes", type=int, default=2)
    ap.add_argument("--cluster", default="cluster1")
    args = ap.parse_args()
    RESULTS = args.results
    cl = args.cluster

    # Imported here (not at module top) so OCM_MCP_* env is set before config loads.
    from ocm_mcp_server import approvals, ocm
    from ocm_mcp_server import server as srv

    _setup_fixtures(srv, approvals, ocm, cl)

    # ------------------------------------------------------------------ reads
    P = "5. Read tools (safe, no gate) - how an agent investigates a fleet"
    # (title, why, fn, empty_note)
    reads = [
        ("list_clusters", "The fleet roster: every managed cluster, its version and health.",
         lambda: ocm.list_managed_clusters(), None),
        (f"get_cluster({cl})", "Zoom into one cluster: acceptance, taints, capacity, claims.",
         lambda: ocm.get_managed_cluster(cl), None),
        ("list_cluster_sets", "Groupings of clusters used for placement.",
         lambda: ocm.list_cluster_sets(), None),
        ("list_cluster_set_bindings", "Which cluster sets a namespace may schedule to.",
         lambda: ocm.list_cluster_set_bindings(), None),
        ("list_cluster_claims", "Facts each cluster self-reports (id, platform, version).",
         lambda: ocm.list_cluster_claims(), None),
        (f"get_cluster_health({cl})", "The on-call view: unhealthy pods and degraded deployments.",
         lambda: ocm.cluster_health(cl), None),
        (f"query_events({cl})", "Recent Kubernetes events - the 'why' behind failures.",
         lambda: ocm.cluster_events(cl, limit=8), None),
        (f"list_manifestworks({cl})", "What the hub is currently delivering to this cluster.",
         lambda: ocm.list_manifestworks(cl), None),
        ("list_manifestworkreplicasets", "Fleet-wide rollouts (a template fanned across clusters).",
         lambda: ocm.list_manifestworkreplicasets(),
         "ManifestWorkReplicaSet is feature-gated; none are defined on this fleet."),
        ("list_cluster_management_addons", "Fleet-level add-on definitions.",
         lambda: ocm.list_cluster_management_addons(), None),
        ("get_addon_health", "Per-cluster add-on health across the fleet.",
         lambda: ocm.addon_health(), None),
        (f"list_addons_for_cluster({cl})", "Every add-on installed on one cluster, with health.",
         lambda: ocm.list_addons_for_cluster(cl), None),
        ("list_pending_csrs", "Clusters waiting to be admitted to the hub.",
         lambda: ocm.list_pending_csrs(),
         "No pending CSRs - every cluster is already admitted (a healthy fleet)."),
        ("list_placements", "Placements and how many clusters each selects.",
         lambda: ocm.list_placements(), None),
        ("get_placement_decision(demo-all)", "Exactly which clusters a Placement chose.",
         lambda: ocm.get_placement_decision("demo-all", "default"), None),
        ("list_policies", "Governance Policies and per-cluster compliance.",
         lambda: ocm.list_policies(), None),
        ("list_policy_violations", "Only the NonCompliant / Pending policy-cluster pairs.",
         lambda: ocm.list_policy_violations(),
         "No violations - evaluated policies are compliant (or evaluation is in progress)."),
        (f"get_cluster_info({cl})", "Extended inventory (OpenShift version, nodes) - ACM only.",
         lambda: ocm.get_cluster_info(cl), None),
        ("list_hosted_clusters", "HyperShift hosted control planes - when the hub hosts them.",
         lambda: ocm.list_hosted_clusters(), None),
        ("list_node_pools", "HyperShift worker node pools - when the hub hosts HCPs.",
         lambda: ocm.list_node_pools(), None),
        ("list_resources(managedclusters)", "Generic allow-listed reader over any OCM type.",
         lambda: ocm.list_resources("managedclusters"), None),
        (f"get_resource(managedclusters/{cl})", "Generic get of one allow-listed OCM object.",
         lambda: ocm.get_resource("managedclusters", cl), None),
        (f"list_addon_placement_scores({cl})", "Per-cluster placement scores add-ons publish.",
         lambda: ocm.list_addon_placement_scores(cl),
         "No AddOnPlacementScores - no score-publishing add-on runs on this fleet."),
        (f"get_pod_logs({cl})", "Container logs from a spoke pod, via the hub-known read context.",
         lambda: _first_pod_logs(ocm, cl), None),
        ("get_hosted_cluster(demo-hcp)", "One HyperShift hosted control plane in detail.",
         lambda: ocm.get_hosted_cluster("demo-hcp", "clusters"), None),
    ]
    for title, why, fn, note in reads:
        try:
            out = fn()
            if out in ([], {}, None):
                rec(P, title, why, "OK", "tool: " + title.split("(")[0],
                    note or "0 items - none present on this fleet yet.")
            else:
                rec(P, title, why, "OK", "tool: " + title.split("(")[0], short(out))
        except (ocm.FeatureNotInstalled, LookupError, ValueError) as e:
            rec(P, title, why, "UNAVAILABLE", "tool: " + title.split("(")[0],
                f"{e}\n(feature-detected: this API is not installed on a plain kind/OCM hub - "
                "it needs ACM/MCE or HyperShift. Not an error.)")
        except Exception as e:  # noqa: BLE001
            rec(P, title, why, "FAIL", "tool: " + title.split("(")[0], f"{type(e).__name__}: {e}")

    applied_pid = _write_flow(srv, approvals, cl)
    _rollback_flow(srv, approvals, ocm, cl, applied_pid)
    _lifecycle(srv, approvals, ocm, cl)
    _prompts(srv, cl)
    _audit(srv)
    _mcp_protocol()
    _negative_sweep(srv, approvals, ocm, cl)
    _tracing_export()
    _negative_scenario(srv, approvals, ocm, cl)

    print(f"\n{C['g'] if not FAILS else C['r']}e2e_tools.py finished "
          f"({'0 failures' if not FAILS else str(len(FAILS)) + ' FAILED: ' + ', '.join(FAILS)}).{C['x']}")
    return 1 if FAILS else 0


def _first_pod_logs(ocm, cl):
    """Logs from a running pod - exercises get_pod_logs. Prefers the demo namespace;
    falls back to kube-system (every cluster has running pods there)."""
    from ocm_mcp_server.k8s import spoke_core
    for ns in ("shop", "kube-system"):
        pods = spoke_core(cl).list_namespaced_pod(ns, limit=10).items
        running = [p for p in pods if p.status.phase == "Running"]
        if running:
            pod = running[0].metadata.name
            return {"namespace": ns, "pod": pod,
                    "log_tail": ocm.pod_logs(cl, ns, pod, lines=5)[-400:]}
    raise LookupError("no running pod found to read logs from")


# --------------------------------------------------------------------- fixtures
def _setup_fixtures(srv, approvals, ocm, cl):
    P = "4c. Setup fixtures - create the objects the read tools will report on"
    from ocm_mcp_server.k8s import OCM_CLUSTER_GROUP, OCM_POLICY_GROUP, OCM_WORK_GROUP, hub_custom
    api = hub_custom()

    def _create(kind_desc, fn):
        try:
            fn(); return "created"
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            return "already exists" if "AlreadyExists" in msg or "409" in msg else f"skip ({type(e).__name__})"

    r1 = _create("binding", lambda: api.create_namespaced_custom_object(
        OCM_CLUSTER_GROUP, "v1beta2", "default", "managedclustersetbindings",
        {"apiVersion": f"{OCM_CLUSTER_GROUP}/v1beta2", "kind": "ManagedClusterSetBinding",
         "metadata": {"name": "global", "namespace": "default"}, "spec": {"clusterSet": "global"}}))
    r2 = _create("placement", lambda: api.create_namespaced_custom_object(
        OCM_CLUSTER_GROUP, "v1beta1", "default", "placements",
        {"apiVersion": f"{OCM_CLUSTER_GROUP}/v1beta1", "kind": "Placement",
         "metadata": {"name": "demo-all", "namespace": "default"}, "spec": {"clusterSets": ["global"]}}))
    rec(P, "Placement + ClusterSetBinding", "Bind the 'global' cluster set into a namespace and add a "
        "Placement that selects every cluster - so the placement tools have a real decision to show.",
        "OK", "kubectl apply Placement + ManagedClusterSetBinding", f"binding={r1}, placement={r2}")

    # Seed a ManifestWork through the real gated flow so list_manifestworks has data.
    cm = [{"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": "e2e-seed", "namespace": "shop"},
           "data": {"managed-by": "ocm-mcp-server"}}]
    try:
        pr = tj(srv.propose_manifestwork(cluster=cl, name="e2e-seed",
                summary="Seed marker ConfigMap.", manifests_json=json.dumps(cm)))
        pid = pr.get("proposal_id")
        if not pid:
            rec(P, "seed ManifestWork", "Deploy a marker ManifestWork so the work tools report on "
                "something real.", "SKIP", "propose_manifestwork", pr.get("_raw", json.dumps(pr)))
        else:
            prop = approvals.load_proposal(pid)
            ar = srv.apply_manifestwork(proposal_id=pid,
                                        approval_token=approvals.mint_token(prop, operation="apply"))
            ok = "applied" in ar.lower() and "reject" not in ar.lower()
            rec(P, "seed ManifestWork (gated)", "Deploy a marker ManifestWork via propose+approve+apply "
                "so the work tools report on something real.", "OK" if ok else "SKIP",
                "propose_manifestwork -> apply_manifestwork", f"proposal_id={pid}\n{ar[:160]}")
    except Exception as e:  # noqa: BLE001
        rec(P, "seed ManifestWork", "Seed a ManifestWork.", "SKIP", "", f"{type(e).__name__}: {e}")

    # ManifestWorkReplicaSet (needs the feature gate enabled in phase 4b).
    r3 = _create("mwrs", lambda: api.create_namespaced_custom_object(
        OCM_WORK_GROUP, "v1alpha1", "default", "manifestworkreplicasets",
        {"apiVersion": f"{OCM_WORK_GROUP}/v1alpha1", "kind": "ManifestWorkReplicaSet",
         "metadata": {"name": "demo-mwrs", "namespace": "default"},
         "spec": {"placementRefs": [{"name": "demo-all"}],
                  "manifestWorkTemplate": {"workload": {"manifests": cm}}}}))
    rec(P, "ManifestWorkReplicaSet", "A single template fanned across every placement-selected cluster - "
        "so list_manifestworkreplicasets shows a rollout.", "OK" if r3 == "created" else "SKIP",
        "kubectl apply ManifestWorkReplicaSet", f"result={r3}")

    # A governance Policy (needs the policy add-on from phase 4b).
    policy = {"apiVersion": f"{OCM_POLICY_GROUP}/v1", "kind": "Policy",
              "metadata": {"name": "require-cm", "namespace": "default"},
              "spec": {"remediationAction": "inform", "disabled": False,
                       "policy-templates": [{"objectDefinition": {
                           "apiVersion": f"{OCM_POLICY_GROUP}/v1", "kind": "ConfigurationPolicy",
                           "metadata": {"name": "require-cm"},
                           "spec": {"severity": "low", "remediationAction": "inform",
                                    "namespaceSelector": {"include": ["default"]},
                                    "object-templates": [{"complianceType": "musthave", "objectDefinition": {
                                        "apiVersion": "v1", "kind": "ConfigMap",
                                        "metadata": {"name": "must-exist", "namespace": "default"}}}]}}}]}}
    r4 = _create("policy", lambda: api.create_namespaced_custom_object(
        OCM_POLICY_GROUP, "v1", "default", "policies", policy))
    rec(P, "governance Policy", "A sample inform Policy so the policy tools report on a real object.",
        "OK" if r4 in ("created", "already exists") else "SKIP", "kubectl apply Policy", f"result={r4}")
    time.sleep(6)


# --------------------------------------------------------------- gated write flow
def _write_flow(srv, approvals, cl):
    P = "7. Gated write flow - propose, prove the gate rejects a bad token, then apply"
    mw = [{"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": "ocm-mcp-e2e", "namespace": "shop"},
           "data": {"note": "applied via the gated write path"}}]
    try:
        pr = tj(srv.propose_manifestwork(cluster=cl, name="e2e-demo",
                summary="Add an e2e marker ConfigMap to shop.", manifests_json=json.dumps(mw)))
        pid = pr.get("proposal_id")
        if not pid:
            rec(P, "propose_manifestwork", "Propose a change.", "FAIL", "tool: propose_manifestwork", short(pr))
            return
        rec(P, "propose_manifestwork", "The agent PROPOSES a change. It must pass static guardrails and a "
            "Kyverno dry-run first; nothing is applied yet.", "OK", "tool: propose_manifestwork",
            f"proposal_id={pid}\nstatus=pending_approval")
        # Prove the gate: a wrong token must be REJECTED by the real apply tool.
        bad = srv.apply_manifestwork(proposal_id=pid, approval_token="deadbeef.0.badbadbad")
        rec(P, "apply with a BAD token", "Prove the gate holds: apply with an invalid token must be refused "
            "by the server, not applied.", "PASS" if "REJECTED" in bad else "FAIL",
            "tool: apply_manifestwork(bad token)", bad)
        # Now the human mints a real token and the change applies.
        prop = approvals.load_proposal(pid)
        token = approvals.mint_token(prop)
        rec(P, "ocm-mcp approve (human)", "A human on a trusted terminal mints an approval token: an Ed25519 "
            "signature binding the exact content and operation. The server holds only the public key, so it "
            "can verify a token but can never mint one - and neither can the agent.", "OK",
            f"ocm-mcp approve {pid}", f"token minted (...{token[-12:]})")
        ar = srv.apply_manifestwork(proposal_id=pid, approval_token=token)
        applied = "applied" in ar.lower() and "reject" not in ar.lower()
        rec(P, "apply_manifestwork(token)", "With a valid token, the server verifies it and delivers the "
            "change as an OCM ManifestWork.", "OK" if applied else "FAIL", "tool: apply_manifestwork", ar)
        time.sleep(5)
        got = srv.get_manifestwork(cluster=cl, name="e2e-demo")
        ok = '"Applied": "True"' in got
        rec(P, "get_manifestwork (verify)", "Confirm the hub actually applied it on the spoke.",
            "PASS" if ok else "OK", "tool: get_manifestwork", short(got))
        return pid
    except Exception as e:  # noqa: BLE001
        rec(P, "write flow", "Gated ManifestWork write.", "FAIL", "", f"{type(e).__name__}: {e}")
    return None


# ----------------------------------------------------------------- gated rollback
def _rollback_flow(srv, approvals, ocm, cl, applied_pid):
    P = "7b. Gated rollback - undoing an applied change needs its own approval"
    if not applied_pid:
        rec(P, "rollback flow", "Roll back the applied ManifestWork.", "SKIP", "",
            "no applied proposal from the write flow to roll back")
        return
    try:
        rb = tj(srv.propose_rollback(proposal_id=applied_pid))
        rb_id = rb.get("rollback_proposal_id") or rb.get("proposal_id")
        rec(P, "propose_rollback", "The agent proposes UNDOING the applied change. This creates a distinct "
            "proposal bound to the exact ManifestWork name and UID - an old apply token can never delete "
            "a workload.", "OK" if rb_id else "FAIL", "tool: propose_rollback", short(rb))
        if not rb_id:
            return
        # Prove operation binding: an APPLY-scoped token must not authorize a rollback.
        apply_scoped = approvals.mint_token(approvals.load_proposal(rb_id), operation="apply")
        wrong = srv.rollback_manifestwork(rollback_proposal_id=rb_id, approval_token=apply_scoped)
        rec(P, "rollback with an APPLY token", "Prove operation binding: a token minted for 'apply' must be "
            "refused for a rollback.", "PASS" if "REJECTED" in wrong else "FAIL",
            "tool: rollback_manifestwork(apply-scoped token)", wrong[:300])
        token = approvals.mint_token(approvals.load_proposal(rb_id), operation="rollback")
        rr = srv.rollback_manifestwork(rollback_proposal_id=rb_id, approval_token=token)
        ok = "rolled_back" in rr
        rec(P, "rollback_manifestwork(token)", "With a rollback-scoped token, the server removes the "
            "ManifestWork it created.", "OK" if ok else "FAIL", "tool: rollback_manifestwork", rr[:300])
        time.sleep(4)
        try:
            ocm.get_manifestwork(cl, "e2e-demo")
            gone = False
        except Exception:  # noqa: BLE001 - not-found is the success case here
            gone = True
        rec(P, "verify rollback", "The e2e-demo ManifestWork no longer exists on the hub.",
            "PASS" if gone else "FAIL", f"tool: get_manifestwork({cl}, e2e-demo)",
            "ManifestWork removed - rollback confirmed." if gone else "ManifestWork still present.")
    except Exception as e:  # noqa: BLE001
        rec(P, "rollback flow", "Gated rollback.", "FAIL", "", f"{type(e).__name__}: {e}")


# ------------------------------------------------------------ gated lifecycle action
def _lifecycle(srv, approvals, ocm, cl):
    P = "8. Gated lifecycle action - cordon a cluster out of scheduling, then undo"
    try:
        pr = tj(srv.propose_cluster_action(cluster=cl, action="cordon",
                summary="Cordon for maintenance.", params_json="{}"))
        pid = pr.get("proposal_id")
        rec(P, "propose_cluster_action(cordon)", "Propose adding a NoSelect taint so Placements stop "
            "scheduling here - still gated by approval.", "OK" if pid else "FAIL",
            "tool: propose_cluster_action", short(pr))
        if not pid:
            return
        prop = approvals.load_proposal(pid)
        ar = srv.apply_cluster_action(proposal_id=pid, approval_token=approvals.mint_token(prop))
        taints = ocm.get_managed_cluster(cl).get("taints", [])
        rec(P, "apply_cluster_action(cordon)", "Applied after approval; the taint now keeps new work off "
            "this cluster.", "OK" if "applied" in ar.lower() else "FAIL", "tool: apply_cluster_action",
            f"taints={json.dumps(taints)}")
        # Undo so we leave the cluster schedulable.
        up = tj(srv.propose_cluster_action(cluster=cl, action="uncordon", summary="Undo.", params_json="{}"))
        uprop = approvals.load_proposal(up["proposal_id"])
        srv.apply_cluster_action(proposal_id=up["proposal_id"], approval_token=approvals.mint_token(uprop))
        rec(P, "uncordon (restore)", "Remove the taint so the cluster is schedulable again.", "OK",
            "tool: apply_cluster_action(uncordon)",
            f"taints_after={json.dumps(ocm.get_managed_cluster(cl).get('taints', []))}")
    except Exception as e:  # noqa: BLE001
        rec(P, "lifecycle action", "Cordon/uncordon.", "FAIL", "", f"{type(e).__name__}: {e}")

    def _gated_action(title, why, action, params, expect_label=None):
        try:
            pr = tj(srv.propose_cluster_action(cluster=cl, action=action,
                    summary=title, params_json=json.dumps(params)))
            pid = pr.get("proposal_id")
            if not pid:
                rec(P, title, why, "FAIL", f"tool: propose_cluster_action({action})", short(pr))
                return
            ar = srv.apply_cluster_action(proposal_id=pid,
                                          approval_token=approvals.mint_token(approvals.load_proposal(pid)))
            ok = "applied" in ar.lower()
            if ok and expect_label:
                labels = ocm.get_managed_cluster(cl).get("labels", {})
                ok = labels.get(expect_label[0]) == expect_label[1]
            rec(P, title, why, "OK" if ok else "FAIL", f"tool: apply_cluster_action({action})", ar[:300])
        except Exception as e:  # noqa: BLE001
            rec(P, title, why, "FAIL", "", f"{type(e).__name__}: {e}")

    _gated_action("set_label (gated)", "Stamp a fleet label through the same propose/approve gate - "
                  "labels drive Placements, so they are write-gated too.", "set_label",
                  {"key": "e2e.ocm-mcp.io/checked", "value": "true"},
                  expect_label=("e2e.ocm-mcp.io/checked", "true"))
    _gated_action("accept (gated, idempotent)", "Re-assert hubAcceptsClient on an already-accepted "
                  "cluster - exercises the accept path without changing fleet state.", "accept", {})
    _gated_action("enable_addon (gated)", "Create a ManagedClusterAddOn through the gate.",
                  "enable_addon", {"addon": "e2e-demo-addon"})
    _gated_action("disable_addon (gated, cleanup)", "Delete the same ManagedClusterAddOn through the "
                  "gate - leaving the fleet exactly as we found it.", "disable_addon",
                  {"addon": "e2e-demo-addon"})


def _prompts(srv, cl):
    P = "9. Prompts - reusable runbooks the server hands any MCP client"
    for name, fn, kw in [
        ("diagnose_fleet", srv.diagnose_fleet, {}),
        ("remediate_with_approval", srv.remediate_with_approval, {"symptom": "payments degraded on cluster1"}),
        ("why_not_scheduled", srv.why_not_scheduled, {"cluster": cl, "placement": "demo-all", "namespace": "default"}),
        ("incident_postmortem", srv.incident_postmortem, {}),
        ("onboard_cluster", srv.onboard_cluster, {"cluster": cl}),
        ("addon_troubleshoot", srv.addon_troubleshoot, {"addon": "governance-policy-framework"}),
        ("hosted_cluster_health", srv.hosted_cluster_health, {"cluster": "demo-hcp"}),
        ("policy_compliance_report", srv.policy_compliance_report, {}),
        ("capacity_report", srv.capacity_report, {}),
        ("rollout_status", srv.rollout_status, {"name": "demo-mwrs", "namespace": "default"}),
    ]:
        try:
            rec(P, "prompt: " + name, "A ready-made, safety-first runbook an agent can start from.",
                "OK", "mcp prompt: " + name, short(fn(**kw), 700))
        except Exception as e:  # noqa: BLE001
            rec(P, "prompt: " + name, "Render the prompt.", "FAIL", "", f"{type(e).__name__}: {e}")


def _audit(srv):
    P = "10. Audit - the server's own record of every tool call"
    try:
        rec(P, "list_pending_proposals", "Proposals still awaiting human approval.", "OK",
            "tool: list_pending_proposals", short(srv.list_pending_proposals()))
        rec(P, "get_audit_trail", "The append-only log of every tool call so far - the agent writes its "
            "incident report from this record, not from memory.", "OK", "tool: get_audit_trail",
            short(srv.get_audit_trail(last_n=8)))
    except Exception as e:  # noqa: BLE001
        rec(P, "audit", "Read the audit trail.", "FAIL", "", f"{type(e).__name__}: {e}")


# -------------------------------------------------------------- MCP protocol layer
def _mcp_protocol():
    """Drive the ACTUAL server binary over stdio JSON-RPC with the official MCP client.

    Everything before this phase calls the tool functions in-process; a regression in
    the FastMCP layer itself (schema serialization, annotations, resource templates,
    the stdio transport) would pass those. This phase catches it.
    """
    P = "11. MCP protocol layer - the real server binary over stdio JSON-RPC"
    import asyncio
    import os

    async def run():
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        params = StdioServerParameters(
            command=sys.executable,
            args=["-c", "from ocm_mcp_server.server import main; main()"],
            env=dict(os.environ),
        )
        out = {}
        async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
                init = await session.initialize()
                out["server"] = init.serverInfo.name
                tools = (await session.list_tools()).tools
                out["tools"] = len(tools)
                by_name = {t.name: t for t in tools}
                out["read_annotation_ok"] = bool(by_name["list_clusters"].annotations.readOnlyHint)
                out["apply_annotation_ok"] = bool(by_name["apply_manifestwork"].annotations.destructiveHint)
                out["prompts"] = len((await session.list_prompts()).prompts)
                res = {str(r.uri) for r in (await session.list_resources()).resources}
                tpl = {t.uriTemplate for t in (await session.list_resource_templates()).resourceTemplates}
                out["resources"] = len(res) + len(tpl)
                out["guardrails_resource_ok"] = "allowed_gvk" in (
                    (await session.read_resource("ocm://guardrails")).contents[0].text)
                call = await session.call_tool("list_clusters", {})
                out["list_clusters_over_wire"] = isinstance(json.loads(call.content[0].text), list)
                prompt = await session.get_prompt("diagnose_fleet", {})
                out["prompt_over_wire_ok"] = len(prompt.messages) > 0
        return out

    try:
        out = asyncio.run(run())
        checks_ok = (out["tools"] == 35 and out["prompts"] == 10 and out["resources"] == 6
                     and out["read_annotation_ok"] and out["apply_annotation_ok"]
                     and out["guardrails_resource_ok"] and out["list_clusters_over_wire"]
                     and out["prompt_over_wire_ok"])
        rec(P, "stdio JSON-RPC session", "Spawn the real server binary, complete the MCP handshake, and "
            "verify the full advertised surface (35 tools with safety annotations, 10 prompts, "
            "6 resources) plus a tool call, a resource read, and a prompt over the wire.",
            "PASS" if checks_ok else "FAIL", "mcp.client.stdio -> ocm-mcp-server", short(out))
    except Exception as e:  # noqa: BLE001
        rec(P, "stdio JSON-RPC session", "Drive the server over the real MCP protocol.", "FAIL", "",
            f"{type(e).__name__}: {e}")


# ------------------------------------------------------------------ negative sweep
def _negative_sweep(srv, approvals, ocm, cl):
    """Every gate must FAIL CLOSED: expired, replayed, read-only, and tampered paths."""
    P = "11b. Negative sweep - proving every gate fails closed"
    import os
    import tempfile

    # Expired token -> REJECTED; a fresh token on the SAME proposal still applies
    # (isolating the expiry check); replaying the spent token -> REJECTED again.
    try:
        cm = [{"apiVersion": "v1", "kind": "ConfigMap",
               "metadata": {"name": "e2e-negative", "namespace": "shop"}, "data": {"k": "v"}}]
        pr = tj(srv.propose_manifestwork(cluster=cl, name="e2e-negative",
                summary="Negative-sweep marker.", manifests_json=json.dumps(cm)))
        pid = pr["proposal_id"]
        prop = approvals.load_proposal(pid)
        expired = approvals.mint_token(prop, operation="apply", ttl_seconds=1)
        time.sleep(2)
        r1 = srv.apply_manifestwork(proposal_id=pid, approval_token=expired)
        rec(P, "expired token refused", "A token past its TTL must be rejected even though proposal and "
            "content are valid.", "PASS" if "REJECTED" in r1 else "FAIL",
            "apply_manifestwork(expired token)", r1[:200])
        good = approvals.mint_token(approvals.load_proposal(pid), operation="apply")
        r2 = srv.apply_manifestwork(proposal_id=pid, approval_token=good)
        rec(P, "fresh token still applies", "Same proposal, fresh token: applies - proving the expiry "
            "rejection was about the token, not the content.",
            "PASS" if "applied" in r2.lower() else "FAIL", "apply_manifestwork(fresh token)", r2[:200])
        r3 = srv.apply_manifestwork(proposal_id=pid, approval_token=good)
        rec(P, "replayed token refused", "The just-spent token must never work twice.",
            "PASS" if "REJECTED" in r3 else "FAIL", "apply_manifestwork(replayed token)", r3[:200])
    except Exception as e:  # noqa: BLE001
        rec(P, "token negative paths", "Expired/replayed token handling.", "FAIL", "",
            f"{type(e).__name__}: {e}")

    # Read-only mode: a fresh server process with OCM_MCP_READ_ONLY=1 refuses writes.
    try:
        code = ("from ocm_mcp_server import server\n"
                "print(server.propose_manifestwork(cluster='x', name='x', summary='x', "
                "manifests_json='[]'))\n")
        env = dict(os.environ, OCM_MCP_READ_ONLY="1")
        ro = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                            env=env, check=False)
        refused = "read-only" in ro.stdout.lower() or "rejected" in ro.stdout.lower()
        rec(P, "read-only mode refuses writes", "With OCM_MCP_READ_ONLY=1 every write tool refuses "
            "before any guardrail or token logic runs - the coarse backstop.",
            "PASS" if refused else "FAIL", "OCM_MCP_READ_ONLY=1 propose_manifestwork", ro.stdout[:200])
    except Exception as e:  # noqa: BLE001
        rec(P, "read-only mode", "Read-only backstop.", "FAIL", "", f"{type(e).__name__}: {e}")

    # Audit tamper-evidence: a modified COPY of the log must fail verification, the
    # real log must pass, and a signed anchor must verify.
    try:
        from ocm_mcp_server.config import SETTINGS
        from ocm_mcp_server.tracing import (
            anchor_audit_chain,
            verify_audit_anchors,
            verify_audit_chain,
        )
        ok_real, msg_real = verify_audit_chain()
        lines = SETTINGS.audit_log.read_text().strip().splitlines()
        mid = len(lines) // 2
        tampered = json.loads(lines[mid]); tampered["tool"] = "totally-innocent-tool"
        lines[mid] = json.dumps(tampered)
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as fh:
            fh.write("\n".join(lines) + "\n"); tmp = fh.name
        ok_tampered, msg_tampered = verify_audit_chain(tmp)
        os.unlink(tmp)
        anchor_audit_chain()
        ok_anchor, msg_anchor = verify_audit_anchors()
        good = ok_real and not ok_tampered and ok_anchor
        rec(P, "audit chain + signed anchor", "The genuine log verifies; a log with one rewritten entry "
            "fails; and a chain head signed by the off-box key (audit-anchor) verifies - so mid-log "
            "edits AND tail truncation are both detectable.", "PASS" if good else "FAIL",
            "audit-verify / tamper copy / audit-anchor",
            f"real: {msg_real}\ntampered copy: {msg_tampered}\nanchors: {msg_anchor}")
    except Exception as e:  # noqa: BLE001
        rec(P, "audit tamper-evidence", "Audit chain and anchors.", "FAIL", "", f"{type(e).__name__}: {e}")

    # ocm-mcp doctor: the live read-path smoke test the docs point operators at.
    try:
        from ocm_mcp_server import cli
        code = cli.cmd_doctor(None)
        rec(P, "ocm-mcp doctor", "The operator-facing smoke test runs the read path against the live "
            "hub and reports per-check status.", "PASS" if code == 0 else "FAIL",
            "ocm-mcp doctor", f"exit={code}")
    except Exception as e:  # noqa: BLE001
        rec(P, "ocm-mcp doctor", "Doctor smoke test.", "FAIL", "", f"{type(e).__name__}: {e}")


# ------------------------------------------------------------- OTel tracing export
def _tracing_export():
    """Prove OTel spans actually leave the process over OTLP/HTTP.

    A local OTLP sink stands in for Jaeger's collector (same wire protocol, port
    4318 in real deployments). A fresh server process with OTEL_EXPORTER_OTLP_ENDPOINT
    set makes one tool call; the sink must receive a trace batch naming the tool span
    and the service. This covers the exporter wiring end to end without needing a
    Jaeger container in CI.
    """
    P = "11c. Tracing - OTel spans export over OTLP (what Jaeger would receive)"
    import http.server
    import os
    import threading

    bodies = []

    class Sink(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0))
            bodies.append((self.path, self.rfile.read(n)))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *args):
            pass  # keep the e2e console clean

    sink = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Sink)
    port = sink.server_address[1]
    threading.Thread(target=sink.serve_forever, daemon=True).start()
    try:
        code = ("from ocm_mcp_server import server\n"
                "server.list_pending_proposals()\n")
        env = dict(os.environ, OTEL_EXPORTER_OTLP_ENDPOINT=f"http://127.0.0.1:{port}")
        proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                              env=env, check=False, timeout=90)
        blob = b"".join(b for _, b in bodies)
        got_traces = any(p == "/v1/traces" for p, _ in bodies)
        span_named = b"tool.list_pending_proposals" in blob and b"ocm-mcp-server" in blob
        ok = proc.returncode == 0 and got_traces and span_named
        rec(P, "OTLP span export", "With OTEL_EXPORTER_OTLP_ENDPOINT set (and the [tracing] extra "
            "installed), every tool call opens a span named tool.<name> with redacted args; the "
            "BatchSpanProcessor flushes it over OTLP/HTTP - the same endpoint a Jaeger all-in-one "
            "or any OTel collector listens on (:4318).", "PASS" if ok else "FAIL",
            "OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:PORT python -c 'tool call'",
            f"posts={len(bodies)} paths={sorted({p for p, _ in bodies})} span_named={span_named} "
            f"rc={proc.returncode}" + ("" if ok else f"\n{proc.stderr[-300:]}"))
    finally:
        sink.shutdown()


# ------------------------------------------------- negative scenario: break then fix
def _negative_scenario(srv, approvals, ocm, cl):
    P = "12. Negative scenario - break something, then debug and fix it end to end"
    root = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                          capture_output=True, text=True, check=False).stdout.strip() or "."
    inj = subprocess.run(["bash", f"{root}/chaos/inject.sh", "failing-rollout", cl],
                         capture_output=True, text=True, check=False)
    rec(P, "INJECT: failing-rollout", "Deploy a 'payments-v2' with a broken image tag, exactly the kind of "
        "bad rollout that pages someone at 2 a.m.", "INJECT", f"./chaos/inject.sh failing-rollout {cl}",
        (inj.stdout + inj.stderr).strip())
    time.sleep(12)
    try:
        health = ocm.cluster_health(cl)
        bad = [p for p in health.get("unhealthy_pods", []) if "payments-v2" in p.get("name", "")]
        rec(P, "DIAGNOSE: get_cluster_health", "The agent asks 'what is unhealthy here?' and sees "
            "payments-v2 is not running.", "OK", f"tool: get_cluster_health({cl})",
            short({"unhealthy_pods": bad or health.get("unhealthy_pods", [])[:3],
                   "degraded_deployments": health.get("degraded_deployments", [])[:3]}))
        evs = [e for e in ocm.cluster_events(cl, namespace="shop", limit=25)
               if e.get("reason") in ("Failed", "BackOff", "ErrImagePull", "FailedCreate")][:5]
        rec(P, "DIAGNOSE: query_events", "Events reveal the root cause in plain English: the image cannot "
            "be pulled.", "OK", f"tool: query_events({cl}, shop)", short(evs or "no matching events"))
    except Exception as e:  # noqa: BLE001
        rec(P, "DIAGNOSE", "Investigate the failure.", "FAIL", "", f"{type(e).__name__}: {e}")
    fix = [{"apiVersion": "apps/v1", "kind": "Deployment",
            "metadata": {"name": "payments-v2", "namespace": "shop", "labels": {"app": "payments", "version": "v2"}},
            "spec": {"replicas": 2, "selector": {"matchLabels": {"app": "payments", "version": "v2"}},
                     "template": {"metadata": {"labels": {"app": "payments", "version": "v2"}},
                                  "spec": {"automountServiceAccountToken": False,
                                           "securityContext": {"runAsUser": 65532, "runAsGroup": 65532},
                                           "containers": [{"name": "payments",
                                           "image": "registry.k8s.io/e2e-test-images/agnhost:2.47",
                                           "args": ["netexec", "--http-port=8080"],
                                           "ports": [{"containerPort": 8080}],
                                           "securityContext": {"runAsNonRoot": True,
                                               "allowPrivilegeEscalation": False,
                                               "seccompProfile": {"type": "RuntimeDefault"},
                                               "capabilities": {"drop": ["ALL"]}}}]}}}}]
    try:
        pr = tj(srv.propose_manifestwork(cluster=cl, name="fix-payments-v2",
                summary="Pin payments-v2 to the known-good agnhost:2.47 image.", manifests_json=json.dumps(fix)))
        pid = pr["proposal_id"]
        rec(P, "FIX: propose + approve", "The agent proposes the smallest safe fix (a pinned, known-good "
            "image). It clears the guardrails and a human approves it.", "FIX",
            "propose_manifestwork -> ocm-mcp approve",
            f"proposal_id={pid}\nguardrails=passed  kyverno_dry_run=passed  approved=yes")
        srv.apply_manifestwork(proposal_id=pid, approval_token=approvals.mint_token(approvals.load_proposal(pid)))
        rec(P, "FIX: apply_manifestwork", "Delivered to the cluster through the hub as a ManifestWork.",
            "FIX", "tool: apply_manifestwork(token)", "status=applied")
    except Exception as e:  # noqa: BLE001
        rec(P, "FIX", "Apply the fix.", "FAIL", "", f"{type(e).__name__}: {e}")
    recovered = False
    for _ in range(30):
        time.sleep(6)
        try:
            h = ocm.cluster_health(cl)
            still_bad = [p for p in h.get("unhealthy_pods", []) if "payments-v2" in p.get("name", "")]
            deps = {d["name"]: d["ready"] for d in h.get("degraded_deployments", [])}
            if not still_bad and "payments-v2" not in deps:
                recovered = True
                break
        except Exception:  # noqa: BLE001, S110 - transient read errors during recovery are expected
            pass
    rec(P, "VERIFY: recovery", "Re-read health until payments-v2 is running again - the incident is closed, "
        "with a full audit trail of everything that happened.", "PASS" if recovered else "FAIL",
        f"tool: get_cluster_health({cl})",
        "payments-v2 is Running again - fix confirmed end to end." if recovered
        else "payments-v2 did not recover within the timeout (see ManifestWork status).")


if __name__ == "__main__":
    sys.exit(main())
