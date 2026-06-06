"""Routing flow: sub-agent request → CTO → executor."""

import json

from omoikane.core.book import ProjectBook
from omoikane.core.orchestrator import TeamOrchestrator
from omoikane.tools import book_assign_task, book_request_task


def test_request_task_creates_routing_to_cto(temp_hermes_home):
    book = ProjectBook.create("brief", ["AC"])
    res = json.loads(book_request_task({
        "project_id": book.project_id,
        "title": "Add a missing migration",
        "rationale": "Implementer hit a foreign-key error and needs DB schema fix",
        "requester_role": "agent-implementer",
        "suggested_role": "agent-database-specialist",
    }))
    assert res["success"] is True
    assert res["routing_status"] == "routing"
    assert res["assignee_role"] == "agent-cto"

    data = book.load()
    meta = data["task_meta"][res["task"]]
    assert meta["assignee_role"] == "agent-cto"
    assert meta["routing_status"] == "routing"
    assert meta["requester_role"] == "agent-implementer"
    assert meta["suggested_role"] == "agent-database-specialist"
    assert "foreign-key" in meta["rationale"]


def test_orchestrator_dispatches_routing_to_cto_first(temp_hermes_home):
    book = ProjectBook.create("brief", ["AC"])
    orch = TeamOrchestrator(book.project_id)
    orch.run_once()  # bootstrap

    # File a routing request AFTER bootstrap; orchestrator must service it
    # ahead of the executor tasks already in the queue.
    book_request_task({
        "project_id": book.project_id,
        "title": "Decompose auth flow",
        "rationale": "We need a security review before continuing",
        "requester_role": "agent-implementer",
    })
    result = orch.run_once()
    assert result["status"] == "in_progress"
    nd = result["next_delegation"]
    assert nd["to_role"] == "agent-cto"
    assert nd["routing"] is True
    assert "Routing brief" in nd["context"]
    assert "agent-implementer" in nd["context"]


def test_assign_task_routes_to_executor(temp_hermes_home):
    book = ProjectBook.create("brief", ["AC"])
    orch = TeamOrchestrator(book.project_id)
    orch.run_once()  # bootstrap

    # Clear the bootstrap executor queue so the routed task is unambiguously
    # the next executor pick once CTO has reassigned it. (FIFO order applies
    # to non-routing tasks.)
    data = book.load()
    data["open_tasks"] = []
    book.store.save_book(data)

    req = json.loads(book_request_task({
        "project_id": book.project_id,
        "title": "Audit secrets in config",
        "rationale": "Implementer found unmasked tokens in config.yaml",
        "requester_role": "agent-implementer",
    }))
    task_id = req["task"]

    # CTO sees it on the next tick
    first = orch.run_once()
    assert first["next_delegation"]["to_role"] == "agent-cto"
    assert first["next_delegation"]["task"] == task_id

    # CTO routes it to the security engineer
    assigned = json.loads(book_assign_task({
        "project_id": book.project_id,
        "task": task_id,
        "role": "agent-security-engineer",
    }))
    assert assigned["success"] is True
    assert assigned["assignee_role"] == "agent-security-engineer"
    assert assigned["routing_status"] == "assigned"

    # Next tick dispatches the same task to the assigned executor.
    second = orch.run_once()
    assert second["next_delegation"]["task"] == task_id
    assert second["next_delegation"]["to_role"] == "agent-security-engineer"
    assert second["next_delegation"]["routing"] is False


def test_assign_task_rejects_non_routing(temp_hermes_home):
    book = ProjectBook.create("brief", ["AC"])
    orch = TeamOrchestrator(book.project_id)
    orch.run_once()  # bootstrap creates executor tasks
    executor_task = book.load()["open_tasks"][0]

    res = json.loads(book_assign_task({
        "project_id": book.project_id,
        "task": executor_task,
        "role": "agent-frontend-engineer",
    }))
    assert "error" in res
    assert "routing state" in res["error"]


def test_request_task_missing_fields_returns_error(temp_hermes_home):
    book = ProjectBook.create("brief", ["AC"])
    res = json.loads(book_request_task({
        "project_id": book.project_id,
        "title": "x",
        # rationale + requester_role missing
    }))
    assert "error" in res


def test_request_task_includes_omoikane_in_toolsets(temp_hermes_home):
    """Sub-agents need the omoikane toolset to surface follow-up work."""
    book = ProjectBook.create("brief", ["AC"])
    orch = TeamOrchestrator(book.project_id)
    orch.run_once()  # bootstrap
    nd = orch.run_once()["next_delegation"]
    assert "omoikane" in nd["toolsets"]


def test_cto_routing_context_carries_team_roster_and_workload(temp_hermes_home):
    """CTO must see who they can route to, what each role does, and how
    loaded each is — otherwise routing is uninformed."""
    book = ProjectBook.create("brief", ["AC"])
    orch = TeamOrchestrator(book.project_id)
    orch.run_once()  # bootstrap → analyst + architect + kickoff(blocked)

    book_request_task({
        "project_id": book.project_id,
        "title": "Decide auth approach",
        "rationale": "Implementer needs upstream architectural decision",
        "requester_role": "agent-implementer",
        "suggested_role": "agent-architekt",
    })
    nd = orch.run_once()["next_delegation"]
    assert nd["to_role"] == "agent-cto"
    ctx = nd["context"]

    assert "Team roster" in ctx
    # Architect, implementer, qa-reviewer, product-analyst all loaded from
    # bootstrap — confirm at least the upstream-decision roles appear with
    # their description and a workload count.
    for role in [
        "agent-architekt",
        "agent-product-analyst",
        "agent-implementer",
        "agent-qa-reviewer",
    ]:
        assert role in ctx, f"roster missing {role}"
    assert "open:" in ctx and "done:" in ctx
    assert "Routing guidance" in ctx
    # CTO must not appear in its own roster.
    assert ctx.count("agent-cto:") == 0
