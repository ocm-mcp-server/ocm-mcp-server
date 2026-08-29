# SPDX-FileCopyrightText: 2026 Sandeep Bazar
# SPDX-License-Identifier: Apache-2.0

"""Kubernetes client plumbing.

The MCP server (not the agent) holds the kubeconfig. The hub context is used for
all OCM API access; spoke contexts are optional read-only ServiceAccounts used
for events/logs. In production, replace direct spoke contexts with the OCM
cluster-proxy add-on - see docs/architecture.md.
"""

from __future__ import annotations

import os
import threading
import time

from kubernetes import client, config

from .config import SETTINGS

# Rebuild the API client periodically so a long-lived server process picks up
# rotated credentials / refreshed exec tokens instead of caching them forever.
_CLIENT_TTL = int(os.environ.get("OCM_MCP_CLIENT_TTL", "600"))
_CLIENTS: dict[str, tuple[float, client.ApiClient]] = {}
# Guards the read-check-build-store below. Duplicate client builds under the
# fan-out were benign (last write wins, both clients are equally valid) but the
# lock makes it a non-question rather than a relied-upon accident.
_CLIENTS_LOCK = threading.Lock()

OCM_CLUSTER_GROUP = "cluster.open-cluster-management.io"
OCM_WORK_GROUP = "work.open-cluster-management.io"
OCM_ADDON_GROUP = "addon.open-cluster-management.io"
OCM_OPERATOR_GROUP = "operator.open-cluster-management.io"
OCM_POLICY_GROUP = "policy.open-cluster-management.io"
# ManagedClusterInfo (ACM extended inventory) lives under the internal. group.
OCM_INTERNAL_GROUP = "internal.open-cluster-management.io"
# HyperShift Hosted Control Planes (HCP spokes in ACM/MCE).
HYPERSHIFT_GROUP = "hypershift.openshift.io"


def api_client(context: str = "") -> client.ApiClient:
    """Build (or reuse, within a TTL) an ApiClient for a kubeconfig context.

    "" resolves to the configured hub context (or the current kubeconfig context).
    The client is rebuilt after OCM_MCP_CLIENT_TTL seconds (default 600) so rotated
    or exec-refreshed credentials are eventually picked up rather than cached forever.
    """
    ctx = context or (SETTINGS.hub_context or None)
    key = ctx or "__hub__"
    with _CLIENTS_LOCK:
        now = time.monotonic()
        cached = _CLIENTS.get(key)
        if cached and (now - cached[0]) < _CLIENT_TTL:
            return cached[1]
        fresh = config.new_client_from_config(config_file=SETTINGS.kubeconfig or None, context=ctx)
        _CLIENTS[key] = (now, fresh)
        return fresh


def hub_custom(_api: client.CustomObjectsApi | None = None) -> client.CustomObjectsApi:
    return _api or client.CustomObjectsApi(api_client())


def hub_certificates() -> client.CertificatesV1Api:
    """CertificateSigningRequest client on the hub (cluster-join handshake)."""
    return client.CertificatesV1Api(api_client())


def _spoke_context(cluster: str) -> str:
    """The kubeconfig context for a managed cluster, or a message saying how to set one.

    Shared by every spoke client so the three of them cannot drift in what they
    tell an operator to do about a missing context.
    """
    ctx = SETTINGS.spoke_contexts.get(cluster)
    if not ctx:
        raise LookupError(
            f"No read context configured for cluster '{cluster}'. "
            "Set OCM_MCP_SPOKE_CONTEXTS=name=context,... (see README)."
        )
    return ctx


def spoke_core(cluster: str) -> client.CoreV1Api:
    """Read-only CoreV1 client for a managed cluster, if a context is configured."""
    return client.CoreV1Api(api_client(_spoke_context(cluster)))


def spoke_apps(cluster: str) -> client.AppsV1Api:
    return client.AppsV1Api(api_client(_spoke_context(cluster)))


def spoke_custom(cluster: str) -> client.CustomObjectsApi:
    """Custom-objects client on a managed cluster.

    AppliedManifestWork is the only thing this reads today. It lives on the SPOKE,
    not the hub: it is the agent's own record of what it actually materialised
    there, which is what makes it worth reading after an apply.
    """
    return client.CustomObjectsApi(api_client(_spoke_context(cluster)))
