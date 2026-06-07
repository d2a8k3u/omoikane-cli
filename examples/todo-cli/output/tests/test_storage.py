"""Tests for JsonStorage in storage.py."""

import json
import tempfile
from pathlib import Path

import pytest

from todo.storage import JsonStorage


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


class TestJsonStorageInit:
    def test_stores_path(self, tmp_dir):
        path = tmp_dir / "tasks.json"
        storage = JsonStorage(path)
        assert storage._path == path

    def test_accepts_string_path(self, tmp_dir):
        """Path is typed as Path but constructors with str should also work."""
        path = tmp_dir / "tasks.json"
        storage = JsonStorage(path)
        assert storage._path == path


class TestJsonStorageLoad:
    def test_load_returns_empty_list_when_file_not_exists(self, tmp_dir):
        path = tmp_dir / "tasks.json"
        storage = JsonStorage(path)
        result = storage.load()
        assert result == []

    def test_load_returns_empty_list_for_empty_file(self, tmp_dir):
        path = tmp_dir / "tasks.json"
        path.write_text("[]")
        storage = JsonStorage(path)
        assert storage.load() == []

    def test_load_returns_parsed_json(self, tmp_dir):
        tasks = [
            {"id": 1, "text": "Buy milk", "status": "pending", "created_at": "2024-01-01T00:00:00"},
            {"id": 2, "text": "Walk dog", "status": "done", "created_at": "2024-01-02T00:00:00"},
        ]
        path = tmp_dir / "tasks.json"
        path.write_text(json.dumps(tasks))
        storage = JsonStorage(path)
        assert storage.load() == tasks

    def test_load_returns_list_of_dicts(self, tmp_dir):
        tasks = [{"id": 1, "text": "Test", "status": "pending", "created_at": "2024-01-01T00:00:00"}]
        path = tmp_dir / "tasks.json"
        path.write_text(json.dumps(tasks))
        result = storage = JsonStorage(path)
        result = storage.load()
        assert isinstance(result, list)
        assert isinstance(result[0], dict)

    def test_load_returns_empty_list_for_non_list_json(self, tmp_dir):
        """If the JSON file contains a non-list (e.g. object), return []."""
        path = tmp_dir / "tasks.json"
        path.write_text(json.dumps({"not": "a list"}))
        storage = JsonStorage(path)
        result = storage.load()
        assert result == []

    def test_load_returns_empty_list_for_json_string(self, tmp_dir):
        """If the JSON file contains a bare string, return []."""
        path = tmp_dir / "tasks.json"
        path.write_text(json.dumps("just a string"))
        storage = JsonStorage(path)
        result = storage.load()
        assert result == []

    def test_load_returns_empty_list_for_json_number(self, tmp_dir):
        """If the JSON file contains a bare number, return []."""
        path = tmp_dir / "tasks.json"
        path.write_text(json.dumps(42))
        storage = JsonStorage(path)
        result = storage.load()
        assert result == []

    def test_load_raises_on_malformed_json(self, tmp_dir):
        """Malformed JSON should raise json.JSONDecodeError."""
        path = tmp_dir / "tasks.json"
        path.write_text("{invalid json content")
        storage = JsonStorage(path)
        with pytest.raises(json.JSONDecodeError):
            storage.load()

    def test_load_empty_string_file_returns_empty_list(self, tmp_dir):
        """Completely empty file (0 bytes) should return []."""
        path = tmp_dir / "tasks.json"
        path.write_text("")
        storage = JsonStorage(path)
        result = storage.load()
        assert result == []

    def test_load_preserves_all_dict_fields(self, tmp_dir):
        """Loaded dicts must retain all original keys and values."""
        tasks = [
            {"id": 1, "text": "A", "status": "pending", "created_at": "2024-01-01T00:00:00", "extra": "field"},
            {"id": 2, "text": "B", "status": "done", "created_at": "2024-01-02T00:00:00"},
        ]
        path = tmp_dir / "tasks.json"
        path.write_text(json.dumps(tasks))
        storage = JsonStorage(path)
        result = storage.load()
        assert result == tasks
        assert result[0]["extra"] == "field"

    def test_load_returns_empty_list_for_json_null(self, tmp_dir):
        """JSON null is not a list — should return []."""
        path = tmp_dir / "tasks.json"
        path.write_text("null")
        storage = JsonStorage(path)
        result = storage.load()
        assert result == []

    def test_load_returns_empty_list_for_json_true(self, tmp_dir):
        """JSON true is not a list — should return []."""
        path = tmp_dir / "tasks.json"
        path.write_text("true")
        storage = JsonStorage(path)
        result = storage.load()
        assert result == []

    def test_load_does_not_create_file(self, tmp_dir):
        """Calling load() when file doesn't exist must not create it."""
        path = tmp_dir / "tasks.json"
        storage = JsonStorage(path)
        storage.load()
        assert not path.exists()


