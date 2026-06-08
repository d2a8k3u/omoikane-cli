"""Tool-registration bridge for the hermes-agent SDK.

The standalone Omoikane CLI registers every Book tool against the SDK's
module-level :class:`tools.registry.ToolRegistry` before any
``AIAgent(...)`` is constructed — the SDK snapshots its available tools
at agent-init time, so registration must happen up front.

Call :func:`register_book_tools` once during process startup. The CLI
entry point in :mod:`omoikane.cli.main` does this automatically. Library
consumers (e.g. a test that builds an ``AIAgent`` directly) should call
it explicitly:

.. code-block:: python

    from omoikane.tools import register_book_tools
    register_book_tools()
    from run_agent import AIAgent
    agent = AIAgent(model="...", enabled_toolsets=["omoikane"])

The function is idempotent — repeat calls are a no-op so importers do
not need to coordinate.
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict

logger = logging.getLogger(__name__)

# Module-name → (schema_const, handler_attr) mapping. The 20 entries
# below mirror ``plugins/omoikane/__init__.py:register(ctx)`` (plus the
# standalone-only ``book_set_criteria``) so the tool surface visible to
# the LLM stays aligned with the orchestrator-protocol SKILL.md briefs.
_TOOL_SPECS: Dict[str, tuple] = {
    # M1 — project lifecycle
    "project_start": ("PROJECT_START", "project_start"),
    "project_status": ("PROJECT_STATUS", "project_status"),
    "book_log": ("BOOK_LOG", "book_log"),
    # M3 — delegation
    "book_delegate": ("BOOK_DELEGATE", "book_delegate"),
    "book_record_result": ("BOOK_RECORD_RESULT", "book_record_result"),
    # M5 — continuation
    "project_continue": ("PROJECT_CONTINUE", "project_continue"),
    # Task / artifact tools (spec §8)
    "book_open_task": ("BOOK_OPEN_TASK", "book_open_task"),
    "book_complete_task": ("BOOK_COMPLETE_TASK", "book_complete_task"),
    "book_add_artifact": ("BOOK_ADD_ARTIFACT", "book_add_artifact"),
    "book_reflect": ("BOOK_REFLECT", "book_reflect"),
    # Routing + criteria gating
    "book_request_task": ("BOOK_REQUEST_TASK", "book_request_task"),
    "book_assign_task": ("BOOK_ASSIGN_TASK", "book_assign_task"),
    "book_satisfy_criterion": ("BOOK_SATISFY_CRITERION", "book_satisfy_criterion"),
    "book_set_criteria": ("BOOK_SET_CRITERIA", "book_set_criteria"),
    "book_set_roadmap": ("BOOK_SET_ROADMAP", "book_set_roadmap"),
    "prepare_manager_handoff": (
        "PREPARE_MANAGER_HANDOFF",
        "prepare_manager_handoff",
    ),
    # Approval escalation
    "book_request_approval": ("BOOK_REQUEST_APPROVAL", "book_request_approval"),
    "book_resolve_approval": ("BOOK_RESOLVE_APPROVAL", "book_resolve_approval"),
    # Task splitting
    "book_request_split": ("BOOK_REQUEST_SPLIT", "book_request_split"),
    "book_split_task": ("BOOK_SPLIT_TASK", "book_split_task"),
}

OMOIKANE_TOOLSET = "omoikane"

_REGISTRATION_LOCK = threading.Lock()
_REGISTERED = False


def register_book_tools(*, override: bool = False) -> Dict[str, Any]:
    """Register every Omoikane tool against ``tools.registry`` from the SDK.

    Idempotent: a second call returns the same mapping without touching
    the registry. Pass ``override=True`` to force re-registration (used
    by tests that want a clean slate after monkey-patching).

    Returns a dict ``{tool_name: handler_callable}`` so callers can
    assert which tools are now live.
    """
    global _REGISTERED

    from omoikane.core import schemas

    from . import handlers

    with _REGISTRATION_LOCK:
        if _REGISTERED and not override:
            return {
                name: getattr(handlers, attr)
                for name, (_, attr) in _TOOL_SPECS.items()
            }

        try:
            from tools.registry import registry as sdk_registry  # type: ignore
        except Exception as exc:  # pragma: no cover - SDK absent
            raise RuntimeError(
                "hermes-agent SDK not importable. Install the runtime extra: "
                "`pip install 'omoikane[runtime]'`."
            ) from exc

        registered: Dict[str, Any] = {}
        for tool_name, (schema_attr, handler_attr) in _TOOL_SPECS.items():
            schema = getattr(schemas, schema_attr)
            handler = getattr(handlers, handler_attr)
            sdk_registry.register(
                name=tool_name,
                toolset=OMOIKANE_TOOLSET,
                schema=schema,
                handler=handler,
                override=override,
            )
            registered[tool_name] = handler

        _REGISTERED = True
        logger.info(
            "Registered %d omoikane tools against hermes-agent SDK registry",
            len(registered),
        )
        return registered


def is_registered() -> bool:
    """Return ``True`` if :func:`register_book_tools` has run successfully."""
    return _REGISTERED


def reset_registration_for_tests() -> None:
    """Drop the idempotency guard so the next call re-registers tools."""
    global _REGISTERED
    with _REGISTRATION_LOCK:
        _REGISTERED = False


# Re-export every handler at the package root so legacy call sites that
# did ``from omoikane.tools import book_log`` keep working. Ported tests
# from the Hermes plugin depend on this pattern, and it costs nothing
# beyond importing the handlers module (which itself only touches core
# modules — no SDK).
from .handlers import (  # noqa: E402,F401  (re-export)
    book_add_artifact,
    book_assign_task,
    book_complete_task,
    book_delegate,
    book_log,
    book_open_task,
    book_record_result,
    book_reflect,
    book_request_approval,
    book_request_split,
    book_request_task,
    book_resolve_approval,
    book_satisfy_criterion,
    book_set_criteria,
    book_set_roadmap,
    book_split_task,
    prepare_manager_handoff,
    project_continue,
    project_start,
    project_status,
)

__all__ = [
    "OMOIKANE_TOOLSET",
    "book_add_artifact",
    "book_assign_task",
    "book_complete_task",
    "book_delegate",
    "book_log",
    "book_open_task",
    "book_record_result",
    "book_reflect",
    "book_request_approval",
    "book_request_split",
    "book_request_task",
    "book_resolve_approval",
    "book_satisfy_criterion",
    "book_set_criteria",
    "book_set_roadmap",
    "book_split_task",
    "is_registered",
    "prepare_manager_handoff",
    "project_continue",
    "project_start",
    "project_status",
    "register_book_tools",
    "reset_registration_for_tests",
]
