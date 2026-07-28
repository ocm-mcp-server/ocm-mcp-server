# SPDX-FileCopyrightText: 2026 Sandeep Bazar
# SPDX-License-Identifier: Apache-2.0

"""Open Cluster Management API operations (hub side).

Wraps ManagedCluster (cluster.open-cluster-management.io/v1) and ManifestWork
(work.open-cluster-management.io/v1) with small, typed, agent-friendly results:
no raw multi-thousand-line objects, just the fields an operator would look at.
"""

from __future__ import annotations

import base64
import binascii
import concurrent.futures
import hashlib
import os
from typing import Any

from kubernetes.client import ApiException

from .config import CORDON_TAINT_KEY, READABLE_RESOURCES
from .k8s import (
    HYPERSHIFT_GROUP,
    OCM_ADDON_GROUP,
    OCM_CLUSTER_GROUP,
    OCM_INTERNAL_GROUP,
    OCM_POLICY_GROUP,
    OCM_WORK_GROUP,
    hub_certificates,
    hub_custom,
    spoke_apps,
    spoke_core,
)

# ACM compliance states that mean "not healthy" for a violations rollup.
NONCOMPLIANT_STATES = ("NonCompliant", "Pending")

# Spoke reads are bounded and time-limited so one very large managed cluster cannot
# hang a tool call or pull an unbounded object set into memory.
SPOKE_TIMEOUT = (5, int(os.environ.get("OCM_MCP_SPOKE_TIMEOUT", "30")))
HEALTH_LIMIT = int(os.environ.get("OCM_MCP_HEALTH_LIMIT", "500"))

# Fleet-wide health fanout: concurrent spoke scans bounded to prevent resource exhaustion.
FANOUT_WORKERS = int(os.environ.get("OCM_MCP_FANOUT_WORKERS", "8"))

# Label OCM stamps on a PlacementDecision to link it to its Placement, and the one
# that records a ManagedCluster's ClusterSet membership.
PLACEMENT_LABEL = "cluster.open-cluster-management.io/placement"
CLUSTERSET_LABEL = "cluster.open-cluster-management.io/clusterset"

# Hub reads are paged so a large fleet does not arrive as one unbounded response.
# LIST_MAX_ITEMS is a safety ceiling; hitting it marks the result as truncated.
LIST_PAGE_SIZE = int(os.environ.get("OCM_MCP_LIST_PAGE_SIZE", "500"))
LIST_MAX_ITEMS = int(os.environ.get("OCM_MCP_LIST_MAX_ITEMS", "5000"))


def paged_list(list_fn: Any, *args: Any, **kwargs: Any) -> dict[str, Any]:
    """Call a Kubernetes list function with server-side pagination.

    Follows metadata.continue tokens so the apiserver streams pages of
    LIST_PAGE_SIZE instead of materializing the whole collection at once, and
    stops at LIST_MAX_ITEMS with an explicit "truncated" note - silent
    truncation would read as "that's everything" when it isn't.
    """
    items: list[Any] = []
    cont = ""
    truncated = False
    while True:
        if cont:
            kwargs["_continue"] = cont
        res = list_fn(*args, limit=LIST_PAGE_SIZE, **kwargs)
        items.extend(res.get("items", []) or [])
        cont = (res.get("metadata") or {}).get("continue") or ""
        if not cont:
            break
        if len(items) >= LIST_MAX_ITEMS:
            truncated = True
            break
    out: dict[str, Any] = {"items": items}
    if truncated:
        out["truncated"] = (
            f"result truncated at {LIST_MAX_ITEMS} items; narrow the query or raise "
            "OCM_MCP_LIST_MAX_ITEMS"
        )
    return out


def _fanout_workers() -> int:
    """Bounded concurrency for fleet-wide spoke scans (floor 1)."""
    return max(1, int(os.environ.get("OCM_MCP_FANOUT_WORKERS", "8")))


class FeatureNotInstalled(LookupError):
    """A requested OCM API type is not served by this hub (add-on not installed)."""


def _condition_map(obj: dict[str, Any]) -> dict[str, str]:
    return {
        c.get("type", "?"): c.get("status", "?")
        for c in obj.get("status", {}).get("conditions", [])
    }


def _summarize(item: dict[str, Any]) -> dict[str, Any]:
    """Trim a raw object to the fields an operator scans: identity, labels, conditions."""
    meta = item.get("metadata", {})
    summary: dict[str, Any] = {"name": meta.get("name")}
    if meta.get("namespace"):
        summary["namespace"] = meta["namespace"]
    labels = meta.get("labels", {})
    if labels:
        summary["labels"] = labels
    conds = _condition_map(item)
    if conds:
        summary["conditions"] = conds
    return summary


