# SPDX-FileCopyrightText: 2026 Sandeep Bazar
# SPDX-License-Identifier: Apache-2.0

"""Coverage for ocm.py error branches: ApiException paths, spoke fallbacks, namespaced
list variants, write helpers, and CSR edge cases. All Kubernetes clients are faked."""

import base64
from types import SimpleNamespace

import pytest
from kubernetes.client import ApiException

from ocm_mcp_server import ocm
from tests.test_csr import _FakeCerts, csr, pkcs10
from tests.test_ocm import patch_hub


class RecordingCustom:
    """Fake CustomObjectsApi that records every call (method, args, kwargs)."""

    def __init__(self, obj=None, items=None):
        self.calls: list[tuple[str, tuple, dict]] = []
        self._obj = obj if obj is not None else {}
        self._items = items if items is not None else []

    def _record(self, op, a, k, ret):
        self.calls.append((op, a, k))
        return ret

    def list_cluster_custom_object(self, *a, **k):
        return self._record("list_cluster", a, k, {"items": self._items})

    def list_namespaced_custom_object(self, *a, **k):
        return self._record("list_ns", a, k, {"items": self._items})

    def get_cluster_custom_object(self, *a, **k):
        return self._record("get_cluster", a, k, self._obj)

    def get_namespaced_custom_object(self, *a, **k):
        return self._record("get_ns", a, k, self._obj)

    def create_namespaced_custom_object(self, *a, **k):
        return self._record("create", a, k, {"status": "created"})

    def delete_namespaced_custom_object(self, *a, **k):
        return self._record("delete", a, k, {"status": "deleted"})

    def patch_cluster_custom_object(self, *a, **k):
        return self._record("patch", a, k, {"status": "patched"})


class RaisingCustom:
    """Fake CustomObjectsApi where every method raises the given ApiException."""

    def __init__(self, status, reason="boom"):
        self._exc = ApiException(status=status, reason=reason)

    def __getattr__(self, name):
        exc = self._exc

        def _raise(*a, **k):
            raise exc

        return _raise


def patch_recording(monkeypatch, obj=None, items=None):
    fake = RecordingCustom(obj=obj, items=items)
    monkeypatch.setattr(ocm, "hub_custom", lambda: fake)
    return fake


def patch_raising(monkeypatch, status):
    monkeypatch.setattr(ocm, "hub_custom", lambda: RaisingCustom(status))


# --------------------------------------------------------------------- _summarize branches


def test_summarize_namespace_without_labels_or_conditions():
    item = {"metadata": {"name": "w1", "namespace": "cluster1"}}
    s = ocm._summarize(item)
    assert s == {"name": "w1", "namespace": "cluster1"}
    assert "labels" not in s and "conditions" not in s


# --------------------------------------------------------------------- cluster_health branches


class _TruncatedCore:
    def list_pod_for_all_namespaces(self, limit, _request_timeout):
        return SimpleNamespace(items=[], metadata=SimpleNamespace(_continue="next-page-token"))


class _HealthyApps:
    def list_deployment_for_all_namespaces(self, limit, _request_timeout):
        return SimpleNamespace(
            items=[
                SimpleNamespace(
                    spec=SimpleNamespace(replicas=2),
                    status=SimpleNamespace(ready_replicas=2),
                    metadata=SimpleNamespace(namespace="shop", name="healthy"),
                )
            ]
        )


def test_cluster_health_notes_pod_truncation_and_skips_healthy_deployments(monkeypatch):
    patch_hub(monkeypatch, obj={"status": {"conditions": []}})
    monkeypatch.setattr(ocm, "spoke_core", lambda c: _TruncatedCore())
    monkeypatch.setattr(ocm, "spoke_apps", lambda c: _HealthyApps())
    out = ocm.cluster_health("cluster1")
    assert "more than" in out["note"] and str(ocm.HEALTH_LIMIT) in out["note"]
    assert out["degraded_deployments"] == []  # ready >= desired is not degraded


# --------------------------------------------------------------------- pod_logs fallback


class _FlakyLogCore:
    """Raises on the current-instance read; may serve the previous instance."""

    def __init__(self, exc):
        self._exc = exc
        self.previous_flags: list[bool] = []

    def read_namespaced_pod_log(self, pod, ns, container, tail_lines, previous, _request_timeout):
        self.previous_flags.append(previous)
        if not previous:
            raise self._exc
        return "previous-instance logs"


