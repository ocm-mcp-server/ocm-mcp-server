# SPDX-FileCopyrightText: 2026 Sandeep Bazar
# SPDX-License-Identifier: Apache-2.0

"""Coverage for tracing.py's OTel setup, chain-head edge cases, and failure paths."""

import json
import sys
import types
from contextlib import contextmanager

import pytest

from ocm_mcp_server import metrics, tracing
from ocm_mcp_server.config import SETTINGS

# --- _get_tracer: OTel import + exporter wiring (lines 61-74) -----------------


class _FakeExporter:
    pass


class _FakeProcessor:
    def __init__(self, exporter):
        self.exporter = exporter


class _FakeResource:
    @staticmethod
    def create(attrs):
        return dict(attrs)


class _FakeProvider:
    def __init__(self, resource=None):
        self.resource = resource
        self.processors = []

    def add_span_processor(self, processor):
        self.processors.append(processor)


def _install_fake_otel(monkeypatch):
    """Register a minimal fake OpenTelemetry SDK in sys.modules and return the
    dict that records what tracing._get_tracer wired up."""
    recorded = {}

    trace_mod = types.ModuleType("opentelemetry.trace")
    trace_mod.set_tracer_provider = lambda p: recorded.__setitem__("provider", p)
    tracer_sentinel = object()

    def get_tracer(name):
        recorded["tracer_name"] = name
        return tracer_sentinel

    trace_mod.get_tracer = get_tracer
    recorded["tracer_sentinel"] = tracer_sentinel

    otel_pkg = types.ModuleType("opentelemetry")
    otel_pkg.trace = trace_mod

    exporter_mod = types.ModuleType("opentelemetry.exporter.otlp.proto.http.trace_exporter")
    exporter_mod.OTLPSpanExporter = _FakeExporter
    resources_mod = types.ModuleType("opentelemetry.sdk.resources")
    resources_mod.Resource = _FakeResource
    sdk_trace_mod = types.ModuleType("opentelemetry.sdk.trace")
    sdk_trace_mod.TracerProvider = _FakeProvider
    export_mod = types.ModuleType("opentelemetry.sdk.trace.export")
    export_mod.BatchSpanProcessor = _FakeProcessor

    monkeypatch.setitem(sys.modules, "opentelemetry", otel_pkg)
    monkeypatch.setitem(sys.modules, "opentelemetry.trace", trace_mod)
    monkeypatch.setitem(
        sys.modules, "opentelemetry.exporter.otlp.proto.http.trace_exporter", exporter_mod
    )
    monkeypatch.setitem(sys.modules, "opentelemetry.sdk.resources", resources_mod)
    monkeypatch.setitem(sys.modules, "opentelemetry.sdk.trace", sdk_trace_mod)
    monkeypatch.setitem(sys.modules, "opentelemetry.sdk.trace.export", export_mod)
    return recorded


def test_get_tracer_configures_otlp_exporter(monkeypatch):
    monkeypatch.setattr(SETTINGS, "otel_endpoint", "http://localhost:4318", raising=False)
    monkeypatch.setattr(tracing, "_tracer", None)
    recorded = _install_fake_otel(monkeypatch)

    tracer = tracing._get_tracer()

    assert tracer is recorded["tracer_sentinel"]
    assert recorded["tracer_name"] == "ocm-mcp-server"
    provider = recorded["provider"]
    assert isinstance(provider, _FakeProvider)
    assert provider.resource == {"service.name": "ocm-mcp-server"}
    assert len(provider.processors) == 1
    processor = provider.processors[0]
    assert isinstance(processor, _FakeProcessor)
    assert isinstance(processor.exporter, _FakeExporter)
    # Cached: a second call returns the same tracer without re-running setup.
    recorded.pop("provider")
    assert tracing._get_tracer() is tracer
    assert "provider" not in recorded


def test_get_tracer_falls_back_to_disabled_when_otel_missing(monkeypatch):
    monkeypatch.setattr(SETTINGS, "otel_endpoint", "http://localhost:4318", raising=False)
    monkeypatch.setattr(tracing, "_tracer", None)
    # A None entry in sys.modules makes `from opentelemetry import trace` raise ImportError.
    monkeypatch.setitem(sys.modules, "opentelemetry", None)

    assert tracing._get_tracer() is False
    # The disabled state is cached too.
    assert tracing._get_tracer() is False


# --- _chain_head edge cases (lines 86, 95, 98-99) -----------------------------


