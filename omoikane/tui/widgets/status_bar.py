"""Compact status header — title / status / phase / daemon-online dot."""
from __future__ import annotations

from rich.text import Text
from textual.containers import Container
from textual.widgets import Static


class StatusBar(Static):
    DEFAULT_CSS = """
    StatusBar {
        dock: top;
        height: 1;
        background: $boost;
        padding: 0 1;
    }
    """

    def update_from_book(self, book: dict, *, daemon_running: bool) -> None:
        text = Text()
        text.append("● ", style="green" if daemon_running else "red")
        text.append(book.get("title") or "untitled", style="bold")
        text.append(f"  status={book.get('status') or '?'}", style="dim")
        text.append(f"  phase={book.get('current_phase') or '?'}", style="dim")
        criteria = book.get("acceptance_criteria") or []
        status = book.get("criteria_status") or {}
        satisfied = sum(1 for v in status.values() if v == "satisfied")
        text.append(f"  criteria={satisfied}/{len(criteria)}", style="dim")
        self.update(text)
