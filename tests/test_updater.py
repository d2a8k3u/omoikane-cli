"""Unit tests for omoikane.update.updater (pure logic + frozen gating)."""
from __future__ import annotations

import omoikane.update.updater as up


def test_parse_handles_v_prefix_and_prerelease():
    assert up._parse("v1.2.3") == (1, 2, 3)
    assert up._parse("1.2.3") == (1, 2, 3)
    assert up._parse("v0.0.1-rc1") == (0, 0, 1)
    assert up._parse("2.0") == (2, 0, 0)


def test_is_newer():
    assert up.is_newer("v0.2.0", "0.1.0")
    assert up.is_newer("1.0.0", "0.9.9")
    assert not up.is_newer("0.1.0", "0.1.0")
    assert not up.is_newer("v0.1.0", "0.2.0")


def test_asset_name_macos_arm64(monkeypatch):
    monkeypatch.setattr(up.sys, "platform", "darwin")
    monkeypatch.setattr(up.platform, "machine", lambda: "arm64")
    assert up.asset_name() == "omoikane-macos-arm64.tar.gz"


def test_asset_name_linux_x86_64(monkeypatch):
    monkeypatch.setattr(up.sys, "platform", "linux")
    monkeypatch.setattr(up.platform, "machine", lambda: "x86_64")
    assert up.asset_name() == "omoikane-linux-x86_64.tar.gz"


def test_asset_name_unsupported(monkeypatch):
    monkeypatch.setattr(up.sys, "platform", "darwin")
    monkeypatch.setattr(up.platform, "machine", lambda: "x86_64")  # Intel mac not built
    assert up.asset_name() is None
    monkeypatch.setattr(up.sys, "platform", "win32")
    assert up.asset_name() is None


def test_self_update_noop_when_not_frozen(monkeypatch, capsys):
    monkeypatch.setattr(up, "is_frozen", lambda: False)
    rc = up.self_update()
    assert rc == 0
    assert "managed by pip" in capsys.readouterr().err


def test_maybe_nag_silent_when_not_frozen(monkeypatch, capsys):
    monkeypatch.setattr(up, "is_frozen", lambda: False)
    up.maybe_nag("list")
    assert capsys.readouterr().err == ""


def test_maybe_nag_prints_from_cache(monkeypatch, capsys, temp_omoikane_home):
    # Frozen + TTY + fresh cache holding a newer tag -> one-line nag, no network.
    monkeypatch.setattr(up, "is_frozen", lambda: True)
    monkeypatch.setattr(up.sys.stderr, "isatty", lambda: True)
    monkeypatch.delenv("OMOIKANE_NO_UPDATE_CHECK", raising=False)
    up._write_cache("v9.9.9")  # fresh cache -> no network fetch
    up.maybe_nag("list")
    err = capsys.readouterr().err
    assert "v9.9.9" in err and "self-update" in err


def test_maybe_nag_skips_supervisor(monkeypatch, capsys, temp_omoikane_home):
    monkeypatch.setattr(up, "is_frozen", lambda: True)
    monkeypatch.setattr(up.sys.stderr, "isatty", lambda: True)
    up._write_cache("v9.9.9")
    up.maybe_nag("supervisor")
    assert capsys.readouterr().err == ""


def _make_fake_release(tmp_path):
    """Build a fake onedir tarball (root `omoikane/omoikane`) + sha sidecar.

    Returns a release-JSON dict with file:// asset URLs.
    """
    import hashlib
    import tarfile

    payload = tmp_path / "payload" / "omoikane"
    payload.mkdir(parents=True)
    (payload / "omoikane").write_text("#!/bin/sh\necho hi\n")
    (payload / "_internal").mkdir()

    tarball = tmp_path / "asset.tar.gz"
    with tarfile.open(tarball, "w:gz") as tf:
        tf.add(payload, arcname="omoikane")

    sha = hashlib.sha256(tarball.read_bytes()).hexdigest()
    shafile = tmp_path / "asset.tar.gz.sha256"
    shafile.write_text(f"{sha}  asset.tar.gz\n")

    return {
        "tag_name": "v9.9.9",
        "assets": [
            {"name": "asset.tar.gz", "browser_download_url": tarball.as_uri()},
            {"name": "asset.tar.gz.sha256", "browser_download_url": shafile.as_uri()},
        ],
    }


def test_self_update_end_to_end(monkeypatch, tmp_path, temp_omoikane_home):
    release = _make_fake_release(tmp_path)
    monkeypatch.setattr(up, "is_frozen", lambda: True)
    monkeypatch.setattr(up, "asset_name", lambda: "asset.tar.gz")
    monkeypatch.setattr(up, "fetch_latest", lambda *a, **k: release)

    rc = up.self_update()
    assert rc == 0

    link = up.paths.binary_path()
    assert link.is_symlink()
    expected = up.paths.version_dir("9.9.9") / "omoikane" / "omoikane"
    assert link.resolve() == expected.resolve()
    assert expected.read_text().startswith("#!/bin/sh")


def test_self_update_checksum_mismatch_aborts(monkeypatch, tmp_path, temp_omoikane_home):
    release = _make_fake_release(tmp_path)
    # Corrupt the sha sidecar so verification fails.
    bad = tmp_path / "bad.sha256"
    bad.write_text("deadbeef  asset.tar.gz\n")
    release["assets"][1]["browser_download_url"] = bad.as_uri()

    monkeypatch.setattr(up, "is_frozen", lambda: True)
    monkeypatch.setattr(up, "asset_name", lambda: "asset.tar.gz")
    monkeypatch.setattr(up, "fetch_latest", lambda *a, **k: release)

    rc = up.self_update()
    assert rc == 1
    assert not up.paths.binary_path().exists()
