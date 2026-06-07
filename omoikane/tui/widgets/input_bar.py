"""Operator input bar — slash parser → inbox.jsonl."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container
from textual.message import Message
from textual.widgets import Input, Static

from omoikane.cli.slash import parse_input
from omoikane.runtime.injection import write_message


class InputBar(Container):
    DEFAULT_CSS = """
    InputBar {
        dock: bottom;
        height: 3;
        border: tall $primary;
    }
    InputBar > Static#input-hint {
        color: $text-muted;
        padding: 0 1;
    }
    InputBar > Input {
        height: 1;
    }
    """

    class Sent(Message):
        def __init__(self, parsed: dict):
            super().__init__()
            self.parsed = parsed

    def __init__(self, project_id: str, **kwargs):
        super().__init__(**kwargs)
        self.project_id = project_id

    def compose(self) -> ComposeResult:
        yield Static(
            "type a message for the CTO, or /cto, /task:<id>, /<role>, "
            "/approve <id>, /deny <id>, /broadcast …",
            id="input-hint",
        )
        yield Input(placeholder="message...", id="operator-input")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        parsed = parse_input(event.value)
        event.input.value = ""
        if not parsed:
            return
        # Route to inbox for normal inject targets; control verbs pass
        # through as a message so the app can act on them directly.
        if parsed.get("target") != "__control__":
            content = parsed.get("content") or ""
            if content.strip():
                write_message(self.project_id, content, target=parsed["target"])
        self.post_message(self.Sent(parsed))
