# SPDX-FileCopyrightText: 2026 Sandeep Bazar
# SPDX-License-Identifier: Apache-2.0

"""Property-based tests for the static guardrails.

Example-based tests prove the guardrails catch the attacks someone thought of;
these prove structural invariants over inputs nobody thought of:

1. TOTALITY - for ANY input shape, validate_manifests either passes or raises
   GuardrailViolation. It never crashes with anything else (the schema-check-
   first claim in guardrails.py).
2. NO SECRET PATH - a workload reading a Secret via env is rejected no matter
   where in the pod the reference hides.
3. NO PRIVILEGE - privileged containers are rejected in every container role.
4. NAMESPACE FENCE - protected namespaces and their prefixes always reject.
5. GVK FENCE - any (apiVersion, kind) outside the exact allow-list rejects.
6. BOUNDS - more than 10 manifests always rejects, regardless of content.
"""

from __future__ import annotations

import copy
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from ocm_mcp_server.config import ALLOWED_GVK, PROTECTED_NAMESPACES
from ocm_mcp_server.guardrails import GuardrailViolation, validate_manifests

# Arbitrary JSON-shaped data, small enough to keep the suite fast.
_scalar = st.none() | st.booleans() | st.integers(-5, 5) | st.text(max_size=12)
_json = st.recursive(
    _scalar,
    lambda kids: (
        st.lists(kids, max_size=3) | st.dictionaries(st.text(max_size=8), kids, max_size=4)
    ),
    max_leaves=12,
)


def _compliant_deployment() -> dict[str, Any]:
    """A deployment that passes every static guardrail (mirrors the policy fixtures)."""
    return {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": "app", "namespace": "shop"},
        "spec": {
            "replicas": 1,
            "selector": {"matchLabels": {"app": "app"}},
            "template": {
                "metadata": {"labels": {"app": "app"}},
                "spec": {
                    "automountServiceAccountToken": False,
                    "containers": [
                        {
                            "name": "app",
                            "image": "registry.example.com/app:1.0.0",
                            "securityContext": {
                                "runAsNonRoot": True,
                                "allowPrivilegeEscalation": False,
                                "seccompProfile": {"type": "RuntimeDefault"},
                                "capabilities": {"drop": ["ALL"]},
                            },
                        }
                    ],
                },
            },
        },
    }


def _rejected(manifests: list[Any]) -> bool:
    try:
        validate_manifests(manifests)
        return False
    except GuardrailViolation:
        return True


@settings(max_examples=200, deadline=None)
@given(st.lists(_json, min_size=1, max_size=3))
def test_totality_any_input_passes_or_raises_guardrail_violation(manifests: list[Any]) -> None:
    """No input shape may crash the guardrails - only pass or a clean violation."""
    try:
        validate_manifests(manifests)
    except GuardrailViolation:
        pass  # a clean, agent-readable rejection is a valid outcome


@settings(max_examples=100, deadline=None)
@given(role=st.sampled_from(["containers", "initContainers"]), via_env_from=st.booleans())
def test_secret_env_refs_always_rejected(role: str, via_env_from: bool) -> None:
    manifest = _compliant_deployment()
    ctr = copy.deepcopy(manifest["spec"]["template"]["spec"]["containers"][0])
    if via_env_from:
        ctr["envFrom"] = [{"secretRef": {"name": "creds"}}]
    else:
        ctr["env"] = [{"name": "PW", "valueFrom": {"secretKeyRef": {"name": "creds", "key": "p"}}}]
    manifest["spec"]["template"]["spec"][role] = [ctr]
    assert _rejected([manifest])


@settings(max_examples=100, deadline=None)
@given(role=st.sampled_from(["containers", "initContainers", "ephemeralContainers"]))
def test_privileged_always_rejected(role: str) -> None:
    manifest = _compliant_deployment()
    ctr = copy.deepcopy(manifest["spec"]["template"]["spec"]["containers"][0])
    ctr["securityContext"]["privileged"] = True
    manifest["spec"]["template"]["spec"][role] = [ctr]
    assert _rejected([manifest])


@settings(max_examples=100, deadline=None)
@given(
    namespace=st.sampled_from(sorted(PROTECTED_NAMESPACES))
    | st.sampled_from(["kube-", "openshift-", "open-cluster-management"]).flatmap(
        lambda p: st.text(min_size=0, max_size=8).map(lambda s: p + s)
    )
)
def test_protected_namespaces_always_rejected(namespace: str) -> None:
    manifest = _compliant_deployment()
    manifest["metadata"]["namespace"] = namespace
    assert _rejected([manifest])


@settings(max_examples=150, deadline=None)
@given(api_version=st.text(max_size=20), kind=st.text(max_size=20))
def test_gvk_outside_allowlist_always_rejected(api_version: str, kind: str) -> None:
    if (api_version, kind) in ALLOWED_GVK:
        return  # the allow-listed pairs are exactly the ones permitted
    manifest = _compliant_deployment()
    manifest["apiVersion"] = api_version
    manifest["kind"] = kind
    assert _rejected([manifest])


@settings(max_examples=25, deadline=None)
@given(count=st.integers(min_value=11, max_value=30))
def test_manifest_count_over_ten_always_rejected(count: int) -> None:
    cm = {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {"name": "cm", "namespace": "shop"},
        "data": {"k": "v"},
    }
    assert _rejected([copy.deepcopy(cm) for _ in range(count)])
