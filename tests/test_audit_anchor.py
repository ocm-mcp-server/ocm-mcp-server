# SPDX-FileCopyrightText: 2026 Sandeep Bazar
# SPDX-License-Identifier: Apache-2.0

"""Signed audit-chain anchors: the defense the bare hash chain cannot provide.

The hash chain detects edits in the middle of the log but not tail truncation
or a full rewrite by someone who recomputes every hash. Anchors close that:
the chain head is signed with the off-box approval key, so the log must keep
extending every anchored head.
"""

from __future__ import annotations

import json

import pytest

from ocm_mcp_server.approvals import ApprovalError
from ocm_mcp_server.config import SETTINGS
from ocm_mcp_server.tracing import (
    anchor_audit_chain,
    audit,
    verify_audit_anchors,
    verify_audit_chain,
)


def _seed_log(n: int = 3) -> None:
    for i in range(n):
        audit({"tool": f"tool_{i}", "args": {}, "outcome": "ok", "error": "", "duration_ms": 1})


def test_anchor_then_verify_round_trip(tmp_home) -> None:
    _seed_log(3)
    anchor = anchor_audit_chain()
    assert anchor["seq"] == 3
    ok, msg = verify_audit_anchors()
    assert ok
    assert "1 anchor(s) verified" in msg
    assert "last anchored seq 3" in msg


def test_no_anchors_yet_is_informational_not_failure(tmp_home) -> None:
    _seed_log(1)
    ok, msg = verify_audit_anchors()
    assert ok
    assert "no anchors recorded yet" in msg


def test_anchor_empty_log_refused(tmp_home) -> None:
    with pytest.raises(ApprovalError, match="no entries"):
        anchor_audit_chain()


def test_tail_truncation_detected(tmp_home) -> None:
    _seed_log(3)
    anchor_audit_chain()
    _seed_log(2)  # seq 4, 5 - then an attacker deletes them AND the anchored seq 3
    anchor_audit_chain()  # anchored at seq 5
    lines = SETTINGS.audit_log.read_text().strip().splitlines()
    SETTINGS.audit_log.write_text("\n".join(lines[:4]) + "\n")  # drop seq 5
    ok, _ = verify_audit_chain()
    assert ok  # the bare chain is blind to tail truncation...
    anchors_ok, msg = verify_audit_anchors()
    assert not anchors_ok  # ...the anchors are not
    assert "truncated or rewritten" in msg


def test_wholesale_rewrite_detected(tmp_home) -> None:
    _seed_log(2)
    anchor_audit_chain()
    SETTINGS.audit_log.write_text("")  # attacker rewrites the log from scratch
    _seed_log(2)  # same seq numbers, different content and hashes
    ok, _ = verify_audit_chain()
    assert ok  # the rewritten chain is internally consistent...
    anchors_ok, msg = verify_audit_anchors()
    assert not anchors_ok  # ...but no longer matches the signed head
    assert "seq 2" in msg


def test_tampered_anchor_signature_detected(tmp_home) -> None:
    _seed_log(1)
    anchor = anchor_audit_chain()
    forged = dict(anchor, seq=999, hash="0" * 64)
    SETTINGS.audit_anchors_path.write_text(json.dumps(forged) + "\n")
    ok, msg = verify_audit_anchors()
    assert not ok
    assert "invalid signature" in msg


def test_corrupt_anchor_file_detected(tmp_home) -> None:
    _seed_log(1)
    anchor_audit_chain()
    SETTINGS.audit_anchors_path.write_text("not json\n")
    ok, msg = verify_audit_anchors()
    assert not ok
    assert "corrupt" in msg


def test_blank_lines_in_log_and_anchor_file_ignored(tmp_home) -> None:
    _seed_log(2)
    anchor_audit_chain()
    with SETTINGS.audit_log.open("a") as f:
        f.write("\n\n")
    with SETTINGS.audit_anchors_path.open("a") as f:
        f.write("\n\n")
    ok, msg = verify_audit_anchors()
    assert ok
    assert "1 anchor(s) verified" in msg


def test_cli_audit_anchor_and_verify(tmp_home, capsys) -> None:
    from ocm_mcp_server import cli

    _seed_log(2)
    assert cli.cmd_audit_anchor(None) == 0
    assert "anchored audit chain head: seq 2" in capsys.readouterr().out
    assert cli.cmd_audit_verify(None) == 0
    out = capsys.readouterr().out
    assert "audit chain intact" in out
    assert "1 anchor(s) verified" in out


def test_cli_audit_verify_fails_on_broken_anchor(tmp_home, capsys) -> None:
    from ocm_mcp_server import cli

    _seed_log(2)
    anchor_audit_chain()
    lines = SETTINGS.audit_log.read_text().strip().splitlines()
    SETTINGS.audit_log.write_text(lines[0] + "\n")  # truncate below the anchored head
    assert cli.cmd_audit_verify(None) == 1


def test_cli_audit_anchor_empty_log(tmp_home, capsys) -> None:
    from ocm_mcp_server import cli

    assert cli.cmd_audit_anchor(None) == 1
    assert "no entries" in capsys.readouterr().err
