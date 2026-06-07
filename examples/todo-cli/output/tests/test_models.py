"""Tests for the Task dataclass in models.py."""

import json
from datetime import datetime
from todo.models import Task


class TestTaskCreation:
    def test_default_status_is_pending(self):
        task = Task(id=1, text="Buy milk")
        assert task.status == "pending"

    def test_default_created_at_is_iso_timestamp(self):
        task = Task(id=1, text="Buy milk")
        # Should be parseable as an ISO-8601 datetime
        parsed = datetime.fromisoformat(task.created_at)
        assert isinstance(parsed, datetime)
        # Should be very recent (within a few seconds)
        assert (datetime.now() - parsed).total_seconds() < 5

    def test_explicit_values(self):
        task = Task(id=2, text="Walk dog", status="done", created_at="2024-01-01T00:00:00")
        assert task.id == 2
        assert task.text == "Walk dog"
        assert task.status == "done"
        assert task.created_at == "2024-01-01T00:00:00"

    def test_equality(self):
        a = Task(id=1, text="test", status="pending", created_at="2024-01-01")
        b = Task(id=1, text="test", status="pending", created_at="2024-01-01")
        assert a == b

    def test_inequality(self):
        a = Task(id=1, text="test", status="pending", created_at="2024-01-01")
        b = Task(id=2, text="test", status="pending", created_at="2024-01-01")
        assert a != b


class TestTaskSerialization:
    def test_to_dict_returns_all_fields(self):
        task = Task(id=1, text="Buy milk", status="pending", created_at="2024-06-15T12:00:00")
        d = task.to_dict()
        assert d == {"id": 1, "text": "Buy milk", "status": "pending", "created_at": "2024-06-15T12:00:00"}

    def test_from_dict_round_trip(self):
        original = Task(id=1, text="Buy milk", status="done", created_at="2024-06-15T12:00:00")
        restored = Task.from_dict(original.to_dict())
        assert restored == original

    def test_from_dict_preserves_types(self):
        d = {"id": 3, "text": "Read book", "status": "pending", "created_at": "2024-06-15T12:00:00"}
        task = Task.from_dict(d)
        assert isinstance(task, Task)
        assert task.id == 3
        assert task.text == "Read book"

    def test_to_dict_is_json_serializable(self):
        task = Task(id=1, text="Buy milk", status="pending", created_at="2024-06-15T12:00:00")
        d = task.to_dict()
        json_str = json.dumps(d)
        parsed = json.loads(json_str)
        assert parsed == d

    def test_status_values(self):
        """Status field should accept 'pending' or 'done'."""
        t1 = Task(id=1, text="a", status="pending")
        t2 = Task(id=2, text="b", status="done")
        assert t1.status == "pending"
        assert t2.status == "done"
