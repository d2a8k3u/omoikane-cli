"""Slack transport via Incoming Webhook (outbound) + Events API (inbound).

Only the outbound half is implemented — Slack incoming webhooks are
trivial and require no auth handshake beyond holding the URL. Inbound
responses
require either the Events API (HTTPS reachable from Slack) or a
periodic ``conversations.history`` poll; the public surface mirrors
:class:`omoikane.transport.telegram.TelegramTransport` so swapping is
just a config edit.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import List

from .base import (
    ApprovalEnvelope,
    TransportResponse,
    format_approval_message,
    format_completion_message,
)

logger = logging.getLogger(__name__)


def _resolve_env(value: str) -> str:
    if value.startswith("env:"):
        return os.environ.get(value[4:], "")
    return value


@dataclass
class SlackConfig:
    webhook_url: str

    @classmethod
    def from_dict(cls, data: dict) -> "SlackConfig":
        return cls(webhook_url=_resolve_env(str(data.get("webhook_url", ""))))


class SlackTransport:
    name = "slack"

    def __init__(self, config: SlackConfig, *, http_client=None):
        self.config = config
        self._http = http_client

    def send_approval_request(self, envelope: ApprovalEnvelope) -> bool:
        return self._send(format_approval_message(envelope))

    def send_completion(self, project_id: str, summary: str) -> bool:
        return self._send(format_completion_message(project_id, summary))

    def poll_responses(self) -> List[TransportResponse]:
        # Inbound responses require either the Events API webhook or
        # conversations.history polling with a bot token. This transport
        # is write-only; operators reply through the CLI or TUI.
        return []

    # ------------------------------------------------------------------
    def _send(self, text: str) -> bool:
        if not self.config.webhook_url:
            logger.warning("slack transport missing webhook_url")
            return False
        try:
            if self._http is not None:
                self._http.post(self.config.webhook_url, json={"text": text})
            else:
                import httpx

                with httpx.Client(timeout=10.0) as client:
                    r = client.post(self.config.webhook_url, json={"text": text})
                    r.raise_for_status()
        except Exception:
            logger.exception("slack webhook POST failed")
            return False
        return True


__all__ = ["SlackConfig", "SlackTransport"]
