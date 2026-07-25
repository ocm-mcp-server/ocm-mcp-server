# SPDX-FileCopyrightText: 2026 Sandeep Bazar <sandeepbazar@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Human approval flow for destructive actions.

Design:
- propose_manifestwork stores a proposal file (JSON) with a SHA-256 content hash.
- A human runs `ocm-mcp approve <id>` on a trusted terminal; the CLI prints an
  HMAC token bound to that exact content hash and an expiry timestamp.
- apply_manifestwork only succeeds when the token verifies against the stored
  proposal. Change one byte of the proposal and the token is useless.

The agent can request approval; it can never mint one. The HMAC key lives in
OCM_MCP_HOME/secret (0600), which the MCP server process reads but never
exposes through any tool.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from dataclasses import asdict, dataclass
from typing import Any

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

    def path(self):
        return SETTINGS.proposals_dir / f"{self.id}.json"

    def save(self) -> None:
        self.path().write_text(json.dumps(asdict(self), indent=2, sort_keys=True))


def content_hash(cluster: str, name: str, manifests: list[dict[str, Any]]) -> str:
    canonical = json.dumps(
        {"cluster": cluster, "name": name, "manifests": manifests},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def new_proposal(
    cluster: str, name: str, summary: str, manifests: list[dict[str, Any]]
) -> Proposal:
    prop = Proposal(
        id=uuid.uuid4().hex[:8],
        cluster=cluster,
        name=name,
        summary=summary,
        manifests=manifests,
        created_at=time.time(),
    )
    prop.content_hash = content_hash(cluster, name, manifests)
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


def _token_payload(prop: Proposal, expires_at: int) -> bytes:
    return f"{prop.id}:{prop.content_hash}:{expires_at}".encode()


def mint_token(prop: Proposal, ttl_seconds: int | None = None) -> str:
    """Called by the CLI (a human), never by any MCP tool."""
    expires_at = int(time.time()) + (ttl_seconds or SETTINGS.approval_ttl_seconds)
    sig = hmac.new(SETTINGS.secret(), _token_payload(prop, expires_at), hashlib.sha256)
    return f"{prop.id}.{expires_at}.{sig.hexdigest()}"


def verify_token(prop: Proposal, token: str) -> None:
    """Raises ApprovalError unless the token matches this exact proposal content."""
    try:
        token_id, expires_str, sig = token.strip().split(".")
        expires_at = int(expires_str)
    except ValueError as exc:
        raise ApprovalError("Malformed approval token.") from exc
    if token_id != prop.id:
        raise ApprovalError("Token was minted for a different proposal.")
    if time.time() > expires_at:
        raise ApprovalError("Approval token has expired; request a fresh approval.")
    expected = hmac.new(
        SETTINGS.secret(), _token_payload(prop, expires_at), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, sig):
        raise ApprovalError(
            "Invalid approval token (content mismatch - the proposal may have changed)."
        )
