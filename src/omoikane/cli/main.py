"""Top-level ``omoikane`` entry point.

The full operator surface (``start``, ``open``, ``status``, ``supervisor`` …)
lands in Phase 3-5. This Phase 2 build ships just the subcommands needed to
exercise the SDK plumbing end-to-end:

- ``omoikane init-project`` — create a Project Book from brief + criteria.
- ``omoikane status`` — print a project's current Book.
- ``omoikane list`` — list known projects from the SQLite index.

Each subcommand lives in :mod:`omoikane.cli.commands.<name>` and registers
itself by exposing ``add_subparser(subparsers)`` plus ``run(args) -> int``.
"""
from __future__ import annotations

import argparse
import logging
import sys
from typing import Callable, List, Tuple


def _commands() -> List[Tuple[str, Callable, Callable]]:
    """Lazy-import each subcommand so a partial install (e.g. missing SDK)
    still loads the top-level parser. Each tuple is
    ``(name, add_subparser_fn, run_fn)``.
    """
    from .commands import init as init_cmd
    from .commands import inject as inject_cmd
    from .commands import list as list_cmd
    from .commands import resume as resume_cmd
    from .commands import start as start_cmd
    from .commands import status as status_cmd

    return [
        ("start", start_cmd.add_subparser, start_cmd.run),
        ("resume", resume_cmd.add_subparser, resume_cmd.run),
        ("init-project", init_cmd.add_subparser, init_cmd.run),
        ("status", status_cmd.add_subparser, status_cmd.run),
        ("list", list_cmd.add_subparser, list_cmd.run),
        ("inject", inject_cmd.add_subparser, inject_cmd.run),
    ]


def build_parser() -> Tuple[argparse.ArgumentParser, dict]:
    """Return ``(parser, dispatch_table)`` so callers can introspect / test."""
    parser = argparse.ArgumentParser(
        prog="omoikane",
        description=(
            "Standalone CLI/TUI orchestrator for autonomous agent teams on "
            "the hermes-agent SDK."
        ),
    )
    parser.add_argument(
        "-v", "--verbose",
        action="count", default=0,
        help="Increase log verbosity (-v INFO, -vv DEBUG).",
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    dispatch: dict = {}
    for name, register, runner in _commands():
        sp = sub.add_parser(name)
        register(sp)
        dispatch[name] = runner

    return parser, dispatch


def main(argv: List[str] = None) -> int:
    parser, dispatch = build_parser()
    args = parser.parse_args(argv)

    level = logging.WARNING
    if args.verbose >= 2:
        level = logging.DEBUG
    elif args.verbose == 1:
        level = logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if not args.command:
        parser.print_help()
        return 2

    runner = dispatch.get(args.command)
    if runner is None:  # pragma: no cover - argparse already guards
        parser.error(f"unknown command: {args.command}")
        return 2

    return runner(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
