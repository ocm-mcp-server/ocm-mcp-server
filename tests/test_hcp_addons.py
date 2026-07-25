# SPDX-FileCopyrightText: 2026 Sandeep Bazar
# SPDX-License-Identifier: Apache-2.0

"""Pure-function tests for the HCP, ManagedClusterInfo, and add-on helpers.

These exercise the shaping logic against object fixtures matching the verified
upstream JSON (statusFeedback singular, HostedCluster version history, ACM Policy
lowercase keys) - no cluster required.
"""

import pytest

from ocm_mcp_server import ocm
from ocm_mcp_server.config import ALLOWED_CLUSTER_ACTIONS, READABLE_RESOURCES


def test_feedback_value_uses_type_discriminator():
    assert ocm._feedback_value({"type": "Integer", "integer": 3}) == 3
    assert ocm._feedback_value({"type": "String", "string": "Running"}) == "Running"
    assert ocm._feedback_value({"type": "Boolean", "boolean": True}) is True
    assert ocm._feedback_value({"type": "JsonRaw", "jsonRaw": "{}"}) == "{}"


def test_feedback_value_falls_back_without_type():
    assert ocm._feedback_value({"integer": 5}) == 5
    assert ocm._feedback_value({}) is None


def test_hosted_cluster_summary_reads_version_history():
    h = {
        "metadata": {"name": "hcp-1", "namespace": "clusters"},
        "status": {
            "version": {"history": [{"version": "4.16.7", "state": "Completed"}]},
            "conditions": [{"type": "Available", "status": "True"}],
        },
    }
    s = ocm._hosted_cluster_summary(h)
    assert s["name"] == "hcp-1"
    assert s["version"] == "4.16.7"
    assert s["version_state"] == "Completed"
    assert s["conditions"]["Available"] == "True"


def test_hosted_cluster_summary_handles_no_history():
    s = ocm._hosted_cluster_summary({"metadata": {"name": "x"}, "status": {}})
    assert s["version"] is None


def test_managed_cluster_addon_body():
    body = ocm.managed_cluster_addon_body("cluster2", "search-collector", "custom-ns")
    assert body["kind"] == "ManagedClusterAddOn"
    assert body["metadata"] == {"name": "search-collector", "namespace": "cluster2"}
    assert body["spec"]["installNamespace"] == "custom-ns"
    # Without an install namespace, spec stays minimal (let the add-on default).
    assert ocm.managed_cluster_addon_body("c", "a", "")["spec"] == {}


def test_addon_actions_are_allowed():
    assert "enable_addon" in ALLOWED_CLUSTER_ACTIONS
    assert "disable_addon" in ALLOWED_CLUSTER_ACTIONS


def test_new_resource_types_on_allow_list():
    for name in ("hostedclusters", "nodepools", "managedclusterinfos"):
        assert name in READABLE_RESOURCES
        _group, _v, plural, _ns = ocm._resolve_resource(name)
        assert plural == name


def test_noncompliant_states_include_pending():
    # ACM compliant field is not binary: Pending must count as a violation.
    assert "Pending" in ocm.NONCOMPLIANT_STATES
    assert "NonCompliant" in ocm.NONCOMPLIANT_STATES
    assert "Compliant" not in ocm.NONCOMPLIANT_STATES


def test_unknown_action_patch_raises():
    with pytest.raises(ValueError, match="Unknown cluster action"):
        ocm._action_patch("c", "nonsense", {})
