"""
Omoikane — Tool handlers (standalone CLI port).

Each function below implements one tool registered against the
hermes-agent SDK's ``tools.registry`` from
:func:`omoikane.tools.register_book_tools`. Handlers follow the SDK
contract: ``handler(args: dict, **kwargs) -> str``, where ``args`` is
the validated JSON-Schema payload and the return value is a JSON string
the model parses.

Differences from the original Hermes plugin:

- Origin capture is delegated to :mod:`omoikane.tools.audit` and no
  longer reads Hermes session ContextVars.
- Session ↔ project binding goes through :mod:`omoikane.tools.session`
  (a process-local dict) instead of ``omoikane.hooks``.
- Project supervisor scheduling is owned by :mod:`omoikane.supervisor`
  (one global tick iterates all projects); ``project_start`` returns
  ``supervisor_cron_id=None``.
"""
from __future__ import annotations

import json
import logging
from typing import Optional, Tuple

from omoikane.core.agents_registry import get_registry
from omoikane.core.book import ProjectBook
from omoikane.core.execution import choose_execution_mode
from omoikane.core.orchestrator import TeamOrchestrator

from .audit import capture_origin

logger = logging.getLogger(__name__)


def _ensure_project_cron_safe(project_id: str) -> Tuple[Optional[str], Optional[str]]:
    """No-op: per-project cron is not used.

    Returns ``(None, None)`` — no cron is registered, no error is
    reported. :func:`omoikane.supervisor.install` owns the global
    supervisor schedule; per-project cron records are intentionally
    removed from the design (one global tick iterates all projects from
    the SQLite index).
    """
    return None, None


def _remove_project_cron_safe(project_id: str) -> Tuple[bool, Optional[str]]:
    """No-op. See :func:`_ensure_project_cron_safe`."""
    return True, None


def _capture_origin(kwargs: Optional[dict] = None) -> Optional[dict]:
    """Compatibility wrapper around :func:`omoikane.tools.audit.capture_origin`.

    Kept under the legacy single-underscore name so the ported handler
    bodies below can call it without further edits.
    """
    return capture_origin(kwargs)


def project_start(args: dict, **kwargs) -> str:
    """Create a new Project Book and start the run."""
    try:
        brief = (args.get("brief") or "").strip()
        if not brief:
            return json.dumps({"error": "brief is required"})

        # Criteria are optional. When omitted, the product analyst derives them
        # from the brief during the analysis phase (see agent-product-analyst).
        criteria = args.get("acceptance_criteria") or []
        state = args.get("starting_state", "scratch")
        review_criteria = bool(args.get("review_criteria"))

        book = ProjectBook.create(
            brief=brief,
            acceptance_criteria=criteria,
            starting_state=state,
        )

        # Opt-in one-shot pause: the driver surfaces the derived criteria and
        # stops once before committing the roadmap so the operator can review.
        if review_criteria:
            def _set_review(data: dict) -> None:
                data["review_criteria"] = True

            book.store.update_book(_set_review)

        # Capture origin platform + chat_id so the supervisor can route
        # approval pushes back to the operator's main channel.
        origin = _capture_origin(kwargs)
        if origin:
            data = book.load()
            data["origin"] = origin
            book.store.save_book(data)
            book.log(
                "decision",
                f"Origin captured: {origin['platform']}:{origin.get('chat_id') or '-'}",
                data={"origin": origin},
            )

        book.log("decision", f"Project started with {len(criteria)} acceptance criteria")

        # Kick the first orchestration iteration (bootstrap initial tasks).
        first_tick = TeamOrchestrator(book.project_id).run_once()

        # Intentional no-op: _ensure_project_cron_safe returns
        # (None, None). Per-project cron records were removed from the design;
        # the global supervisor (omoikane.supervisor) owns scheduling
        # and iterates all projects from the SQLite index on each tick. The
        # returned keys are kept for return-shape compatibility.
        cron_id, cron_err = _ensure_project_cron_safe(book.project_id)

        return json.dumps({
            "project_id": book.project_id,
            "status": book.status,
            "phase": book.current_phase,
            "tick": first_tick,
            "supervisor_cron_id": cron_id,
            "supervisor_cron_error": cron_err,
            "message": (
                "Project Book created. Call project_continue with this "
                "project_id to receive the first delegation plan, then "
                "dispatch it via delegate_task."
            ),
        })

    except Exception as e:
        return json.dumps({"error": f"project_start failed: {str(e)}"})


