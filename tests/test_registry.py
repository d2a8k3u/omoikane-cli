from omoikane.core.agents_registry import get_registry, reload_registry


def test_registry_loads_bundled_agents():
    registry = reload_registry()
    roles = registry.list_roles()
    assert "agent-implementer" in roles
    assert "agent-qa-reviewer" in roles
    assert "agent-architekt" in roles
    assert "orchestrator-protocol" in roles


def test_get_skill_content_returns_markdown():
    registry = get_registry()
    content = registry.get_skill_content("agent-implementer")
    assert content is not None
    assert len(content) > 0


def test_get_skill_content_unknown_role():
    registry = get_registry()
    assert registry.get_skill_content("agent-does-not-exist") is None


def test_default_team_subset_of_loaded():
    registry = reload_registry()
    team = registry.get_default_team()
    roles = set(registry.list_roles())
    assert set(team).issubset(roles)


def test_default_team_includes_core_roles():
    team = set(reload_registry().get_default_team())
    for required in [
        "orchestrator-protocol",
        "agent-product-analyst",
        "agent-architekt",
        "agent-designer",
        "agent-backend-engineer",
        "agent-frontend-engineer",
        "agent-implementer",
        "agent-qa-reviewer",
        "agent-security-engineer",
        "agent-devops",
        "agent-database-specialist",
        "agent-tech-writer",
    ]:
        assert required in team, f"default team missing {required}"


def test_domain_specific_agents_removed():
    roles = set(reload_registry().list_roles())
    for dropped in [
        "agent-crypto-prediction",
        "agent-financni-analytik",
        "agent-polymarket-analyzer",
        "agent-opportunity-specialist",
        "partnership-orchestrator",
    ]:
        assert dropped not in roles, f"expected {dropped} to be removed"
