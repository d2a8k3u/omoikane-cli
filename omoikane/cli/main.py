"""Top-level ``omoikane`` entry point.

The operator surface spans project lifecycle (``start``, ``resume``,
``stop``, ``open``), inspection (``status``, ``list``), the operator
inbox (``inject``, ``approvals``), the background ``supervisor``, and
``migrate`` for on-disk upgrades.

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
    from .commands import approvals as approvals_cmd
    from .commands import init as init_cmd
    from .commands import inject as inject_cmd
    from .commands import list as list_cmd
    from .commands import migrate as migrate_cmd
    from .commands import open as open_cmd
    from .commands import resume as resume_cmd
    from .commands import self_update as self_update_cmd
    from .commands import start as start_cmd
    from .commands import status as status_cmd
    from .commands import stop as stop_cmd
    from .commands import supervisor as supervisor_cmd

    return [
        ("start", start_cmd.add_subparser, start_cmd.run),
        ("resume", resume_cmd.add_subparser, resume_cmd.run),
        ("open", open_cmd.add_subparser, open_cmd.run),
        ("stop", stop_cmd.add_subparser, stop_cmd.run),
        ("supervisor", supervisor_cmd.add_subparser, supervisor_cmd.run),
        ("approvals", approvals_cmd.add_subparser, approvals_cmd.run),
        ("init-project", init_cmd.add_subparser, init_cmd.run),
        ("status", status_cmd.add_subparser, status_cmd.run),
        ("list", list_cmd.add_subparser, list_cmd.run),
        ("inject", inject_cmd.add_subparser, inject_cmd.run),
        ("migrate-from-hermes", migrate_cmd.add_subparser, migrate_cmd.run),
        ("self-update", self_update_cmd.add_subparser, self_update_cmd.run),
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
    from omoikane import __version__

    parser.add_argument(
        "--version",
        action="version",
        version=f"omoikane {__version__}",
    )
    # Hidden: verify the frozen binary can reach the bundled hermes SDK
    # (register tools + construct AIAgent). Used by the release CI smoke test
    # to catch missing hidden-imports / data files before users do.
    parser.add_argument(
        "--self-test", action="store_true", help=argparse.SUPPRESS,
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


def _self_test() -> int:
    """Prove the (frozen) binary can reach the bundled hermes SDK.

    Exercises the exact path that breaks when a hidden import or data file is
    missing from the build: register tools + construct an ``AIAgent``.
    """
    try:
        from omoikane.tools import register_book_tools

        registered = register_book_tools()
        from run_agent import AIAgent  # noqa: F401

        AIAgent(
            model="dummy",
            api_key="dummy",
            enabled_toolsets=["omoikane"],
            quiet_mode=True,
            skip_context_files=True,
            skip_memory=True,
            max_iterations=1,
        )
    except (ModuleNotFoundError, ImportError, FileNotFoundError) as exc:
        print(f"self-test FAILED (freeze gap): {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 - benign (auth/model) means the SDK loaded
        print(f"self-test OK (reached construction; benign: {type(exc).__name__})")
        return 0
    print(f"self-test OK ({len(registered)} tools, AIAgent constructed)")
    return 0


def main(argv: List[str] = None) -> int:
    parser, dispatch = build_parser()
    args = parser.parse_args(argv)

    if getattr(args, "self_test", False):
        return _self_test()

    level = logging.WARNING
    if args.verbose >= 2:
        level = logging.DEBUG
    elif args.verbose == 1:
        level = logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if not args.command:
        parser.print_help()
        return 2

    # Best-effort "newer version available" nag (frozen binary + TTY only;
    # throttled, fail-silent — never blocks the command).
    from omoikane.update import updater
    updater.maybe_nag(args.command)

    runner = dispatch.get(args.command)
    if runner is None:  # pragma: no cover - argparse already guards
        parser.error(f"unknown command: {args.command}")
        return 2

    return runner(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
