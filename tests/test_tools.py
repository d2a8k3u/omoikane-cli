import json

from omoikane.tools import project_start, project_status, book_log


def test_project_start_tool(temp_hermes_home):
    args = {
        "brief": "Build a simple CLI tool",
        "acceptance_criteria": ["CLI works", "Tests pass"],
        "starting_state": "scratch",
    }
    result = json.loads(project_start(args))
    assert "project_id" in result
    assert result["project_id"].startswith("proj-")


def test_project_start_requires_brief(temp_hermes_home):
    result = json.loads(project_start({"acceptance_criteria": ["x"]}))
    assert "error" in result


def test_project_start_requires_criteria(temp_hermes_home):
    result = json.loads(project_start({"brief": "x"}))
    assert "error" in result


def test_project_status_tool(temp_hermes_home):
    created = json.loads(project_start({"brief": "Test", "acceptance_criteria": ["OK"]}))
    pid = created["project_id"]

    status = json.loads(project_status({"project_id": pid}))
    assert status["project_id"] == pid
    assert status["status"] in {"created", "in_progress"}


def test_project_status_missing_id(temp_hermes_home):
    result = json.loads(project_status({}))
    assert "error" in result


def test_book_log_tool(temp_hermes_home):
    created = json.loads(project_start({"brief": "Test log", "acceptance_criteria": ["OK"]}))
    pid = created["project_id"]

    log_result = json.loads(book_log({
        "project_id": pid,
        "kind": "note",
        "summary": "Manual note from test",
    }))
    assert log_result["success"] is True
