# SPDX-FileCopyrightText: 2026 Sandeep Bazar
# SPDX-License-Identifier: Apache-2.0

"""Tracing and audit for every tool call.

Two independent records:
- OpenTelemetry spans (optional; enabled when OTEL_EXPORTER_OTLP_ENDPOINT is set,
  e.g. the Jaeger container started by hack/bootstrap.sh).
- A local append-only audit log (always on): one JSON line per tool call with
  arguments, outcome, and duration. The eval harness scores safety from this file.
"""

from __future__ import annotations

import functools
import json
import time
from collections.abc import Callable
from typing import Any

from .config import SETTINGS

_tracer = None


def _get_tracer():
    global _tracer
    if _tracer is not None:
        return _tracer
    if not SETTINGS.otel_endpoint:
        _tracer = False
        return _tracer
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        provider = TracerProvider(
            resource=Resource.create({"service.name": "ocm-mcp-server"})
        )
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
        trace.set_tracer_provider(provider)
        _tracer = trace.get_tracer("ocm-mcp-server")
    except ImportError:
        _tracer = False
    return _tracer


def audit(entry: dict[str, Any]) -> None:
    entry["ts"] = time.time()
    with SETTINGS.audit_log.open("a") as f:
        f.write(json.dumps(entry, default=str) + "\n")


def traced_tool(fn: Callable) -> Callable:
    """Wrap an MCP tool: one OTel span + one audit line per invocation."""

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        tracer = _get_tracer()
        start = time.time()
        outcome, error = "ok", ""

        def run() -> Any:
            return fn(*args, **kwargs)

        try:
            if tracer:
                with tracer.start_as_current_span(f"tool.{fn.__name__}") as span:
                    for key, value in kwargs.items():
                        if key not in ("approval_token",):
                            span.set_attribute(f"arg.{key}", str(value)[:200])
                    return run()
            return run()
        except Exception as exc:
            outcome, error = "error", f"{type(exc).__name__}: {exc}"
            raise
        finally:
            audit(
                {
                    "tool": fn.__name__,
                    "args": {
                        k: (v if k != "approval_token" else "<redacted>")
                        for k, v in kwargs.items()
                    },
                    "outcome": outcome,
                    "error": error[:500],
                    "duration_ms": round((time.time() - start) * 1000),
                }
            )

    return wrapper
