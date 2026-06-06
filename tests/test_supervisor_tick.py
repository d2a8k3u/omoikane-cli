"""Supervisor tick — classifier outcomes + respawn routing."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from omoikane.core.book import ProjectBook
from omoikane.orchestrator import daemon as _daemon
from omoikane.runtime.agent_run import RunConfig
from omoikane.supervisor import tick as _tick


def _force_idle(book: ProjectBook, minutes: float) -> None:
    """Mutate book.last_activity so the watchdog sees the project as stalled.

    ``ProjectStore.save_book`` rewrites ``last_activity`` on every flush, so
    going through the public API here would clobber our cutoff. Drop the
    timestamp directly into ``book.json`` instead.
    """
    import json

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    raw = json.loads(book.store.book_path.read_text(encoding="utf-8"))
    raw["last_activity"] = cutoff.isoformat()
    book.store.book_path.write_text(json.dumps(raw))


def test_healthy_project_yields_noop(temp_hermes_home):
    book = ProjectBook.create("brief", ["AC"])
    book.open_task("Do something", "agent-implementer")
    outcomes = _tick.run_tick(project_ids=[book.project_id])
    assert len(outcomes) == 1
    assert outcomes[0].state == "healthy"
    assert outcomes[0].action == "noop_healthy"


def test_completed_project_marked_done(temp_hermes_home):
    book = ProjectBook.create("brief", ["AC"])
    # No open tasks and the criterion satisfied → COMPLETED classifier.
    book.satisfy_criterion(0)
    outcomes = _tick.run_tick(project_ids=[book.project_id])
    assert outcomes[0].state == "completed"
    assert outcomes[0].action == "marked_done"
    assert ProjectBook(book.project_id).load()["status"] == "done"


def test_stalled_without_config_skips_respawn(temp_hermes_home):
    book = ProjectBook.create("brief", ["AC"])
    book.open_task("Do something", "agent-implementer")
    _force_idle(book, minutes=30)

    outcomes = _tick.run_tick(project_ids=[book.project_id])
    assert outcomes[0].state == "stalled"
    assert outcomes[0].action == "stalled_respawn_skipped_no_config"


def test_stalled_with_config_attempts_respawn(temp_hermes_home, monkeypatch):
    book = ProjectBook.create("brief", ["AC"])
    book.open_task("Do something", "agent-implementer")
    _force_idle(book, minutes=30)

    invoked = {}

    def fake_start(project_id, *, config, detach=True, **kwargs):
        invoked["project_id"] = project_id
        invoked["config"] = config
        invoked["detach"] = detach
        return 4242

    monkeypatch.setattr(
        _daemon.OrchestratorDaemon, "start", staticmethod(fake_start),
    )

    config = RunConfig(model="x", api_key="y")
    outcomes = _tick.run_tick(config=config, project_ids=[book.project_id])
    assert outcomes[0].state == "stalled"
    assert outcomes[0].action == "stalled_respawn"
    assert invoked["project_id"] == book.project_id
    assert invoked["detach"] is True


def test_already_running_daemon_skips_respawn(temp_hermes_home, monkeypatch):
    """A live pidfile must short-circuit the respawn path."""
    book = ProjectBook.create("brief", ["AC"])
    book.open_task("Do something", "agent-implementer")
    _force_idle(book, minutes=30)

    pid_path = _daemon.pidfile_path(book.project_id)
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    import os
    pid_path.write_text(f"{os.getpid()}\n")

    starts = []
    monkeypatch.setattr(
        _daemon.OrchestratorDaemon, "start",
        staticmethod(lambda *a, **kw: starts.append(kw) or 1),
    )

    config = RunConfig(model="x", api_key="y")
    outcomes = _tick.run_tick(config=config, project_ids=[book.project_id])
    # The classifier sees a live pid → IN_FLIGHT, not STALLED. No restart.
    assert outcomes[0].state in {"in_flight", "stalled"}
    assert not starts
