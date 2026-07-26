# SPDX-FileCopyrightText: 2026 Sandeep Bazar
# SPDX-License-Identifier: Apache-2.0

"""Human approval flow for destructive actions.

Design:
- A propose_* tool stores a proposal file (JSON) with a SHA-256 content hash.
- A human runs `ocm-mcp approve <id>` on a trusted terminal; the CLI signs an
  approval token (Ed25519) whose claims bind the exact proposal content hash, the
  intended operation (apply or rollback), and an expiry.
- apply_* only succeeds when the token's signature verifies and its claims match.

Approval is asymmetric on purpose. The signing (private) key lives in
OCM_MCP_HOME/approval_ed25519 (0600) and is used only by the `ocm-mcp` CLI. The MCP
server loads only the public key (approval_ed25519.pub), so it can verify a token
but can never mint one - even if the server, or an agent that reads the server's key
material, is compromised. Keep the signer in a separate OS account, device, or
chat-ops/ticket service for full isolation; until then, treat shell/filesystem
isolation between the agent and the CLI as mandatory.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

from .config import SETTINGS
from .filelock import locked


class ApprovalError(Exception):
    """Raised when an approval token is missing, expired, or invalid."""


SCHEMA_VERSION = 1

# Legal proposal status transitions. A proposal advances forward only; it can never
# move back to pending or from a terminal state, so a stale file cannot be re-applied.
_STATUS_TRANSITIONS = {
    "pending": {"applied", "rejected"},
    "applied": {"rolled_back"},
    "rejected": set(),
    "rolled_back": set(),
}


def _valid_id(proposal_id: str) -> bool:
    """A proposal id must be a 32-char uuid4 hex string. This is also what keeps a
    caller-supplied id from escaping the proposals directory (path traversal)."""
    return (
        isinstance(proposal_id, str)
        and len(proposal_id) == 32
        and all(c in "0123456789abcdef" for c in proposal_id)
    )


@dataclass
class Proposal:
    id: str
    cluster: str
    name: str
    summary: str
    manifests: list[dict[str, Any]]
    created_at: float
    content_hash: str = ""
    status: str = "pending"  # pending | applied | rolled_back | rejected
    applied_work: str = ""
    applied_uid: str = ""  # UID of the created ManifestWork, checked before rollback
    # "manifestwork" (deploy a bundle), "action" (OCM lifecycle), or "rollback".
    kind: str = "manifestwork"
    action: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    approved_by: str = ""  # the human recorded in the approval token that applied this
    schema_version: int = SCHEMA_VERSION

    def path(self) -> Path:
        if not _valid_id(self.id):
            raise ApprovalError(f"Invalid proposal id '{self.id}'.")
        return SETTINGS.proposals_dir / f"{self.id}.json"

    def save(self) -> None:
        """Write atomically (temp file + fsync + rename) under a lock, so concurrent
        writers can't interleave and a crash can't leave a torn file."""
        p = self.path()
        with locked(p):
            tmp = p.with_suffix(".json.tmp")
            with tmp.open("w") as f:
                f.write(json.dumps(asdict(self), indent=2, sort_keys=True))
                f.flush()
                os.fsync(f.fileno())
            tmp.chmod(0o600)
            tmp.replace(p)

    def set_status(self, new_status: str) -> None:
        """Advance to new_status only if the transition is legal, then persist."""
        if new_status != self.status and new_status not in _STATUS_TRANSITIONS.get(
            self.status, set()
        ):
            raise ApprovalError(
                f"Illegal proposal transition {self.status} -> {new_status} for '{self.id}'."
            )
        self.status = new_status
        self.save()


def content_hash(
    cluster: str,
    name: str,
    manifests: list[dict[str, Any]],
    kind: str = "manifestwork",
    action: str = "",
    params: dict[str, Any] | None = None,
) -> str:
    """A token binds to this hash. Changing any field below invalidates approval."""
    canonical = json.dumps(
        {
            "cluster": cluster,
            "name": name,
            "manifests": manifests,
            "kind": kind,
            "action": action,
            "params": params or {},
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def new_proposal(
    cluster: str, name: str, summary: str, manifests: list[dict[str, Any]]
) -> Proposal:
    prop = Proposal(
        id=uuid.uuid4().hex,
        cluster=cluster,
        name=name,
        summary=summary,
        manifests=manifests,
        created_at=time.time(),
        kind="manifestwork",
    )
    prop.content_hash = content_hash(cluster, name, manifests, kind="manifestwork")
    prop.save()
    return prop


def new_action_proposal(
    cluster: str, action: str, summary: str, params: dict[str, Any]
) -> Proposal:
    """A proposed OCM lifecycle action (cordon/uncordon/set_label/accept) awaiting approval."""
    prop = Proposal(
        id=uuid.uuid4().hex,
        cluster=cluster,
        name=f"{action}-{cluster}",
        summary=summary,
        manifests=[],
        created_at=time.time(),
        kind="action",
        action=action,
        params=params,
    )
    prop.content_hash = content_hash(
        cluster, prop.name, [], kind="action", action=action, params=params
    )
    prop.save()
    return prop


_FIELDS = {f for f in Proposal.__dataclass_fields__}  # type: ignore[attr-defined]


def _from_json(raw: str) -> Proposal:
    """Build a Proposal from stored JSON, ignoring keys this version doesn't know
    (forward compatibility) so a newer file can't crash an older reader."""
    data = {k: v for k, v in json.loads(raw).items() if k in _FIELDS}
    return Proposal(**data)


