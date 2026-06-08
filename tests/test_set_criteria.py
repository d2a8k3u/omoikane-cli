"""book_set_criteria — append-only criteria with provenance.

Pins the headline brief-driven-criteria behaviour: criteria can be appended
after start (analyst derivation / CTO escalation / QA completeness gap),
append-only never disturbs already-satisfied or operator-given entries, and
provenance is tracked alongside status.
"""
import json

from omoikane.core.book import ProjectBook
from omoikane.tools import book_set_criteria


def test_set_criteria_appends_with_provenance(temp_hermes_home):
    book = ProjectBook.create("brief", [])  # no criteria at start
    res = json.loads(book_set_criteria({
        "project_id": book.project_id,
        "criteria": [
            {"text": "CLI exits 0 on --help", "provenance": "extracted"},
            {"text": "Empty input is rejected", "provenance": "synthesized"},
        ],
    }))
    assert res["success"] is True
    assert res["new_indices"] == [0, 1]
    assert res["criteria_count"] == 2

    data = book.load()
    assert data["acceptance_criteria"] == [
        "CLI exits 0 on --help", "Empty input is rejected",
    ]
    assert data["criteria_status"] == {"0": "pending", "1": "pending"}
    assert data["criteria_provenance"] == {"0": "extracted", "1": "synthesized"}


def test_set_criteria_is_append_only_and_preserves_satisfied(temp_hermes_home):
    book = ProjectBook.create("brief", ["operator one"])
    book.satisfy_criterion(0, evidence="checked")

    new_idx = book.set_criteria([
        {"text": "derived two", "provenance": "synthesized"},
    ])
    assert new_idx == [1]

    data = book.load()
    # Existing operator criterion is untouched: same text, still satisfied,
    # provenance still operator_given. New one appends pending.
    assert data["acceptance_criteria"][0] == "operator one"
    assert data["criteria_status"]["0"] == "satisfied"
    assert data["criteria_provenance"]["0"] == "operator_given"
    assert data["criteria_status"]["1"] == "pending"
    assert data["criteria_provenance"]["1"] == "synthesized"


def test_set_criteria_dedupes_exact_text(temp_hermes_home):
    book = ProjectBook.create("brief", ["already here"])
    new_idx = book.set_criteria([
        {"text": "  already here  ", "provenance": "synthesized"},  # dup (stripped)
        {"text": "", "provenance": "synthesized"},                  # blank skipped
        {"text": "genuinely new", "provenance": "extracted"},
    ])
    assert new_idx == [1]  # only the genuinely-new one landed
    assert book.load()["acceptance_criteria"] == ["already here", "genuinely new"]


def test_set_criteria_handler_rejects_bad_input(temp_hermes_home):
    book = ProjectBook.create("brief", [])
    assert "error" in json.loads(book_set_criteria({"project_id": book.project_id, "criteria": []}))
    assert "error" in json.loads(book_set_criteria({"project_id": book.project_id, "criteria": [{"text": ""}]}))
    bad_prov = json.loads(book_set_criteria({
        "project_id": book.project_id,
        "criteria": [{"text": "x", "provenance": "made_up"}],
    }))
    assert "error" in bad_prov
    assert "provenance" in bad_prov["error"]


def test_set_criteria_logs_decision_with_full_list(temp_hermes_home):
    book = ProjectBook.create("brief", [])
    book.set_criteria([{"text": "log me", "provenance": "escalated"}])
    activity = book.store.activity_path.read_text()
    assert "Criteria appended" in activity
    assert "log me" in activity
    assert "escalated" in activity


def test_set_criteria_default_provenance_is_synthesized(temp_hermes_home):
    book = ProjectBook.create("brief", [])
    json.loads(book_set_criteria({
        "project_id": book.project_id,
        "criteria": [{"text": "no provenance given"}],
    }))
    assert book.load()["criteria_provenance"]["0"] == "synthesized"
