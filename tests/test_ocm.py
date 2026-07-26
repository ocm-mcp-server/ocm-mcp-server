# SPDX-FileCopyrightText: 2026 Sandeep Bazar
# SPDX-License-Identifier: Apache-2.0

"""OCM shaping/read functions driven with a fake hub custom-objects client (no cluster)."""

import pytest

from ocm_mcp_server import ocm


class FakeCustom:
    """Stands in for the Kubernetes CustomObjectsApi: returns canned list/get payloads."""

    def __init__(self, items=None, obj=None):
        self._items = items if items is not None else []
        self._obj = obj if obj is not None else {}

    def list_cluster_custom_object(self, *a, **k):
        return {"items": self._items}

    def list_namespaced_custom_object(self, *a, **k):
        return {"items": self._items}

    def get_cluster_custom_object(self, *a, **k):
        return self._obj

    def get_namespaced_custom_object(self, *a, **k):
        return self._obj

    def patch_cluster_custom_object(self, *a, **k):
        return {"status": "patched"}

    def create_namespaced_custom_object(self, *a, **k):
        return {"status": "created"}

    def delete_namespaced_custom_object(self, *a, **k):
        return {"status": "deleted"}


def patch_hub(monkeypatch, items=None, obj=None):
    monkeypatch.setattr(ocm, "hub_custom", lambda: FakeCustom(items=items, obj=obj))


MANAGED_CLUSTER = {
    "metadata": {"name": "cluster1", "labels": {"env": "prod"}},
    "status": {
        "conditions": [
            {"type": "ManagedClusterConditionAvailable", "status": "True"},
            {"type": "ManagedClusterJoined", "status": "True"},
        ],
        "version": {"kubernetes": "v1.29"},
        "capacity": {"cpu": "8", "memory": "32Gi"},
        "clusterClaims": [{"name": "platform.open-cluster-management.io", "value": "AWS"}],
    },
    "spec": {"hubAcceptsClient": True, "taints": []},
}


# --------------------------------------------------------------------- pure helpers


def test_condition_map():
    obj = {"status": {"conditions": [{"type": "Ready", "status": "True"}]}}
    assert ocm._condition_map(obj) == {"Ready": "True"}


def test_summarize_trims_to_key_fields():
    s = ocm._summarize(MANAGED_CLUSTER)
    assert s["name"] == "cluster1" and "labels" in s and "conditions" in s


def test_manifestwork_body_wraps_and_labels():
    body = ocm.manifestwork_body("w", [{"kind": "ConfigMap"}])
    assert body["metadata"]["labels"]["app.kubernetes.io/managed-by"] == "ocm-mcp-server"
    assert body["spec"]["workload"]["manifests"] == [{"kind": "ConfigMap"}]


# --------------------------------------------------------------------- list/get reads


def test_list_managed_clusters(monkeypatch):
    patch_hub(monkeypatch, items=[MANAGED_CLUSTER])
    out = ocm.list_managed_clusters()
    assert out[0]["name"] == "cluster1"
    assert out[0]["available"] == "True" and out[0]["kubernetes_version"] == "v1.29"


def test_get_managed_cluster(monkeypatch):
    patch_hub(monkeypatch, obj=MANAGED_CLUSTER)
    out = ocm.get_managed_cluster("cluster1")
    assert isinstance(out, dict) and out.get("name") == "cluster1"


def test_list_cluster_claims(monkeypatch):
    patch_hub(monkeypatch, items=[MANAGED_CLUSTER])
    out = ocm.list_cluster_claims()
    assert isinstance(out, list)


def test_list_manifestworks(monkeypatch):
    mw = {
        "metadata": {"name": "w1"},
        "status": {"conditions": [{"type": "Applied", "status": "True"}]},
    }
    patch_hub(monkeypatch, items=[mw])
    out = ocm.list_manifestworks("cluster1")
    assert out and out[0]["name"] == "w1"


def test_list_placements(monkeypatch):
    pl = {
        "metadata": {"name": "p", "namespace": "default"},
        "status": {"numberOfSelectedClusters": 2},
    }
    patch_hub(monkeypatch, items=[pl])
    out = ocm.list_placements()
    assert isinstance(out, list)


def test_list_resources_allowlisted(monkeypatch):
    patch_hub(monkeypatch, items=[MANAGED_CLUSTER])
    out = ocm.list_resources("managedclusters")
    assert isinstance(out, list) and out and out[0]["name"] == "cluster1"


