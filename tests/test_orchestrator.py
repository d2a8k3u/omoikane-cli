from omoikane.core.book import ProjectBook
from omoikane.core.orchestrator import TeamOrchestrator


def test_first_run_bootstraps_tasks_and_switches_to_in_progress(temp_hermes_home):
    book = ProjectBook.create("Build CLI", ["CLI works", "Tests pass"])
    result = TeamOrchestrator(book.project_id).run_once()

    assert result["status"] == "tasks_created"
    data = book.load()
    assert data["status"] == "in_progress"
    assert len(data["open_tasks"]) > 0


def test_second_run_returns_next_delegation_payload(temp_hermes_home):
    book = ProjectBook.create("Build CLI", ["CLI works"])
    orch = TeamOrchestrator(book.project_id)
    orch.run_once()  # bootstrap

    result = orch.run_once()
    assert result["status"] == "in_progress"
    nd = result["next_delegation"]
    # The plan carries everything the LLM needs to call delegate_task itself.
    assert nd["task"].startswith("task-")
    assert nd["to_role"].startswith("agent-")
    assert nd["goal"]
    assert "Project brief" in nd["context"]
    assert "Acceptance criteria" in nd["context"]
    assert "Your role's SKILL.md" in nd["context"]
    assert isinstance(nd["toolsets"], list) and nd["toolsets"]


def test_next_delegation_includes_role_skill_content(temp_hermes_home):
    book = ProjectBook.create("Build CLI", ["CLI works"])
    orch = TeamOrchestrator(book.project_id)
    orch.run_once()
    result = orch.run_once()
    # First non-kickoff dispatch in the new bootstrap is the analyst.
    # Verify the analyst's SKILL.md text is embedded in the context — not
    # just the role name — so the subagent starts with real instructions.
    nd = result["next_delegation"]
    assert nd["to_role"] == "agent-product-analyst"
    assert "Product Analyst" in nd["context"]
    assert "Your role's SKILL.md" in nd["context"]


def test_run_once_does_not_auto_complete_tasks(temp_hermes_home):
    """The plugin must never close tasks on its own — that is the LLM's job
    after delegate_task returns and the reviewer signs off."""
    book = ProjectBook.create("Build CLI", ["CLI works"])
    orch = TeamOrchestrator(book.project_id)
    orch.run_once()
    open_before = list(book.load()["open_tasks"])
    orch.run_once()
    open_after = list(book.load()["open_tasks"])
    assert open_before == open_after  # nothing was silently closed


def test_no_open_tasks_auto_files_routing_task_for_cto(temp_hermes_home):
    """needs_decomposition is no longer the happy-path output — the
    orchestrator instead files a CTO routing task and surfaces a
    delegation in the same tick."""
    book = ProjectBook.create("Brief", ["A"])
    orch = TeamOrchestrator(book.project_id)
    orch.run_once()  # bootstrap

    # Drain every bootstrap task without satisfying the criterion.
    while book.load().get("open_tasks"):
        data = book.load()
        data["open_tasks"] = []
        book.store.save_book(data)

    result = orch.run_once()
    assert result["status"] == "in_progress"
    nd = result["next_delegation"]
    assert nd["to_role"] == "agent-cto"
    assert nd["routing"] is True
    assert "Decompose remaining work" in nd["title"]


def test_project_done_only_when_all_criteria_satisfied(temp_hermes_home):
    book = ProjectBook.create("Brief", ["A", "B"])
    orch = TeamOrchestrator(book.project_id)
    orch.run_once()  # bootstrap

    # Drain all open tasks without satisfying criteria
    while book.load().get("open_tasks"):
        data = book.load()
        data["open_tasks"] = []
        book.store.save_book(data)

    result = orch.run_once()
    assert result["status"] in {"needs_decomposition", "in_progress"}
    assert book.load()["status"] != "done"

    # Satisfy criteria explicitly and re-run
    book.satisfy_criterion(0)
    book.satisfy_criterion(1)
    result = orch.run_once()
    assert result["status"] == "completed"
    assert book.load()["status"] == "done"


def test_run_once_idempotent_when_already_done(temp_hermes_home):
    book = ProjectBook.create("Brief", ["A"])
    book.update_status("done", phase="completed")
    result = TeamOrchestrator(book.project_id).run_once()
    assert result["status"] == "already_done"
