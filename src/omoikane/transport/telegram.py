"""Telegram Bot API transport — long-poll for replies, send via sendMessage.

Configuration lives in ``~/.omoikane/config.toml``:

.. code-block:: toml

    [transport.telegram]
    bot_token   = "env:TELEGRAM_BOT_TOKEN"
    chat_id     = "-100123456789"
    parse_mode  = "Markdown"       # optional
    poll_offset_path = "telegram.offset"  # relative to OMOIKANE_HOME

The transport never persists messages locally — every ``poll_responses``
call talks to ``getUpdates`` so deliveries are at-least-once. The offset
is stored in ``OMOIKANE_HOME/<poll_offset_path>`` to dedupe across
supervisor ticks.
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from omoikane.config import paths

from .base import (
    ApprovalEnvelope,
    TransportResponse,
    format_approval_message,
    format_completion_message,
)

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.telegram.org/bot{token}"


def _resolve_env(value: str) -> str:
    if value.startswith("env:"):
        return os.environ.get(value[4:], "")
    return value


@dataclass
class TelegramConfig:
    bot_token: str
    chat_id: str
    parse_mode: str = "Markdown"
    poll_offset_path: str = "telegram.offset"

    @classmethod
    def from_dict(cls, data: dict) -> "TelegramConfig":
        return cls(
            bot_token=_resolve_env(str(data.get("bot_token", ""))),
            chat_id=str(data.get("chat_id", "")),
            parse_mode=str(data.get("parse_mode") or "Markdown"),
            poll_offset_path=str(data.get("poll_offset_path") or "telegram.offset"),
        )


class TelegramTransport:
    """Telegram Bot API client driven by long polling."""

    name = "telegram"

    def __init__(self, config: TelegramConfig, *, http_client=None):
        self.config = config
        self._http = http_client  # lazy via httpx unless injected (tests)

    # ------------------------------------------------------------------
    def send_approval_request(self, envelope: ApprovalEnvelope) -> bool:
        return self._send(format_approval_message(envelope))

    def send_completion(self, project_id: str, summary: str) -> bool:
        return self._send(format_completion_message(project_id, summary))

    def poll_responses(self) -> List[TransportResponse]:
        if not self.config.bot_token:
            return []
        offset = self._read_offset()
        params = {"timeout": 0, "allowed_updates": ["message"]}
        if offset:
            params["offset"] = offset + 1

        try:
            response = self._http_get("getUpdates", params=params)
        except Exception:
            logger.exception("telegram getUpdates failed")
            return []

        updates = response.get("result", []) or []
        if not updates:
            return []

        responses: List[TransportResponse] = []
        highest = offset
        for update in updates:
            update_id = update.get("update_id", offset)
            highest = max(highest, update_id)
            message = (update.get("message") or {}).get("text") or ""
            parsed = _parse_decision(message)
            if parsed:
                responses.append(parsed)
        if highest != offset:
            self._write_offset(highest)
        return responses

    # ------------------------------------------------------------------
    def _send(self, text: str) -> bool:
        if not self.config.bot_token or not self.config.chat_id:
            logger.warning("telegram transport missing bot_token/chat_id")
            return False
        try:
            self._http_post("sendMessage", json={
                "chat_id": self.config.chat_id,
                "text": text,
                "parse_mode": self.config.parse_mode,
            })
        except Exception:
            logger.exception("telegram sendMessage failed")
            return False
        return True

    # ------------------------------------------------------------------
    def _http_get(self, method: str, params: dict) -> dict:
        if self._http is not None:
            return self._http.get(self._url(method), params)
        import httpx

        with httpx.Client(timeout=10.0) as client:
            r = client.get(self._url(method), params=params)
            r.raise_for_status()
            return r.json()

    def _http_post(self, method: str, json: dict) -> dict:
        if self._http is not None:
            return self._http.post(self._url(method), json)
        import httpx as _httpx

        with _httpx.Client(timeout=10.0) as client:
            r = client.post(self._url(method), json=json)
            r.raise_for_status()
            return r.json()

    def _url(self, method: str) -> str:
        return f"{_BASE_URL.format(token=self.config.bot_token)}/{method}"

    def _offset_file(self) -> Path:
        rel = Path(self.config.poll_offset_path)
        if rel.is_absolute():
            return rel
        return paths.home() / rel

    def _read_offset(self) -> int:
        path = self._offset_file()
        if not path.exists():
            return 0
        try:
            return int(path.read_text(encoding="utf-8").strip() or "0")
        except (OSError, ValueError):
            return 0

    def _write_offset(self, offset: int) -> None:
        path = self._offset_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(offset), encoding="utf-8")


_APPROVE_RE = re.compile(r"^/approve\s+(\S+)(?:\s+(.*))?$", re.IGNORECASE)
_DENY_RE = re.compile(r"^/deny\s+(\S+)(?:\s+(.*))?$", re.IGNORECASE)


def _parse_decision(text: str) -> Optional[TransportResponse]:
    text = (text or "").strip()
    if not text:
        return None
    match = _APPROVE_RE.match(text)
    if match:
        return TransportResponse(
            approval_id=match.group(1),
            decision="approve",
            note=(match.group(2) or "").strip(),
        )
    match = _DENY_RE.match(text)
    if match:
        return TransportResponse(
            approval_id=match.group(1),
            decision="deny",
            note=(match.group(2) or "").strip(),
        )
    return None


__all__ = ["TelegramConfig", "TelegramTransport"]
