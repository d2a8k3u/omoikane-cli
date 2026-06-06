from omoikane.core.execution import choose_execution_mode, ExecutionMetadata


def test_default_in_process():
    assert choose_execution_mode() == "in_process"
    assert choose_execution_mode({}) == "in_process"
    assert choose_execution_mode({"title": "Write a small helper function"}) == "in_process"


def test_build_keyword_is_isolated():
    assert choose_execution_mode({"title": "Run full build of frontend"}) == "isolated"


def test_test_suite_keyword_is_isolated():
    assert choose_execution_mode({"title": "Run the entire test suite"}) == "isolated"


def test_deploy_keyword_is_isolated():
    assert choose_execution_mode({"title": "Deploy to staging"}) == "isolated"


def test_long_estimate_is_isolated():
    assert choose_execution_mode({"estimated_minutes": 10}) == "isolated"
    assert choose_execution_mode({"estimated_minutes": 30}) == "isolated"


def test_short_estimate_skips_keyword_fallback():
    """When estimated_minutes is explicitly low, keywords are ignored (metadata wins)."""
    assert choose_execution_mode({"title": "Deploy to staging", "estimated_minutes": 5}) == "in_process"
    assert choose_execution_mode({"title": "Run full build", "estimated_minutes": 2}) == "in_process"


def test_requires_network_is_isolated():
    assert choose_execution_mode({"title": "Fetch latest packages", "requires_network": True}) == "isolated"


def test_dangerous_commands_is_isolated():
    assert choose_execution_mode({"dangerous_commands": True}) == "isolated"


def test_background_is_isolated():
    assert choose_execution_mode({"background": True}) == "isolated"


def test_explicit_false_metadata_skips_keywords():
    """A task with keywords that *would* trigger isolation, but metadata says no."""
    assert choose_execution_mode({"title": "build", "requires_network": False}) == "in_process"
    assert choose_execution_mode({"title": "deploy", "background": False}) == "in_process"


def test_explicit_zero_minutes_skips_keywords():
    assert choose_execution_mode({"title": "full build", "estimated_minutes": 0}) == "in_process"


def test_metadata_dict_vs_keyword_with_underscore():
    """A keyword inside a metadata key name should not accidentally match."""
    assert choose_execution_mode({"description": "Run full deploy build"}) == "in_process"


# === Expanded keyword & structured metadata coverage ===

def test_docker_build_keyword_is_isolated():
    assert choose_execution_mode({"title": "docker build image for release"}) == "isolated"


def test_e2e_test_keyword_is_isolated():
    assert choose_execution_mode({"title": "run e2e tests on staging"}) == "isolated"


def test_terraform_destroy_keyword_is_isolated():
    assert choose_execution_mode({"title": "terraform destroy old cluster"}) == "isolated"


def test_database_migration_keyword_is_isolated():
    assert choose_execution_mode({"title": "Database migration for new schema"}) == "isolated"


def test_expected_text_also_considered():
    """When title is vague, the expected description is also scanned."""
    assert choose_execution_mode({
        "title": "Infrastructure work",
        "expected": "Run terraform apply on prod cluster",
    }) == "isolated"


def test_expected_text_alone_can_trigger():
    assert choose_execution_mode({
        "title": "Weekly maintenance",
        "expected": "reboot server and restart services",
    }) == "isolated"


# --- ExecutionMetadata API ---

def test_execution_metadata_from_dict_round_trip():
    raw = {
        "title": "Deploy",
        "estimated_minutes": 45,
        "requires_network": False,
        "dangerous_commands": True,
    }
    meta = ExecutionMetadata.from_dict(raw)
    assert meta.title == "Deploy"
    assert meta.estimated_minutes == 45
    assert meta.requires_network is False
    assert meta.dangerous_commands is True
    assert meta.background is None
    assert meta.to_dict() == {
        "title": "Deploy",
        "expected": "",
        "estimated_minutes": 45,
        "requires_network": False,
        "dangerous_commands": True,
    }


def test_execution_metadata_skips_none_in_to_dict():
    meta = ExecutionMetadata(title="Fix bug", expected="patch")
    assert meta.to_dict() == {
        "title": "Fix bug",
        "expected": "patch",
    }


def test_execution_metadata_has_explicit_when_any_field_set():
    assert ExecutionMetadata(requires_network=False).has_explicit_metadata() is True
    assert ExecutionMetadata(background=False).has_explicit_metadata() is True
    assert ExecutionMetadata(estimated_minutes=None).has_explicit_metadata() is False
    assert ExecutionMetadata().has_explicit_metadata() is False
