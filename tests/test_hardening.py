# SPDX-FileCopyrightText: 2026 Sandeep Bazar
# SPDX-License-Identifier: Apache-2.0

"""Regression tests for the review hardening fixes (H1, M2, M4, M5)."""

import pytest

from ocm_mcp_server import approvals, guardrails
from ocm_mcp_server.config import SETTINGS

MANIFEST = {
    "apiVersion": "apps/v1",
    "kind": "Deployment",
    "metadata": {"name": "payments", "namespace": "shop"},
    "spec": {
        "template": {
            "spec": {
                "automountServiceAccountToken": False,
                "containers": [
                    {
                        "name": "c",
                        "image": "reg/app:1.2.3",
                        "securityContext": {
                            "runAsNonRoot": True,
                            "allowPrivilegeEscalation": False,
                            "seccompProfile": {"type": "RuntimeDefault"},
                            "capabilities": {"drop": ["ALL"]},
                        },
                    }
                ],
            }
        }
    },
}


# --- approval keys: server holds the public key only; rotation invalidates tokens ---


def test_approval_keypair_generated_and_public_only_verifies(tmp_home):
    prop = approvals.new_proposal("c2", "fix", "summary", [MANIFEST])
    token = approvals.mint_token(prop)  # generates the Ed25519 keypair on first mint
    assert SETTINGS.approval_private_key_path.exists()
    assert SETTINGS.approval_public_key_path.exists()
    # Verification uses only the public key - delete the private key and it still works.
    SETTINGS.approval_private_key_path.unlink()
    approvals.verify_token(prop, token, operation="apply")


def test_rotate_approval_key_invalidates_tokens(tmp_home):
    prop = approvals.new_proposal("c2", "fix", "summary", [MANIFEST])
    token = approvals.mint_token(prop)
    approvals.verify_token(prop, token, operation="apply")  # valid before rotation
    SETTINGS.rotate_approval_key()
    with pytest.raises(approvals.ApprovalError):
        approvals.verify_token(prop, token, operation="apply")  # old token is now worthless


def test_apply_token_cannot_authorize_rollback(tmp_home):
    prop = approvals.new_proposal("c2", "fix", "summary", [MANIFEST])
    apply_token = approvals.mint_token(prop, operation="apply")
    with pytest.raises(approvals.ApprovalError, match="authorizes 'apply', not 'rollback'"):
        approvals.verify_token(prop, apply_token, operation="rollback")


# --- M4: proposal IDs are full UUIDs, not 8 hex chars ---------------------------


def test_proposal_ids_are_full_uuid(tmp_home):
    p1 = approvals.new_proposal("c", "a", "s", [MANIFEST])
    p2 = approvals.new_action_proposal("c", "cordon", "s", {})
    assert len(p1.id) == 32
    assert len(p2.id) == 32


# --- M2: content-hash integrity is re-checked at apply time ---------------------


def test_content_intact_detects_tampered_manifests(tmp_home):
    from ocm_mcp_server.server import _content_intact

    prop = approvals.new_proposal("c2", "fix", "summary", [MANIFEST])
    assert _content_intact(prop) is None  # pristine proposal is fine
    # Simulate an at-rest edit: change the manifests but leave content_hash stale.
    prop.manifests = [{**MANIFEST, "spec": {"replicas": 99}}]
    msg = _content_intact(prop)
    assert msg is not None and "content hash" in msg


# --- M5: pod-spec extraction is robust across workload kinds --------------------


def test_pod_spec_handles_cronjob():
    cron = {
        "kind": "CronJob",
        "spec": {
            "jobTemplate": {
                "spec": {"template": {"spec": {"containers": [{"name": "c", "image": "x:1"}]}}}
            }
        },
    }
    containers = [c for _, c in guardrails._containers(cron)]
    assert containers and containers[0]["image"] == "x:1"


def test_pod_spec_handles_statefulset_like_deployment():
    sts = {
        "kind": "StatefulSet",
        "spec": {"template": {"spec": {"containers": [{"name": "c", "image": "y:2"}]}}},
    }
    assert next(c for _, c in guardrails._containers(sts))["image"] == "y:2"


# --- v0.2.1 approval hardening: replay, issuer/audience, one-time use ---


def test_token_replay_refused(tmp_home):
    prop = approvals.new_proposal("c2", "fix", "s", [MANIFEST])
    token = approvals.mint_token(prop, operation="apply")
    approvals.verify_token(prop, token, operation="apply", consume=True)  # first use ok
    with pytest.raises(approvals.ApprovalError, match="already been used"):
        approvals.verify_token(prop, token, operation="apply", consume=True)