def project_status(args: dict, **kwargs) -> str:
    """Return current status of a project."""
    try:
        project_id = args.get("project_id")
        if not project_id:
            return json.dumps({"error": "project_id is required"})

        book = ProjectBook(project_id)
        data = book.load()

        return json.dumps({
            "project_id": project_id,
            "title": data.get("title"),
            "status": data.get("status"),
            "current_phase": data.get("current_phase"),
            "open_tasks": len(data.get("open_tasks", [])),
            "completed_tasks": len(data.get("completed_tasks", [])),
            "last_activity": data.get("last_activity"),
            "blockers": data.get("blockers", [])
        })

    except Exception as e:
        return json.dumps({"error": f"project_status failed: {str(e)}"})


def book_log(args: dict, **kwargs) -> str:
    """Append a log entry to the active project book."""
    try:
        project_id = args.get("project_id")
        if not project_id:
            return json.dumps({"error": "project_id is required for book_log in M1"})

        kind = args.get("kind")
        summary = args.get("summary")
        data = args.get("data")

        book = ProjectBook(project_id)
        book.log(kind=kind, summary=summary, data=data)

        return json.dumps({"success": True, "logged": True})

    except Exception as e:
        return json.dumps({"error": f"book_log failed: {str(e)}"})


# === M3/M5: Delegation tools ===

def book_delegate(args: dict, **kwargs) -> str:
    """Record a delegation in the Project Book (with execution mode decision)."""
    try:
        project_id = args.get("project_id")
        task = args.get("task")
        to_role = args.get("to_role")
        expected = args.get("expected")
        mode = args.get("mode")

        if not all([project_id, task, to_role, expected]):
            return json.dumps({"error": "Missing required fields"})

        # M5: Auto-decide mode if not provided. Inspect the textual `expected`
        # description rather than the opaque task id.
        if not mode:
            mode = choose_execution_mode({"title": f"{task} {expected}", "expected": expected})

        registry = get_registry()
        skill_content = registry.get_skill_content(to_role)

        book = ProjectBook(project_id)
        book.log(
            kind="delegation",
            summary=f"Delegated '{task}' to {to_role} (mode={mode})",
            data={
                "to_role": to_role,
                "expected": expected,
                "mode": mode,
                "has_skill": bool(skill_content),
            },
        )
        # Mirror into the delegation tree (spec §5.5)
        node_id = book.store.add_delegation(
            task=task,
            to_role=to_role,
            expected=expected,
            mode=mode,
        )

        # M5: Record whether this will be isolated or in-process
        if mode == "isolated":
            book.log(
                kind="note",
                summary=f"Task '{task}' scheduled as isolated execution",
                data={"requires_background": True},
            )

        return json.dumps({
            "success": True,
            "delegated": True,
            "to_role": to_role,
            "mode": mode,
            "node": node_id,
        })

    except Exception as e:
        return json.dumps({"error": f"book_delegate failed: {str(e)}"})


def book_record_result(args: dict, **kwargs) -> str:
    """Record the result of a delegated task."""
    try:
        project_id = args.get("project_id")
        task = args.get("task")
        status = args.get("status")
        reflection = args.get("reflection")

        if not all([project_id, task, status]):
            return json.dumps({"error": "Missing required fields"})

        book = ProjectBook(project_id)
        reflection_ref = book.record_result(task=task, status=status, reflection=reflection)

        return json.dumps({"success": True, "recorded": True, "reflection_ref": reflection_ref})

    except Exception as e:
        return json.dumps({"error": f"book_record_result failed: {str(e)}"})


# === Task & artifact tools (spec §8) ===

def book_open_task(args: dict, **kwargs) -> str:
    """Create a new open task in the Book.

    Optional kwargs (``phase``, ``blocked_by``, ``milestone_id``,
    ``execution_metadata``) let the CTO file roadmap-aware executor tasks
    during kickoff.
    """
    try:
        project_id = args.get("project_id")
        title = args.get("title")
        if not project_id or not title:
            return json.dumps({"error": "project_id and title are required"})

        blocked_by = args.get("blocked_by")
        if blocked_by is not None and not isinstance(blocked_by, list):
            return json.dumps({"error": "blocked_by must be a list of task ids"})

        book = ProjectBook(project_id)
        task_id = book.open_task(
            title=title,
            assignee_role=args.get("assignee_role"),
            parent=args.get("parent"),
            phase=args.get("phase"),
            blocked_by=blocked_by,
            milestone_id=args.get("milestone_id"),
            execution_metadata=args.get("execution_metadata"),
        )
        return json.dumps({
            "success": True,
            "task": task_id,
            "phase": args.get("phase"),
            "assignee_role": args.get("assignee_role"),
            "blocked_by": blocked_by or [],
            "milestone_id": args.get("milestone_id"),
            "execution_metadata": args.get("execution_metadata"),
        })
    except Exception as e:
        return json.dumps({"error": f"book_open_task failed: {e}"})