def test_pod_logs_falls_back_to_previous_instance_on_400(monkeypatch):
    core = _FlakyLogCore(ApiException(status=400, reason="container is waiting to start"))
    monkeypatch.setattr(ocm, "spoke_core", lambda c: core)
    assert ocm.pod_logs("cluster1", "shop", "p") == "previous-instance logs"
    assert core.previous_flags == [False, True]


def test_pod_logs_reraises_400_when_previous_already_missing(monkeypatch):
    core = _FlakyLogCore(ApiException(status=400, reason="previous terminated container not found"))
    monkeypatch.setattr(ocm, "spoke_core", lambda c: core)
    with pytest.raises(ApiException):
        ocm.pod_logs("cluster1", "shop", "p")
    assert core.previous_flags == [False]  # no retry loop


def test_pod_logs_reraises_non_400(monkeypatch):
    core = _FlakyLogCore(ApiException(status=500, reason="server exploded"))
    monkeypatch.setattr(ocm, "spoke_core", lambda c: core)
    with pytest.raises(ApiException):
        ocm.pod_logs("cluster1", "shop", "p")
    assert core.previous_flags == [False]


# --------------------------------------------------------------------- manifestwork writes


def test_dry_run_manifestwork_sends_dry_run_all(monkeypatch):
    fake = patch_recording(monkeypatch)
    body = ocm.manifestwork_body("w", [{"kind": "ConfigMap"}])
    ocm.dry_run_manifestwork("cluster1", body)
    op, args, kwargs = fake.calls[0]
    assert op == "create" and kwargs.get("dry_run") == "All"
    assert "cluster1" in args and body in args


def test_create_manifestwork_is_a_real_create(monkeypatch):
    fake = patch_recording(monkeypatch)
    out = ocm.create_manifestwork("cluster1", {"kind": "ManifestWork"})
    assert out == {"status": "created"}
    op, _args, kwargs = fake.calls[0]
    assert op == "create" and "dry_run" not in kwargs


def test_delete_manifestwork(monkeypatch):
    fake = patch_recording(monkeypatch)
    ocm.delete_manifestwork("cluster1", "w1")
    op, args, _ = fake.calls[0]
    assert op == "delete" and args[-1] == "w1" and "cluster1" in args


def test_get_manifestwork_object_returns_raw_object(monkeypatch):
    raw = {"metadata": {"name": "w1", "uid": "u-1", "labels": {"a": "b"}}}
    patch_recording(monkeypatch, obj=raw)
    assert ocm.get_manifestwork_object("cluster1", "w1") == raw


# --------------------------------------------------------------------- namespaced list variants


def test_list_cluster_set_bindings_namespaced(monkeypatch):
    fake = patch_recording(
        monkeypatch, items=[{"metadata": {"name": "b", "namespace": "team-a"}, "spec": {}}]
    )
    out = ocm.list_cluster_set_bindings("team-a")
    assert out[0]["cluster_set"] == "b"  # falls back to the binding name
    op, args, _ = fake.calls[0]
    assert op == "list_ns" and args[2] == "team-a"


def test_list_placements_namespaced(monkeypatch):
    fake = patch_recording(monkeypatch, items=[{"metadata": {"name": "p", "namespace": "d"}}])
    out = ocm.list_placements("d")
    assert out[0]["name"] == "p"
    op, args, _ = fake.calls[0]
    assert op == "list_ns" and args[2] == "d"


def test_list_manifestworkreplicasets_namespaced(monkeypatch):
    fake = patch_recording(monkeypatch, items=[{"metadata": {"name": "r", "namespace": "d"}}])
    out = ocm.list_manifestworkreplicasets("d")
    assert out[0]["name"] == "r"
    op, args, _ = fake.calls[0]
    assert op == "list_ns" and args[2] == "d"


def test_list_policies_namespaced(monkeypatch):
    fake = patch_recording(
        monkeypatch, items=[{"metadata": {"name": "pol", "namespace": "gov"}, "status": {}}]
    )
    out = ocm.list_policies("gov")
    assert out[0]["name"] == "pol"
    op, args, _ = fake.calls[0]
    assert op == "list_ns" and args[2] == "gov"