def load_proposal(proposal_id: str) -> Proposal:
    if not _valid_id(proposal_id):
        raise ApprovalError(f"Invalid proposal id '{proposal_id}'.")
    path = SETTINGS.proposals_dir / f"{proposal_id}.json"
    if not path.exists():
        raise ApprovalError(f"No proposal with id '{proposal_id}'.")
    return _from_json(path.read_text())


def list_proposals(status: str = "") -> list[Proposal]:
    out = []
    for path in sorted(SETTINGS.proposals_dir.glob("*.json")):
        prop = _from_json(path.read_text())
        if not status or prop.status == status:
            out.append(prop)
    return out


def proposal_lock(proposal_id: str):
    """Serialize the whole apply of one proposal so two concurrent applies (even with two
    separately minted valid tokens) can't both pass the pending-status check and both
    write. Uses a distinct `.apply` lock file so it never nests with save()'s own lock."""
    if not _valid_id(proposal_id):
        raise ApprovalError(f"Invalid proposal id '{proposal_id}'.")
    return locked(SETTINGS.proposals_dir / f"{proposal_id}.apply")


def new_rollback_proposal(applied: Proposal, summary: str) -> Proposal:
    """A distinct, approvable proposal to roll back an already-applied ManifestWork.

    It binds the exact ManifestWork name and UID recorded at apply time, so an old
    apply token can never authorize a rollback and the rollback targets exactly the
    object the human approved.
    """
    params = {
        "target_work": applied.applied_work,
        "target_uid": applied.applied_uid,
        "origin": applied.id,
    }
    prop = Proposal(
        id=uuid.uuid4().hex,
        cluster=applied.cluster,
        name=f"rollback-{applied.applied_work}",
        summary=summary,
        manifests=[],
        created_at=time.time(),
        kind="rollback",
        params=params,
    )
    prop.content_hash = content_hash(applied.cluster, prop.name, [], kind="rollback", params=params)
    prop.save()
    return prop


def intended_operation(prop: Proposal) -> str:
    """The operation a token for this proposal authorizes: 'rollback' or 'apply'."""
    return "rollback" if prop.kind == "rollback" else "apply"


# --------------------------------------------------------------- asymmetric tokens


def _private_key() -> Ed25519PrivateKey:
    """The signing key. Held by the human side (ocm-mcp CLI); the server must not call this."""
    path = SETTINGS.approval_private_key_path
    if path.exists():
        return Ed25519PrivateKey.from_private_bytes(bytes.fromhex(path.read_text().strip()))
    SETTINGS.home.mkdir(parents=True, exist_ok=True)
    key = Ed25519PrivateKey.generate()
    path.write_text(key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption()).hex())
    path.chmod(0o600)
    pub = SETTINGS.approval_public_key_path
    pub.write_text(key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex())
    pub.chmod(0o644)
    return key


