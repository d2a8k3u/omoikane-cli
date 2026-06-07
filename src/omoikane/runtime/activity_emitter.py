"""Append SDK callback events to a per-project ``activity.jsonl`` stream.

The TUI tails this file with ``watchfiles`` to render the live
agent transcript. The orchestrator wires the SDK's
``stream_delta_callback`` / ``tool_start_callback`` / ``tool_complete_callback``
into :meth:`ActivityEmitter.emit` so every model token and tool call
lands in the same place — regardless of whether it came from the parent
CTO or a delegated child.

Semantically meaningful events (delegation, result, criterion satisfied,
task opened/closed) ALSO fan out into the durable Project Book via
:meth:`omoikane.core.book.ProjectBook.log`. Stream deltas and tool I/O
previews stay in ``activity.jsonl`` only — fanning them into the Book
would blow up its size by orders of magnitude.

Secret redaction is applied to every payload before it touches disk so
the file is safe to share / replay (matches the contract of
``ProjectBook.store.append_activity``).
"""
from __future__ import annotations

import fcntl
import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from omoikane.config import paths
from omoikane.core.book import ProjectBook
from omoikane.core.redact import redact, redact_text

logger = logging.getLogger(__name__)

# Events that are interesting enough to land in the durable Book log.
# The remaining traffic (``assistant_delta``, ``status``, raw
# ``tool_output``) is too noisy and stays in activity.jsonl only.
_BOOK_EVENT_KINDS = frozenset({
    "delegation_spawned",
    "delegation_returned",
    "task_opened",
    "task_closed",
    "criterion_satisfied",
    "approval_requested",
    "approval_resolved",
    "error",
    "operator_steer",
    "orchestrator",
})

# Per-process cache, keyed by project_id. The orchestrator daemon runs in
# a single process so a single emitter per project is enough. The lock
# guards both the cache and the JSONL append itself.
_CACHE: Dict[str, "ActivityEmitter"] = {}
_CACHE_LOCK = threading.Lock()


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _truncate(value: Any, limit: int) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


class ActivityEmitter:
    """Project-scoped emitter that writes one JSONL line per event."""

    def __init__(self, project_id: str):
        self.project_id = project_id
        self.book = ProjectBook(project_id)
        self.path = paths.project_dir(project_id) / "activity.jsonl"
        self._write_lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Low-level emission
    # ------------------------------------------------------------------
    def emit(self, kind: str, data: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
        """Append one ``{ts, kind, ...data}`` line.

        ``data`` is redacted recursively before write. The returned dict
        is the on-disk record — tests assert against it.
        """
        payload: Dict[str, Any] = {"ts": _iso_now(), "kind": kind}
        if data:
            payload.update(redact(dict(data)))
        # Summary becomes the human-readable preview in the Book log
        # below. Trimmed so a 50KB tool result doesn't bloat book.json.
        if "summary" in payload:
            payload["summary"] = _truncate(redact_text(str(payload["summary"])), 400)

        line = json.dumps(payload, default=str) + "\n"
        with self._write_lock:
            with open(self.path, "ab") as fh:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
                try:
                    fh.write(line.encode("utf-8"))
                    fh.flush()
                    os.fsync(fh.fileno())
                finally:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)

        if kind in _BOOK_EVENT_KINDS:
            try:
                self.book.log(
                    kind=kind,
                    summary=payload.get("summary") or kind,
                    data={k: v for k, v in payload.items() if k not in {"ts", "kind"}},
                )
            except Exception:
                logger.exception("ActivityEmitter book.log fan-out failed")

        return payload

    # ------------------------------------------------------------------
    # SDK-callback convenience wrappers — keep the callsites tiny.
    # ------------------------------------------------------------------
    def stream_delta(self, role: str, delta: str) -> None:
        """``stream_delta_callback`` → assistant token stream.

        Aggregated to whole text rather than line-by-line to keep the
        JSONL file readable; the TUI re-concatenates on render.
        """
        if not delta:
            return
        self.emit("assistant_delta", {"role": role, "delta": _truncate(delta, 4000)})

    def tool_start(self, role: str, tool_name: str, args: Any) -> None:
        self.emit("tool_call", {
            "role": role,
            "tool": tool_name,
            "args_preview": _truncate(args, 600),
        })

    def tool_complete(
        self,
        role: str,
        tool_name: str,
        result: Any,
        duration_ms: Optional[float] = None,
        is_error: bool = False,
    ) -> None:
        self.emit("tool_output", {
            "role": role,
            "tool": tool_name,
            "duration_ms": duration_ms,
            "is_error": bool(is_error),
            "output_preview": _truncate(result, 1000),
        })

    def status(self, role: str, status: str, detail: Optional[str] = None) -> None:
        self.emit("status", {"role": role, "status": status, "detail": detail})

    def notice(self, role: str, message: str) -> None:
        self.emit("notice", {"role": role, "message": _truncate(message, 800)})

    def operator_steer(self, content: str, target: str = "agent-cto") -> None:
        self.emit("operator_steer", {
            "target": target,
            "summary": _truncate(content, 400),
        })

    def delegation_spawned(self, parent_role: str, child_role: str, task: str, brief: str) -> None:
        self.emit("delegation_spawned", {
            "parent_role": parent_role,
            "role": child_role,
            "task": task,
            "summary": f"{parent_role} → {child_role}: {task}",
            "brief_preview": _truncate(brief, 400),
        })

    def delegation_returned(self, parent_role: str, child_role: str, task: str, summary: str) -> None:
        self.emit("delegation_returned", {
            "parent_role": parent_role,
            "role": child_role,
            "task": task,
            "summary": f"{child_role} → {parent_role}: {summary[:120]}",
        })

    def error(self, role: str, message: str, **extra: Any) -> None:
        self.emit("error", {"role": role, "summary": message, **extra})


def for_project(project_id: str) -> ActivityEmitter:
    """Return the cached emitter for ``project_id``, building one if needed."""
    with _CACHE_LOCK:
        emitter = _CACHE.get(project_id)
        if emitter is None:
            emitter = ActivityEmitter(project_id)
            _CACHE[project_id] = emitter
        return emitter


def reset_cache_for_tests() -> None:
    """Drop the per-process cache. Used by pytest fixtures between cases."""
    with _CACHE_LOCK:
        _CACHE.clear()


__all__ = [
    "ActivityEmitter",
    "for_project",
    "reset_cache_for_tests",
]
