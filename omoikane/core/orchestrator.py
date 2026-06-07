"""
Omoikane - TeamOrchestrator (M4).

One iteration of the loop:

  1. read the book
  2. if status == "created"  → bootstrap initial tasks and switch to in_progress
  3. if every acceptance criterion is satisfied → mark project done
  4. otherwise pick the next open task — *routing tasks first* so CTO is
     always dispatched ahead of executors — record the delegation, and return
     a structured ``next_delegation`` payload so the *calling LLM*
     (the orchestrator agent) can invoke Hermes' built-in
     ``delegate_task`` itself
  5. when criteria are still pending but no open tasks remain, auto-file a
     CTO routing task ("Decompose remaining work toward acceptance
     criteria") so the loop never deadlocks on its own state

The plugin does **not** call ``delegate_task`` on its own. Hermes' tool
dispatcher invokes plugin handlers with ``task_id`` / ``enabled_tools`` /
``user_task`` only — there is no ``ctx`` in ``kwargs`` and there is no
re-entrant tool-dispatch surface a plugin can reach into without coupling
to internals. The honest model is: the plugin owns state, the LLM owns
agency. ``run_once`` records the delegation in the Book, and returns the
goal + context + toolsets the LLM should pass to ``delegate_task``.

After ``delegate_task`` returns its summary, the LLM is expected to call
``book_record_result(project_id, task, status, reflection)`` to close the
delegation edge. When the QA reviewer's verdict satisfies an acceptance
criterion, the reviewer also calls ``book_satisfy_criterion(index,
evidence)`` so the next tick's completion check is accurate.
See ``agents/orchestrator-protocol/SKILL.md``.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from .book import ProjectBook
from .agents_registry import get_registry
from .execution import choose_execution_mode


# Match the `description:` line in a SKILL.md frontmatter so the CTO roster
# stays in sync with each role's actual prompt — no separate metadata file.
_DESC_RE = re.compile(r"^description:\s*(.+?)\s*$", re.MULTILINE)


def _role_description(skill_md: str) -> str:
    """Extract the one-line role description from a SKILL.md frontmatter."""
    if not skill_md:
        return ""
    m = _DESC_RE.search(skill_md)
    return m.group(1).strip() if m else ""


# Ordered phases — used both for computing the current phase from the open
# task set and for tagging tasks the orchestrator files itself. The bootstrap
# no longer seeds one fixed task per phase; the CTO files executor tasks
# dynamically after the analyst + architect kickoff round.
_PHASE_ORDER: List[str] = ["analysis", "design", "implementation",
                            "testing", "review"]

# Sensible default toolsets per role. Every role gets the ``omoikane``
# toolset by default so sub-agents can surface work via
# ``book_request_task`` without the operator having to wire it explicitly.
_BASE_TOOLSETS: Dict[str, List[str]] = {
    "agent-product-analyst": ["file", "web"],
    "agent-architekt": ["file", "web"],
    "agent-designer": ["file", "web"],
    "agent-backend-engineer": ["file", "terminal", "code_exec"],
    "agent-frontend-engineer": ["file", "terminal", "code_exec"],
    "agent-database-specialist": ["file", "terminal"],
    "agent-implementer": ["file", "terminal", "code_exec"],
    "agent-devops": ["file", "terminal"],
    "agent-security-engineer": ["file", "terminal"],
    "agent-ai-engineer": ["file", "terminal", "code_exec", "web"],
    "agent-ml-engineer": ["file", "terminal", "code_exec"],
    "agent-analytik": ["file", "terminal"],
    "agent-qa-reviewer": ["file", "terminal"],
    "agent-tech-writer": ["file", "web"],
    "agent-cto": ["file", "web"],
}


def _toolsets_for(role: str) -> List[str]:
    base = list(_BASE_TOOLSETS.get(role, ["file", "terminal"]))
    if "omoikane" not in base:
        base.append("omoikane")
    return base


class TeamOrchestrator:
    """Drives a project from its current state toward completion."""

    def __init__(self, project_id: str):
        self.project_id = project_id
        self.book = ProjectBook(project_id)
        self.registry = get_registry()

    # === Public entry point ===

    def run_once(self, ctx: Optional[Any] = None) -> Dict[str, Any]:
        """Advance the project by exactly one orchestration step.

        ``ctx`` is accepted for API compatibility and is *ignored*. The plugin
        no longer attempts to dispatch ``delegate_task`` directly — see this
        module's docstring for the design rationale.
        """
        data = self.book.load()

        if data["status"] == "done":
            return {"status": "already_done", "project_id": self.project_id}

        if data["status"] == "created":
            self._bootstrap(data)
            data = self.book.load()
            self._advance_phase(data)
            return {
                "status": "tasks_created",
                "project_id": self.project_id,
                "current_phase": self.book.current_phase,
                "message": (
                    "Initial decomposition complete. Call project_continue "
                    "again to receive the first delegation plan."
                ),
            }

        data = self.book.load()  # refresh after potential mutation above
        open_tasks: List[str] = list(data.get("open_tasks", []))

        # A project is complete only when EVERY acceptance criterion is
        # satisfied AND no tasks remain open. Criteria satisfaction alone does
        # not finish it — queued work (README, QA, …) must still be executed.
        if self.book.all_criteria_satisfied() and not open_tasks:
            self.book.update_status("done", phase="completed")
            self.book.log(
                "decision",
                "All acceptance criteria satisfied and all tasks complete. "
                "Project complete.",
            )
            # Tear down the per-project supervisor cron immediately so the
            # next scheduler tick doesn't waste a slot. Soft-fail: the
            # supervisor's own teardown path covers this too.
            try:
                from .project_cron import remove_project_cron
                remove_project_cron(self.project_id)
            except Exception:
                pass
            return {
                "status": "completed",
                "project_id": self.project_id,
                "current_phase": "completed",
            }

        if not open_tasks:
            # Criteria pending + no work queued. Don't deadlock — auto-file a
            # decomposition request that lands on CTO's desk. Then continue
            # the same tick so we still surface a delegation to the LLM.
            decomp_task = self._auto_decompose(data)
            data = self.book.load()
            open_tasks = list(data.get("open_tasks", []))
            if not open_tasks:
                # Should never happen unless persistence is broken.
                return {
                    "status": "needs_decomposition",
                    "project_id": self.project_id,
                    "message": (
                        "Auto-decomposition could not file a routing task. "
                        "Inspect the Book and unblock manually."
                    ),
                    "criteria_status": data.get("criteria_status", {}),
                }
            self.book.log(
                "note",
                f"Auto-decomposition filed routing task {decomp_task}",
                data={"task": decomp_task, "via": "orchestrator-auto"},
            )

        # Routing tasks first so CTO is always serviced before executors.
        next_task = self._pick_next_task(data, open_tasks)
        self._advance_phase(data)
        plan = self._plan_delegation(next_task, data)

        return {
            "status": "in_progress",
            "project_id": self.project_id,
            "current_phase": self.book.current_phase,
            "open_tasks": len(open_tasks),
            "next_delegation": plan,
            "message": (
                f"Call delegate_task(goal=…, context=…, toolsets=…) using "
                f"the next_delegation payload. When the subagent returns, "
                f"call book_record_result(project_id, task={next_task!r}, "
                f"status=…, reflection=…)."
            ),
        }

    # === Internal helpers ===

    def _bootstrap(self, data: Dict[str, Any]):
        """Seed the project with the minimum viable planning round.

        Three tasks are filed instead of the legacy fixed-phase decomposition:

        1. **Analyst** — refines the brief into checkable user stories.
        2. **Architect** — proposes architecture, ADRs, and a milestone outline.
        3. **Kickoff** (routing → CTO) — blocked on (1) and (2). Once both
           close, CTO is dispatched, reads their reflections, commits the
           roadmap via ``book_set_roadmap``, files executor tasks dynamically
           via ``book_open_task``, and closes the kickoff itself.

        The CTO — not the orchestrator — decides how many tasks the project
        needs, which roles handle them, and what milestones group them.
        """
        team = set(self.registry.list_routable_roles())

        analyst_role = ("agent-product-analyst" if "agent-product-analyst" in team
                        else "agent-implementer")
        architect_role = ("agent-architekt" if "agent-architekt" in team
                          else "agent-implementer")

        analyst_id = self.book.open_task(
            title="Refine the brief into checkable user stories and acceptance-mapped requirements",
            assignee_role=analyst_role,
            phase="analysis",
        )
        architect_id = self.book.open_task(
            title="Propose architecture, ADRs, and a milestone outline for the brief",
            assignee_role=architect_role,
            phase="design",
        )

        brief = (data.get("brief") or "").strip()
        criteria = data.get("acceptance_criteria", [])
        criteria_block = "\n".join(f"  [{i}] {ac}" for i, ac in enumerate(criteria)) or "  (none recorded)"
        rationale = (
            "Project kickoff. The analyst and architect tasks above are "
            "running first; once both close, you will be dispatched here with "
            "their reflections in your context.\n\n"
            f"Brief:\n  {brief}\n\n"
            f"Acceptance criteria (in order):\n{criteria_block}\n\n"
            "Procedure when you receive this task:\n"
            "  1. Read the analyst + architect reflections (listed in the "
            "'Completed work and reflections' block).\n"
            "  2. Decide milestones and call book_set_roadmap(milestones=[...]).\n"
            "  3. For each milestone file executor tasks via book_open_task "
            "(title, assignee_role, phase, milestone_id).\n"
            "  4. Optionally book_reflect(...) with the roadmap rationale.\n"
            "  5. Close this kickoff: book_record_result(status='done', "
            "reflection=...) then book_complete_task(task=<this>)."
        )

        kickoff_id = self.book.request_task(
            title="Kickoff: synthesise analyst + architect output, commit roadmap, file executor tasks",
            requester_role="orchestrator",
            rationale=rationale,
            suggested_role="agent-cto",
        )

        # Tag the kickoff as blocked on the analyst + architect tasks.
        # `request_task` already saved meta with phase=meta + routing; reopen
        # the book to attach `blocked_by` without losing those fields.
        latest = self.book.load()
        kmeta = latest["task_meta"][kickoff_id]
        kmeta["blocked_by"] = [analyst_id, architect_id]
        latest["task_meta"][kickoff_id] = kmeta
        self.book.store.save_book(latest)

        # Analysis phase first — analyst task drives initial phase tag.
        self.book.update_status("in_progress", phase="analysis")
        self.book.log(
            "phase_change",
            "Kickoff seeded: analyst + architect parallel; CTO planning blocked until both close.",
            data={
                "analyst": analyst_id,
                "architect": architect_id,
                "kickoff": kickoff_id,
                "phase": "analysis",
            },
        )

    def _auto_decompose(self, data: Dict[str, Any]) -> Optional[str]:
        """File a CTO routing task to break the no-tasks/criteria-pending
        deadlock. Returns the new task id, or ``None`` if no criteria are
        actually pending (defensive)."""
        criteria = data.get("acceptance_criteria", [])
        status = data.get("criteria_status", {})
        pending = [
            f"  [{i}] {criteria[i]}"
            for i in range(len(criteria))
            if status.get(str(i)) != "satisfied"
        ]
        if not pending:
            return None
        rationale = (
            "No open tasks remain but these acceptance criteria are still "
            "pending. Decide who should advance them and assign the work.\n"
            + "\n".join(pending)
        )
        return self.book.request_task(
            title="Decompose remaining work toward acceptance criteria",
            requester_role="orchestrator",
            rationale=rationale,
            suggested_role="agent-product-analyst",
        )

    def _is_blocked(self, task_id: str, data: Dict[str, Any]) -> bool:
        """A task is blocked while any id in its ``blocked_by`` remains open."""
        meta = data.get("task_meta", {}).get(task_id, {})
        blocked_by = meta.get("blocked_by") or []
        if not blocked_by:
            return False
        open_set = set(data.get("open_tasks", []))
        return any(bid in open_set for bid in blocked_by)

    def _is_split_pending(self, task_id: str, data: Dict[str, Any]) -> bool:
        """A task is paused while it carries an unresolved split request.

        The picker skips it so the orchestrator does NOT re-dispatch the
        oversized task before CTO files its replacement children — that
        would just time out again and burn another agent session.
        """
        meta = data.get("task_meta", {}).get(task_id, {})
        return meta.get("split_status") == "requested"

    def _pick_next_task(self, data: Dict[str, Any],
                        open_tasks: List[str]) -> str:
        """Routing-first task selection over unblocked tasks. FIFO fallback.

        Tasks are skipped when:
        * they have a ``blocked_by`` entry still open (kickoff waits on
          analyst+architect), or
        * they carry ``split_status='requested'`` (waiting on CTO to
          file replacement children via ``book_split_task``).

        Routing tasks that ask CTO to act on a split request must still
        run, so the split-pending filter only applies to non-routing
        tasks — the routing task ITSELF (which IS the request to CTO)
        does not carry the ``split_status`` flag.
        """
        meta = data.get("task_meta", {})
        eligible = [
            tid for tid in open_tasks
            if not self._is_blocked(tid, data)
            and not self._is_split_pending(tid, data)
        ]

        for task_id in eligible:
            if meta.get(task_id, {}).get("routing_status") == "routing":
                return task_id
        if eligible:
            return eligible[0]
        # Every task is blocked or awaiting a split — defensive fallback
        # so the surface still reports useful state. Real flows should
        # rarely hit this; when they do, surface the most recent open
        # task so the operator can see what is stuck.
        return open_tasks[0]

    def _advance_phase(self, data: Dict[str, Any]) -> None:
        """Recompute and persist ``current_phase`` from the open task set.

        Phase = the earliest (most upstream) phase that still has open work.
        That gives the operator a useful signal: phase ``implementation``
        means "design is done, implementation tasks remain". When no
        executor tasks are open but a meta/routing task is being handled,
        the phase becomes ``meta``.
        """
        meta = data.get("task_meta", {})
        open_tasks = data.get("open_tasks", [])

        if not open_tasks:
            return  # nothing to advance from

        # Look for executor work first, in phase order. Tasks blocked on
        # still-open prerequisites do not pull the phase forward (a blocked
        # kickoff/meta routing task should not flip the project into "meta"
        # while its analyst/architect prereqs are still running).
        for phase in _PHASE_ORDER:
            for task_id in open_tasks:
                tmeta = meta.get(task_id, {})
                if tmeta.get("routing_status") == "routing":
                    continue
                if self._is_blocked(task_id, data):
                    continue
                if self._is_split_pending(task_id, data):
                    continue
                if tmeta.get("phase") == phase:
                    self.book.set_phase(phase)
                    return

        # Only routing/meta tasks open (and unblocked) → meta phase.
        for task_id in open_tasks:
            if self._is_blocked(task_id, data):
                continue
            self.book.set_phase("meta")
            return

    def _plan_delegation(self, task_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Record the delegation in the Book and build the payload the LLM
        will pass to Hermes' native ``delegate_task`` tool."""
        meta = data.get("task_meta", {}).get(task_id, {})
        title = meta.get("title", task_id)
        routing = meta.get("routing_status") == "routing"
        # Routing tasks always go to CTO regardless of stored assignee.
        if routing:
            role = "agent-cto"
        else:
            role = meta.get("assignee_role") or self._pick_role(title)
        mode = choose_execution_mode(meta)
        toolsets = _toolsets_for(role)
        skill_content = self.registry.get_skill_content(role) or ""

        expected = (
            "A working result aligned with the task title, the project "
            "brief, and the role's responsibilities. Include verification "
            "evidence (commands run, files changed, tests passed)."
        )

        # Log the delegation decision and add it to the tree before we hand
        # the plan back to the LLM. If delegate_task fails, the operator can
        # still see the intent in the Book.
        self.book.log(
            "delegation",
            f"Planned delegation of {task_id} to {role} (mode={mode})",
            data={
                "task": task_id,
                "to_role": role,
                "mode": mode,
                "title": title,
                "routing": routing,
                "toolsets": toolsets,
            },
        )
        node_id = self.book.store.add_delegation(
            task=task_id,
            to_role=role,
            expected=expected,
            mode=mode,
            label=title,
        )

        # Build a self-contained context block so the subagent starts cold
        # but informed (delegate_task subagents share zero history with the
        # parent — see Hermes' delegation docs).
        criteria_lines = "\n".join(
            f"  - [{'x' if data.get('criteria_status', {}).get(str(i)) == 'satisfied' else ' '}] {ac}"
            for i, ac in enumerate(data.get("acceptance_criteria", []))
        ) or "  (none recorded)"

        is_kickoff = (
            routing
            and meta.get("requester_role") == "orchestrator"
            and isinstance(title, str)
            and title.startswith("Kickoff:")
        )

        routing_block = ""
        if routing:
            roster = self._team_roster(data, exclude=role)
            kickoff_section = ""
            if is_kickoff:
                kickoff_section = (
                    "\n=== Kickoff procedure ===\n"
                    "This is the project kickoff — do NOT call "
                    "book_assign_task. Handle it yourself:\n"
                    "  1. Read each analyst + architect reflection listed in "
                    "the 'Completed work and reflections' block (open them "
                    "with your file toolset).\n"
                    "  2. Decide the milestone list. Call "
                    "book_set_roadmap(project_id, milestones=[{milestone_id, "
                    "title, description, criteria_indices, status:'planned'}, "
                    "...]). Each milestone should map to one or more "
                    "acceptance criteria indices.\n"
                    "  3. For each milestone file the executor tasks: "
                    "book_open_task(title, assignee_role, phase, "
                    "milestone_id). Phase is one of analysis / design / "
                    "implementation / testing / review. Role comes from the "
                    "team roster below.\n"
                    "  4. Optionally book_reflect(lesson=<roadmap rationale + "
                    f"rejected alternatives>, task={task_id!r}).\n"
                    "  5. Close this kickoff: "
                    f"book_record_result(task={task_id!r}, status='done', "
                    "reflection=<one-line summary>) then "
                    f"book_complete_task(task={task_id!r}).\n"
                )
            else:
                kickoff_section = (
                    f"\nAs CTO, call book_assign_task(project_id, "
                    f"task={task_id!r}, role=<chosen role>). Do not "
                    "implement the work yourself.\n"
                )
            routing_block = (
                "\n=== Routing brief ===\n"
                f"This task is a routing request from "
                f"{meta.get('requester_role', 'an agent')}.\n"
                f"Suggested executor: {meta.get('suggested_role') or '(none)'}\n"
                f"Rationale: {meta.get('rationale', '').strip()}\n\n"
                "=== Team roster (pick from here) ===\n"
                f"{roster}\n\n"
                "Routing guidance:\n"
                "- If the work needs an upstream decision before code can be "
                "written (architecture, contracts, UX, data model), route to "
                "the role that owns that decision — they will file follow-up "
                "requests via book_request_task when ready for the next stage.\n"
                "- Prefer the smallest competent role. Do not stack work on "
                "agents already heavily loaded unless the topic demands it.\n"
                "- The suggested_role is a hint, not a command. Override it "
                "freely when the rationale points elsewhere.\n"
                f"{kickoff_section}"
            )

        cto_state_block = ""
        if role == "agent-cto":
            cto_state_block = self._cto_state_block(data)

        # Task-size budget guidance for every non-routing specialist —
        # routing tasks are short by construction and CTO has its own
        # sizing rules in its SKILL.md.
        size_block = ""
        if not routing:
            budget = data.get("task_size_budget_minutes") or 20
            est = (meta.get("execution_metadata") or {}).get("estimated_minutes")
            est_line = (
                f"Estimated minutes for this task (set by the filer): {est}.\n"
                if est is not None else ""
            )
            size_block = (
                "\n=== Self-monitor for task size ===\n"
                f"This project targets ≤ {budget} minutes per task. "
                f"{est_line}"
                "If you reach roughly half of your iteration budget and the "
                "task scope is visibly still much larger than what remains, "
                "DO NOT push through to timeout. Stop, then call:\n"
                "  book_request_split(\n"
                "    project_id=<this project_id>,\n"
                f"    task='{task_id}',\n"
                f"    requester_role='{role}',\n"
                "    reason='<one paragraph: what you tried, where the wall "
                "is, why size is the cause>',\n"
                "    suggested_subtasks=[\n"
                "      {title, estimated_minutes, suggested_role, rationale},\n"
                "      ...\n"
                "    ],\n"
                "  )\n"
                "Then return your summary. The plugin pauses this task so "
                "the orchestrator does NOT re-dispatch it; CTO files the "
                "replacement children on the next tick. Filing a split "
                "request is preferred over timing out — the loop ends here "
                "and resumes when the children are ready.\n"
            )

        context_text = (
            f"You are the {role} agent inside the Omoikane team.\n\n"
            f"=== Project brief ===\n{data.get('brief', '').strip()}\n\n"
            f"=== Acceptance criteria ===\n{criteria_lines}\n"
            f"{routing_block}"
            f"{cto_state_block}\n"
            f"=== Your assignment ===\n"
            f"Task id:    {task_id}\n"
            f"Title:      {title}\n"
            f"Expected:   {expected}\n"
            f"{size_block}\n"
            f"=== Your role's SKILL.md ===\n{skill_content.strip() or '(empty)'}"
        )

        return {
            "task": task_id,
            "node": node_id,
            "to_role": role,
            "mode": mode,
            "routing": routing,
            "title": title,
            "goal": title,
            "context": context_text,
            "toolsets": toolsets,
            "expected": expected,
        }

    def _cto_state_block(self, data: Dict[str, Any]) -> str:
        """CTO-only context: completed work + reflections + current roadmap.

        Lets CTO synthesise the kickoff (and any later re-planning) without
        re-walking the filesystem. Reflections are surfaced as absolute file
        paths so CTO's ``file`` toolset can open them regardless of CWD.

        Two paths produce reflections:
          - ``book_record_result(reflection=...)`` stores a ref in the
            delegation tree's edge.
          - An agent calling ``book.reflect()`` directly (what the analyst
            and architect SKILL.mds instruct) writes the file but does not
            touch the tree.

        Both are surfaced — the tree gives the canonical ref when present,
        and a directory scan covers the direct-reflect path.
        """
        meta = data.get("task_meta", {})
        completed = data.get("completed_tasks", [])
        project_dir = self.book.store.project_dir

        refl_by_task: Dict[str, str] = {}
        # 1. Edges in the delegation tree (book_record_result path).
        try:
            tree = self.book.store._load_delegation()
            for edge in tree.get("edges", []):
                ref = edge.get("reflection_ref")
                node_id = edge.get("to") or ""
                if not ref or not node_id.startswith("n-"):
                    continue
                refl_by_task[node_id[len("n-"):]] = ref
        except Exception:
            pass  # best-effort — never block CTO dispatch on a tree read

        # 2. Direct-reflect path: scan reflections/ for files named
        #    ``r-<ts>-<task_id>.md`` and pick the newest per task.
        try:
            refl_dir = project_dir / "reflections"
            if refl_dir.is_dir():
                for path in sorted(refl_dir.glob("r-*-*.md")):
                    # Filename format: r-{ts}-{suffix}.md  where suffix is
                    # the task id (or "general"). Split on the first two
                    # dashes from the left to isolate the suffix.
                    stem = path.stem  # "r-{ts}-{task_id}"
                    parts = stem.split("-", 2)
                    if len(parts) < 3:
                        continue
                    suffix = parts[2]
                    if suffix == "general":
                        continue
                    # Use sorted order (lex == chronological because of the
                    # %Y%m%dT%H%M%S format) so the last write wins.
                    refl_by_task[suffix] = f"reflections/{path.name}"
        except Exception:
            pass

        lines: List[str] = []
        for tid in completed:
            tmeta = meta.get(tid, {})
            title = tmeta.get("title", tid)
            assignee = tmeta.get("assignee_role") or "?"
            ref = refl_by_task.get(tid)
            if ref:
                abs_path = str(project_dir / ref)
                tail = f" — reflection: {abs_path}"
            else:
                tail = ""
            lines.append(f"  - {tid} [{assignee}] {title}{tail}")

        completed_section = (
            "\n=== Completed work and reflections ===\n"
            + ("\n".join(lines) if lines else "  (none yet)")
            + "\n"
        )

        roadmap = data.get("roadmap") or []
        if roadmap:
            rl: List[str] = []
            for m in roadmap:
                indices = ", ".join(str(i) for i in (m.get("criteria_indices") or []))
                rl.append(
                    f"  - {m.get('milestone_id')}: {m.get('title')} "
                    f"[status={m.get('status', 'planned')}] "
                    f"(criteria: {indices or 'unbound'})"
                )
            roadmap_section = (
                "\n=== Committed roadmap ===\n" + "\n".join(rl) + "\n"
            )
        else:
            roadmap_section = (
                "\n=== Committed roadmap ===\n  (empty — set via "
                "book_set_roadmap once you have decided)\n"
            )

        return completed_section + roadmap_section

    def _team_roster(self, data: Dict[str, Any], exclude: Optional[str] = None) -> str:
        """Render the team roster CTO sees when routing.

        Each line is ``- agent-<role>: <description> (open: N, done: M)``.
        Workload counts come from task_meta so CTO can avoid stacking work
        on already-loaded agents. ``exclude`` skips one role from the
        listing (typically CTO itself).
        """
        meta = data.get("task_meta", {})
        open_set = set(data.get("open_tasks", []))
        done_set = set(data.get("completed_tasks", []))

        open_load: Dict[str, int] = {}
        done_load: Dict[str, int] = {}
        for task_id, t_meta in meta.items():
            assignee = t_meta.get("assignee_role")
            if not assignee:
                continue
            if task_id in open_set:
                open_load[assignee] = open_load.get(assignee, 0) + 1
            elif task_id in done_set:
                done_load[assignee] = done_load.get(assignee, 0) + 1

        roles = sorted(self.registry.list_routable_roles())
        lines: List[str] = []
        for role in roles:
            if role == exclude:
                continue
            if role == "orchestrator-protocol":
                continue  # not an assignable executor
            desc = _role_description(self.registry.get_skill_content(role) or "")
            open_n = open_load.get(role, 0)
            done_n = done_load.get(role, 0)
            lines.append(
                f"- {role}: {desc} (open: {open_n}, done: {done_n})"
            )
        return "\n".join(lines) if lines else "(no other roles available)"

    def _pick_role(self, title: str) -> str:
        """Heuristic role assignment when task meta does not specify one."""
        t = title.lower()
        if "design" in t and ("ui" in t or "ux" in t or "interface" in t):
            return "agent-designer"
        if "design" in t or "architect" in t:
            return "agent-architekt"
        if "test" in t or "review" in t or "verify" in t:
            return "agent-qa-reviewer"
        if "deploy" in t or "ci" in t or "infrastructure" in t:
            return "agent-devops"
        if "security" in t:
            return "agent-security-engineer"
        if "database" in t or "schema" in t or "migration" in t:
            return "agent-database-specialist"
        if "frontend" in t or "ui" in t:
            return "agent-frontend-engineer"
        if "backend" in t or "api" in t:
            return "agent-backend-engineer"
        if "doc" in t or "readme" in t:
            return "agent-tech-writer"
        if "analyze" in t or "requirement" in t:
            return "agent-product-analyst"
        return "agent-implementer"
