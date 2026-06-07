"""``omoikane list`` — enumerate known projects from the SQLite index."""
from __future__ import annotations

import argparse
import json


def add_subparser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--json", action="store_true",
        help="Emit a JSON array instead of the aligned text table.",
    )
    parser.add_argument(
        "--status", choices=[
            "created", "in_progress", "review", "done", "failed", "cancelled",
        ],
        help="Filter rows by project status.",
    )


def run(args: argparse.Namespace) -> int:
    from omoikane.core.project_index import ProjectIndex

    rows = ProjectIndex().list_projects()
    if args.status:
        rows = [r for r in rows if r.get("status") == args.status]

    if args.json:
        print(json.dumps(rows, indent=2))
        return 0

    if not rows:
        print("(no projects)")
        return 0

    fmt = "{id:<32}  {status:<12}  {phase:<14}  {title}"
    print(fmt.format(id="id", status="status", phase="phase", title="title"))
    print("-" * 100)
    for row in rows:
        print(fmt.format(
            id=str(row.get("id") or "")[:32],
            status=str(row.get("status") or ""),
            phase=str(row.get("current_phase") or ""),
            title=str(row.get("title") or "")[:60],
        ))
    return 0
