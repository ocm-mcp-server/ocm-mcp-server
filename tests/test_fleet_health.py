# SPDX-FileCopyrightText: 2026 Sandeep Bazar
# SPDX-License-Identifier: Apache-2.0

"""fleet_health fan-out: hub list once, spoke scans concurrent, errors isolated."""

from ocm_mcp_server import ocm

from .test_ocm import patch_hub


def mc(name, available="True"):
    return {
        "metadata": {"name": name},
        "status": {
            "conditions": [{"type": "ManagedClusterConditionAvailable", "status": available}]
        },
    }


def test_fleet_health_whole_fleet_no_spoke_contexts(monkeypatch):
    patch_hub(monkeypatch, items=[mc("c1"), mc("c2", available="False")])
    monkeypatch.setattr(ocm, "_spoke_health", lambda c: (_ for _ in ()).throw(LookupError()))
    res = ocm.fleet_health()
    assert res["fleet"] == {
        "total": 2,
        "available": 1,
        "unavailable": 1,
        "spoke_checked": 0,
        "with_issues": 1,
    }
    # unavailable cluster sorts first (issues-first ordering)
    assert res["clusters"][0]["cluster"] == "c2"
    assert res["clusters"][0]["spoke_view"] == "unavailable (no read context configured)"


def test_fleet_health_subset_and_unknown_name(monkeypatch):
    patch_hub(monkeypatch, items=[mc("c1"), mc("c2")])
    monkeypatch.setattr(
        ocm, "_spoke_health", lambda c: {"unhealthy_pods": [], "degraded_deployments": []}
    )
    res = ocm.fleet_health(clusters="c1, ghost")
    names = {e["cluster"] for e in res["clusters"]}
    assert names == {"c1", "ghost"}
    ghost = next(e for e in res["clusters"] if e["cluster"] == "ghost")
    assert "not found on the hub" in ghost["error"]
    assert res["fleet"]["total"] == 2  # subset never hides fleet size


def test_fleet_health_spoke_error_isolated(monkeypatch):
    patch_hub(monkeypatch, items=[mc("c1"), mc("c2")])

    def boom(cluster):
        if cluster == "c1":
            raise RuntimeError("spoke down")
        return {"unhealthy_pods": [{"name": "p"}], "degraded_deployments": []}

    monkeypatch.setattr(ocm, "_spoke_health", boom)
    res = ocm.fleet_health()
    c1 = next(e for e in res["clusters"] if e["cluster"] == "c1")
    assert c1["error"] == "RuntimeError: spoke down"
    assert res["fleet"]["spoke_checked"] == 1
    assert res["fleet"]["with_issues"] == 2  # error counts as an issue


def test_fleet_health_spoke_note_propagates(monkeypatch):
    patch_hub(monkeypatch, items=[mc("c1")])
    monkeypatch.setattr(
        ocm,
        "_spoke_health",
        lambda c: {"unhealthy_pods": [], "degraded_deployments": [], "note": "truncated"},
    )
    res = ocm.fleet_health()
    assert res["clusters"][0]["note"] == "truncated"
    assert res["clusters"][0]["spoke_view"] == "ok"


def test_fanout_workers_floor(monkeypatch):
    monkeypatch.setenv("OCM_MCP_FANOUT_WORKERS", "0")
    assert ocm._fanout_workers() == 1
    monkeypatch.delenv("OCM_MCP_FANOUT_WORKERS")
    assert ocm._fanout_workers() == 8
