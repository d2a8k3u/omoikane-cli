"""``omoikane approvals list|approve|deny`` — operator-facing approval flow.

Approvals live inside ``book.json`` under ``pending_approvals`` and
``approved_commands``. The Phase-6 CLI fronts the same surface the TUI
ApprovalsPane consumes, so an operator can resolve pending requests
without launching the TUI.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Dict, Iterable, List


def add_subparser(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="approvals_command", required=True)

    list_p = sub.add_parser("list", help="List pending approvals across projects.")
    list_p.add_argument(
        "project_id", nargs="?",
        help="Restrict listing to one project; omit to scan every active project.",
    )
    list_p.add_argument("--json", action="store_true", help="Emit JSON.")

    for action in ("approve", "deny"):
        p = sub.add_parser(action, help=f"{action.title()} a pending approval.")
        p.add_argument("project_id")
        p.add_argument("approval_id")
        p.add_argument(
            "--note", default="",
            help=(
                "Reason recorded in the Book and (for approve) appended to the "
                "command's allowlist entry."
            ),
        )


def run(args: argparse.Namespace) -> int:
    cmd = args.approvals_command
    if cmd == "list":
        return _cmd_list(args)
    if cmd == "approve":
        return _cmd_resolve(args, decision="approve")
    if cmd == "deny":
        return _cmd_resolve(args, decision="deny")
    raise SystemExit(f"unknown approvals subcommand: {cmd}")


def _cmd_list(args: argparse.Namespace) -> int:
    rows = list(_iter_pending(args.project_id))
    if args.json:
        print(json.dumps(rows, indent=2))
        return 0
    if not rows:
        print("(no pending approvals)")
        return 0
    fmt = "{pid:<32}  {aid:<10}  {role:<22}  {action:<18}  {summary}"
    print(fmt.format(
        pid="project", aid="approval", role="requester",
        action="action", summary="command",
    ))
    print("-" * 110)
    for row in rows:
        print(fmt.format(
            pid=row["project_id"],
            aid=row["approval_id"],
            role=row["requester_role"] or "-",
            action=row["action"] or "-",
            summary=(row["command"] or row["reason"] or "")[:60],
        ))
    return 0


def _cmd_resolve(args: argparse.Namespace, *, decision: str) -> int:
    from omoikane.core.book import ProjectBook

    try:
        book = ProjectBook(args.project_id)
        book.load()
    except FileNotFoundError:
        print(f"project not found: {args.project_id}", file=sys.stderr)
        return 1
    try:
        entry = book.resolve_approval(
            approval_id=args.approval_id, decision=decision, note=args.note,
        )
    except ValueError as exc:
        print(f"failed to resolve approval: {exc}", file=sys.stderr)
        return 1
    if entry is None:
        print(
            f"approval {args.approval_id} not found in {args.project_id}",
            file=sys.stderr,
        )
        return 1
    print(f"{decision}d approval {args.approval_id} for project {args.project_id}")
    return 0


def _iter_pending(project_id_filter: str = None) -> Iterable[Dict[str, str]]:
    from omoikane.core.book import ProjectBook
    from omoikane.core.dashboard import DashboardProvider

    if project_id_filter:
        ids: List[str] = [project_id_filter]
    else:
        ids = [r["id"] for r in DashboardProvider().list_projects()]
    for pid in ids:
        try:
            data = ProjectBook(pid).load()
        except FileNotFoundError:
            continue
        for approval in data.get("pending_approvals") or []:
            if approval.get("status") and approval.get("status") != "pending":
                continue
            yield {
                "project_id": pid,
                "approval_id": approval.get("approval_id", "?"),
                "requester_role": approval.get("requester_role", ""),
                "action": approval.get("action", ""),
                "command": approval.get("command", ""),
                "reason": approval.get("reason", ""),
                "filed_at": approval.get("filed_at", ""),
            }
