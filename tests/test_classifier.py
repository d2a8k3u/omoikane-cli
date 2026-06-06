"""Classifier — 5-state project state machine. v0.4.0."""

from datetime import datetime, timedelta, timezone

import pytest

from omoikane.core.book import ProjectBook
from omoikane.core.watchdog import (
    DEFAULT_HEALTHY_MINUTES,
    DEFAULT_STALL_MINUTES,
    ProjectState,
    classify,
)


def _project_with(*, status="in_progress", last_activity_minutes_ago=1,
                  open_tasks=None, criteria=None, criteria_satisfied=0,
                  active_resurrect_run_id=None):
    last_iso = (
        datetime.now(timezone.utc) - timedelta(minutes=last_activity_minutes_ago)
    ).isoformat()
    data = {
        "status": status,
        "last_activity": last_iso,
        "open_tasks": list(open_tasks or []),
        "acceptance_criteria": list(criteria or []),
        "criteria_status": {
            str(i): "satisfied" for i in range(criteria_satisfied)
        },
        "active_resurrect_run_id": active_resurrect_run_id,
    }
    return data


def test_classify_terminal_status():
    data = _project_with(status="done")
    v = classify(data, datetime.now(timezone.utc))
    assert v.state == ProjectState.TERMINAL


def test_classify_completed_when_no_open_and_all_satisfied():
    data = _project_with(
        open_tasks=[], criteria=["A", "B"], criteria_satisfied=2,
    )
    v = classify(data, datetime.now(timezone.utc))
    assert v.state == ProjectState.COMPLETED


def test_classify_healthy_recent_activity():
    data = _project_with(
        last_activity_minutes_ago=1, open_tasks=["t1"],
        criteria=["A"], criteria_satisfied=0,
    )
    v = classify(data, datetime.now(timezone.utc),
                 stall_minutes=10, healthy_minutes=3)
    assert v.state == ProjectState.HEALTHY


def test_classify_stalled_when_idle_past_threshold():
    data = _project_with(
        last_activity_minutes_ago=60, open_tasks=["t1"],
        criteria=["A"], criteria_satisfied=0,
    )
    v = classify(data, datetime.now(timezone.utc), stall_minutes=10)
    assert v.state == ProjectState.STALLED
    assert v.idle_minutes >= 10


def test_classify_in_flight_when_resurrect_running():
    data = _project_with(
        last_activity_minutes_ago=60, open_tasks=["t1"], criteria=["A"],
        active_resurrect_run_id="run-1",
    )
    v = classify(data, datetime.now(timezone.utc),
                 run_status_fn=lambda r: "running")
    assert v.state == ProjectState.IN_FLIGHT
    assert v.active_resurrect_run_id == "run-1"
    assert v.run_status == "running"


def test_classify_crashed_when_run_terminal_but_work_remains():
    data = _project_with(
        last_activity_minutes_ago=60, open_tasks=["t1"], criteria=["A"],
        active_resurrect_run_id="run-dead",
    )
    v = classify(data, datetime.now(timezone.utc),
                 run_status_fn=lambda r: "completed")
    assert v.state == ProjectState.CRASHED


def test_classify_in_flight_when_gateway_unreachable():
    """Gateway blip MUST NOT spawn a duplicate run — slot stays held."""
    data = _project_with(
        last_activity_minutes_ago=60, open_tasks=["t1"], criteria=["A"],
        active_resurrect_run_id="run-1",
    )
    v = classify(data, datetime.now(timezone.utc),
                 run_status_fn=lambda r: "unreachable")
    assert v.state == ProjectState.IN_FLIGHT


def test_classify_in_flight_when_status_fn_returns_none():
    data = _project_with(
        last_activity_minutes_ago=60, open_tasks=["t1"], criteria=["A"],
        active_resurrect_run_id="run-1",
    )
    v = classify(data, datetime.now(timezone.utc),
                 run_status_fn=lambda r: None)
    assert v.state == ProjectState.IN_FLIGHT


def test_classify_crashed_when_run_definitively_gone():
    data = _project_with(
        last_activity_minutes_ago=60, open_tasks=["t1"], criteria=["A"],
        active_resurrect_run_id="run-gone",
    )
    v = classify(data, datetime.now(timezone.utc),
                 run_status_fn=lambda r: "gone")
    assert v.state == ProjectState.CRASHED


def test_classify_optimistic_in_flight_when_status_unchecked():
    data = _project_with(
        last_activity_minutes_ago=60, open_tasks=["t1"], criteria=["A"],
        active_resurrect_run_id="run-1",
    )
    v = classify(data, datetime.now(timezone.utc), run_status_fn=None)
    assert v.state == ProjectState.IN_FLIGHT


def test_classification_dict_serializes():
    data = _project_with(
        last_activity_minutes_ago=60, open_tasks=["t1"], criteria=["A"],
    )
    v = classify(data, datetime.now(timezone.utc))
    d = v.as_dict()
    assert d["state"] == "stalled"
    assert d["idle_minutes"] >= 10
    assert d["open_tasks_count"] == 1
    assert d["unsatisfied_criteria_count"] == 1
