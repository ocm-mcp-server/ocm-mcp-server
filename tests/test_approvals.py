# SPDX-FileCopyrightText: 2026 Sandeep Bazar
# SPDX-License-Identifier: Apache-2.0

import time

import pytest

from ocm_mcp_server import approvals
from ocm_mcp_server.approvals import ApprovalError

MANIFESTS = [
    {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": "payments", "namespace": "shop"},
        "spec": {"replicas": 2},
    }
]


def make_proposal():
    return approvals.new_proposal("cluster2", "fix-payments", "pin image back to v1.9", MANIFESTS)


def test_token_roundtrip(tmp_home):
    prop = make_proposal()
    token = approvals.mint_token(prop)
    approvals.verify_token(prop, token)  # must not raise


def test_token_rejected_for_other_proposal(tmp_home):
    first = make_proposal()
    second = approvals.new_proposal("cluster3", "other", "different change", MANIFESTS)
    token = approvals.mint_token(first)
    with pytest.raises(ApprovalError, match="different proposal"):
        approvals.verify_token(second, token)


def test_token_invalid_after_content_change(tmp_home):
    prop = make_proposal()
    token = approvals.mint_token(prop)
    prop.content_hash = approvals.content_hash(
        prop.cluster, prop.name, [{**MANIFESTS[0], "spec": {"replicas": 50}}]
    )
    with pytest.raises(ApprovalError, match="content mismatch"):
        approvals.verify_token(prop, token)


def test_token_expiry(tmp_home):
    prop = make_proposal()
    token = approvals.mint_token(prop, ttl_seconds=-1)
    with pytest.raises(ApprovalError, match="expired"):
        approvals.verify_token(prop, token)


def test_malformed_tokens(tmp_home):
    prop = make_proposal()
    for bad in ["", "abc", "a.b", "a.b.c.d", f"{prop.id}.notanumber.deadbeef"]:
        with pytest.raises(ApprovalError):
            approvals.verify_token(prop, bad)


def test_tampered_signature(tmp_home):
    prop = make_proposal()
    token = approvals.mint_token(prop)
    head, _, sig = token.rpartition(".")
    flipped = ("0" if sig[0] != "0" else "1") + sig[1:]
    with pytest.raises(ApprovalError):
        approvals.verify_token(prop, f"{head}.{flipped}")


def test_proposal_persistence(tmp_home):
    prop = make_proposal()
    loaded = approvals.load_proposal(prop.id)
    assert loaded.cluster == "cluster2"
    assert loaded.status == "pending"
    assert loaded.content_hash == prop.content_hash
    assert approvals.list_proposals(status="pending")


def test_unknown_proposal(tmp_home):
    with pytest.raises(ApprovalError, match="No proposal"):
        approvals.load_proposal("0" * 32)  # valid format, just does not exist


def test_invalid_proposal_id_rejected(tmp_home):
    # A path-traversal-ish or malformed id is refused before any filesystem access.
    with pytest.raises(ApprovalError, match="Invalid proposal id"):
        approvals.load_proposal("../../etc/passwd")


def test_expiry_uses_wall_clock(tmp_home, monkeypatch):
    prop = make_proposal()
    token = approvals.mint_token(prop, ttl_seconds=3600)
    future = time.time() + 7200
    monkeypatch.setattr(time, "time", lambda: future)
    with pytest.raises(ApprovalError, match="expired"):
        approvals.verify_token(prop, token)


# ------------------------------------------------------------ small-gap coverage


def test_proposal_with_invalid_id_cannot_be_saved(tmp_home):
    prop = approvals.Proposal(
        id="../../escape",
        cluster="c",
        name="n",
        summary="s",
        manifests=[],
        created_at=time.time(),
    )
    with pytest.raises(ApprovalError, match="Invalid proposal id"):
        prop.save()


def test_proposal_lock_rejects_invalid_id(tmp_home):
    with pytest.raises(ApprovalError, match="Invalid proposal id"):
        approvals.proposal_lock("../../etc/passwd")


def test_list_proposals_status_filter_excludes_nonmatching(tmp_home):
    make_proposal()
    assert approvals.list_proposals(status="applied") == []
    assert len(approvals.list_proposals(status="pending")) == 1


def test_load_used_missing_file_and_blank_lines(tmp_home):
    assert approvals._load_used(tmp_home / "does-not-exist.jsonl") == []
    ledger = tmp_home / "used_tokens.jsonl"
    ledger.write_text('\n{"jti": "abc"}\n\nnot-json\n')
    assert approvals._load_used(ledger) == [{"jti": "abc"}]


def test_mark_token_used_refuses_replay(tmp_home):
    claims = {"jti": "j1", "id": "a" * 32, "op": "apply", "exp": int(time.time()) + 60}
    approvals._mark_token_used(claims)
    with pytest.raises(ApprovalError, match="already been used"):
        approvals._mark_token_used(claims)


def test_ledger_compaction_drops_expired_entries(tmp_home, monkeypatch):
    monkeypatch.setattr(approvals, "_LEDGER_COMPACT_AT", 3)
    now = int(time.time())
    path = approvals.SETTINGS.used_tokens_path
    import json as _json

    with path.open("w") as f:
        for jti, exp in (("old1", now - 100), ("old2", now - 50), ("live", now + 3600)):
            f.write(_json.dumps({"jti": jti, "exp": exp}) + "\n")
    approvals._mark_token_used({"jti": "new", "id": "b" * 32, "op": "apply", "exp": now + 3600})
    jtis = {e["jti"] for e in approvals._load_used(path)}
    assert jtis == {"live", "new"}  # expired ids dropped, live + new kept


def test_signed_non_json_payload_rejected(tmp_home):
    # A payload with a VALID signature but non-JSON content must still be refused.
    prop = make_proposal()
    key = approvals._private_key()
    payload = b"this is not json"
    token = approvals._b64(payload) + "." + approvals._b64(key.sign(payload))
    with pytest.raises(ApprovalError, match="Malformed approval token"):
        approvals.verify_token(prop, token)
