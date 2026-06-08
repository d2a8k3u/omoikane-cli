"""Prompt templates for the long-lived CTO session.

The CTO ``AIAgent`` is briefed once via ``ephemeral_system_prompt`` (the
project brief + acceptance criteria + a SKILL.md-derived role brief) and
then advanced one iteration at a time with a small ``user_message``
that describes what changed since the previous tick. Operator inject
text is concatenated into that same message inside a marked block so
the model can react without rewriting its long-running plan.

Templates ported from
``plugins/omoikane/supervisor_script.py:_resurrect_prompt_stalled`` and
``_resurrect_prompt_crashed`` with the Hermes-specific path replaced by
the omoikane home and ``delegate_task`` left as the SDK-native call name.
"""
from __future__ import annotations

import json
import textwrap
from typing import Any, Dict, Iterable, List, Mapping, Optional

from omoikane.config import paths
from omoikane.core.agents_registry import get_registry

INJECT_START = "=== OPERATOR STEER ==="
INJECT_END = "=== END OPERATOR STEER ==="

_PROJECT_PATH_HINT = "~/.omoikane/projects/{pid}/book.json"


def _project_path_hint(project_id: str) -> str:
    return _PROJECT_PATH_HINT.format(pid=project_id)


def _format_criteria(criteria: Iterable[str], status: Mapping[str, str]) -> str:
    lines: List[str] = []
    for idx, item in enumerate(criteria):
        marker = "[x]" if status.get(str(idx)) == "satisfied" else "[ ]"
        lines.append(f"  {marker} ({idx}) {item}")
    return "\n".join(lines) if lines else "  (none filed yet)"


def _format_tasks(open_tasks: Iterable[str], task_meta: Mapping[str, Mapping[str, Any]]) -> str:
    lines: List[str] = []
    for tid in open_tasks:
        meta = task_meta.get(tid) or {}
        title = meta.get("title") or tid
        role = meta.get("assignee_role") or "(unassigned)"
        phase = meta.get("phase") or "-"
        routing = " [routing]" if meta.get("routing_status") == "routing" else ""
        lines.append(f"  - {tid} :: {role} :: {phase}{routing} — {title}")
    return "\n".join(lines) if lines else "  (no open tasks)"


def build_cto_system_prompt(
    project_id: str,
    book: Mapping[str, Any],
    *,
    enabled_toolsets: List[str],
) -> str:
    """Compose the ``ephemeral_system_prompt`` used to build the CTO agent.

    Combines the agent-cto SKILL.md brief with the project's brief +
    acceptance criteria + a short operating manual that explains the
    ``delegate_task`` ↔ ``book_*`` protocol.
    """
    registry = get_registry()
    cto_skill = (registry.get_skill_content("agent-cto") or "").strip()

    criteria = book.get("acceptance_criteria") or []
    criteria_status = book.get("criteria_status") or {}

    delegation_advice = textwrap.dedent("""
        Operating manual
        ----------------

        You are the CTO / planner for this Omoikane project. You do NOT run
        specialists yourself — the Omoikane orchestrator executes every task you
        file and closes it. You are dispatched for a single routing/kickoff task
        at a time; do exactly that task with the ``omoikane`` Project Book tools,
        then stop.

        Typical actions for the task you were given:

        1. Kickoff: read the analyst + architect reflections (paths are in your
           context), then ``book_set_roadmap(...)`` and file the executor tasks
           with ``book_open_task(title, assignee_role, phase, milestone_id)``.
           The orchestrator runs each filed task next — you do NOT dispatch them.
        2. Routing request targeting ``agent-cto``: choose the executor and call
           ``book_assign_task(task=..., role=...)``.
        3. Close your task: ``book_record_result(task=..., status='done',
           reflection=...)`` then ``book_complete_task(task=...)``.

        Do NOT call ``delegate_task`` — dispatch is the orchestrator's job.
        Specialists self-gate dangerous commands via ``book_request_approval``.

        The Project Book lives at ``{path_hint}``. Treat it as the single
        source of truth.
    """).strip()

    sections = [
        cto_skill if cto_skill else "",
        delegation_advice.format(path_hint=_project_path_hint(project_id)),
        f"Brief:\n{book.get('brief', '').strip()}",
        "Acceptance criteria:\n" + _format_criteria(criteria, criteria_status),
        f"Enabled toolsets: {', '.join(enabled_toolsets)}",
    ]
    return "\n\n".join(s for s in sections if s)


