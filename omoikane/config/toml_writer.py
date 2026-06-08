"""Minimal stdlib TOML serializer + atomic config writer.

``tomllib`` (stdlib) reads TOML but cannot write it, and the binary-critical
paths in this project stay stdlib-only (see :mod:`omoikane.update.updater`).
Onboarding writes ``config.toml`` on the first frozen-binary launch, so pulling
in a third-party writer would mean bundling it in ``omoikane.spec`` or crashing
on exactly that path. This ~40-line serializer avoids that.

Scope: a two-level dict — top-level scalars/arrays, ``[section]``, and one
level of nested tables ``[section.subsection]`` (covers ``[transport.telegram]``).
Supported value types: ``str``, ``int``, ``float``, ``bool``, and ``list`` of
those scalars.

Note: writing is read-merge-rewrite. Re-running onboarding reformats
``config.toml`` and does NOT preserve hand-added comments or key order beyond
the dict's insertion order. Secrets that must stay untouched belong in env vars
via the ``env:VAR`` indirection.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

_ESCAPES = (
    ("\\", "\\\\"),
    ("\"", "\\\""),
    ("\n", "\\n"),
    ("\r", "\\r"),
    ("\t", "\\t"),
)


def _fmt_value(value) -> str:
    """Render a single scalar or list-of-scalars as a TOML value."""
    # bool is a subclass of int — check it first.
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        out = value
        for raw, esc in _ESCAPES:
            out = out.replace(raw, esc)
        return f'"{out}"'
    if isinstance(value, list):
        return "[" + ", ".join(_fmt_value(item) for item in value) + "]"
    raise TypeError(f"unsupported TOML value type: {type(value).__name__}")


def _emit_scalars(lines: list, table: dict) -> None:
    for key, val in table.items():
        if isinstance(val, dict):
            continue
        lines.append(f"{key} = {_fmt_value(val)}")


def dumps(data: dict) -> str:
    """Serialize a two-level dict to TOML text.

    Top-level scalar keys are emitted first (TOML requires them before any
    table header), then each section, then its nested subtables.
    """
    lines: list = []

    # Top-level scalars must precede any section header.
    _emit_scalars(lines, data)

    for key, val in data.items():
        if not isinstance(val, dict):
            continue
        if lines:
            lines.append("")
        lines.append(f"[{key}]")
        _emit_scalars(lines, val)
        for subkey, subval in val.items():
            if not isinstance(subval, dict):
                continue
            lines.append("")
            lines.append(f"[{key}.{subkey}]")
            _emit_scalars(lines, subval)

    return "\n".join(lines) + "\n"


def write_config(data: dict, path: Optional[Path] = None) -> Path:
    """Atomically write ``data`` to ``config.toml`` with mode 0600.

    Writes to a temp file in the same directory then ``os.replace`` (atomic,
    mirrors ``updater._flip_symlink``). The config may hold a plaintext API key,
    so the file is chmod'd to owner read/write only.
    """
    from omoikane.config import paths

    if path is None:
        path = paths.config_file()
    paths.ensure_home()

    text = dumps(data)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    # Create the temp file 0600 from the start so the plaintext API key is never
    # briefly world-readable (umask could otherwise widen a later chmod's window).
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(tmp, flags, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, 0o600)  # defeat a restrictive-then-permissive umask
        os.replace(tmp, path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    return path
