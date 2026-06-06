"""``omoikane resume <pid>`` — continue an existing project's CTO loop."""
from __future__ import annotations

import argparse
import os
import sys
from typing import Optional

from omoikane.runtime.agent_run import RunConfig


def add_subparser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("project_id", help="Project identifier (proj-...).")
    parser.add_argument(
        "--model",
        default=os.environ.get("OMOIKANE_MODEL", "openrouter/owl-alpha"),
    )
    parser.add_argument(
        "--provider",
        default=os.environ.get("OMOIKANE_PROVIDER", "openrouter"),
    )
    parser.add_argument(
        "--max-iterations", type=int, default=20,
        help="Cap on CTO iterations for this resume run (default: 20).",
    )
    parser.add_argument(
        "--foreground", action="store_true", default=True,
        help="Run attached to this shell (the only mode supported in Phase 3).",
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

    api_key = _resolve_api_key()
    if not api_key:
        print(
            "No API key found. Set OMOIKANE_API_KEY / OPENROUTER_API_KEY / "
            "ANTHROPIC_API_KEY and retry.",
            file=sys.stderr,
        )
        return 1

    from omoikane.orchestrator.loop import run_foreground

    config = RunConfig(
        model=args.model,
        api_key=api_key,
        provider=args.provider,
        max_iterations=args.max_iterations,
    )
    iterations = run_foreground(
        args.project_id,
        config=config,
        max_iterations=args.max_iterations,
    )
    print(f"CTO session ended after {iterations} iteration(s)")
    return 0
