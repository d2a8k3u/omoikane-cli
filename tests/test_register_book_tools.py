"""Smoke: every Book tool reaches the SDK registry."""
from __future__ import annotations

import pytest


def _import_sdk_registry():
    """Skip the test suite cleanly when the SDK runtime extra is not installed.

    Core-only contributors can still run ``pytest`` without bringing the
    hermes-agent wheel into their environment.
    """
    pytest.importorskip("tools.registry", reason="hermes-agent SDK not installed")
    from tools.registry import registry as sdk_registry  # type: ignore

    return sdk_registry


def test_register_book_tools_loads_all_20_into_sdk():
    sdk_registry = _import_sdk_registry()

    from omoikane.tools import (
        OMOIKANE_TOOLSET,
        is_registered,
        register_book_tools,
        reset_registration_for_tests,
    )

    reset_registration_for_tests()
    assert not is_registered()

    mapping = register_book_tools(override=True)

    assert is_registered()
    assert len(mapping) == 20

    registered_names = sorted(mapping)
    sdk_names = sorted(
        t.name for t in sdk_registry._tools.values() if t.toolset == OMOIKANE_TOOLSET
    )
    assert registered_names == sdk_names

    expected = {
        "project_start", "project_status", "book_log",
        "book_delegate", "book_record_result", "project_continue",
        "book_open_task", "book_complete_task", "book_add_artifact",
        "book_reflect", "book_request_task", "book_assign_task",
        "book_satisfy_criterion", "book_set_criteria", "book_set_roadmap",
        "prepare_manager_handoff", "book_request_approval",
        "book_resolve_approval", "book_request_split", "book_split_task",
    }
    assert set(registered_names) == expected


def test_register_book_tools_is_idempotent():
    _import_sdk_registry()

    from omoikane.tools import (
        register_book_tools,
        reset_registration_for_tests,
    )

    reset_registration_for_tests()
    first = register_book_tools()
    second = register_book_tools()
    assert first.keys() == second.keys()


def test_registered_tools_are_callable_and_persist(temp_hermes_home):
    """End-to-end through the SDK dispatch path: a registered tool
    successfully mutates the Project Book just like any other handler."""
    sdk_registry = _import_sdk_registry()

    import json

    from omoikane.core.book import ProjectBook
    from omoikane.tools import register_book_tools, reset_registration_for_tests

    reset_registration_for_tests()
    register_book_tools(override=True)

    book = ProjectBook.create("test brief", ["AC1"])
    entry = next(
        t for t in sdk_registry._tools.values() if t.name == "book_log"
    )
    out = entry.handler({
        "project_id": book.project_id,
        "kind": "decision",
        "summary": "smoke-test entry",
    })
    payload = json.loads(out)
    assert payload.get("success") is True

    activity_lines = (book.store.activity_path).read_text().splitlines()
    assert any("smoke-test entry" in line for line in activity_lines)


def test_project_start_round_trip_through_registry(temp_hermes_home):
    """Dispatch the highest-value handler (project_start) through the live SDK
    registry: it must capture origin into book.json and return the cron no-op
    return shape (supervisor_cron_id / supervisor_cron_error both None).

    This pins both the return-shape contract AND the intentional cron
    no-op that no other test exercises through the registry.
    """
    sdk_registry = _import_sdk_registry()

    import json

    from omoikane.core.book import ProjectBook
    from omoikane.tools import register_book_tools, reset_registration_for_tests

    reset_registration_for_tests()
    register_book_tools(override=True)

    entry = next(
        t for t in sdk_registry._tools.values() if t.name == "project_start"
    )
    out = entry.handler(
        {"brief": "round-trip brief", "acceptance_criteria": ["AC1", "AC2"]},
        origin={"platform": "cli", "chat_id": "x"},
    )
    payload = json.loads(out)

    assert payload.get("project_id")
    assert payload.get("status")
    assert "supervisor_cron_id" in payload
    assert "supervisor_cron_error" in payload
    assert payload["supervisor_cron_id"] is None
    assert payload["supervisor_cron_error"] is None

    origin = ProjectBook(payload["project_id"]).load().get("origin")
    assert origin is not None
    assert origin["platform"] == "cli"
    assert origin["chat_id"] == "x"
