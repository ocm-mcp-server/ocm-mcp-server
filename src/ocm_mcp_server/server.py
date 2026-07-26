# SPDX-FileCopyrightText: 2026 Sandeep Bazar
# SPDX-License-Identifier: Apache-2.0

"""The MCP server: a broad READ surface over an OCM hub, a narrow GATED write path.

The tool surface is organized into toolsets, mirrored in the README:

    inventory      clusters, cluster sets, set bindings, claims          (read)
    observability  cluster health, events, pod logs                      (read)
    placement      placements, placement decisions, addon scores         (read)
    work           manifestwork status + the gated propose/apply/rollback flow
    addons         cluster-management add-ons, per-cluster add-on health  (read)
    registration   pending join CSRs + gated cluster lifecycle actions
    policy         governance policy compliance (only if the add-on is installed, read)
    resources      generic get/list over an allow-list of OCM API types  (read)
    audit          pending proposals, this server's own audit trail       (read)

Every read tool is annotated readOnlyHint=True. Every write is annotated
destructiveHint and, more importantly, is *enforced*: a change reaches a cluster
only after static guardrails, a Kyverno dry-run, and a human-minted approval
token bound to the exact content. The agent never sees a kubeconfig, a Secret, or
an exec socket. There is no tool that can read Secrets, exec into pods, or delete
arbitrary resources - by design, not by prompt. OCM_MCP_READ_ONLY=1 additionally
refuses every write as a coarse backstop under the token gate.
"""

from __future__ import annotations

import json
import os
from typing import Any

from kubernetes.client import ApiException
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from . import approvals, guardrails, ocm
from .config import ALLOWED_CLUSTER_ACTIONS, SETTINGS
from .tracing import traced_tool

mcp = FastMCP(
    "ocm-mcp-server",
    instructions=(
        "Tools for operating a multi-cluster Kubernetes fleet through an Open Cluster "
        "Management hub. Investigate freely with the read tools (inventory, observability, "
        "placement, addons, work, policy, resources, audit). Any change must be proposed "
        "- a workload with propose_manifestwork, or a cluster lifecycle action with "
        "propose_cluster_action - and will only apply after a human approves it out-of-band; "
        "ask the operator to run `ocm-mcp approve <proposal-id>` and give you the token. "
        "Never claim a change is applied unless the apply tool returned success."
    ),
)

# MCP tool annotations advertise each tool's safety class to the client and model.
READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True)
PROPOSE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True)
APPLY = ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=True)


def _json(data: Any) -> str:
    return json.dumps(data, indent=2, default=str)


def _read(fn, *args: Any, **kwargs: Any) -> str:
    """Run a read helper and JSON-encode it, turning expected gaps into clear messages."""
    try:
        return _json(fn(*args, **kwargs))
    except (ocm.FeatureNotInstalled, LookupError, ValueError) as exc:
        return f"UNAVAILABLE: {exc}"
    except ApiException as exc:
        return f"ERROR: {(exc.body or str(exc))[:800]}"


def _writable() -> str | None:
    """The read-only backstop. Returns a rejection string when writes are disabled."""
    if SETTINGS.read_only:
        return (
            "REJECTED: this server runs in read-only mode (OCM_MCP_READ_ONLY). "
            "No proposals or writes are accepted."
        )
    return None


def _content_intact(prop: approvals.Proposal) -> str | None:
    """Confirm the stored proposal still matches its own content hash, at apply time.

    The approval token already binds to the hash, but the on-disk manifests could be
    edited while leaving the hash field untouched (a TOCTOU on a writable state dir).
    Recomputing the hash from the stored content closes that window; ManifestWork
    proposals also get a fresh static-guardrail pass. Defense in depth.
    """
    expected = approvals.content_hash(
        prop.cluster,
        prop.name,
        prop.manifests,
        kind=prop.kind,
        action=prop.action,
        params=prop.params,
    )
    if expected != prop.content_hash:
        return (
            "REJECTED: the stored proposal no longer matches its approved content hash. "
            "Re-propose and get a fresh approval."
        )
    if prop.kind == "manifestwork":
        try:
            guardrails.validate_manifests(prop.manifests)
        except guardrails.GuardrailViolation as exc:
            return f"REJECTED by static guardrails at apply time:\n{exc}"
    return None


# ============================================================== toolset: inventory


@mcp.tool(annotations=READ)
@traced_tool
def list_clusters() -> str:
    """List all managed clusters with availability, version, labels, and capacity."""
    return _read(ocm.list_managed_clusters)


