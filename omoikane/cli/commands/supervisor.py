"""``omoikane supervisor install|tick|status|uninstall``."""
from __future__ import annotations

import argparse
import json
import os
import sys

from omoikane.config import paths
from omoikane.runtime.agent_run import RunConfig
from omoikane.supervisor import install as _install
from omoikane.supervisor import tick as _tick


def add_subparser(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="supervisor_command", required=True)

    install_p = sub.add_parser("install", help="Install the recurring supervisor schedule.")
    install_p.add_argument("--schedule", default="*/5 * * * *",
                           help="Cron-style schedule (default: */5 * * * *).")
    install_p.add_argument("--dry-run", action="store_true",
                           help="Print what would be written, don't touch disk.")
    install_p.add_argument("--backend", choices=("launchd", "systemd", "cron"),
                           help="Override platform autodetection.")

    sub.add_parser("uninstall", help="Remove the recurring supervisor schedule.")

    tick_p = sub.add_parser("tick", help="Run a single supervisor pass.")
    tick_p.add_argument("--json", action="store_true",
                        help="Emit JSON outcomes instead of the human summary.")
    tick_p.add_argument(
        "--model", default=os.environ.get("OMOIKANE_MODEL", "openrouter/owl-alpha"),
        help="Model id used when respawning stalled daemons.",
    )
    tick_p.add_argument(
        "--provider", default=os.environ.get("OMOIKANE_PROVIDER", "openrouter"),
    )
    tick_p.add_argument(
        "--no-respawn", action="store_true",
        help="Run the classifier without restarting stalled daemons.",
    )

    sub.add_parser("status", help="Report whether the supervisor schedule is installed.")


def run(args: argparse.Namespace) -> int:
    cmd = args.supervisor_command
    if cmd == "install":
        result = _install.install(
            schedule=args.schedule,
            log_dir=paths.logs_dir(),
            dry_run=args.dry_run,
            backend=args.backend,
        )
        print(f"[{result.backend}] installed; paths:")
        for path in result.paths:
            print(f"  {path}")
        if result.note:
            print(f"note: {result.note}")
        return 0

    if cmd == "uninstall":
        result = _install.uninstall()
        print(f"[{result.backend}] uninstalled.")
        for path in result.paths:
            print(f"  removed: {path}")
        if result.note:
            print(f"note: {result.note}")
        return 0

    if cmd == "tick":
        config = None
        if not args.no_respawn:
            from omoikane.config import settings

            api_key = settings.resolve_api_key()
            if not api_key:
                print(
                    "supervisor tick missing API key; will skip respawns. "
                    "Set OMOIKANE_API_KEY / OPENROUTER_API_KEY / ANTHROPIC_API_KEY "
                    "(or run `omoikane onboard`), or pass --no-respawn to suppress "
                    "this warning.",
                    file=sys.stderr,
                )
            else:
                config = RunConfig(
                    model=args.model,
                    api_key=api_key,
                    provider=args.provider,
                )
        outcomes = _tick.run_tick(config=config)
        if args.json:
            print(json.dumps([o.to_dict() for o in outcomes], indent=2))
        else:
            if not outcomes:
                print("no active projects")
                return 0
            for o in outcomes:
                pid = o.pid if o.pid is not None else "-"
                print(f"  {o.project_id:32s}  {o.state:10s}  {o.action:24s}  pid={pid}")
        return 0

    if cmd == "status":
        backend = _install.detect_backend()
        if backend == "launchd":
            installed = _install.launchd_plist_path().exists()
            target = _install.launchd_plist_path()
        elif backend == "systemd":
            installed = _install.systemd_timer_path().exists()
            target = _install.systemd_timer_path()
        else:
            installed = False
            target = None
        print(f"backend: {backend}")
        print(f"installed: {installed}")
        if target:
            print(f"path: {target}")
        return 0

    raise SystemExit(f"unknown supervisor subcommand: {cmd}")
