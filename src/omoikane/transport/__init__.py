"""Transport selection + config loader.

``transport.load_from_config`` reads the ``[transport]`` section of
``~/.omoikane/config.toml`` and returns a list of configured backends.
Multiple backends fan out (the supervisor pushes the same approval to
each); responses from every backend are merged on poll.

Example configuration::

    [transport]
    backends = ["stdout", "telegram"]

    [transport.telegram]
    bot_token = "env:TELEGRAM_BOT_TOKEN"
    chat_id   = "-100123456789"

    [transport.slack]
    webhook_url = "env:SLACK_WEBHOOK_URL"
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional

from .base import (
    ApprovalEnvelope,
    Transport,
    TransportResponse,
    format_approval_message,
    format_completion_message,
)
from .slack import SlackConfig, SlackTransport
from .stdout import StdoutTransport
from .telegram import TelegramConfig, TelegramTransport

logger = logging.getLogger(__name__)


def build_transport(backend: str, settings: dict) -> Optional[Transport]:
    """Instantiate one transport by name. Returns ``None`` on unknown backend."""
    name = (backend or "").lower()
    if name == "stdout":
        return StdoutTransport()
    if name == "telegram":
        return TelegramTransport(TelegramConfig.from_dict(settings or {}))
    if name == "slack":
        return SlackTransport(SlackConfig.from_dict(settings or {}))
    logger.warning("unknown transport backend: %s", backend)
    return None


def load_from_config(config: Optional[dict] = None) -> List[Transport]:
    """Read ``[transport]`` and build every backend listed in ``backends``.

    ``config`` is the parsed TOML dict; ``None`` causes the loader to
    read ``~/.omoikane/config.toml`` itself (skipped if missing).
    """
    if config is None:
        config = _load_config_file()
    section = (config or {}).get("transport", {}) or {}
    backends = section.get("backends") or ["stdout"]
    transports: List[Transport] = []
    for backend in backends:
        transport = build_transport(str(backend), section.get(str(backend)))
        if transport is not None:
            transports.append(transport)
    return transports


def _load_config_file() -> dict:
    try:
        import tomllib
    except Exception:
        return {}
    from omoikane.config import paths

    path: Path = paths.config_file()
    if not path.exists():
        return {}
    try:
        with open(path, "rb") as fh:
            return tomllib.load(fh)
    except Exception:
        logger.exception("failed to load %s", path)
        return {}


__all__ = [
    "ApprovalEnvelope",
    "SlackConfig",
    "SlackTransport",
    "StdoutTransport",
    "TelegramConfig",
    "TelegramTransport",
    "Transport",
    "TransportResponse",
    "build_transport",
    "format_approval_message",
    "format_completion_message",
    "load_from_config",
]
