"""``omoikane start`` — bootstrap a project and (optionally) run the CTO.

Foreground-only: the project is created in the current process and the
CTO ``AIAgent`` is driven attached to the shell.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from omoikane.runtime.agent_run import RunConfig

from . import init as init_cmd


def add_subparser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--brief", "-b", required=True, type=Path,
        help="Project brief (markdown/plain text).",
    )
    parser.add_argument(
        "--criteria", "-c", required=False, default=None, type=Path,
        help=(
            "Optional acceptance criteria file (JSON array, YAML list, or plain "
            "text). When omitted, the product analyst derives criteria from the "
            "brief."
        ),
    )
    parser.add_argument(
        "--review-criteria", action="store_true",
        help=(
            "Pause once after the analyst derives criteria so you can review "
            "them before the build plan is committed. Resume with "
            "`omoikane resume <pid>`."
        ),
    )
    parser.add_argument(
        "--starting-state", default="scratch", choices=["scratch", "existing"],
        help="Starting state hint (default: scratch).",
    )
    parser.add_argument(
        "--model", default=None,
        help=(
            "Model id passed to AIAgent. Defaults to $OMOIKANE_MODEL, then "
            "config.toml [model].id, then 'openrouter/owl-alpha'."
        ),
    )
    parser.add_argument(
        "--provider", default=None,
        help=(
            "LLM provider passed to AIAgent. Defaults to $OMOIKANE_PROVIDER, "
            "then config.toml [model].provider, then 'openrouter'."
        ),
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


def run(args: argparse.Namespace) -> int:
    if not args.brief.is_file():
        print(f"brief file not found: {args.brief}", file=sys.stderr)
        return 1

    brief = args.brief.read_text(encoding="utf-8").strip()
    if not brief:
        print(f"brief file is empty: {args.brief}", file=sys.stderr)
        return 1

    # Criteria are optional — omit the file to have the analyst derive them.
    if args.criteria is None:
        criteria = []
    elif not args.criteria.is_file():
        print(f"criteria file not found: {args.criteria}", file=sys.stderr)
        return 1
    else:
        criteria = init_cmd._load_criteria(args.criteria)

    from omoikane.tools.handlers import project_start

    payload = project_start({
        "brief": brief,
        "acceptance_criteria": criteria,
        "starting_state": args.starting_state,
        "review_criteria": args.review_criteria,
    })
    response = json.loads(payload)
    if response.get("error"):
        print(f"project_start failed: {response['error']}", file=sys.stderr)
        return 1

    project_id = response["project_id"]
    print(f"Project created: {project_id}")
    if criteria:
        print(f"  criteria: {len(criteria)} (operator-supplied)")
    else:
        print("  criteria: none supplied — the analyst will derive them from the brief")

    if args.no_run:
        return 0

    from omoikane.config import settings

    cfg = settings.load_config()
    api_key = settings.resolve_api_key(cfg)
    if not api_key:
        print(
            "No API key found. Set OMOIKANE_API_KEY / OPENROUTER_API_KEY / "
            "ANTHROPIC_API_KEY (or run `omoikane onboard`) and re-run with "
            "`omoikane resume <pid>`.",
            file=sys.stderr,
        )
        return 0

    config = RunConfig(
        model=args.model or settings.resolve_model(cfg),
        api_key=api_key,
        provider=args.provider or settings.resolve_provider(cfg),
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

    # Surface the acceptance criteria (derived ones included) so the operator
    # can see the completion contract the team is building against.
    if not criteria:
        from omoikane.core.book import ProjectBook

        data = ProjectBook(project_id).load()
        derived = data.get("acceptance_criteria") or []
        if derived:
            provenance = data.get("criteria_provenance") or {}
            print("Acceptance criteria:")
            for i, text in enumerate(derived):
                tag = provenance.get(str(i), "?")
                print(f"  [{i}] ({tag}) {text}")
    return 0
