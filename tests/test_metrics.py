# SPDX-FileCopyrightText: 2026 Sandeep Bazar
# SPDX-License-Identifier: Apache-2.0

from ocm_mcp_server import metrics


def test_record_and_render():
    metrics.record("list_clusters", "ok", 12)
    metrics.record("list_clusters", "ok", 8)
    metrics.record("apply_manifestwork", "rejected", 3)
    out = metrics.render()
    assert 'ocm_mcp_tool_calls_total{tool="list_clusters",outcome="ok"} 2' in out
    assert 'ocm_mcp_tool_calls_total{tool="apply_manifestwork",outcome="rejected"} 1' in out
    assert "ocm_mcp_tool_duration_ms_sum" in out
