"""Shared slash-command parser for the TUI input bar and ``omoikane inject``.

The parser maps a raw line into a dict that the inbox writer (and the
TUI control plane) consumes. Recognised forms:

- ``/cto <text>``         → target=``agent-cto`` content=text
- ``/task:<id> <text>``   → target=``task:<id>`` content=text
- ``/picker <text>``      → target=``__picker__`` content=text
- ``/<role> <text>``      → target=role content=text (anything matching a
                            known specialist role)
- ``/approve <id> [note]``→ control command ``approve``
- ``/deny <id> [reason]`` → control command ``deny``
- ``/<other> <args>``     → control command, args preserved verbatim
- bare text               → target=``agent-cto`` content=text (default)

The returned dict has at least one of ``content`` (for inbox writes) or
``command`` (for control actions). Empty input returns ``None``.
"""
from __future__ import annotations

import re
from typing import Dict, Optional

from omoikane.core.agents_registry import get_registry
from omoikane.runtime.injection import BROADCAST_TARGET, CTO_TARGET

_TASK_RE = re.compile(r"^/task:([A-Za-z0-9_\-.]+)\s*(.*)$", re.DOTALL)
_SLASH_RE = re.compile(r"^/([A-Za-z][A-Za-z0-9_\-]*)\s*(.*)$", re.DOTALL)

_CONTROL_VERBS = frozenset({
    "approve", "deny", "stop", "pause", "resume",
    "help", "h", "?", "quit", "q",
})


def _role_names() -> set:
    return set(get_registry().list_roles())


def parse_input(raw: str) -> Optional[Dict[str, object]]:
    """Return ``None`` for empty input, else a normalised dict.

    The dict always carries a ``target`` field for inbox routing and one
    of ``content`` (regular inject) or ``command``+``args`` (control).
    """
    if raw is None:
        return None
    raw = raw.strip()
    if not raw:
        return None

    # /task:<id> shorthand handled first so the leading word isn't
    # interpreted as a role name.
    task_match = _TASK_RE.match(raw)
    if task_match:
        return {
            "target": f"task:{task_match.group(1)}",
            "content": task_match.group(2).strip(),
        }

    slash_match = _SLASH_RE.match(raw)
    if not slash_match:
        return {"target": CTO_TARGET, "content": raw}

    keyword = slash_match.group(1).lower()
    rest = slash_match.group(2).strip()

    if keyword == "cto":
        return {"target": CTO_TARGET, "content": rest}
    if keyword == "picker":
        return {"target": "__picker__", "content": rest}
    if keyword in {"all", "broadcast", "everyone"}:
        return {"target": BROADCAST_TARGET, "content": rest}
    if keyword in _CONTROL_VERBS:
        return {
            "target": "__control__",
            "command": keyword,
            "args": rest,
        }

    # Specialist role names — match by full agent-* form OR shorthand.
    role_set = _role_names()
    candidates = [keyword, f"agent-{keyword}"]
    for cand in candidates:
        if cand in role_set:
            return {"target": cand, "content": rest}

    # Unknown slash word — treat as a control command so the TUI can
    # surface a "not found" message without silently rewriting to CTO.
    return {
        "target": "__control__",
        "command": keyword,
        "args": rest,
        "unknown": True,
    }


__all__ = ["parse_input"]
