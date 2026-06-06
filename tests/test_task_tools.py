import json
import tempfile
from pathlib import Path

from omoikane.core.book import ProjectBook
from omoikane.tools import (
    book_open_task,
    book_complete_task,
    book_add_artifact,
    book_reflect,
)


def test_book_open_task(temp_hermes_home):
    book = ProjectBook.create("brief", ["AC"])
    res = json.loads(book_open_task({
        "project_id": book.project_id,
        "title": "Implement parser",
        "assignee_role": "agent-implementer",
    }))
    assert res["success"] is True
    assert res["task"].startswith("task-")

    data = book.load()
    assert res["task"] in data["open_tasks"]
    assert data["task_meta"][res["task"]]["assignee_role"] == "agent-implementer"


def test_book_open_task_forwards_phase_blocked_by_milestone(temp_hermes_home):
    book = ProjectBook.create("brief", ["AC"])
    parent = json.loads(book_open_task({
        "project_id": book.project_id,
        "title": "Parent",
    }))
    res = json.loads(book_open_task({
        "project_id": book.project_id,
        "title": "Wire frontend to API",
        "assignee_role": "agent-frontend-engineer",
        "phase": "implementation",
        "blocked_by": [parent["task"]],
        "milestone_id": "m-frontend",
    }))
    assert res["success"] is True
    assert res["phase"] == "implementation"
    assert res["milestone_id"] == "m-frontend"
    assert res["blocked_by"] == [parent["task"]]

    meta = book.load()["task_meta"][res["task"]]
    assert meta["phase"] == "implementation"
    assert meta["blocked_by"] == [parent["task"]]
    assert meta["milestone_id"] == "m-frontend"


def test_book_open_task_rejects_blocked_by_non_list(temp_hermes_home):
    book = ProjectBook.create("brief", ["AC"])
    res = json.loads(book_open_task({
        "project_id": book.project_id,
        "title": "X",
        "blocked_by": "task-0001",
    }))
    assert "error" in res
    assert "blocked_by" in res["error"]


def test_book_complete_task_moves_to_completed(temp_hermes_home):
    book = ProjectBook.create("brief", ["AC"])
    opened = json.loads(book_open_task({
        "project_id": book.project_id,
        "title": "Write tests",
    }))
    tid = opened["task"]

    res = json.loads(book_complete_task({
        "project_id": book.project_id,
        "task": tid,
    }))
    assert res["success"] is True
    data = book.load()
    assert tid in data["completed_tasks"]
    assert tid not in data["open_tasks"]


def test_book_complete_task_unknown_returns_error(temp_hermes_home):
    book = ProjectBook.create("brief", ["AC"])
    res = json.loads(book_complete_task({
        "project_id": book.project_id,
        "task": "task-does-not-exist",
    }))
    assert "error" in res


def test_book_add_artifact_copies_file(temp_hermes_home, tmp_path):
    book = ProjectBook.create("brief", ["AC"])
    src = tmp_path / "out.py"
    src.write_text("print('hi')\n")

    res = json.loads(book_add_artifact({
        "project_id": book.project_id,
        "path": str(src),
        "kind": "code",
        "note": "First module",
    }))
    assert res["success"] is True
    assert res["path"] == "artifacts/out.py"
    assert (book.store.project_dir / "artifacts" / "out.py").exists()

    data = book.load()
    assert data["artifacts"][-1]["path"] == "artifacts/out.py"


def test_book_reflect_writes_file_and_logs(temp_hermes_home):
    book = ProjectBook.create("brief", ["AC"])
    res = json.loads(book_reflect({
        "project_id": book.project_id,
        "lesson": "Always check the spec twice",
        "task": "task-0001",
    }))
    assert res["success"] is True
    refl_path = book.store.project_dir / res["ref"]
    assert refl_path.exists()
    assert "Always check the spec twice" in refl_path.read_text()

    activity = book.store.activity_path.read_text()
    assert "reflection" in activity
