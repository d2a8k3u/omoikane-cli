"""OrchestratorDaemon — pidfile lock, status probes, stop semantics."""
from __future__ import annotations

import os

import pytest

from omoikane.core.book import ProjectBook
from omoikane.orchestrator import daemon as _daemon


def test_status_missing_when_no_pidfile(temp_hermes_home):
    book = ProjectBook.create("brief", ["AC"])
    snap = _daemon.status(book.project_id)
    assert snap.state == "missing"
    assert not snap.is_running


def test_status_running_for_live_pid(temp_hermes_home):
    book = ProjectBook.create("brief", ["AC"])
    pid_path = _daemon.pidfile_path(book.project_id)
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text(f"{os.getpid()}\n")
    snap = _daemon.status(book.project_id)
    assert snap.state == "running"
    assert snap.pid == os.getpid()


def test_status_stale_when_pid_dead(temp_hermes_home):
    book = ProjectBook.create("brief", ["AC"])
    pid_path = _daemon.pidfile_path(book.project_id)
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text("99999999\n")  # pid almost certainly not alive
    snap = _daemon.status(book.project_id)
    assert snap.state in {"stale", "gone"}


def test_stop_clears_stale_pidfile(temp_hermes_home):
    book = ProjectBook.create("brief", ["AC"])
    pid_path = _daemon.pidfile_path(book.project_id)
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text("99999999\n")
    assert _daemon.OrchestratorDaemon.stop(book.project_id, timeout=1.0)
    assert not pid_path.exists()


def test_already_running_error_blocks_second_acquire(temp_hermes_home, monkeypatch):
    book = ProjectBook.create("brief", ["AC"])
    handle = _daemon._acquire_pidfile(book.project_id)
    try:
        with pytest.raises(_daemon.AlreadyRunningError):
            _daemon._acquire_pidfile(book.project_id)
    finally:
        handle.close()
        _daemon.pidfile_path(book.project_id).unlink(missing_ok=True)


def test_check_pid_alive_returns_running_for_self():
    assert _daemon.check_pid_alive(os.getpid()) == "running"


def test_check_pid_alive_returns_gone_for_high_pid():
    assert _daemon.check_pid_alive(99999998) in {"gone", "unreachable"}
