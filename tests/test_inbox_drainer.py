"""Inbox channel — write + drain + dedup."""
from __future__ import annotations

from omoikane.core.book import ProjectBook
from omoikane.runtime.injection import (
    BROADCAST_TARGET,
    CTO_TARGET,
    InboxDrainer,
    write_message,
)


def test_write_and_drain_round_trip(temp_hermes_home):
    book = ProjectBook.create("brief", ["AC1"])
    mid = write_message(book.project_id, "Switch the schema to uuid v7.")

    drainer = InboxDrainer(book.project_id)
    drained = drainer.drain()
    assert len(drained) == 1
    assert drained[0]["msg_id"] == mid
    assert drained[0]["content"].startswith("Switch the schema")


def test_drain_marks_consumed(temp_hermes_home):
    book = ProjectBook.create("brief", ["AC1"])
    write_message(book.project_id, "first")
    write_message(book.project_id, "second")

    drainer = InboxDrainer(book.project_id)
    first = drainer.drain()
    second = drainer.drain()

    assert {e["content"] for e in first} == {"first", "second"}
    assert second == []


def test_target_filter(temp_hermes_home):
    book = ProjectBook.create("brief", ["AC1"])
    write_message(book.project_id, "for the CTO", target=CTO_TARGET)
    write_message(book.project_id, "for the picker", target="__picker__")
    write_message(book.project_id, "broadcast", target=BROADCAST_TARGET)

    drainer = InboxDrainer(book.project_id)
    cto_msgs = drainer.drain(target=CTO_TARGET)
    contents = sorted(m["content"] for m in cto_msgs)
    assert contents == ["broadcast", "for the CTO"]

    # broadcast already consumed; picker still has its own message.
    picker_msgs = drainer.drain(target="__picker__")
    assert [m["content"] for m in picker_msgs] == ["for the picker"]


def test_peek_does_not_consume(temp_hermes_home):
    book = ProjectBook.create("brief", ["AC1"])
    write_message(book.project_id, "hello")

    drainer = InboxDrainer(book.project_id)
    assert len(drainer.peek()) == 1
    assert len(drainer.peek()) == 1
    drained = drainer.drain()
    assert len(drained) == 1
    assert drainer.peek() == []


def test_drain_handles_missing_inbox(temp_hermes_home):
    book = ProjectBook.create("brief", ["AC1"])
    drainer = InboxDrainer(book.project_id)
    # No inbox.jsonl yet — drain must not raise.
    assert drainer.drain() == []


def test_drain_ignores_malformed_lines(temp_hermes_home):
    book = ProjectBook.create("brief", ["AC1"])
    inbox = (book.store.project_dir / "inbox.jsonl")
    inbox.write_text(
        "{\"msg_id\":\"good\",\"target\":\"agent-cto\",\"content\":\"hi\"}\n"
        "not json at all\n"
    )
    drainer = InboxDrainer(book.project_id)
    drained = drainer.drain()
    assert [e["msg_id"] for e in drained] == ["good"]
