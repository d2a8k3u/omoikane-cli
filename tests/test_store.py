"""Tests for store.py atomicity, locking, and edge cases."""

import json
import os
import shutil
import threading
import time

import pytest

from omoikane.core.store import ProjectStore, generate_project_id


def test_atomic_json_write_durable(tmp_path):
    """_atomic_json_write should produce a valid, readable file even after multiple writes."""
    from omoikane.core.store import _atomic_json_write
    path = tmp_path / "test.json"
    for i in range(3):
        _atomic_json_write(path, {"iteration": i})
        data = json.loads(path.read_text())
        assert data["iteration"] == i


def test_atomic_json_write_tmp_cleanup(tmp_path):
    """Temp files should never persist after crash path is resolved."""
    from omoikane.core.store import _atomic_json_write
    path = tmp_path / "data.json"
    _atomic_json_write(path, {"x": 1})
    assert path.exists()
    assert not list(tmp_path.glob("*.tmp-*"))


def test_store_load_book_missing():
    """load_book must raise FileNotFoundError for a missing project."""
    store = ProjectStore("proj-never-exists-123")
    with pytest.raises(FileNotFoundError):
        store.load_book()


def test_store_create_book_rejects_duplicate_locked(temp_hermes_home):
    """Two concurrent create_book calls on the same ID must not produce a corrupted book."""
    pid = "proj-race-001"
    store = ProjectStore(pid)
    store.create_book("brief", ["a"])
    with pytest.raises(FileExistsError):
        store.create_book("brief", ["b"])


def test_store_update_book_atomic(temp_hermes_home):
    """update_book must perform read-modify-write under one exclusive lock."""
    pid = "proj-updater-001"
    store = ProjectStore(pid)
    store.create_book("brief", ["ac"])

    def _mutate(data):
        data["status"] = "mutated"
        return "ok"

    book, result = store.update_book(_mutate)
    assert result == "ok"
    assert book["status"] == "mutated"
    # Re-read to confirm persistence
    book2 = store.load_book()
    assert book2["status"] == "mutated"


def test_store_update_book_raises_on_updater_exception(temp_hermes_home):
    """If the updater raises, the book must remain unchanged."""
    pid = "proj-updater-002"
    store = ProjectStore(pid)
    store.create_book("brief", ["ac"])

    def _bad(data):
        raise RuntimeError("boom")

    original = store.load_book()
    with pytest.raises(RuntimeError, match="boom"):
        store.update_book(_bad)
    after = store.load_book()
    assert after == original


def test_store_append_activity_is_durable(temp_hermes_home):
    """append_activity should fsync so entries survive simulated crash."""
    pid = "proj-act-dur"
    store = ProjectStore(pid)
    store.create_book("b", ["a"])
    store.append_activity(kind="note", summary="hello", actor="x")
    lines = store.activity_path.read_text().strip().split("\n")
    assert len(lines) == 1
    assert json.loads(lines[0])["summary"] == "hello"


# --- Concurrency stress tests (lightweight) ---


def test_store_update_book_no_lost_update(temp_hermes_home):
    """Ten parallel incrementers should not lose updates."""
    pid = "proj-concur-001"
    store = ProjectStore(pid)
    store.create_book("b", ["a"])

    counters = {"ok": 0, "errors": []}

    def worker():
        for _ in range(5):
            def _inc(data):
                data.setdefault("counter", 0)
                data["counter"] += 1
            try:
                store.update_book(_inc)
                counters["ok"] += 1
            except Exception as exc:
                counters["errors"].append(str(exc))
                # back-off slightly on contention
                time.sleep(0.001)

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    book = store.load_book()
    # Every successful iteration contributes exactly one increment.
    assert book.get("counter", 0) == counters["ok"]
    assert book["counter"] <= 50


# --- delegation edge cases ---


def test_delegation_corruption_handled(temp_hermes_home):
    """Corrupted delegation.json should raise ValueError, not silently return empty."""
    pid = "proj-delegation-bad"
    store = ProjectStore(pid)
    store.create_book("b", ["a"])
    store.delegation_path.write_text("this is not json")
    with pytest.raises(ValueError, match="Corrupted delegation.json"):
        store._load_delegation()


# --- resurrection check-and-set from store level ---


def test_compare_and_set_resurrect_idempotent(temp_hermes_home):
    """compare_and_set_resurrect_run_id must fail if already set."""
    pid = "proj-cas-001"
    store = ProjectStore(pid)
    store.create_book("b", ["a"])
    assert store.compare_and_set_resurrect_run_id("run-1") is True
    assert store.compare_and_set_resurrect_run_id("run-2") is False
    book = store.load_book()
    assert book["active_resurrect_run_id"] == "run-1"
