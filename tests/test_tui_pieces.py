"""TUI widget unit tests that do not need a running Textual app loop."""
from __future__ import annotations

import asyncio
import json

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Static

from omoikane.core.book import ProjectBook
from omoikane.tui.app import OmoikaneApp


@pytest.mark.asyncio
async def test_app_mounts_and_streams_activity(temp_hermes_home):
    book = ProjectBook.create("brief", ["AC1"])
    activity_path = book.store.activity_path
    activity_path.write_text(json.dumps({
        "ts": "2026-06-07T00:00:00", "kind": "tool_call",
        "role": "agent-cto", "tool": "book_log", "args_preview": "{}",
    }) + "\n")

    app = OmoikaneApp(book.project_id, poll_interval=0.05, max_initial_lines=200)
    async with app.run_test() as pilot:
        # Allow a tick so on_mount finishes and the first poll runs.
        await pilot.pause(0.1)
        # Append a new activity line and confirm the polling loop drains it.
        with open(activity_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "ts": "2026-06-07T00:00:01", "kind": "operator_steer",
                "role": "agent-cto", "summary": "use uuid v7",
            }) + "\n")
        await pilot.pause(0.2)
        from omoikane.tui.widgets.activity_pane import ActivityPane
        log = pilot.app.query_one(ActivityPane)
        assert log is not None
        await pilot.press("ctrl+c")


class _SingleWidgetHost(App):
    """Throwaway host that mounts exactly one widget for assertions."""

    def __init__(self, widget):
        super().__init__()
        self._widget = widget

    def compose(self) -> ComposeResult:
        yield self._widget


@pytest.mark.asyncio
async def test_criteria_pane_renders_marker_for_satisfied(temp_hermes_home):
    from omoikane.tui.widgets.criteria_pane import CriteriaPane

    book = ProjectBook.create("brief", ["First criterion", "Second criterion"])
    book.satisfy_criterion(0)
    data = book.load()

    pane = CriteriaPane()
    async with _SingleWidgetHost(pane).run_test() as pilot:
        pane.update_from_book(data)
        await pilot.pause()
        body = pane.query_one("#criteria-body", Static)
        rendered = body.visual.plain

    assert "[x] (0) First criterion" in rendered
    assert "[ ] (1) Second criterion" in rendered


@pytest.mark.asyncio
async def test_status_bar_text_includes_status_and_phase(temp_hermes_home):
    from omoikane.tui.widgets.status_bar import StatusBar

    book = ProjectBook.create("brief", ["AC"])
    data = book.load()

    bar = StatusBar()
    async with _SingleWidgetHost(bar).run_test() as pilot:
        bar.update_from_book(data, daemon_running=False)
        await pilot.pause()
        plain = bar.visual.plain

    assert data["title"] in plain
    assert f"status={data['status']}" in plain
    assert f"phase={data['current_phase']}" in plain
