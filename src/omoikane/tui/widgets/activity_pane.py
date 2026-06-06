"""Live tail of ``<project>/activity.jsonl`` rendered into a ``RichLog``."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container
from textual.widgets import RichLog, Static


_KIND_STYLE = {
    "tool_call":           "cyan",
    "tool_output":         "green",
    "assistant_delta":     "white",
    "operator_steer":      "yellow bold",
    "delegation_spawned":  "magenta bold",
    "delegation_returned": "magenta",
    "task_opened":         "blue",
    "task_closed":         "blue",
    "criterion_satisfied": "green bold",
    "approval_requested":  "red bold",
    "approval_resolved":   "green",
    "error":               "red bold",
    "orchestrator":        "yellow",
    "daemon_started":      "dim",
    "daemon_stopped":      "dim",
    "daemon_health":       "dim cyan",
    "notice":              "yellow",
    "status":              "dim",
}


def _format_event(payload: Dict[str, Any]) -> Text:
    ts = (payload.get("ts") or "").rsplit(".", 1)[0]
    kind = payload.get("kind", "?")
    role = payload.get("role") or payload.get("parent_role") or "-"
    style = _KIND_STYLE.get(kind, "white")

    body = payload.get("summary")
    if not body:
        tool = payload.get("tool")
        if tool:
            preview = payload.get("output_preview") or payload.get("args_preview") or ""
            body = f"{tool}: {preview}"
        else:
            body = payload.get("delta") or payload.get("message") or ""

    line = Text()
    line.append(f"{ts[-8:]:>8} ", style="dim")
    line.append(f"{kind:<20} ", style=style)
    line.append(f"{role:<24} ", style="dim italic")
    line.append(str(body))
    return line


class ActivityPane(Container):
    """A scrollable log fed by ``activity.jsonl`` lines."""

    DEFAULT_CSS = """
    ActivityPane {
        border: tall $primary;
    }
    ActivityPane > Static.title {
        background: $boost;
        padding: 0 1;
    }
    ActivityPane > RichLog {
        height: 1fr;
    }
    """

    def __init__(self, project_id: str, activity_path: Path, **kwargs):
        super().__init__(**kwargs)
        self.project_id = project_id
        self.activity_path = activity_path

    def compose(self) -> ComposeResult:
        yield Static(f"Activity — {self.project_id}", classes="title")
        yield RichLog(id="activity-log", wrap=False, max_lines=2000, auto_scroll=True)

    def append_line(self, raw: str) -> None:
        raw = raw.strip()
        if not raw:
            return
        log = self.query_one("#activity-log", RichLog)
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            log.write(Text(raw))
            return
        log.write(_format_event(payload))

    def populate_tail(self, limit: int = 200) -> None:
        if not self.activity_path.exists():
            return
        lines = self.activity_path.read_text(encoding="utf-8").splitlines()
        for line in lines[-limit:]:
            self.append_line(line)
