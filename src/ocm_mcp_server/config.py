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

# The generic reader (list_resources / get_resource) works only against this
# allow-list of Open Cluster Management API types. This is an allow-list, not a
# deny-list, on purpose: Secrets, ConfigMaps with credentials, and every other
# core or third-party kind are simply not expressible through the generic reader,
# so no prompt can coax it into reading them. Each entry is
#   friendly-name -> (group, version, plural, namespaced)
# "namespaced" resources on an OCM hub usually live in the cluster namespace (a
# hub namespace named after each ManagedCluster) or a user namespace.
READABLE_RESOURCES: dict[str, tuple[str, str, str, bool]] = {
    # inventory
    "managedclusters": ("cluster.open-cluster-management.io", "v1", "managedclusters", False),
    "managedclustersets": (
        "cluster.open-cluster-management.io", "v1beta2", "managedclustersets", False,
    ),
    "managedclustersetbindings": (
        "cluster.open-cluster-management.io", "v1beta2", "managedclustersetbindings", True,
    ),
    # placement / scheduling
    "placements": ("cluster.open-cluster-management.io", "v1beta1", "placements", True),
    "placementdecisions": (
        "cluster.open-cluster-management.io", "v1beta1", "placementdecisions", True,
    ),
    "addonplacementscores": (
        "cluster.open-cluster-management.io", "v1alpha1", "addonplacementscores", True,
    ),
    # work distribution
    "manifestworks": ("work.open-cluster-management.io", "v1", "manifestworks", True),
    "manifestworkreplicasets": (
        "work.open-cluster-management.io", "v1alpha1", "manifestworkreplicasets", True,
    ),
    # add-ons
    "clustermanagementaddons": (
        "addon.open-cluster-management.io", "v1alpha1", "clustermanagementaddons", False,
    ),
    "managedclusteraddons": (
        "addon.open-cluster-management.io", "v1alpha1", "managedclusteraddons", True,
    ),
    "addondeploymentconfigs": (
        "addon.open-cluster-management.io", "v1alpha1", "addondeploymentconfigs", True,
    ),
    "addontemplates": ("addon.open-cluster-management.io", "v1alpha1", "addontemplates", False),
    # operator / control plane (read to confirm features and health)
    "clustermanagers": ("operator.open-cluster-management.io", "v1", "clustermanagers", False),
    "klusterlets": ("operator.open-cluster-management.io", "v1", "klusterlets", False),
    # governance policy add-on (present only if installed; feature-detected at call time)
    "policies": ("policy.open-cluster-management.io", "v1", "policies", True),
    "policysets": ("policy.open-cluster-management.io", "v1beta1", "policysets", True),
    "placementbindings": ("policy.open-cluster-management.io", "v1", "placementbindings", True),
    # ACM extended inventory (multicloud-operators-foundation / cluster-lifecycle-api)
    "managedclusterinfos": ("internal.open-cluster-management.io", "v1beta1", "managedclusterinfos", True),
    # HyperShift Hosted Control Planes, when the fleet runs HCP spokes
    "hostedclusters": ("hypershift.openshift.io", "v1beta1", "hostedclusters", True),
    "nodepools": ("hypershift.openshift.io", "v1beta1", "nodepools", True),
}

# OCM-native lifecycle actions an agent may PROPOSE. Each still routes through the
# same propose -> human approval token -> apply gate as a ManifestWork; none is
# ever applied inline. Everything not listed here cannot be proposed at all.
ALLOWED_CLUSTER_ACTIONS = frozenset(
    {"cordon", "uncordon", "set_label", "accept", "enable_addon", "disable_addon"}
)

# The NoSelect taint the cordon/uncordon actions add to or remove from a
# ManagedCluster to pull it out of (or back into) Placement scheduling.
CORDON_TAINT_KEY = "ocm-mcp-server.io/cordoned"


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
    # Coarse defense-in-depth backstop, layered UNDER the per-tool HMAC gate. When
    # set truthy (OCM_MCP_READ_ONLY=1/true/yes), every write tool refuses before it
    # does anything, so a hub operator can run a strictly-inspection deployment.
    read_only: bool = field(
        default_factory=lambda: os.environ.get("OCM_MCP_READ_ONLY", "").strip().lower()
        in ("1", "true", "yes", "on")
    )

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
