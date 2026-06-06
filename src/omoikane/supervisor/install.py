"""Cross-platform installer for the recurring supervisor schedule.

Three back-ends are supported, picked by ``sys.platform`` with sensible
fallbacks:

- macOS (``darwin``)  → user-level launchd plist
- Linux + systemd user → ``omoikane-supervisor.{service,timer}``
- Anything else        → ``crontab`` entry (the universal escape hatch)

The supervisor configuration lives in ``~/.omoikane/config.toml`` under
``[supervisor]``; the install command reads the schedule from there but
also accepts ``--schedule`` on the CLI for one-off overrides.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# Locations
# ----------------------------------------------------------------------

LAUNCHD_LABEL = "com.omoikane.supervisor"
SYSTEMD_UNIT = "omoikane-supervisor"


def launchd_plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"


def systemd_service_path() -> Path:
    return Path.home() / ".config" / "systemd" / "user" / f"{SYSTEMD_UNIT}.service"


def systemd_timer_path() -> Path:
    return Path.home() / ".config" / "systemd" / "user" / f"{SYSTEMD_UNIT}.timer"


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def _resolve_binary() -> str:
    binary = shutil.which("omoikane")
    if binary:
        return binary
    # Fall back to the running interpreter + module so installs from an
    # editable source tree still work without symlinking ``omoikane``.
    return f"{sys.executable} -m omoikane.cli.main"


def _cron_schedule_to_seconds(schedule: str) -> int:
    """Best-effort cron → ``StartInterval`` translation for launchd.

    Only handles the ``*/N`` shorthand in the minute slot since that
    covers every supervisor cadence the project documents (1-30 min).
    Anything else falls back to 300 seconds — the launchd plist always
    accepts being too eager, and the supervisor tick is cheap.
    """
    parts = schedule.split()
    if not parts:
        return 300
    minute = parts[0]
    if minute.startswith("*/") and minute[2:].isdigit():
        return max(60, int(minute[2:]) * 60)
    if minute.isdigit():
        return max(60, int(minute) * 60)
    return 300


# ----------------------------------------------------------------------
# Renderers — kept side-effect-free so tests can assert on the content.
# ----------------------------------------------------------------------

def render_launchd_plist(binary: str, schedule: str, log_dir: Path) -> str:
    interval = _cron_schedule_to_seconds(schedule)
    stdout_log = log_dir / "supervisor.log"
    stderr_log = log_dir / "supervisor.err"
    return f"""<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<!DOCTYPE plist PUBLIC \"-//Apple//DTD PLIST 1.0//EN\"
  \"http://www.apple.com/DTDs/PropertyList-1.0.dtd\">
