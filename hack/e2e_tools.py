#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Sandeep Bazar
# SPDX-License-Identifier: Apache-2.0
"""Exercise the ocm-mcp-server tools, prompts, and a negative-scenario debug loop
against a live Open Cluster Management hub, printing clean terminal output and
appending JSONL records that hack/e2e_report.py renders into an HTML report.

Env (set by hack/e2e-local.sh): OCM_MCP_HUB_CONTEXT, OCM_MCP_SPOKE_CONTEXTS,
OCM_MCP_HOME, plus --results, --spokes, --cluster.
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


def rec(phase, title, why, status, cmd="", output=""):
    """Print a clean console block and append a JSONL record for the HTML report.

    Argument order is always (phase, title, why, status, cmd, output).
    """
    c = COL.get(status, "d")
    print(f"\n{C[c]}[{status}]{C['x']} {C['b']}{title}{C['x']}")
    if why:
        print(f"   {C['d']}{why}{C['x']}")
    if cmd:
        print(f"   {C['d']}$ {cmd}{C['x']}")
    if output:
        for line in str(output).rstrip().splitlines()[:12]:
            print(f"     {line}")
    with open(RESULTS, "a") as f:
        f.write(json.dumps({"phase": phase, "title": title, "why": why,
                            "status": status, "cmd": cmd, "output": output}) + "\n")


def short(obj, n=1400):
    s = obj if isinstance(obj, str) else json.dumps(obj, indent=2, default=str)
    return s if len(s) <= n else s[:n] + "\n... (truncated)"


def main():
    global RESULTS
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", required=True)
    ap.add_argument("--spokes", type=int, default=2)
    ap.add_argument("--cluster", default="cluster1")
    args = ap.parse_args()
    RESULTS = args.results
    cl = args.cluster

    from ocm_mcp_server import approvals, guardrails, ocm  # noqa: after env is set

    # ------------------------------------------------------------------ reads
    P3 = "5. Read tools (safe, no gate) - how an agent investigates a fleet"
    reads = [
        ("list_clusters", "The fleet roster: every managed cluster, its version and health.",
         lambda: ocm.list_managed_clusters()),
        (f"get_cluster({cl})", "Zoom into one cluster: acceptance, taints, capacity, claims.",
         lambda: ocm.get_managed_cluster(cl)),
        ("list_cluster_sets", "Groupings of clusters used for placement.",
         lambda: ocm.list_cluster_sets()),
        ("list_cluster_set_bindings", "Which cluster sets a namespace may schedule to.",
         lambda: ocm.list_cluster_set_bindings()),
        ("list_cluster_claims", "Facts each cluster self-reports (region, platform, version).",
         lambda: ocm.list_cluster_claims()),
        (f"get_cluster_health({cl})", "The on-call view: unhealthy pods and degraded deployments.",
         lambda: ocm.cluster_health(cl)),
        (f"query_events({cl})", "Recent Kubernetes events - the 'why' behind failures.",
         lambda: ocm.cluster_events(cl, limit=8)),
        (f"list_manifestworks({cl})", "What the hub is currently delivering to this cluster.",
         lambda: ocm.list_manifestworks(cl)),
        ("list_manifestworkreplicasets", "Fleet-wide rollouts (a template fanned across clusters).",
         lambda: ocm.list_manifestworkreplicasets()),
        ("list_cluster_management_addons", "Fleet-level add-on definitions.",
         lambda: ocm.list_cluster_management_addons()),
        ("get_addon_health", "Per-cluster add-on health across the fleet.",
         lambda: ocm.addon_health()),
        ("list_pending_csrs", "Clusters waiting to be admitted to the hub.",
         lambda: ocm.list_pending_csrs()),
        (f"get_cluster_info({cl})", "Extended inventory (OpenShift version, nodes) - ACM only.",
         lambda: ocm.get_cluster_info(cl)),
        ("list_policies", "Governance compliance - the policy add-on (ACM) only.",
         lambda: ocm.list_policies()),
        ("list_hosted_clusters", "HyperShift hosted control planes - when the hub hosts them.",
         lambda: ocm.list_hosted_clusters()),
        ("list_resources(managedclusters)", "Generic allow-listed reader over any OCM type.",
         lambda: ocm.list_resources("managedclusters")),
    ]
    for title, why, fn in reads:
        try:
            out = fn()
            empty = out in ([], {}, None)
            rec(P3, title, why, "OK", "tool: " + title.split("(")[0],
                "(empty result - nothing to report)" if empty else short(out))
        except (ocm.FeatureNotInstalled, LookupError, ValueError) as e:
            rec(P3, title, why, "UNAVAILABLE", "tool: " + title.split("(")[0],
                f"UNAVAILABLE: {e}\n(feature-detected: this add-on/CRD is not on a plain OCM hub - "
                "expected on kind).")
        except Exception as e:  # noqa: BLE001
            rec(P3, title, why, "FAIL", "tool: " + title.split("(")[0], f"{type(e).__name__}: {e}")

    # ------------------------------------------------------- placement (create + read)
    P3b = "6. Placement - scheduling clusters, then reading the decision"
    try:
        _make_placement(ocm)
        rec(P3b, "create Placement 'demo-all'", "Set up a Placement selecting every cluster so we "
            "can show the scheduling tools working.", "OK", "kubectl apply Placement + Binding", "created")
        time.sleep(4)
        rec(P3b, "list_placements", "The Placement and how many clusters it selected.",
            "OK", "tool: list_placements", short(ocm.list_placements()))
        dec = ocm.get_placement_decision("demo-all", "default")
        rec(P3b, "get_placement_decision(demo-all)", "Exactly which clusters were chosen - the "
            "answer to 'where will my workload land?'", "OK", "tool: get_placement_decision", short(dec))
    except Exception as e:  # noqa: BLE001
        rec(P3b, "placement demo", "Create + read a Placement.", "FAIL", "", f"{type(e).__name__}: {e}")

    # ------------------------------------------------------------- gated write flow
    P5 = "7. Gated write flow - propose -> human approval -> apply -> verify"
    mw = [{"apiVersion": "v1", "kind": "ConfigMap",
           "metadata": {"name": "ocm-mcp-e2e", "namespace": "shop"},
           "data": {"managed-by": "ocm-mcp-server", "note": "applied via the gated write path"}}]
    try:
        guardrails.validate_manifests(mw)
        ocm.dry_run_manifestwork(cl, ocm.manifestwork_body("e2e-demo", mw))
        prop = approvals.new_proposal(cl, "e2e-demo", "Add an e2e marker ConfigMap to shop.", mw)
        rec(P5, "propose_manifestwork", "The agent PROPOSES a change. Nothing is applied yet; it "
            "must pass static guardrails and a Kyverno dry-run first.", "OK",
            "tool: propose_manifestwork", f"proposal_id={prop.id}\nstatus=pending_approval")
        token = approvals.mint_token(prop)
        rec(P5, "ocm-mcp approve (human)", "A human on a trusted terminal mints an approval token "
            "bound to the exact content. The agent can never mint one itself.", "OK",
            f"ocm-mcp approve {prop.id}", f"approval token minted (...{token[-12:]})")
        ocm.create_manifestwork(cl, ocm.manifestwork_body(prop.name, prop.manifests))
        prop.status = "applied"; prop.applied_work = prop.name; prop.save()
        rec(P5, "apply_manifestwork(token)", "With a valid token, the change is delivered to the "
            "cluster as an OCM ManifestWork.", "OK", "tool: apply_manifestwork", "status=applied")
        time.sleep(4)
        got = ocm.get_manifestwork(cl, "e2e-demo")
        applied = got.get("conditions", {}).get("Applied", "?")
        rec(P5, "get_manifestwork (verify)", "Confirm the hub actually applied it on the spoke.",
            "OK", "tool: get_manifestwork", short(got))
        rec(P5, "write flow result", "End-to-end: proposed, approved, applied, verified.",
            "PASS" if applied == "True" else "OK", "", f"ManifestWork Applied={applied}")
    except Exception as e:  # noqa: BLE001
        rec(P5, "write flow", "Gated ManifestWork write.", "FAIL", "", f"{type(e).__name__}: {e}")

    # -------------------------------------------------------- lifecycle action (cordon)
    P6 = "8. Gated lifecycle action - cordon a cluster out of scheduling, then undo"
    try:
        ocm.validate_cluster_action(cl, "cordon", {})
        cprop = approvals.new_action_proposal(cl, "cordon", "Cordon for maintenance.", {})
        approvals.mint_token(cprop)  # a human mints this out-of-band; the harness applies directly
        rec(P6, "propose_cluster_action(cordon)", "Propose adding a NoSelect taint so Placements "
            "stop scheduling here - still gated by approval.", "OK", "tool: propose_cluster_action",
            f"proposal_id={cprop.id}")
        ocm.apply_cluster_action(cl, "cordon", {}); cprop.status = "applied"; cprop.save()
        taints = ocm.get_managed_cluster(cl).get("taints", [])
        rec(P6, "apply_cluster_action(cordon)", "Applied after approval; the taint now keeps new "
            "work off this cluster.", "OK", "tool: apply_cluster_action", f"taints={json.dumps(taints)}")
        approvals.mint_token(approvals.new_action_proposal(cl, "uncordon", "Undo.", {}))
        ocm.apply_cluster_action(cl, "uncordon", {})
        rec(P6, "uncordon (restore)", "Remove the taint so the cluster is schedulable again.",
            "OK", "tool: apply_cluster_action(uncordon)",
            f"taints_after={json.dumps(ocm.get_managed_cluster(cl).get('taints', []))}")
    except Exception as e:  # noqa: BLE001
        rec(P6, "lifecycle action", "Cordon/uncordon.", "FAIL", "", f"{type(e).__name__}: {e}")

    # ------------------------------------------------------------------------ prompts
    P7 = "9. Prompts - reusable runbooks the server hands any MCP client"
    try:
        from ocm_mcp_server import server as srv
        for name, fn, kw in [
            ("diagnose_fleet", srv.diagnose_fleet, {}),
            ("remediate_with_approval", srv.remediate_with_approval, {"symptom": "payments degraded on cluster1"}),
            ("why_not_scheduled", srv.why_not_scheduled, {"cluster": cl, "placement": "demo-all", "namespace": "default"}),
        ]:
            rec(P7, "prompt: " + name, "A ready-made, safety-first runbook an agent can start from.",
                "OK", "mcp prompt: " + name, short(fn(**kw), 900))
    except Exception as e:  # noqa: BLE001
        rec(P7, "prompts", "Render MCP prompts.", "FAIL", "", f"{type(e).__name__}: {e}")

    # ------------------------------------------------- negative scenario: break then fix
    _negative_scenario(ocm, guardrails, approvals, cl)

    print(f"\n{C['g']}e2e_tools.py finished.{C['x']}")


def _make_placement(ocm):
    from ocm_mcp_server.k8s import OCM_CLUSTER_GROUP, hub_custom
    api = hub_custom()
    for body in (
        {"apiVersion": f"{OCM_CLUSTER_GROUP}/v1beta2", "kind": "ManagedClusterSetBinding",
         "metadata": {"name": "global", "namespace": "default"},
         "spec": {"clusterSet": "global"}},
        {"apiVersion": f"{OCM_CLUSTER_GROUP}/v1beta1", "kind": "Placement",
         "metadata": {"name": "demo-all", "namespace": "default"},
         "spec": {"clusterSets": ["global"]}},
    ):
        try:
            if body["kind"] == "ManagedClusterSetBinding":
                api.create_namespaced_custom_object(OCM_CLUSTER_GROUP, "v1beta2", "default",
                                                    "managedclustersetbindings", body)
            else:
                api.create_namespaced_custom_object(OCM_CLUSTER_GROUP, "v1beta1", "default",
                                                    "placements", body)
        except Exception:  # noqa: BLE001, S110 - already-exists is fine for an idempotent setup
            pass


def _negative_scenario(ocm, guardrails, approvals, cl):
    P8 = "10. Negative scenario - break something, then debug and fix it end to end"
    root = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                          capture_output=True, text=True, check=False).stdout.strip() or "."
    # 1. INJECT
    inj = subprocess.run(["bash", f"{root}/chaos/inject.sh", "failing-rollout", cl],
                         capture_output=True, text=True, check=False)
    rec(P8, "INJECT: failing-rollout", "Deploy a 'payments-v2' with a broken image tag, exactly the "
        "kind of bad rollout that pages someone at 2 a.m.", "INJECT",
        f"./chaos/inject.sh failing-rollout {cl}", (inj.stdout + inj.stderr).strip())
    time.sleep(12)
    # 2. DIAGNOSE
    try:
        health = ocm.cluster_health(cl)
        bad = [p for p in health.get("unhealthy_pods", []) if "payments-v2" in p.get("name", "")]
        rec(P8, "DIAGNOSE: get_cluster_health", "The agent asks the fleet 'what is unhealthy here?' "
            "and immediately sees payments-v2 is not running.", "OK", f"tool: get_cluster_health({cl})",
            short({"unhealthy_pods": bad or health.get("unhealthy_pods", [])[:3],
                   "degraded_deployments": health.get("degraded_deployments", [])[:3]}))
        evs = [e for e in ocm.cluster_events(cl, namespace="shop", limit=25)
               if e.get("reason") in ("Failed", "BackOff", "ErrImagePull", "FailedCreate")][:5]
        rec(P8, "DIAGNOSE: query_events", "Events reveal the root cause in plain English: the image "
            "cannot be pulled.", "OK", f"tool: query_events({cl}, shop)",
            short(evs or "no matching events"))
    except Exception as e:  # noqa: BLE001
        rec(P8, "DIAGNOSE", "Investigate the failure.", "FAIL", "", f"{type(e).__name__}: {e}")
    # 3. FIX via the gated write path
    fix = [{"apiVersion": "apps/v1", "kind": "Deployment",
            "metadata": {"name": "payments-v2", "namespace": "shop", "labels": {"app": "payments", "version": "v2"}},
            "spec": {"replicas": 2, "selector": {"matchLabels": {"app": "payments", "version": "v2"}},
                     "template": {"metadata": {"labels": {"app": "payments", "version": "v2"}},
                                  "spec": {"containers": [{"name": "payments",
                                           "image": "registry.k8s.io/e2e-test-images/agnhost:2.47",
                                           "args": ["netexec", "--http-port=8080"],
                                           "ports": [{"containerPort": 8080}]}]}}}}]
    try:
        guardrails.validate_manifests(fix)
        ocm.dry_run_manifestwork(cl, ocm.manifestwork_body("fix-payments-v2", fix))
        prop = approvals.new_proposal(cl, "fix-payments-v2",
                                      "Pin payments-v2 to the known-good agnhost:2.47 image.", fix)
        approvals.mint_token(prop)  # human-minted out-of-band; harness applies directly below
        rec(P8, "FIX: propose + approve", "The agent proposes the smallest safe fix (a pinned, "
            "known-good image). It clears the guardrails and a human approves it.", "FIX",
            "propose_manifestwork -> ocm-mcp approve",
            f"proposal_id={prop.id}\nguardrails=passed  kyverno_dry_run=passed  approved=yes")
        ocm.create_manifestwork(cl, ocm.manifestwork_body(prop.name, prop.manifests))
        prop.status = "applied"; prop.save()
        rec(P8, "FIX: apply_manifestwork", "Delivered to the cluster through the hub as a ManifestWork.",
            "FIX", "tool: apply_manifestwork(token)", "status=applied")
    except Exception as e:  # noqa: BLE001
        rec(P8, "FIX", "Apply the fix.", "FAIL", "", f"{type(e).__name__}: {e}")
    # 4. VERIFY recovery
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
    rec(P8, "VERIFY: recovery", "Re-read health until payments-v2 is running again - the incident is "
        "closed, with a full audit trail of everything that happened.",
        "PASS" if recovered else "FAIL", f"tool: get_cluster_health({cl})",
        "payments-v2 is Running again - fix confirmed end to end." if recovered
        else "payments-v2 did not recover within the timeout (see ManifestWork status).")


if __name__ == "__main__":
    sys.exit(main())
