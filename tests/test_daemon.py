"""OrchestratorDaemon — pidfile lock, status probes, stop semantics."""
from __future__ import annotations

import os
import signal

import pytest

from omoikane.core.book import ProjectBook
from omoikane.orchestrator import daemon as _daemon
from omoikane.runtime.agent_run import RunConfig


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


def test_daemon_body_graceful_sigterm_cleans_up_pidfile(
    temp_hermes_home, monkeypatch,
):
    """The graceful path: SIGTERM flips the internal SessionStop, the body
    finishes, and the ``finally`` block releases the flock + removes the
    pidfile. Exercised in-process (no fork) by stubbing run_long_session
    to invoke the handler the body installed, then return."""
    book = ProjectBook.create("brief", ["AC"])

    # Avoid the SDK-touching tool registration the body does on startup.
    import omoikane.tools as _tools
    monkeypatch.setattr(_tools, "register_book_tools", lambda *a, **k: None)

    saw_stop = {"requested": False}

    def fake_run_long_session(project_id, *, config, stop, max_iterations,
                              iteration_pause_seconds):
        # Simulate the OS delivering SIGTERM mid-run: invoke the handler the
        # body registered, then observe that it co-operatively flipped stop.
        handler = signal.getsignal(signal.SIGTERM)
        handler(signal.SIGTERM, None)
        saw_stop["requested"] = stop.requested()
        return 1

    monkeypatch.setattr(_daemon, "run_long_session", fake_run_long_session)

    prev_term = signal.getsignal(signal.SIGTERM)
    prev_usr1 = signal.getsignal(signal.SIGUSR1)
    try:
        _daemon._run_daemon_body(
            book.project_id,
            config=RunConfig(model="fake/model", api_key="dummy"),
            max_iterations=1,
            iteration_pause_seconds=0.0,
        )
    finally:
        signal.signal(signal.SIGTERM, prev_term)
        signal.signal(signal.SIGUSR1, prev_usr1)

    # SIGTERM handler flipped the stop event passed into the session loop.
    assert saw_stop["requested"] is True
    # Pidfile removed in the finally block.
    assert not _daemon.pidfile_path(book.project_id).exists()
    # Lock released — a fresh acquire must succeed (would raise if still held).
    handle = _daemon._acquire_pidfile(book.project_id)
    handle.close()
    _daemon.pidfile_path(book.project_id).unlink(missing_ok=True)
    # Lifecycle events landed in the activity stream.
    activity = (
        _daemon.paths.project_dir(book.project_id) / "activity.jsonl"
    ).read_text(encoding="utf-8")
    assert "daemon_started" in activity
    assert "daemon_stopped" in activity


def test_check_pid_alive_returns_running_for_self():
    assert _daemon.check_pid_alive(os.getpid()) == "running"


def test_check_pid_alive_returns_gone_for_high_pid():
    assert _daemon.check_pid_alive(99999998) in {"gone", "unreachable"}
