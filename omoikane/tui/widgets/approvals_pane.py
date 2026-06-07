"""Pending-approvals panel — sourced from ``book.pending_approvals``."""
from __future__ import annotations

from typing import Any, Dict, List

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container
from textual.widgets import ListItem, ListView, Static


class ApprovalsPane(Container):
    DEFAULT_CSS = """
    ApprovalsPane {
        border: tall $error;
        height: auto;
        min-height: 6;
    }
    ApprovalsPane > Static.title {
        background: $boost;
        padding: 0 1;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._items: List[Dict[str, Any]] = []

    def compose(self) -> ComposeResult:
        yield Static("Pending approvals (F2 approve · F3 deny)", classes="title")
        yield ListView(id="approvals-list")

    def update_from_book(self, book: Dict[str, Any]) -> None:
        pending = [
            a for a in (book.get("pending_approvals") or [])
            if (a.get("status") or "pending") == "pending"
        ]
        self._items = pending
        view = self.query_one("#approvals-list", ListView)
        view.clear()
        if not pending:
            view.append(ListItem(Static(Text("(no pending approvals)", style="dim"))))
            return
        for approval in pending:
            view.append(ListItem(Static(self._render_entry(approval))))

    def selected_approval(self) -> Dict[str, Any]:
        view = self.query_one("#approvals-list", ListView)
        if view.index is None or view.index >= len(self._items):
            return {}
        return self._items[view.index]

    @staticmethod
    def _render_entry(approval: Dict[str, Any]) -> Text:
        text = Text()
        text.append(f"[{approval.get('approval_id', '?')}] ", style="bold")
        text.append(f"{approval.get('requester_role', '-')} ", style="cyan")
        text.append(approval.get("action", "?"), style="yellow")
        text.append("  ")
        cmd = approval.get("command") or approval.get("reason") or ""
        text.append(cmd[:80], style="dim")
        return text
