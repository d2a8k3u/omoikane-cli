"""In-process session ↔ project binding for tool handlers.

The legacy Hermes plugin used ``omoikane.hooks.bind_session_to_project`` —
an in-memory map keyed by Hermes session id, populated when an LLM run
attaches and consumed by ``post_tool_call`` / ``post_llm_call`` hooks so
the active project can be resolved without forcing every tool call to
spell out ``project_id``.

The standalone Omoikane CLI owns its own process and so reuses the same
shape: a module-level dict keyed by session/task id. Bindings live for
the lifetime of the orchestrator process and are cleared explicitly when
a session ends.
"""
from __future__ import annotations

import threading
from typing import Dict, Optional

_LOCK = threading.RLock()
_SESSION_TO_PROJECT: Dict[str, str] = {}


def bind_session_to_project(session_id: str, project_id: str) -> None:
    """Associate ``session_id`` with ``project_id`` for later lookup."""
    if not session_id or not project_id:
        return
    with _LOCK:
        _SESSION_TO_PROJECT[str(session_id)] = str(project_id)


def get_active_project(
    session_id: Optional[str] = None,
    task_id: Optional[str] = None,
) -> Optional[str]:
    """Return the bound project id for the given identifier, or ``None``.

    Both ``session_id`` and ``task_id`` are queried because hermes-agent
    sometimes forwards only one or the other depending on the call site
    (top-level run vs. delegated subagent).
    """
    with _LOCK:
        for candidate in (session_id, task_id):
            if candidate and candidate in _SESSION_TO_PROJECT:
                return _SESSION_TO_PROJECT[candidate]
    return None


def clear_session_binding(session_id: str) -> bool:
    """Drop a binding; returns ``True`` if a binding was removed."""
    with _LOCK:
        return _SESSION_TO_PROJECT.pop(str(session_id), None) is not None


def reset_for_tests() -> None:
    """Wipe all bindings. Pytest fixtures call this to keep cases isolated."""
    with _LOCK:
        _SESSION_TO_PROJECT.clear()


def bind_from_handler_kwargs(kwargs: dict, project_id: str) -> None:
    """Inspect typical SDK handler kwargs and bind any session-shaped ids.

    The SDK passes ``task_id`` and (when ``pass_session_id=True``) a
    ``session_id`` through to the handler. Either one is a stable enough
    correlation key for later lookup.
    """
    for key in ("session_id", "task_id"):
        value = kwargs.get(key)
        if value:
            bind_session_to_project(str(value), project_id)
