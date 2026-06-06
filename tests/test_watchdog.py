"""Unit tests for the watchdog stall detector."""

import json
from datetime import datetime, timezone, timedelta

from omoikane.core.book import ProjectBook
from omoikane.core.watchdog import (
    DEFAULT_STALL_MINUTES,
    _is_stalled,
    _parse_iso,
    run_watchdog,
)


def _force_last_activity(book: ProjectBook, minutes_ago: float) -> None:
    """Backdate last_activity bypassing ProjectStore.save_book (which would
    clobber it back to now)."""
    when = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    data = book.load()
    data["last_activity"] = when.isoformat()
    with open(book.store.book_path, "w") as fh:
        json.dump(data, fh, indent=2)


def test_parse_iso_roundtrip():
    now = datetime.now(timezone.utc).replace(microsecond=0)
    parsed = _parse_iso(now.isoformat())
    assert parsed == now


def test_parse_iso_handles_z_suffix():
    assert _parse_iso("2026-01-01T12:00:00Z") is not None
    assert _parse_iso(None) is None
    assert _parse_iso("not-a-date") is None


def test_is_stalled_false_when_recent(temp_hermes_home):
    book = ProjectBook.create("brief", ["AC"])
    book.update_status("in_progress")
    book.open_task("real task")
    data = book.load()
    assert _is_stalled(data, datetime.now(timezone.utc), DEFAULT_STALL_MINUTES) is False


def test_is_stalled_true_when_idle_with_open_tasks(temp_hermes_home):
    book = ProjectBook.create("brief", ["AC"])
    book.update_status("in_progress")
    book.open_task("real task")
    _force_last_activity(book, minutes_ago=60)
    data = book.load()
    assert _is_stalled(data, datetime.now(timezone.utc), DEFAULT_STALL_MINUTES) is True


def test_is_stalled_false_when_no_open_tasks_and_no_criteria(temp_hermes_home):
    book = ProjectBook.create("brief", [])  # zero criteria → nothing to chase
    book.update_status("in_progress")
    _force_last_activity(book, minutes_ago=60)
    data = book.load()
    assert _is_stalled(data, datetime.now(timezone.utc), DEFAULT_STALL_MINUTES) is False


def test_is_stalled_true_when_criteria_pending(temp_hermes_home):
    book = ProjectBook.create("brief", ["A", "B"])
    book.update_status("in_progress")
    _force_last_activity(book, minutes_ago=60)
    data = book.load()
    assert _is_stalled(data, datetime.now(timezone.utc), DEFAULT_STALL_MINUTES) is True


def test_is_stalled_false_when_all_criteria_satisfied(temp_hermes_home):
    book = ProjectBook.create("brief", ["A"])
    book.update_status("in_progress")
    book.satisfy_criterion(0)
    _force_last_activity(book, minutes_ago=60)
    data = book.load()
    assert _is_stalled(data, datetime.now(timezone.utc), DEFAULT_STALL_MINUTES) is False


def test_run_watchdog_pokes_stalled_project(temp_hermes_home):
    book = ProjectBook.create("Build CLI", ["CLI works"])
    book.update_status("in_progress")
    book.open_task("Implement parser")
    _force_last_activity(book, minutes_ago=60)

    result = run_watchdog(stall_minutes=DEFAULT_STALL_MINUTES)

    assert result.checked == 1
    assert book.project_id in result.poked
    assert book.project_id not in result.skipped_active

    activity = book.store.activity_path.read_text()
    assert "watchdog classified" in activity
    assert "stalled" in activity


def test_run_watchdog_skips_active_project(temp_hermes_home):
    book = ProjectBook.create("Healthy", ["AC"])
    book.update_status("in_progress")
    book.open_task("ongoing task")
    # last_activity stays at "now" — project is moving

    result = run_watchdog(stall_minutes=DEFAULT_STALL_MINUTES)

    assert result.checked == 1
    assert book.project_id in result.skipped_active
    assert book.project_id not in result.poked


def test_run_watchdog_skips_done_project(temp_hermes_home):
    book = ProjectBook.create("Finished", ["A"])
    book.satisfy_criterion(0)
    book.update_status("done", phase="completed")
    _force_last_activity(book, minutes_ago=600)

    result = run_watchdog()
    assert book.project_id in result.skipped_terminal
    assert book.project_id not in result.poked


def test_run_watchdog_skips_blocked_project(temp_hermes_home):
    """Blocked projects are operator-owned — the watchdog must not nudge them."""
    book = ProjectBook.create("Paused", ["A"])
    book.update_status("blocked")
    book.open_task("waiting on human")
    _force_last_activity(book, minutes_ago=600)

    result = run_watchdog()
    assert book.project_id in result.skipped_terminal


def test_run_watchdog_empty_store(temp_hermes_home):
    result = run_watchdog()
    assert result.checked == 0
    assert result.poked == []
