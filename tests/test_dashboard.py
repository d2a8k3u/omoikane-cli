from omoikane.core.book import ProjectBook
from omoikane.core.dashboard import DashboardProvider
from omoikane.tools import book_delegate


def test_list_projects_cold_start_initializes_schema(monkeypatch, tmp_path):
    """Hermes UI may load the Omoikane tab before any tool has been
    invoked. DashboardProvider must trigger the lazy schema init on its
    own cold-start path — not assume some other code already ran it.

    Without the dashboard._get_conn → _store._get_conn delegation this
    raises sqlite3.OperationalError: no such table: projects.
    """
    from omoikane.core import store as _store
    monkeypatch.setenv("OMOIKANE_HOME", str(tmp_path))
    # Force the lazy-init guard back to False so this test exercises the
    # cold path even if a prior test in the session already ran init.
    monkeypatch.setattr(_store, "_DB_READY", False)
    # NOTE: deliberately do NOT call store.init_index_db() here — that
    # would mask the bug we're guarding against.
    assert not (tmp_path / "index.db").exists()

    rows = DashboardProvider().list_projects()
    assert rows == []
    # The lazy init must have created the index file as a side effect.
    assert (tmp_path / "index.db").exists()


def test_list_projects_empty(temp_hermes_home):
    assert DashboardProvider().list_projects() == []


def test_list_projects_returns_created(temp_hermes_home):
    b1 = ProjectBook.create("brief 1", ["AC"])
    b2 = ProjectBook.create("brief 2", ["AC"])
    rows = DashboardProvider().list_projects()
    ids = {r["id"] for r in rows}
    assert b1.project_id in ids
    assert b2.project_id in ids


def test_project_detail_includes_book_and_delegation_tree(temp_hermes_home):
    book = ProjectBook.create("brief", ["AC"])
    book_delegate({
        "project_id": book.project_id,
        "task": "task-d1",
        "to_role": "agent-implementer",
        "expected": "x",
    })
    detail = DashboardProvider().project_detail(book.project_id)
    assert detail["id"] == book.project_id
    assert detail["book"]["title"]
    assert any(n["id"] == "n-task-d1" for n in detail["delegation_tree"]["nodes"])


def test_project_detail_unknown():
    assert "error" in DashboardProvider().project_detail("proj-missing")


def test_tail_activity_returns_recent(temp_hermes_home):
    book = ProjectBook.create("brief", ["AC"])
    for i in range(5):
        book.log("note", f"event {i}")

    entries = DashboardProvider().tail_activity(book.project_id, limit=3)
    assert len(entries) == 3
    assert entries[-1]["summary"] == "event 4"
