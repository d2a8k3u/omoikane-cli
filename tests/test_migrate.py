"""Migration from the Hermes plugin home."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from omoikane.cli.commands import migrate as migrate_cmd


def _seed_hermes(tmp_path: Path) -> Path:
    src_root = tmp_path / "hermes" / "omoikane" / "projects"
    src_root.mkdir(parents=True)
    pid = "proj-test-001"
    pdir = src_root / pid
    pdir.mkdir()
    (pdir / "book.json").write_text(json.dumps({
        "id": pid,
        "brief": "legacy project",
        "status": "in_progress",
        "current_phase": "analysis",
        "acceptance_criteria": ["A"],
        "criteria_status": {"0": "pending"},
        "open_tasks": ["t-1"],
        "completed_tasks": [],
        "task_meta": {"t-1": {"title": "do thing"}},
        "active_resurrect_run_id": "old-run-42",
        "active_resurrect_started_at": "2026-01-01T00:00:00",
        "supervisor": {
            "cron_id": "omoikane-project-old",
            "consecutive_no_progress_ticks": 7,
            "last_action": "stalled_respawn",
        },
        "last_activity": "2026-01-01T00:00:00",
    }))
    (pdir / "delegation.json").write_text(json.dumps({"nodes": [], "edges": []}))
    (pdir / "activity.jsonl").write_text("")
    return src_root.parent


@pytest.fixture
def hermes_root(tmp_path):
    return _seed_hermes(tmp_path)


def test_migrate_copies_and_sanitises(temp_hermes_home, hermes_root):
    args = type("A", (), {
        "hermes_root": hermes_root,
        "dry_run": False,
        "overwrite": False,
    })()
    rc = migrate_cmd.run(args)
    assert rc == 0

    from omoikane.config import paths
    from omoikane.core.book import ProjectBook

    migrated_dir = paths.project_dir("proj-test-001")
    assert migrated_dir.exists()
    data = ProjectBook("proj-test-001").load()
    assert data["status"] == "in_progress"
    assert data["active_resurrect_run_id"] is None
    sup = data.get("supervisor") or {}
    assert "cron_id" not in sup
    assert sup.get("consecutive_no_progress_ticks") == 0


def test_migrate_dry_run_no_copy(temp_hermes_home, hermes_root, capsys):
    args = type("A", (), {
        "hermes_root": hermes_root,
        "dry_run": True,
        "overwrite": False,
    })()
    rc = migrate_cmd.run(args)
    assert rc == 0

    from omoikane.config import paths
    assert not paths.project_dir("proj-test-001").exists()
    captured = capsys.readouterr().out
    assert "would copy" in captured


def test_migrate_skips_existing_without_overwrite(temp_hermes_home, hermes_root, capsys):
    args_first = type("A", (), {
        "hermes_root": hermes_root,
        "dry_run": False,
        "overwrite": False,
    })()
    assert migrate_cmd.run(args_first) == 0

    # Mutate the destination so we can detect that the second run did
    # NOT overwrite it.
    from omoikane.config import paths
    marker = paths.project_dir("proj-test-001") / "marker.txt"
    marker.write_text("untouched")

    args_second = type("A", (), {
        "hermes_root": hermes_root,
        "dry_run": False,
        "overwrite": False,
    })()
    assert migrate_cmd.run(args_second) == 0
    assert marker.exists()
    captured = capsys.readouterr().out
    assert "skipped" in captured


def test_missing_hermes_root_returns_error(temp_hermes_home, tmp_path):
    args = type("A", (), {
        "hermes_root": tmp_path / "nope",
        "dry_run": False,
        "overwrite": False,
    })()
    assert migrate_cmd.run(args) == 1
