# SPDX-FileCopyrightText: 2026 Sandeep Bazar
# SPDX-License-Identifier: Apache-2.0

"""CSR validation for the `accept` path: only genuine, pending, cluster-bound OCM join
CSRs may ride the human approval into kube-apiserver trust."""

import base64
from types import SimpleNamespace

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from ocm_mcp_server import ocm
from ocm_mcp_server.ocm import (
    OCM_CSR_SIGNER,
    _approve_pending_csrs,
    _csr_matches_cluster,
    _csr_request_hash,
    _csr_subject_cn_ok,
    _is_ocm_join_csr,
)


def pkcs10(cn: str) -> str:
    """A real, self-signed PKCS#10 request with the given subject CN (base64 DER)."""
    key = ec.generate_private_key(ec.SECP256R1())
    req = (
        x509.CertificateSigningRequestBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)]))
        .sign(key, hashes.SHA256())
    )
    return base64.b64encode(req.public_bytes(serialization.Encoding.DER)).decode()


def csr(
    name="csr-1",
    uid="u1",
    cluster="cluster1",
    username=None,
    signer=OCM_CSR_SIGNER,
    groups=None,
    usages=None,
    condition_types=(),
    label_cluster="__default__",
    request="__default__",
    subject_cn=None,
):
    username = (
        username if username is not None else f"system:open-cluster-management:{cluster}:agent"
    )
    groups = (
        groups
        if groups is not None
        else [f"system:open-cluster-management:{cluster}", "system:authenticated"]
    )
    usages = (
        usages if usages is not None else ["digital signature", "key encipherment", "client auth"]
    )
    label_cluster = cluster if label_cluster == "__default__" else label_cluster
    labels = (
        {} if label_cluster is None else {"open-cluster-management.io/cluster-name": label_cluster}
    )
    # By default the request's subject CN matches the bootstrap username for the cluster.
    if request == "__default__":
        request = pkcs10(subject_cn if subject_cn is not None else username)
    return SimpleNamespace(
        metadata=SimpleNamespace(name=name, uid=uid, labels=labels),
        spec=SimpleNamespace(
            username=username, signer_name=signer, groups=groups, usages=usages, request=request
        ),
        status=SimpleNamespace(conditions=[SimpleNamespace(type=t) for t in condition_types]),
    )


# --------------------------------------------------------------- _is_ocm_join_csr


def test_valid_ocm_join_csr_accepted():
    assert _is_ocm_join_csr(csr()) is True


def test_csr_denied_is_not_approvable():
    assert _is_ocm_join_csr(csr(condition_types=["Denied"])) is False


def test_csr_already_approved_is_not_approvable():
    assert _is_ocm_join_csr(csr(condition_types=["Approved"])) is False


def test_csr_wrong_signer_rejected():
    assert _is_ocm_join_csr(csr(signer="kubernetes.io/kubelet-serving")) is False


def test_csr_missing_ocm_group_rejected():
    assert _is_ocm_join_csr(csr(groups=["system:authenticated"])) is False


def test_csr_missing_client_auth_usage_rejected():
    assert _is_ocm_join_csr(csr(usages=["digital signature", "key encipherment"])) is False


def test_csr_wrong_username_prefix_rejected():
    assert _is_ocm_join_csr(csr(username="system:node:worker")) is False


# --------------------------------------------------------------- _csr_matches_cluster


def test_csr_matches_when_label_and_username_agree():
    assert _csr_matches_cluster(csr(cluster="cluster1"), "cluster1") is True


def test_csr_label_cluster_mismatch_rejected():
    assert (
        _csr_matches_cluster(csr(cluster="cluster1", label_cluster="clusterB"), "cluster1") is False
    )


def test_csr_username_cluster_mismatch_rejected():
    # label names clusterA but the bootstrap username names clusterB
    c = csr(cluster="clusterA", username="system:open-cluster-management:clusterB:agent")
    assert _csr_matches_cluster(c, "clusterA") is False


# --------------------------------------------------------------- _approve_pending_csrs (TOCTOU)


class _FakeCerts:
    def __init__(self, items):
        self._items = items
        self.approved: list[str] = []

    def list_certificate_signing_request(self):
        return SimpleNamespace(items=self._items)

    def replace_certificate_signing_request_approval(self, name, _obj):
        self.approved.append(name)


def test_approve_only_captured_csrs(monkeypatch):
    reviewed = csr(name="reviewed", uid="u-rev", cluster="cluster1")
    sneaked_in = csr(name="late", uid="u-late", cluster="cluster1")  # created after human review
    fake = _FakeCerts([reviewed, sneaked_in])
    monkeypatch.setattr(ocm, "hub_certificates", lambda: fake)
    approved = _approve_pending_csrs(
        "cluster1",
        [{"name": "reviewed", "uid": "u-rev", "request_hash": _csr_request_hash(reviewed)}],
    )
    assert approved == ["reviewed"] and "late" not in approved


def test_approve_skips_uid_changed(monkeypatch):
    # Same name captured, but the live CSR has a different uid (re-created between review and apply).
    live = csr(name="reviewed", uid="u-new", cluster="cluster1")
    fake = _FakeCerts([live])
    monkeypatch.setattr(ocm, "hub_certificates", lambda: fake)
    approved = _approve_pending_csrs("cluster1", [{"name": "reviewed", "uid": "u-old"}])
    assert approved == []


def test_approve_skips_now_denied(monkeypatch):
    live = csr(name="reviewed", uid="u-rev", cluster="cluster1", condition_types=["Denied"])
    fake = _FakeCerts([live])
    monkeypatch.setattr(ocm, "hub_certificates", lambda: fake)
    approved = _approve_pending_csrs("cluster1", [{"name": "reviewed", "uid": "u-rev"}])
    assert approved == []


# --------------------------------------------------------------- PKCS#10 subject + request hash


def test_subject_cn_matches_cluster():
    assert _csr_subject_cn_ok(csr(cluster="cluster1"), "cluster1") is True


def test_subject_cn_wrong_cluster_rejected():
    # A request whose certificate CN names a different cluster than the join target.
    c = csr(cluster="cluster1", subject_cn="system:open-cluster-management:clusterB:agent")
    assert _csr_subject_cn_ok(c, "cluster1") is False


def test_subject_cn_unparseable_request_rejected():
    assert _csr_subject_cn_ok(csr(request="not-base64-pkcs10"), "cluster1") is False


def test_approve_skips_request_hash_changed(monkeypatch):
    # Human captured one request; the live CSR now carries a different PKCS#10 request.
    live = csr(name="reviewed", uid="u-rev", cluster="cluster1")
    fake = _FakeCerts([live])
    monkeypatch.setattr(ocm, "hub_certificates", lambda: fake)
    approved = _approve_pending_csrs(
        "cluster1",
        [{"name": "reviewed", "uid": "u-rev", "request_hash": "deadbeef-not-the-live-hash"}],
    )
    assert approved == []


def test_approve_accepts_matching_request_hash(monkeypatch):
    live = csr(name="reviewed", uid="u-rev", cluster="cluster1")
    fake = _FakeCerts([live])
    monkeypatch.setattr(ocm, "hub_certificates", lambda: fake)
    approved = _approve_pending_csrs(
        "cluster1",
        [{"name": "reviewed", "uid": "u-rev", "request_hash": _csr_request_hash(live)}],
    )
    assert approved == ["reviewed"]
