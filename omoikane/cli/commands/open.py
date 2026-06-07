"""``omoikane open <pid>`` — attach the TUI to a running project."""
from __future__ import annotations

import argparse
import os
import sys
from typing import Optional

from omoikane.orchestrator import daemon as _daemon
from omoikane.runtime.agent_run import RunConfig


def add_subparser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("project_id", help="Project identifier (proj-...).")
    parser.add_argument(
        "--start-if-stopped", action="store_true",
        help=(
            "When no daemon is running, start one in detached mode before "
            "launching the TUI. Requires an API key in the environment."
        ),
    )
    parser.add_argument(
        "--model", default=os.environ.get("OMOIKANE_MODEL", "openrouter/owl-alpha"),
        help="Model id used if --start-if-stopped fires.",
    )
    parser.add_argument(
        "--provider", default=os.environ.get("OMOIKANE_PROVIDER", "openrouter"),
    )
    parser.add_argument(
        "--poll-interval", type=float, default=1.0,
        help="Polling cadence (seconds) for activity / book refresh.",
    )


def _resolve_api_key() -> Optional[str]:
    for key in ("OMOIKANE_API_KEY", "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY"):
        if os.environ.get(key):
            return os.environ[key]
    return None


def run(args: argparse.Namespace) -> int:
    from omoikane.core.book import ProjectBook

    try:
        ProjectBook(args.project_id).load()
    except FileNotFoundError:
        print(f"project not found: {args.project_id}", file=sys.stderr)
        return 1

    snapshot = _daemon.status(args.project_id)
    if not snapshot.is_running and args.start_if_stopped:
        api_key = _resolve_api_key()
        if not api_key:
            print(
                "--start-if-stopped requires an API key; set OMOIKANE_API_KEY / "
                "OPENROUTER_API_KEY / ANTHROPIC_API_KEY first.",
                file=sys.stderr,
            )
            return 1
        config = RunConfig(model=args.model, api_key=api_key, provider=args.provider)
        try:
            pid = _daemon.OrchestratorDaemon.start(args.project_id, config=config, detach=True)
            print(f"started daemon: pid={pid}", file=sys.stderr)
        except _daemon.AlreadyRunningError as exc:
            print(str(exc), file=sys.stderr)

    try:
        from omoikane.tui.app import run_app
    except Exception as exc:  # pragma: no cover - missing tui extra
        print(
            f"TUI extra not installed: {exc}. Install with `pip install 'omoikane[tui]'`.",
            file=sys.stderr,
        )
        return 1

    return run_app(args.project_id, poll_interval=args.poll_interval)
