# SPDX-FileCopyrightText: 2026 Sandeep Bazar
# SPDX-License-Identifier: Apache-2.0

"""Static guardrails - defense in depth, evaluated before Kyverno ever sees a proposal.

Layer model (a proposal must pass ALL of these, in order):
    1. Static checks here (fast, local, no cluster required)
    2. Kyverno dry-run admission on the hub (deploy/policies/)
    3. Human approval token (approvals.py)
    4. Least-privilege RBAC on the actual apply (deploy/rbac.yaml)

Prompts are wishes; these are guarantees.
"""

from __future__ import annotations

from typing import Any

from .config import ALLOWED_GVK, ALLOWED_SERVICE_ACCOUNTS, PROTECTED_NAMESPACES


class GuardrailViolation(Exception):
    """A proposal failed a static guardrail. The message is agent-readable."""


def _pod_spec(manifest: dict[str, Any]) -> dict[str, Any]:
    """Locate the PodSpec regardless of the enclosing workload kind.

    Pod embeds it directly; CronJob nests it under jobTemplate; every other workload
    (Deployment, StatefulSet, DaemonSet, ReplicaSet, Job) uses spec.template.spec. This
    keeps the security checks correct if ALLOWED_KINDS grows beyond Deployment.
    """
    spec = manifest.get("spec", {})
    kind = manifest.get("kind")
    if kind == "Pod":
        return spec
    if kind == "CronJob":
        return spec.get("jobTemplate", {}).get("spec", {}).get("template", {}).get("spec", {})
    return spec.get("template", {}).get("spec", {})


def _containers(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    pod_spec = _pod_spec(manifest)
    return list(pod_spec.get("containers", [])) + list(pod_spec.get("initContainers", []))


def _env_uses_secret(ctr: dict[str, Any]) -> bool:
    for e in ctr.get("env", []) or []:
        if isinstance(e, dict) and (e.get("valueFrom", {}) or {}).get("secretKeyRef"):
            return True
    for src in ctr.get("envFrom", []) or []:
        if isinstance(src, dict) and src.get("secretRef"):
            return True
    return False


def check_manifest(manifest: dict[str, Any]) -> list[str]:
    """Return a list of violation strings for a single manifest (empty = clean)."""
    violations: list[str] = []
    api_version = manifest.get("apiVersion", "")
    kind = manifest.get("kind", "")
    namespace = manifest.get("metadata", {}).get("namespace", "")

    # Match the FULL group/version/kind, not just the kind, so a manifest cannot spoof
    # the group (e.g. apiVersion: evil.example/v1, kind: Deployment).
    if (api_version, kind) not in ALLOWED_GVK:
        allowed = ", ".join(f"{a}/{k}" for a, k in sorted(ALLOWED_GVK))
        violations.append(
            f"'{api_version or '(missing)'}, {kind or '(missing)'}' is not an allowed "
            f"apiVersion/kind. Allowed: {allowed}."
        )
    if not namespace:
        violations.append(
            f"{kind}/{manifest.get('metadata', {}).get('name', '?')}: metadata.namespace is "
            "required - cluster-scoped or default-namespace writes are not allowed."
        )
    elif namespace in PROTECTED_NAMESPACES:
        violations.append(
            f"namespace '{namespace}' is protected - agent writes to system namespaces are "
            "never allowed."
        )

    pod_spec = _pod_spec(manifest)
    if pod_spec.get("hostNetwork"):
        violations.append("hostNetwork is not allowed.")
    if pod_spec.get("hostPID") or pod_spec.get("hostIPC"):
        violations.append("hostPID/hostIPC are not allowed.")
    sa = pod_spec.get("serviceAccountName", pod_spec.get("serviceAccount", ""))
    if sa and sa not in ALLOWED_SERVICE_ACCOUNTS:
        violations.append(
            f"serviceAccountName '{sa}' is not allowed - running as an arbitrary service "
            "account is an escalation path. Use the default service account."
        )
    for vol in pod_spec.get("volumes", []) or []:
        name = vol.get("name", "?")
        if "hostPath" in vol:
            violations.append(f"hostPath volume '{name}' is not allowed.")
        if "secret" in vol:
            violations.append(f"secret volume '{name}' is not allowed (no indirect Secret access).")
        projected = (vol.get("projected", {}) or {}).get("sources", []) or []
        if any("serviceAccountToken" in (s or {}) or "secret" in (s or {}) for s in projected):
            violations.append(
                f"projected volume '{name}' mounting a serviceAccountToken or secret is not allowed."
            )

    for ctr in _containers(manifest):
        sc = ctr.get("securityContext", {}) or {}
        name = ctr.get("name", "?")
        if sc.get("privileged"):
            violations.append(f"container '{name}': privileged=true is not allowed.")
        if sc.get("allowPrivilegeEscalation"):
            violations.append(f"container '{name}': allowPrivilegeEscalation is not allowed.")
        caps = (sc.get("capabilities", {}) or {}).get("add", []) or []
        if caps:
            violations.append(f"container '{name}': adding capabilities {caps} is not allowed.")
        if _env_uses_secret(ctr):
            violations.append(
                f"container '{name}': reading a Secret via env secretKeyRef/secretRef is not "
                "allowed (there is no path to Secret contents)."
            )
        image = ctr.get("image", "")
        if image.endswith(":latest") or (":" not in image.split("/")[-1] and "@" not in image):
            violations.append(
                f"container '{name}': image '{image}' must be pinned to an explicit tag "
                "or digest (no :latest, no floating tags)."
            )
    return violations


def validate_manifests(manifests: list[dict[str, Any]]) -> None:
    """Raise GuardrailViolation with every problem found across all manifests."""
    if not manifests:
        raise GuardrailViolation("Proposal contains no manifests.")
    if len(manifests) > 10:
        raise GuardrailViolation(
            f"Proposal contains {len(manifests)} manifests; the per-proposal limit is 10. "
            "Split large changes into reviewable pieces."
        )
    all_violations: list[str] = []
    for i, manifest in enumerate(manifests):
        for v in check_manifest(manifest):
            all_violations.append(f"[manifest {i}] {v}")
    if all_violations:
        raise GuardrailViolation(
            "Static guardrails rejected this proposal:\n- " + "\n- ".join(all_violations)
        )