def book_complete_task(args: dict, **kwargs) -> str:
    """Mark a task as completed."""
    try:
        project_id = args.get("project_id")
        task = args.get("task")
        if not project_id or not task:
            return json.dumps({"error": "project_id and task are required"})

        book = ProjectBook(project_id)
        ok = book.complete_task(task)
        if not ok:
            return json.dumps({"error": f"Task {task} not in open list"})
        return json.dumps({"success": True, "task": task})
    except Exception as e:
        return json.dumps({"error": f"book_complete_task failed: {e}"})


def book_add_artifact(args: dict, **kwargs) -> str:
    """Register an artifact under the project."""
    try:
        project_id = args.get("project_id")
        path = args.get("path")
        kind = args.get("kind")
        if not all([project_id, path, kind]):
            return json.dumps({"error": "project_id, path, kind are required"})

        book = ProjectBook(project_id)
        stored = book.add_artifact(path=path, kind=kind, note=args.get("note"))
        return json.dumps({"success": True, "path": stored})
    except Exception as e:
        return json.dumps({"error": f"book_add_artifact failed: {e}"})


def book_reflect(args: dict, **kwargs) -> str:
    """Capture a reflection for the project."""
    try:
        project_id = args.get("project_id")
        lesson = args.get("lesson")
        if not project_id or not lesson:
            return json.dumps({"error": "project_id and lesson are required"})

        book = ProjectBook(project_id)
        ref = book.reflect(lesson=lesson, task=args.get("task"))
        return json.dumps({"success": True, "ref": ref})
    except Exception as e:
        return json.dumps({"error": f"book_reflect failed: {e}"})


# === Sub-agent routing + criteria gating ===

def book_request_task(args: dict, **kwargs) -> str:
    """File a new routing task that lands on CTO's desk."""
    try:
        project_id = args.get("project_id")
        title = args.get("title")
        rationale = args.get("rationale")
        requester_role = args.get("requester_role")
        suggested_role = args.get("suggested_role")
        if not all([project_id, title, rationale, requester_role]):
            return json.dumps({
                "error": "project_id, title, rationale and requester_role are required"
            })

        book = ProjectBook(project_id)
        task_id = book.request_task(
            title=title,
            requester_role=requester_role,
            rationale=rationale,
            suggested_role=suggested_role,
        )
        return json.dumps({
            "success": True,
            "task": task_id,
            "routing_status": "routing",
            "assignee_role": "agent-cto",
        })
    except Exception as e:
        return json.dumps({"error": f"book_request_task failed: {e}"})


def book_assign_task(args: dict, **kwargs) -> str:
    """CTO routes a queued task to its executor role."""
    try:
        project_id = args.get("project_id")
        task = args.get("task")
        role = args.get("role")
        if not all([project_id, task, role]):
            return json.dumps({"error": "project_id, task and role are required"})

        book = ProjectBook(project_id)
        ok = book.assign_task(task, role)
        if not ok:
            return json.dumps({
                "error": f"Task {task} is not in routing state (cannot reassign)"
            })
        return json.dumps({
            "success": True,
            "task": task,
            "assignee_role": role,
            "routing_status": "assigned",
        })
    except Exception as e:
        return json.dumps({"error": f"book_assign_task failed: {e}"})


def book_set_roadmap(args: dict, **kwargs) -> str:
    """CTO commits a roadmap of milestones. Overwrites the prior list.

    Each milestone requires ``milestone_id`` and ``title``. Optional fields:
    ``description``, ``criteria_indices`` (list of ints), ``status``.
    """
    try:
        project_id = args.get("project_id")
        milestones = args.get("milestones")
        if not project_id:
            return json.dumps({"error": "project_id is required"})
        if milestones is None or not isinstance(milestones, list):
            return json.dumps({"error": "milestones must be a list of objects"})

        book = ProjectBook(project_id)
        try:
            count = book.set_roadmap(milestones)
        except ValueError as ve:
            return json.dumps({"error": str(ve)})
        return json.dumps({"success": True, "milestone_count": count})
    except Exception as e:
        return json.dumps({"error": f"book_set_roadmap failed: {e}"})


