"""Config load + value resolution with ENV-over-config precedence.

Consolidates the scattered "read config.toml, fall back to env" logic. The
precedence everywhere is: **CLI flag > env var > config.toml > hardcoded
default** (the CLI-flag step happens in each command's ``run``).

The ``env:VAR`` indirection matches the transport convention
(:func:`omoikane.transport.telegram._resolve_env`): a config value of
``"env:FOO"`` resolves to ``os.environ["FOO"]``.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "openrouter/owl-alpha"
_DEFAULT_PROVIDER = "openrouter"
_API_KEY_ENV = ("OMOIKANE_API_KEY", "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY")


def load_config() -> dict:
    """Read ``~/.omoikane/config.toml`` once. Returns ``{}`` if missing/bad."""
    try:
        import tomllib
    except Exception:
        return {}
    from omoikane.config import paths

    path = paths.config_file()
    if not path.exists():
        return {}
    try:
        with open(path, "rb") as fh:
            return tomllib.load(fh)
    except Exception:
        logger.exception("failed to load %s", path)
        return {}


def config_exists() -> bool:
    """True when ``config.toml`` is present (drives the onboarding gate)."""
    from omoikane.config import paths

    return paths.config_file().exists()


def _resolve_env(value: str) -> str:
    """Resolve the ``env:VAR`` indirection; pass literals through unchanged."""
    if value.startswith("env:"):
        return os.environ.get(value[4:], "")
    return value


def resolve_api_key(config: Optional[dict] = None) -> Optional[str]:
    """ENV (``OMOIKANE_API_KEY`` → ``OPENROUTER_API_KEY`` → ``ANTHROPIC_API_KEY``)
    then ``[auth].api_key`` (with ``env:`` indirection). ``None`` if unset."""
    for key in _API_KEY_ENV:
        if os.environ.get(key):
            return os.environ[key]
    if config is None:
        config = load_config()
    raw = str((config.get("auth", {}) or {}).get("api_key", "") or "")
    resolved = _resolve_env(raw)
    return resolved or None


def resolve_model(config: Optional[dict] = None) -> str:
    """``OMOIKANE_MODEL`` → ``[model].id`` → ``"openrouter/owl-alpha"``."""
    env = os.environ.get("OMOIKANE_MODEL")
    if env:
        return env
    if config is None:
        config = load_config()
    return str((config.get("model", {}) or {}).get("id") or _DEFAULT_MODEL)


def resolve_provider(config: Optional[dict] = None) -> str:
    """``OMOIKANE_PROVIDER`` → ``[model].provider`` → ``"openrouter"``."""
    env = os.environ.get("OMOIKANE_PROVIDER")
    if env:
        return env
    if config is None:
        config = load_config()
    return str((config.get("model", {}) or {}).get("provider") or _DEFAULT_PROVIDER)
