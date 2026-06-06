"""Transport adapters — stdout / telegram / slack."""
from __future__ import annotations

from typing import Any, Dict, List

import pytest

from omoikane.transport import (
    ApprovalEnvelope,
    SlackConfig,
    SlackTransport,
    StdoutTransport,
    TelegramConfig,
    TelegramTransport,
    TransportResponse,
    build_transport,
    format_approval_message,
    load_from_config,
)


def _envelope() -> ApprovalEnvelope:
    return ApprovalEnvelope(
        project_id="proj-abc",
        approval_id="a-1",
        requester_role="agent-implementer",
        action="execute_command",
        command="rm -rf /tmp/foo",
        reason="garbage collection",
    )


def test_format_approval_message_contains_required_fields():
    text = format_approval_message(_envelope())
    assert "proj-abc" in text
    assert "/approve a-1" in text
    assert "/deny a-1" in text
    assert "rm -rf" in text


def test_stdout_transport_writes_and_returns_empty_poll(capsys):
    transport = StdoutTransport()
    assert transport.send_approval_request(_envelope())
    assert transport.send_completion("proj-abc", "done")
    captured = capsys.readouterr().out
    assert "proj-abc" in captured
    assert "done" in captured
    assert transport.poll_responses() == []


class _FakeHttp:
    def __init__(self, responses: Dict[str, Any] = None):
        self.responses = responses or {}
        self.calls: List[Dict[str, Any]] = []

    def get(self, url, params):
        self.calls.append({"method": "GET", "url": url, "params": params})
        return self.responses.get(url, {"result": []})

    def post(self, url, json):
        self.calls.append({"method": "POST", "url": url, "json": json})
        return self.responses.get(url, {"ok": True})


def test_telegram_send_uses_chat_id(tmp_path, monkeypatch):
    monkeypatch.setenv("OMOIKANE_HOME", str(tmp_path))
    config = TelegramConfig(bot_token="t", chat_id="-1001", parse_mode="HTML")
    http = _FakeHttp()
    transport = TelegramTransport(config, http_client=http)
    assert transport.send_approval_request(_envelope())
    assert http.calls and http.calls[0]["method"] == "POST"
    assert http.calls[0]["json"]["chat_id"] == "-1001"
    assert http.calls[0]["json"]["parse_mode"] == "HTML"
    assert "a-1" in http.calls[0]["json"]["text"]


def test_telegram_poll_parses_approve_deny(tmp_path, monkeypatch):
    monkeypatch.setenv("OMOIKANE_HOME", str(tmp_path))
    config = TelegramConfig(bot_token="t", chat_id="-1001")
    url = f"https://api.telegram.org/bott/getUpdates"
    http = _FakeHttp(responses={url: {"result": [
        {"update_id": 10, "message": {"text": "/approve a-1"}},
        {"update_id": 11, "message": {"text": "/deny a-2 too risky"}},
        {"update_id": 12, "message": {"text": "ignore me"}},
    ]}})
    transport = TelegramTransport(config, http_client=http)
    responses = transport.poll_responses()
    assert [(r.approval_id, r.decision) for r in responses] == [
        ("a-1", "approve"),
        ("a-2", "deny"),
    ]
    assert responses[1].note == "too risky"
    # Offset file persisted so the next poll only sees newer updates.
    offset_path = tmp_path / "telegram.offset"
    assert offset_path.exists()
    assert offset_path.read_text() == "12"


def test_slack_send_posts_to_webhook():
    http = _FakeHttp()
    transport = SlackTransport(SlackConfig(webhook_url="https://hooks/x"), http_client=http)
    assert transport.send_completion("proj-abc", "all done")
    assert http.calls and http.calls[0]["method"] == "POST"
    assert http.calls[0]["json"]["text"].startswith("✅")


def test_slack_send_skips_without_webhook():
    transport = SlackTransport(SlackConfig(webhook_url=""))
    assert not transport.send_completion("proj-abc", "all done")


def test_build_transport_returns_none_for_unknown_backend():
    assert build_transport("smoke-signals", {}) is None


def test_load_from_config_defaults_to_stdout():
    transports = load_from_config({})
    assert len(transports) == 1
    assert transports[0].name == "stdout"


def test_load_from_config_multi_backend():
    transports = load_from_config({
        "transport": {
            "backends": ["stdout", "telegram"],
            "telegram": {"bot_token": "t", "chat_id": "-1001"},
        }
    })
    assert [t.name for t in transports] == ["stdout", "telegram"]
