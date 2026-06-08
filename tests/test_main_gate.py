"""Tests for the auto-onboarding gate in cli.main.

Note: the existing command tests call each command's ``run()`` directly and
never go through ``main()``/dispatch, so a missing config.toml under
``temp_omoikane_home`` never triggers this gate for them.
"""
from __future__ import annotations

import types

from omoikane.cli import main
from omoikane.config import paths, settings
from omoikane.update import updater


def _set(monkeypatch, *, frozen, config, isatty, skip=False, no_onboard=False):
    monkeypatch.setattr(updater, "is_frozen", lambda: frozen)
    monkeypatch.setattr(settings, "config_exists", lambda: config)
    monkeypatch.setattr(paths, "onboard_skip_file",
                        lambda: types.SimpleNamespace(exists=lambda: skip))
    monkeypatch.setattr(main.sys, "stdin", types.SimpleNamespace(isatty=lambda: isatty))
    if no_onboard:
        monkeypatch.setenv("OMOIKANE_NO_ONBOARD", "1")
    else:
        monkeypatch.delenv("OMOIKANE_NO_ONBOARD", raising=False)


def test_excludes_onboard_and_self_update(monkeypatch):
    _set(monkeypatch, frozen=True, config=False, isatty=True)
    assert main._should_auto_onboard("onboard") is False
    assert main._should_auto_onboard("self-update") is False


def test_false_when_configured(monkeypatch):
    _set(monkeypatch, frozen=True, config=True, isatty=True)
    assert main._should_auto_onboard("start") is False


def test_false_when_skip_sentinel_present(monkeypatch):
    _set(monkeypatch, frozen=True, config=False, isatty=True, skip=True)
    assert main._should_auto_onboard("start") is False


def test_false_when_not_frozen(monkeypatch):
    _set(monkeypatch, frozen=False, config=False, isatty=True)
    assert main._should_auto_onboard("start") is False


def test_false_when_no_onboard_env(monkeypatch):
    _set(monkeypatch, frozen=True, config=False, isatty=True, no_onboard=True)
    assert main._should_auto_onboard("start") is False


def test_false_for_empty_command(monkeypatch):
    _set(monkeypatch, frozen=True, config=False, isatty=True)
    assert main._should_auto_onboard("") is False


def test_true_when_frozen_unconfigured_tty(monkeypatch):
    _set(monkeypatch, frozen=True, config=False, isatty=True)
    assert main._should_auto_onboard("start") is True
