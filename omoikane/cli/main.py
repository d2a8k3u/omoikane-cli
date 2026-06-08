"""Top-level ``omoikane`` entry point.

The operator surface spans project lifecycle (``start``, ``resume``,
``stop``, ``open``, ``delete-project``), inspection (``status``, ``list``), the operator
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


def _commands() -> List[Tuple[str, str, Callable, Callable]]:
    """Lazy-import each subcommand so a partial install (e.g. missing SDK)
    still loads the top-level parser. Each tuple is
    ``(name, summary, add_subparser_fn, run_fn)``.
    """
    from .commands import approvals as approvals_cmd
    from .commands import delete as delete_cmd
    from .commands import init as init_cmd
    from .commands import inject as inject_cmd
    from .commands import list as list_cmd
    from .commands import migrate as migrate_cmd
    from .commands import onboard as onboard_cmd
    from .commands import open as open_cmd
    from .commands import resume as resume_cmd
    from .commands import self_update as self_update_cmd
    from .commands import start as start_cmd
    from .commands import status as status_cmd
    from .commands import stop as stop_cmd
    from .commands import supervisor as supervisor_cmd

    return [
        ("start", "Create a project and optionally run the CTO loop.",
         start_cmd.add_subparser, start_cmd.run),
        ("resume", "Resume an existing project's CTO loop from saved history.",
         resume_cmd.add_subparser, resume_cmd.run),
        ("open", "Attach the live TUI to a project.",
         open_cmd.add_subparser, open_cmd.run),
        ("stop", "Stop a project's orchestrator daemon.",
         stop_cmd.add_subparser, stop_cmd.run),
        ("supervisor", "Manage the background health-check schedule.",
         supervisor_cmd.add_subparser, supervisor_cmd.run),
        ("approvals", "Review and resolve gated actions.",
         approvals_cmd.add_subparser, approvals_cmd.run),
        ("onboard", "Configure API key, model, notifications, and supervisor.",
         onboard_cmd.add_subparser, onboard_cmd.run),
        ("init-project", "Create a project book without running the CTO.",
         init_cmd.add_subparser, init_cmd.run),
        ("delete-project", "Permanently delete a project (directory + index).",
         delete_cmd.add_subparser, delete_cmd.run),
        ("status", "Show a project's book and phase summary.",
         status_cmd.add_subparser, status_cmd.run),
        ("list", "List all known projects from the index.",
         list_cmd.add_subparser, list_cmd.run),
        ("inject", "Send a message into a project's inbox.",
         inject_cmd.add_subparser, inject_cmd.run),
        ("migrate-from-hermes", "Migrate legacy ~/.hermes data into ~/.omoikane.",
         migrate_cmd.add_subparser, migrate_cmd.run),
        ("self-update", "Upgrade the standalone binary in place.",
         self_update_cmd.add_subparser, self_update_cmd.run),
    ]


def build_parser() -> Tuple[argparse.ArgumentParser, dict]:
    """Return ``(parser, dispatch_table)`` so callers can introspect / test."""
    parser = argparse.ArgumentParser(
        prog="omoikane",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Standalone CLI/TUI orchestrator for autonomous agent teams on "
            "the hermes-agent SDK.\n\n"
            "A project is created with `start` (or `init-project`), driven by a\n"
            "CTO loop running in a per-project daemon, and watched live in the\n"
            "TUI via `open`. State lives under ~/.omoikane/."
        ),
        epilog=(
            "Examples:\n"
            "  omoikane start -b \"build a todo CLI\" -c criteria.txt\n"
            "  omoikane list\n"
            "  omoikane open <project-id>\n"
            "  omoikane inject <project-id> '/cto add tests'\n"
            "  omoikane delete-project <project-id> --force\n\n"
            "Run 'omoikane <command> --help' for the full flags of any command."
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
    sub = parser.add_subparsers(dest="command", metavar="<command>", title="commands")

    dispatch: dict = {}
    for name, summary, register, runner in _commands():
        sp = sub.add_parser(name, help=summary, description=summary)
        register(sp)
        dispatch[name] = runner

    return parser, dispatch


def _self_test() -> int:
    """Prove the (frozen) binary can reach the bundled hermes SDK.

    Exercises the exact path that breaks when a hidden import or data file is
    missing from the build: register tools + construct an ``AIAgent``.
    """
    try:
        import httpx  # noqa: F401
        from omoikane.tui.app import run_app  # noqa: F401

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


def _should_auto_onboard(command: str) -> bool:
    """Whether a normal CLI run should launch onboarding first.

    Only fires for a configured-but-not-yet-set-up frozen install on a real
    terminal. Excludes ``onboard`` (loop guard) and ``self-update`` (which
    triggers onboarding itself after a successful update).
    """
    import os

    if not command or command in {"onboard", "self-update"}:
        return False
    if os.environ.get("OMOIKANE_NO_ONBOARD"):
        return False

    from omoikane.config import paths, settings
    from omoikane.update import updater

    if settings.config_exists():
        return False
    if paths.onboard_skip_file().exists():  # user dismissed the wizard earlier
        return False
    if not updater.is_frozen():  # dev/editable runs shouldn't be force-onboarded
        return False
    if sys.stdin.isatty():
        return True
    try:
        open("/dev/tty", "r").close()
        return True
    except OSError:
        return False


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

    # First-run setup: write config.toml before the first real command runs.
    if _should_auto_onboard(args.command):
        from .commands import onboard as onboard_cmd
        try:
            onboard_cmd.run(argparse.Namespace(
                reconfigure=False, no_supervisor=False, gate_triggered=True,
            ))
        except KeyboardInterrupt:
            # onboard handles its own Ctrl-C, but guard the gate too so a stray
            # interrupt never dumps a traceback — and leave the skip sentinel so
            # we don't re-prompt on the next command.
            print(file=sys.stderr)
            try:
                from omoikane.config import paths
                paths.ensure_home()
                paths.onboard_skip_file().write_text("skipped\n", encoding="utf-8")
            except Exception:  # noqa: BLE001
                pass
        except Exception:  # noqa: BLE001 - setup must never block the command
            logging.getLogger(__name__).debug("auto-onboard failed", exc_info=True)

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