@mcp.tool(annotations=READ)
@traced_tool
def get_cluster(cluster: str) -> str:
    """Full view of one ManagedCluster.

    Args:
        cluster: managed cluster name as the hub knows it (see list_clusters).

    Returns acceptance (hubAcceptsClient), taints, hub conditions, Kubernetes
    version, capacity/allocatable, and the cluster's ClusterClaims.
    """
    return _read(ocm.get_managed_cluster, cluster)


@mcp.tool(annotations=READ)
@traced_tool
def list_cluster_sets() -> str:
    """List ManagedClusterSets with their selector type and member clusters."""
    return _read(ocm.list_cluster_sets)


@mcp.tool(annotations=READ)
@traced_tool
def list_cluster_set_bindings(namespace: str = "") -> str:
    """List ManagedClusterSetBindings (which ClusterSets a namespace's Placements may use).

    Args:
        namespace: limit to one namespace; empty lists bindings across all namespaces.
    """
    return _read(ocm.list_cluster_set_bindings, namespace=namespace)


@mcp.tool(annotations=READ)
@traced_tool
def list_cluster_claims() -> str:
    """Every cluster's ClusterClaims (id, platform, region, version) rolled up from status."""
    return _read(ocm.list_cluster_claims)


@mcp.tool(annotations=READ)
@traced_tool
def get_cluster_info(cluster: str) -> str:
    """Extended inventory for one cluster from the hub: OpenShift version, nodes, console URL.

    Args:
        cluster: managed cluster name.

    Reads ManagedClusterInfo on the hub, so it needs no spoke access and works for
    any spoke - external OpenShift, HCP, or cloud. Needs the ACM/MCE
    multicloud-operators-foundation add-on; reports clearly if it is not present.
    """
    return _read(ocm.get_cluster_info, cluster)


# ========================================================== toolset: observability


@mcp.tool(annotations=READ)
@traced_tool
def get_cluster_health(cluster: str) -> str:
    """Health summary for one cluster: hub conditions, unhealthy pods, degraded deployments.

    Args:
        cluster: managed cluster name. Pod/deployment detail requires a read-only
            spoke context (OCM_MCP_SPOKE_CONTEXTS); hub conditions work without one.
    """
    return _read(ocm.cluster_health, cluster)


@mcp.tool(annotations=READ)
@traced_tool
def query_events(cluster: str, namespace: str = "", limit: int = 40) -> str:
    """Recent Kubernetes events from a managed cluster, newest first.

    Args:
        cluster: managed cluster name.
        namespace: optional namespace filter; empty means all namespaces.
        limit: maximum number of events to return (default 40).

    Use this to find the 'why' behind unhealthy pods.
    """
    return _read(ocm.cluster_events, cluster, namespace=namespace, limit=limit)


@mcp.tool(annotations=READ)
@traced_tool
def get_pod_logs(
    cluster: str, namespace: str, pod: str, container: str = "", lines: int = 80
) -> str:
    """Tail logs from a pod on a managed cluster.

    Args:
        cluster: managed cluster name.
        namespace: pod namespace.
        pod: pod name.
        container: container name; empty picks the default container.
        lines: number of trailing log lines (default 80).

    Falls back to the previous container instance if the current one is crashing.
    """
    try:
        return ocm.pod_logs(cluster, namespace, pod, container=container, lines=lines)
    except LookupError as exc:
        return f"UNAVAILABLE: {exc}"
    except ApiException as exc:
        return f"ERROR: {(exc.body or str(exc))[:800]}"


# ============================================================== toolset: placement


@mcp.tool(annotations=READ)
@traced_tool
def list_placements(namespace: str = "") -> str:
    """List Placements and how many clusters each currently selects.

    Args:
        namespace: limit to one namespace; empty lists across all namespaces.
    """
    return _read(ocm.list_placements, namespace=namespace)


@mcp.tool(annotations=READ)
@traced_tool
def get_placement_decision(placement: str, namespace: str) -> str:
    """Which clusters a Placement actually selected (reads its PlacementDecisions).

    Args:
        placement: Placement name.
        namespace: the namespace the Placement lives in.
    """
    return _read(ocm.get_placement_decision, placement, namespace)


@mcp.tool(annotations=READ)
@traced_tool
def list_addon_placement_scores(cluster: str) -> str:
    """List AddOnPlacementScores in a cluster's namespace (custom scores prioritizers consume).

    Args:
        cluster: managed cluster name (its hub namespace holds the scores).
    """
    return _read(ocm.list_addon_placement_scores, cluster)


