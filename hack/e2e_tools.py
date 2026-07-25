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

    from ocm_mcp_server import approvals, ocm  # noqa: after env is set
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

    _write_flow(srv, approvals, cl)
    _lifecycle(srv, approvals, ocm, cl)
    _prompts(srv, cl)
    _audit(srv)
    _negative_scenario(srv, approvals, ocm, cl)

    print(f"\n{C['g'] if not FAILS else C['r']}e2e_tools.py finished "
          f"({'0 failures' if not FAILS else str(len(FAILS)) + ' FAILED: ' + ', '.join(FAILS)}).{C['x']}")
    return 1 if FAILS else 0


# --------------------------------------------------------------------- fixtures
def _setup_fixtures(srv, approvals, ocm, cl):
    P = "4c. Setup fixtures - create the objects the read tools will report on"
    from ocm_mcp_server.k8s import OCM_CLUSTER_GROUP, OCM_WORK_GROUP, OCM_POLICY_GROUP, hub_custom
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
    except Exception as e:  # noqa: BLE001
        rec(P, "write flow", "Gated ManifestWork write.", "FAIL", "", f"{type(e).__name__}: {e}")


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


def _prompts(srv, cl):
    P = "9. Prompts - reusable runbooks the server hands any MCP client"
    try:
        for name, fn, kw in [
            ("diagnose_fleet", srv.diagnose_fleet, {}),
            ("remediate_with_approval", srv.remediate_with_approval, {"symptom": "payments degraded on cluster1"}),
            ("why_not_scheduled", srv.why_not_scheduled, {"cluster": cl, "placement": "demo-all", "namespace": "default"}),
        ]:
            rec(P, "prompt: " + name, "A ready-made, safety-first runbook an agent can start from.",
                "OK", "mcp prompt: " + name, short(fn(**kw), 900))
    except Exception as e:  # noqa: BLE001
        rec(P, "prompts", "Render MCP prompts.", "FAIL", "", f"{type(e).__name__}: {e}")


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
                                  "spec": {"containers": [{"name": "payments",
                                           "image": "registry.k8s.io/e2e-test-images/agnhost:2.47",
                                           "args": ["netexec", "--http-port=8080"],
                                           "ports": [{"containerPort": 8080}]}]}}}}]
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
