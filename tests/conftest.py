"""Pytest configuration for the standalone Omoikane test suite.

Redirects Omoikane's persistence root into a fresh temporary directory per
test by setting ``OMOIKANE_HOME`` before the resolvers in
:mod:`omoikane.config.paths` are consulted, then initialising the SQLite
index inside that temp directory. The fixture is named ``temp_omoikane_home``
to make the standalone heritage obvious in test signatures.

Backwards-compatible alias ``temp_hermes_home`` is provided so test files
ported verbatim from the legacy Hermes plugin can still resolve their
fixture by name without rewriting every signature.
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def temp_omoikane_home(monkeypatch):
    """Redirect Omoikane persistence into a fresh temporary directory."""
    tmp = Path(tempfile.mkdtemp(prefix="omoikane-test-"))
    monkeypatch.setenv("OMOIKANE_HOME", str(tmp))

    # Reset the lazy ``_DB_READY`` flag inside the store module so the new
    # OMOIKANE_HOME triggers a fresh schema initialisation on first use.
    from omoikane.core import store

    monkeypatch.setattr(store, "_DB_READY", False, raising=False)
    store.init_index_db()
    try:
        yield tmp
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# Compatibility alias — ported tests still reference ``temp_hermes_home``.
@pytest.fixture
def temp_hermes_home(temp_omoikane_home):
    """Alias of :func:`temp_omoikane_home` for ported legacy tests."""
    return temp_omoikane_home
