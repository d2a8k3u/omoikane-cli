"""``omoikane delete-project <pid>`` — permanently remove a project.

Refuses while a daemon is live unless ``--force`` is given, in which case the
daemon is stopped (graceful SIGTERM) before deletion. A daemon owned by
another user (``unreachable``) is never overridden. Deletion removes the
on-disk project directory (book, activity, delegation, pidfile, logs) and the
SQLite index rows. Irreversible.
"""
from __future__ import annotations

import argparse
import sys

from omoikane.core import store as _store
from omoikane.orchestrator import daemon as _daemon


def add_subparser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("project_id", help="Project identifier (proj-...).")
    parser.add_argument(
        "-f", "--force", action="store_true",
        help="Skip the confirmation prompt and stop a running daemon (SIGTERM) first.",
    )


def run(args: argparse.Namespace) -> int:
    pid = args.project_id

    snap = _daemon.status(pid)
    if snap.state == "unreachable":
        # Owned by another user / no permission to signal — we cannot stop it,
        # so --force can't help either. Refuse rather than delete under a live
        # process we don't control.
        print(
            f"daemon for {pid} is unreachable (pid={snap.pid}); cannot delete safely.",
            file=sys.stderr,
        )
        return 1
    if snap.state == "running":
        if not args.force:
            print(
                f"daemon for {pid} is running (pid={snap.pid}); stop it first: "
                f"omoikane stop {pid}  (or pass --force to stop it and delete)",
                file=sys.stderr,
            )
            return 1
        # --force: stop the daemon (graceful SIGTERM) before deleting.
        if not _daemon.OrchestratorDaemon.stop(pid, timeout=10.0, force=False):
            print(
                f"--force could not stop the daemon (pid={snap.pid}); stop it "
                f"manually: omoikane stop {pid} --force",
                file=sys.stderr,
            )
            return 1
        print(f"stopped daemon for {pid}", file=sys.stderr)

    if not _store.project_exists(pid):
        print(f"project not found: {pid}", file=sys.stderr)
        return 1

    if not args.force:
        if not sys.stdin.isatty():
            print(
                f"refusing to delete {pid} without --force (no interactive terminal).",
                file=sys.stderr,
            )
            return 1
        reply = input(f"Permanently delete {pid} and all its data? [y/N] ").strip().lower()
        if reply not in {"y", "yes"}:
            print("aborted.")
            return 0

    try:
        _store.delete_project(pid)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"deleted project {pid}")
    return 0
