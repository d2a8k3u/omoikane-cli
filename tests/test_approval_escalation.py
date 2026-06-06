"""Approval escalation: specialists file requests, operator resolves them.

Covers the path that lets autonomous projects survive Hermes' cron approval
wedge — when a tool returns ``pending_approval``, the specialist files a Book
entry, the supervisor surfaces it, the operator resolves via CLI/dashboard.
"""

import json

from omoikane.core.book import ProjectBook
from omoikane.tools import (
    book_request_approval,
    book_resolve_approval,
)


def _file_approval(book: ProjectBook, **overrides):
    args = {
        "project_id": book.project_id,
        "task_id": "task-1234",
        "requester_role": "agent-implementer",
        "action": "run pytest",
        "command": "pytest -q",
        "reason": "verify acceptance criterion 0",
    }
    args.update(overrides)
    return json.loads(book_request_approval(args))


def test_request_approval_persists_entry(temp_hermes_home):
    book = ProjectBook.create("brief", ["AC"])
    res = _file_approval(book)

    assert res["success"] is True
    assert res["status"] == "pending"
    assert res["approval_id"].startswith("appr-")

    data = book.load()
    assert len(data["pending_approvals"]) == 1
    entry = data["pending_approvals"][0]
    assert entry["approval_id"] == res["approval_id"]
    assert entry["task_id"] == "task-1234"
    assert entry["requester_role"] == "agent-implementer"
    assert entry["action"] == "run pytest"
    assert entry["command"] == "pytest -q"
    assert entry["status"] == "pending"
    assert entry["resolved_at"] is None
    assert entry["resolution"] is None


def test_request_approval_logs_activity(temp_hermes_home):
    book = ProjectBook.create("brief", ["AC"])
    _file_approval(book, action="install pandas", command="pip install pandas")

    activity = book.store.activity_path.read_text()
    assert "approval_request" in activity
    assert "install pandas" in activity


def test_request_approval_missing_fields_returns_error(temp_hermes_home):
    book = ProjectBook.create("brief", ["AC"])
    res = json.loads(book_request_approval({
        "project_id": book.project_id,
        "task_id": "task-1",
        # missing requester_role/action/command/reason
    }))
    assert "error" in res
    assert "requester_role" in res["error"]


def test_request_approval_generates_unique_ids(temp_hermes_home):
    book = ProjectBook.create("brief", ["AC"])
    ids = {_file_approval(book)["approval_id"] for _ in range(5)}
    assert len(ids) == 5


def test_resolve_approval_approve_appends_command(temp_hermes_home):
    book = ProjectBook.create("brief", ["AC"])
    aid = _file_approval(book, command="pytest -q tests/")["approval_id"]

    res = json.loads(book_resolve_approval({
        "project_id": book.project_id,
        "approval_id": aid,
        "decision": "approve",
        "note": "ok",
    }))
    assert res["success"] is True
    assert res["status"] == "approve"

    data = book.load()
    entry = data["pending_approvals"][0]
    assert entry["status"] == "approve"
    assert entry["resolved_at"] is not None
    assert entry["resolution"] == "ok"
    assert "pytest -q tests/" in data["approved_commands"]


def test_resolve_approval_deny_does_not_append_command(temp_hermes_home):
    book = ProjectBook.create("brief", ["AC"])
    aid = _file_approval(book, command="rm -rf /")["approval_id"]

    res = json.loads(book_resolve_approval({
        "project_id": book.project_id,
        "approval_id": aid,
        "decision": "deny",
        "note": "absolutely not",
    }))
    assert res["success"] is True

    data = book.load()
    assert data["approved_commands"] == []
    assert data["pending_approvals"][0]["status"] == "deny"


def test_resolve_approval_unknown_id_errors(temp_hermes_home):
    book = ProjectBook.create("brief", ["AC"])
    res = json.loads(book_resolve_approval({
        "project_id": book.project_id,
        "approval_id": "appr-missing",
        "decision": "approve",
    }))
    assert "error" in res
    assert "not found" in res["error"]


def test_resolve_approval_already_resolved_errors(temp_hermes_home):
    book = ProjectBook.create("brief", ["AC"])
    aid = _file_approval(book)["approval_id"]

    book_resolve_approval({
        "project_id": book.project_id,
        "approval_id": aid,
        "decision": "approve",
    })
    res = json.loads(book_resolve_approval({
        "project_id": book.project_id,
        "approval_id": aid,
        "decision": "deny",
    }))
    assert "error" in res
    assert "already resolved" in res["error"]


