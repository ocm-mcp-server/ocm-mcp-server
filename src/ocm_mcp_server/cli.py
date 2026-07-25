# SPDX-FileCopyrightText: 2026 Sandeep Bazar
# SPDX-License-Identifier: Apache-2.0

"""ocm-mcp: the human side of the approval flow.

Run on a trusted terminal, never by the agent:

    ocm-mcp pending                 list proposals waiting for approval
    ocm-mcp show <id>               print the full manifests of a proposal
    ocm-mcp approve <id>            review + mint an approval token
    ocm-mcp reject <id>             mark a proposal rejected
    ocm-mcp audit [-n 20]           tail the tool-call audit log
    ocm-mcp doctor                  live read-path smoke test against the hub
    ocm-mcp rotate-secret           mint a new HMAC key (invalidates all tokens)
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


def cmd_rotate_secret(args: argparse.Namespace) -> int:
    if not args.yes:
        print(
            "Rotating the HMAC key invalidates ALL previously minted approval tokens; "
            "any pending proposal must be approved again."
        )
        if input("Rotate now? [y/N] ").strip().lower() != "y":
            print("Not rotated.")
            return 1
    SETTINGS.rotate_secret()
    print("Rotated. Previously minted approval tokens are now invalid.")
    return 0


def cmd_doctor(_args: argparse.Namespace) -> int:
    """Exercise every read tool against the live hub and print a PASS/EMPTY/SKIP/FAIL table.

    Writes nothing. This is the fastest way to confirm the server can actually see
    a real Open Cluster Management / ACM-MCE fleet before wiring an agent to it.
    """
    from . import ocm  # local import: pulls in the kubernetes client only when needed

    ctx = SETTINGS.hub_context or "(current kubeconfig context)"
    print(f"ocm-mcp doctor - live read-path smoke test\nhub context: {ctx}\n")

    counts = {"OK": 0, "EMPTY": 0, "SKIP": 0, "FAIL": 0}

    def run(label: str, fn) -> object | None:
        try:
            result = fn()
        except LookupError as exc:
            # no spoke context configured, or an optional add-on / CRD not installed
            print(f"  [SKIP]  {label:32s} {str(exc)[:70]}")
            counts["SKIP"] += 1
            return None
        except Exception as exc:  # noqa: BLE001 - doctor must never abort on one check
            print(f"  [FAIL]  {label:32s} {type(exc).__name__}: {str(exc)[:64]}")
            counts["FAIL"] += 1
            return None
        empty = result in ([], {}, None, "")
        status, detail = ("EMPTY", "no items") if empty else ("OK", _detail(result))
        counts[status] += 1
        print(f"  [{status:5s}] {label:32s} {detail}")
        return None if empty else result

    # Hub-level reads (no arguments).
    run("list_clusters", ocm.list_managed_clusters)
    run("list_cluster_sets", ocm.list_cluster_sets)
    run("list_cluster_set_bindings", ocm.list_cluster_set_bindings)
    run("list_cluster_claims", ocm.list_cluster_claims)
    run("list_placements", ocm.list_placements)
    run("list_manifestworkreplicasets", ocm.list_manifestworkreplicasets)
    run("list_cluster_management_addons", ocm.list_cluster_management_addons)
    run("get_addon_health", ocm.addon_health)
    run("list_pending_csrs", ocm.list_pending_csrs)
    run("list_policies", ocm.list_policies)
    if hasattr(ocm, "list_hosted_clusters"):
        run("list_hosted_clusters", ocm.list_hosted_clusters)
    if hasattr(ocm, "list_policy_violations"):
        run("list_policy_violations", ocm.list_policy_violations)

    # Per-cluster reads: sample the first cluster we can see.
    clusters = []
    try:
        clusters = ocm.list_managed_clusters()
    except Exception:  # noqa: BLE001 - sampling is best-effort; failures already reported above
        clusters = []
    if clusters:
        c = clusters[0]["name"]
        print(f"\n  sample cluster: {c}")
        run(f"get_cluster({c})", lambda: ocm.get_managed_cluster(c))
        run(f"get_cluster_health({c})", lambda: ocm.cluster_health(c))
        run(f"list_manifestworks({c})", lambda: ocm.list_manifestworks(c))
        run(f"list_addon_placement_scores({c})", lambda: ocm.list_addon_placement_scores(c))
        if hasattr(ocm, "get_cluster_info"):
            run(f"get_cluster_info({c})", lambda: ocm.get_cluster_info(c))
        if hasattr(ocm, "list_addons_for_cluster"):
            run(f"list_addons_for_cluster({c})", lambda: ocm.list_addons_for_cluster(c))

    print(
        f"\nSummary: {counts['OK']} ok, {counts['EMPTY']} empty, "
        f"{counts['SKIP']} skipped, {counts['FAIL']} failed."
    )
    if counts["FAIL"]:
        print("A FAIL means the hub returned an error for that call - check RBAC and the CRD.")
    return 1 if counts["FAIL"] else 0


def _detail(result: object) -> str:
    if isinstance(result, list):
        return f"{len(result)} item(s)"
    if isinstance(result, dict):
        keys = [k for k in ("name", "cluster", "available", "conditions") if k in result]
        if keys:
            return ", ".join(f"{k}={result[k]}" for k in keys[:2])
        return f"{len(result)} field(s)"
    return str(result)[:60]


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

    sub.add_parser("doctor").set_defaults(func=cmd_doctor)

    p_rotate = sub.add_parser("rotate-secret")
    p_rotate.add_argument("-y", "--yes", action="store_true", help="skip confirmation prompt")
    p_rotate.set_defaults(func=cmd_rotate_secret)

    args = parser.parse_args()
    raise SystemExit(args.func(args))


if __name__ == "__main__":
    main()
