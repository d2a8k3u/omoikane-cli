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

    return updater.self_update(force=args.force, check_only=args.check)
