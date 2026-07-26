# SPDX-FileCopyrightText: 2026 Sandeep Bazar
# SPDX-License-Identifier: Apache-2.0

"""Lightweight, dependency-free Prometheus metrics.

Every tool call increments in-process counters (calls by tool and outcome, plus a
duration sum). When OCM_MCP_METRICS_PORT is set, a tiny stdlib HTTP server exposes them
at /metrics in Prometheus text format - no prometheus_client dependency, no extra attack
surface beyond a read-only, localhost-bindable endpoint.
"""

from __future__ import annotations

import threading
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, HTTPServer

_lock = threading.Lock()
_calls: dict[tuple[str, str], int] = defaultdict(int)
_duration_ms: dict[str, float] = defaultdict(float)
_started = False


def record(tool: str, outcome: str, duration_ms: float) -> None:
    with _lock:
        _calls[(tool, outcome)] += 1
        _duration_ms[tool] += duration_ms


def _escape(v: str) -> str:
    return v.replace("\\", "\\\\").replace('"', '\\"')


def render() -> str:
    lines = [
        "# HELP ocm_mcp_tool_calls_total Tool calls by tool and outcome.",
        "# TYPE ocm_mcp_tool_calls_total counter",
    ]
    with _lock:
        for (tool, outcome), n in sorted(_calls.items()):
            lines.append(
                f'ocm_mcp_tool_calls_total{{tool="{_escape(tool)}",'
                f'outcome="{_escape(outcome)}"}} {n}'
            )
        lines += [
            "# HELP ocm_mcp_tool_duration_ms_sum Cumulative tool duration in milliseconds.",
            "# TYPE ocm_mcp_tool_duration_ms_sum counter",
        ]
        for tool, ms in sorted(_duration_ms.items()):
            lines.append(f'ocm_mcp_tool_duration_ms_sum{{tool="{_escape(tool)}"}} {ms:.0f}')
    return "\n".join(lines) + "\n"


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path.rstrip("/") not in ("/metrics", ""):
            self.send_error(404)
            return
        body = render().encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args: object) -> None:  # silence access logging
        pass


def start_metrics_server(port: int, host: str | None = None) -> None:
    """Start the /metrics HTTP server once, in a daemon thread.

    Binds localhost by default so the endpoint is not exposed network-wide; set
    OCM_MCP_METRICS_HOST (e.g. 0.0.0.0) to override when a scraper needs remote access.
    """
    import os

    global _started
    if _started or port <= 0:
        return
    _started = True
    bind = host or os.environ.get("OCM_MCP_METRICS_HOST", "127.0.0.1")
    server = HTTPServer((bind, port), _Handler)
    threading.Thread(target=server.serve_forever, name="ocm-mcp-metrics", daemon=True).start()
