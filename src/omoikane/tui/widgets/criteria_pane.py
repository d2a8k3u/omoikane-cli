"""Acceptance criteria checklist sourced from book.json."""
from __future__ import annotations

from typing import Any, Dict, List

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container
from textual.widgets import Static


class CriteriaPane(Container):
    DEFAULT_CSS = """
    CriteriaPane {
        border: tall $success;
        height: auto;
    }
    CriteriaPane > Static.title {
        background: $boost;
        padding: 0 1;
    }
    CriteriaPane > Static#criteria-body {
        padding: 1;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def compose(self) -> ComposeResult:
        yield Static("Acceptance criteria", classes="title")
        yield Static("(no project loaded)", id="criteria-body")

    def update_from_book(self, book: Dict[str, Any]) -> None:
        criteria: List[str] = book.get("acceptance_criteria") or []
        statuses: Dict[str, str] = book.get("criteria_status") or {}
        text = Text()
        if not criteria:
            text.append("(no acceptance criteria)")
        for idx, item in enumerate(criteria):
            satisfied = statuses.get(str(idx)) == "satisfied"
            marker = "[x]" if satisfied else "[ ]"
            style = "green" if satisfied else "white"
            text.append(f"{marker} ", style=style)
            text.append(f"({idx}) ")
            text.append(f"{item}\n", style=style)
        body = self.query_one("#criteria-body", Static)
        body.update(text)
