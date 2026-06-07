"""Per-call audit helpers used by tool handlers.

Originally lived inside ``plugins/omoikane/tools.py`` as ``_capture_origin``
and read Hermes-specific session ContextVars. The standalone Omoikane CLI
captures origin from three explicit sources (in priority order):

1. **Caller-supplied kwargs** — when the CLI knows the operator's transport
   (``omoikane start --notify telegram:12345``) it forwards
   ``origin={...}`` directly into the handler kwargs.
2. **Environment** — ``OMOIKANE_ORIGIN_PLATFORM``, ``..._CHAT_ID``,
   ``..._THREAD_ID``, ``..._USER_ID``. The legacy Hermes env names
   (``HERMES_SESSION_*``) are kept as a fallback so existing deployment
   scripts keep working.
3. **Config file** — ``[transport] default_notify_channel = "platform:chat"``
   in ``~/.omoikane/config.toml`` (loaded lazily; missing file → skip).

When none of those yield a platform, the function returns ``None`` and the
caller stores no origin block — the project simply runs without an
attached notification channel.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def _from_kwargs(kwargs: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    raw = kwargs.get("origin")
    if not isinstance(raw, dict):
        return None
    platform = (raw.get("platform") or "").strip()
    if not platform:
        return None
    return {
        "platform": platform,
        "chat_id": (raw.get("chat_id") or None) or None,
        "thread_id": (raw.get("thread_id") or None) or None,
        "user_id": (raw.get("user_id") or None) or None,
    }


def _from_env() -> Optional[Dict[str, Any]]:
    def env(key: str) -> str:
        # Prefer the OMOIKANE_* names but fall back to HERMES_SESSION_*
        # so deployments migrating off the plugin keep working.
        return (
            os.getenv(f"OMOIKANE_ORIGIN_{key}")
            or os.getenv(f"HERMES_SESSION_{key}")
            or ""
        )

    platform = env("PLATFORM").strip()
    if not platform:
        return None
    return {
        "platform": platform,
        "chat_id": env("CHAT_ID").strip() or None,
        "thread_id": env("THREAD_ID").strip() or None,
        "user_id": env("USER_ID").strip() or None,
    }


def _from_config() -> Optional[Dict[str, Any]]:
    try:
        from omoikane.config import paths
    except Exception:
        return None
    cfg_file = paths.config_file()
    if not cfg_file.exists():
        return None
    try:
        import tomllib

        with open(cfg_file, "rb") as f:
            cfg = tomllib.load(f) or {}
    except Exception as exc:
        logger.warning("Failed to read %s: %s", cfg_file, exc)
        return None
    transport = cfg.get("transport") or {}
    fallback = transport.get("default_notify_channel")
    if not isinstance(fallback, str) or not fallback.strip():
        return None
    raw = fallback.strip()
    if ":" in raw:
        platform, chat_id = raw.split(":", 1)
    else:
        platform, chat_id = raw, ""
    platform = platform.strip()
    if not platform:
        return None
    return {
        "platform": platform,
        "chat_id": chat_id.strip() or None,
        "thread_id": None,
        "user_id": None,
    }


def capture_origin(kwargs: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """Best-effort origin capture for a freshly-started project.

    Priority: explicit kwargs ``origin`` dict → env vars → config file.
    Returns a dict shaped like the legacy plugin so the rest of the book
    layer needs no changes, or ``None`` if no usable origin exists.
    """
    kwargs = kwargs or {}
    found = _from_kwargs(kwargs) or _from_env() or _from_config()
    if not found:
        return None
    found["captured_at"] = datetime.now(timezone.utc).isoformat()
    return found
