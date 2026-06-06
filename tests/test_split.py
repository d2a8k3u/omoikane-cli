"""Task splitting flow: specialist/manager files split → CTO splits → children open."""

import json

import pytest

from omoikane.core.book import DEFAULT_TASK_SIZE_BUDGET_MINUTES, ProjectBook
from omoikane.core.orchestrator import TeamOrchestrator
from omoikane.tools import book_request_split, book_split_task


# ---------------------------------------------------------------------------
# Defaults exposed
# ---------------------------------------------------------------------------

def test_default_task_size_budget_is_20_minutes():
    assert DEFAULT_TASK_SIZE_BUDGET_MINUTES == 20


def test_book_seeds_task_size_budget_on_load(temp_hermes_home):
    book = ProjectBook.create("brief", ["AC"])
    data = book.load()
    assert data["task_size_budget_minutes"] == 20


# ---------------------------------------------------------------------------
# request_split
# ---------------------------------------------------------------------------

def test_request_split_flags_task_and_files_routing(temp_hermes_home):
    book = ProjectBook.create("brief", ["AC"])
    tid = book.open_task("Implement big feature", assignee_role="agent-implementer",
                         phase="implementation")

    routing_id = book.request_split(
        task_id=tid,
        requester_role="agent-implementer",
        reason="Hit iter cap at 40% — three subsystems still untouched.",
        suggested_subtasks=[
            {"title": "Wire DB schema", "estimated_minutes": 15},
            {"title": "Wire API layer", "estimated_minutes": 15},
            {"title": "Wire integration test", "estimated_minutes": 15},
        ],
    )
    assert routing_id is not None
    data = book.load()
    assert data["task_meta"][tid]["split_status"] == "requested"
    assert data["task_meta"][tid]["split_reason"].startswith("Hit iter cap")
    assert data["task_meta"][routing_id]["assignee_role"] == "agent-cto"
    assert data["task_meta"][routing_id]["routing_status"] == "routing"
    assert data["task_meta"][routing_id]["phase"] == "meta"
    assert (
        data["task_meta"][routing_id]["execution_metadata"]["kind"]
        == "split_request"
    )
    assert data["task_meta"][routing_id]["execution_metadata"]["original_task"] == tid

    pending = book.list_pending_split_requests()
    assert len(pending) == 1
    assert pending[0]["task_id"] == tid


def test_request_split_idempotent_for_already_flagged(temp_hermes_home):
    book = ProjectBook.create("brief", ["AC"])
    tid = book.open_task("big", assignee_role="agent-implementer")
    first = book.request_split(
        task_id=tid, requester_role="agent-implementer",
        reason="r1", suggested_subtasks=[],
    )
    assert first is not None
    second = book.request_split(
        task_id=tid, requester_role="agent-implementer",
        reason="r2", suggested_subtasks=[],
    )
    assert second is None  # no duplicate routing task
    data = book.load()
    routing_open_for_split = [
        t for t in data["open_tasks"]
        if data["task_meta"][t].get("execution_metadata", {}).get(
            "original_task"
        ) == tid
    ]
    assert len(routing_open_for_split) == 1
    assert data["task_meta"][tid]["split_reason"] == "r2"


def test_request_split_returns_none_for_unknown_task(temp_hermes_home):
    book = ProjectBook.create("brief", ["AC"])
    assert book.request_split(
        task_id="task-9999", requester_role="agent-implementer",
        reason="ghost", suggested_subtasks=[],
    ) is None


# ---------------------------------------------------------------------------
# split_task
# ---------------------------------------------------------------------------

