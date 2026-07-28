# SPDX-FileCopyrightText: 2026 Sandeep Bazar
# SPDX-License-Identifier: Apache-2.0

"""MCP resources: read-only fleet state, a strict subset of the read tools."""

from __future__ import annotations

import json

import pytest

from ocm_mcp_server import ocm, server


def test_resource_clusters(tmp_home, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ocm, "list_managed_clusters", lambda: [{"name": "c1"}])
    assert json.loads(server.resource_clusters()) == [{"name": "c1"}]


def test_resource_cluster_template(tmp_home, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ocm, "get_managed_cluster", lambda cluster: {"name": cluster})
    assert json.loads(server.resource_cluster("c2")) == {"name": "c2"}


def test_resource_policies(tmp_home, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ocm, "list_policies", lambda namespace: [{"policy": "p", "ns": namespace}])
    assert json.loads(server.resource_policies()) == [{"policy": "p", "ns": ""}]


def test_resource_proposals_matches_tool(tmp_home) -> None:
    # The resource and the tool must expose the same pending-proposal view.
    assert server.resource_proposals() == server.list_pending_proposals()
    assert json.loads(server.resource_proposals()) == []


def test_resource_audit_tail(tmp_home) -> None:
    from ocm_mcp_server.tracing import audit

    audit({"tool": "t", "args": {}, "outcome": "ok", "error": "", "duration_ms": 1})
    entries = json.loads(server.resource_audit_tail())
    # The resource read itself is audited too, so at least the seeded entry is present.
    assert any(e["tool"] == "t" for e in entries)


def test_resource_guardrails_reflects_config(tmp_home) -> None:
    cfg = json.loads(server.resource_guardrails())
    assert "apps/v1/Deployment" in cfg["allowed_gvk"]
    assert "cordon" in cfg["allowed_cluster_actions"]
    assert "configMap" in cfg["allowed_volume_types"]
    assert "kube-system" in cfg["protected_namespaces"]
    assert cfg["max_manifests_per_proposal"] == 10
    assert cfg["read_only_mode"] is False


def test_resources_are_registered() -> None:
    """Every ocm:// resource must actually be registered with the MCP server."""
    import anyio

    async def collect() -> set[str]:
        static = {str(r.uri) for r in await server.mcp.list_resources()}
        templates = {t.uriTemplate for t in await server.mcp.list_resource_templates()}
        return static | templates

    uris = anyio.run(collect)
    assert {
        "ocm://clusters",
        "ocm://policies",
        "ocm://proposals",
        "ocm://audit/tail",
        "ocm://guardrails",
        "ocm://clusters/{cluster}",
    } <= uris
