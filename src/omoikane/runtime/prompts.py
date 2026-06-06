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

        You are the long-lived CTO for this Omoikane project. The hermes-agent
        SDK ``delegation`` toolset gives you ``delegate_task`` — use it to
        dispatch specialist agents. The ``omoikane`` toolset gives you the
        Project Book tools (``book_log``, ``book_open_task``, ``book_record_result``,
        ``book_satisfy_criterion``, ``prepare_manager_handoff``, …). Both
        toolsets are enabled for you and propagate to children automatically.

        Each iteration you receive a status snapshot in the user message. Take
        ONE concrete step per iteration:

        1. If a specialist is in flight, wait for its delegate_task to return
           before opening another. Then ``prepare_manager_handoff`` and dispatch
           the manager to validate.
        2. If a routing task targets ``agent-cto``, decide assignment with
           ``book_assign_task``.
        3. If acceptance criteria are unsatisfied and no open work remains,
           file the next concrete task with ``book_open_task`` and dispatch.
        4. If everything is satisfied, summarise and stop — do not call any
           more tools.

        ``delegate_task`` MUST pass ``role="leaf"`` for specialists and
        ``toolsets`` enumerating only the toolsets the specialist needs.
        Specialists must call ``book_request_approval`` BEFORE dangerous
        commands; if ``pending_approval`` comes back, pause that task and
        report to the operator via ``book_log`` — do NOT retry.

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
    "INJECT_END",
    "INJECT_START",
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
