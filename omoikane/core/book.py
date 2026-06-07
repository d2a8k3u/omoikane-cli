"""
Omoikane - ProjectBook high-level API (M1)
"""

import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .store import ProjectStore, generate_project_id

DEFAULT_CIRCUIT_BREAKER_MINUTES = 30

# Soft target for a single specialist session. The CTO sizes tasks against
# this when filing them via book_open_task — anything materially larger
# should be filed as a small parent task that splits into children, not
# one fat task that will time out. Overridable per project via
# ``book.task_size_budget_minutes`` in book.json.
DEFAULT_TASK_SIZE_BUDGET_MINUTES = 20


class ProjectBook:
    """High-level interface to a Project Activity Book."""

    def __init__(self, project_id: str):
        self.project_id = project_id
        self.store = ProjectStore(project_id)

    @classmethod
    def create(cls, brief: str, acceptance_criteria: List[str],
               starting_state: str = "scratch", title: Optional[str] = None) -> "ProjectBook":
        """Create a new project and its Book."""
        project_id = generate_project_id()
        book = cls(project_id)
        book.store.create_book(brief, acceptance_criteria, starting_state, title)
        book.store.append_activity(
            kind="decision",
            summary=f"Project created with starting_state={starting_state}",
            actor="omoikane"
        )
        return book

    def load(self) -> Dict[str, Any]:
        """Load current book state."""
        data = self.store.load_book()
        # Forward-compat: older projects predate these fields.
        data.setdefault("roadmap", [])
        data.setdefault("pending_approvals", [])
        data.setdefault("approved_commands", [])
        data.setdefault("origin", None)
        data.setdefault("active_resurrect_run_id", None)
        data.setdefault("active_resurrect_started_at", None)
        data.setdefault("supervisor", {
            "last_tick_at": None,
            "last_action": None,
            "last_state": None,
            "consecutive_no_progress_ticks": 0,
            "circuit_breaker_tripped": False,
            "circuit_breaker_threshold_minutes": DEFAULT_CIRCUIT_BREAKER_MINUTES,
            "last_resurrect_run_id": None,
            "last_resurrect_outcome": None,
            "cron_job_id": None,
        })
        data.setdefault("task_size_budget_minutes", DEFAULT_TASK_SIZE_BUDGET_MINUTES)
        data.setdefault("split_requests", [])
        return data

    def request_approval(self, *, task_id: str, requester_role: str,
                         action: str, command: str, reason: str) -> str:
        """File an approval request from a blocked specialist.

        Returns the new approval id. Persists into ``pending_approvals`` and
        logs an ``approval_request`` activity entry so the supervisor session
        and the dashboard both see it.
        """
        approval_id = f"appr-{uuid.uuid4().hex[:8]}"
        entry = {
            "approval_id": approval_id,
            "task_id": task_id,
            "requester_role": requester_role,
            "action": action,
            "command": command,
            "reason": reason,
            "status": "pending",
            "requested_at": datetime.now(timezone.utc).isoformat(),
            "resolved_at": None,
            "resolution": None,
            "notified_at": None,
            "notified_via": None,
        }

        def _updater(data: Dict[str, Any]) -> None:
            data.setdefault("pending_approvals", []).append(entry)

        self.store.update_book(_updater)
        self.log(
            "approval_request",
            f"{requester_role} requested approval for: {action}",
            data={
                "approval_id": approval_id,
                "task_id": task_id,
                "requester_role": requester_role,
                "command": command,
                "reason": reason,
            },
        )
        return approval_id

    def resolve_approval(self, *, approval_id: str, decision: str,
                         note: Optional[str] = None) -> Dict[str, Any]:
        """Operator resolves an approval. Returns the updated entry.

        Raises ``ValueError`` for unknown id, already-resolved entry, or
        invalid decision.

        On ``decision == 'approve'`` the entry's command is appended both
        to the project-scoped ``approved_commands`` list (informational) AND
        to Hermes' global ``command_allowlist`` via
        ``tools.approval.save_permanent_allowlist`` — that's the only branch
        that actually unblocks the cron-mode gate on the next specialist
        dispatch. Operator approval is meaningless without the global write,
        so it always runs.
        """
        if decision not in {"approve", "deny"}:
            raise ValueError(f"decision must be 'approve' or 'deny', got {decision!r}")

        def _updater(data: Dict[str, Any]) -> Dict[str, Any]:
            approvals = data.setdefault("pending_approvals", [])
            entry = next(
                (a for a in approvals if a.get("approval_id") == approval_id),
                None,
            )
            if entry is None:
                raise ValueError(f"approval '{approval_id}' not found")
            if entry.get("status") != "pending":
                raise ValueError(
                    f"approval '{approval_id}' already resolved as "
                    f"{entry.get('status')!r}"
                )
            entry["status"] = decision
            entry["resolved_at"] = datetime.now(timezone.utc).isoformat()
            entry["resolution"] = note or None
            if decision == "approve":
                cmd = entry.get("command") or ""
                allowlist = data.setdefault("approved_commands", [])
                if cmd and cmd not in allowlist:
                    allowlist.append(cmd)
                if cmd:
                    entry["allowlisted_globally"] = self._extend_hermes_global_allowlist(cmd)
            return entry

        _, entry = self.store.update_book(_updater)
        self.log(
            "approval_resolved",
            f"approval {approval_id} - {decision}",
            data={
                "approval_id": approval_id,
                "decision": decision,
                "note": note,
                "allowlisted_globally": entry.get("allowlisted_globally", False),
            },
        )
        return entry

    def mark_approval_notified(self, *, approval_id: str, platform: str,
                               chat_id: str, message_id: Optional[str] = None) -> bool:
        """Supervisor records that an approval push reached the operator's channel.

        Returns False if the approval id is not found. Idempotent — calling
        twice doesn't double-mark, but the most recent timestamp wins.
        """

        def _updater(data: Dict[str, Any]) -> bool:
            entry = next(
                (a for a in data.get("pending_approvals", []) if a.get("approval_id") == approval_id),
                None,
            )
            if entry is None:
                return False
            entry["notified_at"] = datetime.now(timezone.utc).isoformat()
            entry["notified_via"] = {
                "platform": platform,
                "chat_id": chat_id,
                "message_id": message_id,
            }
            return True

        _, ok = self.store.update_book(_updater)
        return ok

    def set_active_resurrect_run_id(self, run_id: str) -> bool:
        """Check-and-set the active resurrect run id.

        Returns True if the run was recorded, False if another run is already
        in flight (caller should treat the slot as taken and not spawn).
        """

        def _updater(data: Dict[str, Any]) -> bool:
            if data.get("active_resurrect_run_id"):
                return False
            data["active_resurrect_run_id"] = run_id
            data["active_resurrect_started_at"] = datetime.now(timezone.utc).isoformat()
            return True

        _, ok = self.store.update_book(_updater)
        if ok:
            self.log(
                "supervisor_tick",
                f"resurrect spawned: run_id={run_id}",
                data={"run_id": run_id},
            )
        return ok

    def clear_active_resurrect_run_id(self, *, final_status: Optional[str] = None) -> None:
        """Clear the active resurrect slot after a run reaches a terminal state."""

        def _updater(data: Dict[str, Any]) -> Optional[str]:
            prior = data.get("active_resurrect_run_id")
            data["active_resurrect_run_id"] = None
            data["active_resurrect_started_at"] = None
            return prior

        _, prior = self.store.update_book(_updater)
        self.log(
            "supervisor_tick",
            f"resurrect cleared (prior run={prior}, final={final_status})",
            data={"prior_run": prior, "final_status": final_status},
        )

    # === Task splitting (CTO-mediated) ===

    def request_split(
        self,
        *,
        task_id: str,
        requester_role: str,
        reason: str,
        suggested_subtasks: Optional[List[Dict[str, Any]]] = None,
    ) -> Optional[str]:
        """Specialist (or manager) flags a task as too big to finish in one
        specialist session. Returns the routing-task id filed to CTO, or
        ``None`` when the original task is unknown.

        Behavior:

        * ``task_meta[task_id]["split_status"]`` flips to ``"requested"`` —
          the orchestrator skips re-dispatching this task until CTO acts.
        * An entry is appended to ``data["split_requests"]`` so the
          dashboard / supervisor / audit log can see who asked for what.
        * A routing task is opened on CTO's desk via the existing
          ``open_task`` path (``assignee_role='agent-cto'``,
          ``routing_status='routing'``, ``phase='meta'``). Its title is
          ``"Split task <tid>: <one-line reason>"`` and its
          ``execution_metadata`` carries the reason + suggested subtasks
          so CTO sees them in its context next tick.

        Idempotent: a second call on an already-flagged task replaces the
        latest reason / suggested_subtasks but does not file another
        routing task.
        """

        suggested = list(suggested_subtasks or [])
        request_payload = {
            "task_id": task_id,
            "requester_role": requester_role,
            "reason": reason,
            "suggested_subtasks": suggested,
            "requested_at": datetime.now(timezone.utc).isoformat(),
            "status": "pending",
        }

        def _updater(data: Dict[str, Any]) -> Optional[str]:
            meta = data.get("task_meta", {}).get(task_id)
            if meta is None:
                return None
            already_flagged = meta.get("split_status") == "requested"
            meta["split_status"] = "requested"
            meta["split_reason"] = reason
            meta["split_requested_by"] = requester_role
            meta["split_requested_at"] = request_payload["requested_at"]
            data.setdefault("task_meta", {})[task_id] = meta
            data.setdefault("split_requests", []).append(request_payload)
            return "existing" if already_flagged else "new"

        _, kind = self.store.update_book(_updater)
        if kind is None:
            return None

        if kind == "existing":
            self.log(
                "note",
                f"Split request updated for {task_id} (by {requester_role})",
                data={"task": task_id, "reason": reason, "suggested_subtasks": suggested},
            )
            # Don't file a duplicate routing task; CTO already has one open.
            return None

        routing_task_id = self.open_task(
            title=f"Split task {task_id}: {reason[:120]}",
            assignee_role="agent-cto",
            phase="meta",
            routing_status="routing",
            requester_role=requester_role,
            rationale=(
                f"Specialist {requester_role} flagged task {task_id} as "
                f"too large for one session. Reason: {reason}. "
                f"Suggested split into {len(suggested)} subtasks."
            ),
            execution_metadata={
                "kind": "split_request",
                "original_task": task_id,
                "reason": reason,
                "suggested_subtasks": suggested,
            },
        )
        self.log(
            "decision",
            f"Split requested for {task_id} by {requester_role}",
            data={
                "task": task_id,
                "routing_task": routing_task_id,
                "reason": reason,
                "suggested_subtasks": suggested,
            },
        )
        return routing_task_id

    def split_task(
        self,
        *,
        task_id: str,
        replacement_specs: List[Dict[str, Any]],
        requester_role: str,
        reflection: Optional[str] = None,
    ) -> Optional[List[str]]:
        """CTO replaces an oversized task with N children. Returns the
        list of child task ids, or ``None`` if the original is unknown.

        Each ``replacement_specs`` entry must carry ``title`` and
        ``assignee_role``; optional fields: ``phase``, ``estimated_minutes``,
        ``execution_metadata`` (merged), ``blocked_by`` (list of indices
        into ``replacement_specs`` — converted to real task ids after
        children are created), ``milestone_id``.

        Atomicity: original task moves from ``open_tasks`` to
        ``completed_tasks`` with ``task_meta[task_id]["closure_kind"] =
        "split"`` and ``task_meta[task_id]["split_into"] = [<child ids>]``
        in the SAME update as opening the children, so a crash mid-split
        can never produce orphan or duplicate work.
        """

        if not replacement_specs:
            return None

        now_iso = datetime.now(timezone.utc).isoformat()

        # Validate specs up-front so we don't half-commit.
        for i, spec in enumerate(replacement_specs):
            if not isinstance(spec, dict):
                raise ValueError(f"replacement_specs[{i}] must be a dict")
            if not spec.get("title"):
                raise ValueError(f"replacement_specs[{i}].title is required")
            if not spec.get("assignee_role"):
                raise ValueError(
                    f"replacement_specs[{i}].assignee_role is required"
                )

        def _updater(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
            meta = data.get("task_meta", {}).get(task_id)
            if meta is None:
                return None

            # Generate unique child ids in this single critical section.
            existing = set(data.get("open_tasks", []) + data.get("completed_tasks", []))
            base = len(existing)
            child_ids: List[str] = []
            cursor = 0
            while len(child_ids) < len(replacement_specs):
                candidate = f"task-{1000 + base + cursor:04d}"
                cursor += 1
                if candidate in existing or candidate in child_ids:
                    continue
                child_ids.append(candidate)
                existing.add(candidate)

            # Open children. ``blocked_by`` entries that look like ints are
            # treated as indices into the sibling list; everything else is
            # passed through verbatim (must already be a real task id).
            for i, spec in enumerate(replacement_specs):
                child_id = child_ids[i]
                blocked_by_raw = spec.get("blocked_by") or []
                resolved_blocked_by: List[str] = []
                for entry in blocked_by_raw:
                    if isinstance(entry, int) and 0 <= entry < len(child_ids):
                        resolved_blocked_by.append(child_ids[entry])
                    else:
                        resolved_blocked_by.append(str(entry))
                child_meta: Dict[str, Any] = {
                    "title": spec["title"],
                    "assignee_role": spec["assignee_role"],
                    "parent": task_id,
                    "phase": spec.get("phase") or meta.get("phase"),
                    "routing_status": "assigned",
                    "created_at": now_iso,
                    "milestone_id": spec.get("milestone_id") or meta.get("milestone_id"),
                }
                if resolved_blocked_by:
                    child_meta["blocked_by"] = resolved_blocked_by
                exec_meta = dict(spec.get("execution_metadata") or {})
                if spec.get("estimated_minutes") is not None:
                    exec_meta["estimated_minutes"] = spec["estimated_minutes"]
                if exec_meta:
                    child_meta["execution_metadata"] = exec_meta
                data.setdefault("open_tasks", []).append(child_id)
                data.setdefault("task_meta", {})[child_id] = child_meta

            # Close the parent atomically.
            open_tasks = data.setdefault("open_tasks", [])
            if task_id in open_tasks:
                open_tasks.remove(task_id)
            completed = data.setdefault("completed_tasks", [])
            if task_id not in completed:
                completed.append(task_id)
            meta["closed_at"] = now_iso
            meta["closure_kind"] = "split"
            meta["split_into"] = list(child_ids)
            meta["split_status"] = "resolved"
            meta["split_resolved_by"] = requester_role
            meta["split_resolved_at"] = now_iso
            data.setdefault("task_meta", {})[task_id] = meta

            # Mark the pending split_request entry as resolved.
            for entry in data.get("split_requests", []) or []:
                if entry.get("task_id") == task_id and entry.get("status") == "pending":
                    entry["status"] = "resolved"
                    entry["resolved_at"] = now_iso
                    entry["resolved_by"] = requester_role
                    entry["split_into"] = list(child_ids)

            return {"child_ids": child_ids, "parent_meta": meta}

        _, result = self.store.update_book(_updater)
        if result is None:
            return None

        child_ids = result["child_ids"]
        self.log(
            "decision",
            (
                f"CTO split {task_id} into {len(child_ids)} children: "
                + ", ".join(child_ids)
            ),
            data={
                "task": task_id,
                "split_into": child_ids,
                "requester_role": requester_role,
                "reflection": reflection,
            },
        )
        if reflection:
            self.reflect(reflection, task=task_id)
        return child_ids

    def list_pending_split_requests(self) -> List[Dict[str, Any]]:
        return [
            entry for entry in self.load().get("split_requests", []) or []
            if entry.get("status") == "pending"
        ]

    # === Supervisor heartbeat + circuit breaker ===

    def record_supervisor_tick(
        self,
        *,
        state: str,
        action: str,
        run_id: Optional[str] = None,
        outcome: Optional[str] = None,
        progressed: bool = False,
    ) -> Dict[str, Any]:
        """Persist one supervisor tick into the Book.

        ``state`` is the classifier verdict (e.g. ``'healthy'`` / ``'stalled'``
        / ``'crashed'`` / ``'in_flight'`` / ``'completed'``). ``action`` is
        what the supervisor did about it (``'noop'``, ``'stalled_respawn'``,
        ``'crashed_respawn'``, ``'completed_teardown'``, ``'circuit_break'``,
        ``'error'``).

        ``progressed`` resets the no-progress counter. The supervisor sets
        it True when the previous tick's resurrect closed tasks or when
        ``last_activity`` advanced since the prior tick.

        Returns the updated supervisor sub-dict.
        """

        def _updater(data: Dict[str, Any]) -> Dict[str, Any]:
            sup = data.setdefault("supervisor", {})
            sup["last_tick_at"] = datetime.now(timezone.utc).isoformat()
            sup["last_state"] = state
            sup["last_action"] = action
            if run_id is not None:
                sup["last_resurrect_run_id"] = run_id
            if outcome is not None:
                sup["last_resurrect_outcome"] = outcome
            if progressed:
                sup["consecutive_no_progress_ticks"] = 0
            else:
                sup["consecutive_no_progress_ticks"] = (
                    int(sup.get("consecutive_no_progress_ticks") or 0) + 1
                )
            return dict(sup)

        _, sup = self.store.update_book(_updater)
        return sup

    def trip_circuit_breaker(self, reason: str) -> None:
        """Mark the project ``blocked`` and stop auto-nudging it.

        The supervisor calls this once ``consecutive_no_progress_ticks``
        exceeds the configured threshold so the operator gets paged
        instead of an infinite respawn loop.
        """

        def _updater(data: Dict[str, Any]) -> None:
            sup = data.setdefault("supervisor", {})
            sup["circuit_breaker_tripped"] = True
            sup["circuit_breaker_reason"] = reason
            sup["circuit_breaker_tripped_at"] = datetime.now(timezone.utc).isoformat()
            data["status"] = "blocked"

        self.store.update_book(_updater)
        self.log(
            "decision",
            f"Circuit breaker tripped: {reason}",
            data={"reason": reason},
        )

    def set_cron_job_id(self, job_id: Optional[str]) -> None:
        """Record the cron job id created for this project (or clear it)."""

        def _updater(data: Dict[str, Any]) -> None:
            data.setdefault("supervisor", {})["cron_job_id"] = job_id

        self.store.update_book(_updater)

    def supervisor_state(self) -> Dict[str, Any]:
        """Read-only snapshot of the supervisor field."""
        return dict(self.load().get("supervisor") or {})

    def ticks_until_circuit_break(self, tick_interval_minutes: float) -> int:
        """How many more no-progress ticks until the breaker trips.

        Returns ``-1`` once the breaker has already tripped.
        """
        sup = self.supervisor_state()
        if sup.get("circuit_breaker_tripped"):
            return -1
        threshold_min = float(
            sup.get("circuit_breaker_threshold_minutes")
            or DEFAULT_CIRCUIT_BREAKER_MINUTES
        )
        if tick_interval_minutes <= 0:
            return 0
        budget = int(threshold_min // tick_interval_minutes)
        used = int(sup.get("consecutive_no_progress_ticks") or 0)
        return max(0, budget - used)

    @staticmethod
    def _extend_hermes_global_allowlist(pattern: str) -> bool:
        """No-op shim retained for ABI compatibility with the Hermes plugin.

        In the standalone Omoikane CLI there is no host-level command
        allowlist — approval gating is mediated by per-project state and the
        operator transport. Always returns ``False`` so callers fall back to
        their local approval bookkeeping.
        """
        return False

    def log(self, kind: str, summary: str, data: Optional[Dict] = None):
        """Append an entry to the activity log."""
        self.store.append_activity(kind=kind, summary=summary, data=data)

    def update_status(self, status: str, phase: Optional[str] = None):
        """Update project status and optionally phase."""

        def _updater(data: Dict[str, Any]) -> None:
            data["status"] = status
            if phase:
                data["current_phase"] = phase

        self.store.update_book(_updater)

    def satisfy_criterion(self, index: int, evidence: Optional[str] = None) -> bool:
        """Mark an acceptance criterion as satisfied. Returns False if index out of range."""

        def _updater(data: Dict[str, Any]) -> Optional[str]:
            criteria = data.get("acceptance_criteria", [])
            if index < 0 or index >= len(criteria):
                return None
            status = data.setdefault("criteria_status", {})
            status[str(index)] = "satisfied"
            data.setdefault("supervisor", {})["consecutive_no_progress_ticks"] = 0
            return criteria[index]

        _, criterion_text = self.store.update_book(_updater)
        if criterion_text is not None:
            self.log(
                "decision",
                f"Acceptance criterion {index} satisfied",
                data={"criterion": criterion_text, "evidence": evidence},
            )
            return True
        return False

    def all_criteria_satisfied(self) -> bool:
        """True only when every acceptance criterion has status == 'satisfied'."""
        data = self.load()
        criteria = data.get("acceptance_criteria", [])
        status = data.get("criteria_status", {})
        if not criteria:
            return False
        return all(status.get(str(i)) == "satisfied" for i in range(len(criteria)))

    @property
    def status(self) -> str:
        return self.load().get("status", "unknown")

    @property
    def current_phase(self) -> str:
        return self.load().get("current_phase", "unknown")

    # === Task management (spec §8) ===

    def open_task(self, title: str, assignee_role: Optional[str] = None,
                  parent: Optional[str] = None,
                  phase: Optional[str] = None,
                  routing_status: str = "assigned",
                  requester_role: Optional[str] = None,
                  rationale: Optional[str] = None,
                  suggested_role: Optional[str] = None,
                  blocked_by: Optional[List[str]] = None,
                  milestone_id: Optional[str] = None,
                  execution_metadata: Optional[Dict[str, Any]] = None) -> str:
        """Create a new task. Returns the task id.

        ``phase`` tags the task with one of the orchestrator's phase buckets
        (analysis / design / implementation / testing / review / meta) so
        ``TeamOrchestrator`` can compute the current phase from the open set.

        ``routing_status`` defaults to ``'assigned'`` (the legacy behaviour) but
        flips to ``'routing'`` for tasks that were filed via
        ``request_task`` — those land on CTO's desk and must be re-assigned via
        ``assign_task`` before they're dispatched to an executor.

        ``blocked_by`` is the list of task ids that must close before this task
        becomes eligible for dispatch. ``_pick_next_task`` / ``_advance_phase``
        skip any task with at least one entry still in ``open_tasks``.

        ``milestone_id`` links an executor task to a roadmap milestone (set
        by the CTO via ``book_set_roadmap``) for dashboard grouping.

        ``execution_metadata`` is an optional dict of structured signals
        (``estimated_minutes``, ``requires_network``, ``dangerous_commands``,
        ``background``) that the orchestrator passes to
        ``choose_execution_mode`` when planning the delegation.
        """

        def _updater(data: Dict[str, Any]) -> str:
            existing = set(data.get("open_tasks", []) + data.get("completed_tasks", []))
            base = len(existing)
            candidate = None
            for i in range(base + 1):
                tid = f"task-{1000 + base + i:04d}"
                if tid not in existing:
                    candidate = tid
                    break
            if candidate is None:
                raise RuntimeError("Unable to generate unique task id")
            task_id = candidate
            data.setdefault("open_tasks", []).append(task_id)
            meta: Dict[str, Any] = {
                "title": title,
                "assignee_role": assignee_role,
                "parent": parent,
                "phase": phase,
                "routing_status": routing_status,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            if requester_role is not None:
                meta["requester_role"] = requester_role
            if rationale is not None:
                meta["rationale"] = rationale
            if suggested_role is not None:
                meta["suggested_role"] = suggested_role
            if blocked_by:
                meta["blocked_by"] = list(blocked_by)
            if milestone_id is not None:
                meta["milestone_id"] = milestone_id
            if execution_metadata is not None:
                meta["execution_metadata"] = dict(execution_metadata)
            data.setdefault("task_meta", {})[task_id] = meta
            return task_id

        _, task_id = self.store.update_book(_updater)
        self.log(
            "note",
            f"Opened task {task_id}: {title}",
            data={
                "task": task_id,
                "assignee_role": assignee_role,
                "parent": parent,
                "phase": phase,
                "routing_status": routing_status,
                "blocked_by": blocked_by,
                "milestone_id": milestone_id,
                "execution_metadata": execution_metadata,
            },
        )
        return task_id

    def request_task(self, title: str, requester_role: str, rationale: str,
                     suggested_role: Optional[str] = None,
                     execution_metadata: Optional[Dict[str, Any]] = None) -> str:
        """File a routing task that lands on CTO's desk.

        Any agent can call this to surface new work without picking the
        executor themselves. CTO sees the task next tick and calls
        :meth:`assign_task` to pick the real assignee.

        ``execution_metadata`` is an optional dict of structured signals
        that the orchestrator / CTO can forward into the final executor
        task (e.g. ``estimated_minutes``) when it is assigned.
        """
        task_id = self.open_task(
            title=title,
            assignee_role="agent-cto",
            phase="meta",
            routing_status="routing",
            requester_role=requester_role,
            rationale=rationale,
            suggested_role=suggested_role,
            execution_metadata=execution_metadata,
        )
        suffix = f" (suggested: {suggested_role})" if suggested_role else ""
        self.log(
            "note",
            f"Task requested by {requester_role} - routing to CTO{suffix}",
            data={
                "task": task_id,
                "requester_role": requester_role,
                "suggested_role": suggested_role,
                "rationale": rationale,
            },
        )
        return task_id

    def assign_task(self, task_id: str, role: str) -> bool:
        """Flip a routing task to an assigned executor. CTO's prerogative.

        Returns False when the task does not exist or is not in routing
        state — the caller should treat that as a no-op rather than an error.
        """

        def _updater(data: Dict[str, Any]) -> Optional[str]:
            meta = data.get("task_meta", {}).get(task_id)
            if meta is None:
                return None
            if meta.get("routing_status") != "routing":
                return None
            previous = meta.get("assignee_role")
            meta["assignee_role"] = role
            meta["routing_status"] = "assigned"
            meta["assigned_at"] = datetime.now(timezone.utc).isoformat()
            data.setdefault("task_meta", {})[task_id] = meta
            return previous

        _, previous = self.store.update_book(_updater)
        if previous is not None:
            self.log(
                "decision",
                f"CTO routed {task_id} to {role}",
                data={"task": task_id, "previous": previous, "assignee_role": role},
            )
            return True
        return False

    def set_phase(self, phase: str) -> bool:
        """Persist a phase change. Idempotent — only logs when it actually
        moves. Returns True iff the phase was updated."""

        def _updater(data: Dict[str, Any]) -> Optional[str]:
            current = data.get("current_phase")
            if current == phase:
                return None
            data["current_phase"] = phase
            return current

        _, current = self.store.update_book(_updater)
        if current is not None:
            self.log(
                "phase_change",
                f"Phase advanced: {current} - {phase}",
                data={"previous": current, "current": phase},
            )
            return True
        return False

    def record_result(
        self,
        task: str,
        status: str,
        reflection: Optional[str] = None,
    ) -> Optional[str]:
        """Close a delegation edge: log the result, store the reflection, and
        record the outcome on the delegation tree.

        Mirrors the ``book_record_result`` tool handler so the deterministic
        orchestration driver can close tasks itself without depending on the
        agent to call the tool. Returns the reflection ref (if any).
        """
        self.log(
            kind="result",
            summary=f"Task {task} finished with status={status}",
            data={"status": status, "reflection": reflection},
        )
        reflection_ref = self.reflect(lesson=reflection, task=task) if reflection else None
        self.store.record_delegation_result(
            task=task,
            status=status,
            reflection_ref=reflection_ref,
        )
        return reflection_ref

    def complete_task(self, task_id: str) -> bool:
        """Move a task from open to completed. Returns False if not open.

        Completion is a progress signal — the supervisor's no-progress
        counter is reset so a project that's actually moving doesn't
        trip the circuit breaker.
        """

        def _updater(data: Dict[str, Any]) -> bool:
            open_tasks = data.setdefault("open_tasks", [])
            if task_id not in open_tasks:
                return False
            open_tasks.remove(task_id)
            data.setdefault("completed_tasks", []).append(task_id)
            meta = data.setdefault("task_meta", {}).get(task_id, {})
            meta["closed_at"] = datetime.now(timezone.utc).isoformat()
            data.setdefault("task_meta", {})[task_id] = meta
            data.setdefault("supervisor", {})["consecutive_no_progress_ticks"] = 0
            return True

        _, ok = self.store.update_book(_updater)
        if ok:
            self.log("result", f"Completed task {task_id}",
                     data={"task": task_id})
        return ok

    # === Roadmap (Omoikane M6) ===

    def set_roadmap(self, milestones: List[Dict[str, Any]]) -> int:
        """Commit a roadmap of milestones. Overwrites prior roadmap in full.

        Each entry must carry ``milestone_id`` (unique string) and ``title``.
        Optional fields: ``description``, ``criteria_indices`` (list of ints),
        ``status`` (defaults to ``'planned'``).

        Returns the number of milestones committed. Raises ``ValueError`` when
        a milestone is missing a required field or duplicates an id.
        """
        normalized: List[Dict[str, Any]] = []
        seen_ids = set()
        for i, entry in enumerate(milestones or []):
            if not isinstance(entry, dict):
                raise ValueError(f"milestone[{i}] must be an object, got {type(entry).__name__}")
            mid = entry.get("milestone_id")
            title = entry.get("title")
            if not mid or not isinstance(mid, str):
                raise ValueError(f"milestone[{i}].milestone_id is required (non-empty string)")
            if mid in seen_ids:
                raise ValueError(f"milestone_id {mid!r} duplicated")
            seen_ids.add(mid)
            if not title or not isinstance(title, str):
                raise ValueError(f"milestone[{i}].title is required (non-empty string)")
            normalized.append({
                "milestone_id": mid,
                "title": title,
                "description": entry.get("description", ""),
                "criteria_indices": list(entry.get("criteria_indices") or []),
                "status": entry.get("status") or "planned",
            })

        def _updater(data: Dict[str, Any]) -> None:
            data["roadmap"] = normalized

        self.store.update_book(_updater)
        self.log(
            "decision",
            f"Roadmap committed: {len(normalized)} milestones",
            data={"milestone_count": len(normalized),
                  "milestone_ids": [m["milestone_id"] for m in normalized]},
        )
        return len(normalized)

    # === Artifacts ===

    def add_artifact(self, path: str, kind: str, note: Optional[str] = None) -> str:
        """Register an artifact. If `path` is an absolute file, copies it under
        artifacts/. If relative, treats it as a path inside artifacts/. Returns
        the artifact's stored path relative to the project dir."""
        artifacts_dir = self.store.project_dir / "artifacts"
        artifacts_dir.mkdir(parents=True, exist_ok=True)

        src = Path(path)
        if src.is_absolute():
            if not src.is_file():
                raise RuntimeError(f"Artifact source not found: {src}")
            dest = artifacts_dir / src.name
            try:
                shutil.copy2(src, dest)
            except (OSError, shutil.Error) as exc:
                raise RuntimeError(f"Failed to copy artifact {src} to {dest}: {exc}") from exc
            stored_rel = f"artifacts/{src.name}"
        else:
            # Treat as logical path inside artifacts/
            stored_rel = f"artifacts/{Path(path).name}"

        def _updater(data: Dict[str, Any]) -> str:
            data.setdefault("artifacts", []).append({
                "path": stored_rel,
                "kind": kind,
                "note": note,
                "added_at": datetime.now(timezone.utc).isoformat(),
            })
            return stored_rel

        _, rel = self.store.update_book(_updater)
        self.log("note", f"Artifact registered: {stored_rel}",
                 data={"path": stored_rel, "kind": kind, "note": note})
        return rel

    # === Reflections ===

    def reflect(self, lesson: str, task: Optional[str] = None) -> str:
        """Persist a reflection under reflections/ and log it."""
        refl_dir = self.store.project_dir / "reflections"
        refl_dir.mkdir(parents=True, exist_ok=True)

        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        suffix = task or "general"
        fname = f"r-{ts}-{suffix}.md"
        (refl_dir / fname).write_text(lesson, encoding="utf-8")

        ref = f"reflections/{fname}"
        self.log("reflection", f"Reflection captured ({suffix})",
                 data={"task": task, "ref": ref})
        return ref
