"""CTO prompt builders + inject formatter."""
from __future__ import annotations

from omoikane.core.book import ProjectBook
from omoikane.runtime import prompts


def test_format_inject_renders_block():
    rendered = prompts.format_inject([
        {"ts": "2026-06-07T12:00:00Z", "target": "agent-cto", "content": "Use uuid v7"},
        {"ts": "2026-06-07T12:01:00Z", "target": "agent-cto", "content": "Cache the result"},
    ])
    assert prompts.INJECT_START in rendered
    assert prompts.INJECT_END in rendered
    assert "Use uuid v7" in rendered
    assert "Cache the result" in rendered


def test_prepend_injects_no_op_on_empty():
    assert prompts.prepend_injects("hello", []) == "hello"


def test_build_initial_directive_includes_project_state(temp_hermes_home):
    book = ProjectBook.create("Brief here", ["AC one", "AC two"])
    data = book.load()
    msg = prompts.build_initial_directive(book.project_id, data)
    assert book.project_id in msg
    assert data["current_phase"] in msg


def test_build_cto_system_prompt_pulls_skill(temp_hermes_home):
    book = ProjectBook.create("Brief", ["AC"])
    data = book.load()
    prompt = prompts.build_cto_system_prompt(
        book.project_id, data,
        enabled_toolsets=["file", "delegation", "omoikane"],
    )
    assert "Brief" in prompt
    assert "delegate_task" in prompt
    assert "omoikane" in prompt


def test_history_round_trip(temp_hermes_home):
    book = ProjectBook.create("Brief", ["AC"])
    sample = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "go"},
        {"role": "assistant", "content": "ok"},
    ]
    prompts.save_cto_history(book.project_id, sample)
    loaded = prompts.load_cto_history(book.project_id)
    assert loaded == sample


def test_history_missing_returns_empty(temp_hermes_home):
    book = ProjectBook.create("Brief", ["AC"])
    assert prompts.load_cto_history(book.project_id) == []
