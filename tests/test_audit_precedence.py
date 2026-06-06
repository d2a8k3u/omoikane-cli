"""Origin precedence for :func:`omoikane.tools.audit.capture_origin`.

The existing ``test_origin_capture.py`` suite exercises the env→config tiers
through the ``project_start`` handler, but never the full three-tier
precedence ladder (kwargs > env > config) directly against
``capture_origin``. These tests pin that ladder and the
``HERMES_SESSION_*`` env fallback.
"""
from __future__ import annotations

from omoikane.config import paths
from omoikane.tools.audit import capture_origin

_ORIGIN_ENV_KEYS = ("PLATFORM", "CHAT_ID", "THREAD_ID", "USER_ID")


def _clear_origin_env(monkeypatch):
    for key in _ORIGIN_ENV_KEYS:
        monkeypatch.delenv(f"OMOIKANE_ORIGIN_{key}", raising=False)
        monkeypatch.delenv(f"HERMES_SESSION_{key}", raising=False)


def _write_config(channel: str) -> None:
    cfg_file = paths.config_file()
    cfg_file.parent.mkdir(parents=True, exist_ok=True)
    cfg_file.write_text(
        "[transport]\n"
        f'default_notify_channel = "{channel}"\n'
    )


def test_kwargs_origin_wins_over_env_and_config(monkeypatch, temp_hermes_home):
    """An explicit kwargs ``origin`` dict beats both env and config."""
    _clear_origin_env(monkeypatch)
    monkeypatch.setenv("OMOIKANE_ORIGIN_PLATFORM", "telegram")
    monkeypatch.setenv("OMOIKANE_ORIGIN_CHAT_ID", "999")
    _write_config("discord:888")

    result = capture_origin({"origin": {"platform": "slack", "chat_id": "C123"}})

    assert result is not None
    assert result["platform"] == "slack"
    assert result["chat_id"] == "C123"
    assert result["captured_at"]


def test_env_beats_config(monkeypatch, temp_hermes_home):
    """OMOIKANE_ORIGIN_* env vars beat the config default_notify_channel."""
    _clear_origin_env(monkeypatch)
    monkeypatch.setenv("OMOIKANE_ORIGIN_PLATFORM", "telegram")
    monkeypatch.setenv("OMOIKANE_ORIGIN_CHAT_ID", "555")
    _write_config("discord:888")

    result = capture_origin({})

    assert result is not None
    assert result["platform"] == "telegram"
    assert result["chat_id"] == "555"


def test_hermes_session_env_is_fallback_when_omoikane_absent(monkeypatch, temp_hermes_home):
    """HERMES_SESSION_* still resolves inside the env tier (beats config)."""
    _clear_origin_env(monkeypatch)
    monkeypatch.setenv("HERMES_SESSION_PLATFORM", "telegram")
    monkeypatch.setenv("HERMES_SESSION_CHAT_ID", "777")
    _write_config("discord:888")

    result = capture_origin({})

    assert result is not None
    assert result["platform"] == "telegram"
    assert result["chat_id"] == "777"


def test_returns_none_when_nothing_set(monkeypatch, temp_hermes_home):
    """No kwargs, no env (OMOIKANE or HERMES), no config → None."""
    _clear_origin_env(monkeypatch)
    # temp home is fresh; no config.toml exists.
    assert not paths.config_file().exists()

    assert capture_origin({}) is None
