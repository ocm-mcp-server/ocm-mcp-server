# SPDX-FileCopyrightText: 2026 Sandeep Bazar
# SPDX-License-Identifier: Apache-2.0

"""Regression tests for the review hardening fixes (H1, M2, M4, M5)."""

import pytest

from ocm_mcp_server import approvals, guardrails
from ocm_mcp_server.config import SETTINGS

MANIFEST = {
    "apiVersion": "apps/v1",
    "kind": "Deployment",
    "metadata": {"name": "payments", "namespace": "shop"},
    "spec": {"template": {"spec": {"containers": [{"name": "c", "image": "reg/app:1.2.3"}]}}},
}


# --- H1: the HMAC key is cached in-process and rotation invalidates it -----------


def test_secret_is_cached(tmp_home):
    first = SETTINGS.secret()
    # Delete the file on disk; a cached read must still succeed with the same value.
    (tmp_home / "secret").unlink()
    assert SETTINGS.secret() == first


def test_rotate_secret_changes_key_and_invalidates_tokens(tmp_home):
    prop = approvals.new_proposal("c2", "fix", "summary", [MANIFEST])
    token = approvals.mint_token(prop)
    approvals.verify_token(prop, token)  # valid before rotation
    SETTINGS.rotate_secret()
    with pytest.raises(approvals.ApprovalError):
        approvals.verify_token(prop, token)  # old token is now worthless


# --- M4: proposal IDs are full UUIDs, not 8 hex chars ---------------------------


def test_proposal_ids_are_full_uuid(tmp_home):
    p1 = approvals.new_proposal("c", "a", "s", [MANIFEST])
    p2 = approvals.new_action_proposal("c", "cordon", "s", {})
    assert len(p1.id) == 32
    assert len(p2.id) == 32


# --- M2: content-hash integrity is re-checked at apply time ---------------------


def test_content_intact_detects_tampered_manifests(tmp_home):
    from ocm_mcp_server.server import _content_intact

    prop = approvals.new_proposal("c2", "fix", "summary", [MANIFEST])
    assert _content_intact(prop) is None  # pristine proposal is fine
    # Simulate an at-rest edit: change the manifests but leave content_hash stale.
    prop.manifests = [{**MANIFEST, "spec": {"replicas": 99}}]
    msg = _content_intact(prop)
    assert msg is not None and "content hash" in msg


# --- M5: pod-spec extraction is robust across workload kinds --------------------


def test_pod_spec_handles_cronjob():
    cron = {
        "kind": "CronJob",
        "spec": {
            "jobTemplate": {
                "spec": {"template": {"spec": {"containers": [{"name": "c", "image": "x:1"}]}}}
            }
        },
    }
    containers = guardrails._containers(cron)
    assert containers and containers[0]["image"] == "x:1"


def test_pod_spec_handles_statefulset_like_deployment():
    sts = {
        "kind": "StatefulSet",
        "spec": {"template": {"spec": {"containers": [{"name": "c", "image": "y:2"}]}}},
    }
    assert guardrails._containers(sts)[0]["image"] == "y:2"
