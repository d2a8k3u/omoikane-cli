"""prepare_manager_handoff — manager dispatch payload builder."""

import json

from omoikane.core.book import ProjectBook
from omoikane.tools import prepare_manager_handoff


def test_payload_contains_manager_skill_and_report(temp_hermes_home):
    book = ProjectBook.create("Build CLI", ["task X works", "tests pass"])
    task_id = book.open_task(
        "Implement feature",
        assignee_role="agent-implementer",
        phase="implementation",
    )

    res = json.loads(prepare_manager_handoff({
        "project_id": book.project_id,
        "task_id": task_id,
        "subagent_role": "agent-implementer",
        "subagent_summary": "Implemented feature; tests pass; see commit abcd1234.",
        "subagent_exit_status": "success",
    }))
    assert res["success"] is True
    assert res["toolsets"] == ["omoikane"]
    assert task_id in res["goal"]

    ctx = res["context"]
    # Manager SKILL must be inlined — that's the whole point of this tool.
    assert "Manager rules (SKILL.md)" in ctx
    assert "ledger keeper" in ctx or "agent-manager" in ctx
    # Report fields must be present verbatim.
    assert task_id in ctx
    assert "agent-implementer" in ctx
    assert "subagent_exit_status:  success" in ctx
    assert "Implemented feature; tests pass" in ctx
    # Project context must include brief + criteria.
    assert "Build CLI" in ctx
    assert "task X works" in ctx
    assert "tests pass" in ctx


def test_payload_requires_core_fields(temp_hermes_home):
    book = ProjectBook.create("brief", ["AC"])
    res = json.loads(prepare_manager_handoff({
        "project_id": book.project_id,
        "task_id": "task-0001",
        # subagent_role + subagent_summary missing
    }))
    assert "error" in res
    assert "required" in res["error"]


def test_payload_surfaces_max_iters_reached_status(temp_hermes_home):
    book = ProjectBook.create("brief", ["AC"])
    tid = book.open_task("t", assignee_role="agent-implementer")
    res = json.loads(prepare_manager_handoff({
        "project_id": book.project_id,
        "task_id": tid,
        "subagent_role": "agent-implementer",
        "subagent_summary": "ran out of iterations mid-edit",
        "subagent_exit_status": "max_iters_reached",
    }))
    assert res["success"] is True
    assert "subagent_exit_status:  max_iters_reached" in res["context"]


def test_payload_defaults_exit_status_to_success(temp_hermes_home):
    book = ProjectBook.create("brief", ["AC"])
    tid = book.open_task("t", assignee_role="agent-implementer")
    res = json.loads(prepare_manager_handoff({
        "project_id": book.project_id,
        "task_id": tid,
        "subagent_role": "agent-implementer",
        "subagent_summary": "done",
    }))
    assert res["success"] is True
    assert "subagent_exit_status:  success" in res["context"]
