# SPDX-FileCopyrightText: 2026 Sandeep Bazar
# SPDX-License-Identifier: Apache-2.0

"""The generic reader is an allow-list, not a deny-list.

The safety property is that dangerous reads cannot be *expressed*: Secrets and any
non-OCM kind are simply absent from READABLE_RESOURCES, so _resolve_resource
refuses them before any API call. This is stronger than an opt-in deny-list.
"""

import pytest

from ocm_mcp_server import ocm
from ocm_mcp_server.config import READABLE_RESOURCES


def test_known_ocm_types_resolve():
    for name in ("managedclusters", "placements", "manifestworks", "managedclusteraddons"):
        group, _version, plural, _namespaced = ocm._resolve_resource(name)
        assert group.endswith("open-cluster-management.io")
        assert plural == name


def test_resolution_is_case_insensitive():
    assert ocm._resolve_resource("ManagedClusters") == ocm._resolve_resource("managedclusters")


def test_secrets_cannot_be_read():
    for forbidden in ("secrets", "configmaps", "pods", "serviceaccounts"):
        assert forbidden not in READABLE_RESOURCES
        with pytest.raises(ValueError, match="not a readable OCM resource"):
            ocm._resolve_resource(forbidden)


def test_unknown_type_lists_allowed_set():
    with pytest.raises(ValueError, match="managedclusters"):
        ocm._resolve_resource("nope")


def test_cordon_patch_adds_and_removes_taint(monkeypatch):
    from ocm_mcp_server.config import CORDON_TAINT_KEY

    monkeypatch.setattr(ocm, "hub_custom", lambda: _FakeCustom({"spec": {"taints": []}}))
    patch = ocm.cordon_patch("cluster2", cordon=True)
    keys = [t["key"] for t in patch["spec"]["taints"]]
    assert CORDON_TAINT_KEY in keys

    monkeypatch.setattr(
        ocm,
        "hub_custom",
        lambda: _FakeCustom(
            {"spec": {"taints": [{"key": CORDON_TAINT_KEY, "value": "true", "effect": "NoSelect"}]}}
        ),
    )
    patch = ocm.cordon_patch("cluster2", cordon=False)
    assert patch["spec"]["taints"] == []


def test_label_patch_empty_value_removes():
    assert ocm.label_patch("tier", "")["metadata"]["labels"]["tier"] is None
    assert ocm.label_patch("tier", "gold")["metadata"]["labels"]["tier"] == "gold"


class _FakeCustom:
    def __init__(self, obj):
        self._obj = obj

    def get_cluster_custom_object(self, *_a, **_k):
        return self._obj
