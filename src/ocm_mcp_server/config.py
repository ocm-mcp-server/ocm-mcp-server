# SPDX-FileCopyrightText: 2026 Sandeep Bazar
# SPDX-License-Identifier: Apache-2.0

"""Configuration for ocm-mcp-server.

All state lives under OCM_MCP_HOME (default: ~/.ocm-mcp):
    secret            HMAC key for approval tokens (created on first use, 0600)
    proposals/        pending ManifestWork proposals awaiting approval
    audit.jsonl       append-only audit log of every tool call
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

PROTECTED_NAMESPACES = frozenset(
    {
        "kube-system",
        "kube-public",
        "kube-node-lease",
        "open-cluster-management",
        "open-cluster-management-hub",
        "open-cluster-management-agent",
        "open-cluster-management-agent-addon",
        "kyverno",
    }
)

# Kinds an agent proposal may contain. Everything else is rejected before the
# proposal is even stored. Deliberately small; grow it consciously.
ALLOWED_KINDS = frozenset(
    {
        "Deployment",
        "Service",
        "ConfigMap",
        "HorizontalPodAutoscaler",
        "PodDisruptionBudget",
        "ResourceQuota",
        "NetworkPolicy",
    }
)


@dataclass
class Settings:
    home: Path = field(
        default_factory=lambda: Path(os.environ.get("OCM_MCP_HOME", "~/.ocm-mcp")).expanduser()
    )
    hub_context: str = field(default_factory=lambda: os.environ.get("OCM_MCP_HUB_CONTEXT", ""))
    kubeconfig: str = field(default_factory=lambda: os.environ.get("KUBECONFIG", ""))
    # cluster-name -> kubeconfig context for read-only spoke access.
    # Format: "cluster1=kind-cluster1,cluster2=kind-cluster2"
    spoke_contexts: dict[str, str] = field(default_factory=dict)
    otel_endpoint: str = field(
        default_factory=lambda: os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    )
    approval_ttl_seconds: int = int(os.environ.get("OCM_MCP_APPROVAL_TTL", "3600"))

    def __post_init__(self) -> None:
        raw = os.environ.get("OCM_MCP_SPOKE_CONTEXTS", "")
        if raw and not self.spoke_contexts:
            for pair in raw.split(","):
                if "=" in pair:
                    name, ctx = pair.split("=", 1)
                    self.spoke_contexts[name.strip()] = ctx.strip()

    @property
    def proposals_dir(self) -> Path:
        d = self.home / "proposals"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def audit_log(self) -> Path:
        self.home.mkdir(parents=True, exist_ok=True)
        return self.home / "audit.jsonl"

    def secret(self) -> bytes:
        """HMAC key for approval tokens; generated once, stored 0600."""
        path = self.home / "secret"
        if not path.exists():
            self.home.mkdir(parents=True, exist_ok=True)
            path.write_text(secrets.token_hex(32))
            path.chmod(0o600)
        return path.read_text().strip().encode()


SETTINGS = Settings()
