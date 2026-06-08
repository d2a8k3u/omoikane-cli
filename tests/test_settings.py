"""Tests for config load + ENV-over-config resolution."""
from __future__ import annotations

from omoikane.config import settings, toml_writer

_KEYS = ("OMOIKANE_API_KEY", "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY")


def _clear_env(monkeypatch):
    for k in (*_KEYS, "OMOIKANE_MODEL", "OMOIKANE_PROVIDER"):
        monkeypatch.delenv(k, raising=False)


def test_config_exists(temp_omoikane_home):
    assert settings.config_exists() is False
    toml_writer.write_config({"model": {"id": "m"}})
    assert settings.config_exists() is True


def test_api_key_env_beats_config(temp_omoikane_home, monkeypatch):
    _clear_env(monkeypatch)
    toml_writer.write_config({"auth": {"api_key": "from-config"}})
    monkeypatch.setenv("OMOIKANE_API_KEY", "from-env")
    assert settings.resolve_api_key() == "from-env"


def test_api_key_config_when_env_absent(temp_omoikane_home, monkeypatch):
    _clear_env(monkeypatch)
    toml_writer.write_config({"auth": {"api_key": "from-config"}})
    assert settings.resolve_api_key() == "from-config"


def test_api_key_env_indirection(temp_omoikane_home, monkeypatch):
    _clear_env(monkeypatch)
    toml_writer.write_config({"auth": {"api_key": "env:CUSTOM_KEY"}})
    monkeypatch.setenv("CUSTOM_KEY", "indirected")
    assert settings.resolve_api_key() == "indirected"


def test_api_key_none_when_unset(temp_omoikane_home, monkeypatch):
    _clear_env(monkeypatch)
    assert settings.resolve_api_key() is None


def test_model_precedence(temp_omoikane_home, monkeypatch):
    _clear_env(monkeypatch)
    assert settings.resolve_model() == "openrouter/owl-alpha"  # hardcoded default
    toml_writer.write_config({"model": {"id": "cfg/model"}})
    assert settings.resolve_model() == "cfg/model"  # config beats default
    monkeypatch.setenv("OMOIKANE_MODEL", "env/model")
    assert settings.resolve_model() == "env/model"  # env beats config


def test_provider_precedence(temp_omoikane_home, monkeypatch):
    _clear_env(monkeypatch)
    assert settings.resolve_provider() == "openrouter"
    toml_writer.write_config({"model": {"provider": "cfgprov"}})
    assert settings.resolve_provider() == "cfgprov"
    monkeypatch.setenv("OMOIKANE_PROVIDER", "envprov")
    assert settings.resolve_provider() == "envprov"