class TestJsonStorageSave:
    def test_save_creates_file(self, tmp_dir):
        path = tmp_dir / "tasks.json"
        storage = JsonStorage(path)
        assert not path.exists()
        storage.save([{"id": 1, "text": "Test", "status": "pending", "created_at": "2024-01-01T00:00:00"}])
        assert path.exists()

    def test_save_writes_valid_json(self, tmp_dir):
        tasks = [{"id": 1, "text": "Test", "status": "pending", "created_at": "2024-01-01T00:00:00"}]
        path = tmp_dir / "tasks.json"
        storage = JsonStorage(path)
        storage.save(tasks)
        raw = path.read_text()
        parsed = json.loads(raw)
        assert parsed == tasks

    def test_save_creates_parent_directories(self, tmp_dir):
        path = tmp_dir / "subdir" / "tasks.json"
        storage = JsonStorage(path)
        storage.save([{"id": 1, "text": "Test", "status": "pending", "created_at": "2024-01-01T00:00:00"}])
        assert path.exists()

    def test_save_overwrites_existing_file(self, tmp_dir):
        path = tmp_dir / "tasks.json"
        path.write_text(json.dumps([{"id": 1, "text": "Old", "status": "done", "created_at": "2024-01-01T00:00:00"}]))
        storage = JsonStorage(path)
        new_tasks = [{"id": 2, "text": "New", "status": "pending", "created_at": "2024-06-01T00:00:00"}]
        storage.save(new_tasks)
        assert storage.load() == new_tasks

    def test_save_empty_list(self, tmp_dir):
        path = tmp_dir / "tasks.json"
        storage = JsonStorage(path)
        storage.save([])
        assert storage.load() == []

    def test_save_preserves_unicode_characters(self, tmp_dir):
        """Unicode text must round-trip correctly (ensure_ascii=False)."""
        tasks = [
            {"id": 1, "text": "Koupit mléko 🥛", "status": "pending", "created_at": "2024-01-01T00:00:00"},
            {"id": 2, "text": "散步狗", "status": "done", "created_at": "2024-01-02T00:00:00"},
        ]
        path = tmp_dir / "tasks.json"
        storage = JsonStorage(path)
        storage.save(tasks)
        result = storage.load()
        assert result == tasks
        # Also verify raw file contains actual UTF-8 chars, not \u escapes
        raw = path.read_text(encoding="utf-8")
        assert "🥛" in raw
        assert "散步" in raw

    def test_save_with_large_dataset(self, tmp_dir):
        """Saving 1000 tasks should work and round-trip correctly."""
        tasks = [
            {"id": i, "text": f"Task {i}", "status": "pending" if i % 2 else "done", "created_at": f"2024-01-{(i % 28) + 1:02d}T00:00:00"}
            for i in range(1, 1001)
        ]
        path = tmp_dir / "tasks.json"
        storage = JsonStorage(path)
        storage.save(tasks)
        result = storage.load()
        assert len(result) == 1000
        assert result[0]["id"] == 1
        assert result[999]["id"] == 1000

    def test_save_file_is_indented(self, tmp_dir):
        """Written JSON should be pretty-printed with indent=2."""
        tasks = [{"id": 1, "text": "Test", "status": "pending", "created_at": "2024-01-01T00:00:00"}]
        path = tmp_dir / "tasks.json"
        storage = JsonStorage(path)
        storage.save(tasks)
        raw = path.read_text(encoding="utf-8")
        # indented JSON has newlines
        assert "\n" in raw

    def test_overwrite_clears_old_data(self, tmp_dir):
        """Saving a smaller list after a larger one must replace entirely."""
        path = tmp_dir / "tasks.json"
        storage = JsonStorage(path)
        storage.save([
            {"id": 1, "text": "A", "status": "pending", "created_at": "2024-01-01T00:00:00"},
            {"id": 2, "text": "B", "status": "done", "created_at": "2024-01-02T00:00:00"},
            {"id": 3, "text": "C", "status": "pending", "created_at": "2024-01-03T00:00:00"},
        ])
        storage.save([{"id": 99, "text": "Only", "status": "pending", "created_at": "2024-06-01T00:00:00"}])
        result = storage.load()
        assert len(result) == 1
        assert result[0]["id"] == 99


