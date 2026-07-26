# SPDX-FileCopyrightText: 2026 Sandeep Bazar
# SPDX-License-Identifier: Apache-2.0

"""Static guardrails - defense in depth, evaluated before Kyverno ever sees a proposal.

Layer model (a proposal must pass ALL of these, in order):
    1. Static checks here (fast, local, no cluster required)
    2. Kyverno dry-run admission on the hub (deploy/policies/)
    3. Human approval token (approvals.py)
    4. Least-privilege RBAC on the actual apply (deploy/rbac.yaml)

These enforce a Restricted-Pod-Security baseline on every embedded workload: an exact
apiVersion/kind allow-list, no host access, no arbitrary service account, no projected
API token, an allow-list of volume and Service types, and a required non-root, no-
privilege-escalation, all-capabilities-dropped, seccomp-confined security context. Inputs
are schema-checked first, so a malformed manifest is a clean violation, never a crash.

Prompts are wishes; these are guarantees.
"""

from __future__ import annotations

from typing import Any

from .config import (
    ALLOWED_GVK,
    ALLOWED_SECCOMP_TYPES,
    ALLOWED_SERVICE_ACCOUNTS,
    ALLOWED_SERVICE_TYPES,
    ALLOWED_VOLUME_TYPES,
    PROTECTED_NAMESPACES,
    SETTINGS,
)


class GuardrailViolation(Exception):
    """A proposal failed a static guardrail. The message is agent-readable."""


def _as_dict(value: Any) -> dict[str, Any]:
    """Return value if it is a dict, else an empty dict - so a malformed manifest
    (a string, a list, a null where an object is expected) produces a violation
    downstream instead of an AttributeError."""
    return value if isinstance(value, dict) else {}


def _pod_spec(manifest: dict[str, Any]) -> dict[str, Any]:
    """Locate the PodSpec regardless of the enclosing workload kind.

    Pod embeds it directly; CronJob nests it under jobTemplate; every other workload
    (Deployment, StatefulSet, DaemonSet, ReplicaSet, Job) uses spec.template.spec.
    """
    spec = _as_dict(manifest.get("spec"))
    kind = manifest.get("kind")
    if kind == "Pod":
        return spec
    if kind == "CronJob":
        job = _as_dict(_as_dict(spec.get("jobTemplate")).get("spec"))
        return _as_dict(_as_dict(job.get("template")).get("spec"))
    return _as_dict(_as_dict(spec.get("template")).get("spec"))


def _has_pod_spec(manifest: dict[str, Any]) -> bool:
    """Only workload kinds carry a PodSpec; Service/ConfigMap/etc. must not be
    subjected to container checks (and an empty PodSpec must not read as 'clean')."""
    return manifest.get("kind") in {
        "Pod",
        "CronJob",
        "Deployment",
        "StatefulSet",
        "DaemonSet",
        "ReplicaSet",
        "Job",
    }