# =================================================================== toolset: work


@mcp.tool(annotations=READ)
@traced_tool
def list_manifestworks(cluster: str) -> str:
    """List ManifestWorks targeting a cluster (what the hub is managing there).

    Args:
        cluster: managed cluster name.
    """
    return _read(ocm.list_manifestworks, cluster)


@mcp.tool(annotations=READ)
@traced_tool
def get_manifestwork(cluster: str, name: str) -> str:
    """Detailed ManifestWork status: top-level conditions and per-resource status feedback.

    Args:
        cluster: managed cluster name.
        name: ManifestWork name.

    Use this to answer 'why is this ManifestWork not Applied/Available' and to read
    status feedback (for example replica counts) reported back from the spoke.
    """
    return _read(ocm.get_manifestwork, cluster, name)


@mcp.tool(annotations=READ)
@traced_tool
def list_manifestworkreplicasets(namespace: str = "") -> str:
    """List ManifestWorkReplicaSets (a template fanned across a Placement) with rollout summary.

    Args:
        namespace: limit to one namespace; empty lists across all namespaces.
    """
    return _read(ocm.list_manifestworkreplicasets, namespace=namespace)


@mcp.tool(annotations=PROPOSE)
@traced_tool
def propose_manifestwork(cluster: str, name: str, summary: str, manifests_json: str) -> str:
    """Propose a change to one cluster as an OCM ManifestWork. Does NOT apply anything.

    Args:
        cluster: target managed cluster name.
        name: a short kebab-case name for the ManifestWork.
        summary: one or two sentences a human approver will read. Be precise about
            what changes and why.
        manifests_json: JSON array of complete Kubernetes manifests (allowed kinds
            only; all namespaced; images pinned).

    The proposal must pass static guardrails and a Kyverno dry-run on the hub.
    On success it is stored pending and the human operator must run
    `ocm-mcp approve <id>` to mint an approval token.
    """
    if msg := _writable():
        return msg
    try:
        manifests = json.loads(manifests_json)
    except json.JSONDecodeError as exc:
        return f"REJECTED: manifests_json is not valid JSON: {exc}"
    if isinstance(manifests, dict):
        manifests = [manifests]

    try:
        guardrails.validate_manifests(manifests)
    except guardrails.GuardrailViolation as exc:
        return f"REJECTED by static guardrails:\n{exc}"

    body = ocm.manifestwork_body(name, manifests)
    try:
        ocm.dry_run_manifestwork(cluster, body)
    except ApiException as exc:
        detail = exc.body or str(exc)
        return f"REJECTED by hub admission (Kyverno policy):\n{detail[:1500]}"

    prop = approvals.new_proposal(cluster, name, summary, manifests)
    return _json(
        {
            "proposal_id": prop.id,
            "status": "pending_approval",
            "next_step": (
                f"Ask the human operator to run: ocm-mcp approve {prop.id} "
                "and provide you the approval token."
            ),
        }
    )


@mcp.tool(annotations=APPLY)
@traced_tool
def apply_manifestwork(proposal_id: str, approval_token: str) -> str:
    """Apply a previously proposed ManifestWork. Requires a human-minted approval token.

    Args:
        proposal_id: id returned by propose_manifestwork.
        approval_token: token the operator produced with `ocm-mcp approve <id>`.
    """
    if msg := _writable():
        return msg
    try:
        prop = approvals.load_proposal(proposal_id)
        if prop.kind != "manifestwork":
            return (
                f"REJECTED: proposal {proposal_id} is a '{prop.action}' action, not a ManifestWork."
            )
        if prop.status != "pending":
            return f"REJECTED: proposal {proposal_id} is '{prop.status}', not pending."
        claims = approvals.verify_token(prop, approval_token, operation="apply", consume=True)
    except approvals.ApprovalError as exc:
        return f"REJECTED: {exc}"

    if msg := _content_intact(prop):
        return msg

    body = ocm.manifestwork_body(prop.name, prop.manifests)
    try:
        created = ocm.create_manifestwork(prop.cluster, body)
    except ApiException as exc:
        return f"FAILED to create ManifestWork: {(exc.body or str(exc))[:1500]}"

    prop.applied_work = prop.name
    prop.applied_uid = created.get("metadata", {}).get("uid", "")
    prop.approved_by = claims.get("approver", "")
    prop.set_status("applied")
    return _json(
        {
            "status": "applied",
            "cluster": prop.cluster,
            "manifestwork": prop.name,
            "note": "Verify rollout with get_cluster_health / get_manifestwork. To undo, call "
            "propose_rollback then apply the rollback with a fresh approval.",
        }
    )