def test_get_resource_allowlisted(monkeypatch):
    patch_hub(monkeypatch, obj=MANAGED_CLUSTER)
    out = ocm.get_resource("managedclusters", "cluster1")
    assert isinstance(out, dict)


def test_resource_not_on_allowlist_rejected():
    with pytest.raises(ValueError, match="not a readable OCM resource type"):
        ocm.list_resources("secrets")


# --------------------------------------------------------------------- lifecycle patches


def test_cordon_patch_adds_taint(monkeypatch):
    patch_hub(monkeypatch, obj={"spec": {"taints": []}})
    p = ocm.cordon_patch("cluster1", cordon=True)
    assert any(t["key"] == ocm.CORDON_TAINT_KEY for t in p["spec"]["taints"])


def test_uncordon_patch_removes_taint(monkeypatch):
    patch_hub(monkeypatch, obj={"spec": {"taints": [{"key": ocm.CORDON_TAINT_KEY}]}})
    p = ocm.cordon_patch("cluster1", cordon=False)
    assert p["spec"]["taints"] == []


def test_label_patch_set_and_remove():
    assert ocm.label_patch("k", "v")["metadata"]["labels"]["k"] == "v"
    assert ocm.label_patch("k", "")["metadata"]["labels"]["k"] is None


def test_accept_patch():
    assert ocm.accept_patch()["spec"]["hubAcceptsClient"] is True


def test_managed_cluster_addon_body():
    b = ocm.managed_cluster_addon_body("cluster1", "search", "ns")
    assert b["kind"] == "ManagedClusterAddOn" and b["spec"]["installNamespace"] == "ns"


def test_validate_cluster_action_cordon(monkeypatch):
    patch_hub(monkeypatch, obj={"spec": {"taints": []}})
    ocm.validate_cluster_action("cluster1", "cordon", {})  # dry-run patch, must not raise


def test_validate_cluster_action_enable_addon(monkeypatch):
    patch_hub(monkeypatch)
    ocm.validate_cluster_action("cluster1", "enable_addon", {"addon": "search"})


def test_apply_cluster_action_cordon(monkeypatch):
    patch_hub(monkeypatch, obj={"spec": {"taints": []}})
    out = ocm.apply_cluster_action("cluster1", "cordon", {})
    assert isinstance(out, dict)


def test_apply_cluster_action_set_label(monkeypatch):
    patch_hub(monkeypatch)
    out = ocm.apply_cluster_action("cluster1", "set_label", {"key": "tier", "value": "gold"})
    assert isinstance(out, dict)


# --------------------------------------------------------------------- more reads


def test_list_cluster_sets(monkeypatch):
    patch_hub(monkeypatch, items=[{"metadata": {"name": "global"}, "spec": {}}])
    assert isinstance(ocm.list_cluster_sets(), list)


def test_list_manifestworkreplicasets(monkeypatch):
    patch_hub(monkeypatch, items=[{"metadata": {"name": "r", "namespace": "d"}, "status": {}}])
    assert isinstance(ocm.list_manifestworkreplicasets(), list)


def test_list_cluster_management_addons(monkeypatch):
    patch_hub(monkeypatch, items=[{"metadata": {"name": "search"}, "spec": {}}])
    assert isinstance(ocm.list_cluster_management_addons(), list)


def test_addon_health(monkeypatch):
    patch_hub(
        monkeypatch, items=[{"metadata": {"name": "a", "namespace": "cluster1"}, "status": {}}]
    )
    assert isinstance(ocm.addon_health(), list)


def test_list_hosted_clusters(monkeypatch):
    patch_hub(
        monkeypatch,
        items=[{"metadata": {"name": "hc", "namespace": "clusters"}, "status": {}, "spec": {}}],
    )
    assert isinstance(ocm.list_hosted_clusters(), list)


def test_get_manifestwork(monkeypatch):
    obj = {
        "metadata": {"name": "w"},
        "status": {"conditions": [], "resourceStatus": {"manifests": []}},
    }
    patch_hub(monkeypatch, obj=obj)
    assert isinstance(ocm.get_manifestwork("cluster1", "w"), dict)


# --------------------------------------------------------------------- CSR list reads


