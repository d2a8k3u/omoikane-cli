"""project_start captures origin platform/chat_id from Hermes session ContextVars
into book.json — that's how the supervisor routes approval pushes back to the
operator's main channel.
"""

import json
import os
from unittest.mock import patch

import pytest

from omoikane.core.book import ProjectBook
from omoikane.tools import project_start


def _project_start(**overrides):
    args = {
        "brief": "Tiny project",
        "acceptance_criteria": ["A", "B"],
    }
    args.update(overrides)
    return json.loads(project_start(args))


def test_origin_captured_from_env_vars(monkeypatch, temp_hermes_home):
    """When Hermes session vars are bound, project_start persists origin."""
    monkeypatch.setenv("HERMES_SESSION_PLATFORM", "telegram")
    monkeypatch.setenv("HERMES_SESSION_CHAT_ID", "12345")
    monkeypatch.setenv("HERMES_SESSION_THREAD_ID", "")
    monkeypatch.setenv("HERMES_SESSION_USER_ID", "u-99")

    res = _project_start()
    book = ProjectBook(res["project_id"])
    data = book.load()

    origin = data.get("origin")
    assert origin is not None
    assert origin["platform"] == "telegram"
    assert origin["chat_id"] == "12345"
    assert origin["user_id"] == "u-99"
    assert origin["captured_at"]


def test_origin_falls_back_to_default_notify_channel(monkeypatch, temp_hermes_home):
    """No env origin + ``[transport] default_notify_channel`` set in config → use it.

    Rewritten for the standalone CLI: instead of patching ``hermes_cli.config``
    we drop a real ``~/.omoikane/config.toml`` into the temp home that the
    new :mod:`omoikane.tools.audit` module loads on demand.
    """
    monkeypatch.delenv("OMOIKANE_ORIGIN_PLATFORM", raising=False)
    monkeypatch.delenv("OMOIKANE_ORIGIN_CHAT_ID", raising=False)
    monkeypatch.delenv("HERMES_SESSION_PLATFORM", raising=False)
    monkeypatch.delenv("HERMES_SESSION_CHAT_ID", raising=False)

    from omoikane.config import paths

    cfg_file = paths.config_file()
    cfg_file.parent.mkdir(parents=True, exist_ok=True)
    cfg_file.write_text(
        "[transport]\n"
        'default_notify_channel = "telegram:777"\n'
    )

    res = _project_start()

    book = ProjectBook(res["project_id"])
    origin = book.load().get("origin")
    assert origin is not None
    assert origin["platform"] == "telegram"
    assert origin["chat_id"] == "777"


def test_origin_null_when_no_session_and_no_default(monkeypatch, temp_hermes_home):
    """No session context AND no default config → origin stays null. Project
    still starts (supervisor will skip the approval push with a no-origin note)."""
    monkeypatch.delenv("HERMES_SESSION_PLATFORM", raising=False)
    monkeypatch.delenv("HERMES_SESSION_CHAT_ID", raising=False)

    res = _project_start()
    book = ProjectBook(res["project_id"])
    data = book.load()
    assert data.get("origin") in (None, {})


def test_origin_thread_id_preserved(monkeypatch, temp_hermes_home):
    """Telegram topics carry thread_id; supervisor needs it for replies."""
    monkeypatch.setenv("HERMES_SESSION_PLATFORM", "telegram")
    monkeypatch.setenv("HERMES_SESSION_CHAT_ID", "-100123")
    monkeypatch.setenv("HERMES_SESSION_THREAD_ID", "7")

    res = _project_start()
    book = ProjectBook(res["project_id"])
    origin = book.load().get("origin") or {}
    assert origin.get("thread_id") == "7"
