"""Tests for the ``delete-project`` command's daemon handling and guards."""

import argparse

import pytest

from omoikane.cli.commands import delete as delete_cmd
from omoikane.orchestrator.daemon import DaemonStatus


def _args(pid="proj-x", force=False):
    return argparse.Namespace(project_id=pid, force=force)


@pytest.fixture
def patched(monkeypatch):
    """Stub the daemon + store so we exercise only the command's branching."""
    calls = {"stop": [], "delete": []}

    def fake_status(pid):
        return calls["status"]

    def fake_stop(pid, *, timeout=10.0, force=False):
        calls["stop"].append((pid, force))
        return calls["stop_ok"]

    def fake_delete(pid):
        calls["delete"].append(pid)
        return True

    monkeypatch.setattr(delete_cmd._daemon, "status", fake_status)
    monkeypatch.setattr(
        delete_cmd._daemon.OrchestratorDaemon, "stop", staticmethod(fake_stop)
    )
    monkeypatch.setattr(delete_cmd._store, "project_exists", lambda pid: True)
    monkeypatch.setattr(delete_cmd._store, "delete_project", fake_delete)
    # Default happy-path knobs; individual tests override.
    calls["status"] = DaemonStatus("proj-x", None, "missing")
    calls["stop_ok"] = True
    return calls


def test_running_without_force_refuses_and_keeps_daemon(patched, capsys):
    patched["status"] = DaemonStatus("proj-x", 4242, "running")
    rc = delete_cmd.run(_args(force=False))
    assert rc == 1
    assert patched["stop"] == []      # daemon untouched
    assert patched["delete"] == []    # nothing deleted
    assert "stop it first" in capsys.readouterr().err


def test_running_with_force_stops_then_deletes(patched, capsys):
    patched["status"] = DaemonStatus("proj-x", 4242, "running")
    rc = delete_cmd.run(_args(force=True))
    assert rc == 0
    assert patched["stop"] == [("proj-x", False)]  # SIGTERM, not SIGKILL
    assert patched["delete"] == ["proj-x"]
    assert "stopped daemon" in capsys.readouterr().err


def test_force_stop_failure_aborts_before_delete(patched, capsys):
    patched["status"] = DaemonStatus("proj-x", 4242, "running")
    patched["stop_ok"] = False
    rc = delete_cmd.run(_args(force=True))
    assert rc == 1
    assert patched["stop"] == [("proj-x", False)]
    assert patched["delete"] == []  # never reached deletion
    assert "could not stop" in capsys.readouterr().err


def test_unreachable_refused_even_with_force(patched, capsys):
    patched["status"] = DaemonStatus("proj-x", 4242, "unreachable")
    rc = delete_cmd.run(_args(force=True))
    assert rc == 1
    assert patched["stop"] == []   # never tried to signal someone else's process
    assert patched["delete"] == []
    assert "unreachable" in capsys.readouterr().err


def test_no_daemon_force_deletes(patched):
    patched["status"] = DaemonStatus("proj-x", None, "missing")
    rc = delete_cmd.run(_args(force=True))
    assert rc == 0
    assert patched["stop"] == []
    assert patched["delete"] == ["proj-x"]