def test_list_hosted_clusters_namespaced(monkeypatch):
    fake = patch_recording(
        monkeypatch, items=[{"metadata": {"name": "hc", "namespace": "clusters"}}]
    )
    out = ocm.list_hosted_clusters("clusters")
    assert out[0]["name"] == "hc"
    op, args, _ = fake.calls[0]
    assert op == "list_ns" and args[2] == "clusters"


def test_list_node_pools_filters_to_one_hosted_cluster(monkeypatch):
    patch_recording(
        monkeypatch,
        items=[
            {"metadata": {"name": "np-a", "namespace": "clusters"}, "spec": {"clusterName": "hc1"}},
            {"metadata": {"name": "np-b", "namespace": "clusters"}, "spec": {"clusterName": "hc2"}},
        ],
    )
    out = ocm.list_node_pools("clusters", cluster="hc1")
    assert [np["name"] for np in out] == ["np-a"]


def test_list_resources_namespaced_path(monkeypatch):
    fake = patch_recording(monkeypatch, items=[{"metadata": {"name": "p", "namespace": "d"}}])
    out = ocm.list_resources("placements", namespace="d")
    assert out == [{"name": "p", "namespace": "d"}]
    op, args, _ = fake.calls[0]
    assert op == "list_ns" and args[2] == "d"


def test_get_resource_namespaced_requires_namespace(monkeypatch):
    patch_recording(monkeypatch)
    with pytest.raises(ValueError, match="is namespaced; pass the namespace"):
        ocm.get_resource("placements", "p")


def test_get_resource_namespaced_with_namespace(monkeypatch):
    fake = patch_recording(monkeypatch, obj={"metadata": {"name": "p"}})
    out = ocm.get_resource("placements", "p", namespace="d")
    assert out == {"metadata": {"name": "p"}}
    op, args, _ = fake.calls[0]
    assert op == "get_ns" and args[2] == "d"


# --------------------------------------------------------------------- feature detection (404)


FEATURE_GATED_CALLS = [
    pytest.param(lambda: ocm.list_manifestworkreplicasets(), id="manifestworkreplicasets"),
    pytest.param(lambda: ocm.list_cluster_management_addons(), id="clustermanagementaddons"),
    pytest.param(lambda: ocm.addon_health(), id="addon_health"),
    pytest.param(lambda: ocm.list_policies(), id="policies"),
    pytest.param(lambda: ocm.list_policy_violations(), id="policy_violations"),
    pytest.param(lambda: ocm.get_cluster_info("cluster1"), id="cluster_info"),
    pytest.param(lambda: ocm.list_addons_for_cluster("cluster1"), id="addons_for_cluster"),
    pytest.param(lambda: ocm.list_hosted_clusters(), id="hostedclusters"),
    pytest.param(lambda: ocm.list_node_pools(), id="nodepools"),
    pytest.param(lambda: ocm.list_resources("managedclusters"), id="list_resources"),
    pytest.param(lambda: ocm.get_resource("managedclusters", "c1"), id="get_resource"),
]


@pytest.mark.parametrize("call", FEATURE_GATED_CALLS)
def test_404_maps_to_feature_not_installed(monkeypatch, call):
    patch_raising(monkeypatch, 404)
    with pytest.raises(ocm.FeatureNotInstalled):
        call()


@pytest.mark.parametrize("call", FEATURE_GATED_CALLS)
def test_non_404_api_errors_reraise(monkeypatch, call):
    patch_raising(monkeypatch, 500)
    with pytest.raises(ApiException):
        call()


def test_feature_not_installed_message_names_the_gate(monkeypatch):
    patch_raising(monkeypatch, 404)
    with pytest.raises(ocm.FeatureNotInstalled, match="feature-gated"):
        ocm.list_manifestworkreplicasets()
    with pytest.raises(ocm.FeatureNotInstalled, match="multicloud-operators-foundation"):
        ocm.get_cluster_info("cluster1")


# --------------------------------------------------------------------- policy rollup branch


