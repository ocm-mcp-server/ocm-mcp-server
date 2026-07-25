# SPDX-FileCopyrightText: 2026 Sandeep Bazar
# SPDX-License-Identifier: Apache-2.0

import time

import pytest

from ocm_mcp_server import approvals
from ocm_mcp_server.approvals import ApprovalError

MANIFESTS = [
    {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": "payments", "namespace": "shop"},
        "spec": {"replicas": 2},
    }
]


def make_proposal():
    return approvals.new_proposal("cluster2", "fix-payments", "pin image back to v1.9", MANIFESTS)


def test_token_roundtrip(tmp_home):
    prop = make_proposal()
    token = approvals.mint_token(prop)
    approvals.verify_token(prop, token)  # must not raise


def test_token_rejected_for_other_proposal(tmp_home):
    first = make_proposal()
    second = approvals.new_proposal("cluster3", "other", "different change", MANIFESTS)
    token = approvals.mint_token(first)
    with pytest.raises(ApprovalError, match="different proposal"):
        approvals.verify_token(second, token)


def test_token_invalid_after_content_change(tmp_home):
    prop = make_proposal()
    token = approvals.mint_token(prop)
    prop.content_hash = approvals.content_hash(
        prop.cluster, prop.name, [{**MANIFESTS[0], "spec": {"replicas": 50}}]
    )
    with pytest.raises(ApprovalError, match="content mismatch"):
        approvals.verify_token(prop, token)


def test_token_expiry(tmp_home):
    prop = make_proposal()
    token = approvals.mint_token(prop, ttl_seconds=-1)
    with pytest.raises(ApprovalError, match="expired"):
        approvals.verify_token(prop, token)


def test_malformed_tokens(tmp_home):
    prop = make_proposal()
    for bad in ["", "abc", "a.b", "a.b.c.d", f"{prop.id}.notanumber.deadbeef"]:
        with pytest.raises(ApprovalError):
            approvals.verify_token(prop, bad)


def test_tampered_signature(tmp_home):
    prop = make_proposal()
    token = approvals.mint_token(prop)
    head, _, sig = token.rpartition(".")
    flipped = ("0" if sig[0] != "0" else "1") + sig[1:]
    with pytest.raises(ApprovalError):
        approvals.verify_token(prop, f"{head}.{flipped}")


def test_proposal_persistence(tmp_home):
    prop = make_proposal()
    loaded = approvals.load_proposal(prop.id)
    assert loaded.cluster == "cluster2"
    assert loaded.status == "pending"
    assert loaded.content_hash == prop.content_hash
    assert approvals.list_proposals(status="pending")


def test_unknown_proposal(tmp_home):
    with pytest.raises(ApprovalError, match="No proposal"):
        approvals.load_proposal("doesnotexist")


def test_expiry_uses_wall_clock(tmp_home, monkeypatch):
    prop = make_proposal()
    token = approvals.mint_token(prop, ttl_seconds=3600)
    future = time.time() + 7200
    monkeypatch.setattr(time, "time", lambda: future)
    with pytest.raises(ApprovalError, match="expired"):
        approvals.verify_token(prop, token)
