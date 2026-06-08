"""Tests for the ``self-update`` -> onboard wiring in the CLI command.

Onboarding after self-update mirrors the main gate's guards: real binary only,
honor OMOIKANE_NO_ONBOARD and the skip sentinel, success and non-``--check`` only.
"""
from __future__ import annotations

import argparse
import types

from omoikane.cli.commands import onboard, self_update
from omoikane.config import paths, settings
from omoikane.update import updater


def _wire(monkeypatch, *, rc, config_exists, frozen=True, skip=False, no_onboard=False):
    monkeypatch.setattr(updater, "self_update", lambda *, force, check_only: rc)
    monkeypatch.setattr(updater, "is_frozen", lambda: frozen)
    monkeypatch.setattr(settings, "config_exists", lambda: config_exists)
    monkeypatch.setattr(paths, "onboard_skip_file",
                        lambda: types.SimpleNamespace(exists=lambda: skip))
    if no_onboard:
        monkeypatch.setenv("OMOIKANE_NO_ONBOARD", "1")
    else:
        monkeypatch.delenv("OMOIKANE_NO_ONBOARD", raising=False)
    fired = []
    monkeypatch.setattr(onboard, "run", lambda args: fired.append(args) or 0)
    return fired


def _args(check=False, force=False):
    return argparse.Namespace(check=check, force=force)


def test_onboard_fires_on_success_when_config_missing(monkeypatch):
    fired = _wire(monkeypatch, rc=0, config_exists=False)
    assert self_update.run(_args()) == 0
    assert len(fired) == 1
    assert fired[0].gate_triggered is True


def test_onboard_skipped_when_config_present(monkeypatch):
    fired = _wire(monkeypatch, rc=0, config_exists=True)
    assert self_update.run(_args()) == 0
    assert fired == []


def test_onboard_skipped_on_check_only(monkeypatch):
    fired = _wire(monkeypatch, rc=0, config_exists=False)
    assert self_update.run(_args(check=True)) == 0
    assert fired == []


def test_onboard_skipped_on_failed_update(monkeypatch):
    fired = _wire(monkeypatch, rc=1, config_exists=False)
    assert self_update.run(_args()) == 1
    assert fired == []


def test_onboard_skipped_when_not_frozen(monkeypatch):
    fired = _wire(monkeypatch, rc=0, config_exists=False, frozen=False)
    assert self_update.run(_args()) == 0
    assert fired == []


def test_onboard_skipped_when_opted_out(monkeypatch):
    fired = _wire(monkeypatch, rc=0, config_exists=False, no_onboard=True)
    assert self_update.run(_args()) == 0
    assert fired == []


def test_onboard_skipped_when_skip_sentinel(monkeypatch):
    fired = _wire(monkeypatch, rc=0, config_exists=False, skip=True)
    assert self_update.run(_args()) == 0
    assert fired == []
