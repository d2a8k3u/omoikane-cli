"""``omoikane stop <pid>`` — send SIGTERM to a running daemon."""
from __future__ import annotations

import argparse
import sys

from omoikane.orchestrator import daemon as _daemon


def add_subparser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("project_id", help="Project identifier (proj-...).")
    parser.add_argument(
        "--timeout", type=float, default=10.0,
        help="Seconds to wait for the daemon to exit (default: 10).",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Escalate to SIGKILL after the timeout elapses.",
    )


def run(args: argparse.Namespace) -> int:
    snapshot = _daemon.status(args.project_id)
    if snapshot.state == "missing":
        print(f"no daemon registered for {args.project_id}")
        return 0
    if snapshot.state in {"stale", "gone"}:
        print(f"daemon pid {snapshot.pid} no longer alive; cleaning pidfile")
    ok = _daemon.OrchestratorDaemon.stop(
        args.project_id, timeout=args.timeout, force=args.force,
    )
    if not ok:
        print(
            f"timed out waiting for daemon (pid={snapshot.pid}); retry with --force",
            file=sys.stderr,
        )
        return 2
    print(f"stopped daemon for {args.project_id}")
    return 0
