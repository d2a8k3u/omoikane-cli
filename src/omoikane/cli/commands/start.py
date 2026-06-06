"""``omoikane start`` — bootstrap a project and (optionally) run the CTO.

Phase 3 ships a foreground-only variant: the project is created in the
current process and the CTO ``AIAgent`` is driven attached to the shell.
The Phase 4 build will add daemon mode (``--detach``) on top of this same
entry point.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Optional

from omoikane.runtime.agent_run import RunConfig

from . import init as init_cmd


def add_subparser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--brief", "-b", required=True, type=Path,
        help="Project brief (markdown/plain text).",
    )
    parser.add_argument(
        "--criteria", "-c", required=True, type=Path,
        help="Acceptance criteria file (JSON array, YAML list, or plain text).",
    )
    parser.add_argument(
        "--starting-state", default="scratch", choices=["scratch", "existing"],
        help="Starting state hint (default: scratch).",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("OMOIKANE_MODEL", "openrouter/owl-alpha"),
        help=(
            "Model id passed to AIAgent. Defaults to $OMOIKANE_MODEL or "
            "'openrouter/owl-alpha'."
        ),
    )
    parser.add_argument(
        "--provider",
        default=os.environ.get("OMOIKANE_PROVIDER", "openrouter"),
        help="LLM provider passed to AIAgent (default: openrouter).",
    )
    parser.add_argument(
        "--max-iterations", type=int, default=20,
        help="Cap on CTO iterations for this run (default: 20).",
    )
    parser.add_argument(
        "--foreground", action="store_true",
        help="Run the CTO attached to the current terminal.",
    )
    parser.add_argument(
        "--detach", action="store_true",
        help=(
            "Spawn a background daemon for the CTO via a double-fork. "
            "The daemon's stdout/stderr land in orchestrator.log."
        ),
    )
    parser.add_argument(
        "--no-run", action="store_true",
        help="Create the project then exit without running the CTO.",
    )


def _resolve_api_key() -> Optional[str]:
    for key in ("OMOIKANE_API_KEY", "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY"):
        if os.environ.get(key):
            return os.environ[key]
    return None


def run(args: argparse.Namespace) -> int:
    if not args.brief.is_file():
        print(f"brief file not found: {args.brief}", file=sys.stderr)
        return 1
    if not args.criteria.is_file():
        print(f"criteria file not found: {args.criteria}", file=sys.stderr)
        return 1

    brief = args.brief.read_text(encoding="utf-8").strip()
    if not brief:
        print(f"brief file is empty: {args.brief}", file=sys.stderr)
        return 1

    criteria = init_cmd._load_criteria(args.criteria)

    from omoikane.tools.handlers import project_start

    payload = project_start({
        "brief": brief,
        "acceptance_criteria": criteria,
        "starting_state": args.starting_state,
    })
    response = json.loads(payload)
    if response.get("error"):
        print(f"project_start failed: {response['error']}", file=sys.stderr)
        return 1

    project_id = response["project_id"]
    print(f"Project created: {project_id}")
    print(f"  criteria: {len(criteria)}")

    if args.no_run:
        return 0

    api_key = _resolve_api_key()
    if not api_key:
        print(
            "No API key found. Set OMOIKANE_API_KEY / OPENROUTER_API_KEY / "
            "ANTHROPIC_API_KEY and re-run with `omoikane resume <pid>`.",
            file=sys.stderr,
        )
        return 0

    config = RunConfig(
        model=args.model,
        api_key=api_key,
        provider=args.provider,
        max_iterations=args.max_iterations,
    )

    if args.foreground and args.detach:
        print("--foreground and --detach are mutually exclusive", file=sys.stderr)
        return 2

    if args.detach:
        from omoikane.orchestrator.daemon import (
            AlreadyRunningError,
            OrchestratorDaemon,
        )
        try:
            pid = OrchestratorDaemon.start(
                project_id,
                config=config,
                max_iterations=args.max_iterations,
                detach=True,
            )
        except AlreadyRunningError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(f"daemon started: pid={pid}")
        return 0

    if not args.foreground:
        print(
            "Re-run with --foreground or --detach to start the CTO. "
            "The project is created on disk; use `omoikane status <pid>` to inspect.",
            file=sys.stderr,
        )
        return 0

    from omoikane.orchestrator.loop import run_foreground

    iterations = run_foreground(
        project_id,
        config=config,
        max_iterations=args.max_iterations,
    )
    print(f"CTO session ended after {iterations} iteration(s)")
    return 0
