"""``omoikane supervisor tick`` — no-LLM watchdog pass.

A single tick iterates every project tracked in the SQLite index, asks
:func:`omoikane.core.watchdog.classify` what state it is in (using a
local ``os.kill(pid, 0)`` check instead of the legacy Hermes gateway
HTTP probe), and takes one cheap action per classification:

- ``HEALTHY``  → noop (the daemon owns its own heartbeat)
- ``STALLED``  → restart the daemon (it will resume cto_history)
- ``CRASHED``  → clear the stale pidfile and restart
- ``COMPLETED``→ flip status to ``done`` so the row stops being polled
- ``IN_FLIGHT``→ noop (we are inside a fresh respawn window)
- ``TERMINAL`` → noop (project is done/failed/cancelled)

Tick increments the no-progress counter and trips the per-project
circuit breaker once it exceeds the configured threshold (defaults
mirror the watchdog module).
"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Iterable, Iterator, List, Optional

from omoikane.config import paths
from omoikane.core import store as _store
from omoikane.core.book import (
    DEFAULT_CIRCUIT_BREAKER_MINUTES,
    ProjectBook,
)
from omoikane.core.watchdog import ProjectState, classify
from omoikane.orchestrator import daemon as _daemon
from omoikane.runtime.agent_run import RunConfig
from omoikane.transport.base import ApprovalEnvelope, Transport

logger = logging.getLogger(__name__)


def _iter_index_rows() -> Iterator[sqlite3.Row]:
    _store.init_index_db()
    conn = sqlite3.connect(paths.index_db())
    conn.row_factory = sqlite3.Row
    try:
        for row in conn.execute("""
            SELECT id, status FROM projects
            WHERE status NOT IN ('done', 'failed', 'cancelled')
        """).fetchall():
            yield row
    finally:
        conn.close()


def _local_run_status(daemon_pid_string: Optional[str]) -> str:
    """Match the watchdog's ``run_status_fn`` contract using local pid checks."""
    if not daemon_pid_string:
        return "gone"
    try:
        pid = int(daemon_pid_string)
    except (TypeError, ValueError):
        return "gone"
    return _daemon.check_pid_alive(pid)


@dataclass
class TickOutcome:
    project_id: str
    state: str
    action: str
    pid: Optional[int]
    note: Optional[str] = None

    def to_dict(self) -> Dict[str, object]:
        return {
            "project_id": self.project_id,
            "state": self.state,
            "action": self.action,
            "pid": self.pid,
            "note": self.note,
        }


def run_tick(
    *,
    config: Optional[RunConfig] = None,
    project_ids: Optional[Iterable[str]] = None,
    stall_minutes: float = 10.0,
    circuit_breaker_minutes: float = DEFAULT_CIRCUIT_BREAKER_MINUTES,
    tick_interval_minutes: float = 5.0,
    transports: Optional[Iterable[Transport]] = None,
) -> List[TickOutcome]:
    """Run a single supervisor pass. Returns one :class:`TickOutcome` per project.

    The caller supplies ``config`` — without it the supervisor cannot
    respawn a stalled daemon, so STALLED projects land with
    ``action="respawn_skipped_no_config"`` and a note explaining how to
    re-arm them.

    When ``transports`` is supplied the supervisor also pushes every new
    pending approval to each transport and applies any polled operator
    responses back into the Book. ``transports=None`` (the default) skips
    that step entirely, preserving the no-transport behaviour.
    """
    now = datetime.now(timezone.utc)
    if project_ids is None:
        rows = list(_iter_index_rows())
    else:
        rows = [{"id": pid} for pid in project_ids]

    outcomes: List[TickOutcome] = []
    for row in rows:
        pid = row["id"] if isinstance(row, sqlite3.Row) else row["id"]
        try:
            outcome = _tick_one(
                pid,
                now=now,
                config=config,
                stall_minutes=stall_minutes,
                circuit_breaker_minutes=circuit_breaker_minutes,
                tick_interval_minutes=tick_interval_minutes,
            )
            outcomes.append(outcome)
        except Exception as exc:  # noqa: BLE001 - never let one project break the tick
            logger.exception("tick failed for %s", pid)
            outcomes.append(TickOutcome(pid, "error", "tick_error", None, str(exc)))

    if transports:
        tick_project_ids = [o.project_id for o in outcomes]
        push_and_poll_approvals(list(transports), project_ids=tick_project_ids)

    return outcomes