def test_verify_without_consume_does_not_burn_token(tmp_home):
    prop = approvals.new_proposal("c2", "fix", "s", [MANIFEST])
    token = approvals.mint_token(prop, operation="apply")
    approvals.verify_token(prop, token, operation="apply")  # inspection, no consume
    approvals.verify_token(prop, token, operation="apply", consume=True)  # still usable


def test_wrong_audience_refused(tmp_home, monkeypatch):
    prop = approvals.new_proposal("c2", "fix", "s", [MANIFEST])
    token = approvals.mint_token(prop, operation="apply")
    monkeypatch.setattr(SETTINGS, "audience", "some-other-deployment")
    with pytest.raises(approvals.ApprovalError, match="audience"):
        approvals.verify_token(prop, token, operation="apply")


def test_wrong_issuer_refused(tmp_home, monkeypatch):
    prop = approvals.new_proposal("c2", "fix", "s", [MANIFEST])
    token = approvals.mint_token(prop, operation="apply")
    monkeypatch.setattr(SETTINGS, "issuer", "someone-else")
    with pytest.raises(approvals.ApprovalError, match="issuer"):
        approvals.verify_token(prop, token, operation="apply")


def test_approver_recorded_in_claims(tmp_home):
    prop = approvals.new_proposal("c2", "fix", "s", [MANIFEST])
    token = approvals.mint_token(prop, operation="apply", approver="alice")
    claims = approvals.verify_token(prop, token, operation="apply")
    assert claims["approver"] == "alice"


# --- v0.2.1 state store: guarded status transitions ---


def test_illegal_status_transition_refused(tmp_home):
    prop = approvals.new_proposal("c2", "fix", "s", [MANIFEST])
    prop.set_status("applied")
    with pytest.raises(approvals.ApprovalError, match="Illegal proposal transition"):
        prop.set_status("pending")  # cannot go back


def test_terminal_status_is_final(tmp_home):
    prop = approvals.new_proposal("c2", "fix", "s", [MANIFEST])
    prop.set_status("rejected")
    with pytest.raises(approvals.ApprovalError, match="Illegal proposal transition"):
        prop.set_status("applied")


# --- v0.2.1 audit: tamper-evident hash chain ---


def test_audit_chain_detects_tampering(tmp_home):
    from ocm_mcp_server import tracing

    tracing.audit({"tool": "a", "outcome": "ok"})
    tracing.audit({"tool": "b", "outcome": "ok"})
    ok, _ = tracing.verify_audit_chain()
    assert ok

    # Tamper with a line in place; the chain must no longer verify.
    log = SETTINGS.audit_log
    lines = log.read_text().splitlines()
    import json as _json

    rec = _json.loads(lines[0])
    rec["outcome"] = "rejected"  # rewrite history, keep the old hash
    lines[0] = _json.dumps(rec)
    log.write_text("\n".join(lines) + "\n")
    ok, msg = tracing.verify_audit_chain()
    assert not ok and "broken" in msg


def test_manifestwork_body_always_labeled():
    # The anchor that makes the Kyverno require-managed-by-label policy effective: the
    # server can never emit a ManifestWork without the managed-by label.
    from ocm_mcp_server import ocm

    body = ocm.manifestwork_body("x", [MANIFEST])
    assert body["metadata"]["labels"]["app.kubernetes.io/managed-by"] == "ocm-mcp-server"


# --- v0.2.1 approval: nbf, planned rotation overlap, off-box signer, cross-process replay ---


def test_token_not_yet_valid_rejected(tmp_home, monkeypatch):
    prop = approvals.new_proposal("c2", "fix", "s", [MANIFEST])
    token = approvals.mint_token(prop, operation="apply")
    monkeypatch.setattr(approvals.time, "time", lambda: 0)  # before nbf
    with pytest.raises(approvals.ApprovalError, match="not yet valid"):
        approvals.verify_token(prop, token, operation="apply")


def test_token_before_planned_rotation_still_verifies(tmp_home):
    import shutil

    prop = approvals.new_proposal("c2", "fix", "s", [MANIFEST])
    token = approvals.mint_token(prop, operation="apply")  # generates keypair
    # Planned rotation: stage the current verifier as previous, then mint a fresh keypair.
    shutil.copy(SETTINGS.approval_public_key_path, SETTINGS.previous_public_key_path)
    SETTINGS.approval_private_key_path.unlink()
    SETTINGS.approval_public_key_path.unlink()
    approvals.mint_token(prop, operation="apply")  # regenerates a new keypair
    # The old token still verifies via the retained previous verifier key.
    approvals.verify_token(prop, token, operation="apply")


