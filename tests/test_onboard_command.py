"""Tests for ``omoikane onboard`` — drives run() with a scripted fake tty."""
from __future__ import annotations

import argparse
import io

from omoikane.cli.commands import onboard
from omoikane.config import paths, settings, toml_writer


def _args(reconfigure=False, no_supervisor=False, gate_triggered=False):
    return argparse.Namespace(
        reconfigure=reconfigure, no_supervisor=no_supervisor,
        gate_triggered=gate_triggered,
    )


def _spy_write(monkeypatch):
    captured = {}

    def fake_write(data, path=None):
        captured["data"] = data
        return paths.config_file()

    monkeypatch.setattr("omoikane.config.toml_writer.write_config", fake_write)
    return captured


def _feed(monkeypatch, lines: str):
    monkeypatch.setattr(onboard, "_open_tty", lambda: io.StringIO(lines))


def _no_supervisor_side_effects(monkeypatch):
    installed, uninstalled = [], []
    monkeypatch.setattr(onboard, "_install_supervisor", lambda s: installed.append(s))
    monkeypatch.setattr(onboard, "_uninstall_supervisor", lambda: uninstalled.append(True))
    return installed, uninstalled


def _clear_secret_env(monkeypatch):
    for k in ("OMOIKANE_API_KEY", "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY",
              "TELEGRAM_BOT_TOKEN", "SLACK_WEBHOOK_URL"):
        monkeypatch.delenv(k, raising=False)


def test_idempotent_when_configured(temp_omoikane_home, monkeypatch, capsys):
    toml_writer.write_config({"model": {"id": "m"}})
    captured = _spy_write(monkeypatch)
    monkeypatch.setattr(onboard, "_open_tty",
                        lambda: (_ for _ in ()).throw(AssertionError("prompted")))
    rc = onboard.run(_args(reconfigure=False))
    assert rc == 0
    assert "data" not in captured
    assert "Already configured" in capsys.readouterr().out


def test_non_interactive_skips(temp_omoikane_home, monkeypatch, capsys):
    captured = _spy_write(monkeypatch)
    monkeypatch.setattr(onboard, "_open_tty", lambda: None)
    rc = onboard.run(_args())
    assert rc == 0
    assert "data" not in captured
    assert "no interactive terminal" in capsys.readouterr().err


def test_happy_path_stdout_no_supervisor(temp_omoikane_home, monkeypatch):
    _clear_secret_env(monkeypatch)
    captured = _spy_write(monkeypatch)
    installed, _ = _no_supervisor_side_effects(monkeypatch)
    # api / provider / model / backends / supervisor?(n) / confirm(y)
    _feed(monkeypatch, "sk-test\n\n\nstdout\nn\ny\n")
    rc = onboard.run(_args())
    assert rc == 0
    data = captured["data"]
    assert data["auth"]["api_key"] == "sk-test"
    assert data["model"] == {"provider": "openrouter", "id": "openrouter/owl-alpha"}
    assert data["transport"]["backends"] == ["stdout"]
    assert "supervisor" not in data
    assert installed == []


def test_telegram_valid_writes_subtable(temp_omoikane_home, monkeypatch):
    _clear_secret_env(monkeypatch)
    captured = _spy_write(monkeypatch)
    _no_supervisor_side_effects(monkeypatch)
    # api / prov / model / backends=telegram / token / chat / supervisor?(n) / confirm(y)
    _feed(monkeypatch, "sk\n\n\ntelegram\n123:abc\n-100\nn\ny\n")
    rc = onboard.run(_args())
    assert rc == 0
    data = captured["data"]
    assert data["transport"]["backends"] == ["telegram"]
    assert data["transport"]["telegram"] == {"bot_token": "123:abc", "chat_id": "-100"}


def test_telegram_blank_chat_is_dropped(temp_omoikane_home, monkeypatch, capsys):
    _clear_secret_env(monkeypatch)  # TELEGRAM_BOT_TOKEN unset -> env: default resolves empty
    captured = _spy_write(monkeypatch)
    _no_supervisor_side_effects(monkeypatch)
    # backends=telegram, token blank (-> env default, unset), chat blank -> dropped
    _feed(monkeypatch, "sk\n\n\ntelegram\n\n\nn\ny\n")
    rc = onboard.run(_args())
    assert rc == 0
    data = captured["data"]
    assert data["transport"]["backends"] == ["stdout"]
    assert "telegram" not in data["transport"]
    assert "dropping it" in capsys.readouterr().err