def build_role_system_prompt(
    project_id: str,
    book: Mapping[str, Any],
    *,
    role: str,
    enabled_toolsets: List[str],
) -> str:
    """``ephemeral_system_prompt`` for a focused, single-task specialist run.

    Unlike :func:`build_cto_system_prompt` (which casts the agent as the
    long-lived orchestrator), this briefs a *leaf worker*: do exactly the one
    delegated task, write real files, do not try to delegate further.
    """
    registry = get_registry()
    skill = (registry.get_skill_content(role) or "").strip()
    path_hint = _project_path_hint(project_id)
    manual = (
        "Operating manual\n----------------\n"
        f"You are the {role} agent in the Omoikane team. You have been delegated "
        "exactly ONE task; its full assignment is in the user message. Do the "
        "work for real:\n"
        "  - Before you start, open and read the upstream-decision reflection "
        "files listed in your assignment context — build on the architect's / "
        "analyst's choices instead of re-deciding them.\n"
        "  - Use your file / terminal toolsets to CREATE and EDIT real files in "
        "the current working directory. Do not merely describe a plan.\n"
        "  - Record durable outcomes with the Project Book tools (book_log, "
        "book_reflect, book_add_artifact) when relevant.\n"
        "  - If you find a problem, blocker, or deficiency that must be fixed "
        "before the project is done — even outside this task — do NOT silently "
        "work around it. File it to the CTO via book_request_task(...); it will "
        "be folded into the roadmap and block completion until resolved.\n"
        "  - When the task is genuinely complete, stop with a short summary "
        "naming the files you changed and the verification you ran.\n"
        "Do not call delegate_task — you are a leaf worker, not the "
        f"orchestrator. The Project Book lives at {path_hint}."
    )
    criteria = book.get("acceptance_criteria") or []
    criteria_status = book.get("criteria_status") or {}
    sections = [
        skill,
        manual,
        f"Project brief:\n{(book.get('brief') or '').strip()}",
        "Acceptance criteria:\n" + _format_criteria(criteria, criteria_status),
        f"Enabled toolsets: {', '.join(enabled_toolsets)}",
    ]
    return "\n\n".join(s for s in sections if s)


def build_task_directive(plan: Mapping[str, Any]) -> str:
    """``user_message`` driving one focused task execution.

    ``plan`` is the ``next_delegation`` payload from
    :meth:`TeamOrchestrator.run_once` — its ``context`` is already a complete,
    self-contained assignment (brief, criteria, role SKILL.md, routing/kickoff
    procedure). We append an imperative footer so a weak model implements
    rather than narrates.
    """
    context = (plan.get("context") or "").strip()
    action = (
        "\n\n=== ACTION ===\n"
        "Complete this task NOW in the current working directory. Implement it "
        "for real — create/edit the actual files; do not only describe a plan. "
        "When finished, stop and summarize the files you changed and the "
        "verification you ran."
    )
    return f"{context}{action}"


def build_qa_directive(project_id: str, book: Mapping[str, Any]) -> str:
    """``user_message`` for a deterministic QA/verification pass.

    Lists the still-unsatisfied acceptance criteria and tells the reviewer to
    verify each against the produced files, satisfying the ones that pass and
    filing fix tasks for the ones that don't.
    """
    criteria = book.get("acceptance_criteria") or []
    status = book.get("criteria_status") or {}
    pending = [
        f"  ({i}) {c}"
        for i, c in enumerate(criteria)
        if status.get(str(i)) != "satisfied"
    ]
    pending_block = "\n".join(pending) or "  (none)"
    path_hint = _project_path_hint(project_id)
    return (
        f"You are the QA reviewer for project {project_id}. The team has been "
        "building in the current working directory. Verify the project against "
        "each UNSATISFIED acceptance criterion below by inspecting and, where "
        "possible, running the actual files (use your file / terminal tools).\n\n"
        f"Project brief:\n{(book.get('brief') or '').strip()}\n\n"
        f"Unsatisfied acceptance criteria:\n{pending_block}\n\n"
        "For EACH criterion:\n"
        "  - If it genuinely passes, call book_satisfy_criterion(project_id, "
        "index=<the number above>, evidence=<what you checked / command output>).\n"
        "  - If it fails or is missing, call book_open_task(project_id, "
        "title=<concrete fix>, assignee_role=<role>, phase='implementation') so "
        "the team can address it.\n"
        "Do NOT satisfy a criterion you could not actually verify. "
        f"The Project Book lives at {path_hint}. When done, stop with a short "
        "summary of what passed and what you filed."
    )