@mcp.tool(annotations=PROPOSE)
@traced_tool
def propose_rollback(proposal_id: str) -> str:
    """Propose rolling back an applied ManifestWork. Applies nothing; needs its own approval.

    Args:
        proposal_id: id of an already-applied ManifestWork proposal.

    Creates a distinct rollback proposal bound to the exact ManifestWork name and UID.
    The human approves it separately (`ocm-mcp approve <rollback-id>`), and the token can
    only authorize a rollback - an old apply token can never delete a workload.
    """
    if msg := _writable():
        return msg
    try:
        applied = approvals.load_proposal(proposal_id)
    except approvals.ApprovalError as exc:
        return f"REJECTED: {exc}"
    if applied.kind != "manifestwork" or applied.status != "applied":
        return f"REJECTED: proposal {proposal_id} is not an applied ManifestWork."
    rb = approvals.new_rollback_proposal(
        applied, f"Roll back ManifestWork '{applied.applied_work}' on {applied.cluster}."
    )
    return _json(
        {
            "rollback_proposal_id": rb.id,
            "status": "pending_approval",
            "next_step": (
                f"Ask the human operator to run: ocm-mcp approve {rb.id} and give you the "
                f"token, then call rollback_manifestwork({rb.id}, <token>)."
            ),
        }
    )


@mcp.tool(annotations=APPLY)
@traced_tool
def rollback_manifestwork(rollback_proposal_id: str, approval_token: str) -> str:
    """Delete a ManifestWork after a rollback proposal has been approved.

    Args:
        rollback_proposal_id: id returned by propose_rollback.
        approval_token: a rollback token from `ocm-mcp approve <rollback-id>`.
    """
    if msg := _writable():
        return msg
    try:
        prop = approvals.load_proposal(rollback_proposal_id)
        if prop.kind != "rollback":
            return f"REJECTED: {rollback_proposal_id} is not a rollback proposal (call propose_rollback first)."
        if prop.status != "pending":
            return f"REJECTED: rollback proposal {rollback_proposal_id} is '{prop.status}', not pending."
        claims = approvals.verify_token(prop, approval_token, operation="rollback", consume=True)
    except approvals.ApprovalError as exc:
        return f"REJECTED: {exc}"

    if msg := _content_intact(prop):
        return msg

    work, uid = prop.params.get("target_work", ""), prop.params.get("target_uid", "")
    # Ownership check: only delete a ManifestWork this server created and that still has
    # the exact UID the human approved, so we never delete an unrelated or re-created work.
    try:
        current = ocm.get_manifestwork_object(prop.cluster, work)
    except ApiException as exc:
        return f"FAILED to read ManifestWork '{work}': {(exc.body or str(exc))[:800]}"
    labels = current.get("metadata", {}).get("labels", {})
    if labels.get("app.kubernetes.io/managed-by") != "ocm-mcp-server":
        return (
            f"REJECTED: ManifestWork '{work}' is not managed by ocm-mcp-server; refusing to delete."
        )
    if uid and current.get("metadata", {}).get("uid") != uid:
        return (
            f"REJECTED: ManifestWork '{work}' UID changed since approval; re-propose the rollback."
        )

    try:
        ocm.delete_manifestwork(prop.cluster, work)
    except ApiException as exc:
        return f"FAILED to delete ManifestWork: {(exc.body or str(exc))[:1500]}"

    prop.approved_by = claims.get("approver", "")
    prop.set_status("applied")
    try:
        origin = approvals.load_proposal(prop.params.get("origin", ""))
        origin.set_status("rolled_back")
    except approvals.ApprovalError:
        pass
    return _json({"status": "rolled_back", "cluster": prop.cluster, "manifestwork": work})


# ================================================================= toolset: addons


@mcp.tool(annotations=READ)
@traced_tool
def list_cluster_management_addons() -> str:
    """List fleet-level add-on definitions (ClusterManagementAddOn) and their install strategy."""
    return _read(ocm.list_cluster_management_addons)


@mcp.tool(annotations=READ)
@traced_tool
def get_addon_health() -> str:
    """Per-cluster add-on health across the fleet (ManagedClusterAddOn Available / Degraded)."""
    return _read(ocm.addon_health)


@mcp.tool(annotations=READ)
@traced_tool
def list_addons_for_cluster(cluster: str) -> str:
    """Every add-on installed on one cluster, with health (ManagedClusterAddOn in its namespace).

    Args:
        cluster: managed cluster name.
    """
    return _read(ocm.list_addons_for_cluster, cluster)


