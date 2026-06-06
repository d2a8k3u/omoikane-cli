"""Unix double-fork daemon for the orchestrator CTO loop.

A single daemon per project owns the long-lived ``AIAgent``. The TUI
attaches and detaches without touching it; the supervisor's tick command
checks pid liveness via ``os.kill(pid, 0)``.

Lifecycle:

1. ``OrchestratorDaemon.start(project_id, config)`` performs the classic
   double-fork, detaches from the controlling terminal, redirects
   stdin/stdout/stderr to ``<pid>/orchestrator.log``, takes an exclusive
   ``fcntl.flock`` on ``orchestrator.pid``, writes its PID, then calls
   :func:`omoikane.orchestrator.cto_session.run_long_session`.
2. ``SIGTERM`` → graceful: flip ``SessionStop`` so the CTO finishes its
   current iteration, persist ``cto_history.json``, release the lock,
   exit 0.
3. ``SIGUSR1`` → write a one-line health snapshot to the activity stream.
4. ``OrchestratorDaemon.stop(project_id)`` reads the pidfile, sends
   ``SIGTERM`` to that pid, optionally waits up to ``timeout`` seconds,
   escalates to ``SIGKILL`` only if explicitly requested. Operators
   keep their data — ``--force`` is opt-in.

The pidfile lock prevents a second ``start`` from racing the supervisor's
respawn or a concurrent ``omoikane start --detach`` invocation.
"""
from __future__ import annotations

import errno
import fcntl
import json
import logging
import os
import signal
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from omoikane.config import paths
from omoikane.runtime import activity_emitter as _activity
from omoikane.runtime.agent_run import RunConfig

from .cto_session import SessionStop, run_long_session

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# Filesystem layout
# ----------------------------------------------------------------------

def pidfile_path(project_id: str) -> Path:
    return paths.project_dir(project_id) / "orchestrator.pid"


def logfile_path(project_id: str) -> Path:
    return paths.project_dir(project_id) / "orchestrator.log"


# ----------------------------------------------------------------------
# Daemon state probe
# ----------------------------------------------------------------------

@dataclass
class DaemonStatus:
    project_id: str
    pid: Optional[int]
    state: str  # "running" | "stale" | "gone" | "unreachable" | "missing"

    @property
    def is_running(self) -> bool:
        return self.state == "running"


