# SPDX-FileCopyrightText: 2026 Sandeep Bazar
# SPDX-License-Identifier: Apache-2.0

"""Configuration for ocm-mcp-server.

State lives under OCM_MCP_HOME (default: ~/.ocm-mcp):
    approval_ed25519      private signing key, used only by the `ocm-mcp` CLI (0600)
    approval_ed25519.pub  public verification key, all the server needs (0644)
    proposals/            pending proposals awaiting approval (dir 0700, files 0600)
    audit.jsonl           append-only audit log of every tool call (0600)
    used_tokens.jsonl     spent approval-token IDs, so a token cannot be replayed

The signer and verifier key paths can be overridden independently
(OCM_MCP_SIGNER_KEY / OCM_MCP_VERIFIER_KEY) so the private signing key can live on
a separate device or account and the server can mount only a read-only verifier.
"""

from __future__ import annotations

import os
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

# Exact (apiVersion, kind) tuples an agent proposal may contain. Checking the kind alone
# lets a manifest spoof the group - e.g. apiVersion: evil.example/v1, kind: Deployment - so
# the guardrails match the full group/version/kind against this set.
ALLOWED_GVK = frozenset(
    {
        ("apps/v1", "Deployment"),
        ("v1", "Service"),
        ("v1", "ConfigMap"),
        ("v1", "ResourceQuota"),
        ("autoscaling/v2", "HorizontalPodAutoscaler"),
        ("autoscaling/v1", "HorizontalPodAutoscaler"),
        ("policy/v1", "PodDisruptionBudget"),
        ("networking.k8s.io/v1", "NetworkPolicy"),
    }
)

# Service accounts a workload may run as. Anything else (e.g. a cluster-admin-bound SA)
# is an escalation path and is rejected. The default SA is allowed only together with
# automountServiceAccountToken: false (enforced in guardrails), so no API token is
# projected into the pod.
ALLOWED_SERVICE_ACCOUNTS = frozenset({"", "default"})

# Volume types a proposed PodSpec may use. This is an allow-list: persistentVolumeClaim,
# csi, hostPath, secret, nfs, and every other type are rejected because they are data- or
# host-access paths that belong behind separate, explicit policy. projected volumes are
# allowed only when they carry no serviceAccountToken or secret source (checked in
# guardrails).
ALLOWED_VOLUME_TYPES = frozenset({"configMap", "emptyDir", "downwardAPI", "projected"})

# Service types a proposed Service may use. NodePort, LoadBalancer, and ExternalName expose
# workloads outside the cluster or resolve to arbitrary external hosts, so they are gated
# out; externalIPs is rejected regardless of type.
ALLOWED_SERVICE_TYPES = frozenset({"", "ClusterIP"})