# =========================================================== toolset: registration


@mcp.tool(annotations=READ)
@traced_tool
def list_pending_csrs() -> str:
    """List pending cluster-join / add-on registration CSRs awaiting hub approval."""
    return _read(ocm.list_pending_csrs)


@mcp.tool(annotations=PROPOSE)
@traced_tool
def propose_cluster_action(cluster: str, action: str, summary: str, params_json: str = "{}") -> str:
    """Propose an OCM cluster lifecycle action. Does NOT apply anything.

    Args:
        cluster: target managed cluster name.
        action: one of 'cordon' (taint out of scheduling), 'uncordon' (undo cordon),
            'set_label' (params: {"key","value"}; empty value removes the label),
            'accept' (set hubAcceptsClient=true and approve pending join CSRs),
            'enable_addon' (params: {"addon","install_namespace"?}; create a
            ManagedClusterAddOn), 'disable_addon' (params: {"addon"}; delete it).
        summary: one or two sentences the human approver will read.
        params_json: JSON object of action parameters (set_label and the addon
            actions need it; cordon/uncordon/accept do not).

    The action is validated with a server-side dry-run, then stored pending. The
    human operator must run `ocm-mcp approve <id>` to mint the approval token.
    """
    if msg := _writable():
        return msg
    action = action.strip().lower()
    if action not in ALLOWED_CLUSTER_ACTIONS:
        return (
            f"REJECTED: '{action}' is not an allowed action. "
            f"Allowed: {sorted(ALLOWED_CLUSTER_ACTIONS)}."
        )
    try:
        params = json.loads(params_json) if params_json else {}
    except json.JSONDecodeError as exc:
        return f"REJECTED: params_json is not valid JSON: {exc}"
    if action == "set_label" and not params.get("key"):
        return 'REJECTED: set_label requires params_json like {"key": "...", "value": "..."}.'
    if action in ("enable_addon", "disable_addon") and not params.get("addon"):
        return f'REJECTED: {action} requires params_json like {{"addon": "..."}}.'

    try:
        ocm.validate_cluster_action(cluster, action, params)
        if action == "accept":
            # Capture the exact pending join CSRs NOW, so apply approves only these - the
            # human is approving these specific CSRs, not "whatever is pending at apply time".
            params["csrs"] = ocm.pending_csr_identities(cluster)
    except ApiException as exc:
        return f"REJECTED by hub admission: {(exc.body or str(exc))[:1200]}"
    except (ValueError, KeyError) as exc:
        return f"REJECTED: {exc}"

    prop = approvals.new_action_proposal(cluster, action, summary, params)
    return _json(
        {
            "proposal_id": prop.id,
            "status": "pending_approval",
            "action": action,
            "next_step": (
                f"Ask the human operator to run: ocm-mcp approve {prop.id} "
                "and provide you the approval token, then call apply_cluster_action."
            ),
        }
    )


@mcp.tool(annotations=APPLY)
@traced_tool
def apply_cluster_action(proposal_id: str, approval_token: str) -> str:
    """Apply a previously proposed cluster lifecycle action. Requires a human-minted token.

    Args:
        proposal_id: id returned by propose_cluster_action.
        approval_token: token the operator produced with `ocm-mcp approve <id>`.
    """
    if msg := _writable():
        return msg
    try:
        prop = approvals.load_proposal(proposal_id)
        if prop.kind != "action":
            return f"REJECTED: proposal {proposal_id} is a ManifestWork, not a cluster action."
        if prop.status != "pending":
            return f"REJECTED: proposal {proposal_id} is '{prop.status}', not pending."
        claims = approvals.verify_token(prop, approval_token, operation="apply", consume=True)
    except approvals.ApprovalError as exc:
        return f"REJECTED: {exc}"

    if msg := _content_intact(prop):
        return msg

    try:
        result = ocm.apply_cluster_action(prop.cluster, prop.action, prop.params)
    except ApiException as exc:
        return f"FAILED to apply action: {(exc.body or str(exc))[:1500]}"

    prop.approved_by = claims.get("approver", "")
    prop.set_status("applied")
    return _json(result)


# =============================================================== toolset: policy


@mcp.tool(annotations=READ)
@traced_tool
def list_policies(namespace: str = "") -> str:
    """List governance Policies and per-cluster compliance (only if the add-on is installed).

    Args:
        namespace: limit to one namespace; empty lists across all namespaces.
    """
    return _read(ocm.list_policies, namespace=namespace)


