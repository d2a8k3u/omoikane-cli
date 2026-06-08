"""Tests for the stdlib TOML serializer + atomic writer."""
from __future__ import annotations

import stat
import tomllib

from omoikane.config import paths, toml_writer


def test_round_trip_nested():
    data = {
        "auth": {"api_key": "sk-123"},
        "model": {"provider": "openrouter", "id": "openrouter/owl-alpha"},
        "transport": {
            "backends": ["stdout", "telegram"],
            "telegram": {"bot_token": "env:TG", "chat_id": "-100"},
        },
        "supervisor": {"schedule": "*/5 * * * *"},
    }
    assert tomllib.loads(toml_writer.dumps(data)) == data


def test_escaping_quotes_and_backslashes():
    data = {"auth": {"api_key": 'a"b\\c'}}
    parsed = tomllib.loads(toml_writer.dumps(data))
    assert parsed["auth"]["api_key"] == 'a"b\\c'


def test_bool_and_int_and_list():
    data = {"flags": {"on": True, "off": False, "count": 3, "names": ["a", "b"]}}
    assert tomllib.loads(toml_writer.dumps(data)) == data


def test_top_level_scalars_precede_sections():
    text = toml_writer.dumps({"name": "x", "sec": {"k": "v"}})
    assert text.index("name =") < text.index("[sec]")
    assert tomllib.loads(text) == {"name": "x", "sec": {"k": "v"}}


def test_write_config_atomic_mode_0600(temp_omoikane_home):
    path = toml_writer.write_config({"model": {"id": "m"}})
    assert path == paths.config_file()
    assert path.exists()
    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == 0o600
    # No leftover temp files in the home dir.
    leftovers = [p.name for p in path.parent.glob(".config.toml.*.tmp")]
    assert leftovers == []
    assert tomllib.loads(path.read_text()) == {"model": {"id": "m"}}