def list_managed_clusters() -> list[dict[str, Any]]:
    res = paged_list(
        hub_custom().list_cluster_custom_object, OCM_CLUSTER_GROUP, "v1", "managedclusters"
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


def _spoke_health(cluster: str) -> dict[str, Any]:
    """Pod/deployment scan of one spoke. Raises LookupError without a spoke context."""
    core = spoke_core(cluster)
    apps = spoke_apps(cluster)
    out: dict[str, Any] = {"unhealthy_pods": [], "degraded_deployments": []}
    pods = core.list_pod_for_all_namespaces(limit=HEALTH_LIMIT, _request_timeout=SPOKE_TIMEOUT)
    if pods.metadata._continue:
        out["note"] = (
            f"cluster has more than {HEALTH_LIMIT} pods; showing the first {HEALTH_LIMIT}. "
            "Raise OCM_MCP_HEALTH_LIMIT or scope by namespace for full coverage."
        )
    for pod in pods.items:
        phase = pod.status.phase
        waiting_reasons = [
            cs.state.waiting.reason
            for cs in (pod.status.container_statuses or [])
            if cs.state and cs.state.waiting and cs.state.waiting.reason
        ]
        restarts = sum(cs.restart_count for cs in (pod.status.container_statuses or []))
        if phase not in ("Running", "Succeeded") or waiting_reasons or restarts > 3:
            out["unhealthy_pods"].append(
                {
                    "namespace": pod.metadata.namespace,
                    "name": pod.metadata.name,
                    "phase": phase,
                    "waiting": waiting_reasons,
                    "restarts": restarts,
                }
            )
    deployments = apps.list_deployment_for_all_namespaces(
        limit=HEALTH_LIMIT, _request_timeout=SPOKE_TIMEOUT
    )
    for dep in deployments.items:
        desired = dep.spec.replicas or 0
        ready = dep.status.ready_replicas or 0
        if ready < desired:
            out["degraded_deployments"].append(
                {
                    "namespace": dep.metadata.namespace,
                    "name": dep.metadata.name,
                    "ready": f"{ready}/{desired}",
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
        spoke = _spoke_health(cluster)
    except LookupError:
        return health
    health["spoke_view"] = "ok"
    health.update(spoke)
    return health


def fleet_health(clusters: str = "") -> dict[str, Any]:
    """Whole-fleet health in one call: hub conditions from ONE paged list, spoke
    pod/deployment scans fanned out on a bounded thread pool. A slow or broken
    cluster becomes a per-cluster 'error' entry - it never fails the sweep."""
    res = paged_list(
        hub_custom().list_cluster_custom_object, OCM_CLUSTER_GROUP, "v1", "managedclusters"
    )
    hub = {c["metadata"]["name"]: c for c in res.get("items", [])}
    wanted = [c.strip() for c in clusters.split(",") if c.strip()] or sorted(hub)

    def scan(name: str) -> dict[str, Any]:
        if name not in hub:
            return {"cluster": name, "error": f"'{name}' not found on the hub"}
        conds = _condition_map(hub[name])
        entry: dict[str, Any] = {
            "cluster": name,
            "available": conds.get("ManagedClusterConditionAvailable", "Unknown"),
            "hub_conditions": conds,
            "unhealthy_pods": [],
            "degraded_deployments": [],
            "spoke_view": "unavailable (no read context configured)",
        }
        try:
            spoke = _spoke_health(name)
        except LookupError:
            return entry
        except Exception as exc:  # noqa: BLE001 - isolation is the contract
            entry["error"] = f"{type(exc).__name__}: {exc}"
            return entry
        entry["spoke_view"] = "ok"
        entry.update(spoke)
        return entry

    with concurrent.futures.ThreadPoolExecutor(max_workers=_fanout_workers()) as pool:
        entries = list(pool.map(scan, wanted))

    def has_issues(e: dict[str, Any]) -> bool:
        return bool(
            e.get("error")
            or e.get("unhealthy_pods")
            or e.get("degraded_deployments")
            or e.get("available") != "True"
        )

    entries.sort(key=lambda e: (not has_issues(e), e["cluster"]))
    avail = sum(
        1
        for c in hub.values()
        if _condition_map(c).get("ManagedClusterConditionAvailable") == "True"
    )
    return {
        "fleet": {
            "total": len(hub),
            "available": avail,
            "unavailable": len(hub) - avail,
            "spoke_checked": sum(1 for e in entries if e.get("spoke_view") == "ok"),
            "with_issues": sum(1 for e in entries if has_issues(e)),
        },
        "clusters": entries,
    }


def cluster_events(cluster: str, namespace: str = "", limit: int = 40) -> list[dict[str, Any]]:
    core = spoke_core(cluster)
    # The events API is not time-ordered, so limiting to N then sorting would miss newer
    # events on a busy cluster. Fetch a wider bounded window, sort by time, then slice.
    fetch = min(500, max(limit * 10, 100))
    if namespace:
        events = core.list_namespaced_event(namespace, limit=fetch, _request_timeout=SPOKE_TIMEOUT)
    else:
        events = core.list_event_for_all_namespaces(limit=fetch, _request_timeout=SPOKE_TIMEOUT)
    items = sorted(
        events.items,
        key=lambda e: e.last_timestamp or e.event_time or e.metadata.creation_timestamp,
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
            _request_timeout=SPOKE_TIMEOUT,
        )
    except ApiException as exc:
        if exc.status == 400 and "previous" not in str(exc):
            # container may be crashing; try previous instance
            return core.read_namespaced_pod_log(
                pod,
                namespace,
                container=container or None,
                tail_lines=lines,
                previous=True,
                _request_timeout=SPOKE_TIMEOUT,
            )
        raise


def list_manifestworks(cluster: str) -> list[dict[str, Any]]:
    res = paged_list(
        hub_custom().list_namespaced_custom_object, OCM_WORK_GROUP, "v1", cluster, "manifestworks"
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
                    for man in item.get("status", {}).get("resourceStatus", {}).get("manifests", [])
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


def get_manifestwork_object(cluster: str, name: str) -> dict[str, Any]:
    """The raw ManifestWork object (labels, uid) - used to verify ownership before rollback."""
    return hub_custom().get_namespaced_custom_object(
        OCM_WORK_GROUP, "v1", cluster, "manifestworks", name
    )


# ------------------------------------------------------------------ inventory reads


def get_managed_cluster(name: str) -> dict[str, Any]:
    """Full-but-trimmed view of one ManagedCluster: acceptance, version, capacity, taints."""
    obj = hub_custom().get_cluster_custom_object(OCM_CLUSTER_GROUP, "v1", "managedclusters", name)
    status = obj.get("status", {})
    return {
        "name": name,
        "labels": obj.get("metadata", {}).get("labels", {}),
        "hub_accepts_client": obj.get("spec", {}).get("hubAcceptsClient", False),
        "taints": obj.get("spec", {}).get("taints", []),
        "conditions": _condition_map(obj),
        "kubernetes_version": status.get("version", {}).get("kubernetes", "unknown"),
        "capacity": status.get("capacity", {}),
        "allocatable": status.get("allocatable", {}),
        "cluster_claims": {c.get("name"): c.get("value") for c in status.get("clusterClaims", [])},
    }


def list_cluster_sets() -> list[dict[str, Any]]:
    """ManagedClusterSets with their selector and the clusters that belong to each."""
    sets = paged_list(
        hub_custom().list_cluster_custom_object, OCM_CLUSTER_GROUP, "v1beta2", "managedclustersets"
    )
    clusters = paged_list(
        hub_custom().list_cluster_custom_object, OCM_CLUSTER_GROUP, "v1", "managedclusters"
    ).get("items", [])
    out = []
    for cs in sets.get("items", []):
        name = cs["metadata"]["name"]
        selector = cs.get("spec", {}).get("clusterSelector", {})
        members = [
            c["metadata"]["name"]
            for c in clusters
            if c.get("metadata", {}).get("labels", {}).get(CLUSTERSET_LABEL) == name
        ]
        out.append(
            {
                "name": name,
                "selector_type": selector.get("selectorType", "ExclusiveClusterSetLabel"),
                "conditions": _condition_map(cs),
                "members": members,
            }
        )
    return out


def list_cluster_set_bindings(namespace: str = "") -> list[dict[str, Any]]:
    """ManagedClusterSetBindings (which ClusterSets a namespace's Placements may target)."""
    api = hub_custom()
    if namespace:
        res = paged_list(
            api.list_namespaced_custom_object,
            OCM_CLUSTER_GROUP,
            "v1beta2",
            namespace,
            "managedclustersetbindings",
        )
    else:
        res = paged_list(
            api.list_cluster_custom_object,
            OCM_CLUSTER_GROUP,
            "v1beta2",
            "managedclustersetbindings",
        )
    return [
        {
            "namespace": b["metadata"].get("namespace"),
            "name": b["metadata"]["name"],
            "cluster_set": b.get("spec", {}).get("clusterSet", b["metadata"]["name"]),
            "conditions": _condition_map(b),
        }
        for b in res.get("items", [])
    ]


def list_cluster_claims() -> list[dict[str, Any]]:
    """Every cluster's ClusterClaims (id, platform, region, version...) rolled up from status."""
    clusters = paged_list(
        hub_custom().list_cluster_custom_object, OCM_CLUSTER_GROUP, "v1", "managedclusters"
    )
    return [
        {
            "cluster": c["metadata"]["name"],
            "claims": {
                cl.get("name"): cl.get("value")
                for cl in c.get("status", {}).get("clusterClaims", [])
            },
        }
        for c in clusters.get("items", [])
    ]


# ------------------------------------------------------------------ placement reads


def list_placements(namespace: str = "") -> list[dict[str, Any]]:
    """Placements and how many clusters each currently selects."""
    api = hub_custom()
    if namespace:
        res = paged_list(
            api.list_namespaced_custom_object, OCM_CLUSTER_GROUP, "v1beta1", namespace, "placements"
        )
    else:
        res = paged_list(api.list_cluster_custom_object, OCM_CLUSTER_GROUP, "v1beta1", "placements")
    out = []
    for p in res.get("items", []):
        spec = p.get("spec", {})
        out.append(
            {
                "namespace": p["metadata"].get("namespace"),
                "name": p["metadata"]["name"],
                "cluster_sets": spec.get("clusterSets", []),
                "number_of_clusters": spec.get("numberOfClusters"),
                "selected": p.get("status", {}).get("numberOfSelectedClusters"),
                "conditions": _condition_map(p),
            }
        )
    return out


def get_placement_decision(placement: str, namespace: str) -> dict[str, Any]:
    """Which clusters a Placement actually selected (reads its PlacementDecisions)."""
    res = paged_list(
        hub_custom().list_namespaced_custom_object,
        OCM_CLUSTER_GROUP,
        "v1beta1",
        namespace,
        "placementdecisions",
        label_selector=f"{PLACEMENT_LABEL}={placement}",
    )
    decisions: list[str] = []
    for pd in res.get("items", []):
        decisions.extend(d.get("clusterName") for d in pd.get("status", {}).get("decisions", []))
    return {
        "placement": placement,
        "namespace": namespace,
        "selected_clusters": sorted(set(decisions)),
        "count": len(set(decisions)),
    }


def list_addon_placement_scores(cluster: str) -> list[dict[str, Any]]:
    """AddOnPlacementScores in a cluster's namespace (custom scores prioritizers consume)."""
    res = paged_list(
        hub_custom().list_namespaced_custom_object,
        OCM_CLUSTER_GROUP,
        "v1alpha1",
        cluster,
        "addonplacementscores",
    )
    return [
        {
            "name": s["metadata"]["name"],
            "scores": {
                sc.get("name"): sc.get("value") for sc in s.get("status", {}).get("scores", [])
            },
            "valid_until": s.get("status", {}).get("validUntil"),
        }
        for s in res.get("items", [])
    ]


# ------------------------------------------------------------------ work reads


def _feedback_value(fv: dict[str, Any]) -> Any:
    """Read a ManifestWork FeedbackValue by its type discriminator (Integer/String/Boolean/JsonRaw)."""
    kind = fv.get("type")
    key = {"Integer": "integer", "String": "string", "Boolean": "boolean", "JsonRaw": "jsonRaw"}
    if kind in key:
        return fv.get(key[kind])
    # fall back across the typed fields if the discriminator is absent
    for k in ("integer", "string", "boolean", "jsonRaw"):
        if k in fv:
            return fv[k]
    return None


def get_manifestwork(cluster: str, name: str) -> dict[str, Any]:
    """Detailed ManifestWork status: top-level conditions + per-resource status feedback.

    The JSON path is `status.resourceStatus.manifests[].statusFeedback.values[]` - note
    `statusFeedback` is singular on the wire even though the Go field is plural.
    """
    obj = hub_custom().get_namespaced_custom_object(
        OCM_WORK_GROUP, "v1", cluster, "manifestworks", name
    )
    resources = []
    for man in obj.get("status", {}).get("resourceStatus", {}).get("manifests", []):
        meta = man.get("resourceMeta", {})
        feedback = {
            v.get("name"): _feedback_value(v.get("fieldValue", {}) or {})
            for v in man.get("statusFeedback", {}).get("values", [])
        }
        resources.append(
            {
                "resource": f"{meta.get('kind', '?')}/{meta.get('name', '?')}",
                "namespace": meta.get("namespace"),
                "conditions": {c.get("type"): c.get("status") for c in man.get("conditions", [])},
                "status_feedback": feedback,
            }
        )
    return {
        "cluster": cluster,
        "name": name,
        "conditions": _condition_map(obj),
        "resources": resources,
    }


def list_manifestworkreplicasets(namespace: str = "") -> list[dict[str, Any]]:
    """ManifestWorkReplicaSets: one template fanned out across a Placement, with rollout summary."""
    api = hub_custom()
    try:
        if namespace:
            res = paged_list(
                api.list_namespaced_custom_object,
                OCM_WORK_GROUP,
                "v1alpha1",
                namespace,
                "manifestworkreplicasets",
            )
        else:
            res = paged_list(
                api.list_cluster_custom_object,
                OCM_WORK_GROUP,
                "v1alpha1",
                "manifestworkreplicasets",
            )
    except ApiException as exc:
        if exc.status == 404:
            raise FeatureNotInstalled(
                "ManifestWorkReplicaSet is not served by this hub. It is feature-gated; "
                "enable it in the ClusterManager (spec.workConfiguration featureGates)."
            ) from exc
        raise
    return [
        {
            "namespace": r["metadata"].get("namespace"),
            "name": r["metadata"]["name"],
            "summary": r.get("status", {}).get("summary", {}),
            "conditions": _condition_map(r),
        }
        for r in res.get("items", [])
    ]


# ------------------------------------------------------------------ add-on reads


def list_cluster_management_addons() -> list[dict[str, Any]]:
    """Fleet-level add-on definitions (ClusterManagementAddOn) and their install strategy."""
    try:
        res = paged_list(
            hub_custom().list_cluster_custom_object,
            OCM_ADDON_GROUP,
            "v1alpha1",
            "clustermanagementaddons",
        )
    except ApiException as exc:
        if exc.status == 404:
            raise FeatureNotInstalled(
                "The add-on API (addon.open-cluster-management.io) is not installed on this hub."
            ) from exc
        raise
    return [
        {
            "name": a["metadata"]["name"],
            "install_strategy": a.get("spec", {}).get("installStrategy", {}).get("type"),
            "conditions": _condition_map(a),
        }
        for a in res.get("items", [])
    ]


def addon_health() -> list[dict[str, Any]]:
    """ManagedClusterAddOn health across every cluster namespace (Available / Degraded)."""
    try:
        res = paged_list(
            hub_custom().list_cluster_custom_object,
            OCM_ADDON_GROUP,
            "v1alpha1",
            "managedclusteraddons",
        )
    except ApiException as exc:
        if exc.status == 404:
            raise FeatureNotInstalled(
                "The add-on API (addon.open-cluster-management.io) is not installed on this hub."
            ) from exc
        raise
    out = []
    for a in res.get("items", []):
        conds = _condition_map(a)
        out.append(
            {
                "cluster": a["metadata"].get("namespace"),
                "addon": a["metadata"]["name"],
                "available": conds.get("Available", "Unknown"),
                "degraded": conds.get("Degraded", "False"),
                "progressing": conds.get("Progressing", "Unknown"),
            }
        )
    return out


# ------------------------------------------------------------------ registration reads


OCM_CSR_USERNAME_PREFIX = "system:open-cluster-management:"
OCM_CSR_GROUP_PREFIX = "system:open-cluster-management:"
OCM_CSR_SIGNER = "kubernetes.io/kube-apiserver-client"
CSR_CLUSTER_LABEL = "open-cluster-management.io/cluster-name"
CSR_REQUIRED_USAGE = "client auth"


def _is_ocm_join_csr(c: Any) -> bool:
    """A CSR is an approvable OCM join request only if it is a pending (not approved, not
    denied) client-auth CSR from the OCM signer, requested by an OCM bootstrap identity in
    an OCM group, for client authentication. Approving anything looser would let a crafted
    CSR ride the accept path, so every field the kube-apiserver will trust is checked."""
    conditions = c.status.conditions or []
    if any(cond.type in ("Approved", "Denied") for cond in conditions):
        return False
    if c.spec.signer_name != OCM_CSR_SIGNER:
        return False
    if not (c.spec.username or "").startswith(OCM_CSR_USERNAME_PREFIX):
        return False
    groups = c.spec.groups or []
    if not any((g or "").startswith(OCM_CSR_GROUP_PREFIX) for g in groups):
        return False
    usages = [str(u).lower() for u in (c.spec.usages or [])]
    return CSR_REQUIRED_USAGE in usages


def _csr_matches_cluster(c: Any, cluster: str) -> bool:
    """The CSR's own labelled cluster and bootstrap username must both name `cluster`, so
    an approval captured for one cluster cannot approve a join for another."""
    labels = c.metadata.labels or {}
    if labels.get(CSR_CLUSTER_LABEL) != cluster:
        return False
    return (c.spec.username or "").startswith(f"{OCM_CSR_USERNAME_PREFIX}{cluster}:")


def _csr_request_der(c: Any) -> bytes | None:
    """The DER-encoded PKCS#10 request bytes from spec.request (base64 in the API)."""
    req = getattr(c.spec, "request", None)
    if not req:
        return None
    raw = req.encode() if isinstance(req, str) else bytes(req)
    try:
        return base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError):
        return None


def _csr_request_hash(c: Any) -> str:
    """SHA-256 of the exact PKCS#10 request bytes, so an approval binds the certificate
    request itself - not just the CSR object's metadata - and a swapped request is caught."""
    der = _csr_request_der(c)
    return hashlib.sha256(der).hexdigest() if der else ""


def _csr_subject_cn_ok(c: Any, cluster: str) -> bool:
    """Parse the PKCS#10 request and require its subject Common Name to be the OCM agent
    identity for this cluster (system:open-cluster-management:<cluster>:...). The API-level
    username records who *submitted* the CSR; the CN is what the issued certificate will
    actually assert, so it must be validated too."""
    der = _csr_request_der(c)
    if der is None:
        return False
    try:
        from cryptography import x509
        from cryptography.x509.oid import NameOID

        csr = x509.load_der_x509_csr(der)
        if not csr.is_signature_valid:
            return False
        cns = csr.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
        cn = cns[0].value if cns else ""
    except Exception:  # noqa: BLE001 - any parse/verify failure means it is not approvable
        return False
    return str(cn).startswith(f"{OCM_CSR_USERNAME_PREFIX}{cluster}:")


def list_pending_csrs() -> list[dict[str, Any]]:
    """Pending cluster-join / add-on registration CSRs awaiting hub approval."""
    out = []
    for c in hub_certificates().list_certificate_signing_request().items:
        if not _is_ocm_join_csr(c):
            continue
        labels = c.metadata.labels or {}
        out.append(
            {
                "name": c.metadata.name,
                "requester": c.spec.username,
                "cluster": labels.get(CSR_CLUSTER_LABEL, "?"),
                "signer": c.spec.signer_name,
            }
        )
    return out


def pending_csr_identities(cluster: str) -> list[dict[str, str]]:
    """Exact identities of the pending OCM join CSRs for a cluster, captured at propose time
    so that apply approves only these - never a CSR created after the human reviewed."""
    out = []
    for c in hub_certificates().list_certificate_signing_request().items:
        labels = c.metadata.labels or {}
        if labels.get(CSR_CLUSTER_LABEL) != cluster or not _is_ocm_join_csr(c):
            continue
        out.append(
            {
                "name": c.metadata.name,
                "uid": c.metadata.uid or "",
                "signer": c.spec.signer_name,
                "username": c.spec.username or "",
                "request_hash": _csr_request_hash(c),
            }
        )
    return out


# ------------------------------------------------------------------ policy reads (optional)


def list_policies(namespace: str = "") -> list[dict[str, Any]]:
    """Governance Policies and their per-cluster compliance (only if the add-on is installed)."""
    api = hub_custom()
    try:
        if namespace:
            res = paged_list(
                api.list_namespaced_custom_object,
                "policy.open-cluster-management.io",
                "v1",
                namespace,
                "policies",
            )
        else:
            res = paged_list(
                api.list_cluster_custom_object,
                "policy.open-cluster-management.io",
                "v1",
                "policies",
            )
    except ApiException as exc:
        if exc.status == 404:
            raise FeatureNotInstalled(
                "The governance policy add-on (policy.open-cluster-management.io) is not "
                "installed on this hub."
            ) from exc
        raise
    out = []
    for p in res.get("items", []):
        status = p.get("status", {})
        out.append(
            {
                "namespace": p["metadata"].get("namespace"),
                "name": p["metadata"]["name"],
                "remediation": p.get("spec", {}).get("remediationAction"),
                "compliant": status.get("compliant"),
                # ACM CompliancePerClusterStatus keys are all-lowercase on the wire.
                "per_cluster": {
                    s.get("clustername"): s.get("compliant") for s in (status.get("status") or [])
                },
            }
        )
    return out


def list_policy_violations() -> list[dict[str, Any]]:
    """Only the Policy/cluster pairs that are NonCompliant or Pending - the fleet's open risks."""
    api = hub_custom()
    try:
        res = paged_list(api.list_cluster_custom_object, OCM_POLICY_GROUP, "v1", "policies")
    except ApiException as exc:
        if exc.status == 404:
            raise FeatureNotInstalled(
                "The governance policy add-on (policy.open-cluster-management.io) is not "
                "installed on this hub."
            ) from exc
        raise
    violations = []
    for p in res.get("items", []):
        status = p.get("status", {})
        for s in status.get("status") or []:
            if s.get("compliant") in NONCOMPLIANT_STATES:
                violations.append(
                    {
                        "policy": f"{p['metadata'].get('namespace')}/{p['metadata']['name']}",
                        "cluster": s.get("clustername"),
                        "compliant": s.get("compliant"),
                        "remediation": p.get("spec", {}).get("remediationAction"),
                    }
                )
    return violations


# ------------------------------------------------------------------ ACM extended inventory


def get_cluster_info(cluster: str) -> dict[str, Any]:
    """Extended inventory for one cluster from the HUB (no spoke access needed).

    ManagedClusterInfo is populated by the OCM work agent and stored on the hub in
    the cluster namespace, so this works for any spoke - external OCP, HCP, or cloud -
    without a kubeconfig for that cluster. Reports OpenShift/distribution version,
    node list, console URL, and vendor.
    """
    try:
        obj = hub_custom().get_namespaced_custom_object(
            OCM_INTERNAL_GROUP, "v1beta1", cluster, "managedclusterinfos", cluster
        )
    except ApiException as exc:
        if exc.status == 404:
            raise FeatureNotInstalled(
                f"No ManagedClusterInfo for '{cluster}'. This needs the ACM/MCE "
                "multicloud-operators-foundation add-on (internal.open-cluster-management.io)."
            ) from exc
        raise
    status = obj.get("status", {})
    dist = status.get("distributionInfo", {})
    nodes = status.get("nodeList", [])
    return {
        "cluster": cluster,
        "console_url": status.get("consoleURL"),
        "kube_vendor": status.get("kubeVendor"),
        "cloud_vendor": status.get("cloudVendor"),
        "openshift_version": dist.get("ocp", {}).get("version"),
        "node_count": len(nodes),
        "nodes": [
            {
                "name": n.get("name"),
                "capacity": n.get("capacity", {}),
                "labels": n.get("labels", {}),
            }
            for n in nodes[:50]
        ],
        "conditions": _condition_map(obj),
    }


def list_addons_for_cluster(cluster: str) -> list[dict[str, Any]]:
    """Every ManagedClusterAddOn in one cluster's namespace, with health conditions."""
    try:
        res = paged_list(
            hub_custom().list_namespaced_custom_object,
            OCM_ADDON_GROUP,
            "v1alpha1",
            cluster,
            "managedclusteraddons",
        )
    except ApiException as exc:
        if exc.status == 404:
            raise FeatureNotInstalled(
                "The add-on API (addon.open-cluster-management.io) is not installed on this hub."
            ) from exc
        raise
    out = []
    for a in res.get("items", []):
        conds = _condition_map(a)
        out.append(
            {
                "addon": a["metadata"]["name"],
                "install_namespace": a.get("spec", {}).get("installNamespace"),
                "available": conds.get("Available", "Unknown"),
                "degraded": conds.get("Degraded", "False"),
            }
        )
    return out


# ------------------------------------------------------------------ HyperShift HCP reads


def list_hosted_clusters(namespace: str = "") -> list[dict[str, Any]]:
    """HyperShift HostedClusters, when the hub is the HCP hosting/management cluster.

    HostedCluster objects live on whichever cluster hosts the control plane. If HCPs
    are hosted on a separate management cluster, they are not on this hub - the tool
    says so, and the ManagedCluster view still covers those spokes.
    """
    api = hub_custom()
    try:
        if namespace:
            res = paged_list(
                api.list_namespaced_custom_object,
                HYPERSHIFT_GROUP,
                "v1beta1",
                namespace,
                "hostedclusters",
            )
        else:
            res = paged_list(
                api.list_cluster_custom_object, HYPERSHIFT_GROUP, "v1beta1", "hostedclusters"
            )
    except ApiException as exc:
        if exc.status == 404:
            raise FeatureNotInstalled(
                "No HostedCluster API on this hub. Either HyperShift/HCP is not enabled here, "
                "or the hosted control planes are hosted on a different management cluster "
                "(the spokes still appear via list_clusters as ManagedClusters)."
            ) from exc
        raise
    return [_hosted_cluster_summary(h) for h in res.get("items", [])]


def get_hosted_cluster(name: str, namespace: str) -> dict[str, Any]:
    """Detailed HostedCluster: version history, conditions, node pools in the same namespace."""
    obj = hub_custom().get_namespaced_custom_object(
        HYPERSHIFT_GROUP, "v1beta1", namespace, "hostedclusters", name
    )
    summary = _hosted_cluster_summary(obj)
    summary["node_pools"] = list_node_pools(namespace, cluster=name)
    return summary


def list_node_pools(namespace: str = "", cluster: str = "") -> list[dict[str, Any]]:
    """HyperShift NodePools (worker groups), optionally filtered to one HostedCluster."""
    api = hub_custom()
    try:
        if namespace:
            res = paged_list(
                api.list_namespaced_custom_object,
                HYPERSHIFT_GROUP,
                "v1beta1",
                namespace,
                "nodepools",
            )
        else:
            res = paged_list(
                api.list_cluster_custom_object, HYPERSHIFT_GROUP, "v1beta1", "nodepools"
            )
    except ApiException as exc:
        if exc.status == 404:
            raise FeatureNotInstalled(
                "No NodePool API on this hub (HyperShift not enabled here)."
            ) from exc
        raise
    out = []
    for np in res.get("items", []):
        spec = np.get("spec", {})
        if cluster and spec.get("clusterName") != cluster:
            continue
        out.append(
            {
                "name": np["metadata"]["name"],
                "namespace": np["metadata"].get("namespace"),
                "cluster": spec.get("clusterName"),
                "desired_replicas": spec.get("replicas"),
                "current_replicas": np.get("status", {}).get("replicas"),
                "conditions": _condition_map(np),
            }
        )
    return out


def _hosted_cluster_summary(h: dict[str, Any]) -> dict[str, Any]:
    status = h.get("status", {})
    history = status.get("version", {}).get("history", [])
    return {
        "name": h["metadata"]["name"],
        "namespace": h["metadata"].get("namespace"),
        "version": history[0].get("version") if history else None,
        "version_state": history[0].get("state") if history else None,
        "conditions": _condition_map(h),
    }


# ------------------------------------------------------------------ generic reader


def list_resources(resource: str, namespace: str = "") -> list[dict[str, Any]]:
    """List any allow-listed OCM resource type, trimmed to identity + conditions."""
    group, version, plural, namespaced = _resolve_resource(resource)
    api = hub_custom()
    try:
        if namespaced and namespace:
            res = paged_list(api.list_namespaced_custom_object, group, version, namespace, plural)
        else:
            res = paged_list(api.list_cluster_custom_object, group, version, plural)
    except ApiException as exc:
        if exc.status == 404:
            raise FeatureNotInstalled(
                f"'{resource}' ({group}/{version}) is not served by this hub."
            ) from exc
        raise
    return [_summarize(item) for item in res.get("items", [])]


def get_resource(resource: str, name: str, namespace: str = "") -> dict[str, Any]:
    """Get one allow-listed OCM resource in full (never a Secret - not on the allow-list)."""
    group, version, plural, namespaced = _resolve_resource(resource)
    api = hub_custom()
    try:
        if namespaced:
            if not namespace:
                raise ValueError(
                    f"'{resource}' is namespaced; pass the namespace "
                    "(usually the cluster namespace on the hub)."
                )
            return api.get_namespaced_custom_object(group, version, namespace, plural, name)
        return api.get_cluster_custom_object(group, version, plural, name)
    except ApiException as exc:
        if exc.status == 404:
            raise FeatureNotInstalled(
                f"'{resource}/{name}' not found (or the type is not served by this hub)."
            ) from exc
        raise


def _resolve_resource(resource: str) -> tuple[str, str, str, bool]:
    key = resource.strip().lower()
    if key not in READABLE_RESOURCES:
        allowed = ", ".join(sorted(READABLE_RESOURCES))
        raise ValueError(
            f"'{resource}' is not a readable OCM resource type. Allowed types: {allowed}."
        )
    return READABLE_RESOURCES[key]


# ------------------------------------------------------------------ lifecycle writes


def _merge_patch_cluster(name: str, patch: dict[str, Any], dry_run: bool = False) -> None:
    hub_custom().patch_cluster_custom_object(
        OCM_CLUSTER_GROUP,
        "v1",
        "managedclusters",
        name,
        patch,
        **({"dry_run": "All"} if dry_run else {}),
    )


def cordon_patch(cluster: str, cordon: bool) -> dict[str, Any]:
    """Build the taints patch that pulls a cluster out of (cordon) or back into scheduling."""
    obj = hub_custom().get_cluster_custom_object(
        OCM_CLUSTER_GROUP, "v1", "managedclusters", cluster
    )
    taints = [t for t in obj.get("spec", {}).get("taints", []) if t.get("key") != CORDON_TAINT_KEY]
    if cordon:
        taints.append({"key": CORDON_TAINT_KEY, "value": "true", "effect": "NoSelect"})
    return {"spec": {"taints": taints}}


def label_patch(key: str, value: str) -> dict[str, Any]:
    """Build a labels merge-patch. An empty value removes the label."""
    return {"metadata": {"labels": {key: value or None}}}


def accept_patch() -> dict[str, Any]:
    return {"spec": {"hubAcceptsClient": True}}


PATCH_ACTIONS = ("cordon", "uncordon", "set_label", "accept")


def managed_cluster_addon_body(cluster: str, addon: str, install_namespace: str) -> dict[str, Any]:
    body: dict[str, Any] = {
        "apiVersion": f"{OCM_ADDON_GROUP}/v1alpha1",
        "kind": "ManagedClusterAddOn",
        "metadata": {"name": addon, "namespace": cluster},
        "spec": {},
    }
    if install_namespace:
        body["spec"]["installNamespace"] = install_namespace
    return body


def validate_cluster_action(cluster: str, action: str, params: dict[str, Any]) -> None:
    """Server-side dry-run of a lifecycle action so it fails at propose time, not apply time."""
    if action in PATCH_ACTIONS:
        _merge_patch_cluster(cluster, _action_patch(cluster, action, params), dry_run=True)
    elif action == "enable_addon":
        body = managed_cluster_addon_body(
            cluster, params["addon"], params.get("install_namespace", "")
        )
        hub_custom().create_namespaced_custom_object(
            OCM_ADDON_GROUP, "v1alpha1", cluster, "managedclusteraddons", body, dry_run="All"
        )
    elif action == "disable_addon":
        # Confirm it exists; a 404 here surfaces at propose time as a clear rejection.
        hub_custom().get_namespaced_custom_object(
            OCM_ADDON_GROUP, "v1alpha1", cluster, "managedclusteraddons", params["addon"]
        )
    else:
        raise ValueError(f"Unknown cluster action '{action}'.")


def apply_cluster_action(cluster: str, action: str, params: dict[str, Any]) -> dict[str, Any]:
    """Apply an approved lifecycle action.

    Cluster patches (cordon/uncordon/set_label/accept) merge-patch the ManagedCluster;
    'accept' also approves pending join CSRs. enable_addon/disable_addon create or
    delete a ManagedClusterAddOn in the cluster namespace.
    """
    result: dict[str, Any] = {"cluster": cluster, "action": action, "status": "applied"}
    if action in PATCH_ACTIONS:
        _merge_patch_cluster(cluster, _action_patch(cluster, action, params))
        if action == "accept":
            result["approved_csrs"] = _approve_pending_csrs(cluster, params.get("csrs", []))
    elif action == "enable_addon":
        body = managed_cluster_addon_body(
            cluster, params["addon"], params.get("install_namespace", "")
        )
        hub_custom().create_namespaced_custom_object(
            OCM_ADDON_GROUP, "v1alpha1", cluster, "managedclusteraddons", body
        )
        result["addon"] = params["addon"]
    elif action == "disable_addon":
        hub_custom().delete_namespaced_custom_object(
            OCM_ADDON_GROUP, "v1alpha1", cluster, "managedclusteraddons", params["addon"]
        )
        result["addon"] = params["addon"]
    else:
        raise ValueError(f"Unknown cluster action '{action}'.")
    return result


def _action_patch(cluster: str, action: str, params: dict[str, Any]) -> dict[str, Any]:
    if action == "cordon":
        return cordon_patch(cluster, cordon=True)
    if action == "uncordon":
        return cordon_patch(cluster, cordon=False)
    if action == "set_label":
        return label_patch(params["key"], params.get("value", ""))
    if action == "accept":
        return accept_patch()
    raise ValueError(f"Unknown cluster action '{action}'.")


def _approve_pending_csrs(cluster: str, allowed: list[dict[str, str]]) -> list[str]:
    """Approve ONLY the exact CSRs captured (by name + uid) when the human approved.

    A CSR created after the human review, or one whose uid/signer/username no longer
    matches, is skipped - so approval cannot be widened between propose and apply.
    """
    from kubernetes import client

    # (name, uid) -> the request hash captured at propose time.
    wanted = {(a.get("name"), a.get("uid")): a.get("request_hash", "") for a in allowed}
    certs = hub_certificates()
    approved: list[str] = []
    for c in certs.list_certificate_signing_request().items:
        key = (c.metadata.name, c.metadata.uid or "")
        if key not in wanted:
            continue
        # Re-verify at apply time: still a pending OCM client-auth join CSR (signer, groups,
        # usages, not approved/denied), still bound to this exact cluster, the PKCS#10
        # request bytes are unchanged since the human reviewed, and the certificate subject
        # CN is the OCM agent identity for this cluster.
        if not _is_ocm_join_csr(c) or not _csr_matches_cluster(c, cluster):
            continue
        # Fail closed: the live PKCS#10 request must hash-match what the human reviewed.
        # An empty captured hash (a capture failure at propose time) will not match a real
        # CSR's request, so it is refused rather than skipped.
        if _csr_request_hash(c) != wanted[key]:
            continue
        if not _csr_subject_cn_ok(c, cluster):
            continue
        c.status.conditions = (c.status.conditions or []) + [
            client.V1CertificateSigningRequestCondition(
                type="Approved",
                status="True",
                reason="OCMMCPApproved",
                message="Approved through ocm-mcp-server after human approval.",
            )
        ]
        certs.replace_certificate_signing_request_approval(c.metadata.name, c)
        approved.append(c.metadata.name)
    return approved
