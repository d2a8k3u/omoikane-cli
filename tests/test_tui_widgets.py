"""TUI widget coverage tests that drive the live Textual app loop.

These pin behaviours that were previously unexercised:

- B2: incremental ``activity.jsonl`` drain (offset advances, no re-read)
- B3: input-bar slash routing into ``inbox.jsonl``
- B4: delegation-tree construction from ``delegation.json``
"""
from __future__ import annotations

import json
import os

import pytest

from omoikane.config import paths
from omoikane.core.book import ProjectBook
from omoikane.tui.app import OmoikaneApp


def _write_activity(path, count: int) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        for i in range(count):
            fh.write(json.dumps({
                "ts": f"2026-06-07T00:00:{i:02d}",
                "kind": "tool_call",
                "role": "agent-cto",
                "tool": "book_log",
                "args_preview": "{}",
            }) + "\n")


# ----------------------------------------------------------------------
# B2 — activity pane incremental drain
# ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_activity_drain_advances_offset_without_reread(temp_hermes_home):
    book = ProjectBook.create("brief", ["AC1"])
    activity_path = book.store.activity_path
    _write_activity(activity_path, 3)

    app = OmoikaneApp(book.project_id, poll_interval=0.05, max_initial_lines=200)
    async with app.run_test() as pilot:
        await pilot.pause(0.15)
        log = app.query_one("#activity-log")
        assert len(log.lines) == 3
        first_offset = app._tail_position
        assert first_offset == os.path.getsize(activity_path)

        with open(activity_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "ts": "2026-06-07T00:00:09",
                "kind": "operator_steer",
                "role": "agent-cto",
                "summary": "use uuid v7",
            }) + "\n")
        new_eof = os.path.getsize(activity_path)
        await pilot.pause(0.2)

        # Exactly one new line rendered — a full re-read would yield 7.
        assert len(log.lines) == 4
        # Offset advanced strictly and now sits at the new EOF.
        assert app._tail_position > first_offset
        assert app._tail_position == new_eof


# ----------------------------------------------------------------------
# B3 — input bar slash → inbox.jsonl
# ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_input_bar_slash_command_writes_inbox(temp_hermes_home):
    from textual.widgets import Input

    book = ProjectBook.create("brief", ["AC1"])
    app = OmoikaneApp(book.project_id, poll_interval=0.05)
    async with app.run_test() as pilot:
        await pilot.pause(0.1)
        inp = app.query_one("#operator-input", Input)
        inp.focus()
        inp.value = "/cto deploy now"
        await pilot.press("enter")
        await pilot.pause(0.1)

    inbox = paths.project_dir(book.project_id) / "inbox.jsonl"
    entries = [json.loads(l) for l in inbox.read_text(encoding="utf-8").splitlines()]
    assert len(entries) == 1
    assert entries[0]["target"] == "agent-cto"
    assert entries[0]["content"] == "deploy now"


@pytest.mark.asyncio
async def test_input_bar_bare_text_routes_to_cto(temp_hermes_home):
    from textual.widgets import Input

    book = ProjectBook.create("brief", ["AC1"])
    app = OmoikaneApp(book.project_id, poll_interval=0.05)
    async with app.run_test() as pilot:
        await pilot.pause(0.1)
        inp = app.query_one("#operator-input", Input)
        inp.focus()
        inp.value = "ship it"
        await pilot.press("enter")
        await pilot.pause(0.1)

    inbox = paths.project_dir(book.project_id) / "inbox.jsonl"
    entries = [json.loads(l) for l in inbox.read_text(encoding="utf-8").splitlines()]
    assert len(entries) == 1
    assert entries[0]["target"] == "agent-cto"
    assert entries[0]["content"] == "ship it"


# ----------------------------------------------------------------------
# B4 — delegation pane tree from real delegation.json
# ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_delegation_pane_builds_nested_tree(temp_hermes_home):
    book = ProjectBook.create("brief", ["AC1"])
    book.store.add_delegation(task="design", to_role="agent-cto", expected="x")
    book.store.add_delegation(
        task="impl", to_role="agent-eng", expected="y", from_node="n-design",
    )

    app = OmoikaneApp(book.project_id, poll_interval=0.05)
    async with app.run_test() as pilot:
        await pilot.pause(0.15)
        tree = app.query_one("#delegation-tree")
        tree.root.expand_all()
        await pilot.pause()

        root_labels = [c.label.plain for c in tree.root.children]
        assert root_labels == ["agent-cto :: design"]

        nested_labels = [
            g.label.plain
            for c in tree.root.children
            for g in c.children
        ]
        assert nested_labels == ["agent-eng :: impl"]
