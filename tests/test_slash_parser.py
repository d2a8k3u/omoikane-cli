"""Slash parser — shared between TUI input bar and ``omoikane inject``."""
from __future__ import annotations

from omoikane.cli.slash import parse_input


def test_empty_input_returns_none():
    assert parse_input("") is None
    assert parse_input("   ") is None
    assert parse_input(None) is None


def test_bare_text_targets_cto():
    out = parse_input("rebuild the schema migration")
    assert out == {"target": "agent-cto", "content": "rebuild the schema migration"}


def test_explicit_cto_prefix():
    out = parse_input("/cto switch ORM to SQLAlchemy")
    assert out == {"target": "agent-cto", "content": "switch ORM to SQLAlchemy"}


def test_task_shorthand_captures_id_and_body():
    out = parse_input("/task:t-42 add the missing index")
    assert out == {"target": "task:t-42", "content": "add the missing index"}


def test_picker_target():
    out = parse_input("/picker pause picking new tasks for 5 minutes")
    assert out == {"target": "__picker__", "content": "pause picking new tasks for 5 minutes"}


def test_broadcast_alias_routes_to_star():
    out = parse_input("/broadcast deploy freeze")
    assert out == {"target": "*", "content": "deploy freeze"}


def test_specialist_role_shorthand():
    out = parse_input("/backend-engineer add an explain query")
    # Either matches the agent-* form or the canonical name.
    assert out["target"] in {"agent-backend-engineer", "backend-engineer"}
    assert out["content"] == "add an explain query"


def test_unknown_slash_routes_to_control_with_unknown_flag():
    out = parse_input("/totally-unknown blah")
    assert out["target"] == "__control__"
    assert out["command"] == "totally-unknown"
    assert out["unknown"] is True


def test_approve_command():
    out = parse_input("/approve a-7")
    assert out == {
        "target": "__control__",
        "command": "approve",
        "args": "a-7",
    }


def test_deny_command_with_reason():
    out = parse_input("/deny a-7 dangerous rm -rf")
    assert out == {
        "target": "__control__",
        "command": "deny",
        "args": "a-7 dangerous rm -rf",
    }