def test_list_pending_csrs(monkeypatch):
    from tests.test_csr import _FakeCerts, csr

    fake = _FakeCerts([csr(name="c1", cluster="cluster1")])
    monkeypatch.setattr(ocm, "hub_certificates", lambda: fake)
    out = ocm.list_pending_csrs()
    assert out and out[0]["cluster"] == "cluster1"


def test_pending_csr_identities_captures_request_hash(monkeypatch):
    from tests.test_csr import _FakeCerts, csr

    fake = _FakeCerts([csr(name="c1", uid="u1", cluster="cluster1")])
    monkeypatch.setattr(ocm, "hub_certificates", lambda: fake)
    out = ocm.pending_csr_identities("cluster1")
    assert out and out[0]["request_hash"]


# --------------------------------------------------------------------- spoke reads (mocked)


def test_cluster_health_without_spoke(monkeypatch):
    # No spoke context configured -> hub view only, no crash.
    patch_hub(monkeypatch, obj={"status": {"conditions": []}})
    monkeypatch.setattr(ocm, "spoke_core", lambda c: (_ for _ in ()).throw(LookupError("no ctx")))
    out = ocm.cluster_health("cluster1")
    assert out["cluster"] == "cluster1" and "unavailable" in out["spoke_view"]


# --------------------------------------------------------------------- spoke reads (fakes)

from types import SimpleNamespace


def _pod(name, phase, reason=None, restarts=0):
    waiting = SimpleNamespace(reason=reason) if reason else None
    cs = SimpleNamespace(state=SimpleNamespace(waiting=waiting), restart_count=restarts)
    return SimpleNamespace(
        status=SimpleNamespace(phase=phase, container_statuses=[cs]),
        metadata=SimpleNamespace(namespace="shop", name=name),
    )


def _event():
    return SimpleNamespace(
        metadata=SimpleNamespace(namespace="shop", creation_timestamp=1),
        type="Warning",
        reason="Failed",
        count=2,
        message="bad image",
        involved_object=SimpleNamespace(kind="Pod", name="p"),
        last_timestamp=1,
        event_time=None,
    )


class FakeCore:
    def list_pod_for_all_namespaces(self, limit, _request_timeout):
        return SimpleNamespace(
            items=[_pod("ok", "Running"), _pod("bad", "Pending", "ImagePullBackOff", 5)],
            metadata=SimpleNamespace(_continue=None),
        )

    def list_namespaced_event(self, ns, limit, _request_timeout):
        return SimpleNamespace(items=[_event()])

    def list_event_for_all_namespaces(self, limit, _request_timeout):
        return SimpleNamespace(items=[_event()])

    def read_namespaced_pod_log(self, pod, ns, container, tail_lines, previous, _request_timeout):
        return "log line one\nlog line two"


class FakeApps:
    def list_deployment_for_all_namespaces(self, limit, _request_timeout):
        return SimpleNamespace(
            items=[
                SimpleNamespace(
                    spec=SimpleNamespace(replicas=3),
                    status=SimpleNamespace(ready_replicas=1),
                    metadata=SimpleNamespace(namespace="shop", name="payments"),
                )
            ]
        )


def test_cluster_health_with_spoke(monkeypatch):
    patch_hub(monkeypatch, obj={"status": {"conditions": [{"type": "Ready", "status": "True"}]}})
    monkeypatch.setattr(ocm, "spoke_core", lambda c: FakeCore())
    monkeypatch.setattr(ocm, "spoke_apps", lambda c: FakeApps())
    out = ocm.cluster_health("cluster1")
    assert out["spoke_view"] == "ok"
    assert any(p["name"] == "bad" for p in out["unhealthy_pods"])
    assert any(d["name"] == "payments" for d in out["degraded_deployments"])


def test_cluster_events_all_namespaces(monkeypatch):
    monkeypatch.setattr(ocm, "spoke_core", lambda c: FakeCore())
    out = ocm.cluster_events("cluster1", limit=5)
    assert out and out[0]["reason"] == "Failed"


def test_cluster_events_namespaced(monkeypatch):
    monkeypatch.setattr(ocm, "spoke_core", lambda c: FakeCore())
    out = ocm.cluster_events("cluster1", namespace="shop", limit=5)
    assert out and out[0]["object"] == "Pod/p"


def test_pod_logs(monkeypatch):
    monkeypatch.setattr(ocm, "spoke_core", lambda c: FakeCore())
    assert "log line" in ocm.pod_logs("cluster1", "shop", "p")


