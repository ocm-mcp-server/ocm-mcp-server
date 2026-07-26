# SPDX-FileCopyrightText: 2026 Sandeep Bazar
# SPDX-License-Identifier: Apache-2.0

import pytest

from ocm_mcp_server import guardrails
from ocm_mcp_server.config import SETTINGS
from ocm_mcp_server.guardrails import GuardrailViolation


def restricted_sc():
    """A security context that satisfies the Restricted Pod Security baseline."""
    return {
        "runAsNonRoot": True,
        "allowPrivilegeEscalation": False,
        "seccompProfile": {"type": "RuntimeDefault"},
        "capabilities": {"drop": ["ALL"]},
    }


def container(name="payments", image="registry.example.com/payments:1.9.2", **extra):
    c = {"name": name, "image": image, "securityContext": restricted_sc()}
    c.update(extra)
    return c


def deployment(**overrides):
    base = {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": "payments", "namespace": "shop"},
        "spec": {
            "replicas": 2,
            "template": {
                "spec": {
                    "automountServiceAccountToken": False,
                    "containers": [container()],
                }
            },
        },
    }
    base.update(overrides)
    return base


def pod_spec(dep):
    return dep["spec"]["template"]["spec"]


# --------------------------------------------------------------------- happy path


def test_clean_deployment_passes():
    guardrails.validate_manifests([deployment()])


def test_clean_configmap_passes():
    guardrails.validate_manifests(
        [
            {
                "apiVersion": "v1",
                "kind": "ConfigMap",
                "metadata": {"name": "cfg", "namespace": "shop"},
                "data": {"a": "b"},
            }
        ]
    )


def test_digest_pinned_image_passes():
    good = deployment()
    pod_spec(good)["containers"][0]["image"] = "registry.example.com/payments@sha256:" + "a" * 64
    guardrails.validate_manifests([good])


# --------------------------------------------------------------------- structural


def test_empty_proposal_rejected():
    with pytest.raises(GuardrailViolation, match="no manifests"):
        guardrails.validate_manifests([])


def test_too_many_manifests_rejected():
    with pytest.raises(GuardrailViolation, match="limit is 10"):
        guardrails.validate_manifests([deployment() for _ in range(11)])


def test_malformed_manifest_is_clean_violation_not_crash():
    # A string where an object is expected must not raise AttributeError.
    with pytest.raises(GuardrailViolation, match="not a JSON object"):
        guardrails.validate_manifests(["oops"])


def test_metadata_not_object_is_clean_violation():
    with pytest.raises(GuardrailViolation, match="metadata must be an object"):
        guardrails.validate_manifests(
            [{"apiVersion": "v1", "kind": "ConfigMap", "metadata": "nope"}]
        )


# --------------------------------------------------------------------- GVK / namespace


def test_disallowed_kind():
    with pytest.raises(GuardrailViolation, match="not an allowed apiVersion/kind"):
        guardrails.validate_manifests([deployment(kind="ClusterRoleBinding")])


def test_gvk_spoofing_blocked():
    with pytest.raises(GuardrailViolation, match="not an allowed apiVersion/kind"):
        guardrails.validate_manifests([deployment(apiVersion="evil.example/v1")])


def test_missing_namespace():
    with pytest.raises(GuardrailViolation, match="namespace is required"):
        guardrails.validate_manifests([deployment(metadata={"name": "payments"})])


def test_protected_namespace():
    bad = deployment(metadata={"name": "payments", "namespace": "kube-system"})
    with pytest.raises(GuardrailViolation, match="protected"):
        guardrails.validate_manifests([bad])


# --------------------------------------------------------------------- pod security


def test_automount_token_must_be_false():
    bad = deployment()
    del pod_spec(bad)["automountServiceAccountToken"]
    with pytest.raises(GuardrailViolation, match="automountServiceAccountToken"):
        guardrails.validate_manifests([bad])


def test_runasnonroot_required():
    bad = deployment()
    pod_spec(bad)["containers"][0]["securityContext"].pop("runAsNonRoot")
    with pytest.raises(GuardrailViolation, match="runAsNonRoot"):
        guardrails.validate_manifests([bad])


def test_drop_all_capabilities_required():
    bad = deployment()
    pod_spec(bad)["containers"][0]["securityContext"]["capabilities"] = {"drop": ["NET_RAW"]}
    with pytest.raises(GuardrailViolation, match="drop must include ALL"):
        guardrails.validate_manifests([bad])


def test_seccomp_required():
    bad = deployment()
    pod_spec(bad)["containers"][0]["securityContext"].pop("seccompProfile")
    with pytest.raises(GuardrailViolation, match="seccompProfile"):
        guardrails.validate_manifests([bad])


def test_allow_privilege_escalation_absent_rejected():
    bad = deployment()
    pod_spec(bad)["containers"][0]["securityContext"].pop("allowPrivilegeEscalation")
    with pytest.raises(GuardrailViolation, match="allowPrivilegeEscalation"):
        guardrails.validate_manifests([bad])


