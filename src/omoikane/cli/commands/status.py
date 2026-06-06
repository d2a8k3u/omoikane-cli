"""``omoikane status <project_id>`` — print Book + phase summary."""
from __future__ import annotations

import argparse
import json
import sys


def add_subparser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("project_id", help="Project identifier (proj-...).")
    parser.add_argument(
        "--json", action="store_true",
        help="Print the full Book JSON instead of the short human summary.",
    )


def run(args: argparse.Namespace) -> int:
    from omoikane.core.book import ProjectBook

    try:
        book = ProjectBook(args.project_id)
        data = book.load()
    except FileNotFoundError:
        print(f"project not found: {args.project_id}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(data, indent=2))
        return 0

    print(f"Project {args.project_id}")
    print(f"  title:   {data.get('title')}")
    print(f"  status:  {data.get('status')}")
    print(f"  phase:   {data.get('current_phase')}")
    print(f"  open tasks:      {len(data.get('open_tasks') or [])}")
    print(f"  completed tasks: {len(data.get('completed_tasks') or [])}")
    criteria = data.get("acceptance_criteria") or []
    status = data.get("criteria_status") or {}
    satisfied = sum(1 for v in status.values() if v == "satisfied")
    print(f"  criteria: {satisfied}/{len(criteria)} satisfied")
    last = data.get("last_activity")
    if last:
        print(f"  last activity: {last}")
    origin = data.get("origin") or {}
    if origin.get("platform"):
        chat = origin.get("chat_id") or "-"
        print(f"  origin: {origin['platform']}:{chat}")
    return 0
