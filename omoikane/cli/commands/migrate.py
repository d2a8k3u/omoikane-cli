"""``omoikane migrate-from-hermes`` — copy legacy plugin state into the new home.

The Hermes plugin stored each project under
``~/.hermes/omoikane/projects/<pid>/`` with the same per-project layout
the standalone CLI uses. Migration copies every project subtree into
``~/.omoikane/projects/<pid>/`` and re-runs the SQLite index so
``omoikane list`` sees the imported rows.

Per-project bookkeeping is sanitised:

- ``supervisor.cron_id`` is cleared (the Hermes per-project cron does
  not exist in the new world).
- ``active_resurrect_run_id`` and ``active_resurrect_started_at`` are
  cleared to avoid pretending a vanished gateway run is still in flight.
- ``supervisor.consecutive_no_progress_ticks`` resets so the new
  supervisor doesn't trip the circuit breaker on day one.

The legacy directory is never deleted. ``--dry-run`` lists everything
that would be copied without touching disk.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import List, Optional

from omoikane.config import paths


_HERMES_ROOT = Path.home() / ".hermes" / "omoikane"


def add_subparser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--hermes-root", type=Path, default=_HERMES_ROOT,
        help="Override the legacy plugin's home (default: ~/.hermes/omoikane).",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print what would be migrated without copying anything.",
    )
    parser.add_argument(
        "--overwrite", action="store_true",
        help="Replace existing projects in the new home (default skips them).",
    )


def run(args: argparse.Namespace) -> int:
    hermes_root: Path = args.hermes_root
    if not hermes_root.exists():
        print(f"no Hermes home at {hermes_root}", file=sys.stderr)
        return 1

    src_projects = hermes_root / "projects"
    if not src_projects.is_dir():
        print(f"no projects directory at {src_projects}", file=sys.stderr)
        return 1

    targets = _discover_projects(src_projects)
    if not targets:
        print("(no projects to migrate)")
        return 0

    dest_root = paths.project_root()
    dest_root.mkdir(parents=True, exist_ok=True)

    migrated: List[str] = []
    skipped: List[str] = []
    for src in targets:
        dest = dest_root / src.name
        if dest.exists() and not args.overwrite:
            skipped.append(src.name)
            continue
        if args.dry_run:
            print(f"would copy {src} → {dest}")
            continue
        if dest.exists() and args.overwrite:
            shutil.rmtree(dest)
        shutil.copytree(src, dest)
        _sanitise(dest)
        migrated.append(src.name)

    if not args.dry_run:
        _reindex()

    if migrated:
        print(f"migrated {len(migrated)} project(s):")
        for pid in migrated:
            print(f"  + {pid}")
    if skipped:
        print(f"skipped {len(skipped)} existing project(s) (use --overwrite to replace):")
        for pid in skipped:
            print(f"  - {pid}")
    return 0


def _discover_projects(src_root: Path) -> List[Path]:
    return sorted(
        (p for p in src_root.iterdir() if p.is_dir() and (p / "book.json").exists()),
        key=lambda p: p.name,
    )


def _sanitise(project_dir: Path) -> None:
    book_path = project_dir / "book.json"
    if not book_path.exists():
        return
    try:
        data = json.loads(book_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return

    changed = False
    sup = data.get("supervisor")
    if isinstance(sup, dict):
        for key in ("cron_id", "last_action"):
            if sup.pop(key, None) is not None:
                changed = True
        if "consecutive_no_progress_ticks" in sup:
            sup["consecutive_no_progress_ticks"] = 0
            changed = True
    if data.get("active_resurrect_run_id"):
        data["active_resurrect_run_id"] = None
        data["active_resurrect_started_at"] = None
        changed = True

    if changed:
        book_path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _reindex() -> None:
    """Rebuild the SQLite index against the new project tree."""
    from omoikane.core import store

    index_path = paths.index_db()
    if index_path.exists():
        index_path.unlink()
    store._DB_READY = False
    store.init_index_db()

    from omoikane.core.book import ProjectBook

    for project_dir in paths.project_root().iterdir():
        if not project_dir.is_dir():
            continue
        if not (project_dir / "book.json").exists():
            continue
        try:
            ProjectBook(project_dir.name).load()
        except Exception:
            continue
        # ProjectStore.create_book already writes to the index; we hit
        # it indirectly through ProjectBook(...).load() because the
        # constructor's _index_project pass runs on every save. For
        # migration we explicitly write the row by saving with an
        # identity updater.
        book = ProjectBook(project_dir.name)
        book.store.update_book(lambda data: None)


__all__ = ["run", "add_subparser"]