def _tick_one(
    project_id: str,
    *,
    now: datetime,
    config: Optional[RunConfig],
    stall_minutes: float,
    circuit_breaker_minutes: float,
    tick_interval_minutes: float,
) -> TickOutcome:
    book = ProjectBook(project_id)
    try:
        data = book.load()
    except FileNotFoundError:
        return TickOutcome(project_id, "missing", "skip", None, "book.json gone")

    daemon_status = _daemon.status(project_id)

    # The watchdog expects a string pid for its run_status_fn lookup so
    # we can reuse the same plumbing the Hermes plugin had.
    book_with_run_id = dict(data)
    if daemon_status.pid is not None:
        book_with_run_id["active_resurrect_run_id"] = str(daemon_status.pid)
    verdict = classify(
        book_with_run_id,
        now=now,
        run_status_fn=_local_run_status,
        stall_minutes=stall_minutes,
    )

    progressed = False
    if verdict.state == ProjectState.HEALTHY:
        action = "noop_healthy"
    elif verdict.state == ProjectState.IN_FLIGHT:
        action = "noop_in_flight"
    elif verdict.state == ProjectState.COMPLETED:
        book.update_status("done", phase="completed")
        action = "marked_done"
        progressed = True
    elif verdict.state == ProjectState.TERMINAL:
        action = "noop_terminal"
    elif verdict.state == ProjectState.STALLED:
        # Respawn success is NOT progress: only real work (a task closing /
        # last_activity advancing) counts. A project that stays STALLED
        # respawn-after-respawn must keep accumulating no-progress ticks so
        # the circuit breaker eventually trips and a human intervenes.
        action, _ = _respawn(project_id, config, "stalled_respawn", daemon_status)
    elif verdict.state == ProjectState.CRASHED:
        # Stale pidfile if daemon vanished — clean up before respawn.
        _daemon.pidfile_path(project_id).unlink(missing_ok=True)
        action, _ = _respawn(project_id, config, "crashed_respawn", daemon_status)
    else:
        action = f"noop_{verdict.state.value}"

    book.record_supervisor_tick(
        state=verdict.state.value,
        action=action,
        run_id=str(daemon_status.pid) if daemon_status.pid else None,
        outcome=verdict.reason,
        progressed=progressed,
    )

    # Circuit breaker after recording the tick so the counter is fresh.
    remaining = book.ticks_until_circuit_break(tick_interval_minutes)
    if remaining <= 0 and verdict.state in {ProjectState.STALLED, ProjectState.CRASHED}:
        book.trip_circuit_breaker(
            f"circuit_breaker_min={circuit_breaker_minutes}"
            f" tick_interval_min={tick_interval_minutes}"
        )
        action = f"{action}+circuit_breaker_tripped"

    return TickOutcome(
        project_id,
        verdict.state.value,
        action,
        daemon_status.pid,
        verdict.reason,
    )


def _respawn(
    project_id: str,
    config: Optional[RunConfig],
    label: str,
    daemon_status: _daemon.DaemonStatus,
) -> tuple:
    if config is None:
        return f"{label}_skipped_no_config", False
    if daemon_status.is_running:
        return f"{label}_skipped_already_running", False
    try:
        pid = _daemon.OrchestratorDaemon.start(project_id, config=config, detach=True)
    except _daemon.AlreadyRunningError:
        return f"{label}_skipped_race", False
    except Exception:  # noqa: BLE001
        logger.exception("respawn failed for %s", project_id)
        return f"{label}_failed", False
    logger.info("respawned %s (label=%s pid=%s)", project_id, label, pid)
    return label, True


def push_and_poll_approvals(
    transports: List[Transport],
    *,
    project_ids: Optional[Iterable[str]] = None,
) -> None:
    """Fan pending approvals out to every transport and apply responses.

    For each active project: send each not-yet-notified pending approval
    via every transport (recording the notified state so the next tick
    does not re-send it), then poll every transport and resolve each
    returned :class:`~omoikane.transport.base.TransportResponse` through
    ``ProjectBook.resolve_approval``.

    A missing/corrupt book for one project never aborts the others.
    """
    if not transports:
        return

    if project_ids is None:
        ids = [row["id"] for row in _iter_index_rows()]
    else:
        ids = list(project_ids)

    for project_id in ids:
        book = ProjectBook(project_id)
        try:
            data = book.load()
        except (FileNotFoundError, ValueError):
            continue

        for entry in data.get("pending_approvals", []):
            if entry.get("status") != "pending":
                continue
            if entry.get("notified_at"):
                continue  # already pushed on an earlier tick — don't double-send
            envelope = ApprovalEnvelope.from_book_entry(project_id, entry)
            sent_any = False
            for transport in transports:
                try:
                    if transport.send_approval_request(envelope):
                        sent_any = True
                except Exception:  # noqa: BLE001 - one transport must not break others
                    logger.exception(
                        "transport %s failed to send approval %s",
                        getattr(transport, "name", "?"),
                        envelope.approval_id,
                    )
            if sent_any:
                book.mark_approval_notified(
                    approval_id=envelope.approval_id,
                    platform=",".join(getattr(t, "name", "?") for t in transports),
                    chat_id="",
                )

    # Poll every transport once and apply responses across all projects.
    responses = []
    for transport in transports:
        try:
            responses.extend(transport.poll_responses())
        except Exception:  # noqa: BLE001
            logger.exception(
                "transport %s failed to poll responses",
                getattr(transport, "name", "?"),
            )

    if not responses:
        return

    # Map approval_id → project_id so a response can find its Book.
    approval_to_project: Dict[str, str] = {}
    for project_id in ids:
        try:
            data = ProjectBook(project_id).load()
        except (FileNotFoundError, ValueError):
            continue
        for entry in data.get("pending_approvals", []):
            aid = entry.get("approval_id")
            if aid:
                approval_to_project[aid] = project_id

    for response in responses:
        project_id = approval_to_project.get(response.approval_id)
        if project_id is None:
            continue
        try:
            ProjectBook(project_id).resolve_approval(
                approval_id=response.approval_id,
                decision=response.decision,
                note=response.note or None,
            )
        except ValueError:
            # Unknown id, already resolved, or invalid decision — skip.
            logger.warning(
                "could not apply response for approval %s", response.approval_id
            )


__all__ = [
    "TickOutcome",
    "push_and_poll_approvals",
    "run_tick",
]
