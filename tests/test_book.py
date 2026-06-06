"""Tests for book.py race-condition fixes and edge-case behaviour."""

import pytest

from omoikane.core.book import ProjectBook


def test_project_book_create(temp_hermes_home):
    book = ProjectBook.create(
        brief="Implement feature X",
        acceptance_criteria=["Tests pass", "Docs updated"],
        starting_state="scratch",
    )
    assert book.project_id.startswith("proj-")
    assert book.status == "created"
    assert book.current_phase == "planning"


def test_project_book_log(temp_hermes_home):
    book = ProjectBook.create("Brief", ["AC"])
    book.log(kind="decision", summary="Chose architecture A")
    activity = book.store.activity_path.read_text()
    assert "decision" in activity
    assert "Chose architecture A" in activity


def test_project_book_update_status(temp_hermes_home):
    book = ProjectBook.create("Brief", ["AC"])
    book.update_status("in_progress", phase="implementation")
    data = book.load()
    assert data["status"] == "in_progress"
    assert data["current_phase"] == "implementation"


def test_open_task_unique_ids(temp_hermes_home):
    """Opening many tasks should never produce duplicate task ids."""
    book = ProjectBook.create("Brief", ["AC"])
    ids = [book.open_task(f"Task {i}") for i in range(3)]
    assert len(ids) == len(set(ids))


def test_open_task_not_brittle_to_missing_book_file():
    """open_task on a non-existent project must fail loudly."""
    book = ProjectBook("proj-does-not-exist-000")
    with pytest.raises(FileNotFoundError):
        book.open_task("bad task")


def test_set_phase_idempotent(temp_hermes_home):
    """set_phase returns False when the phase hasn't actually moved."""
    book = ProjectBook.create("Brief", ["AC"])
    assert book.set_phase("implementation") is True
    assert book.set_phase("implementation") is False
    assert book.load()["current_phase"] == "implementation"


def test_complete_task_twice_returns_false(temp_hermes_home):
    """complete_task must be idempotent (second call returns False)."""
    book = ProjectBook.create("Brief", ["AC"])
    tid = book.open_task("task to close")
    assert book.complete_task(tid) is True
    assert book.complete_task(tid) is False


def test_resolve_invalid_decision(temp_hermes_home):
    """resolve_approval must reject invalid decisions."""
    book = ProjectBook.create("Brief", ["AC"])
    with pytest.raises(ValueError, match="decision must be 'approve' or 'deny'"):
        book.resolve_approval(approval_id="nonexistent", decision="banana")


def test_resolve_missing_approval(temp_hermes_home):
    """resolve_approval must raise ValueError for unknown approval id."""
    book = ProjectBook.create("Brief", ["AC"])
    with pytest.raises(ValueError, match="approval 'unknown' not found"):
        book.resolve_approval(approval_id="unknown", decision="approve")


def test_satisfy_criterion_bounds(temp_hermes_home):
    """satisfy_criterion returns False for out-of-range index."""
    book = ProjectBook.create("Brief", ["A", "B"])
    assert book.satisfy_criterion(-1) is False
    assert book.satisfy_criterion(2) is False
    assert book.satisfy_criterion(0) is True


def test_all_criteria_satisfied_empty_list(temp_hermes_home):
    """all_criteria_satisfied returns False when there are no criteria."""
    book = ProjectBook.create("Brief", [])
    assert book.all_criteria_satisfied() is False


def test_mark_approval_notified_missing(temp_hermes_home):
    """mark_approval_notified returns False if the approval id doesn't exist."""
    book = ProjectBook.create("Brief", ["AC"])
    assert book.mark_approval_notified(
        approval_id="nope", platform="slack", chat_id="c1"
    ) is False


def test_artifact_copy_failure(temp_hermes_home):
    """add_artifact must raise RuntimeError if file copy fails."""
    book = ProjectBook.create("Brief", ["AC"])
    with pytest.raises(RuntimeError, match="Artifact source not found"):
        book.add_artifact("/nonexistent/path/to/file.txt", kind="data")
