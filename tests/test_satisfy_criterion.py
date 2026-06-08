"""book_satisfy_criterion tool — flips status with evidence, validates input."""

import json

from omoikane.core.book import ProjectBook
from omoikane.tools import book_satisfy_criterion


def test_satisfy_criterion_flips_status(temp_hermes_home):
    book = ProjectBook.create("brief", ["A", "B"])
    res = json.loads(book_satisfy_criterion({
        "project_id": book.project_id,
        "index": 0,
        "evidence": "pytest tests/ shows 100% green",
    }))
    assert res["success"] is True
    assert res["criterion_index"] == 0
    assert res["criteria_status"]["0"] == "satisfied"
    assert res["criteria_status"]["1"] == "pending"
    assert res["all_satisfied"] is False


def test_satisfy_criterion_all_done_flips_flag(temp_hermes_home):
    book = ProjectBook.create("brief", ["A"])
    res = json.loads(book_satisfy_criterion({
        "project_id": book.project_id,
        "index": 0,
        "evidence": "verified",
    }))
    assert res["all_satisfied"] is True


def test_satisfy_criterion_requires_evidence(temp_hermes_home):
    book = ProjectBook.create("brief", ["A"])
    res = json.loads(book_satisfy_criterion({
        "project_id": book.project_id,
        "index": 0,
        # evidence missing
    }))
    assert "error" in res


def test_satisfy_criterion_rejects_out_of_range(temp_hermes_home):
    book = ProjectBook.create("brief", ["A"])
    res = json.loads(book_satisfy_criterion({
        "project_id": book.project_id,
        "index": 5,
        "evidence": "n/a",
    }))
    assert "error" in res
    assert "out of range" in res["error"]


def test_satisfy_criterion_rejects_non_integer_index(temp_hermes_home):
    book = ProjectBook.create("brief", ["A"])
    res = json.loads(book_satisfy_criterion({
        "project_id": book.project_id,
        "index": "first",
        "evidence": "n/a",
    }))
    assert "error" in res


def test_create_tags_operator_criteria_and_seeds_completeness_fields(temp_hermes_home):
    book = ProjectBook.create("brief", ["A", "B"])
    data = book.load()
    assert data["criteria_provenance"] == {"0": "operator_given", "1": "operator_given"}
    assert data["completeness_passes"] == 0
    assert data["completeness_clean"] is False
    assert data["review_criteria"] is False


def test_satisfy_criterion_logs_evidence(temp_hermes_home):
    book = ProjectBook.create("brief", ["A"])
    book_satisfy_criterion({
        "project_id": book.project_id,
        "index": 0,
        "evidence": "log line at api.py:42 shows redirect ok",
    })
    activity = book.store.activity_path.read_text()
    assert "redirect ok" in activity
    assert "criterion" in activity.lower()
