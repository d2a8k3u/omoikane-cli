"""Toolset resolution for role-driven AIAgent construction."""
from __future__ import annotations

from omoikane.runtime import role_toolsets


def test_defaults_always_include_omoikane():
    for role in role_toolsets.known_roles():
        ts = role_toolsets.toolsets_for(role)
        assert ts[-1] == "omoikane" or "omoikane" in ts


def test_fallback_for_unknown_role_is_narrow():
    ts = role_toolsets.toolsets_for("agent-unknown-role")
    assert ts == ["file", "omoikane"]


def test_specialists_use_terminal_not_code_execution():
    # Phase 0 spike C — children cannot have code_execution.
    for role in (
        "agent-backend-engineer",
        "agent-frontend-engineer",
        "agent-implementer",
        "agent-ml-engineer",
    ):
        ts = role_toolsets.toolsets_for(role)
        assert "code_execution" not in ts
        assert "terminal" in ts


def test_cto_toolsets_superset_includes_every_specialist_toolset():
    cto = set(role_toolsets.cto_toolsets())
    assert "delegation" in cto
    assert "omoikane" in cto
    for role in role_toolsets.known_roles():
        if role == "agent-cto":
            continue
        for ts in role_toolsets.toolsets_for(role):
            assert ts in cto, f"CTO missing {ts} required by {role}"


def test_overrides_replace_base():
    overrides = {"agent-backend-engineer": ["file", "web", "browser"]}
    ts = role_toolsets.toolsets_for("agent-backend-engineer", overrides=overrides)
    assert ts == ["file", "web", "browser", "omoikane"]


def test_overrides_empty_list_falls_back():
    overrides = {"agent-backend-engineer": []}
    ts = role_toolsets.toolsets_for("agent-backend-engineer", overrides=overrides)
    assert "terminal" in ts


def test_merge_overrides_from_config_filters_garbage():
    cfg = {
        "agent-backend-engineer": ["file", "terminal"],
        "agent-frontend-engineer": "browser",
        "": ["nope"],
        "bad": 42,
    }
    out = role_toolsets.merge_overrides_from_config(cfg)
    assert out == {
        "agent-backend-engineer": ["file", "terminal"],
        "agent-frontend-engineer": ["browser"],
    }


def test_known_roles_includes_seventeen_entries():
    # The CTO entry plus 14 specialists plus orchestrator-protocol and
    # agent-manager — same 17 SKILL.md briefs we bundled in Phase 1.
    assert len(role_toolsets.known_roles()) == 17
