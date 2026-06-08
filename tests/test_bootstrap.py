"""Bootstrap-shape tests for the CTO-driven dynamic kickoff.

Replaces the legacy 5-task hardcoded bootstrap. The seed is now three
tasks: analyst + architect (executor) + kickoff (routing to CTO, blocked).
"""

from omoikane.core.book import ProjectBook
from omoikane.core.orchestrator import TeamOrchestrator


def _classify(open_tasks, meta):
    """Group bootstrap open tasks by role for clean assertions."""
    by_role = {}
    for tid in open_tasks:
        role = meta[tid].get("assignee_role")
        by_role.setdefault(role, []).append(tid)
    return by_role


def test_bootstrap_files_three_seed_tasks(temp_hermes_home):
    book = ProjectBook.create("Brief", ["A", "B"])
    TeamOrchestrator(book.project_id).run_once()

    data = book.load()
    assert len(data["open_tasks"]) == 3
    assert data["status"] == "in_progress"
    assert data["current_phase"] == "analysis"
    assert data["roadmap"] == []

    by_role = _classify(data["open_tasks"], data["task_meta"])
    assert "agent-product-analyst" in by_role
    assert "agent-architekt" in by_role
    assert "agent-cto" in by_role


def test_bootstrap_analyst_task_shape(temp_hermes_home):
    book = ProjectBook.create("Brief", ["A"])
    TeamOrchestrator(book.project_id).run_once()
    data = book.load()
    by_role = _classify(data["open_tasks"], data["task_meta"])
    analyst_id = by_role["agent-product-analyst"][0]
    meta = data["task_meta"][analyst_id]
    assert meta["phase"] == "analysis"
    assert meta["routing_status"] == "assigned"
    assert not meta.get("blocked_by")
    # The analyst now owns deriving the completion contract from the brief.
    title = meta["title"].lower()
    assert "derive" in title and "acceptance criteria" in title


def test_bootstrap_architect_task_shape(temp_hermes_home):
    book = ProjectBook.create("Brief", ["A"])
    TeamOrchestrator(book.project_id).run_once()
    data = book.load()
    by_role = _classify(data["open_tasks"], data["task_meta"])
    architect_id = by_role["agent-architekt"][0]
    meta = data["task_meta"][architect_id]
    assert meta["phase"] == "design"
    assert meta["routing_status"] == "assigned"
    assert not meta.get("blocked_by")


def test_bootstrap_kickoff_task_shape(temp_hermes_home):
    book = ProjectBook.create("Brief", ["A"])
    TeamOrchestrator(book.project_id).run_once()
    data = book.load()
    by_role = _classify(data["open_tasks"], data["task_meta"])
    analyst_id = by_role["agent-product-analyst"][0]
    architect_id = by_role["agent-architekt"][0]
    kickoff_id = by_role["agent-cto"][0]

    meta = data["task_meta"][kickoff_id]
    assert meta["phase"] == "meta"
    assert meta["routing_status"] == "routing"
    assert meta["requester_role"] == "orchestrator"
    assert meta["title"].startswith("Kickoff:")
    assert sorted(meta["blocked_by"]) == sorted([analyst_id, architect_id])


def test_pick_next_task_skips_blocked_kickoff(temp_hermes_home):
    book = ProjectBook.create("Brief", ["A"])
    orch = TeamOrchestrator(book.project_id)
    orch.run_once()

    data = book.load()
    by_role = _classify(data["open_tasks"], data["task_meta"])
    analyst_id = by_role["agent-product-analyst"][0]
    kickoff_id = by_role["agent-cto"][0]

    # _pick_next_task must skip the blocked routing kickoff and return the
    # unblocked analyst even though routing-first is the default rule.
    picked = orch._pick_next_task(data, data["open_tasks"])
    assert picked == analyst_id
    assert picked != kickoff_id


def test_kickoff_unblocks_after_prereqs_close(temp_hermes_home):
    book = ProjectBook.create("Brief", ["A"])
    orch = TeamOrchestrator(book.project_id)
    orch.run_once()

    data = book.load()
    by_role = _classify(data["open_tasks"], data["task_meta"])
    analyst_id = by_role["agent-product-analyst"][0]
    architect_id = by_role["agent-architekt"][0]
    kickoff_id = by_role["agent-cto"][0]

    book.complete_task(analyst_id)
    book.complete_task(architect_id)

    data2 = book.load()
    picked = orch._pick_next_task(data2, data2["open_tasks"])
    assert picked == kickoff_id