def check_pid_alive(pid: int) -> str:
    """``"running"`` / ``"gone"`` / ``"unreachable"`` for the given pid."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return "gone"
    except PermissionError:
        return "unreachable"
    return "running"


def status(project_id: str) -> DaemonStatus:
    path = pidfile_path(project_id)
    if not path.exists():
        return DaemonStatus(project_id, None, "missing")
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return DaemonStatus(project_id, None, "stale")
    try:
        pid = int(raw.splitlines()[0])
    except ValueError:
        return DaemonStatus(project_id, None, "stale")
    state = check_pid_alive(pid)
    if state == "gone":
        # Replaceable on next start — leave file so the supervisor can
        # report it surfaces a CRASHED classification.
        return DaemonStatus(project_id, pid, "stale")
    if state == "unreachable":
        return DaemonStatus(project_id, pid, "unreachable")
    return DaemonStatus(project_id, pid, "running")


# ----------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------

class AlreadyRunningError(RuntimeError):
    """Raised when a second start would race the current daemon."""

    def __init__(self, project_id: str, pid: int):
        super().__init__(f"orchestrator already running for {project_id} (pid={pid})")
        self.project_id = project_id
        self.pid = pid


class OrchestratorDaemon:
    """Helper namespace for starting / stopping the per-project daemon."""

    @staticmethod
    def start(
        project_id: str,
        *,
        config: RunConfig,
        max_iterations: Optional[int] = None,
        iteration_pause_seconds: float = 0.0,
        detach: bool = True,
    ) -> int:
        """Start (or re-attach to) the daemon for ``project_id``.

        Returns the daemon pid. When ``detach=False`` the function runs
        the session loop inline and returns the iteration count instead;
        this is what unit tests use.
        """
        existing = status(project_id)
        if existing.is_running and existing.pid:
            raise AlreadyRunningError(project_id, existing.pid)

        if not detach:
            return _run_session_inline(
                project_id,
                config=config,
                max_iterations=max_iterations,
                iteration_pause_seconds=iteration_pause_seconds,
            )

        # First fork — child becomes session leader.
        first = os.fork()
        if first > 0:
            # Parent: wait for the intermediate child to exit (it's the
            # one that performed setsid), then return the grandchild PID
            # by re-reading the pidfile (the grandchild wrote it).
            os.waitpid(first, 0)
            for _ in range(50):
                snap = status(project_id)
                if snap.is_running and snap.pid:
                    return snap.pid
                time.sleep(0.05)
            raise RuntimeError("daemon failed to write pidfile within 2.5s")

        os.setsid()

        # Second fork — grandchild is the orphan that lives on.
        second = os.fork()
        if second > 0:
            os._exit(0)

        _detach_io(project_id)
        _run_daemon_body(
            project_id,
            config=config,
            max_iterations=max_iterations,
            iteration_pause_seconds=iteration_pause_seconds,
        )
        os._exit(0)  # pragma: no cover - exec never reaches here

    @staticmethod
    def stop(
        project_id: str,
        *,
        timeout: float = 10.0,
        force: bool = False,
    ) -> bool:
        """Send ``SIGTERM`` to the daemon and wait for it to exit.

        Returns ``True`` if the daemon was found and shut down (or was
        already gone), ``False`` if we lack permission. ``force=True``
        escalates to ``SIGKILL`` once ``timeout`` elapses without exit.
        """
        snap = status(project_id)
        if not snap.pid or snap.state in {"missing", "gone"}:
            # Clean up stale pidfile if any.
            try:
                pidfile_path(project_id).unlink(missing_ok=True)
            except OSError:
                pass
            return True
        if snap.state == "unreachable":
            return False

        pid = snap.pid
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pidfile_path(project_id).unlink(missing_ok=True)
            return True

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if check_pid_alive(pid) == "gone":
                pidfile_path(project_id).unlink(missing_ok=True)
                return True
            time.sleep(0.1)

        if force:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            pidfile_path(project_id).unlink(missing_ok=True)
            return True
        return False

    @staticmethod
    def health_snapshot(project_id: str) -> int:
        """Send ``SIGUSR1`` to the running daemon to request a snapshot.

        Returns the pid that received it, or 0 if no daemon is alive.
        """
        snap = status(project_id)
        if not snap.is_running or not snap.pid:
            return 0
        try:
            os.kill(snap.pid, signal.SIGUSR1)
        except ProcessLookupError:
            return 0
        return snap.pid


# ----------------------------------------------------------------------
# Internals — child-side helpers
# ----------------------------------------------------------------------

def _detach_io(project_id: str) -> None:
    project_dir = paths.project_dir(project_id)
    project_dir.mkdir(parents=True, exist_ok=True)
    log_path = logfile_path(project_id)

    sys.stdout.flush()
    sys.stderr.flush()

    try:
        with open(os.devnull, "rb") as null_in:
            os.dup2(null_in.fileno(), 0)
        log_fd = os.open(str(log_path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            os.dup2(log_fd, 1)
            os.dup2(log_fd, 2)
        finally:
            os.close(log_fd)
    except OSError as exc:
        # Last-ditch fallback — keep going so the daemon at least runs.
        logger.exception("Failed to redirect daemon I/O: %s", exc)


def _acquire_pidfile(project_id: str):
    path = pidfile_path(project_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(path, "a+", encoding="utf-8")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        if exc.errno in {errno.EAGAIN, errno.EACCES}:
            fh.close()
            raise AlreadyRunningError(project_id, _read_pid(path) or -1) from exc
        fh.close()
        raise
    fh.seek(0)
    fh.truncate()
    fh.write(f"{os.getpid()}\n{datetime.now(timezone.utc).isoformat()}\n")
    fh.flush()
    os.fsync(fh.fileno())
    return fh


def _read_pid(path: Path) -> Optional[int]:
    try:
        raw = path.read_text(encoding="utf-8").strip().splitlines()
    except OSError:
        return None
    if not raw:
        return None
    try:
        return int(raw[0])
    except ValueError:
        return None


def _run_daemon_body(
    project_id: str,
    *,
    config: RunConfig,
    max_iterations: Optional[int],
    iteration_pause_seconds: float,
) -> None:
    try:
        lock_handle = _acquire_pidfile(project_id)
    except AlreadyRunningError:
        logger.warning("Refusing to start; pidfile lock held by another process")
        return

    emitter = _activity.for_project(project_id)
    stop = SessionStop()

    def _on_sigterm(signum, frame):  # noqa: ARG001
        stop.request("sigterm")

    def _on_sigusr1(signum, frame):  # noqa: ARG001
        emitter.emit("daemon_health", {
            "summary": "daemon health snapshot",
            "pid": os.getpid(),
            "at": datetime.now(timezone.utc).isoformat(),
        })

    signal.signal(signal.SIGTERM, _on_sigterm)
    signal.signal(signal.SIGUSR1, _on_sigusr1)

    emitter.emit("daemon_started", {
        "summary": f"daemon pid={os.getpid()} attached",
        "pid": os.getpid(),
    })

    try:
        # Ensure tools are registered for the spawned process.
        from omoikane.tools import register_book_tools

        register_book_tools()

        run_long_session(
            project_id,
            config=config,
            stop=stop,
            max_iterations=max_iterations,
            iteration_pause_seconds=iteration_pause_seconds,
        )
    except Exception:  # noqa: BLE001
        logger.exception("daemon body raised")
        emitter.error("daemon", "daemon crashed; see orchestrator.log")
    finally:
        emitter.emit("daemon_stopped", {
            "summary": f"daemon pid={os.getpid()} exited",
            "pid": os.getpid(),
        })
        try:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
            lock_handle.close()
            pidfile_path(project_id).unlink(missing_ok=True)
        except OSError:
            pass


def _run_session_inline(
    project_id: str,
    *,
    config: RunConfig,
    max_iterations: Optional[int],
    iteration_pause_seconds: float,
) -> int:
    """Used by tests — no fork, no signal handlers, no pidfile.

    Returns the iteration count from :func:`run_long_session`.
    """
    return run_long_session(
        project_id,
        config=config,
        max_iterations=max_iterations,
        iteration_pause_seconds=iteration_pause_seconds,
    )


__all__ = [
    "AlreadyRunningError",
    "DaemonStatus",
    "OrchestratorDaemon",
    "check_pid_alive",
    "logfile_path",
    "pidfile_path",
    "status",
]