# --------------------------------------------------------------------- more hub reads


def test_get_placement_decision(monkeypatch):
    dec = {"metadata": {"name": "p-1"}, "status": {"decisions": [{"clusterName": "cluster1"}]}}
    patch_hub(monkeypatch, items=[dec])
    out = ocm.get_placement_decision("p", "default")
    assert isinstance(out, dict)


def test_list_cluster_set_bindings(monkeypatch):
    patch_hub(
        monkeypatch,
        items=[{"metadata": {"name": "b", "namespace": "d"}, "spec": {"clusterSet": "global"}}],
    )
    assert isinstance(ocm.list_cluster_set_bindings(), list)


def test_list_policies(monkeypatch):
    pol = {
        "metadata": {"name": "p", "namespace": "d"},
        "status": {"compliant": "Compliant", "status": []},
    }
    patch_hub(monkeypatch, items=[pol])
    assert isinstance(ocm.list_policies(), list)


def test_list_addon_placement_scores(monkeypatch):
    patch_hub(monkeypatch, items=[{"metadata": {"name": "s"}, "status": {"scores": []}}])
    assert isinstance(ocm.list_addon_placement_scores("cluster1"), list)


def test_apply_cluster_action_accept(monkeypatch):
    patch_hub(monkeypatch, obj={"spec": {}})
    monkeypatch.setattr(ocm, "_approve_pending_csrs", lambda cluster, allowed: [])
    out = ocm.apply_cluster_action("cluster1", "accept", {"csrs": []})
    assert isinstance(out, dict)


def test_apply_cluster_action_enable_addon(monkeypatch):
    patch_hub(monkeypatch)
    out = ocm.apply_cluster_action("cluster1", "enable_addon", {"addon": "search"})
    assert isinstance(out, dict)


def test_apply_cluster_action_disable_addon(monkeypatch):
    patch_hub(monkeypatch)
    out = ocm.apply_cluster_action("cluster1", "disable_addon", {"addon": "search"})
    assert isinstance(out, dict)


# --------------------------------------------------------------------- ACM/HyperShift reads


def test_get_cluster_info(monkeypatch):
    obj = {
        "metadata": {"name": "cluster1"},
        "status": {"distributionInfo": {}, "nodeList": [], "version": ""},
    }
    patch_hub(monkeypatch, obj=obj)
    assert isinstance(ocm.get_cluster_info("cluster1"), dict)


def test_list_addons_for_cluster(monkeypatch):
    patch_hub(
        monkeypatch, items=[{"metadata": {"name": "a", "namespace": "cluster1"}, "status": {}}]
    )
    assert isinstance(ocm.list_addons_for_cluster("cluster1"), list)


def test_get_hosted_cluster(monkeypatch):
    obj = {"metadata": {"name": "hc", "namespace": "clusters"}, "status": {}, "spec": {}}
    patch_hub(monkeypatch, obj=obj)
    assert isinstance(ocm.get_hosted_cluster("hc", "clusters"), dict)


def test_list_node_pools(monkeypatch):
    patch_hub(
        monkeypatch,
        items=[
            {
                "metadata": {"name": "np", "namespace": "clusters"},
                "spec": {"replicas": 3},
                "status": {},
            }
        ],
    )
    assert isinstance(ocm.list_node_pools(), list)


def test_list_policy_violations(monkeypatch):
    pol = {
        "metadata": {"name": "p", "namespace": "d"},
        "status": {
            "compliant": "NonCompliant",
            "status": [{"clustername": "cluster1", "compliant": "NonCompliant"}],
        },
    }
    patch_hub(monkeypatch, items=[pol])
    assert isinstance(ocm.list_policy_violations(), list)


def test_get_manifestwork_with_feedback(monkeypatch):
    obj = {
        "metadata": {"name": "w"},
        "status": {
            "conditions": [{"type": "Applied", "status": "True"}],
            "resourceStatus": {
                "manifests": [
                    {
                        "resourceMeta": {"kind": "Deployment", "name": "d", "namespace": "shop"},
                        "statusFeedback": {
                            "values": [
                                {
                                    "name": "readyReplicas",
                                    "fieldValue": {"type": "Integer", "integer": 2},
                                }
                            ]
                        },
                    }
                ]
            },
        },
    }
    patch_hub(monkeypatch, obj=obj)
    out = ocm.get_manifestwork("cluster1", "w")
    assert isinstance(out, dict)