def test_confirm_no_aborts_without_writing(temp_omoikane_home, monkeypatch, capsys):
    _clear_secret_env(monkeypatch)
    captured = _spy_write(monkeypatch)
    _no_supervisor_side_effects(monkeypatch)
    _feed(monkeypatch, "sk\n\n\nstdout\nn\nn\n")  # confirm = n
    rc = onboard.run(_args())
    assert rc == 0
    assert "data" not in captured
    assert "nothing written" in capsys.readouterr().err
    # Declining the write must NOT re-trap the user on the next command.
    assert paths.onboard_skip_file().exists()


def test_gate_triggered_supervisor_defaults_off(temp_omoikane_home, monkeypatch):
    _clear_secret_env(monkeypatch)
    captured = _spy_write(monkeypatch)
    installed, _ = _no_supervisor_side_effects(monkeypatch)
    # supervisor answer BLANK -> default. gate_triggered => default False.
    _feed(monkeypatch, "sk\n\n\nstdout\n\ny\n")
    rc = onboard.run(_args(gate_triggered=True))
    assert rc == 0
    assert "supervisor" not in captured["data"]
    assert installed == []


def test_reconfigure_keeps_prior_key_on_blank(temp_omoikane_home, monkeypatch):
    _clear_secret_env(monkeypatch)
    toml_writer.write_config({
        "auth": {"api_key": "old"},
        "model": {"provider": "prov", "id": "custom/model"},
        "transport": {"backends": ["stdout"]},
    })
    captured = _spy_write(monkeypatch)
    _no_supervisor_side_effects(monkeypatch)
    _feed(monkeypatch, "\n\n\n\nn\ny\n")  # all blank, supervisor n, confirm y
    rc = onboard.run(_args(reconfigure=True))
    assert rc == 0
    data = captured["data"]
    assert data["auth"]["api_key"] == "old"
    assert data["model"] == {"provider": "prov", "id": "custom/model"}
    assert data["transport"]["backends"] == ["stdout"]


def test_reconfigure_decline_supervisor_uninstalls(temp_omoikane_home, monkeypatch):
    _clear_secret_env(monkeypatch)
    toml_writer.write_config({
        "model": {"provider": "p", "id": "m"},
        "transport": {"backends": ["stdout"]},
        "supervisor": {"schedule": "*/5 * * * *"},
    })
    _, uninstalled = _no_supervisor_side_effects(monkeypatch)
    captured = _spy_write(monkeypatch)
    _feed(monkeypatch, "\n\n\nstdout\nn\ny\n")  # supervisor n
    rc = onboard.run(_args(reconfigure=True))
    assert rc == 0
    assert uninstalled == [True]
    # The stale [supervisor].schedule must not survive in the written config.
    assert "supervisor" not in captured["data"]


def test_reconfigure_drops_stale_telegram_subtable(temp_omoikane_home, monkeypatch):
    _clear_secret_env(monkeypatch)
    toml_writer.write_config({
        "model": {"provider": "p", "id": "m"},
        "transport": {
            "backends": ["telegram"],
            "telegram": {"bot_token": "t", "chat_id": "c"},
        },
    })
    captured = _spy_write(monkeypatch)
    _no_supervisor_side_effects(monkeypatch)
    _feed(monkeypatch, "\n\n\nstdout\nn\ny\n")  # switch to stdout
    rc = onboard.run(_args(reconfigure=True))
    assert rc == 0
    assert "telegram" not in captured["data"]["transport"]


def test_ctrl_c_writes_skip_sentinel(temp_omoikane_home, monkeypatch, capsys):
    class _Boom:
        def readline(self):
            raise KeyboardInterrupt
        def isatty(self):
            return False
        def close(self):
            pass

    monkeypatch.setattr(onboard, "_open_tty", lambda: _Boom())
    captured = _spy_write(monkeypatch)
    rc = onboard.run(_args())
    assert rc == 0
    assert "data" not in captured
    assert not settings.config_exists()
    assert paths.onboard_skip_file().exists()
    assert "Setup skipped" in capsys.readouterr().err


def test_completed_onboard_clears_skip_sentinel(temp_omoikane_home, monkeypatch):
    _clear_secret_env(monkeypatch)
    paths.ensure_home()
    paths.onboard_skip_file().write_text("skipped\n")
    # Real write so config_exists() flips and the sentinel-clear path runs.
    _no_supervisor_side_effects(monkeypatch)
    _feed(monkeypatch, "sk\n\n\nstdout\nn\ny\n")
    rc = onboard.run(_args())
    assert rc == 0
    assert settings.config_exists()
    assert not paths.onboard_skip_file().exists()