def test_resolve_approval_invalid_decision_errors(temp_hermes_home):
    book = ProjectBook.create("brief", ["AC"])
    aid = _file_approval(book)["approval_id"]

    res = json.loads(book_resolve_approval({
        "project_id": book.project_id,
        "approval_id": aid,
        "decision": "maybe",
    }))
    assert "error" in res
    assert "approve" in res["error"]


def test_resolve_approval_dedupes_approved_commands(temp_hermes_home):
    """Approving the same command twice does not duplicate the allowlist entry."""
    book = ProjectBook.create("brief", ["AC"])
    aid1 = _file_approval(book, command="pytest -q")["approval_id"]
    aid2 = _file_approval(book, command="pytest -q")["approval_id"]

    book_resolve_approval({
        "project_id": book.project_id, "approval_id": aid1, "decision": "approve",
    })
    book_resolve_approval({
        "project_id": book.project_id, "approval_id": aid2, "decision": "approve",
    })

    data = book.load()
    assert data["approved_commands"] == ["pytest -q"]


def test_resolve_approval_always_extends_global_allowlist(monkeypatch, temp_hermes_home):
    """Operator approval is meaningless without the global write — Hermes'
    gate doesn't read book.json. resolve_approval(approve) must always call
    the extend helper so the next dispatch passes the gate."""
    book = ProjectBook.create("brief", ["AC"])
    aid = _file_approval(book, command="pytest -xvs tests/")["approval_id"]

    calls = []

    def fake_extend(pattern):
        calls.append(pattern)
        return True

    monkeypatch.setattr(
        "omoikane.core.book.ProjectBook._extend_hermes_global_allowlist",
        staticmethod(fake_extend),
    )

    res = json.loads(book_resolve_approval({
        "project_id": book.project_id,
        "approval_id": aid,
        "decision": "approve",
    }))
    assert res["success"] is True
    assert res["allowlisted_globally"] is True
    assert calls == ["pytest -xvs tests/"]


def test_resolve_approval_deny_never_extends_global(monkeypatch, temp_hermes_home):
    """Deny must never touch Hermes allowlist."""
    book = ProjectBook.create("brief", ["AC"])
    aid = _file_approval(book)["approval_id"]

    monkeypatch.setattr(
        "omoikane.core.book.ProjectBook._extend_hermes_global_allowlist",
        staticmethod(lambda p: (_ for _ in ()).throw(AssertionError(
            "deny path must not extend Hermes allowlist"
        ))),
    )

    res = json.loads(book_resolve_approval({
        "project_id": book.project_id,
        "approval_id": aid,
        "decision": "deny",
    }))
    assert res["success"] is True


def test_mark_approval_notified_sets_timestamp(temp_hermes_home):
    """Supervisor records that an approval push reached the operator's channel."""
    book = ProjectBook.create("brief", ["AC"])
    aid = _file_approval(book)["approval_id"]

    ok = book.mark_approval_notified(
        approval_id=aid,
        platform="telegram",
        chat_id="123",
        message_id="msg-7",
    )
    assert ok is True
    data = book.load()
    entry = data["pending_approvals"][0]
    assert entry["notified_at"] is not None
    assert entry["notified_via"] == {
        "platform": "telegram",
        "chat_id": "123",
        "message_id": "msg-7",
    }


def test_mark_approval_notified_unknown_id_returns_false(temp_hermes_home):
    book = ProjectBook.create("brief", ["AC"])
    assert book.mark_approval_notified(
        approval_id="appr-nope", platform="telegram", chat_id="1",
    ) is False


def test_set_active_resurrect_run_id_check_and_set(temp_hermes_home):
    book = ProjectBook.create("brief", ["AC"])
    assert book.set_active_resurrect_run_id("run-1") is True
    # Second call must NOT clobber — race-safety.
    assert book.set_active_resurrect_run_id("run-2") is False
    data = book.load()
    assert data["active_resurrect_run_id"] == "run-1"


def test_clear_active_resurrect_run_id(temp_hermes_home):
    book = ProjectBook.create("brief", ["AC"])
    book.set_active_resurrect_run_id("run-1")
    book.clear_active_resurrect_run_id(final_status="completed")
    data = book.load()
    assert data["active_resurrect_run_id"] is None


def test_load_backfills_approval_fields_for_legacy_book(temp_hermes_home):
    """Older books on disk predate these fields — load() fills them."""
    book = ProjectBook.create("brief", ["AC"])
    raw = json.loads(book.store.book_path.read_text())
    raw.pop("pending_approvals", None)
    raw.pop("approved_commands", None)
    book.store.book_path.write_text(json.dumps(raw))
    on_disk = json.loads(book.store.book_path.read_text())
    assert "pending_approvals" not in on_disk
    assert "approved_commands" not in on_disk

    data = book.load()
    assert data["pending_approvals"] == []
    assert data["approved_commands"] == []