<plist version=\"1.0\">
<dict>
    <key>Label</key><string>{LAUNCHD_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/sh</string>
        <string>-c</string>
        <string>{binary} supervisor tick</string>
    </array>
    <key>StartInterval</key><integer>{interval}</integer>
    <key>RunAtLoad</key><false/>
    <key>StandardOutPath</key><string>{stdout_log}</string>
    <key>StandardErrorPath</key><string>{stderr_log}</string>
</dict>
</plist>
"""


def render_systemd_service(binary: str) -> str:
    return f"""[Unit]
Description=Omoikane supervisor — single tick

[Service]
Type=oneshot
ExecStart={binary} supervisor tick
"""


def render_systemd_timer(schedule: str) -> str:
    # Translate the cron 'minute' slot into a sensible OnUnitActiveSec.
    interval_seconds = _cron_schedule_to_seconds(schedule)
    return f"""[Unit]
Description=Omoikane supervisor recurring trigger

[Timer]
OnBootSec=30s
OnUnitActiveSec={interval_seconds}s
Unit={SYSTEMD_UNIT}.service

[Install]
WantedBy=timers.target
"""


def render_cron_line(binary: str, schedule: str, log_dir: Path) -> str:
    log = log_dir / "supervisor.log"
    return f"{schedule} {binary} supervisor tick >> {log} 2>&1"


# ----------------------------------------------------------------------
# Install / uninstall
# ----------------------------------------------------------------------

@dataclass
class InstallResult:
    backend: str
    paths: List[Path]
    note: Optional[str] = None


def detect_backend() -> str:
    if sys.platform == "darwin":
        return "launchd"
    if sys.platform.startswith("linux") and (Path.home() / ".config" / "systemd").exists():
        return "systemd"
    if sys.platform.startswith("linux"):
        return "systemd"
    return "cron"


def install(
    *,
    schedule: str = "*/5 * * * *",
    log_dir: Path,
    dry_run: bool = False,
    backend: Optional[str] = None,
) -> InstallResult:
    log_dir.mkdir(parents=True, exist_ok=True)
    binary = _resolve_binary()
    backend = backend or detect_backend()

    if backend == "launchd":
        return _install_launchd(binary, schedule, log_dir, dry_run=dry_run)
    if backend == "systemd":
        return _install_systemd(binary, schedule, dry_run=dry_run)
    return _install_cron(binary, schedule, log_dir, dry_run=dry_run)


def uninstall(backend: Optional[str] = None) -> InstallResult:
    backend = backend or detect_backend()
    if backend == "launchd":
        path = launchd_plist_path()
        if path.exists():
            try:
                subprocess.run(["launchctl", "unload", str(path)], check=False)
            except FileNotFoundError:
                pass
            path.unlink()
        return InstallResult(backend, [path], None)
    if backend == "systemd":
        removed: List[Path] = []
        for p in (systemd_timer_path(), systemd_service_path()):
            if p.exists():
                p.unlink()
                removed.append(p)
        try:
            subprocess.run(["systemctl", "--user", "disable", "--now",
                            f"{SYSTEMD_UNIT}.timer"], check=False)
            subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
        except FileNotFoundError:
            pass
        return InstallResult(backend, removed, None)
    return _uninstall_cron()


def _install_launchd(binary: str, schedule: str, log_dir: Path, *, dry_run: bool) -> InstallResult:
    path = launchd_plist_path()
    content = render_launchd_plist(binary, schedule, log_dir)
    if dry_run:
        return InstallResult("launchd", [path], "dry-run: not written")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    note = None
    try:
        subprocess.run(["launchctl", "unload", str(path)], check=False, capture_output=True)
        subprocess.run(["launchctl", "load", str(path)], check=True, capture_output=True)
    except FileNotFoundError:
        note = "launchctl not found; plist written but not loaded"
    except subprocess.CalledProcessError as exc:
        note = f"launchctl load failed: {exc.stderr.decode(errors='replace').strip()}"
    return InstallResult("launchd", [path], note)


def _install_systemd(binary: str, schedule: str, *, dry_run: bool) -> InstallResult:
    service_path = systemd_service_path()
    timer_path = systemd_timer_path()
    service = render_systemd_service(binary)
    timer = render_systemd_timer(schedule)
    if dry_run:
        return InstallResult("systemd", [service_path, timer_path], "dry-run: not written")
    service_path.parent.mkdir(parents=True, exist_ok=True)
    service_path.write_text(service)
    timer_path.write_text(timer)
    note = None
    try:
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
        subprocess.run(
            ["systemctl", "--user", "enable", "--now", f"{SYSTEMD_UNIT}.timer"],
            check=True, capture_output=True,
        )
    except FileNotFoundError:
        note = "systemctl not found; units written but not enabled"
    except subprocess.CalledProcessError as exc:
        note = f"systemctl enable failed: {exc.stderr.decode(errors='replace').strip()}"
    return InstallResult("systemd", [service_path, timer_path], note)


def _install_cron(binary: str, schedule: str, log_dir: Path, *, dry_run: bool) -> InstallResult:
    line = render_cron_line(binary, schedule, log_dir)
    if dry_run:
        return InstallResult("cron", [Path("crontab")], f"dry-run line: {line}")
    current, _ = _read_crontab()
    pruned = [ln for ln in current if "omoikane supervisor tick" not in ln]
    pruned.append(line)
    _write_crontab(pruned)
    return InstallResult("cron", [Path("crontab")], None)


def _uninstall_cron() -> InstallResult:
    current, _ = _read_crontab()
    pruned = [ln for ln in current if "omoikane supervisor tick" not in ln]
    if len(pruned) == len(current):
        return InstallResult("cron", [], "no omoikane line found")
    _write_crontab(pruned)
    return InstallResult("cron", [Path("crontab")], None)


def _read_crontab() -> Tuple[List[str], bool]:
    try:
        proc = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    except FileNotFoundError:
        return [], False
    if proc.returncode != 0:
        return [], False
    return [ln for ln in proc.stdout.splitlines() if ln.strip()], True


def _write_crontab(lines: List[str]) -> None:
    content = "\n".join(lines) + "\n"
    proc = subprocess.run(["crontab", "-"], input=content, text=True, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(f"failed to write crontab: {proc.stderr.strip()}")


__all__ = [
    "InstallResult",
    "LAUNCHD_LABEL",
    "SYSTEMD_UNIT",
    "detect_backend",
    "install",
    "launchd_plist_path",
    "render_cron_line",
    "render_launchd_plist",
    "render_systemd_service",
    "render_systemd_timer",
    "systemd_service_path",
    "systemd_timer_path",
    "uninstall",
]
