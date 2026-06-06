"""Approval self-gating prompt addendum + CLI surface."""
from __future__ import annotations

import json

from omoikane.cli.commands import approvals as approvals_cmd
from omoikane.core.book import ProjectBook
from omoikane.runtime import prompts as _prompts
from omoikane.runtime.agent_run import AgentRun, RunConfig


def test_addendum_present_for_terminal_role():
    text = _prompts.approval_addendum("agent-implementer", ["file", "terminal"])
    assert "book_request_approval" in text
    assert "rm -rf" in text
    assert "agent-implementer" in text


def test_addendum_absent_for_read_only_role():
    assert _prompts.approval_addendum("agent-tech-writer", ["file", "web"]) == ""


_ADDENDUM_MARKER = "Approval self-gating"


def test_agent_run_system_prompt_includes_addendum_for_terminal_role(
    temp_hermes_home,
):
    book = ProjectBook.create("brief", ["AC"])
    config = RunConfig(model="fake/model", api_key="dummy")
    run = AgentRun(
        book.project_id,
        role="agent-backend-engineer",
        book=book.load(),
        config=config,
    )
    assert _ADDENDUM_MARKER in run.system_prompt


def test_agent_run_system_prompt_skips_addendum_for_read_only_role(
    temp_hermes_home,
):
    book = ProjectBook.create("brief", ["AC"])
    config = RunConfig(model="fake/model", api_key="dummy")
    run = AgentRun(
        book.project_id,
        role="agent-tech-writer",
        book=book.load(),
        config=config,
    )
    # Tech writer never gets terminal/code_execution toolsets so the
    # self-gating block stays out of its system prompt.
    assert _ADDENDUM_MARKER not in run.system_prompt


def _file_approval(book: ProjectBook) -> str:
    return book.request_approval(
        requester_role="agent-backend-engineer",
        task_id="t-1",
        action="execute_command",
        command="rm -rf /tmp/foo",
        reason="cleanup",
    )


def test_approvals_list_returns_pending_row(temp_hermes_home, capsys):
    book = ProjectBook.create("brief", ["AC"])
    _file_approval(book)
    rc = approvals_cmd._cmd_list(
        type("A", (), {"project_id": book.project_id, "json": True})()
    )
    assert rc == 0
    captured = capsys.readouterr().out
    payload = json.loads(captured)
    assert len(payload) == 1
    assert payload[0]["requester_role"] == "agent-backend-engineer"


def test_approvals_resolve_marks_decision(temp_hermes_home, capsys):
    book = ProjectBook.create("brief", ["AC"])
    aid = _file_approval(book)
    args = type("A", (), {
        "project_id": book.project_id,
        "approval_id": aid,
        "note": "ok",
    })()
    rc = approvals_cmd._cmd_resolve(args, decision="approve")
    assert rc == 0
    data = ProjectBook(book.project_id).load()
    matched = [a for a in data["pending_approvals"] if a["approval_id"] == aid]
    assert matched
    assert matched[0]["status"] in {"approve", "approved"}
