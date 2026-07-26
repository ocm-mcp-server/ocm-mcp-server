# SPDX-FileCopyrightText: 2026 Sandeep Bazar
# SPDX-License-Identifier: Apache-2.0

"""The gated write path extends to OCM lifecycle actions, not just ManifestWorks.

These tests assert that a proposed cluster action carries the same content-bound
approval guarantee: a token approves an exact (cluster, action, params) tuple, and
changing any of them invalidates it.
"""

import pytest

from ocm_mcp_server import approvals
from ocm_mcp_server.approvals import ApprovalError


def test_action_proposal_records_kind_and_params(tmp_home):
    prop = approvals.new_action_proposal(
        "cluster2", "set_label", "tag as canary", {"key": "tier", "value": "canary"}
    )
    loaded = approvals.load_proposal(prop.id)
    assert loaded.kind == "action"
    assert loaded.action == "set_label"
    assert loaded.params == {"key": "tier", "value": "canary"}
    assert loaded.manifests == []


def test_action_token_roundtrip(tmp_home):
    prop = approvals.new_action_proposal("cluster2", "cordon", "drain for maintenance", {})
    token = approvals.mint_token(prop)
    approvals.verify_token(prop, token)  # must not raise


def test_action_token_invalid_after_params_change(tmp_home):
    prop = approvals.new_action_proposal(
        "cluster2", "set_label", "tag it", {"key": "tier", "value": "gold"}
    )
    token = approvals.mint_token(prop)
    # An agent that swaps the label value after approval must be rejected.
    prop.content_hash = approvals.content_hash(
        prop.cluster,
        prop.name,
        [],
        kind="action",
        action="set_label",
        params={"key": "tier", "value": "platinum"},
    )
    with pytest.raises(ApprovalError, match="content mismatch"):
        approvals.verify_token(prop, token)


def test_manifestwork_and_action_hashes_differ(tmp_home):
    # Same cluster/name must not collide across kinds.
    mw = approvals.content_hash("c1", "x", [], kind="manifestwork")
    act = approvals.content_hash("c1", "x", [], kind="action", action="cordon")
    assert mw != act


def test_legacy_proposal_without_action_fields_loads(tmp_home):
    # A ManifestWork proposal (older on-disk shape) still defaults cleanly.
    prop = approvals.new_proposal("cluster2", "fix", "summary", [])
    loaded = approvals.load_proposal(prop.id)
    assert loaded.kind == "manifestwork"
    assert loaded.action == ""
    assert loaded.params == {}
