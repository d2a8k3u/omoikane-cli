"""Operator inject channel — `inbox.jsonl` reader + dedup.

The TUI (Phase 5) and the ``omoikane inject`` CLI append one JSON record
per operator message to ``<project>/inbox.jsonl``. The orchestrator
process drains the inbox at well-defined points (Phase 3 calls it
once per CTO iteration) and feeds the unconsumed records to
``AIAgent.steer`` so the model sees them on its next API call.

Each record looks like:

.. code-block:: json

    {"ts": "...", "msg_id": "abc1234", "target": "agent-cto",
     "content": "Please switch the schema to uuid v7"}

``target`` is one of:

- ``"agent-cto"`` — drains for CTO sessions (default)
- ``"task:<task_id>"`` — drains for a specialist working on that task
- ``"*"`` — broadcasts to every drainer

Consumption is tracked in a sidecar file ``inbox.jsonl.consumed`` so
the same message never lands twice even if the orchestrator restarts
mid-loop. fcntl shared locks protect concurrent writers (TUI thread or
CLI subprocess) from torn lines.
"""
from __future__ import annotations

import fcntl
import json
import logging
import os
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Optional, Set

from omoikane.config import paths

logger = logging.getLogger(__name__)

CTO_TARGET = "agent-cto"
BROADCAST_TARGET = "*"


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_msg_id() -> str:
    # 8 hex chars = ~32 bits — collision risk per project is negligible
    # because the .consumed sidecar prevents replays anyway.
    return secrets.token_hex(4)


def write_message(
    project_id: str,
    content: str,
    *,
    target: str = CTO_TARGET,
    msg_id: Optional[str] = None,
    extra: Optional[dict] = None,
) -> str:
    """Append a message to the project's ``inbox.jsonl``.

    Returns the ``msg_id`` so callers can confirm receipt. The file is
    created on first write — no manual prep needed.
    """
    project_dir = paths.project_dir(project_id)
    project_dir.mkdir(parents=True, exist_ok=True)
    inbox = project_dir / "inbox.jsonl"

    entry = {
        "ts": _iso_now(),
        "msg_id": msg_id or _new_msg_id(),
        "target": target,
        "content": content,
    }
    if extra:
        entry.update(extra)

    line = json.dumps(entry, default=str) + "\n"
    with open(inbox, "ab") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            fh.write(line.encode("utf-8"))
            fh.flush()
            os.fsync(fh.fileno())
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    return entry["msg_id"]


class InboxDrainer:
    """Read-and-mark drainer for a single project's ``inbox.jsonl``."""

    def __init__(self, project_id: str):
        self.project_id = project_id
        self.path = paths.project_dir(project_id) / "inbox.jsonl"
        self.consumed_path = self.path.with_name(self.path.name + ".consumed")
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public surface
    # ------------------------------------------------------------------
    def drain(self, *, target: str = CTO_TARGET) -> List[dict]:
        """Return every unconsumed entry that matches ``target``.

        ``target`` may be a literal role, a ``task:<id>`` channel, or
        ``"*"`` (which matches everything). Drained messages are
        recorded in the ``.consumed`` sidecar before this method
        returns so a crash mid-iteration cannot duplicate them.
        """
        with self._lock:
            if not self.path.exists():
                return []
            consumed = self._load_consumed()
            entries = self._read_entries()
            fresh: List[dict] = []
            for entry in entries:
                msg_id = entry.get("msg_id")
                if not msg_id or msg_id in consumed:
                    continue
                if not _matches(entry.get("target") or CTO_TARGET, target):
                    continue
                fresh.append(entry)
            if fresh:
                self._mark_consumed([e["msg_id"] for e in fresh])
            return fresh

    def peek(self, *, target: str = CTO_TARGET) -> List[dict]:
        """Like :meth:`drain` but without marking anything as consumed."""
        with self._lock:
            if not self.path.exists():
                return []
            consumed = self._load_consumed()
            return [
                e for e in self._read_entries()
                if e.get("msg_id") not in consumed
                and _matches(e.get("target") or CTO_TARGET, target)
            ]

    def append(
        self,
        content: str,
        *,
        target: str = CTO_TARGET,
        msg_id: Optional[str] = None,
    ) -> str:
        """Convenience wrapper around :func:`write_message`."""
        return write_message(
            self.project_id, content,
            target=target, msg_id=msg_id,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _read_entries(self) -> List[dict]:
        with open(self.path, "rb") as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_SH)
            try:
                data = fh.read()
            finally:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        entries: List[dict] = []
        for raw in data.decode("utf-8").splitlines():
            raw = raw.strip()
            if not raw:
                continue
            try:
                entries.append(json.loads(raw))
            except json.JSONDecodeError:
                logger.warning("Skipping malformed inbox entry: %r", raw[:80])
        return entries

    def _load_consumed(self) -> Set[str]:
        if not self.consumed_path.exists():
            return set()
        try:
            return set(
                self.consumed_path.read_text(encoding="utf-8").split()
            )
        except OSError:
            logger.exception("Failed to read consumed sidecar %s", self.consumed_path)
            return set()

    def _mark_consumed(self, msg_ids: Iterable[str]) -> None:
        if not msg_ids:
            return
        line = "\n".join(msg_ids) + "\n"
        with open(self.consumed_path, "a", encoding="utf-8") as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            try:
                fh.write(line)
                fh.flush()
                os.fsync(fh.fileno())
            finally:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def _matches(entry_target: str, requested_target: str) -> bool:
    if requested_target == BROADCAST_TARGET:
        return True
    if entry_target == BROADCAST_TARGET:
        return True
    return entry_target == requested_target


__all__ = [
    "BROADCAST_TARGET",
    "CTO_TARGET",
    "InboxDrainer",
    "write_message",
]