@mcp.tool(annotations=READ)
@traced_tool
def list_policy_violations() -> str:
    """Only the NonCompliant / Pending Policy-cluster pairs across the fleet - the open risks."""
    return _read(ocm.list_policy_violations)


# ==================================================== toolset: hosted-control-planes


@mcp.tool(annotations=READ)
@traced_tool
def list_hosted_clusters(namespace: str = "") -> str:
    """List HyperShift HostedClusters, when the hub is the HCP hosting cluster.

    Args:
        namespace: limit to one namespace; empty lists across all namespaces.

    HostedCluster objects live on whichever cluster hosts the control plane. If your
    HCPs are hosted on a separate management cluster, they are not on this hub - this
    reports that clearly, and the spokes still appear via list_clusters.
    """
    return _read(ocm.list_hosted_clusters, namespace=namespace)


@mcp.tool(annotations=READ)
@traced_tool
def get_hosted_cluster(name: str, namespace: str) -> str:
    """Detailed HostedCluster: version, conditions, and its NodePools.

    Args:
        name: HostedCluster name.
        namespace: the namespace the HostedCluster lives in (its hosting namespace).
    """
    return _read(ocm.get_hosted_cluster, name, namespace)


@mcp.tool(annotations=READ)
@traced_tool
def list_node_pools(namespace: str = "", cluster: str = "") -> str:
    """List HyperShift NodePools (worker groups), optionally filtered to one HostedCluster.

    Args:
        namespace: limit to one namespace; empty lists across all namespaces.
        cluster: optional HostedCluster name to filter node pools by.
    """
    return _read(ocm.list_node_pools, namespace=namespace, cluster=cluster)


# ============================================================= toolset: resources


@mcp.tool(annotations=READ)
@traced_tool
def list_resources(resource: str, namespace: str = "") -> str:
    """Generic list over an allow-list of OCM API types (identity + conditions only).

    Args:
        resource: an OCM resource type, e.g. managedclusters, placements,
            placementdecisions, manifestworks, managedclusteraddons,
            clustermanagementaddons, managedclustersets, policies, klusterlets.
        namespace: for namespaced types, limit to one namespace; empty lists all.

    Only Open Cluster Management types are allowed. Secrets and other credential
    resources are not on the allow-list and cannot be read through this tool.
    """
    return _read(ocm.list_resources, resource, namespace=namespace)


@mcp.tool(annotations=READ)
@traced_tool
def get_resource(resource: str, name: str, namespace: str = "") -> str:
    """Generic get of one allow-listed OCM resource, in full.

    Args:
        resource: an OCM resource type (see list_resources for the allow-list).
        name: object name.
        namespace: required for namespaced types (usually the cluster namespace).

    Never returns a Secret: Secrets are not on the allow-list, so this capability
    does not exist rather than being merely restricted.
    """
    return _read(ocm.get_resource, resource, name, namespace=namespace)


# ================================================================== toolset: audit


@mcp.tool(annotations=READ)
@traced_tool
def list_pending_proposals() -> str:
    """List proposals (ManifestWorks and cluster actions) waiting for human approval."""
    return _json(
        [
            {
                "id": p.id,
                "cluster": p.cluster,
                "kind": p.kind,
                "action": p.action,
                "name": p.name,
                "summary": p.summary,
            }
            for p in approvals.list_proposals(status="pending")
        ]
    )


@mcp.tool(annotations=READ)
@traced_tool
def get_audit_trail(last_n: int = 30) -> str:
    """Return the last N entries of this server's own tool-call audit log.

    Args:
        last_n: number of trailing audit entries to return (default 30).

    Use this at the end of an incident to write an accurate post-incident report
    of what was inspected, proposed, approved, and applied - from the record, not
    from memory.
    """
    path = SETTINGS.audit_log
    if not path.exists():
        return "[]"
    # Stream the tail with a bounded deque so a large audit log is never fully read.
    from collections import deque

    with path.open() as f:
        lines = [ln.strip() for ln in deque(f, maxlen=max(1, last_n)) if ln.strip()]
    return "[\n" + ",\n".join(lines) + "\n]" if lines else "[]"


# ===================================================================== prompts