def book_request_approval(args: dict, **kwargs) -> str:
    """A specialist subagent files a one-shot approval request into the Book.

    Use ONLY when a Hermes tool call returned ``pending_approval`` and you
    cannot work around it. Do not retry the blocked command — file the
    request, then return your task summary noting the returned approval id.
    """
    try:
        project_id = args.get("project_id")
        task_id = args.get("task_id")
        action = args.get("action")
        command = args.get("command")
        reason = args.get("reason")
        requester_role = args.get("requester_role")
        missing = [k for k, v in {
            "project_id": project_id,
            "task_id": task_id,
            "action": action,
            "command": command,
            "reason": reason,
            "requester_role": requester_role,
        }.items() if not v]
        if missing:
            return json.dumps({
                "error": "missing required fields: " + ", ".join(missing)
            })

        book = ProjectBook(project_id)
        approval_id = book.request_approval(
            task_id=task_id,
            requester_role=requester_role,
            action=action,
            command=command,
            reason=reason,
        )
        return json.dumps({
            "success": True,
            "approval_id": approval_id,
            "status": "pending",
            "next_step": (
                "Return your task summary now. Do NOT retry the blocked "
                "command. The operator will resolve the approval and the "
                "next supervisor tick will re-dispatch."
            ),
        })
    except Exception as e:
        return json.dumps({"error": f"book_request_approval failed: {e}"})


def book_resolve_approval(args: dict, **kwargs) -> str:
    """Operator (or dashboard) resolves a pending approval.

    On ``decision="approve"`` the command is appended to the project-scoped
    ``approved_commands`` list so the next specialist dispatch can see it
    listed in its context. The Hermes-wide ``command_allowlist`` is NOT
    mutated by this tool (intentionally narrow blast radius).
    """
    try:
        project_id = args.get("project_id")
        approval_id = args.get("approval_id")
        decision = args.get("decision")
        note = args.get("note")
        if not project_id or not approval_id or not decision:
            return json.dumps({
                "error": "project_id, approval_id and decision are required"
            })

        book = ProjectBook(project_id)
        try:
            entry = book.resolve_approval(
                approval_id=approval_id,
                decision=decision,
                note=note,
            )
        except ValueError as ve:
            return json.dumps({"error": str(ve)})
        return json.dumps({
            "success": True,
            "approval_id": approval_id,
            "status": entry["status"],
            "resolution": entry.get("resolution"),
            "allowlisted_globally": entry.get("allowlisted_globally", False),
        })
    except Exception as e:
        return json.dumps({"error": f"book_resolve_approval failed: {e}"})