def test_list_policy_violations_reports_only_noncompliant_pairs(monkeypatch):
    pol = {
        "metadata": {"name": "p", "namespace": "gov"},
        "spec": {"remediationAction": "inform"},
        "status": {
            "status": [
                {"clustername": "good", "compliant": "Compliant"},
                {"clustername": "bad", "compliant": "NonCompliant"},
            ]
        },
    }
    patch_hub(monkeypatch, items=[pol])
    out = ocm.list_policy_violations()
    assert len(out) == 1 and out[0]["cluster"] == "bad"


# --------------------------------------------------------------------- CSR edge cases


def test_csr_request_hash_empty_when_request_missing():
    assert ocm._csr_request_der(csr(request=None)) is None
    assert ocm._csr_request_hash(csr(request=None)) == ""


def test_csr_subject_cn_invalid_signature_rejected():
    # Tamper with the signed subject bytes: DER still parses, signature no longer verifies.
    good = base64.b64decode(pkcs10("system:open-cluster-management:cluster1:agent"))
    tampered = good.replace(b"cluster1:agent", b"cluster1:agenX")
    assert tampered != good
    c = csr(request=base64.b64encode(tampered).decode())
    assert ocm._csr_subject_cn_ok(c, "cluster1") is False


def test_csr_subject_cn_valid_base64_but_not_a_csr_rejected():
    junk = base64.b64encode(b"\x30\x03\x02\x01\x01").decode()  # valid base64, not PKCS#10
    assert ocm._csr_subject_cn_ok(csr(request=junk), "cluster1") is False


def test_list_pending_csrs_skips_non_ocm_csrs(monkeypatch):
    fake = _FakeCerts(
        [
            csr(name="join", cluster="cluster1"),
            csr(name="kubelet", cluster="cluster1", signer="kubernetes.io/kubelet-serving"),
        ]
    )
    monkeypatch.setattr(ocm, "hub_certificates", lambda: fake)
    out = ocm.list_pending_csrs()
    assert [c["name"] for c in out] == ["join"]


def test_pending_csr_identities_skips_other_clusters(monkeypatch):
    fake = _FakeCerts([csr(name="mine", cluster="cluster1"), csr(name="other", cluster="cluster2")])
    monkeypatch.setattr(ocm, "hub_certificates", lambda: fake)
    out = ocm.pending_csr_identities("cluster1")
    assert [c["name"] for c in out] == ["mine"]


def test_approve_skips_subject_cn_for_wrong_cluster(monkeypatch):
    # Submitter identity and label say cluster1, but the certificate CN names clusterB.
    live = csr(
        name="reviewed",
        uid="u-rev",
        cluster="cluster1",
        subject_cn="system:open-cluster-management:clusterB:agent",
    )
    fake = _FakeCerts([live])
    monkeypatch.setattr(ocm, "hub_certificates", lambda: fake)
    approved = ocm._approve_pending_csrs(
        "cluster1",
        [{"name": "reviewed", "uid": "u-rev", "request_hash": ocm._csr_request_hash(live)}],
    )
    assert approved == [] and fake.approved == []


# --------------------------------------------------------------------- lifecycle actions


def test_validate_cluster_action_disable_addon_checks_existence(monkeypatch):
    fake = patch_recording(monkeypatch, obj={"metadata": {"name": "search"}})
    ocm.validate_cluster_action("cluster1", "disable_addon", {"addon": "search"})
    op, args, _ = fake.calls[0]
    assert op == "get_ns" and args[-1] == "search"


def test_validate_cluster_action_unknown_rejected(monkeypatch):
    patch_recording(monkeypatch)
    with pytest.raises(ValueError, match="Unknown cluster action 'explode'"):
        ocm.validate_cluster_action("cluster1", "explode", {})


def test_apply_cluster_action_unknown_rejected(monkeypatch):
    patch_recording(monkeypatch)
    with pytest.raises(ValueError, match="Unknown cluster action 'explode'"):
        ocm.apply_cluster_action("cluster1", "explode", {})


def test_apply_cluster_action_uncordon_removes_taint(monkeypatch):
    fake = patch_recording(
        monkeypatch,
        obj={"spec": {"taints": [{"key": ocm.CORDON_TAINT_KEY, "value": "true"}]}},
    )
    out = ocm.apply_cluster_action("cluster1", "uncordon", {})
    assert out["status"] == "applied"
    patch_call = next(c for c in fake.calls if c[0] == "patch")
    assert patch_call[1][-1] == {"spec": {"taints": []}}
