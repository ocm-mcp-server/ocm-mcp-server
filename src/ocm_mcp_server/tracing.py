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
import hashlib
import json
import os
import sys
import time
from collections.abc import Callable
from typing import Any

from .config import SETTINGS
from .filelock import locked

_tracer = None


def _actor() -> str:
    """The process identity attributed to a tool call. The human approver of a write is
    recorded separately on the proposal (approved_by); this is who is running the server."""
    return f"{os.environ.get('USER', 'unknown')}:{os.getpid()}"


def _canonical(entry: dict[str, Any]) -> str:
    return json.dumps(entry, sort_keys=True, separators=(",", ":"), default=str)


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

        provider = TracerProvider(resource=Resource.create({"service.name": "ocm-mcp-server"}))
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
        trace.set_tracer_provider(provider)
        _tracer = trace.get_tracer("ocm-mcp-server")
    except ImportError:
        _tracer = False
    return _tracer


def _chain_head() -> tuple[int, str]:
    """(sequence, hash) of the last audit entry, read from the log itself.

    Derived from the log's last line - not a separate sidecar - so losing or corrupting
    an auxiliary file can never desync the head and raise a false "tampering" alarm. Only
    the tail is read, so appends stay effectively O(1).
    """
    path = SETTINGS.audit_log
    if not path.exists():
        return 0, ""
    with open(path, "rb") as f:
        f.seek(0, 2)
        size = f.tell()
        f.seek(max(0, size - 65536))
        tail = f.read().decode(errors="replace")
    for line in reversed(tail.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            return 0, ""  # torn last line; verify_audit_chain will flag it
        return int(rec.get("seq", 0)), str(rec.get("hash", ""))
    return 0, ""


def audit(entry: dict[str, Any]) -> None:
    """Append one tamper-evident audit line under a lock.

    Each entry carries a monotonic `seq`, the previous entry's hash (`prev`), and its own
    `hash` = sha256(prev + canonical(entry)). Any edit, deletion, or reordering breaks the
    chain, which `verify_audit_chain` detects. Writes are fsynced under a lock.
    """
    path = SETTINGS.audit_log
    entry["ts"] = time.time()
    entry.setdefault("actor", _actor())
    with locked(path):
        seq, prev = _chain_head()
        entry["seq"] = seq + 1
        entry["prev"] = prev
        entry["hash"] = hashlib.sha256(
            (prev + _canonical({k: entry[k] for k in entry if k != "hash"})).encode()
        ).hexdigest()
        with path.open("a") as f:
            f.write(json.dumps(entry, default=str) + "\n")
            f.flush()
            os.fsync(f.fileno())


def _safe_audit(entry: dict[str, Any]) -> None:
    """Audit best-effort: a logging failure must never change a tool's result. On failure
    the error is surfaced to stderr (not swallowed silently) so it is still noticed."""
    try:
        audit(entry)
    except Exception as exc:  # noqa: BLE001 - audit must not mask the tool outcome
        print(f"ocm-mcp-server: audit write failed: {type(exc).__name__}: {exc}", file=sys.stderr)


def verify_audit_chain(path: Any = None) -> tuple[bool, str]:
    """Recompute the hash chain over the audit log. Returns (ok, message)."""
    log = path or SETTINGS.audit_log
    prev, n = "", 0
    with open(log) as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                return False, f"audit chain broken at line {i} (unparseable entry)"
            stated = rec.get("hash", "")
            recomputed = hashlib.sha256(
                (prev + _canonical({k: rec[k] for k in rec if k != "hash"})).encode()
            ).hexdigest()
            if rec.get("prev") != prev or stated != recomputed:
                return False, f"audit chain broken at line {i} (seq {rec.get('seq')})"
            prev, n = stated, n + 1
    return True, f"audit chain intact over {n} entries"


def classify_outcome(result: Any) -> str:
    """Turn a tool's return value into a truthful audit outcome.

    Tools return normally even when they refuse: a string beginning REJECTED / FAILED /
    ERROR / UNAVAILABLE is NOT a success, and must not be audited as 'ok', or the audit
    log (and the eval harness that scores from it) reports false successes.
    """
    if isinstance(result, str):
        s = result.lstrip()
        if s.startswith("REJECTED"):
            return "rejected"
        if s.startswith("FAILED"):
            return "failed"
        if s.startswith("ERROR"):
            return "error"
        if s.startswith("UNAVAILABLE"):
            return "unavailable"
    return "ok"


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
                    result = run()
            else:
                result = run()
            outcome = classify_outcome(result)
            return result
        except Exception as exc:
            outcome, error = "error", f"{type(exc).__name__}: {exc}"
            raise
        finally:
            duration_ms = round((time.time() - start) * 1000)
            _safe_audit(
                {
                    "tool": fn.__name__,
                    "args": {
                        k: (v if k != "approval_token" else "<redacted>") for k, v in kwargs.items()
                    },
                    "outcome": outcome,
                    "error": error[:500],
                    "duration_ms": duration_ms,
                }
            )
            try:
                from . import metrics

                metrics.record(fn.__name__, outcome, duration_ms)
            except Exception:  # noqa: BLE001, S110 - metrics must never affect a tool call
                pass

    return wrapper