@mcp.prompt()
def diagnose_fleet() -> str:
    """Sweep the whole fleet and summarize what is unhealthy and why, without changing anything."""
    return (
        "You are operating a Kubernetes fleet through the OCM hub. Investigate only - "
        "do not propose or apply anything yet.\n\n"
        "1. Call list_clusters to see availability, version, and capacity of every cluster.\n"
        "2. Call get_addon_health to spot Degraded or unavailable add-ons across the fleet.\n"
        "3. For any cluster that is Unavailable or not joined, call get_cluster to read its "
        "conditions, then get_cluster_health for unhealthy pods and degraded deployments.\n"
        "4. For each unhealthy workload, use query_events and get_pod_logs to find the cause.\n"
        "5. Produce a concise report: per cluster, what is wrong, the evidence, and the "
        "smallest safe remediation you would propose. Do not act on it yet."
    )


@mcp.prompt()
def remediate_with_approval(symptom: str) -> str:
    """Investigate a symptom, propose the smallest safe fix, and wait for a human approval token."""
    return (
        f"A fleet operator reports: {symptom}\n\n"
        "Follow the safe remediation workflow:\n"
        "1. Investigate with the read tools (list_clusters, get_cluster_health, query_events, "
        "get_pod_logs, get_manifestwork) until you can name the root cause with evidence.\n"
        "2. Decide the smallest change that fixes it. For a workload change, call "
        "propose_manifestwork with pinned images and a precise summary. For a cluster "
        "lifecycle change (cordon, uncordon, set a label, accept a cluster), call "
        "propose_cluster_action.\n"
        "3. If the proposal is REJECTED by static guardrails or Kyverno, read the reason, "
        "correct the manifest, and propose again. Never try to bypass a rejection.\n"
        "4. Tell the operator the proposal id and ask them to run `ocm-mcp approve <id>` and "
        "give you the token. Wait for it.\n"
        "5. Call the matching apply tool with the token. Then verify recovery with reads.\n"
        "6. Finish by calling get_audit_trail and writing an accurate incident summary."
    )


@mcp.prompt()
def incident_postmortem() -> str:
    """Write a post-incident report strictly from the audit trail, not from memory."""
    return (
        "Write a post-incident report for the change just completed. Base every statement "
        "on evidence, not recollection:\n\n"
        "1. Call get_audit_trail to retrieve the ordered record of tool calls.\n"
        "2. Reconstruct the timeline: what was inspected, what was proposed, which proposal "
        "was approved, and what was applied or rolled back.\n"
        "3. State the root cause, the remediation, and how recovery was verified.\n"
        "4. Note any proposals that were rejected and why, as evidence the guardrails held.\n"
        "5. Keep it factual and concise. If the audit log does not support a claim, do not "
        "make it."
    )


@mcp.prompt()
def why_not_scheduled(cluster: str, placement: str, namespace: str) -> str:
    """Explain why a cluster was or was not selected by a Placement, from the live objects."""
    return (
        f"Explain why cluster '{cluster}' was or was not selected by Placement "
        f"'{placement}' in namespace '{namespace}'. Use only reads:\n\n"
        f"1. get_placement_decision('{placement}', '{namespace}') for the clusters actually chosen.\n"
        f"2. list_placements to read the Placement's clusterSets and selection intent.\n"
        f"3. get_cluster('{cluster}') for its labels, ClusterClaims, and taints.\n"
        f"4. list_cluster_set_bindings to confirm the Placement's namespace is bound to the "
        "ClusterSet the cluster belongs to.\n"
        f"5. list_addon_placement_scores('{cluster}') if the Placement uses AddOn prioritizers.\n"
        "6. Conclude with the specific reason: not in a bound ClusterSet, failed a predicate, "
        "carries a NoSelect taint, or simply out-scored by others."
    )


@mcp.prompt()
def onboard_cluster(cluster: str) -> str:
    """Safely accept a pending cluster into the fleet, through the approval gate."""
    return (
        f"A new cluster '{cluster}' is trying to join the hub. Onboard it safely:\n\n"
        "1. Call list_pending_csrs to see the pending cluster-join CSRs and confirm one "
        f"belongs to '{cluster}'.\n"
        f"2. Call get_cluster('{cluster}') to check its current acceptance and conditions.\n"
        f"3. Propose acceptance: propose_cluster_action('{cluster}', 'accept', <summary>). This "
        "sets hubAcceptsClient and approves the pending join CSRs, but applies nothing yet.\n"
        "4. Give the operator the proposal id, ask them to run `ocm-mcp approve <id>`, and wait "
        "for the token.\n"
        "5. Call apply_cluster_action with the token, then verify with get_cluster and "
        "get_addon_health that the cluster becomes Available and its agents register."
    )


