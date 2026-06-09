"""Unit tests for the shared team-roster renderer.

``render_team_roster`` is the single source of truth for the roster every
role-picking agent sees (CTO routing/kickoff, QA fixes, specialist escalation
and split). It must stay byte-stable in format and never surface a non-routable
role.
"""

from omoikane.core.agents_registry import reload_registry, render_team_roster


def test_render_team_roster_sorted_and_complete():
    r = reload_registry()
    roster = render_team_roster(None, registry=r)
    lines = [ln for ln in roster.splitlines() if ln.startswith("- ")]
    names = [ln[2:].split(":", 1)[0] for ln in lines]
    assert names == sorted(names)
    expected = sorted(
        x for x in r.list_routable_roles() if x != "orchestrator-protocol"
    )
    assert names == expected


def test_render_team_roster_excludes_manager_and_protocol():
    r = reload_registry()
    roster = render_team_roster(None, registry=r)
    assert "- agent-manager:" not in roster
    assert "- orchestrator-protocol:" not in roster


def test_render_team_roster_honours_exclude():
    r = reload_registry()
    roster = render_team_roster(None, registry=r, exclude="agent-cto")
    assert "- agent-cto:" not in roster
    assert "- agent-architekt:" in roster  # a different role still listed


def test_render_team_roster_includes_descriptions():
    r = reload_registry()
    roster = render_team_roster(None, registry=r)
    # The competency description comes straight from each SKILL.md frontmatter.
    assert "- agent-database-specialist:" in roster
    line = next(
        ln
        for ln in roster.splitlines()
        if ln.startswith("- agent-database-specialist:")
    )
    assert len(line.split(":", 1)[1].strip()) > 0


def test_render_team_roster_counts_workload():
    r = reload_registry()
    book = {
        "task_meta": {
            "task-1": {"assignee_role": "agent-backend-engineer"},
            "task-2": {"assignee_role": "agent-backend-engineer"},
            "task-3": {"assignee_role": "agent-backend-engineer"},
        },
        "open_tasks": ["task-1", "task-2"],
        "completed_tasks": ["task-3"],
    }
    roster = render_team_roster(book, registry=r)
    line = next(
        ln for ln in roster.splitlines() if ln.startswith("- agent-backend-engineer:")
    )
    assert "(open: 2, done: 1)" in line


def test_render_team_roster_none_book_is_zero_workload():
    r = reload_registry()
    roster = render_team_roster(None, registry=r)
    for ln in roster.splitlines():
        assert "(open: 0, done: 0)" in ln


def test_render_team_roster_default_registry_does_not_raise():
    # No explicit registry → falls back to the global singleton.
    roster = render_team_roster(None)
    assert "- agent-architekt:" in roster
