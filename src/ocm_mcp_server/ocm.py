# SPDX-FileCopyrightText: 2026 Sandeep Bazar
# SPDX-License-Identifier: Apache-2.0

"""Open Cluster Management API operations (hub side).

Wraps ManagedCluster (cluster.open-cluster-management.io/v1) and ManifestWork
(work.open-cluster-management.io/v1) with small, typed, agent-friendly results:
no raw multi-thousand-line objects, just the fields an operator would look at.
"""

from __future__ import annotations

from typing import Any

from kubernetes.client import ApiException

from .k8s import OCM_CLUSTER_GROUP, OCM_WORK_GROUP, hub_custom, spoke_apps, spoke_core


def _condition_map(obj: dict[str, Any]) -> dict[str, str]:
    return {
        c.get("type", "?"): c.get("status", "?")
        for c in obj.get("status", {}).get("conditions", [])
    }


def list_managed_clusters() -> list[dict[str, Any]]:
    res = hub_custom().list_cluster_custom_object(
        OCM_CLUSTER_GROUP, "v1", "managedclusters"
    )
    out = []
    for item in res.get("items", []):
        conds = _condition_map(item)
        out.append(
            {
                "name": item["metadata"]["name"],
                "labels": item["metadata"].get("labels", {}),
                "available": conds.get("ManagedClusterConditionAvailable", "Unknown"),
                "joined": conds.get("ManagedClusterJoined", "Unknown"),
                "kubernetes_version": item.get("status", {})
                .get("version", {})
                .get("kubernetes", "unknown"),
                "capacity": {
                    k: v
                    for k, v in item.get("status", {}).get("capacity", {}).items()
                    if k in ("cpu", "memory")
                },
            }
        )
    return out


def cluster_health(cluster: str) -> dict[str, Any]:
    """Hub view (conditions) + spoke view (unhealthy pods, deployment status)."""
    obj = hub_custom().get_cluster_custom_object(
        OCM_CLUSTER_GROUP, "v1", "managedclusters", cluster
    )
    health: dict[str, Any] = {
        "cluster": cluster,
        "hub_conditions": _condition_map(obj),
        "unhealthy_pods": [],
        "degraded_deployments": [],
        "spoke_view": "unavailable (no read context configured)",
    }
    try:
        core = spoke_core(cluster)
        apps = spoke_apps(cluster)
    except LookupError:
        return health

    health["spoke_view"] = "ok"
    for pod in core.list_pod_for_all_namespaces(limit=500).items:
        phase = pod.status.phase
        waiting_reasons = [
            cs.state.waiting.reason
            for cs in (pod.status.container_statuses or [])
            if cs.state and cs.state.waiting and cs.state.waiting.reason
        ]
        restarts = sum(cs.restart_count for cs in (pod.status.container_statuses or []))
        if phase not in ("Running", "Succeeded") or waiting_reasons or restarts > 3:
            health["unhealthy_pods"].append(
                {
                    "namespace": pod.metadata.namespace,
                    "name": pod.metadata.name,
                    "phase": phase,
                    "waiting": waiting_reasons,
                    "restarts": restarts,
                }
            )
    for dep in apps.list_deployment_for_all_namespaces(limit=500).items:
        desired = dep.spec.replicas or 0
        ready = dep.status.ready_replicas or 0
        if ready < desired:
            health["degraded_deployments"].append(
                {
                    "namespace": dep.metadata.namespace,
                    "name": dep.metadata.name,
                    "ready": f"{ready}/{desired}",
                }
            )
    return health


def cluster_events(cluster: str, namespace: str = "", limit: int = 40) -> list[dict[str, Any]]:
    core = spoke_core(cluster)
    if namespace:
        events = core.list_namespaced_event(namespace, limit=limit)
    else:
        events = core.list_event_for_all_namespaces(limit=limit)
    items = sorted(
        events.items,
        key=lambda e: (e.last_timestamp or e.event_time or e.metadata.creation_timestamp),
        reverse=True,
    )
    return [
        {
            "namespace": e.metadata.namespace,
            "type": e.type,
            "reason": e.reason,
            "object": f"{e.involved_object.kind}/{e.involved_object.name}",
            "count": e.count,
            "message": (e.message or "")[:400],
        }
        for e in items[:limit]
    ]


def pod_logs(cluster: str, namespace: str, pod: str, container: str = "", lines: int = 80) -> str:
    core = spoke_core(cluster)
    try:
        return core.read_namespaced_pod_log(
            pod,
            namespace,
            container=container or None,
            tail_lines=lines,
            previous=False,
        )
    except ApiException as exc:
        if exc.status == 400 and "previous" not in str(exc):
            # container may be crashing; try previous instance
            return core.read_namespaced_pod_log(
                pod, namespace, container=container or None, tail_lines=lines, previous=True
            )
        raise


def list_manifestworks(cluster: str) -> list[dict[str, Any]]:
    res = hub_custom().list_namespaced_custom_object(
        OCM_WORK_GROUP, "v1", cluster, "manifestworks"
    )
    out = []
    for item in res.get("items", []):
        conds = _condition_map(item)
        out.append(
            {
                "name": item["metadata"]["name"],
                "applied": conds.get("Applied", "Unknown"),
                "available": conds.get("Available", "Unknown"),
                "resources": [
                    f"{rm.get('kind', '?')}/{rm.get('name', '?')} ({rm.get('namespace', '-')})"
                    for man in item.get("status", {})
                    .get("resourceStatus", {})
                    .get("manifests", [])
                    for rm in (man.get("resourceMeta", {}),)
                ],
            }
        )
    return out


def manifestwork_body(name: str, manifests: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "apiVersion": f"{OCM_WORK_GROUP}/v1",
        "kind": "ManifestWork",
        "metadata": {"name": name, "labels": {"app.kubernetes.io/managed-by": "ocm-mcp-server"}},
        "spec": {"workload": {"manifests": manifests}},
    }


def dry_run_manifestwork(cluster: str, body: dict[str, Any]) -> None:
    """Server-side dry-run create on the hub.

    Kyverno's validating webhooks run during admission, so hub policies reject
    non-compliant ManifestWorks here - before anything is stored or applied.
    Raises kubernetes.client.ApiException on rejection.
    """
    hub_custom().create_namespaced_custom_object(
        OCM_WORK_GROUP, "v1", cluster, "manifestworks", body, dry_run="All"
    )


def create_manifestwork(cluster: str, body: dict[str, Any]) -> dict[str, Any]:
    return hub_custom().create_namespaced_custom_object(
        OCM_WORK_GROUP, "v1", cluster, "manifestworks", body
    )


def delete_manifestwork(cluster: str, name: str) -> None:
    hub_custom().delete_namespaced_custom_object(
        OCM_WORK_GROUP, "v1", cluster, "manifestworks", name
    )
