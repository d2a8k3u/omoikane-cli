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


def test_build_completeness_directive_targets_intent_and_routes_for_sizing(temp_hermes_home):
    book = ProjectBook.create("Brief here", ["AC one", "AC two"])
    book.satisfy_criterion(0)
    book.satisfy_criterion(1)
    msg = prompts.build_completeness_directive(book.project_id, book.load())
    assert "Brief here" in msg
    assert "AC one" in msg and "AC two" in msg
    assert "book_set_criteria" in msg
    # Fix work is routed through the CTO (sizing), not opened directly.
    assert "book_request_task" in msg
    assert "book_open_task" not in msg


def test_build_qa_directive_routes_fixes_via_cto_with_roster(temp_hermes_home):
    book = ProjectBook.create("Brief here", ["AC one", "AC two"])
    msg = prompts.build_qa_directive(book.project_id, book.load())
    # QA must pick the fix executor from the whole team, not from memory.
    assert "Team roster" in msg
    assert "agent-architekt" in msg
    # Fixes route through the CTO (best-fit routing + sizing), not direct-assign.
    assert "book_request_task" in msg
    assert "book_open_task" not in msg
    # Non-routable roles are never offered as a target.
    assert "- agent-manager:" not in msg
    assert "- orchestrator-protocol:" not in msg


def test_build_completeness_directive_carries_roster(temp_hermes_home):
    book = ProjectBook.create("Brief here", ["AC one"])
    book.satisfy_criterion(0)
    msg = prompts.build_completeness_directive(book.project_id, book.load())
    assert "Team roster" in msg
    assert "agent-architekt" in msg
    assert "- agent-manager:" not in msg
    # Regression: completeness fixes still route via CTO, never direct.
    assert "book_request_task" in msg
    assert "book_open_task" not in msg


def test_specialist_manual_carries_escalation_and_upstream_read(temp_hermes_home):
    book = ProjectBook.create("Brief", ["AC"])
    manual = prompts.build_role_system_prompt(
        book.project_id, book.load(),
        role="agent-backend-engineer",
        enabled_toolsets=["file", "terminal", "omoikane"],
    )
    assert "book_request_task" in manual            # escalation channel
    assert "upstream-decision" in manual.lower() or "upstream" in manual.lower()


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