def prepare_manager_handoff(args: dict, **kwargs) -> str:
    """Build the ``delegate_task`` payload for an agent-manager ingestion call.

    Hermes' native ``delegate_task`` does not load a SKILL by role name — the
    ``role`` parameter is delegation *depth* (``leaf`` / ``branch``), not
    agent identity. To dispatch the manager we have to inject its SKILL.md
    content into the ``context`` ourselves, alongside the structured report
    fields. This tool returns ``{goal, context, toolsets, expected}`` ready
    for the orchestrator-protocol session to pass straight through:

        payload = prepare_manager_handoff(...)
        delegate_task(
            goal=payload["goal"],
            context=payload["context"],
            toolsets=payload["toolsets"],
            role="leaf",
        )
    """
    try:
        project_id = args.get("project_id")
        task_id = args.get("task_id")
        subagent_role = args.get("subagent_role")
        subagent_summary = args.get("subagent_summary")
        subagent_exit_status = args.get("subagent_exit_status") or "success"
        if not all([project_id, task_id, subagent_role, subagent_summary]):
            return json.dumps({
                "error": (
                    "project_id, task_id, subagent_role, and "
                    "subagent_summary are required"
                )
            })

        registry = get_registry()
        manager_skill = registry.get_skill_content("agent-manager") or ""
        if not manager_skill:
            return json.dumps({"error": "agent-manager SKILL.md not found"})

        book = ProjectBook(project_id)
        data = book.load()
        meta = data.get("task_meta", {}).get(task_id, {})
        title = meta.get("title", task_id)
        criteria = data.get("acceptance_criteria", [])
        criteria_status = data.get("criteria_status", {})

        criteria_lines = "\n".join(
            f"  [{'x' if criteria_status.get(str(i)) == 'satisfied' else ' '}] {ac}"
            for i, ac in enumerate(criteria)
        ) or "  (none recorded)"

        context = (
            "You are the Omoikane agent-manager. Read your operating rules "
            "below and follow them strictly.\n\n"
            "=== Manager rules (SKILL.md) ===\n"
            f"{manager_skill.strip()}\n\n"
            "=== Report to ingest ===\n"
            f"project_id:            {project_id}\n"
            f"task_id:               {task_id}\n"
            f"task_title:            {title}\n"
            f"subagent_role:         {subagent_role}\n"
            f"subagent_exit_status:  {subagent_exit_status}\n\n"
            "=== Project context ===\n"
            f"brief: {data.get('brief', '').strip()}\n\n"
            f"acceptance_criteria:\n{criteria_lines}\n\n"
            "=== Subagent's final summary (verbatim) ===\n"
            f"{subagent_summary}\n\n"
            "Begin. Classify the report (success / needs_revision / "
            "failed), call book_record_result, then book_complete_task if "
            "appropriate. File new work via book_request_task. Return a "
            "one-paragraph human-readable confirmation."
        )

        expected = (
            "A book_record_result call (and optionally book_complete_task / "
            "book_request_task), followed by a one-paragraph confirmation."
        )

        return json.dumps({
            "success": True,
            "goal": f"Ingest report for task {task_id} ({subagent_role})",
            "context": context,
            "toolsets": ["omoikane"],
            "expected": expected,
        })
    except Exception as e:
        return json.dumps({"error": f"prepare_manager_handoff failed: {e}"})


def book_satisfy_criterion(args: dict, **kwargs) -> str:
    """QA reviewer marks one acceptance criterion satisfied with evidence."""
    try:
        project_id = args.get("project_id")
        index = args.get("index")
        evidence = args.get("evidence")
        if project_id is None or index is None or not evidence:
            return json.dumps({
                "error": "project_id, index and evidence are required"
            })
        try:
            index_int = int(index)
        except (TypeError, ValueError):
            return json.dumps({"error": f"index must be an integer, got {index!r}"})

        book = ProjectBook(project_id)
        ok = book.satisfy_criterion(index_int, evidence=evidence)
        if not ok:
            return json.dumps({"error": f"Criterion index {index_int} out of range"})

        data = book.load()
        return json.dumps({
            "success": True,
            "criterion_index": index_int,
            "criteria_status": data.get("criteria_status", {}),
            "all_satisfied": book.all_criteria_satisfied(),
        })
    except Exception as e:
        return json.dumps({"error": f"book_satisfy_criterion failed: {e}"})


_CRITERIA_PROVENANCE = ("operator_given", "extracted", "synthesized", "escalated")


def book_set_criteria(args: dict, **kwargs) -> str:
    """Append acceptance criteria (analyst derivation / CTO escalation / QA gap).

    Append-only: never edits or reorders existing criteria. Validates each
    entry's text and provenance, then delegates to
    :meth:`ProjectBook.set_criteria`.
    """
    try:
        project_id = args.get("project_id")
        items = args.get("criteria")
        if not project_id:
            return json.dumps({"error": "project_id is required"})
        if not isinstance(items, list) or not items:
            return json.dumps({"error": "criteria must be a non-empty list"})

        normalized = []
        for i, entry in enumerate(items):
            if not isinstance(entry, dict):
                return json.dumps({"error": f"criteria[{i}] must be an object"})
            text = str(entry.get("text") or "").strip()
            if not text:
                return json.dumps({"error": f"criteria[{i}].text is required"})
            provenance = entry.get("provenance") or "synthesized"
            if provenance not in _CRITERIA_PROVENANCE:
                return json.dumps({
                    "error": (
                        f"criteria[{i}].provenance must be one of "
                        f"{', '.join(_CRITERIA_PROVENANCE)}"
                    )
                })
            normalized.append({"text": text, "provenance": provenance})

        book = ProjectBook(project_id)
        new_indices = book.set_criteria(normalized)
        data = book.load()
        return json.dumps({
            "success": True,
            "new_indices": new_indices,
            "criteria_count": len(data.get("acceptance_criteria", [])),
            "criteria_status": data.get("criteria_status", {}),
        })
    except Exception as e:
        return json.dumps({"error": f"book_set_criteria failed: {e}"})