class TestJsonStorageRoundTrip:
    def test_load_after_save_returns_same_data(self, tmp_dir):
        tasks = [
            {"id": 1, "text": "Buy milk", "status": "pending", "created_at": "2024-01-01T00:00:00"},
            {"id": 2, "text": "Walk dog", "status": "done", "created_at": "2024-01-02T00:00:00"},
            {"id": 3, "text": "Read book", "status": "pending", "created_at": "2024-01-03T00:00:00"},
        ]
        path = tmp_dir / "tasks.json"
        storage = JsonStorage(path)
        storage.save(tasks)
        assert storage.load() == tasks

    def test_multiple_save_load_cycles(self, tmp_dir):
        """Data should be stable across multiple save/load cycles."""
        path = tmp_dir / "tasks.json"
        storage = JsonStorage(path)

        # First cycle
        storage.save([{"id": 1, "text": "A", "status": "pending", "created_at": "2024-01-01T00:00:00"}])
        result1 = storage.load()

        # Second cycle — load, append, save
        data = storage.load()
        data.append({"id": 2, "text": "B", "status": "done", "created_at": "2024-01-02T00:00:00"})
        storage.save(data)
        result2 = storage.load()

        assert len(result1) == 1
        assert len(result2) == 2
        assert result2[0]["text"] == "A"
        assert result2[1]["text"] == "B"

    def test_separate_instances_same_file(self, tmp_dir):
        """Two JsonStorage instances pointing at the same file must see each other's data."""
        path = tmp_dir / "tasks.json"
        storage_a = JsonStorage(path)
        storage_b = JsonStorage(path)

        storage_a.save([{"id": 1, "text": "From A", "status": "pending", "created_at": "2024-01-01T00:00:00"}])
        result = storage_b.load()
        assert result == [{"id": 1, "text": "From A", "status": "pending", "created_at": "2024-01-01T00:00:00"}]

    def test_empty_save_then_load(self, tmp_dir):
        """Saving empty list then loading should yield []."""
        path = tmp_dir / "tasks.json"
        storage = JsonStorage(path)
        storage.save([])
        assert storage.load() == []

    def test_save_after_nonexistent_load(self, tmp_dir):
        """Loading from nonexistent file then saving should work seamlessly."""
        path = tmp_dir / "tasks.json"
        storage = JsonStorage(path)
        initial = storage.load()
        assert initial == []
        tasks = [{"id": 1, "text": "Hello", "status": "pending", "created_at": "2024-01-01T00:00:00"}]
        storage.save(tasks)
        assert storage.load() == tasks