@mcp.prompt()
def addon_troubleshoot(addon: str) -> str:
    """Diagnose a degraded add-on across the fleet, reads only."""
    return (
        f"The '{addon}' add-on looks unhealthy somewhere in the fleet. Investigate without "
        "changing anything:\n\n"
        "1. Call get_addon_health to find every cluster where an add-on is Degraded or not "
        f"Available, and confirm which clusters have '{addon}' unhealthy.\n"
        "2. For each affected cluster, call list_addons_for_cluster(cluster) for the add-on's "
        "install namespace and conditions.\n"
        "3. Call list_cluster_management_addons to read the fleet-level install strategy for "
        f"'{addon}'.\n"
        "4. If a spoke context is configured, use get_cluster_health, query_events, and "
        "get_pod_logs in the add-on's install namespace to find the root cause.\n"
        "5. Report the affected clusters, the evidence, and the smallest safe remediation. If it "
        "means re-enabling the add-on, propose it with propose_cluster_action(..., 'enable_addon')."
    )


@mcp.prompt()
def hosted_cluster_health(cluster: str) -> str:
    """Assess the health of a HyperShift hosted control plane and its node pools."""
    return (
        f"Assess the health of hosted cluster '{cluster}'. Reads only:\n\n"
        "1. Call list_hosted_clusters to locate it and read its version and conditions. If the "
        "HostedCluster API is not on this hub, the HCP is hosted elsewhere - fall back to the "
        f"ManagedCluster view with get_cluster('{cluster}') and get_cluster_info('{cluster}').\n"
        "2. Call get_hosted_cluster(name, namespace) for its version history, control-plane "
        "conditions, and node pools.\n"
        "3. Check the NodePools' desired vs current replicas for capacity or scaling problems.\n"
        f"4. Cross-check the spoke side: get_cluster('{cluster}') for hub availability and "
        f"get_addon_health for its add-ons.\n"
        "5. Summarize: control-plane state, worker capacity, and anything degraded, with the "
        "evidence for each claim."
    )


@mcp.prompt()
def policy_compliance_report() -> str:
    """Summarize governance policy compliance across the fleet, reads only."""
    return (
        "Produce a governance compliance report for the fleet. Reads only:\n\n"
        "1. Call list_policy_violations for every NonCompliant or Pending policy-cluster pair.\n"
        "2. Call list_policies for the full picture, including which policies are inform vs "
        "enforce (remediationAction).\n"
        "3. Group the violations by policy and by cluster; call out anything Pending separately "
        "from NonCompliant.\n"
        "4. For the highest-impact violations, note whether the policy is inform (visibility "
        "only) or enforce (actively remediating).\n"
        "5. Present a concise table and a short prioritized list of what to fix first. Propose no "
        "changes - this is a report."
    )


@mcp.prompt()
def capacity_report() -> str:
    """Find clusters with spare capacity and clusters under pressure, reads only."""
    return (
        "Report on fleet capacity so an operator can place new workloads well. Reads only:\n\n"
        "1. Call list_clusters for each cluster's capacity and availability.\n"
        "2. Call get_cluster on the candidates to compare capacity against allocatable.\n"
        "3. Where available, call get_cluster_info for node counts and per-node capacity, and "
        "list_addon_placement_scores for any custom scores prioritizers use.\n"
        "4. Rank clusters by headroom; flag any that are Unavailable, cordoned (NoSelect taint), "
        "or nearly full.\n"
        "5. Recommend where a new workload should land, and note any cluster that needs "
        "attention before it can take more."
    )


@mcp.prompt()
def rollout_status(name: str, namespace: str) -> str:
    """Track a ManifestWorkReplicaSet rollout across the clusters a Placement selected."""
    return (
        f"Report the rollout status of ManifestWorkReplicaSet '{name}' in namespace "
        f"'{namespace}'. Reads only:\n\n"
        "1. Call list_manifestworkreplicasets to read its summary (total / applied / available / "
        "progressing / degraded) and conditions.\n"
        "2. Identify the Placement it targets, then call get_placement_decision to list the "
        "clusters in scope.\n"
        "3. For any cluster that looks stuck, call get_manifestwork(cluster, <name>) to read the "
        "per-resource conditions and status feedback and find what is blocking Apply/Available.\n"
        "4. Summarize progress across the fleet and name the specific clusters and resources that "
        "are not yet healthy, with evidence."
    )


def main() -> None:
    port = os.environ.get("OCM_MCP_METRICS_PORT", "").strip()
    if port.isdigit():
        from . import metrics

        metrics.start_metrics_server(int(port))
    mcp.run()


if __name__ == "__main__":
    main()
