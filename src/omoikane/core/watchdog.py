"""Omoikane — project state classifier.

Pure functions. No side effects. The classifier decides what state a
project is in; the per-project supervisor cron tick decides what to do
about it.

Five classifications:

* ``HEALTHY``    — recent activity within ``healthy_minutes``; do nothing.
* ``STALLED``    — idle past ``stall_minutes``; no resurrect in flight;
                   still has open work. Spawn a fresh resurrect session.
* ``CRASHED``    — an ``active_resurrect_run_id`` exists but the gateway
                   reports it terminal (or the run is gone). The session
                   died mid-task; close the active slot and respawn.
* ``IN_FLIGHT``  — resurrect run is still running on the gateway. Leave
                   it alone; just record a heartbeat.
* ``COMPLETED``  — no open tasks AND every acceptance criterion is
                   satisfied. Caller should mark the project ``done``
                   and tear down its cron.
* ``TERMINAL``   — project status is already ``done``/``failed``/
                   ``cancelled``; the cron should self-delete.

The classifier is gateway-aware via the injected ``run_status_fn``: pass
a callable that maps ``run_id -> Optional[str]`` (None means we couldn't
reach the gateway or the run is gone). The supervisor injects
``_check_run_status``; tests pass a stub.

``run_watchdog`` from the legacy single-tick orchestrator is preserved
as a thin wrapper so external callers (the ``hermes omoikane tick`` CLI
subcommand) keep working. It uses the classifier but only logs — it
does not spawn resurrect sessions (that's the supervisor cron's job).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from .book import ProjectBook
from .dashboard import DashboardProvider

logger = logging.getLogger(__name__)

_ACTIVE_STATUSES = {"created", "in_progress", "review"}
ACTIVE_STATUSES = _ACTIVE_STATUSES

DEFAULT_STALL_MINUTES = 10
DEFAULT_HEALTHY_MINUTES = 3

_TERMINAL_RUN_STATES = {"completed", "failed", "cancelled", "stopped", "gone"}
_UNREACHABLE_STATES = {"unreachable"}


class ProjectState(str, Enum):
    HEALTHY = "healthy"
    STALLED = "stalled"
    CRASHED = "crashed"
    IN_FLIGHT = "in_flight"
    COMPLETED = "completed"
    TERMINAL = "terminal"


@dataclass
class Classification:
    state: ProjectState
    reason: str
    idle_minutes: float = 0.0
    open_tasks_count: int = 0
    unsatisfied_criteria_count: int = 0
    active_resurrect_run_id: Optional[str] = None
    run_status: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "state": self.state.value,
            "reason": self.reason,
            "idle_minutes": self.idle_minutes,
            "open_tasks_count": self.open_tasks_count,
            "unsatisfied_criteria_count": self.unsatisfied_criteria_count,
            "active_resurrect_run_id": self.active_resurrect_run_id,
            "run_status": self.run_status,
        }


def _parse_iso(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def _idle_minutes(book_data: Dict[str, Any], now: datetime) -> float:
    last = _parse_iso(book_data.get("last_activity") or book_data.get("created_at"))
    if last is None:
        return 0.0
    return max(0.0, (now - last).total_seconds() / 60.0)


def idle_minutes(book_data: Dict[str, Any], now: datetime) -> float:
    return _idle_minutes(book_data, now)


def _unsatisfied_count(book_data: Dict[str, Any]) -> int:
    criteria = book_data.get("acceptance_criteria") or []
    status = book_data.get("criteria_status") or {}
    return sum(
        1 for i in range(len(criteria))
        if status.get(str(i)) != "satisfied"
    )


def classify(
    book_data: Dict[str, Any],
    now: datetime,
    *,
    stall_minutes: int = DEFAULT_STALL_MINUTES,
    healthy_minutes: int = DEFAULT_HEALTHY_MINUTES,
    run_status_fn: Optional[Callable[[str], Optional[str]]] = None,
) -> Classification:
    """Classify a project's current state. Pure, no side effects.

    ``run_status_fn`` is the gateway probe — pass
    ``supervisor_script._check_run_status`` in production, a stub in
    tests. When ``None``, an ``active_resurrect_run_id`` is treated as
    IN_FLIGHT (optimistic — better to wait than spawn a duplicate).
    """
    status = (book_data.get("status") or "").lower()
    open_tasks = book_data.get("open_tasks") or []
    unsatisfied = _unsatisfied_count(book_data)
    idle = _idle_minutes(book_data, now)
    active_run = book_data.get("active_resurrect_run_id")

    if status not in _ACTIVE_STATUSES:
        return Classification(
            state=ProjectState.TERMINAL,
            reason=f"status={status!r} not in active set",
            idle_minutes=idle,
            open_tasks_count=len(open_tasks),
            unsatisfied_criteria_count=unsatisfied,
            active_resurrect_run_id=active_run,
        )

    if not open_tasks and unsatisfied == 0 and book_data.get("acceptance_criteria"):
        return Classification(
            state=ProjectState.COMPLETED,
            reason="no open tasks, all criteria satisfied",
            idle_minutes=idle,
            open_tasks_count=0,
            unsatisfied_criteria_count=0,
            active_resurrect_run_id=active_run,
        )

    if active_run:
        if run_status_fn is None:
            return Classification(
                state=ProjectState.IN_FLIGHT,
                reason=f"resurrect {active_run} in flight (status unchecked)",
                idle_minutes=idle,
                open_tasks_count=len(open_tasks),
                unsatisfied_criteria_count=unsatisfied,
                active_resurrect_run_id=active_run,
            )
        run_status = run_status_fn(active_run)
        # Unreachable gateway → stay IN_FLIGHT. A transient network blip
        # must NOT clear the slot and spawn a duplicate run.
        if run_status is None or run_status in _UNREACHABLE_STATES:
            return Classification(
                state=ProjectState.IN_FLIGHT,
                reason=(
                    f"resurrect {active_run} gateway unreachable "
                    f"(status={run_status!r}); holding slot"
                ),
                idle_minutes=idle,
                open_tasks_count=len(open_tasks),
                unsatisfied_criteria_count=unsatisfied,
                active_resurrect_run_id=active_run,
                run_status=run_status,
            )
        if run_status in _TERMINAL_RUN_STATES:
            return Classification(
                state=ProjectState.CRASHED,
                reason=(
                    f"resurrect {active_run} terminal "
                    f"(status={run_status!r}) but work remains"
                ),
                idle_minutes=idle,
                open_tasks_count=len(open_tasks),
                unsatisfied_criteria_count=unsatisfied,
                active_resurrect_run_id=active_run,
                run_status=run_status,
            )
        return Classification(
            state=ProjectState.IN_FLIGHT,
            reason=f"resurrect {active_run} running (status={run_status!r})",
            idle_minutes=idle,
            open_tasks_count=len(open_tasks),
            unsatisfied_criteria_count=unsatisfied,
            active_resurrect_run_id=active_run,
            run_status=run_status,
        )

    if idle >= stall_minutes:
        return Classification(
            state=ProjectState.STALLED,
            reason=(
                f"idle {idle:.1f}m >= stall threshold {stall_minutes}m, "
                f"{len(open_tasks)} open tasks"
            ),
            idle_minutes=idle,
            open_tasks_count=len(open_tasks),
            unsatisfied_criteria_count=unsatisfied,
        )

    return Classification(
        state=ProjectState.HEALTHY,
        reason=f"idle {idle:.1f}m within healthy band ({healthy_minutes}m)",
        idle_minutes=idle,
        open_tasks_count=len(open_tasks),
        unsatisfied_criteria_count=unsatisfied,
    )


def _is_stalled(book_data: Dict[str, Any], now: datetime, stall_minutes: int) -> bool:
    last_iso = book_data.get("last_activity") or book_data.get("created_at")
    last_dt = _parse_iso(last_iso)
    if last_dt is None:
        return False
    idle = (now - last_dt).total_seconds() / 60.0
    if idle < stall_minutes:
        return False
    if book_data.get("open_tasks"):
        return True
    return _unsatisfied_count(book_data) > 0


def is_stalled(book_data: Dict[str, Any], now: datetime, stall_minutes: int) -> bool:
    """Back-compat wrapper. New callers should use ``classify()``."""
    return _is_stalled(book_data, now, stall_minutes)


@dataclass
class WatchdogResult:
    checked: int = 0
    poked: List[str] = field(default_factory=list)
    skipped_active: List[str] = field(default_factory=list)
    skipped_terminal: List[str] = field(default_factory=list)
    errors: Dict[str, str] = field(default_factory=dict)
    ran_at: str = ""
    classifications: Dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "checked": self.checked,
            "poked": list(self.poked),
            "skipped_active": list(self.skipped_active),
            "skipped_terminal": list(self.skipped_terminal),
            "errors": dict(self.errors),
            "ran_at": self.ran_at,
            "classifications": dict(self.classifications),
        }


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def run_watchdog(stall_minutes: int = DEFAULT_STALL_MINUTES) -> WatchdogResult:
    """One pass: classify every project, log the verdict.

    Does NOT spawn resurrect sessions — that is the supervisor cron's
    responsibility. Kept so ``hermes omoikane tick`` still emits a
    useful one-shot summary.
    """
    result = WatchdogResult(ran_at=_utc_now().isoformat())
    provider = DashboardProvider()
    now = _utc_now()

    for entry in provider.list_projects():
        pid = entry["id"]
        result.checked += 1
        status = (entry.get("status") or "").lower()
        if status not in _ACTIVE_STATUSES:
            result.skipped_terminal.append(pid)
            continue

        try:
            book = ProjectBook(pid)
            data = book.load()
        except Exception as exc:
            logger.exception("watchdog: failed to load %s", pid)
            result.errors[pid] = f"load_failed: {exc}"
            continue

        verdict = classify(data, now, stall_minutes=stall_minutes)
        result.classifications[pid] = verdict.state.value

        if verdict.state in {ProjectState.HEALTHY, ProjectState.IN_FLIGHT}:
            result.skipped_active.append(pid)
            continue

        try:
            book.log(
                "supervisor_tick",
                f"watchdog classified {pid} as {verdict.state.value}: {verdict.reason}",
                data={**verdict.as_dict(), "via": "watchdog"},
            )
            result.poked.append(pid)
        except Exception as exc:
            logger.exception("watchdog: log failed for %s", pid)
            result.errors[pid] = f"log_failed: {exc}"

    return result