def test_advance_phase_skips_blocked_non_routing_task(temp_hermes_home):
    """_advance_phase must ignore blocked tasks even when they are
    non-routing executor tasks. Without the blocked-skip the earliest
    phase ('analysis') would win and the project would stall on a task
    that cannot be dispatched.

    Setup: a blocked analysis task + an unblocked design task. With the
    blocked-skip, phase advances to 'design'. Without it, phase would be
    'analysis' (earliest in _PHASE_ORDER) — a regression this test catches.
    """
    book = ProjectBook.create("Brief", ["A"])
    orch = TeamOrchestrator(book.project_id)

    # Drain the seeded bootstrap so we control the open set fully.
    orch.run_once()
    for tid in list(book.load()["open_tasks"]):
        book.complete_task(tid)

    prereq = book.open_task(title="prereq",
                            assignee_role="agent-implementer",
                            phase="review")  # late phase so it doesn't compete
    blocked_analysis = book.open_task(title="blocked analysis",
                                      assignee_role="agent-product-analyst",
                                      phase="analysis",
                                      blocked_by=[prereq])
    book.open_task(title="unblocked design",
                   assignee_role="agent-architekt",
                   phase="design")

    orch._advance_phase(book.load())
    assert book.current_phase == "design"
    # Sanity: blocked task is still open but did not pull the phase to
    # 'analysis' — proof the blocked-skip in _advance_phase fired.
    assert blocked_analysis in book.load()["open_tasks"]


def test_kickoff_dispatch_carries_kickoff_procedure_block(temp_hermes_home):
    book = ProjectBook.create("Brief", ["A"])
    orch = TeamOrchestrator(book.project_id)
    orch.run_once()
    data = book.load()
    by_role = _classify(data["open_tasks"], data["task_meta"])
    analyst_id = by_role["agent-product-analyst"][0]
    architect_id = by_role["agent-architekt"][0]
    book.complete_task(analyst_id)
    book.complete_task(architect_id)

    result = orch.run_once()
    nd = result["next_delegation"]
    assert nd["to_role"] == "agent-cto"
    assert nd["routing"] is True
    ctx = nd["context"]
    assert "Kickoff procedure" in ctx
    assert "book_set_roadmap" in ctx
    assert "book_open_task" in ctx
    assert "Completed work and reflections" in ctx
    assert "Committed roadmap" in ctx


def test_cto_routing_context_lists_completed_reflections(temp_hermes_home):
    """Direct-reflect path: analyst/architect call book.reflect() per their
    SKILL.md and never touch the delegation tree. CTO must still see the
    reflection files in its context — surfaced via a directory scan."""
    book = ProjectBook.create("Brief", ["A"])
    orch = TeamOrchestrator(book.project_id)
    orch.run_once()
    data = book.load()
    by_role = _classify(data["open_tasks"], data["task_meta"])
    analyst_id = by_role["agent-product-analyst"][0]
    architect_id = by_role["agent-architekt"][0]

    analyst_ref = book.reflect("Analyst output: 3 user stories", task=analyst_id)
    architect_ref = book.reflect("Architect output: monolith + sqlite",
                                 task=architect_id)
    book.complete_task(analyst_id)
    book.complete_task(architect_id)

    nd = orch.run_once()["next_delegation"]
    ctx = nd["context"]

    # Both completed task ids and the reflection files must appear.
    assert analyst_id in ctx
    assert architect_id in ctx
    # The reflection paths must be absolute so CTO can resolve them
    # regardless of subagent CWD.
    analyst_abs = str(book.store.project_dir / analyst_ref)
    architect_abs = str(book.store.project_dir / architect_ref)
    assert analyst_abs in ctx, f"analyst reflection path missing from context"
    assert architect_abs in ctx, f"architect reflection path missing from context"


def test_cto_context_surfaces_reflections_filed_via_book_record_result(temp_hermes_home):
    """Tree-edge path: book_record_result(reflection=...) records the
    reflection ref on the delegation edge. CTO must see it even when the
    filesystem reflection files are gone — proving the surfacing reads the
    tree, not the directory."""
    from omoikane.tools import book_record_result
    import json as _json
    import shutil as _shutil

    book = ProjectBook.create("Brief", ["A"])
    orch = TeamOrchestrator(book.project_id)
    orch.run_once()
    data = book.load()
    by_role = _classify(data["open_tasks"], data["task_meta"])
    analyst_id = by_role["agent-product-analyst"][0]
    architect_id = by_role["agent-architekt"][0]

    # Drive the analyst dispatch through the orchestrator so a delegation
    # edge exists for book_record_result to close.
    orch.run_once()  # dispatches analyst
    res_a = _json.loads(book_record_result({
        "project_id": book.project_id,
        "task": analyst_id,
        "status": "done",
        "reflection": "Analyst lessons via record_result",
    }))
    book.complete_task(analyst_id)

    orch.run_once()  # dispatches architect
    res_b = _json.loads(book_record_result({
        "project_id": book.project_id,
        "task": architect_id,
        "status": "done",
        "reflection": "Architect lessons via record_result",
    }))
    book.complete_task(architect_id)

    # Wipe reflections/ so the directory-scan fallback in _cto_state_block
    # finds nothing. Only the tree-edge path can surface the refs now.
    refl_dir = book.store.project_dir / "reflections"
    if refl_dir.exists():
        _shutil.rmtree(refl_dir)
    assert not refl_dir.exists()

    nd = orch.run_once()["next_delegation"]
    ctx = nd["context"]
    assert nd["to_role"] == "agent-cto"
    assert res_a["reflection_ref"]
    assert res_b["reflection_ref"]
    # Tree-edge refs must still surface — built from edge.reflection_ref,
    # not from a filesystem walk.
    assert str(book.store.project_dir / res_a["reflection_ref"]) in ctx
    assert str(book.store.project_dir / res_b["reflection_ref"]) in ctx
