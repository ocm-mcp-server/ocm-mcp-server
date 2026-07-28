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


_MAX_ARG_LEN = 2000


def _audit_arg(key: str, value: Any) -> Any:
    """Redact the approval token and bound large argument values, so one big argument
    (e.g. a manifests_json blob) can't bloat the audit line or overflow the hash-chain
    tail read."""
    if key == "approval_token":
        return "<redacted>"
    if isinstance(value, str) and len(value) > _MAX_ARG_LEN:
        return value[:_MAX_ARG_LEN] + f"...(+{len(value) - _MAX_ARG_LEN} chars)"
    return value


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
    `hash` = sha256(prev + canonical(entry)). `verify_audit_chain` detects any edit,
    reordering, or deletion in the middle of the log. Truncation of the tail and wholesale
    rewrites are covered separately: `ocm-mcp audit-anchor` signs the chain head with the
    off-box approval key, and `verify_audit_anchors` fails if the log no longer extends an
    anchored head. Entries newer than the last anchor remain unprotected until the next
    anchor. Writes are fsynced under a lock.
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
        line = json.dumps(entry, default=str)
        with path.open("a") as f:
            f.write(line + "\n")
            f.flush()
            os.fsync(f.fileno())
    if SETTINGS.audit_echo_stderr:
        # Echo to stderr (not stdout - that is the MCP transport) for SIEM forwarding.
        print(line, file=sys.stderr, flush=True)


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


def anchor_audit_chain() -> dict[str, Any]:
    """Sign the current audit-chain head with the approval SIGNER key.

    Run from the trusted terminal (`ocm-mcp audit-anchor`), like minting an
    approval: the server holds only the verifier key, so a compromised server
    cannot forge anchors. Each anchor binds (seq, hash) under an Ed25519
    signature; once anchored, deleting or rewriting the log up to that head is
    detectable by `verify_audit_anchors` - closing the tail-truncation gap the
    bare hash chain cannot see.
    """
    from .approvals import ApprovalError, _b64, _private_key

    seq, head = _chain_head()
    if seq == 0:
        raise ApprovalError("Nothing to anchor: the audit log has no entries.")
    anchor = {"seq": seq, "hash": head, "anchored_at": int(time.time())}
    anchor["sig"] = _b64(_private_key().sign(_canonical(anchor).encode()))
    path = SETTINGS.audit_anchors_path
    with locked(path), path.open("a") as f:
        f.write(json.dumps(anchor) + "\n")
        f.flush()
        os.fsync(f.fileno())
    path.chmod(0o600)
    return anchor


def verify_audit_anchors() -> tuple[bool, str]:
    """Check every signed anchor against the audit log with the verifier key.

    Detects what the bare hash chain cannot: a truncated tail (an anchored seq
    no longer present) and a wholesale rewrite (an anchored hash that no longer
    matches). Entries newer than the last anchor are not yet protected - the
    message says how many, so a monitoring job can alert on a growing gap.
    """
    from .approvals import _unb64, _verifier_keys

    anchors_path = SETTINGS.audit_anchors_path
    if not anchors_path.exists() or not anchors_path.read_text().strip():
        return True, "no anchors recorded yet (run 'ocm-mcp audit-anchor' from a trusted terminal)"

    by_seq: dict[int, str] = {}
    with open(SETTINGS.audit_log) as f:
        for line in f:
            line = line.strip()
            if line:
                with_hash = json.loads(line)
                by_seq[int(with_hash.get("seq", 0))] = str(with_hash.get("hash", ""))
    head_seq = max(by_seq) if by_seq else 0

    keys = _verifier_keys()
    checked = 0
    last_anchored = 0
    with open(anchors_path) as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                anchor = json.loads(line)
            except ValueError:
                return False, f"anchor file corrupt at line {i} (unparseable entry)"
            sig = _unb64(str(anchor.get("sig", "")))
            payload = _canonical({k: anchor[k] for k in anchor if k != "sig"}).encode()
            if not any(_valid_anchor_sig(k, sig, payload) for k in keys):
                return False, f"anchor at line {i} has an invalid signature"
            seq, stated = int(anchor.get("seq", 0)), str(anchor.get("hash", ""))
            if by_seq.get(seq) != stated:
                return False, (
                    f"anchor at line {i} (seq {seq}) does not match the log - the audit "
                    "log was truncated or rewritten after this head was anchored"
                )
            checked += 1
            last_anchored = max(last_anchored, seq)
    unanchored = head_seq - last_anchored
    return True, (
        f"{checked} anchor(s) verified; log head is seq {head_seq}, last anchored seq "
        f"{last_anchored} ({unanchored} newer entr{'y' if unanchored == 1 else 'ies'} "
        "not yet anchored)"
    )


def _valid_anchor_sig(key: Any, sig: bytes, payload: bytes) -> bool:
    try:
        key.verify(sig, payload)
        return True
    except Exception:  # noqa: BLE001 - any signature failure means "not this key"
        return False


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
                    "args": {k: _audit_arg(k, v) for k, v in kwargs.items()},
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
