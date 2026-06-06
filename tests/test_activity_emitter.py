"""ActivityEmitter — JSONL append + book.log fan-out + redaction."""
from __future__ import annotations

import json

import pytest

from omoikane.core.book import ProjectBook
from omoikane.runtime import activity_emitter as _activity


@pytest.fixture(autouse=True)
def _reset_emitter_cache():
    _activity.reset_cache_for_tests()
    yield
    _activity.reset_cache_for_tests()


def test_emit_writes_jsonl_line(temp_hermes_home):
    book = ProjectBook.create("brief", ["AC1"])
    emitter = _activity.for_project(book.project_id)

    baseline_lines = emitter.path.read_text(encoding="utf-8").splitlines()

    emitter.emit("custom", {"summary": "Hello", "n": 3})

    lines = emitter.path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == len(baseline_lines) + 1
    payload = json.loads(lines[-1])
    assert payload["kind"] == "custom"
    assert payload["summary"] == "Hello"
    assert payload["n"] == 3
    assert "ts" in payload


def test_emit_redacts_secret_keys(temp_hermes_home):
    book = ProjectBook.create("brief", ["AC1"])
    emitter = _activity.for_project(book.project_id)

    emitter.emit("tool_output", {
        "tool": "shell",
        "output_preview": "OPENAI_API_KEY=sk-proj-AAAABBBBCCCCDDDDEEEEFFFFGGGGHHHHIIIIJJJJ done",
    })

    last = json.loads(emitter.path.read_text(encoding="utf-8").splitlines()[-1])
    assert "sk-proj-AAAA" not in last["output_preview"]
    assert "[REDACTED]" in last["output_preview"]


def test_emit_fans_out_book_log_for_semantic_kinds(temp_hermes_home):
    book = ProjectBook.create("brief", ["AC1"])
    emitter = _activity.for_project(book.project_id)

    emitter.delegation_spawned(
        parent_role="agent-cto",
        child_role="agent-backend-engineer",
        task="t-init",
        brief="Build feature",
    )

    # ActivityEmitter writes to activity.jsonl always, and to the Book's
    # own activity log for semantic kinds.
    book_lines = book.store.activity_path.read_text(encoding="utf-8").splitlines()
    assert any("delegation_spawned" in line for line in book_lines)


def test_for_project_caches_per_project(temp_hermes_home):
    book = ProjectBook.create("brief", ["AC1"])
    one = _activity.for_project(book.project_id)
    two = _activity.for_project(book.project_id)
    assert one is two


def test_truncate_long_streams(temp_hermes_home):
    book = ProjectBook.create("brief", ["AC1"])
    emitter = _activity.for_project(book.project_id)
    emitter.stream_delta("agent-cto", "x" * 10_000)
    line = json.loads(emitter.path.read_text(encoding="utf-8").splitlines()[-1])
    assert len(line["delta"]) <= 4001  # 4000 chars + ellipsis
