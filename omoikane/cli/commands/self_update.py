"""``omoikane self-update`` — upgrade the standalone binary in place.

No-op (with guidance) for pip/editable installs; the real flow only runs for
PyInstaller-built binaries. See :mod:`omoikane.update.updater`.
"""
from __future__ import annotations

import argparse


def add_subparser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--check", action="store_true",
        help="Only report whether a newer release exists; do not install.",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Reinstall the latest release even if already current.",
    )


def run(args: argparse.Namespace) -> int:
    from omoikane.update import updater

    rc = updater.self_update(force=args.force, check_only=args.check)

    # A user who self-updates before ever configuring still needs setup. Mirror
    # the main-gate guards: real binary only, honor the opt-out and skip
    # sentinel, and never raise out of this convenience path.
    if rc == 0 and not args.check and _should_offer_onboard():
        from omoikane.cli.commands import onboard

        try:
            onboard.run(argparse.Namespace(
                reconfigure=False, no_supervisor=False, gate_triggered=True,
            ))
        except KeyboardInterrupt:
            pass
        except Exception:  # noqa: BLE001
            pass
    return rc


def _should_offer_onboard() -> bool:
    import os

    from omoikane.config import paths, settings
    from omoikane.update import updater

    if os.environ.get("OMOIKANE_NO_ONBOARD"):
        return False
    if not updater.is_frozen():
        return False
    if settings.config_exists() or paths.onboard_skip_file().exists():
        return False
    return True