def _containers(manifest: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Every container that runs, tagged by role: regular, init, and ephemeral.
    Ephemeral containers are a real exec-into-pod path and must be checked too."""
    pod_spec = _pod_spec(manifest)
    out: list[tuple[str, dict[str, Any]]] = []
    for role, key in (
        ("container", "containers"),
        ("initContainer", "initContainers"),
        ("ephemeralContainer", "ephemeralContainers"),
    ):
        for c in pod_spec.get(key, []) or []:
            out.append((role, _as_dict(c)))
    return out


def _env_uses_secret(ctr: dict[str, Any]) -> bool:
    for e in ctr.get("env", []) or []:
        if isinstance(e, dict) and _as_dict(e.get("valueFrom")).get("secretKeyRef"):
            return True
    for src in ctr.get("envFrom", []) or []:
        if isinstance(src, dict) and src.get("secretRef"):
            return True
    return False


def _image_pinned(image: str) -> bool:
    """Reject :latest and floating (untagged) images. In strict mode
    (OCM_MCP_REQUIRE_DIGEST) require a @sha256: digest, not merely a tag."""
    if not image or image.endswith(":latest"):
        return False
    has_digest = "@sha256:" in image
    if SETTINGS.require_image_digest:
        return has_digest
    last = image.split("/")[-1]
    return has_digest or ":" in last


def _check_schema(manifest: Any, idx: int) -> list[str]:
    """Structural checks that must pass before any field access. Returns violations."""
    if not isinstance(manifest, dict):
        return [f"manifest {idx} is not a JSON object (got {type(manifest).__name__})."]
    problems = []
    if not isinstance(manifest.get("apiVersion", ""), str):
        problems.append(f"manifest {idx}: apiVersion must be a string.")
    if not isinstance(manifest.get("kind", ""), str):
        problems.append(f"manifest {idx}: kind must be a string.")
    if "metadata" in manifest and not isinstance(manifest["metadata"], dict):
        problems.append(f"manifest {idx}: metadata must be an object.")
    return problems


def _check_pod_security(manifest: dict[str, Any]) -> list[str]:
    """Restricted-Pod-Security checks for a workload's PodSpec and every container."""
    violations: list[str] = []
    pod_spec = _pod_spec(manifest)

    if pod_spec.get("hostNetwork"):
        violations.append("hostNetwork is not allowed.")
    if pod_spec.get("hostPID") or pod_spec.get("hostIPC"):
        violations.append("hostPID/hostIPC are not allowed.")
    if pod_spec.get("automountServiceAccountToken") is not False:
        violations.append(
            "automountServiceAccountToken must be explicitly false - an auto-mounted "
            "API token is a credential the workload does not need."
        )
    sa = pod_spec.get("serviceAccountName", pod_spec.get("serviceAccount", ""))
    if sa and sa not in ALLOWED_SERVICE_ACCOUNTS:
        violations.append(
            f"serviceAccountName '{sa}' is not allowed - running as an arbitrary service "
            "account is an escalation path."
        )

    pod_sc = _as_dict(pod_spec.get("securityContext"))
    pod_nonroot = pod_sc.get("runAsNonRoot") is True
    pod_seccomp = _as_dict(pod_sc.get("seccompProfile")).get("type")

    for vol in pod_spec.get("volumes", []) or []:
        vol = _as_dict(vol)
        name = vol.get("name", "?")
        vtypes = [k for k in vol if k != "name"]
        for vt in vtypes:
            if vt not in ALLOWED_VOLUME_TYPES:
                violations.append(
                    f"volume '{name}' of type '{vt}' is not allowed (allowed: "
                    f"{', '.join(sorted(ALLOWED_VOLUME_TYPES))})."
                )
        sources = _as_dict(vol.get("projected")).get("sources", []) or []
        if any("serviceAccountToken" in _as_dict(s) or "secret" in _as_dict(s) for s in sources):
            violations.append(
                f"projected volume '{name}' mounting a serviceAccountToken or secret is not allowed."
            )

    for role, ctr in _containers(manifest):
        name = ctr.get("name", "?")
        sc = _as_dict(ctr.get("securityContext"))
        if sc.get("privileged"):
            violations.append(f"{role} '{name}': privileged=true is not allowed.")
        if sc.get("allowPrivilegeEscalation") is not False:
            violations.append(
                f"{role} '{name}': allowPrivilegeEscalation must be explicitly false."
            )
        if not (sc.get("runAsNonRoot") is True or pod_nonroot):
            violations.append(f"{role} '{name}': runAsNonRoot must be true (pod or container).")
        run_as_user = sc.get("runAsUser", pod_sc.get("runAsUser"))
        if run_as_user == 0:
            violations.append(f"{role} '{name}': runAsUser 0 (root) is not allowed.")
        drop = [str(c).upper() for c in _as_dict(sc.get("capabilities")).get("drop", []) or []]
        if "ALL" not in drop:
            violations.append(f"{role} '{name}': capabilities.drop must include ALL.")
        add = _as_dict(sc.get("capabilities")).get("add", []) or []
        if add:
            violations.append(f"{role} '{name}': adding capabilities {add} is not allowed.")
        seccomp = _as_dict(sc.get("seccompProfile")).get("type") or pod_seccomp
        if seccomp not in ALLOWED_SECCOMP_TYPES:
            violations.append(
                f"{role} '{name}': seccompProfile.type must be one of "
                f"{', '.join(sorted(ALLOWED_SECCOMP_TYPES))} (pod or container)."
            )
        if _env_uses_secret(ctr):
            violations.append(
                f"{role} '{name}': reading a Secret via env secretKeyRef/secretRef is not "
                "allowed (there is no path to Secret contents)."
            )
        if not _image_pinned(ctr.get("image", "")):
            digest = " by @sha256: digest" if SETTINGS.require_image_digest else ""
            violations.append(
                f"{role} '{name}': image '{ctr.get('image', '')}' must be pinned{digest} "
                "(no :latest, no floating tags)."
            )
    return violations


def _check_service(manifest: dict[str, Any]) -> list[str]:
    spec = _as_dict(manifest.get("spec"))
    violations = []
    stype = spec.get("type", "")
    if stype not in ALLOWED_SERVICE_TYPES:
        violations.append(
            f"Service type '{stype}' is not allowed (allowed: ClusterIP) - NodePort, "
            "LoadBalancer, and ExternalName expose the workload outside the cluster."
        )
    if spec.get("externalIPs"):
        violations.append("Service.spec.externalIPs is not allowed.")
    return violations


def check_manifest(manifest: dict[str, Any]) -> list[str]:
    """Return a list of violation strings for a single (already schema-valid) manifest."""
    violations: list[str] = []
    api_version = manifest.get("apiVersion", "")
    kind = manifest.get("kind", "")
    metadata = _as_dict(manifest.get("metadata"))
    namespace = metadata.get("namespace", "")

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
            f"{kind}/{metadata.get('name', '?')}: metadata.namespace is required - "
            "cluster-scoped or default-namespace writes are not allowed."
        )
    elif namespace in PROTECTED_NAMESPACES:
        violations.append(
            f"namespace '{namespace}' is protected - agent writes to system namespaces are "
            "never allowed."
        )

    if _has_pod_spec(manifest):
        violations += _check_pod_security(manifest)
    if kind == "Service":
        violations += _check_service(manifest)
    return violations


def validate_manifests(manifests: list[dict[str, Any]]) -> None:
    """Raise GuardrailViolation with every problem found across all manifests."""
    if not isinstance(manifests, list) or not manifests:
        raise GuardrailViolation("Proposal contains no manifests (expected a JSON array).")
    if len(manifests) > 10:
        raise GuardrailViolation(
            f"Proposal contains {len(manifests)} manifests; the per-proposal limit is 10. "
            "Split large changes into reviewable pieces."
        )
    all_violations: list[str] = []
    for i, manifest in enumerate(manifests):
        schema_problems = _check_schema(manifest, i)
        if schema_problems:
            all_violations += [f"[manifest {i}] {p}" for p in schema_problems]
            continue  # field-level checks are unsafe on a malformed manifest
        for v in check_manifest(manifest):
            all_violations.append(f"[manifest {i}] {v}")
    if all_violations:
        raise GuardrailViolation(
            "Static guardrails rejected this proposal:\n- " + "\n- ".join(all_violations)
        )
