# SPDX-FileCopyrightText: 2026 Sandeep Bazar
# SPDX-License-Identifier: Apache-2.0

"""ocm-mcp: the human side of the approval flow.

Run on a trusted terminal, never by the agent:

    ocm-mcp pending                 list proposals waiting for approval
    ocm-mcp show <id>               print the full manifests of a proposal
    ocm-mcp approve <id>            review + mint an approval token
    ocm-mcp reject <id>             mark a proposal rejected
    ocm-mcp audit [-n 20]           tail the tool-call audit log
"""

from __future__ import annotations

import argparse
import json
import sys

from . import approvals
from .config import SETTINGS


def cmd_pending(_args: argparse.Namespace) -> int:
    pending = approvals.list_proposals(status="pending")
    if not pending:
        print("No pending proposals.")
        return 0
    for p in pending:
        kind = p.action if p.kind == "action" else "manifestwork"
        print(f"  {p.id}  cluster={p.cluster}  kind={kind}  name={p.name}")
        print(f"          {p.summary}")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    prop = approvals.load_proposal(args.id)
    print(f"id:       {prop.id}")
    print(f"cluster:  {prop.cluster}")
    print(f"name:     {prop.name}")
    print(f"status:   {prop.status}")
    print(f"summary:  {prop.summary}")
    if prop.kind == "action":
        print(f"action:   {prop.action}")
        print(f"params:   {json.dumps(prop.params)}")
    else:
        print("manifests:")
        print(json.dumps(prop.manifests, indent=2))
    return 0


def cmd_approve(args: argparse.Namespace) -> int:
    prop = approvals.load_proposal(args.id)
    if prop.status != "pending":
        print(f"Proposal {prop.id} is '{prop.status}', not pending.", file=sys.stderr)
        return 1
    if not args.yes:
        print(f"About to approve on cluster '{prop.cluster}': {prop.summary}")
        print(f"Review full manifests first with: ocm-mcp show {prop.id}")
        answer = input("Approve? [y/N] ").strip().lower()
        if answer != "y":
            print("Not approved.")
            return 1
    token = approvals.mint_token(prop)
    print("Approval token (give this to the agent):")
    print(token)
    return 0


def cmd_reject(args: argparse.Namespace) -> int:
    prop = approvals.load_proposal(args.id)
    prop.status = "rejected"
    prop.save()
    print(f"Proposal {prop.id} rejected.")
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    path = SETTINGS.audit_log
    if not path.exists():
        print("No audit log yet.")
        return 0
    lines = path.read_text().strip().splitlines()[-args.n :]
    for line in lines:
        entry = json.loads(line)
        print(
            f'{entry.get("ts", 0):.0f}  {entry.get("tool", "?"):24s} '
            f'{entry.get("outcome", "?"):5s} {entry.get("duration_ms", 0):>6}ms  '
            f'{entry.get("error", "")[:80]}'
        )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(prog="ocm-mcp", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("pending").set_defaults(func=cmd_pending)

    p_show = sub.add_parser("show")
    p_show.add_argument("id")
    p_show.set_defaults(func=cmd_show)

    p_approve = sub.add_parser("approve")
    p_approve.add_argument("id")
    p_approve.add_argument("-y", "--yes", action="store_true", help="skip confirmation prompt")
    p_approve.set_defaults(func=cmd_approve)

    p_reject = sub.add_parser("reject")
    p_reject.add_argument("id")
    p_reject.set_defaults(func=cmd_reject)

    p_audit = sub.add_parser("audit")
    p_audit.add_argument("-n", type=int, default=20)
    p_audit.set_defaults(func=cmd_audit)

    args = parser.parse_args()
    raise SystemExit(args.func(args))


if __name__ == "__main__":
    main()