def test_privileged_rejected():
    bad = deployment()
    pod_spec(bad)["containers"][0]["securityContext"]["privileged"] = True
    with pytest.raises(GuardrailViolation, match="privileged"):
        guardrails.validate_manifests([bad])


def test_added_capabilities():
    bad = deployment()
    pod_spec(bad)["containers"][0]["securityContext"]["capabilities"] = {
        "drop": ["ALL"],
        "add": ["NET_ADMIN"],
    }
    with pytest.raises(GuardrailViolation, match="NET_ADMIN"):
        guardrails.validate_manifests([bad])


def test_host_network():
    bad = deployment()
    pod_spec(bad)["hostNetwork"] = True
    with pytest.raises(GuardrailViolation, match="hostNetwork"):
        guardrails.validate_manifests([bad])


def test_arbitrary_service_account_blocked():
    bad = deployment()
    pod_spec(bad)["serviceAccountName"] = "admin"
    with pytest.raises(GuardrailViolation, match="serviceAccountName"):
        guardrails.validate_manifests([bad])


def test_secret_env_ref_blocked():
    bad = deployment()
    pod_spec(bad)["containers"][0]["env"] = [
        {"name": "PW", "valueFrom": {"secretKeyRef": {"name": "db", "key": "pw"}}}
    ]
    with pytest.raises(GuardrailViolation, match="secretKeyRef"):
        guardrails.validate_manifests([bad])


def test_ephemeral_container_checked():
    bad = deployment()
    pod_spec(bad)["ephemeralContainers"] = [
        {"name": "debug", "image": "busybox:1.36", "securityContext": {"privileged": True}}
    ]
    with pytest.raises(GuardrailViolation, match="ephemeralContainer"):
        guardrails.validate_manifests([bad])


def test_init_containers_checked():
    bad = deployment()
    pod_spec(bad)["initContainers"] = [
        {"name": "init", "image": "busybox:1.36", "securityContext": {"privileged": True}}
    ]
    with pytest.raises(GuardrailViolation, match="privileged"):
        guardrails.validate_manifests([bad])


# --------------------------------------------------------------------- volumes


def test_hostpath_volume():
    bad = deployment()
    pod_spec(bad)["volumes"] = [{"name": "logs", "hostPath": {"path": "/var/log"}}]
    with pytest.raises(GuardrailViolation, match="hostPath"):
        guardrails.validate_manifests([bad])


def test_secret_volume_blocked():
    bad = deployment()
    pod_spec(bad)["volumes"] = [{"name": "s", "secret": {"secretName": "db"}}]
    with pytest.raises(GuardrailViolation, match="type 'secret'"):
        guardrails.validate_manifests([bad])


@pytest.mark.parametrize("vtype", ["persistentVolumeClaim", "csi", "nfs"])
def test_disallowed_volume_types(vtype):
    bad = deployment()
    pod_spec(bad)["volumes"] = [{"name": "v", vtype: {}}]
    with pytest.raises(GuardrailViolation, match="is not allowed"):
        guardrails.validate_manifests([bad])


def test_allowed_volume_types_pass():
    good = deployment()
    pod_spec(good)["volumes"] = [
        {"name": "c", "configMap": {"name": "cfg"}},
        {"name": "tmp", "emptyDir": {}},
    ]
    guardrails.validate_manifests([good])


# --------------------------------------------------------------------- services


def test_nodeport_service_rejected():
    bad = {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {"name": "svc", "namespace": "shop"},
        "spec": {"type": "NodePort", "ports": [{"port": 80}]},
    }
    with pytest.raises(GuardrailViolation, match="Service type"):
        guardrails.validate_manifests([bad])


def test_external_ips_rejected():
    bad = {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {"name": "svc", "namespace": "shop"},
        "spec": {"type": "ClusterIP", "externalIPs": ["1.2.3.4"]},
    }
    with pytest.raises(GuardrailViolation, match="externalIPs"):
        guardrails.validate_manifests([bad])


def test_clusterip_service_passes():
    guardrails.validate_manifests(
        [
            {
                "apiVersion": "v1",
                "kind": "Service",
                "metadata": {"name": "svc", "namespace": "shop"},
                "spec": {"type": "ClusterIP", "ports": [{"port": 80}]},
            }
        ]
    )


# --------------------------------------------------------------------- images


@pytest.mark.parametrize(
    "image",
    ["payments:latest", "payments", "registry.example.com/team/payments"],
)
def test_unpinned_images(image):
    bad = deployment()
    pod_spec(bad)["containers"][0]["image"] = image
    with pytest.raises(GuardrailViolation, match="pinned"):
        guardrails.validate_manifests([bad])


def test_strict_digest_mode_rejects_tag(monkeypatch):
    monkeypatch.setattr(SETTINGS, "require_image_digest", True)
    bad = deployment()  # image is a plain tag
    with pytest.raises(GuardrailViolation, match="sha256"):
        guardrails.validate_manifests([bad])


