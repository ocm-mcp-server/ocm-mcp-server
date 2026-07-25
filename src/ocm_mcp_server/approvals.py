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
import hashlib
import json
import time
import uuid
from dataclasses import asdict, dataclass, field
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


class ApprovalError(Exception):
    """Raised when an approval token is missing, expired, or invalid."""


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

    def path(self):
        return SETTINGS.proposals_dir / f"{self.id}.json"

    def save(self) -> None:
        """Write atomically (temp file + rename) so a crash can't corrupt a proposal."""
        p = self.path()
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2, sort_keys=True))
        tmp.replace(p)


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


def load_proposal(proposal_id: str) -> Proposal:
    path = SETTINGS.proposals_dir / f"{proposal_id}.json"
    if not path.exists():
        raise ApprovalError(f"No proposal with id '{proposal_id}'.")
    return Proposal(**json.loads(path.read_text()))


def list_proposals(status: str = "") -> list[Proposal]:
    out = []
    for path in sorted(SETTINGS.proposals_dir.glob("*.json")):
        prop = Proposal(**json.loads(path.read_text()))
        if not status or prop.status == status:
            out.append(prop)
    return out


def new_rollback_proposal(applied: Proposal, summary: str) -> Proposal:
    """A distinct, approvable proposal to roll back an already-applied ManifestWork.

    It binds the exact ManifestWork name and UID recorded at apply time, so an old
    apply token can never authorize a rollback and the rollback targets exactly the
    object the human approved.
    """
    params = {"target_work": applied.applied_work, "target_uid": applied.applied_uid,
              "origin": applied.id}
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
    prop.content_hash = content_hash(
        applied.cluster, prop.name, [], kind="rollback", params=params
    )
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


def _public_key() -> Ed25519PublicKey:
    """The verification key. All the server needs - it can verify but never mint."""
    path = SETTINGS.approval_public_key_path
    if not path.exists():
        raise ApprovalError("No approval key is configured; no token can be valid.")
    return Ed25519PublicKey.from_public_bytes(bytes.fromhex(path.read_text().strip()))


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def mint_token(prop: Proposal, operation: str | None = None, ttl_seconds: int | None = None) -> str:
    """Sign an approval token. Called by the CLI (a human), never by any MCP tool."""
    claims = {
        "id": prop.id,
        "hash": prop.content_hash,
        "op": operation or intended_operation(prop),
        "exp": int(time.time()) + (ttl_seconds or SETTINGS.approval_ttl_seconds),
    }
    payload = json.dumps(claims, sort_keys=True, separators=(",", ":")).encode()
    return _b64(payload) + "." + _b64(_private_key().sign(payload))


def verify_token(prop: Proposal, token: str, operation: str = "apply") -> None:
    """Raise ApprovalError unless the token is a valid signature over this exact proposal
    content AND authorizes the given operation ('apply' or 'rollback')."""
    try:
        payload_b64, sig_b64 = token.strip().split(".")
        payload, sig = _unb64(payload_b64), _unb64(sig_b64)
    except Exception as exc:  # any parse/decode failure means the token is malformed
        raise ApprovalError("Malformed approval token.") from exc
    try:
        _public_key().verify(sig, payload)
    except InvalidSignature as exc:
        raise ApprovalError("Invalid approval token signature.") from exc
    try:
        claims = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ApprovalError("Malformed approval token.") from exc
    if claims.get("id") != prop.id:
        raise ApprovalError("Token was minted for a different proposal.")
    if claims.get("hash") != prop.content_hash:
        raise ApprovalError(
            "Invalid approval token (content mismatch - the proposal may have changed)."
        )
    if claims.get("op") != operation:
        raise ApprovalError(
            f"This token authorizes '{claims.get('op')}', not '{operation}'."
        )
    if time.time() > claims.get("exp", 0):
        raise ApprovalError("Approval token has expired; request a fresh approval.")