def build_completeness_directive(project_id: str, book: Mapping[str, Any]) -> str:
    """``user_message`` for ONE bounded completeness pass.

    Runs after every enumerated acceptance criterion is satisfied. The reviewer
    checks the brief's *intent* (implied features, edge cases, consequences)
    against the criteria and either appends genuinely-missing criteria once or
    confirms the intent is fully covered.
    """
    criteria = book.get("acceptance_criteria") or []
    criteria_block = "\n".join(f"  ({i}) {c}" for i, c in enumerate(criteria)) or "  (none)"
    path_hint = _project_path_hint(project_id)
    return (
        f"You are the QA reviewer running a COMPLETENESS pass for project "
        f"{project_id}. Every listed acceptance criterion is already satisfied "
        "— your job now is to decide whether the build is genuinely 'thought "
        "through to its consequences', not just literally compliant.\n\n"
        f"Project brief:\n{(book.get('brief') or '').strip()}\n\n"
        f"Satisfied acceptance criteria:\n{criteria_block}\n\n"
        "Compare the brief's INTENT against the criteria above. Look for "
        "implied-but-unstated features, unhandled edge cases, error/empty/"
        "failure paths, security or data-integrity consequences, and anything a "
        "careful operator would expect but the criteria miss.\n\n"
        "Then do EXACTLY ONE of:\n"
        "  - If you find a genuine gap, append the missing checkable "
        "criteria via book_set_criteria(project_id, criteria=[{text, "
        "provenance='synthesized'}, ...]), and file the build work via "
        "book_request_task(project_id, title=<fix>, rationale=<why>, "
        "requester_role='agent-qa-reviewer', suggested_role=<role>) so the CTO "
        "routes AND sizes it — do not open the build task directly (that "
        "bypasses sizing).\n"
        "  - If the brief's intent is already fully covered, append nothing and "
        "say so plainly.\n\n"
        "Only append criteria you can phrase as a concrete check. Do not "
        "re-satisfy or edit existing criteria. "
        f"The Project Book lives at {path_hint}. Stop with a short summary of "
        "what (if anything) you added."
    )


def build_initial_directive(project_id: str, book: Mapping[str, Any]) -> str:
    """``user_message`` for the very first CTO iteration on a fresh project."""
    return (
        f"Starting project {project_id}.\n"
        f"Phase: {book.get('current_phase')}.\n\n"
        f"Open tasks:\n{_format_tasks(book.get('open_tasks') or [], book.get('task_meta') or {})}\n\n"
        f"Decide the next concrete step. Either dispatch the first specialist "
        f"via delegate_task, or file additional bootstrap tasks with "
        f"book_open_task before delegating. One action per iteration."
    )


def build_followup_directive(project_id: str, book: Mapping[str, Any]) -> str:
    """``user_message`` for each subsequent CTO iteration.

    Always lands AFTER a prior tool turn so ``agent.steer`` injects (if any)
    will already be appended to the previous tool result.
    """
    return (
        f"Continuing project {project_id} (phase {book.get('current_phase')}).\n\n"
        f"Open tasks:\n{_format_tasks(book.get('open_tasks') or [], book.get('task_meta') or {})}\n\n"
        f"Acceptance criteria:\n{_format_criteria(book.get('acceptance_criteria') or [], book.get('criteria_status') or {})}\n\n"
        f"Pick the next action. If all criteria are satisfied and no tasks "
        f"remain open, end with a closing summary."
    )