# === M5: Project continuation ===

def project_continue(args: dict, **kwargs) -> str:
    """Resume a paused project."""
    try:
        project_id = args.get("project_id")
        if not project_id:
            return json.dumps({"error": "project_id is required"})

        book = ProjectBook(project_id)
        book_data = book.load()

        if book_data.get("status") == "done":
            return json.dumps({"error": "Project is already completed"})

        book.log("decision", "Project continuation requested")

        result = TeamOrchestrator(project_id).run_once()

        # Surface the delegation plan at the top level so the LLM does not
        # have to dig into a nested object to find what to dispatch next.
        response = {
            "success": True,
            "project_id": project_id,
            "tick": result,
        }
        if "next_delegation" in result:
            response["next_delegation"] = result["next_delegation"]
        if "message" in result:
            response["message"] = result["message"]
        return json.dumps(response)

    except Exception as e:
        return json.dumps({"error": f"project_continue failed: {str(e)}"})

def book_request_split(args: dict, **kwargs) -> str:
    """Specialist or manager flags a task as too large to finish in one
    session. Files a routing task to CTO so it gets split.
    """
    try:
        project_id = args.get("project_id")
        task = args.get("task")
        requester_role = args.get("requester_role")
        reason = args.get("reason")
        suggested = args.get("suggested_subtasks") or []
        missing = [k for k, v in {
            "project_id": project_id,
            "task": task,
            "requester_role": requester_role,
            "reason": reason,
        }.items() if not v]
        if missing:
            return json.dumps({
                "error": "missing required fields: " + ", ".join(missing)
            })
        if not isinstance(suggested, list):
            return json.dumps({
                "error": "suggested_subtasks must be a list of objects"
            })

        book = ProjectBook(project_id)
        routing_task_id = book.request_split(
            task_id=task,
            requester_role=requester_role,
            reason=reason,
            suggested_subtasks=suggested,
        )
        if routing_task_id is None:
            # Either the task is unknown OR it was already flagged
            # earlier (idempotent re-call). Surface a useful message.
            data = book.load()
            meta = data.get("task_meta", {}).get(task)
            if meta is None:
                return json.dumps({"error": f"unknown task {task}"})
            return json.dumps({
                "success": True,
                "task": task,
                "split_status": meta.get("split_status"),
                "routing_task": None,
                "note": (
                    "Split request already on file for this task; "
                    "reason and suggestions updated."
                ),
            })
        return json.dumps({
            "success": True,
            "task": task,
            "split_status": "requested",
            "routing_task": routing_task_id,
            "next_step": (
                "Return your task summary now. Do NOT continue working "
                "this task. The orchestrator will skip it until CTO "
                "files the replacement children."
            ),
        })
    except Exception as e:
        return json.dumps({"error": f"book_request_split failed: {e}"})


def book_split_task(args: dict, **kwargs) -> str:
    """CTO replaces an oversized task with N children atomically."""
    try:
        project_id = args.get("project_id")
        task = args.get("task")
        requester_role = args.get("requester_role")
        replacement_tasks = args.get("replacement_tasks") or []
        reflection = args.get("reflection")
        missing = [k for k, v in {
            "project_id": project_id,
            "task": task,
            "requester_role": requester_role,
        }.items() if not v]
        if missing:
            return json.dumps({
                "error": "missing required fields: " + ", ".join(missing)
            })
        if not isinstance(replacement_tasks, list) or not replacement_tasks:
            return json.dumps({
                "error": "replacement_tasks must be a non-empty list"
            })

        book = ProjectBook(project_id)
        try:
            child_ids = book.split_task(
                task_id=task,
                replacement_specs=replacement_tasks,
                requester_role=requester_role,
                reflection=reflection,
            )
        except ValueError as ve:
            return json.dumps({"error": str(ve)})
        if child_ids is None:
            return json.dumps({"error": f"unknown task {task}"})
        return json.dumps({
            "success": True,
            "task": task,
            "closure_kind": "split",
            "children": child_ids,
        })
    except Exception as e:
        return json.dumps({"error": f"book_split_task failed: {e}"})