def test_strict_digest_mode_accepts_digest(monkeypatch):
    monkeypatch.setattr(SETTINGS, "require_image_digest", True)
    good = deployment()
    pod_spec(good)["containers"][0]["image"] = "registry.example.com/payments@sha256:" + "a" * 64
    guardrails.validate_manifests([good])


# --------------------------------------------------------------------- aggregation


def test_all_violations_reported_together():
    bad = deployment(metadata={"name": "p", "namespace": "kube-system"})
    pod_spec(bad)["hostNetwork"] = True
    with pytest.raises(GuardrailViolation) as excinfo:
        guardrails.validate_manifests([bad])
    message = str(excinfo.value)
    assert "protected" in message and "hostNetwork" in message


# --------------------------------------------------------------------- v0.2.1 gap coverage


def test_projected_service_account_token_volume_rejected():
    bad = deployment()
    pod_spec(bad)["volumes"] = [
        {"name": "t", "projected": {"sources": [{"serviceAccountToken": {"path": "tok"}}]}}
    ]
    with pytest.raises(GuardrailViolation, match="serviceAccountToken or secret"):
        guardrails.validate_manifests([bad])


def test_projected_secret_source_rejected():
    bad = deployment()
    pod_spec(bad)["volumes"] = [
        {"name": "t", "projected": {"sources": [{"secret": {"name": "db"}}]}}
    ]
    with pytest.raises(GuardrailViolation, match="serviceAccountToken or secret"):
        guardrails.validate_manifests([bad])


def test_projected_volume_without_token_or_secret_passes():
    good = deployment()
    pod_spec(good)["volumes"] = [{"name": "t", "projected": {"sources": [{"downwardAPI": {}}]}}]
    guardrails.validate_manifests([good])


def test_env_from_secret_ref_blocked():
    bad = deployment()
    pod_spec(bad)["containers"][0]["envFrom"] = [{"secretRef": {"name": "db"}}]
    with pytest.raises(GuardrailViolation, match="secretKeyRef/secretRef"):
        guardrails.validate_manifests([bad])


def test_pod_level_security_context_satisfies_containers():
    # runAsNonRoot + seccomp supplied at the POD level; container carries only the rest.
    good = deployment()
    ps = pod_spec(good)
    ps["securityContext"] = {"runAsNonRoot": True, "seccompProfile": {"type": "RuntimeDefault"}}
    ps["containers"][0]["securityContext"] = {
        "allowPrivilegeEscalation": False,
        "capabilities": {"drop": ["ALL"]},
    }
    guardrails.validate_manifests([good])


def test_ephemeral_container_unpinned_image_rejected():
    bad = deployment()
    pod_spec(bad)["ephemeralContainers"] = [
        {
            "name": "debug",
            "image": "busybox:latest",
            "securityContext": {
                "runAsNonRoot": True,
                "allowPrivilegeEscalation": False,
                "seccompProfile": {"type": "RuntimeDefault"},
                "capabilities": {"drop": ["ALL"]},
            },
        }
    ]
    with pytest.raises(GuardrailViolation, match="pinned"):
        guardrails.validate_manifests([bad])


@pytest.mark.parametrize("field", ["hostPID", "hostIPC"])
def test_host_pid_ipc_rejected(field):
    bad = deployment()
    pod_spec(bad)[field] = True
    with pytest.raises(GuardrailViolation, match="hostPID/hostIPC"):
        guardrails.validate_manifests([bad])


def test_apiversion_not_string_is_clean_violation():
    bad = {"apiVersion": 123, "kind": "ConfigMap", "metadata": {"name": "c", "namespace": "shop"}}
    with pytest.raises(GuardrailViolation, match="apiVersion must be a string"):
        guardrails.validate_manifests([bad])


def test_kind_not_string_is_clean_violation():
    bad = {
        "apiVersion": "v1",
        "kind": ["ConfigMap"],
        "metadata": {"name": "c", "namespace": "shop"},
    }
    with pytest.raises(GuardrailViolation, match="kind must be a string"):
        guardrails.validate_manifests([bad])


def test_service_account_alias_blocked():
    bad = deployment()
    pod_spec(bad)["serviceAccount"] = "admin"  # the older alias field
    with pytest.raises(GuardrailViolation, match="not allowed"):
        guardrails.validate_manifests([bad])


def test_run_as_user_root_rejected():
    bad = deployment()
    pod_spec(bad)["containers"][0]["securityContext"]["runAsUser"] = 0
    with pytest.raises(GuardrailViolation, match="runAsUser 0"):
        guardrails.validate_manifests([bad])


def test_pod_level_run_as_user_root_rejected():
    bad = deployment()
    pod_spec(bad)["securityContext"] = {"runAsUser": 0}
    with pytest.raises(GuardrailViolation, match="runAsUser 0"):
        guardrails.validate_manifests([bad])
