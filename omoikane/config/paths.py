"""Filesystem path resolution for Omoikane.

All path lookups go through functions (not module-level constants) so tests
can monkeypatch ``OMOIKANE_HOME`` or override the resolvers directly without
re-importing dependent modules.

Resolution order for the project home directory:

1. ``OMOIKANE_HOME`` env var (absolute path) — used by the pytest fixture
2. ``~/.omoikane/`` — production default

The legacy Hermes plugin used ``~/.hermes/omoikane/``. This module never
reads from the legacy location.
"""
from __future__ import annotations

import os
from pathlib import Path

_DEFAULT_HOME_REL = ".omoikane"


def home() -> Path:
    """Return the Omoikane home directory (created on first use by callers).

    Honors ``OMOIKANE_HOME`` env var. Never raises — returns a path even if
    the directory does not yet exist.
    """
    env = os.environ.get("OMOIKANE_HOME")
    if env:
        return Path(env).expanduser()
    return Path.home() / _DEFAULT_HOME_REL


def project_root() -> Path:
    """Return ``<home>/projects/`` — the parent of all project directories."""
    return home() / "projects"


def project_dir(project_id: str) -> Path:
    """Return ``<home>/projects/<project_id>/`` — a specific project's dir."""
    return project_root() / project_id


def index_db() -> Path:
    """Return ``<home>/index.db`` — the SQLite cross-project index."""
    return home() / "index.db"


def config_file() -> Path:
    """Return ``<home>/config.toml`` — global Omoikane config."""
    return home() / "config.toml"


def logs_dir() -> Path:
    """Return ``<home>/logs/`` — supervisor and daemon logs."""
    return home() / "logs"


def bin_dir() -> Path:
    """Return ``<home>/bin/`` — holds the ``omoikane`` symlink for binary installs."""
    return home() / "bin"


def binary_path() -> Path:
    """Return ``<home>/bin/omoikane`` — the stable symlink to the current version.

    install.sh and ``self-update`` keep this pointing at the active
    ``versions/<v>/omoikane``; launchd/systemd/cron units invoke it.
    """
    return bin_dir() / "omoikane"


def versions_dir() -> Path:
    """Return ``<home>/versions/`` — onedir payloads, one subdir per version."""
    return home() / "versions"


def version_dir(version: str) -> Path:
    """Return ``<home>/versions/<version>/`` — a specific binary version payload."""
    return versions_dir() / version


def update_check_file() -> Path:
    """Return ``<home>/.update-check`` — throttle cache for the startup update nag."""
    return home() / ".update-check"


def ensure_home() -> Path:
    """Create the home directory tree if missing. Returns the home path.

    Idempotent. Callers that need the directory to exist (writes, init)
    should call this before path operations; readers should tolerate
    missing dirs.
    """
    h = home()
    h.mkdir(parents=True, exist_ok=True)
    (h / "projects").mkdir(parents=True, exist_ok=True)
    (h / "logs").mkdir(parents=True, exist_ok=True)
    return h
