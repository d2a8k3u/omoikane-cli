"""agent-manager is loaded but excluded from CTO routing + role-picker."""

from omoikane.core.agents_registry import get_registry, reload_registry
from omoikane.core.book import ProjectBook
from omoikane.core.orchestrator import TeamOrchestrator


def test_registry_loads_manager_skill():
    r = reload_registry()
    assert "agent-manager" in r.list_roles()
    skill = r.get_skill_content("agent-manager") or ""
    assert "agent-manager" in skill.lower()


def test_routable_roles_excludes_manager():
    r = reload_registry()
    assert "agent-manager" not in r.list_routable_roles()


def test_cto_team_roster_excludes_manager(temp_hermes_home):
    """The CTO routing roster must never surface agent-manager. CTO would
    happily route random work to it otherwise."""
    book = ProjectBook.create("brief", ["AC"])
    orch = TeamOrchestrator(book.project_id)
    orch.run_once()  # bootstrap

    # Drive to a CTO routing dispatch via book_request_task.
    from omoikane.tools import book_request_task
    book_request_task({
        "project_id": book.project_id,
        "title": "Decide auth approach",
        "rationale": "Implementer needs upstream decision",
        "requester_role": "agent-implementer",
    })
    nd = orch.run_once()["next_delegation"]
    assert nd["to_role"] == "agent-cto"
    ctx = nd["context"]
    # The roster is the only place CTO picks routing targets from.
    # agent-manager may legitimately appear elsewhere (e.g. SKILL.md text)
    # but MUST NOT be a roster line.
    roster_start = ctx.index("Team roster (pick from here)")
    roster_end = ctx.index("Routing guidance:", roster_start)
    roster_block = ctx[roster_start:roster_end]
    assert "- agent-manager:" not in roster_block, (
        f"agent-manager leaked into routable roster:\n{roster_block}"
    )


def test_heuristic_role_picker_does_not_return_manager():
    """_pick_role's title heuristic must never resolve to agent-manager."""
    r = reload_registry()  # ensure manager is in self._agents but excluded
    from omoikane.core.orchestrator import TeamOrchestrator
    # Build a stub orchestrator without loading a book.
    class _Stub(TeamOrchestrator):
        def __init__(self): self.registry = r  # type: ignore
    stub = _Stub()
    # None of the heuristic title keywords (manage / report / record / book)
    # should resolve to agent-manager.
    for title in [
        "manage report ingestion",
        "record results",
        "update the book",
        "book a meeting",
    ]:
        assert stub._pick_role(title) != "agent-manager"
