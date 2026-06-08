"""Phase auto-advance and the autonomous loop reaching done."""

import json

from omoikane.core.book import ProjectBook
from omoikane.core.orchestrator import TeamOrchestrator
from omoikane.tools import (
    book_record_result,
    book_satisfy_criterion,
    project_continue,
    project_start,
)


def _drain_tasks(book: ProjectBook, phase: str) -> None:
    """Force-close every open task tagged with ``phase``."""
    data = book.load()
    meta = data.get("task_meta", {})
    for task_id in list(data.get("open_tasks", [])):
        if meta.get(task_id, {}).get("phase") == phase:
            book.complete_task(task_id)


def test_bootstrap_sets_phase_to_analysis(temp_hermes_home):
    book = ProjectBook.create("brief", ["AC"])
    TeamOrchestrator(book.project_id).run_once()
    assert book.current_phase == "analysis"


def test_phase_advances_as_tasks_close(temp_hermes_home):
    book = ProjectBook.create("brief", ["A", "B"])
    orch = TeamOrchestrator(book.project_id)
    orch.run_once()  # bootstrap → analyst(analysis) + architect(design) + kickoff(meta, blocked)

    # Analyst drains → architect remains in design.
    _drain_tasks(book, "analysis")
    orch.run_once()
    assert book.current_phase == "design"

    # Architect drains → kickoff (routing@meta) unblocks; only unblocked
    # task left is routing → phase advances to meta.
    _drain_tasks(book, "design")
    orch.run_once()
    assert book.current_phase == "meta"

    # Simulate the CTO committing the roadmap: close the kickoff and file
    # executor tasks (one per remaining phase). This mirrors what the CTO
    # does via book_set_roadmap + book_open_task in the real flow.
    for tid in list(book.load()["open_tasks"]):
        book.complete_task(tid)
    book.open_task(title="implement core",
                   assignee_role="agent-implementer", phase="implementation")
    book.open_task(title="write tests",
                   assignee_role="agent-qa-reviewer", phase="testing")
    book.open_task(title="final review",
                   assignee_role="agent-qa-reviewer", phase="review")

    for prior_phase, target_phase in zip(
        ["implementation", "testing"],
        ["testing", "review"],
    ):
        orch.run_once()
        assert book.current_phase == prior_phase
        _drain_tasks(book, prior_phase)
    orch.run_once()
    assert book.current_phase == "review"


def test_phase_becomes_meta_when_only_routing_tasks_remain(temp_hermes_home):
    """Drain to zero open tasks with criteria pending → auto-decomp fires
    and files a fresh CTO routing task. Phase lands on 'meta'."""
    book = ProjectBook.create("brief", ["A"])
    orch = TeamOrchestrator(book.project_id)
    orch.run_once()  # bootstrap

    # Drain EVERY open task — analyst, architect, and the blocked kickoff —
    # so the auto-decomp branch (no open tasks + criteria pending) fires
    # rather than the kickoff being the only routing task left.
    for tid in list(book.load()["open_tasks"]):
        book.complete_task(tid)
    assert book.load()["open_tasks"] == []

    orch.run_once()
    data = book.load()
    assert book.current_phase == "meta"
    # The auto-decomp routing task should be the only open task and its
    # title should match _auto_decompose's filed title.
    open_ids = data["open_tasks"]
    assert len(open_ids) == 1
    new_task = data["task_meta"][open_ids[0]]
    assert new_task["routing_status"] == "routing"
    assert new_task["requester_role"] == "orchestrator"
    assert "Decompose remaining work" in new_task["title"]


def test_satisfying_all_criteria_drives_status_done(temp_hermes_home):
    book = ProjectBook.create("brief", ["A"])
    orch = TeamOrchestrator(book.project_id)
    # Completion requires all criteria satisfied, no open tasks, AND the bounded
    # completeness review. The continuation path files completeness routing
    # tasks until the cap; drive run_once + drain until it converges.
    book.update_status("in_progress")
    book.satisfy_criterion(0, evidence="manual")

    def _drain():
        data = book.load()
        if data.get("open_tasks"):
            data["open_tasks"] = []
            book.store.save_book(data)

    result = orch.run_once()
    for _ in range(8):
        if result["status"] == "completed":
            break
        _drain()
        result = orch.run_once()
    assert result["status"] == "completed"
    assert book.status == "done"
    assert book.current_phase == "completed"


def test_autonomous_loop_reaches_done_with_all_pieces(temp_hermes_home):
    """End-to-end loop simulating sub-agent returns through the new bootstrap.

    Flow: analyst → architect → CTO (kickoff: commits roadmap + files QA
    task) → QA (closes + satisfies all criteria) → done.
    """
    res = json.loads(project_start({
        "brief": "Tiny project",
        "acceptance_criteria": ["criterion A", "criterion B"],
    }))
    pid = res["project_id"]

    book = ProjectBook(pid)
    cto_committed_roadmap = False
    saw_kickoff_dispatch = False
    saw_qa_dispatch = False

    for _ in range(60):
        tick = json.loads(project_continue({"project_id": pid}))
        if tick["tick"]["status"] == "completed":
            break
        nd = tick.get("next_delegation")
        if not nd:
            continue
        # Pretend the sub-agent did the work and signaled back.
        book_record_result({
            "project_id": pid,
            "task": nd["task"],
            "status": "done",
            "reflection": f"simulated {nd['to_role']}",
        })
        # When CTO is dispatched (for the kickoff), simulate the roadmap
        # commit + executor-task filing the CTO is expected to perform.
        if nd["to_role"] == "agent-cto" and not cto_committed_roadmap:
            # Prove the kickoff procedure block actually reached CTO before
            # we simulate its compliance — otherwise the loop could pass
            # against a regression that strips the procedure from context.
            assert "Kickoff procedure" in nd["context"]
            assert "Completed work and reflections" in nd["context"]
            saw_kickoff_dispatch = True
            book.set_roadmap([{
                "milestone_id": "m1",
                "title": "Verify acceptance criteria",
                "description": "Smoke + regression coverage",
                "criteria_indices": list(range(len(book.load()["acceptance_criteria"]))),
                "status": "planned",
            }])
            book.open_task(
                title="QA: verify acceptance criteria for milestone m1",
                assignee_role="agent-qa-reviewer",
                phase="review",
                milestone_id="m1",
            )
            cto_committed_roadmap = True
        # Close the task explicitly — book_record_result records the verdict
        # but leaves the task open for the orchestrator to advance.
        book.complete_task(nd["task"])
        # The QA reviewer satisfies the criteria.
        if nd["to_role"] == "agent-qa-reviewer":
            saw_qa_dispatch = True
            for i in range(len(book.load()["acceptance_criteria"])):
                book_satisfy_criterion({
                    "project_id": pid,
                    "index": i,
                    "evidence": "regression test passes",
                })

    assert book.status == "done", (
        f"project did not finish — status={book.status}, "
        f"open={len(book.load()['open_tasks'])}"
    )
    assert book.current_phase == "completed"
    # Prove the loop actually traversed the new bootstrap chain rather
    # than short-circuiting through some unintended path.
    assert saw_kickoff_dispatch, "CTO never dispatched for the kickoff task"
    assert saw_qa_dispatch, "QA reviewer never dispatched"