def build_resurrect_directive(
    project_id: str,
    book: Mapping[str, Any],
    *,
    idle_minutes: float = 0.0,
    crashed: bool = False,
) -> str:
    """Used after a STALLED / CRASHED classification when the daemon restarts."""
    if crashed:
        return (
            f"Resuming {project_id} after an unexpected exit. Treat any open "
            f"delegation edge without a closed_at as crashed mid-task:\n"
            f"  1. Read delegation.json; call book_record_result(status='needs_revision') "
            f"for orphaned edges.\n"
            f"  2. Then continue normally — one delegate_task per iteration.\n\n"
            f"Current state:\n{_format_tasks(book.get('open_tasks') or [], book.get('task_meta') or {})}"
        )
    return (
        f"Resuming {project_id} after {idle_minutes:.1f} minutes idle. The "
        f"previous session ended cleanly; more work remains.\n\n"
        f"Current state:\n{_format_tasks(book.get('open_tasks') or [], book.get('task_meta') or {})}\n\n"
        f"Drive the next iteration."
    )


def format_inject(injects: List[Mapping[str, Any]]) -> str:
    """Render operator inject messages into a block ready for ``agent.steer``.

    The block is short and self-contained so the model can react without
    being told the inbox transport semantics.
    """
    if not injects:
        return ""
    lines = [INJECT_START]
    for entry in injects:
        ts = entry.get("ts") or ""
        target = entry.get("target") or ""
        content = (entry.get("content") or "").strip()
        if not content:
            continue
        header = f"({ts} → {target})" if ts else f"(→ {target})"
        lines.append(f"{header}\n{content}")
    lines.append(INJECT_END)
    return "\n\n".join(lines)


def prepend_injects(message: str, injects: List[Mapping[str, Any]]) -> str:
    block = format_inject(injects)
    if not block:
        return message
    return f"{block}\n\n{message}"


_APPROVAL_TOOLSETS = frozenset({"terminal", "code_execution"})

APPROVAL_ADDENDUM_TEMPLATE = textwrap.dedent("""
    Approval self-gating
    --------------------

    Before running ANY of the following, you MUST call
    ``book_request_approval(project_id=…, requester_role={role!r},
    action="execute_command", command=<exact-command>, reason=<one-sentence-why>)``
    and stop with a summary that contains ``requires_approval=true``:

    * destructive shell verbs — ``rm -rf``, ``find … -delete``, ``shred``
    * write-side git operations — ``git push --force``, ``git reset --hard``,
      ``git clean -fdx``, ``git branch -D``
    * unauthenticated network execution — ``curl … | sh``, ``wget … | bash``
    * permissions / ownership — ``sudo``, ``chmod -R``, ``chown -R``
    * package mutations — ``apt``, ``yum``, ``pip install --upgrade``,
      ``npm publish``, ``yarn upgrade --latest``
    * filesystem writes outside the project workspace
    * any network egress to a host not on the operator's allowlist

    Once you have filed the approval, do NOT retry the blocked command. The
    orchestrator pauses dispatch until the operator resolves it. The supervisor
    will re-dispatch your task only after the command pattern is approved.
""").strip()


def approval_addendum(role: str, enabled_toolsets: List[str]) -> str:
    """Return the self-gating block, or '' for roles without risky toolsets."""
    if any(ts in _APPROVAL_TOOLSETS for ts in enabled_toolsets):
        return APPROVAL_ADDENDUM_TEMPLATE.format(role=role)
    return ""


def cto_history_path(project_id: str):
    """Return the on-disk location for the CTO ``conversation_history``.

    Stored as JSON so the orchestrator can persist multi-iteration context
    across restarts. The file is intentionally separate from book.json —
    Book records the durable protocol surface, history records every raw
    SDK message.
    """
    return paths.project_dir(project_id) / "cto_history.json"


def load_cto_history(project_id: str) -> List[Dict[str, Any]]:
    path = cto_history_path(project_id)
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []


def save_cto_history(project_id: str, history: List[Dict[str, Any]]) -> None:
    path = cto_history_path(project_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(history, default=str), encoding="utf-8")


__all__ = [
    "APPROVAL_ADDENDUM_TEMPLATE",
    "INJECT_END",
    "INJECT_START",
    "approval_addendum",
    "build_completeness_directive",
    "build_cto_system_prompt",
    "build_followup_directive",
    "build_initial_directive",
    "build_resurrect_directive",
    "cto_history_path",
    "format_inject",
    "load_cto_history",
    "prepend_injects",
    "save_cto_history",
]