def test_split_task_closes_parent_and_opens_children(temp_hermes_home):
    book = ProjectBook.create("brief", ["AC"])
    tid = book.open_task("Implement big feature",
                         assignee_role="agent-implementer", phase="implementation")
    book.request_split(
        task_id=tid, requester_role="agent-implementer",
        reason="too big", suggested_subtasks=[],
    )

    child_ids = book.split_task(
        task_id=tid,
        requester_role="agent-cto",
        replacement_specs=[
            {"title": "Wire DB", "assignee_role": "agent-database-specialist",
             "phase": "implementation", "estimated_minutes": 15},
            {"title": "Wire API", "assignee_role": "agent-backend-engineer",
             "phase": "implementation", "estimated_minutes": 15,
             "blocked_by": [0]},
            {"title": "Wire integration test", "assignee_role": "agent-qa-reviewer",
             "phase": "testing", "estimated_minutes": 10, "blocked_by": [1]},
        ],
        reflection="DB → API → test chain. Each step ≤ 15 min.",
    )
    assert child_ids is not None and len(child_ids) == 3
    data = book.load()

    # Parent closed.
    assert tid in data["completed_tasks"]
    assert tid not in data["open_tasks"]
    assert data["task_meta"][tid]["closure_kind"] == "split"
    assert data["task_meta"][tid]["split_into"] == child_ids
    assert data["task_meta"][tid]["split_status"] == "resolved"

    # Children open with correct assignees + blocked_by chain resolved to real ids.
    assert all(cid in data["open_tasks"] for cid in child_ids)
    assert data["task_meta"][child_ids[0]]["assignee_role"] == "agent-database-specialist"
    assert data["task_meta"][child_ids[1]]["blocked_by"] == [child_ids[0]]
    assert data["task_meta"][child_ids[2]]["blocked_by"] == [child_ids[1]]
    assert data["task_meta"][child_ids[0]]["execution_metadata"]["estimated_minutes"] == 15

    # Split request marked resolved.
    pending = book.list_pending_split_requests()
    assert pending == []


def test_split_task_rejects_empty_replacements(temp_hermes_home):
    book = ProjectBook.create("brief", ["AC"])
    tid = book.open_task("big", assignee_role="agent-implementer")
    assert book.split_task(
        task_id=tid, requester_role="agent-cto",
        replacement_specs=[],
    ) is None


def test_split_task_validates_each_spec(temp_hermes_home):
    book = ProjectBook.create("brief", ["AC"])
    tid = book.open_task("big", assignee_role="agent-implementer")
    with pytest.raises(ValueError):
        book.split_task(
            task_id=tid, requester_role="agent-cto",
            replacement_specs=[{"title": "no role"}],
        )
    with pytest.raises(ValueError):
        book.split_task(
            task_id=tid, requester_role="agent-cto",
            replacement_specs=[{"assignee_role": "agent-implementer"}],
        )


# ---------------------------------------------------------------------------
# Tool-handler JSON contract
# ---------------------------------------------------------------------------

def test_book_request_split_tool_returns_routing_id(temp_hermes_home):
    book = ProjectBook.create("brief", ["AC"])
    tid = book.open_task("big", assignee_role="agent-implementer")
    res = json.loads(book_request_split({
        "project_id": book.project_id,
        "task": tid,
        "requester_role": "agent-implementer",
        "reason": "too big to finish in one session",
        "suggested_subtasks": [{"title": "step 1"}, {"title": "step 2"}],
    }))
    assert res["success"] is True
    assert res["routing_task"] is not None
    assert res["split_status"] == "requested"


def test_book_request_split_tool_missing_fields(temp_hermes_home):
    book = ProjectBook.create("brief", ["AC"])
    res = json.loads(book_request_split({
        "project_id": book.project_id,
        "task": "task-1000",
    }))
    assert "error" in res
    assert "missing" in res["error"]


def test_book_split_task_tool_atomically_replaces(temp_hermes_home):
    book = ProjectBook.create("brief", ["AC"])
    tid = book.open_task("big", assignee_role="agent-implementer",
                         phase="implementation")
    book.request_split(
        task_id=tid, requester_role="agent-implementer",
        reason="r", suggested_subtasks=[],
    )
    res = json.loads(book_split_task({
        "project_id": book.project_id,
        "task": tid,
        "requester_role": "agent-cto",
        "replacement_tasks": [
            {"title": "Step A", "assignee_role": "agent-implementer",
             "estimated_minutes": 10},
            {"title": "Step B", "assignee_role": "agent-implementer",
             "estimated_minutes": 10, "blocked_by": [0]},
        ],
        "reflection": "Smaller steps.",
    }))
    assert res["success"] is True
    assert res["closure_kind"] == "split"
    assert len(res["children"]) == 2