# Seccomp profile types that satisfy the Restricted Pod Security baseline.
ALLOWED_SECCOMP_TYPES = frozenset({"RuntimeDefault", "Localhost"})

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
        "cluster.open-cluster-management.io",
        "v1beta2",
        "managedclustersets",
        False,
    ),
    "managedclustersetbindings": (
        "cluster.open-cluster-management.io",
        "v1beta2",
        "managedclustersetbindings",
        True,
    ),
    # placement / scheduling
    "placements": ("cluster.open-cluster-management.io", "v1beta1", "placements", True),
    "placementdecisions": (
        "cluster.open-cluster-management.io",
        "v1beta1",
        "placementdecisions",
        True,
    ),
    "addonplacementscores": (
        "cluster.open-cluster-management.io",
        "v1alpha1",
        "addonplacementscores",
        True,
    ),
    # work distribution
    "manifestworks": ("work.open-cluster-management.io", "v1", "manifestworks", True),
    "manifestworkreplicasets": (
        "work.open-cluster-management.io",
        "v1alpha1",
        "manifestworkreplicasets",
        True,
    ),
    # add-ons
    "clustermanagementaddons": (
        "addon.open-cluster-management.io",
        "v1alpha1",
        "clustermanagementaddons",
        False,
    ),
    "managedclusteraddons": (
        "addon.open-cluster-management.io",
        "v1alpha1",
        "managedclusteraddons",
        True,
    ),
    "addondeploymentconfigs": (
        "addon.open-cluster-management.io",
        "v1alpha1",
        "addondeploymentconfigs",
        True,
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
    "managedclusterinfos": (
        "internal.open-cluster-management.io",
        "v1beta1",
        "managedclusterinfos",
        True,
    ),
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
    # Bind every approval token to an issuer and audience so a token minted for one
    # deployment cannot be replayed against another.
    issuer: str = field(default_factory=lambda: os.environ.get("OCM_MCP_ISSUER", "ocm-mcp"))
    audience: str = field(
        default_factory=lambda: os.environ.get("OCM_MCP_AUDIENCE", "ocm-mcp-server")
    )
    # When truthy (OCM_MCP_REQUIRE_DIGEST=1), a proposed image must be pinned by
    # @sha256: digest, not merely a tag - the stricter production posture. Off by
    # default so tag-pinned demos still work.
    require_image_digest: bool = field(
        default_factory=lambda: (
            os.environ.get("OCM_MCP_REQUIRE_DIGEST", "").strip().lower()
            in ("1", "true", "yes", "on")
        )
    )
    # Coarse defense-in-depth backstop, layered UNDER the per-tool approval gate. When
    # set truthy (OCM_MCP_READ_ONLY=1/true/yes), every write tool refuses before it
    # does anything, so a hub operator can run a strictly-inspection deployment.
    read_only: bool = field(
        default_factory=lambda: (
            os.environ.get("OCM_MCP_READ_ONLY", "").strip().lower() in ("1", "true", "yes", "on")
        )
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
        _tighten(d, 0o700)
        return d

    @property
    def audit_log(self) -> Path:
        self.home.mkdir(parents=True, exist_ok=True)
        p = self.home / "audit.jsonl"
        if not p.exists():
            p.touch()
        _tighten(p, 0o600)
        return p

    @property
    def used_tokens_path(self) -> Path:
        """Spent approval-token IDs (jti). A token whose id is here is refused as a replay."""
        self.home.mkdir(parents=True, exist_ok=True)
        return self.home / "used_tokens.jsonl"

    # Approval keys. The signing (private) key is meant for the human side (the ocm-mcp
    # CLI); the MCP server needs only the public verifier. The two paths are independent so
    # the signer can live on a separate device/account and the verifier can be mounted
    # read-only next to the server. Overriding OCM_MCP_SIGNER_KEY off-box is what actually
    # makes the "server cannot mint" property hold; co-located, it is a convention.
    @property
    def approval_private_key_path(self) -> Path:
        override = os.environ.get("OCM_MCP_SIGNER_KEY", "").strip()
        return Path(override).expanduser() if override else self.home / "approval_ed25519"

    @property
    def approval_public_key_path(self) -> Path:
        override = os.environ.get("OCM_MCP_VERIFIER_KEY", "").strip()
        return Path(override).expanduser() if override else self.home / "approval_ed25519.pub"

    @property
    def previous_public_key_path(self) -> Path:
        """An optional retired verifier key, honored during a *planned* rotation so tokens
        signed just before the roll still verify until they expire. For a planned rotation,
        stage the old public key here and generate a new keypair; for an *exposure*, use
        rotate_approval_key() below, which drops this too."""
        return self.approval_public_key_path.with_suffix(".pub.prev")

    def rotate_approval_key(self) -> None:
        """Hard-invalidate every approval token (use if a key may have been exposed).

        Removes the private signer, the current verifier, and any staged previous verifier,
        so nothing minted before rotation can verify. A fresh keypair is generated on the
        next mint, and every pending proposal must be approved again.
        """
        for p in (
            self.approval_private_key_path,
            self.approval_public_key_path,
            self.previous_public_key_path,
        ):
            p.unlink(missing_ok=True)


def _tighten(path: Path, mode: int) -> None:
    """Best-effort chmod; never fail a request because a filesystem rejects chmod."""
    try:
        path.chmod(mode)
    except OSError:
        pass


SETTINGS = Settings()
