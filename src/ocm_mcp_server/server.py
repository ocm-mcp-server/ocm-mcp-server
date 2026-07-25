# SPDX-FileCopyrightText: 2026 Sandeep Bazar <sandeepbazar@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""The MCP server: a deliberately small tool surface over an OCM hub.

Read tools are free. Write tools are gated:
    propose_manifestwork  -> static guardrails + Kyverno dry-run, then stored pending
    apply_manifestwork    -> requires a human-minted approval token
    rollback_manifestwork -> requires a human-minted approval token

The agent never sees a kubeconfig, a secret, or an exec socket. There is no
tool that can read Secrets, exec into pods, or delete arbitrary resources  - 
by design, not by prompt.
"""

from __future__ import annotations

import json
from typing import Any

from kubernetes.client import ApiException
from mcp.server.fastmcp import FastMCP

from . import approvals, guardrails, ocm
from .config import SETTINGS
from .tracing import traced_tool

mcp = FastMCP(
    "ocm-mcp-server",
    instructions=(
        "Tools for operating a multi-cluster Kubernetes fleet through an Open Cluster "
        "Management hub. Investigate freely with the read tools. Any change must be "
        "proposed with propose_manifestwork and will only apply after a human approves "
        "it out-of-band; ask the operator to run `ocm-mcp approve <proposal-id>` and "
        "give you the token. Never claim a change is applied unless apply_manifestwork "
        "returned success."
    ),
)


def _json(data: Any) -> str:
    return json.dumps(data, indent=2, default=str)


# --------------------------------------------------------------------------- reads


@mcp.tool()
@traced_tool
def list_clusters() -> str:
    """List all managed clusters with availability, version, labels, and capacity."""
    return _json(ocm.list_managed_clusters())


@mcp.tool()
@traced_tool
def get_cluster_health(cluster: str) -> str:
    """Health summary for one cluster: hub conditions, unhealthy pods, degraded deployments."""
    return _json(ocm.cluster_health(cluster))


@mcp.tool()
@traced_tool
def query_events(cluster: str, namespace: str = "", limit: int = 40) -> str:
    """Recent Kubernetes events from a managed cluster, newest first.

    Optionally filter by namespace. Use this to find the 'why' behind unhealthy pods.
    """
    return _json(ocm.cluster_events(cluster, namespace=namespace, limit=limit))


@mcp.tool()
@traced_tool
def get_pod_logs(
    cluster: str, namespace: str, pod: str, container: str = "", lines: int = 80
) -> str:
    """Tail logs from a pod on a managed cluster (falls back to the previous
    container instance if the current one is crashing)."""
    return ocm.pod_logs(cluster, namespace, pod, container=container, lines=lines)


@mcp.tool()
@traced_tool
def list_manifestworks(cluster: str) -> str:
    """List ManifestWorks currently targeting a cluster (what the hub is managing there)."""
    return _json(ocm.list_manifestworks(cluster))


@mcp.tool()
@traced_tool
def list_pending_proposals() -> str:
    """List proposals waiting for human approval."""
    return _json(
        [
            {"id": p.id, "cluster": p.cluster, "name": p.name, "summary": p.summary}
            for p in approvals.list_proposals(status="pending")
        ]
    )


@mcp.tool()
@traced_tool
def get_audit_trail(last_n: int = 30) -> str:
    """Return the last N entries of this server's own tool-call audit log.

    Use this at the end of an incident to write an accurate post-incident
    report of what was inspected, what was proposed, what was approved, and
    what was applied - from the record, not from memory.
    """
    path = SETTINGS.audit_log
    if not path.exists():
        return "[]"
    lines = path.read_text().strip().splitlines()[-last_n:]
    return "[\n" + ",\n".join(lines) + "\n]"


# -------------------------------------------------------------------------- writes


@mcp.tool()
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


@mcp.tool()
@traced_tool
def apply_manifestwork(proposal_id: str, approval_token: str) -> str:
    """Apply a previously proposed ManifestWork. Requires a human-minted approval token."""
    try:
        prop = approvals.load_proposal(proposal_id)
        if prop.status != "pending":
            return f"REJECTED: proposal {proposal_id} is '{prop.status}', not pending."
        approvals.verify_token(prop, approval_token)
    except approvals.ApprovalError as exc:
        return f"REJECTED: {exc}"

    body = ocm.manifestwork_body(prop.name, prop.manifests)
    try:
        ocm.create_manifestwork(prop.cluster, body)
    except ApiException as exc:
        return f"FAILED to create ManifestWork: {(exc.body or str(exc))[:1500]}"

    prop.status = "applied"
    prop.applied_work = prop.name
    prop.save()
    return _json(
        {
            "status": "applied",
            "cluster": prop.cluster,
            "manifestwork": prop.name,
            "note": "Verify rollout with get_cluster_health / list_manifestworks.",
        }
    )


@mcp.tool()
@traced_tool
def rollback_manifestwork(proposal_id: str, approval_token: str) -> str:
    """Delete the ManifestWork created from an applied proposal. Requires approval."""
    try:
        prop = approvals.load_proposal(proposal_id)
        if prop.status != "applied":
            return f"REJECTED: proposal {proposal_id} is '{prop.status}', not applied."
        approvals.verify_token(prop, approval_token)
    except approvals.ApprovalError as exc:
        return f"REJECTED: {exc}"

    try:
        ocm.delete_manifestwork(prop.cluster, prop.applied_work)
    except ApiException as exc:
        return f"FAILED to delete ManifestWork: {(exc.body or str(exc))[:1500]}"

    prop.status = "rolled_back"
    prop.save()
    return _json({"status": "rolled_back", "cluster": prop.cluster, "manifestwork": prop.name})


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
