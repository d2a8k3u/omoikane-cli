"""Self-update for the standalone (PyInstaller onedir) binary.

Install layout under ``~/.omoikane/`` (see :mod:`omoikane.config.paths`)::

    bin/omoikane            symlink -> versions/<v>/omoikane/omoikane
    versions/<v>/omoikane/  onedir payload (exe + _internal/)

Update = download the platform tarball -> verify sha256 -> extract to a new
``versions/<v>/`` -> atomically repoint the ``bin/omoikane`` symlink -> GC old
versions. The running process's files are never overwritten (replacing loaded
``.so`` files would ABI-crash mid-run), so "in-place" is done as a symlink flip.

Stdlib only — the binary must self-update without third-party deps.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import ssl
import sys
import tarfile
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Optional, Tuple

from omoikane import __version__
from omoikane.config import paths

REPO = "d2a8k3u/omoikane-cli"
_API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
_API_LIST = f"https://api.github.com/repos/{REPO}/releases"
_NAG_INTERVAL_SECONDS = 24 * 60 * 60  # once/day
_HTTP_TIMEOUT = 10.0

_ssl_ctx: Optional[ssl.SSLContext] = None


def _ssl_context() -> ssl.SSLContext:
    """HTTPS context with a working CA bundle.

    The frozen binary's stdlib ``ssl`` may not find the OS trust store, so
    prefer ``certifi`` (bundled via httpx) and fall back to the default.
    """
    global _ssl_ctx
    if _ssl_ctx is None:
        try:
            import certifi

            _ssl_ctx = ssl.create_default_context(cafile=certifi.where())
        except Exception:  # noqa: BLE001
            _ssl_ctx = ssl.create_default_context()
    return _ssl_ctx


# --------------------------------------------------------------------------
# Environment
# --------------------------------------------------------------------------
def is_frozen() -> bool:
    """True when running as a PyInstaller-built binary (vs pip/editable)."""
    return bool(getattr(sys, "frozen", False))


def current_version() -> str:
    return __version__


def asset_name() -> Optional[str]:
    """Return the release asset filename for this platform, or None if unsupported."""
    machine = platform.machine().lower()
    if sys.platform == "darwin":
        if machine in {"arm64", "aarch64"}:
            return "omoikane-macos-arm64.tar.gz"
        return None  # Intel macs not built (decision: arm64 + linux x86_64 only)
    if sys.platform.startswith("linux"):
        if machine in {"x86_64", "amd64"}:
            return "omoikane-linux-x86_64.tar.gz"
        return None
    return None


# --------------------------------------------------------------------------
# Version comparison
# --------------------------------------------------------------------------
def _parse(version: str) -> Tuple[int, int, int]:
    """Parse ``vX.Y.Z`` / ``X.Y.Z`` to a comparable tuple; pre-release ignored."""
    core = version.lstrip("vV").split("-")[0].split("+")[0]
    parts = core.split(".")
    nums = []
    for p in parts[:3]:
        try:
            nums.append(int(p))
        except ValueError:
            nums.append(0)
    while len(nums) < 3:
        nums.append(0)
    return nums[0], nums[1], nums[2]


def is_newer(latest: str, current: str) -> bool:
    return _parse(latest) > _parse(current)


# --------------------------------------------------------------------------
# GitHub Releases API (fail-silent for the nag; raises for explicit update)
# --------------------------------------------------------------------------
def _get_json(url: str, timeout: float = _HTTP_TIMEOUT) -> dict:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "omoikane-cli",
            "Accept": "application/vnd.github+json",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8"))


def fetch_latest(timeout: float = _HTTP_TIMEOUT) -> Optional[dict]:
    """Return the newest release JSON, or None on any error (offline-safe).

    Prefers the latest stable release; falls back to the newest release in the
    list (which may be a prerelease) because ``/releases/latest`` returns 404
    when only prereleases exist.
    """
    try:
        return _get_json(_API_LATEST, timeout=timeout)
    except Exception:  # noqa: BLE001 - no stable release; try the full list
        pass
    try:
        releases = _get_json(_API_LIST, timeout=timeout)
        if isinstance(releases, list) and releases:
            return releases[0]
    except Exception:  # noqa: BLE001 - any failure -> no update info
        pass
    return None


# --------------------------------------------------------------------------
# Startup nag (throttled, cached, fail-silent)
# --------------------------------------------------------------------------
def _read_cache() -> dict:
    try:
        return json.loads(paths.update_check_file().read_text())
    except Exception:  # noqa: BLE001
        return {}


def _write_cache(latest_tag: str) -> None:
    try:
        paths.ensure_home()
        paths.update_check_file().write_text(
            json.dumps({"checked_at": int(time.time()), "latest_tag": latest_tag})
        )
    except Exception:  # noqa: BLE001
        pass


def maybe_nag(command: Optional[str], *, now: Optional[int] = None) -> None:
    """Print a one-line stderr nag if a newer release exists. Never raises.

    Gated: only for frozen installs, only on a TTY, never for the
    supervisor/daemon paths, opt-out via ``OMOIKANE_NO_UPDATE_CHECK``.
    """
    try:
        if not is_frozen():
            return
        if os.environ.get("OMOIKANE_NO_UPDATE_CHECK"):
            return
        if not sys.stderr.isatty():
            return
        if command in {"supervisor", "self-update"}:
            return

        now = int(time.time()) if now is None else now
        cache = _read_cache()
        latest_tag = cache.get("latest_tag")
        stale = (now - int(cache.get("checked_at", 0))) > _NAG_INTERVAL_SECONDS

        if stale:
            release = fetch_latest(timeout=3.0)  # keep startup snappy
            if release and release.get("tag_name"):
                latest_tag = release["tag_name"]
                _write_cache(latest_tag)

        if latest_tag and is_newer(latest_tag, current_version()):
            print(
                f"omoikane {latest_tag} available (current {current_version()}). "
                f"Run `omoikane self-update`.",
                file=sys.stderr,
            )
    except Exception:  # noqa: BLE001 - the nag must never break a command
        pass


# --------------------------------------------------------------------------
# Self-update
# --------------------------------------------------------------------------
def _download(url: str, dest: Path, timeout: float = 120.0) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "omoikane-cli"})
    with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as resp:  # noqa: S310
        dest.write_bytes(resp.read())


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _find_asset(release: dict, name: str) -> Optional[dict]:
    for asset in release.get("assets", []):
        if asset.get("name") == name:
            return asset
    return None


def _flip_symlink(target_exe: Path) -> None:
    """Atomically point ``bin/omoikane`` at ``target_exe``."""
    link = paths.binary_path()
    link.parent.mkdir(parents=True, exist_ok=True)
    tmp = link.parent / f".omoikane.{os.getpid()}.tmp"
    if tmp.exists() or tmp.is_symlink():
        tmp.unlink()
    os.symlink(target_exe, tmp)
    os.replace(tmp, link)  # atomic within the same directory


def _gc_versions(keep: set) -> None:
    vdir = paths.versions_dir()
    if not vdir.is_dir():
        return
    for child in vdir.iterdir():
        if child.name not in keep and child.is_dir():
            import shutil

            shutil.rmtree(child, ignore_errors=True)


def self_update(*, force: bool = False, check_only: bool = False) -> int:
    """Run the self-update flow. Returns a process exit code."""
    if not is_frozen():
        print(
            "This build is managed by pip, not the self-updater.\n"
            "Upgrade with:  pip install -U omoikane-cli",
            file=sys.stderr,
        )
        return 0

    name = asset_name()
    if not name:
        print(
            f"Unsupported platform: {sys.platform}/{platform.machine()}. "
            "Prebuilt binaries are macOS arm64 and Linux x86_64 only.",
            file=sys.stderr,
        )
        return 1

    release = fetch_latest()
    if not release or not release.get("tag_name"):
        print("Could not reach the GitHub Releases API.", file=sys.stderr)
        return 1
    latest_tag = release["tag_name"]
    latest_ver = latest_tag.lstrip("vV")
    _write_cache(latest_tag)

    up_to_date = not is_newer(latest_tag, current_version())
    if up_to_date and not force:
        print(f"Already up to date ({current_version()}).")
        return 0
    if check_only:
        print(f"Update available: {current_version()} -> {latest_ver}")
        return 0

    asset = _find_asset(release, name)
    sha_asset = _find_asset(release, name + ".sha256")
    if not asset:
        print(f"Release {latest_tag} has no asset named {name}.", file=sys.stderr)
        return 1

    paths.versions_dir().mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=str(paths.home())) as td:
        tmp = Path(td)
        tarball = tmp / name
        print(f"Downloading {latest_tag} for this platform...", file=sys.stderr)
        _download(asset["browser_download_url"], tarball)

        if sha_asset:
            shafile = tmp / (name + ".sha256")
            _download(sha_asset["browser_download_url"], shafile)
            expected = shafile.read_text().split()[0].strip()
            actual = _sha256(tarball)
            if expected != actual:
                print(
                    f"Checksum mismatch (expected {expected}, got {actual}). Aborting.",
                    file=sys.stderr,
                )
                return 1
        else:
            print("Warning: no .sha256 sidecar; skipping integrity check.", file=sys.stderr)

        dest = paths.version_dir(latest_ver)
        if dest.exists():
            import shutil

            shutil.rmtree(dest, ignore_errors=True)
        dest.mkdir(parents=True, exist_ok=True)
        with tarfile.open(tarball, "r:gz") as tf:
            tf.extractall(dest)  # noqa: S202 - our own release artifact

    # Tarball root is the onedir folder `omoikane/`; exe is omoikane/omoikane.
    exe = paths.version_dir(latest_ver) / "omoikane" / "omoikane"
    if not exe.exists():
        print(f"Extracted payload missing expected exe at {exe}.", file=sys.stderr)
        return 1
    exe.chmod(0o755)
    _flip_symlink(exe)
    _gc_versions(keep={latest_ver, current_version()})

    print(f"Updated {current_version()} -> {latest_ver}. Restart omoikane to use it.")
    return 0
