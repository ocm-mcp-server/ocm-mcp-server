# SPDX-FileCopyrightText: 2026 Sandeep Bazar
# SPDX-License-Identifier: Apache-2.0

import pytest

from ocm_mcp_server import guardrails
from ocm_mcp_server.guardrails import GuardrailViolation


def deployment(**overrides):
    base = {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": "payments", "namespace": "shop"},
        "spec": {
            "replicas": 2,
            "template": {
                "spec": {
                    "containers": [
                        {"name": "payments", "image": "registry.example.com/payments:1.9.2"}
                    ]
                }
            },
        },
    }
    base.update(overrides)
    return base


def test_clean_deployment_passes():
    guardrails.validate_manifests([deployment()])


def test_empty_proposal_rejected():
    with pytest.raises(GuardrailViolation, match="no manifests"):
        guardrails.validate_manifests([])


def test_too_many_manifests_rejected():
    with pytest.raises(GuardrailViolation, match="limit is 10"):
        guardrails.validate_manifests([deployment() for _ in range(11)])


def test_disallowed_kind():
    bad = deployment(kind="ClusterRoleBinding")
    with pytest.raises(GuardrailViolation, match="not in the allowed set"):
        guardrails.validate_manifests([bad])


def test_missing_namespace():
    bad = deployment(metadata={"name": "payments"})
    with pytest.raises(GuardrailViolation, match="namespace is required"):
        guardrails.validate_manifests([bad])


def test_protected_namespace():
    bad = deployment(metadata={"name": "payments", "namespace": "kube-system"})
    with pytest.raises(GuardrailViolation, match="protected"):
        guardrails.validate_manifests([bad])


@pytest.mark.parametrize(
    "sc_key,sc_value,expected",
    [
        ("privileged", True, "privileged"),
        ("allowPrivilegeEscalation", True, "allowPrivilegeEscalation"),
    ],
)
def test_privileged_security_context(sc_key, sc_value, expected):
    bad = deployment()
    bad["spec"]["template"]["spec"]["containers"][0]["securityContext"] = {sc_key: sc_value}
    with pytest.raises(GuardrailViolation, match=expected):
        guardrails.validate_manifests([bad])


def test_added_capabilities():
    bad = deployment()
    bad["spec"]["template"]["spec"]["containers"][0]["securityContext"] = {
        "capabilities": {"add": ["NET_ADMIN"]}
    }
    with pytest.raises(GuardrailViolation, match="NET_ADMIN"):
        guardrails.validate_manifests([bad])


def test_host_network():
    bad = deployment()
    bad["spec"]["template"]["spec"]["hostNetwork"] = True
    with pytest.raises(GuardrailViolation, match="hostNetwork"):
        guardrails.validate_manifests([bad])


def test_hostpath_volume():
    bad = deployment()
    bad["spec"]["template"]["spec"]["volumes"] = [
        {"name": "logs", "hostPath": {"path": "/var/log"}}
    ]
    with pytest.raises(GuardrailViolation, match="hostPath"):
        guardrails.validate_manifests([bad])


@pytest.mark.parametrize(
    "image",
    ["payments:latest", "payments", "registry.example.com/team/payments"],
)
def test_unpinned_images(image):
    bad = deployment()
    bad["spec"]["template"]["spec"]["containers"][0]["image"] = image
    with pytest.raises(GuardrailViolation, match="pinned"):
        guardrails.validate_manifests([bad])


def test_digest_pinned_image_passes():
    good = deployment()
    good["spec"]["template"]["spec"]["containers"][0]["image"] = (
        "registry.example.com/payments@sha256:" + "a" * 64
    )
    guardrails.validate_manifests([good])


def test_init_containers_checked():
    bad = deployment()
    bad["spec"]["template"]["spec"]["initContainers"] = [
        {"name": "init", "image": "busybox:1.36", "securityContext": {"privileged": True}}
    ]
    with pytest.raises(GuardrailViolation, match="privileged"):
        guardrails.validate_manifests([bad])


def test_all_violations_reported_together():
    bad = deployment(metadata={"name": "p", "namespace": "kube-system"})
    bad["spec"]["template"]["spec"]["hostNetwork"] = True
    with pytest.raises(GuardrailViolation) as excinfo:
        guardrails.validate_manifests([bad])
    message = str(excinfo.value)
    assert "protected" in message and "hostNetwork" in message
