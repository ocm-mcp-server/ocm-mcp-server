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

from .config import ALLOWED_KINDS, PROTECTED_NAMESPACES


class GuardrailViolation(Exception):
    """A proposal failed a static guardrail. The message is agent-readable."""


def _containers(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    spec = manifest.get("spec", {})
    pod_spec = spec.get("template", {}).get("spec", spec if manifest.get("kind") == "Pod" else {})
    return list(pod_spec.get("containers", [])) + list(pod_spec.get("initContainers", []))


def _pod_spec(manifest: dict[str, Any]) -> dict[str, Any]:
    spec = manifest.get("spec", {})
    if manifest.get("kind") == "Pod":
        return spec
    return spec.get("template", {}).get("spec", {})


def check_manifest(manifest: dict[str, Any]) -> list[str]:
    """Return a list of violation strings for a single manifest (empty = clean)."""
    violations: list[str] = []
    kind = manifest.get("kind", "")
    namespace = manifest.get("metadata", {}).get("namespace", "")

    if kind not in ALLOWED_KINDS:
        violations.append(
            f"kind '{kind or '(missing)'}' is not in the allowed set "
            f"{sorted(ALLOWED_KINDS)} - agents may not manage this resource type."
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
    for vol in pod_spec.get("volumes", []) or []:
        if "hostPath" in vol:
            violations.append(f"hostPath volume '{vol.get('name', '?')}' is not allowed.")

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
        image = ctr.get("image", "")
        if image.endswith(":latest") or (":" not in image.split("/")[-1]):
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
