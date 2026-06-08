"""Specialist cooperation: a non-CTO executor's delegation context surfaces
upstream decisions (its own milestone + the relevant reflection) without
dumping the whole project state, and carries the escalation channel.
"""
from omoikane.core.book import ProjectBook
from omoikane.core.orchestrator import TeamOrchestrator


def _setup(book: ProjectBook):
    book.update_status("in_progress")
    book.set_roadmap([
        {"milestone_id": "m1", "title": "Build the parser",
         "description": "Tokenize and parse input", "criteria_indices": [0]},
        {"milestone_id": "m2", "title": "Wire the database",
         "description": "Schema + migrations", "criteria_indices": [1]},
    ])
    # An architect finished m1 and left an ADR reflection.
    arch_id = book.open_task("Design the parser", assignee_role="agent-architekt",
                             phase="design", milestone_id="m1")
    book.reflect("ADR-01: recursive-descent parser chosen over PEG.", task=arch_id)
    book.complete_task(arch_id)
    # The backend engineer now implements within m1.
    impl_id = book.open_task("Implement the parser", assignee_role="agent-backend-engineer",
                             phase="implementation", milestone_id="m1")
    return arch_id, impl_id


def test_specialist_context_surfaces_own_milestone_and_reflection(temp_hermes_home):
    book = ProjectBook.create("brief", ["parser works", "db works"])
    arch_id, impl_id = _setup(book)

    orch = TeamOrchestrator(book.project_id)
    plan = orch._plan_delegation(impl_id, book.load())
    ctx = plan["context"]

    # Own milestone is shown.
    assert "Build the parser" in ctx
    assert "Tokenize and parse input" in ctx
    # The upstream architect reflection is surfaced as an absolute path.
    assert "ADR-01" not in ctx  # we surface the path, not the contents
    refl_abs = str(book.store.project_dir)
    assert refl_abs in ctx
    assert "reflections/" in ctx
    # It does NOT dump the unrelated milestone.
    assert "Wire the database" not in ctx


def test_specialist_context_carries_escalation_channel(temp_hermes_home):
    book = ProjectBook.create("brief", ["parser works", "db works"])
    _arch_id, impl_id = _setup(book)

    plan = TeamOrchestrator(book.project_id)._plan_delegation(impl_id, book.load())
    ctx = plan["context"]
    assert "Escalation" in ctx
    assert "book_request_task" in ctx


def test_cto_context_does_not_get_specialist_block(temp_hermes_home):
    # The CTO keeps its own (full) state block; the specialist block is
    # reserved for non-CTO executors so the two don't double up.
    book = ProjectBook.create("brief", ["parser works"])
    book.update_status("in_progress")
    routing = book.request_task("Route something", requester_role="agent-architekt",
                                rationale="needs a decision", suggested_role="agent-backend-engineer")
    plan = TeamOrchestrator(book.project_id)._plan_delegation(routing, book.load())
    # Routing tasks go to the CTO and use the routing brief, not the
    # specialist upstream-decisions block.
    assert "Upstream decisions (read these before you start)" not in plan["context"]
