"""Supervisor install renderers — assert the on-disk content shape."""
from __future__ import annotations

from pathlib import Path

from omoikane.supervisor import install as _install


def test_launchd_plist_content_mentions_supervisor_tick():
    out = _install.render_launchd_plist(
        binary="/usr/local/bin/omoikane",
        schedule="*/10 * * * *",
        log_dir=Path("/tmp/omoikane-logs"),
    )
    assert "<key>Label</key><string>com.omoikane.supervisor</string>" in out
    assert "supervisor tick" in out
    assert "<integer>600</integer>" in out  # 10 minutes


def test_systemd_service_runs_supervisor_tick():
    out = _install.render_systemd_service("/usr/local/bin/omoikane")
    assert "ExecStart=/usr/local/bin/omoikane supervisor tick" in out
    assert "Type=oneshot" in out


def test_systemd_timer_uses_minute_shorthand():
    out = _install.render_systemd_timer("*/15 * * * *")
    assert "OnUnitActiveSec=900s" in out
    assert "omoikane-supervisor.service" in out


def test_cron_line_contains_log_path():
    line = _install.render_cron_line(
        binary="/usr/local/bin/omoikane",
        schedule="*/3 * * * *",
        log_dir=Path("/tmp"),
    )
    assert "*/3 * * * *" in line
    assert "supervisor tick" in line
    assert ">> /tmp/supervisor.log" in line


def test_dry_run_install_does_not_touch_disk(tmp_path, monkeypatch):
    # Force the launchd path into the temp tree so a real install path
    # cannot accidentally exist on macOS.
    monkeypatch.setattr(_install, "launchd_plist_path",
                        lambda: tmp_path / "launchd" / "test.plist")
    monkeypatch.setattr(_install, "systemd_service_path",
                        lambda: tmp_path / "systemd" / "svc")
    monkeypatch.setattr(_install, "systemd_timer_path",
                        lambda: tmp_path / "systemd" / "timer")

    for backend in ("launchd", "systemd", "cron"):
        result = _install.install(
            schedule="*/5 * * * *",
            log_dir=tmp_path / "logs",
            dry_run=True,
            backend=backend,
        )
        assert result.backend == backend
        if backend == "launchd":
            assert not (tmp_path / "launchd" / "test.plist").exists()
        if backend == "systemd":
            assert not (tmp_path / "systemd" / "svc").exists()
            assert not (tmp_path / "systemd" / "timer").exists()
