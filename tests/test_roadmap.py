"""Roadmap tool + field tests."""

import json

from omoikane.core.book import ProjectBook
from omoikane.tools import book_set_roadmap


def test_book_set_roadmap_persists_milestones(temp_hermes_home):
    book = ProjectBook.create("Brief", ["A", "B"])
    res = json.loads(book_set_roadmap({
        "project_id": book.project_id,
        "milestones": [
            {
                "milestone_id": "m1",
                "title": "Wire the API",
                "description": "Define the public surface",
                "criteria_indices": [0],
            },
            {
                "milestone_id": "m2",
                "title": "Verify end-to-end",
                "criteria_indices": [1],
                "status": "planned",
            },
        ],
    }))
    assert res["success"] is True
    assert res["milestone_count"] == 2

    data = book.load()
    assert len(data["roadmap"]) == 2
    assert data["roadmap"][0]["milestone_id"] == "m1"
    assert data["roadmap"][0]["title"] == "Wire the API"
    assert data["roadmap"][0]["criteria_indices"] == [0]
    assert data["roadmap"][0]["status"] == "planned"
    assert data["roadmap"][1]["milestone_id"] == "m2"


def test_book_set_roadmap_rejects_missing_title(temp_hermes_home):
    book = ProjectBook.create("Brief", ["A"])
    res = json.loads(book_set_roadmap({
        "project_id": book.project_id,
        "milestones": [{"milestone_id": "m1"}],
    }))
    assert "error" in res
    assert "title" in res["error"]


def test_book_set_roadmap_rejects_missing_milestone_id(temp_hermes_home):
    book = ProjectBook.create("Brief", ["A"])
    res = json.loads(book_set_roadmap({
        "project_id": book.project_id,
        "milestones": [{"title": "Do the thing"}],
    }))
    assert "error" in res
    assert "milestone_id" in res["error"]


def test_book_set_roadmap_rejects_duplicate_ids(temp_hermes_home):
    book = ProjectBook.create("Brief", ["A"])
    res = json.loads(book_set_roadmap({
        "project_id": book.project_id,
        "milestones": [
            {"milestone_id": "m1", "title": "A"},
            {"milestone_id": "m1", "title": "B"},
        ],
    }))
    assert "error" in res
    assert "duplicated" in res["error"]


def test_book_set_roadmap_rejects_non_list_milestones(temp_hermes_home):
    book = ProjectBook.create("Brief", ["A"])
    res = json.loads(book_set_roadmap({
        "project_id": book.project_id,
        "milestones": "not a list",
    }))
    assert "error" in res
    # Pin to the validation message so an unrelated exception doesn't
    # accidentally satisfy this test.
    assert "list" in res["error"]


def test_book_set_roadmap_rejects_non_dict_milestone_entry(temp_hermes_home):
    book = ProjectBook.create("Brief", ["A"])
    res = json.loads(book_set_roadmap({
        "project_id": book.project_id,
        "milestones": ["just a string, not an object"],
    }))
    assert "error" in res
    assert "object" in res["error"]


def test_book_set_roadmap_overwrites_full_list(temp_hermes_home):
    book = ProjectBook.create("Brief", ["A"])
    book_set_roadmap({
        "project_id": book.project_id,
        "milestones": [{"milestone_id": "m1", "title": "First"}],
    })
    book_set_roadmap({
        "project_id": book.project_id,
        "milestones": [
            {"milestone_id": "m2", "title": "Second"},
            {"milestone_id": "m3", "title": "Third"},
        ],
    })
    data = book.load()
    ids = [m["milestone_id"] for m in data["roadmap"]]
    assert ids == ["m2", "m3"]


def test_book_set_roadmap_logged_as_decision(temp_hermes_home):
    book = ProjectBook.create("Brief", ["A"])
    book_set_roadmap({
        "project_id": book.project_id,
        "milestones": [{"milestone_id": "m1", "title": "x"}],
    })
    activity = book.store.activity_path.read_text()
    assert "Roadmap committed" in activity
    assert "decision" in activity


def test_load_backfills_roadmap_for_legacy_book(temp_hermes_home):
    """Older books on disk predate the roadmap field — load() must fill it."""
    book = ProjectBook.create("Brief", ["A"])
    # Manually strip the roadmap field to simulate a legacy on-disk book.
    raw = json.loads(book.store.book_path.read_text())
    raw.pop("roadmap", None)
    book.store.book_path.write_text(json.dumps(raw))
    assert "roadmap" not in json.loads(book.store.book_path.read_text())
    assert book.load()["roadmap"] == []