def test_book_split_task_tool_rejects_empty_list(temp_hermes_home):
    book = ProjectBook.create("brief", ["AC"])
    tid = book.open_task("big", assignee_role="agent-implementer")
    res = json.loads(book_split_task({
        "project_id": book.project_id,
        "task": tid,
        "requester_role": "agent-cto",
        "replacement_tasks": [],
    }))
    assert "error" in res
    assert "non-empty" in res["error"]


# ---------------------------------------------------------------------------
# Orchestrator skip
# ---------------------------------------------------------------------------

def test_picker_skips_split_flagged_task(temp_hermes_home):
    book = ProjectBook.create("brief", ["AC"])
    book.update_status("in_progress", phase="implementation")
    big = book.open_task("big task", assignee_role="agent-implementer",
                         phase="implementation")
    small = book.open_task("small task", assignee_role="agent-implementer",
                           phase="implementation")
    routing_id = book.request_split(
        task_id=big, requester_role="agent-implementer",
        reason="too big", suggested_subtasks=[],
    )
    orch = TeamOrchestrator(book.project_id)
    data = book.load()
    # Routing task lands first (routing-first FIFO), big task is split-flagged
    # and must NOT be returned even after the routing task.
    picked = orch._pick_next_task(data, data["open_tasks"])
    assert picked == routing_id

    # Pretend CTO closed the routing task without filing the split yet —
    # the picker should fall through to the small task, NEVER the
    # split-flagged big one.
    data["open_tasks"].remove(routing_id)
    picked2 = orch._pick_next_task(data, data["open_tasks"])
    assert picked2 == small


def test_picker_re_dispatches_children_after_split(temp_hermes_home):
    book = ProjectBook.create("brief", ["AC"])
    book.update_status("in_progress", phase="implementation")
    big = book.open_task("big", assignee_role="agent-implementer",
                         phase="implementation")
    routing_id = book.request_split(
        task_id=big, requester_role="agent-implementer",
        reason="too big", suggested_subtasks=[],
    )
    child_ids = book.split_task(
        task_id=big, requester_role="agent-cto",
        replacement_specs=[
            {"title": "A", "assignee_role": "agent-implementer",
             "phase": "implementation"},
            {"title": "B", "assignee_role": "agent-implementer",
             "phase": "implementation", "blocked_by": [0]},
        ],
    )
    # In the real flow, manager closes the routing task after CTO returns
    # the split. Simulate that so the picker sees only the children.
    book.complete_task(routing_id)

    orch = TeamOrchestrator(book.project_id)
    data = book.load()
    picked = orch._pick_next_task(data, data["open_tasks"])
    # First unblocked child should be picked (A — index 0).
    assert picked == child_ids[0]


# ---------------------------------------------------------------------------
# Dispatch context includes self-monitor guidance
# ---------------------------------------------------------------------------

def test_dispatch_context_includes_size_budget(temp_hermes_home):
    book = ProjectBook.create("brief", ["AC"])
    book.update_status("in_progress", phase="implementation")
    book.open_task(
        "Implement feature", assignee_role="agent-implementer",
        phase="implementation",
        execution_metadata={"estimated_minutes": 18},
    )
    orch = TeamOrchestrator(book.project_id)
    data = book.load()
    plan = orch._plan_delegation(data["open_tasks"][0], data)
    ctx = plan["context"]
    assert "Self-monitor for task size" in ctx
    assert "≤ 20 minutes" in ctx
    assert "book_request_split" in ctx
    assert "Estimated minutes for this task" in ctx