def test_signer_verifier_path_overrides_honored(tmp_home, tmp_path, monkeypatch):
    signer = tmp_path / "signer_key"
    verifier = tmp_path / "verifier_key.pub"
    monkeypatch.setenv("OCM_MCP_SIGNER_KEY", str(signer))
    monkeypatch.setenv("OCM_MCP_VERIFIER_KEY", str(verifier))
    assert SETTINGS.approval_private_key_path == signer
    assert SETTINGS.approval_public_key_path == verifier
    prop = approvals.new_proposal("c2", "fix", "s", [MANIFEST])
    token = approvals.mint_token(prop, operation="apply")
    assert signer.exists() and verifier.exists()
    signer.unlink()  # the server side keeps only the public verifier
    approvals.verify_token(prop, token, operation="apply")


def test_consumed_token_recorded_and_refused_from_file(tmp_home):
    prop = approvals.new_proposal("c2", "fix", "s", [MANIFEST])
    token = approvals.mint_token(prop, operation="apply")
    approvals.verify_token(prop, token, operation="apply", consume=True)
    assert '"jti"' in SETTINGS.used_tokens_path.read_text()  # persisted for cross-restart refusal
    with pytest.raises(approvals.ApprovalError, match="already been used"):
        approvals.verify_token(prop, token, operation="apply")  # refused purely from the file


def test_rotate_removes_private_public_and_previous(tmp_home):
    prop = approvals.new_proposal("c2", "fix", "s", [MANIFEST])
    approvals.mint_token(prop)  # creates private + public
    SETTINGS.previous_public_key_path.write_text("deadbeef")  # a staged previous key
    SETTINGS.rotate_approval_key()
    assert not SETTINGS.approval_private_key_path.exists()
    assert not SETTINGS.approval_public_key_path.exists()
    assert not SETTINGS.previous_public_key_path.exists()


# --- v0.2.1 audit: reordering, actor, permissions ---


def test_audit_chain_detects_reordering(tmp_home):
    from ocm_mcp_server import tracing

    for t in ("a", "b", "c"):
        tracing.audit({"tool": t, "outcome": "ok"})
    log = SETTINGS.audit_log
    lines = log.read_text().splitlines()
    lines[0], lines[1] = lines[1], lines[0]
    log.write_text("\n".join(lines) + "\n")
    ok, msg = tracing.verify_audit_chain()
    assert not ok and "broken" in msg


def test_audit_records_actor(tmp_home):
    import json as _json

    from ocm_mcp_server import tracing

    tracing.audit({"tool": "x", "outcome": "ok"})
    last = _json.loads(SETTINGS.audit_log.read_text().splitlines()[-1])
    assert ":" in last["actor"]


def test_key_and_state_permissions(tmp_home):
    import sys

    if sys.platform == "win32":
        pytest.skip("POSIX permissions")
    from ocm_mcp_server import tracing

    prop = approvals.new_proposal("c2", "fix", "s", [MANIFEST])
    approvals.mint_token(prop)
    tracing.audit({"tool": "x", "outcome": "ok"})

    def mode(p):
        return p.stat().st_mode & 0o777

    assert mode(SETTINGS.approval_private_key_path) == 0o600
    assert mode(SETTINGS.approval_public_key_path) == 0o644
    assert mode(SETTINGS.proposals_dir) == 0o700
    assert mode(prop.path()) == 0o600
    assert mode(SETTINGS.audit_log) == 0o600


def test_audit_arg_values_are_bounded(tmp_home):
    # A large argument must be truncated in the audit line so it can't overflow the
    # hash-chain tail read or bloat the log; the chain must still verify.
    from ocm_mcp_server import tracing

    big = "x" * 100_000
    tracing.audit(
        {"tool": "propose_manifestwork", "args": {"manifests_json": big}, "outcome": "ok"}
    )
    # audit() stores what it is given; the truncation happens in traced_tool via _audit_arg.
    assert tracing._audit_arg("manifests_json", big).endswith("chars)")
    assert tracing._audit_arg("approval_token", "secret") == "<redacted>"
    ok, _ = tracing.verify_audit_chain()
    assert ok
