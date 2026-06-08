"""Deterministic orchestration driver (Hybrid model).

The omoikane loop — not the LLM — drives delegation. Each round:

  1. :meth:`TeamOrchestrator.run_once` (a deterministic state machine) decides
     the next task and produces a self-contained delegation plan.
  2. The driver runs ONE focused :class:`AgentRun` for that plan's role with a
     single-task directive (a CTO for routing/kickoff tasks; a specialist for
     executor tasks). This guarantees specialists actually run — even a weak
     model produces code — because dispatch no longer depends on the LLM
     voluntarily calling ``delegate_task``.
  3. The driver deterministically closes the task (``record_result`` +
     ``complete_task``) if the agent didn't.
  4. When all work is built but criteria are still unverified, a focused QA
     pass verifies them and satisfies/refiles as needed.

A watcher thread maps a SIGTERM-driven :class:`SessionStop` onto the in-flight
``AgentRun.cancel()`` so stop is honored mid-iteration (via ``AIAgent.interrupt``).
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

from omoikane.core.book import DEFAULT_COMPLETENESS_PASS_CAP, ProjectBook
from omoikane.runtime import activity_emitter as _activity
from omoikane.runtime import injection as _injection
from omoikane.runtime import prompts as _prompts
from omoikane.runtime.agent_run import AgentRun, RunConfig

logger = logging.getLogger(__name__)


_TERMINAL_STATUSES = frozenset({"done", "failed", "cancelled"})

# Hard ceiling on focused task-executions per session when the caller doesn't
# cap it — paired with the no-progress breaker so a weak agent can't spin.
_DEFAULT_TASK_CAP = 100
# Consecutive rounds with no task closed / no criteria change → declare blocked.
_NO_PROGRESS_LIMIT = 3
# Bounded "thought-through-to-consequences" completeness passes — loop until a
# pass finds nothing new, or this many passes have run (whichever comes first).
_COMPLETENESS_PASS_CAP = DEFAULT_COMPLETENESS_PASS_CAP


@dataclass
class SessionStop:
    """Co-operatively requests the CTO loop to exit."""
    reason: str = "stop_requested"
    event: threading.Event = field(default_factory=threading.Event)

    def request(self, reason: str = "stop_requested") -> None:
        self.reason = reason
        self.event.set()

    def requested(self) -> bool:
        return self.event.is_set()


def _run_focused(
    project_id: str,
    role: str,
    directive: str,
    *,
    task_id: str,
    config: RunConfig,
    emitter,
    inbox,
    book_data,
    current: dict,
):
    """Run ONE fresh, single-task ``AgentRun`` for ``role`` and return its result.

    Registers the run in ``current`` so the stop watcher can cancel it mid-flight.
    """
    run = AgentRun(
        project_id,
        role=role,
        book=book_data,
        config=config,
        emitter=emitter,
        inbox=inbox,
    )
    current["run"] = run
    try:
        return run.run_iteration(directive, task_id=task_id, drain_target=role)
    finally:
        current["run"] = None


def run_long_session(
    project_id: str,
    *,
    config: RunConfig,
    stop: Optional[SessionStop] = None,
    max_iterations: Optional[int] = None,
    iteration_pause_seconds: float = 0.0,
) -> int:
    """Drive the project to completion deterministically. Returns rounds run.

    ``max_iterations`` caps focused task-executions (tests / smoke runs);
    ``None`` uses :data:`_DEFAULT_TASK_CAP`. A no-progress breaker stops a
    project that stalls; ``stop`` (set by SIGTERM) ends it cooperatively.
    """
    stop = stop or SessionStop()
    book = ProjectBook(project_id)
    emitter = _activity.for_project(project_id)
    inbox = _injection.InboxDrainer(project_id)

    from omoikane.core.orchestrator import TeamOrchestrator  # lazy: avoid import cycle
    orch = TeamOrchestrator(project_id)

    # Shared cell so the watcher thread can cancel whatever run is in flight.
    current: dict = {"run": None}

    def _watch() -> None:
        stop.event.wait()
        run = current.get("run")
        if run is not None:
            run.cancel()

    watcher = threading.Thread(target=_watch, name=f"omoikane-stop-{project_id}", daemon=True)
    watcher.start()

    cap = max_iterations if max_iterations is not None else _DEFAULT_TASK_CAP
    iterations = 0
    no_progress = 0

    def _blocked(summary: str) -> int:
        book.update_status("failed", phase="blocked")
        emitter.emit("orchestrator", {"event": "blocked", "summary": summary})
        return iterations

    def _completed(summary: str) -> int:
        book.update_status("done", phase="completed")
        emitter.emit("orchestrator", {"event": "completed", "summary": summary})
        return iterations

    emitter.emit("orchestrator", {
        "event": "session_start",
        "summary": f"orchestration started for {project_id}",
    })
    try:
        while True:
            if stop.requested():
                emitter.emit("orchestrator", {"event": "stop_requested", "summary": stop.reason})
                return iterations

            data = book.load()
            status = (data.get("status") or "").lower()
            if status in _TERMINAL_STATUSES:
                emitter.emit("orchestrator", {"event": "terminal", "summary": f"status={status}", "status": status})
                return iterations

            if iterations >= cap:
                emitter.emit("orchestrator", {"event": "iteration_budget_reached", "summary": f"hit cap={cap}"})
                return iterations

            open_tasks = list(data.get("open_tasks") or [])
            criteria = data.get("acceptance_criteria") or []
            all_sat = book.all_criteria_satisfied()

            # Opt-in review gate: pause ONCE after the analyst has derived
            # criteria but before the CTO commits the roadmap, so the operator
            # can inspect the completion contract. No-op when criteria were
            # operator-given (nothing to review). The driver consumes the flag
            # on pause, so `omoikane resume` simply re-enters and proceeds.
            provenance = data.get("criteria_provenance") or {}
            if (
                data.get("review_criteria")
                and criteria
                and any(p != "operator_given" for p in provenance.values())
                and not data.get("roadmap")
            ):
                emitter.emit("orchestrator", {
                    "event": "criteria_review",
                    "summary": "derived criteria awaiting operator review",
                    "criteria": criteria,
                })
                book.clear_review_criteria()
                return iterations

            # Completion gate with a bounded completeness loop: once every
            # criterion is satisfied and no tasks remain, run a completeness
            # review against the brief's intent. Repeat until a pass finds
            # nothing new (clean) or the cap is reached.
            if all_sat and not open_tasks:
                if book.completeness_satisfied(_COMPLETENESS_PASS_CAP):
                    if data.get("completeness_clean"):
                        return _completed("criteria satisfied; completeness verified")
                    book.log("note", "completeness cap reached; residual gaps may remain")
                    return _completed(
                        "criteria satisfied; completeness cap reached (possible residual gaps)"
                    )
                before = len(criteria)
                _run_focused(
                    project_id, "agent-qa-reviewer",
                    _prompts.build_completeness_directive(project_id, data),
                    task_id=f"{project_id}-completeness-{iterations}",
                    config=config, emitter=emitter, inbox=inbox,
                    book_data=data, current=current,
                )
                after = book.load()
                added = len(after.get("acceptance_criteria") or []) - before
                new_tasks = bool(after.get("open_tasks"))
                book.record_completeness_pass(clean=(added == 0 and not new_tasks))
                iterations += 1
                no_progress = 0
                continue

            # Fresh project → bootstrap the planning round.
            if status in {"created", ""}:
                orch.run_once()
                iterations += 1
                continue

            # Empty-criteria backstop: analysis drained but no completion
            # contract was written. Re-file derivation once, then fail loudly —
            # never spin the QA pass against zero criteria.
            if not open_tasks and not criteria:
                if book.derivation_retries() >= 1:
                    return _blocked(
                        "analysis produced zero acceptance criteria; cannot "
                        "derive completion contract"
                    )
                book.bump_derivation_retry()
                orch.run_once()  # _auto_decompose re-files an analyst derivation task
                iterations += 1
                continue

            # Built but unverified → deterministic QA pass.
            if not open_tasks and not all_sat:
                before_status = data.get("criteria_status") or {}
                _run_focused(
                    project_id, "agent-qa-reviewer",
                    _prompts.build_qa_directive(project_id, data),
                    task_id=f"{project_id}-qa-{iterations}",
                    config=config, emitter=emitter, inbox=inbox,
                    book_data=data, current=current,
                )
                iterations += 1
                after = book.load()
                progressed = ((after.get("criteria_status") or {}) != before_status) or bool(after.get("open_tasks"))
                no_progress = 0 if progressed else no_progress + 1
                if no_progress >= _NO_PROGRESS_LIMIT:
                    return _blocked("QA made no progress; criteria unverifiable")
                continue

            # Have open work → let the state machine plan the next delegation.
            result = orch.run_once()
            rstatus = result.get("status")
            if rstatus in {"completed", "already_done"}:
                return _completed(str(rstatus))
            if rstatus == "tasks_created":
                iterations += 1
                continue

            plan = result.get("next_delegation")
            if not plan:
                iterations += 1
                no_progress += 1
                if no_progress >= _NO_PROGRESS_LIMIT:
                    return _blocked("state machine produced no delegation")
                continue

            task = plan.get("task")
            role = plan.get("to_role") or "agent-implementer"
            completed_before = set(data.get("completed_tasks") or [])

            res = _run_focused(
                project_id, role,
                _prompts.build_task_directive(plan),
                task_id=f"{project_id}-{task}",
                config=config, emitter=emitter, inbox=inbox,
                book_data=data, current=current,
            )
            iterations += 1

            if res is not None and res.error:
                emitter.error(role, f"task {task} error: {res.error}")

            # Deterministic close: weak models often skip book_record_result /
            # book_complete_task, so the driver closes the task if still open.
            after = book.load()
            if task in (after.get("open_tasks") or []):
                summary = ((res.final_response if res else None)
                           or (res.error if res else None) or "")[:2000]
                book.record_result(task, status=("failed" if (res is None or res.error) else "done"),
                                   reflection=summary or None)
                book.complete_task(task)

            after = book.load()
            if set(after.get("completed_tasks") or []) != completed_before:
                no_progress = 0
            else:
                no_progress += 1
            if no_progress >= _NO_PROGRESS_LIMIT:
                return _blocked("no task completed across successive rounds")

            if iteration_pause_seconds > 0:
                time.sleep(iteration_pause_seconds)
    finally:
        stop.event.set()  # release the watcher thread
        emitter.emit("orchestrator", {"event": "session_end", "summary": f"iterations={iterations}"})


__all__ = [
    "SessionStop",
    "run_long_session",
]