def _verifier_keys() -> list[Ed25519PublicKey]:
    """The verification key(s) the server accepts. During rotation the retired public
    key is kept as `.pub.prev` so tokens minted just before rotation still verify until
    they expire; a hard cutover would reject valid, in-flight approvals."""
    keys = []
    for path in (SETTINGS.approval_public_key_path, SETTINGS.previous_public_key_path):
        if path.exists():
            keys.append(Ed25519PublicKey.from_public_bytes(bytes.fromhex(path.read_text().strip())))
    if not keys:
        raise ApprovalError("No approval key is configured; no token can be valid.")
    return keys


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _load_used(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if line:
                with contextlib.suppress(ValueError):
                    out.append(json.loads(line))
    return out


def _token_used(jti: str) -> bool:
    return any(e.get("jti") == jti for e in _load_used(SETTINGS.used_tokens_path))


# Compact the spent-token ledger once it grows past this many lines, dropping expired
# entries. The common path is an O(1) append; compaction (a full rewrite) is rare.
_LEDGER_COMPACT_AT = 2000


def _mark_token_used(claims: dict[str, Any]) -> None:
    """Record a token id as spent, so it can never be replayed.

    The common case appends one line (O(1) write). Only when the ledger grows past
    `_LEDGER_COMPACT_AT` lines is it rewritten, dropping entries whose token has already
    expired - so it stays bounded without a full rewrite on every apply. A spent id only
    needs to be remembered until its token's expiry.
    """
    path = SETTINGS.used_tokens_path
    now = int(time.time())
    entry = {
        "jti": claims.get("jti"),
        "id": claims.get("id"),
        "op": claims.get("op"),
        "exp": int(claims.get("exp", now)),
        "used_at": now,
    }
    with locked(path):
        used = _load_used(path)
        if any(e.get("jti") == claims.get("jti") for e in used):
            raise ApprovalError("This approval token has already been used (replay refused).")
        if len(used) >= _LEDGER_COMPACT_AT:
            kept = [e for e in used if int(e.get("exp", now)) > now]
            kept.append(entry)
            tmp = path.with_suffix(".jsonl.tmp")
            with tmp.open("w") as f:
                for e in kept:
                    f.write(json.dumps(e, separators=(",", ":")) + "\n")
                f.flush()
                os.fsync(f.fileno())
            tmp.chmod(0o600)
            tmp.replace(path)
        else:
            with path.open("a") as f:
                f.write(json.dumps(entry, separators=(",", ":")) + "\n")
                f.flush()
                os.fsync(f.fileno())


def mint_token(
    prop: Proposal,
    operation: str | None = None,
    ttl_seconds: int | None = None,
    approver: str = "",
) -> str:
    """Sign an approval token. Called by the CLI (a human), never by any MCP tool."""
    now = int(time.time())
    claims = {
        "jti": uuid.uuid4().hex,
        "iss": SETTINGS.issuer,
        "aud": SETTINGS.audience,
        "id": prop.id,
        "hash": prop.content_hash,
        "op": operation or intended_operation(prop),
        "approver": approver or os.environ.get("USER", ""),
        "iat": now,
        "nbf": now,
        "exp": now + (ttl_seconds or SETTINGS.approval_ttl_seconds),
    }
    payload = json.dumps(claims, sort_keys=True, separators=(",", ":")).encode()
    return _b64(payload) + "." + _b64(_private_key().sign(payload))


def verify_token(
    prop: Proposal, token: str, operation: str = "apply", consume: bool = False
) -> dict[str, Any]:
    """Raise ApprovalError unless the token is a valid signature over this exact proposal
    content AND authorizes the given operation ('apply' or 'rollback'). Returns the claims.

    When consume=True (the apply path), the token id is recorded as spent under a lock, so
    the same approval can never be replayed; a token already spent is refused. The apply
    tools consume before the cluster write, so a transient write failure spends the token
    (fail-safe: never risk a replay). The proposal stays pending, so the operator simply
    re-approves to mint a fresh token - a deliberate trade of convenience for safety.
    """
    try:
        payload_b64, sig_b64 = token.strip().split(".")
        payload, sig = _unb64(payload_b64), _unb64(sig_b64)
    except Exception as exc:  # any parse/decode failure means the token is malformed
        raise ApprovalError("Malformed approval token.") from exc
    if not any(_verify_sig(k, sig, payload) for k in _verifier_keys()):
        raise ApprovalError("Invalid approval token signature.")
    try:
        claims = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ApprovalError("Malformed approval token.") from exc
    if claims.get("iss") != SETTINGS.issuer:
        raise ApprovalError("Approval token issuer does not match this deployment.")
    if claims.get("aud") != SETTINGS.audience:
        raise ApprovalError("Approval token audience does not match this deployment.")
    if claims.get("id") != prop.id:
        raise ApprovalError("Token was minted for a different proposal.")
    if claims.get("hash") != prop.content_hash:
        raise ApprovalError(
            "Invalid approval token (content mismatch - the proposal may have changed)."
        )
    if claims.get("op") != operation:
        raise ApprovalError(f"This token authorizes '{claims.get('op')}', not '{operation}'.")
    now = time.time()
    if now < claims.get("nbf", 0):
        raise ApprovalError("Approval token is not yet valid (nbf in the future).")
    if now > claims.get("exp", 0):
        raise ApprovalError("Approval token has expired; request a fresh approval.")
    if _token_used(claims.get("jti", "")):
        raise ApprovalError("This approval token has already been used (replay refused).")
    if consume:
        _mark_token_used(claims)
    return claims


def _verify_sig(key: Ed25519PublicKey, sig: bytes, payload: bytes) -> bool:
    try:
        key.verify(sig, payload)
        return True
    except InvalidSignature:
        return False
