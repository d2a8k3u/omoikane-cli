"""Long-lived CTO session — Mode A driver.

Holds a single :class:`omoikane.runtime.agent_run.AgentRun` for the
project's lifetime, persists its ``conversation_history`` across
iterations and across daemon restarts, and exits on terminal status or
all-criteria-satisfied.

The actual delegation to specialists is handled by the SDK's built-in
``delegate_task`` — Phase 0 spike C confirmed the toolset inheritance
works as long as the CTO's ``enabled_toolsets`` is the union of every
specialist toolset (handled by :func:`runtime.role_toolsets.cto_toolsets`).
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Optional

from omoikane.core.book import ProjectBook
from omoikane.runtime import activity_emitter as _activity
from omoikane.runtime import injection as _injection
from omoikane.runtime import prompts as _prompts
from omoikane.runtime.agent_run import AgentRun, RunConfig

logger = logging.getLogger(__name__)


_TERMINAL_STATUSES = frozenset({"done", "failed", "cancelled"})


@dataclass
class SessionStop:
    """Co-operatively requests the CTO loop to exit."""
    reason: str = "stop_requested"
    event: threading.Event = threading.Event()

    def request(self, reason: str = "stop_requested") -> None:
        self.reason = reason
        self.event.set()

    def requested(self) -> bool:
        return self.event.is_set()


def run_long_session(
    project_id: str,
    *,
    config: RunConfig,
    stop: Optional[SessionStop] = None,
    max_iterations: Optional[int] = None,
    iteration_pause_seconds: float = 0.0,
) -> int:
    """Drive the CTO until the project finishes or ``stop`` is signalled.

    Returns the number of CTO iterations that actually ran. ``max_iterations``
    caps the loop for tests / smoke runs; ``None`` lets the loop run until
    the project status is terminal or ``stop`` flips.
    """
    stop = stop or SessionStop()
    book_handle = ProjectBook(project_id)
    emitter = _activity.for_project(project_id)
    inbox = _injection.InboxDrainer(project_id)

    book_data = book_handle.load()
    history = _prompts.load_cto_history(project_id)

    run = AgentRun(
        project_id,
        role="agent-cto",
        book=book_data,
        config=config,
        emitter=emitter,
        inbox=inbox,
        conversation_history=history,
    )

    iterations = 0
    emitter.emit("orchestrator", {
        "event": "session_start",
        "summary": f"CTO session started for {project_id}",
    })

    try:
        while True:
            if stop.requested():
                emitter.emit("orchestrator", {
                    "event": "stop_requested",
                    "summary": stop.reason,
                })
                return iterations

            book_data = book_handle.load()
            status = (book_data.get("status") or "").lower()
            if status in _TERMINAL_STATUSES:
                emitter.emit("orchestrator", {
                    "event": "terminal",
                    "summary": f"status={status}",
                    "status": status,
                })
                return iterations
            if status in {"created", ""}:
                # Lift the status off "created" so the watchdog stops
                # treating us as a never-started run.
                book_handle.update_status("in_progress")
                book_data = book_handle.load()

            if iterations == 0:
                directive = _prompts.build_initial_directive(project_id, book_data)
            else:
                directive = _prompts.build_followup_directive(project_id, book_data)

            result = run.run_iteration(
                directive,
                task_id=f"{project_id}-cto-{iterations}",
                drain_target="agent-cto",
            )
            iterations += 1
            _prompts.save_cto_history(project_id, run.history)

            if result.error:
                emitter.error("agent-cto", f"iteration error: {result.error}")
                # Don't tight-loop on errors.
                time.sleep(min(5.0, max(iteration_pause_seconds, 1.0)))
                continue

            book_data = book_handle.load()
            if book_handle.all_criteria_satisfied() and not (book_data.get("open_tasks") or []):
                book_handle.update_status("done", phase="completed")
                emitter.emit("orchestrator", {
                    "event": "completed",
                    "summary": "All acceptance criteria satisfied",
                })
                return iterations

            if max_iterations is not None and iterations >= max_iterations:
                emitter.emit("orchestrator", {
                    "event": "iteration_budget_reached",
                    "summary": f"hit max_iterations={max_iterations}",
                })
                return iterations

            if iteration_pause_seconds > 0:
                time.sleep(iteration_pause_seconds)
    finally:
        _prompts.save_cto_history(project_id, run.history)
        emitter.emit("orchestrator", {
            "event": "session_end",
            "summary": f"iterations={iterations}",
        })


__all__ = [
    "SessionStop",
    "run_long_session",
]