def test_chain_head_missing_log_file(monkeypatch, tmp_path):
    missing = tmp_path / "does-not-exist.jsonl"
    # SETTINGS.audit_log is a property that touches the file into existence, so
    # point the property itself at a path that is never created.
    monkeypatch.setattr(type(SETTINGS), "audit_log", property(lambda self: missing))
    assert tracing._chain_head() == (0, "")
    assert not missing.exists()


def test_chain_head_skips_trailing_blank_lines(tmp_home):
    SETTINGS.audit_log.write_text('{"seq": 3, "hash": "abc"}\n\n   \n')
    assert tracing._chain_head() == (3, "abc")


def test_chain_head_torn_last_line_resets(tmp_home):
    SETTINGS.audit_log.write_text('{"seq": 1, "hash": "abc"}\n{"torn')
    assert tracing._chain_head() == (0, "")


# --- _safe_audit failure path (lines 140-141) ---------------------------------


def test_safe_audit_reports_failure_to_stderr(monkeypatch, capsys):
    def boom(entry):
        raise RuntimeError("disk full")

    monkeypatch.setattr(tracing, "audit", boom)
    tracing._safe_audit({"tool": "x"})  # must not raise
    err = capsys.readouterr().err
    assert "audit write failed" in err
    assert "RuntimeError: disk full" in err


# --- verify_audit_chain edge cases (lines 152, 155-156) -----------------------


def test_verify_audit_chain_ignores_blank_lines(tmp_home):
    tracing.audit({"tool": "list_clusters", "outcome": "ok"})
    with SETTINGS.audit_log.open("a") as f:
        f.write("\n   \n")
    ok, msg = tracing.verify_audit_chain()
    assert ok is True
    assert "intact over 1 entries" in msg


def test_verify_audit_chain_flags_unparseable_line(tmp_path):
    log = tmp_path / "audit.jsonl"
    log.write_text("not json at all\n")
    ok, msg = tracing.verify_audit_chain(log)
    assert ok is False
    assert msg == "audit chain broken at line 1 (unparseable entry)"


# --- traced_tool span path (lines 201-205) ------------------------------------


class _FakeSpan:
    def __init__(self):
        self.attributes = {}

    def set_attribute(self, key, value):
        self.attributes[key] = value


class _FakeTracer:
    def __init__(self):
        self.spans = []

    @contextmanager
    def start_as_current_span(self, name):
        span = _FakeSpan()
        self.spans.append((name, span))
        yield span


def test_traced_tool_records_span_with_bounded_args(tmp_home, monkeypatch):
    fake = _FakeTracer()
    monkeypatch.setattr(tracing, "_tracer", fake)

    @tracing.traced_tool
    def sample(cluster, approval_token, blob):
        return "ok"

    assert sample(cluster="c1", approval_token="secret", blob="x" * 500) == "ok"

    assert len(fake.spans) == 1
    name, span = fake.spans[0]
    assert name == "tool.sample"
    assert span.attributes["arg.cluster"] == "c1"
    # Span attribute values are truncated to 200 chars.
    assert span.attributes["arg.blob"] == "x" * 200
    # The approval token never reaches the span.
    assert "arg.approval_token" not in span.attributes
    # The audit line is still written, with the token redacted.
    rec = json.loads(SETTINGS.audit_log.read_text().strip().splitlines()[-1])
    assert rec["tool"] == "sample"
    assert rec["outcome"] == "ok"
    assert rec["args"]["approval_token"] == "<redacted>"


def test_traced_tool_span_path_still_audits_on_exception(tmp_home, monkeypatch):
    fake = _FakeTracer()
    monkeypatch.setattr(tracing, "_tracer", fake)

    @tracing.traced_tool
    def boom():
        raise ValueError("nope")

    with pytest.raises(ValueError):
        boom()
    assert fake.spans[0][0] == "tool.boom"
    rec = json.loads(SETTINGS.audit_log.read_text().strip().splitlines()[-1])
    assert rec["outcome"] == "error"
    assert "ValueError: nope" in rec["error"]


# --- traced_tool metrics failure path (lines 228-229) -------------------------


def test_traced_tool_survives_metrics_failure(tmp_home, monkeypatch):
    monkeypatch.setattr(tracing, "_tracer", False)

    def bad_record(tool, outcome, duration_ms):
        raise RuntimeError("metrics backend down")

    monkeypatch.setattr(metrics, "record", bad_record)

    @tracing.traced_tool
    def sample():
        return "ok"

    assert sample() == "ok"  # the metrics failure must never surface
    rec = json.loads(SETTINGS.audit_log.read_text().strip().splitlines()[-1])
    assert rec["tool"] == "sample"
    assert rec["outcome"] == "ok"
