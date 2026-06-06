"""In-process session ↔ project binding (omoikane.tools.session).

Pins the bind / get / clear / handler-kwarg behaviour that
``post_tool_call`` style hooks rely on to resolve the active project
without every tool call spelling out ``project_id`` (Finding C4).
"""
from __future__ import annotations

import pytest

from omoikane.tools import session


@pytest.fixture(autouse=True)
def _reset_bindings():
    session.reset_for_tests()
    yield
    session.reset_for_tests()


def test_bind_then_get_returns_project():
    session.bind_session_to_project("sess-1", "proj-A")
    assert session.get_active_project(session_id="sess-1") == "proj-A"


def test_get_returns_none_for_unknown():
    assert session.get_active_project(session_id="nope") is None
    assert session.get_active_project(task_id="nope") is None


def test_get_matches_task_id_too():
    session.bind_session_to_project("task-7", "proj-B")
    assert session.get_active_project(task_id="task-7") == "proj-B"


def test_bind_ignores_empty_ids():
    session.bind_session_to_project("", "proj-A")
    session.bind_session_to_project("sess-2", "")
    assert session.get_active_project(session_id="") is None
    assert session.get_active_project(session_id="sess-2") is None


def test_clear_removes_binding():
    session.bind_session_to_project("sess-3", "proj-C")
    assert session.clear_session_binding("sess-3") is True
    assert session.get_active_project(session_id="sess-3") is None
    # Second clear is a no-op.
    assert session.clear_session_binding("sess-3") is False


def test_bind_from_handler_kwargs_binds_task_and_session():
    session.bind_from_handler_kwargs(
        {"session_id": "sess-9", "task_id": "task-9"}, "proj-D"
    )
    assert session.get_active_project(session_id="sess-9") == "proj-D"
    assert session.get_active_project(task_id="task-9") == "proj-D"


def test_bind_from_handler_kwargs_tolerates_missing_keys():
    session.bind_from_handler_kwargs({"task_id": "task-only"}, "proj-E")
    assert session.get_active_project(task_id="task-only") == "proj-E"
    assert session.get_active_project(session_id="absent") is None
