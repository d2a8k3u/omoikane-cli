"""``omoikane inject`` — append a message to a project's inbox.jsonl."""
from __future__ import annotations

import argparse
import sys

from omoikane.runtime.injection import (
    BROADCAST_TARGET,
    CTO_TARGET,
    write_message,
)


def add_subparser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("project_id", help="Project identifier (proj-...).")
    parser.add_argument(
        "--target", default=CTO_TARGET,
        help=(
            "Inject target. Accepts a role name (default: 'agent-cto'), "
            "'task:<id>' for a specific specialist task, or '*' to broadcast."
        ),
    )
    parser.add_argument(
        "content", nargs="+",
        help="The message body. Joined with spaces; pipe stdin with `-` to read.",
    )


def run(args: argparse.Namespace) -> int:
    parts = args.content
    if parts == ["-"]:
        text = sys.stdin.read().strip()
    else:
        text = " ".join(parts).strip()
    if not text:
        print("empty message — nothing to inject", file=sys.stderr)
        return 1

    try:
        msg_id = write_message(args.project_id, text, target=args.target)
    except FileNotFoundError as exc:
        print(f"failed to write inbox: {exc}", file=sys.stderr)
        return 1

    print(f"inject queued: msg_id={msg_id} target={args.target}")
    return 0
