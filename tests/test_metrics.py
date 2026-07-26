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


def test_metrics_http_endpoint():
    import socket
    import urllib.error
    import urllib.request

    metrics.record("list_clusters", "ok", 7)
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    metrics.start_metrics_server(port, host="127.0.0.1")

    body = None
    for _ in range(200):  # brief busy-retry until the daemon thread is serving
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/metrics", timeout=2) as r:
                body = r.read().decode()
            break
        except (urllib.error.URLError, ConnectionError):
            continue
    assert body is not None and "ocm_mcp_tool_calls_total" in body

    # An unknown path returns 404.
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/nope", timeout=2)
        code = 200
    except urllib.error.HTTPError as e:
        code = e.code
    assert code == 404
