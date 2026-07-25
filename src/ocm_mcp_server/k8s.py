# SPDX-FileCopyrightText: 2026 Sandeep Bazar
# SPDX-License-Identifier: Apache-2.0

"""Kubernetes client plumbing.

The MCP server (not the agent) holds the kubeconfig. The hub context is used for
all OCM API access; spoke contexts are optional read-only ServiceAccounts used
for events/logs. In production, replace direct spoke contexts with the OCM
cluster-proxy add-on - see docs/architecture.md.
"""

from __future__ import annotations

from functools import cache

from kubernetes import client, config

from .config import SETTINGS

OCM_CLUSTER_GROUP = "cluster.open-cluster-management.io"
OCM_WORK_GROUP = "work.open-cluster-management.io"


@cache
def api_client(context: str = "") -> client.ApiClient:
    """Build an ApiClient for a kubeconfig context ("" = current/hub context)."""
    ctx = context or (SETTINGS.hub_context or None)
    return config.new_client_from_config(
        config_file=SETTINGS.kubeconfig or None, context=ctx
    )


def hub_custom(_api: client.CustomObjectsApi | None = None) -> client.CustomObjectsApi:
    return _api or client.CustomObjectsApi(api_client())


def spoke_core(cluster: str) -> client.CoreV1Api:
    """Read-only CoreV1 client for a managed cluster, if a context is configured."""
    ctx = SETTINGS.spoke_contexts.get(cluster)
    if not ctx:
        raise LookupError(
            f"No read context configured for cluster '{cluster}'. "
            "Set OCM_MCP_SPOKE_CONTEXTS=name=context,... (see README)."
        )
    return client.CoreV1Api(api_client(ctx))


def spoke_apps(cluster: str) -> client.AppsV1Api:
    ctx = SETTINGS.spoke_contexts.get(cluster)
    if not ctx:
        raise LookupError(
            f"No read context configured for cluster '{cluster}'. "
            "Set OCM_MCP_SPOKE_CONTEXTS=name=context,... (see README)."
        )
    return client.AppsV1Api(api_client(ctx))
