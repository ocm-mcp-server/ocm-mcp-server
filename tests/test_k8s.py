# SPDX-FileCopyrightText: 2026 Sandeep Bazar
# SPDX-License-Identifier: Apache-2.0

"""Kubernetes client plumbing: caching, context resolution, and the no-context guard."""

import pytest

from ocm_mcp_server import k8s
from ocm_mcp_server.config import SETTINGS


def test_spoke_core_without_context_raises(monkeypatch):
    monkeypatch.setattr(SETTINGS, "spoke_contexts", {}, raising=False)
    with pytest.raises(LookupError, match="No read context"):
        k8s.spoke_core("cluster1")


def test_spoke_apps_without_context_raises(monkeypatch):
    monkeypatch.setattr(SETTINGS, "spoke_contexts", {}, raising=False)
    with pytest.raises(LookupError, match="No read context"):
        k8s.spoke_apps("cluster1")


def test_api_client_caches_within_ttl(monkeypatch):
    calls = {"n": 0}

    def fake_new_client(config_file=None, context=None):
        calls["n"] += 1
        return object()

    monkeypatch.setattr(k8s.config, "new_client_from_config", fake_new_client)
    k8s._CLIENTS.clear()
    a = k8s.api_client("ctxA")
    b = k8s.api_client("ctxA")
    assert a is b and calls["n"] == 1  # second call served from cache


def test_hub_and_spoke_clients_built(monkeypatch):
    monkeypatch.setattr(k8s, "api_client", lambda ctx="": ("client", ctx))
    monkeypatch.setattr(k8s.client, "CustomObjectsApi", lambda c: ("custom", c))
    monkeypatch.setattr(k8s.client, "CertificatesV1Api", lambda c: ("certs", c))
    monkeypatch.setattr(k8s.client, "CoreV1Api", lambda c: ("core", c))
    monkeypatch.setattr(SETTINGS, "spoke_contexts", {"cluster1": "kind-cluster1"}, raising=False)
    assert k8s.hub_custom()[0] == "custom"
    assert k8s.hub_certificates()[0] == "certs"
    assert k8s.spoke_core("cluster1")[0] == "core"


def test_spoke_apps_client_built(monkeypatch):
    monkeypatch.setattr(k8s, "api_client", lambda ctx="": ("client", ctx))
    monkeypatch.setattr(k8s.client, "AppsV1Api", lambda c: ("apps", c))
    monkeypatch.setattr(SETTINGS, "spoke_contexts", {"cluster1": "kind-cluster1"}, raising=False)
    assert k8s.spoke_apps("cluster1") == ("apps", ("client", "kind-cluster1"))


def test_spoke_custom_without_context_raises(monkeypatch):
    monkeypatch.setattr(SETTINGS, "spoke_contexts", {}, raising=False)
    with pytest.raises(LookupError, match="No read context"):
        k8s.spoke_custom("cluster1")


def test_spoke_custom_uses_the_cluster_context(monkeypatch):
    """AppliedManifestWork lives on the spoke, so this client must not be the hub's."""
    seen = {}

    def fake_api_client(context=""):
        seen["context"] = context

    monkeypatch.setattr(SETTINGS, "spoke_contexts", {"cluster1": "kind-cluster1"}, raising=False)
    monkeypatch.setattr(k8s, "api_client", fake_api_client)
    k8s.spoke_custom("cluster1")
    assert seen["context"] == "kind-cluster1"
