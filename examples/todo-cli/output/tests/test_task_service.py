"""Tests for TaskService in task_service.py."""

import pytest
import tempfile
from pathlib import Path

from todo.task_service import TaskService, TaskNotFoundError
from todo.storage import JsonStorage


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def service(tmp_dir):
    storage = JsonStorage(tmp_dir / "tasks.json")
    return TaskService(storage)


class TestAddTask:
    def test_returns_task_object(self, service):
        task = service.add_task("Buy milk")
        assert task.text == "Buy milk"
        assert task.status == "pending"

    def test_assigns_unique_ids(self, service):
        t1 = service.add_task("First")
        t2 = service.add_task("Second")
        assert t2.id == t1.id + 1

    def test_first_id_is_one(self, service):
        task = service.add_task("Hello")
        assert task.id == 1

    def test_saves_to_storage(self, service):
        service.add_task("Persist me")
        # New storage instance, same file
        storage2 = JsonStorage(service._storage._path)
        data = storage2.load()
        assert len(data) == 1
        assert data[0]["text"] == "Persist me"
        assert data[0]["status"] == "pending"

    def test_add_then_list_returns_added_task(self, service):
        service.add_task("Test task")
        tasks = service.list_tasks()
        assert len(tasks) == 1
        assert tasks[0].text == "Test task"

    def test_preserves_text_content(self, service):
        service.add_task("Koupit mléko")
        tasks = service.list_tasks()
        assert tasks[0].text == "Koupit mléko"

    def test_multiple_tasks_in_order(self, service):
        service.add_task("A")
        service.add_task("B")
        service.add_task("C")
        tasks = service.list_tasks()
        assert [t.text for t in tasks] == ["A", "B", "C"]
        assert [t.id for t in tasks] == [1, 2, 3]


class TestListTasks:
    def test_empty_when_no_tasks(self, service):
        assert service.list_tasks() == []

    def test_returns_all_added_tasks(self, service):
        service.add_task("One")
        service.add_task("Two")
        tasks = service.list_tasks()
        assert len(tasks) == 2

    def test_returns_task_with_created_at(self, service):
        service.add_task("Timed")
        tasks = service.list_tasks()
        assert isinstance(tasks[0].created_at, str)
        assert len(tasks[0].created_at) > 0

    def test_tasks_have_correct_ids(self, service):
        service.add_task("First")
        service.add_task("Second")
        tasks = service.list_tasks()
        assert tasks[0].id == 1
        assert tasks[1].id == 2


class TestDoneTask:
    def test_marks_task_as_done(self, service):
        service.add_task("Finish me")
        task = service.done_task(1)
        assert task.status == "done"

    def test_done_task_persists(self, service):
        service.add_task("Persist done")
        service.done_task(1)
        tasks = service.list_tasks()
        assert tasks[0].status == "done"

    def test_done_returns_task_object(self, service):
        service.add_task("Return me")
        task = service.done_task(1)
        assert task.id == 1
        assert task.text == "Return me"
        assert task.status == "done"

    def test_done_nonexistent_id_raises(self, service):
        with pytest.raises(TaskNotFoundError):
            service.done_task(999)

    def test_done_already_done_task_is_noop(self, service):
        service.add_task("Already done")
        service.done_task(1)
        task = service.done_task(1)
        assert task.status == "done"


class TestDeleteTask:
    def test_removes_task_from_list(self, service):
        service.add_task("Delete me")
        service.delete_task(1)
        assert service.list_tasks() == []

    def test_delete_persists(self, service):
        service.add_task("Persist delete")
        service.delete_task(1)
        tasks = service.list_tasks()
        assert len(tasks) == 0

    def test_delete_nonexistent_id_raises(self, service):
        with pytest.raises(TaskNotFoundError):
            service.delete_task(999)

    def test_delete_correct_task(self, service):
        service.add_task("Keep me")
        service.add_task("Delete me")
        service.delete_task(2)
        tasks = service.list_tasks()
        assert len(tasks) == 1
        assert tasks[0].text == "Keep me"

    def test_delete_then_readd_reuses_id_logic(self, service):
        service.add_task("First")
        service.add_task("Second")
        service.delete_task(1)
        service.add_task("Third")
        tasks = service.list_tasks()
        assert len(tasks) == 2
        assert tasks[0].text == "Second"
        assert tasks[1].text == "Third"
        assert tasks[1].id == 3


class TestClearDone:
    def test_removes_done_tasks(self, service):
        service.add_task("Keep me")
        service.add_task("Done task")
        service.done_task(2)
        count = service.clear_done()
        assert count == 1
        tasks = service.list_tasks()
        assert len(tasks) == 1
        assert tasks[0].text == "Keep me"
        assert tasks[0].status == "pending"

    def test_returns_number_of_removed_tasks(self, service):
        service.add_task("A")
        service.add_task("B")
        service.add_task("C")
        service.done_task(1)
        service.done_task(3)
        count = service.clear_done()
        assert count == 2
        tasks = service.list_tasks()
        assert len(tasks) == 1
        assert tasks[0].text == "B"

    def test_returns_zero_when_no_done_tasks(self, service):
        service.add_task("Pending 1")
        service.add_task("Pending 2")
        count = service.clear_done()
        assert count == 0
        assert len(service.list_tasks()) == 2

    def test_returns_zero_when_already_empty(self, service):
        count = service.clear_done()
        assert count == 0

    def test_removes_all_tasks_when_all_done(self, service):
        service.add_task("A")
        service.add_task("B")
        service.done_task(1)
        service.done_task(2)
        count = service.clear_done()
        assert count == 2
        assert service.list_tasks() == []

    def test_persists_after_clear(self, service):
        service.add_task("Done")
        service.add_task("Pending")
        service.done_task(1)
        service.clear_done()
        # read back via a fresh storage instance pointing at same file
        storage2 = JsonStorage(service._storage._path)
        data = storage2.load()
        assert len(data) == 1
        assert data[0]["text"] == "Pending"
        assert data[0]["status"] == "pending"

    def test_preserves_pending_tasks_in_order(self, service):
        service.add_task("P1")
        service.add_task("D1")
        service.add_task("P2")
        service.add_task("D2")
        service.add_task("P3")
        service.done_task(2)
        service.done_task(4)
        service.clear_done()
        tasks = service.list_tasks()
        assert [t.text for t in tasks] == ["P1", "P2", "P3"]
        assert all(t.status == "pending" for t in tasks)

    def test_clear_done_idempotent(self, service):
        service.add_task("Done")
        service.done_task(1)
        first = service.clear_done()
        second = service.clear_done()
        assert first == 1
        assert second == 0


class TestTaskNotFoundError:
    def test_is_exception_subclass(self):
        assert issubclass(TaskNotFoundError, Exception)

    def test_message_includes_task_id(self, service):
        with pytest.raises(TaskNotFoundError, match="999"):
            service.done_task(999)

    def test_message_for_delete_includes_task_id(self, service):
        with pytest.raises(TaskNotFoundError, match="42"):
            service.delete_task(42)

    def test_can_be_caught_as_exception(self, service):
        try:
            service.done_task(999)
        except TaskNotFoundError as e:
            assert "999" in str(e)
        else:
            pytest.fail("TaskNotFoundError was not raised")


class TestServiceWithPreExistingData:
    def test_service_loads_existing_tasks(self, tmp_dir):
        """Service should work with a file that already contains tasks."""
        path = tmp_dir / "tasks.json"
        import json
        json.dump([
            {"id": 1, "text": "Pre-existing", "status": "done", "created_at": "2024-01-01T00:00:00"},
            {"id": 2, "text": "Also pre-existing", "status": "pending", "created_at": "2024-01-02T00:00:00"},
        ], path.open("w"))
        storage = JsonStorage(path)
        service = TaskService(storage)
        tasks = service.list_tasks()
        assert len(tasks) == 2
        assert tasks[0].text == "Pre-existing"
        assert tasks[1].text == "Also pre-existing"

    def test_add_after_preexisting_uses_correct_id(self, tmp_dir):
        """New task ID should be max(existing_ids) + 1, not just count-based."""
        path = tmp_dir / "tasks.json"
        import json
        json.dump([
            {"id": 1, "text": "A", "status": "pending", "created_at": "2024-01-01T00:00:00"},
            {"id": 5, "text": "B", "status": "pending", "created_at": "2024-01-02T00:00:00"},
        ], path.open("w"))
        storage = JsonStorage(path)
        service = TaskService(storage)
        task = service.add_task("New")
        assert task.id == 6

    def test_done_on_preexisting_task(self, tmp_dir):
        """Marking a pre-existing task as done should work."""
        path = tmp_dir / "tasks.json"
        import json
        json.dump([
            {"id": 1, "text": "Old done", "status": "done", "created_at": "2024-01-01T00:00:00"},
        ], path.open("w"))
        storage = JsonStorage(path)
        service = TaskService(storage)
        task = service.done_task(1)
        assert task.status == "done"

    def test_delete_on_preexisting_task(self, tmp_dir):
        """Deleting a pre-existing task should work."""
        path = tmp_dir / "tasks.json"
        import json
        json.dump([
            {"id": 1, "text": "Remove me", "status": "pending", "created_at": "2024-01-01T00:00:00"},
        ], path.open("w"))
        storage = JsonStorage(path)
        service = TaskService(storage)
        service.delete_task(1)
        assert service.list_tasks() == []

    def test_add_then_done_then_delete_full_lifecycle(self, tmp_dir):
        """Full lifecycle: add → done → clear should leave empty list."""
        path = tmp_dir / "tasks.json"
        storage = JsonStorage(path)
        service = TaskService(storage)

        service.add_task("Task A")
        service.add_task("Task B")
        service.done_task(1)
        service.clear_done()
        service.delete_task(2)
        assert service.list_tasks() == []

    def test_service_sees_changes_from_another_service_instance(self, tmp_dir):
        """Two services on the same file should see each other's writes."""
        path = tmp_dir / "tasks.json"
        storage_a = JsonStorage(path)
        service_a = TaskService(storage_a)

        service_a.add_task("From A")

        storage_b = JsonStorage(path)
        service_b = TaskService(storage_b)

        tasks = service_b.list_tasks()
        assert len(tasks) == 1
        assert tasks[0].text == "From A"

        service_b.add_task("From B")
        tasks = service_a.list_tasks()
        assert len(tasks) == 2


class TestEdgeCases:
    def test_add_empty_text(self, service):
        """Adding a task with empty string should still create it."""
        task = service.add_task("")
        assert task.text == ""
        assert task.id == 1
        tasks = service.list_tasks()
        assert len(tasks) == 1

    def test_add_unicode_text(self, service):
        """Unicode text (Czech, emoji) should be preserved."""
        task = service.add_task("Koupit mléko 🥛")
        assert task.text == "Koupit mléko 🥛"
        tasks = service.list_tasks()
        assert tasks[0].text == "Koupit mléko 🥛"

    def test_done_on_empty_list_raises(self, service):
        """Calling done_task with no tasks should raise TaskNotFoundError."""
        with pytest.raises(TaskNotFoundError):
            service.done_task(1)

    def test_delete_on_empty_list_raises(self, service):
        """Calling delete_task with no tasks should raise TaskNotFoundError."""
        with pytest.raises(TaskNotFoundError):
            service.delete_task(1)

    def test_done_with_zero_id_raises(self, service):
        service.add_task("Test")
        with pytest.raises(TaskNotFoundError):
            service.done_task(0)

    def test_done_with_negative_id_raises(self, service):
        service.add_task("Test")
        with pytest.raises(TaskNotFoundError):
            service.done_task(-1)

    def test_delete_with_zero_id_raises(self, service):
        service.add_task("Test")
        with pytest.raises(TaskNotFoundError):
            service.delete_task(0)

    def test_delete_with_negative_id_raises(self, service):
        service.add_task("Test")
        with pytest.raises(TaskNotFoundError):
            service.delete_task(-1)

    def test_multiple_done_calls_idempotent(self, service):
        """Calling done_task multiple times should not error."""
        service.add_task("Idempotent done")
        service.done_task(1)
        service.done_task(1)
        service.done_task(1)
        tasks = service.list_tasks()
        assert len(tasks) == 1
        assert tasks[0].status == "done"

    def test_delete_middle_task_preserves_others(self, service):
        """Deleting the middle of three tasks should leave the other two."""
        service.add_task("First")
        service.add_task("Middle")
        service.add_task("Last")
        service.delete_task(2)
        tasks = service.list_tasks()
        assert len(tasks) == 2
        assert tasks[0].text == "First"
        assert tasks[0].id == 1
        assert tasks[1].text == "Last"
        assert tasks[1].id == 3

    def test_add_after_deleting_all(self, service):
        """After deleting all tasks, ID counter resets since storage is empty."""
        service.add_task("A")
        service.add_task("B")
        service.delete_task(1)
        service.delete_task(2)
        task = service.add_task("C")
        # When all tasks are deleted, storage is empty so ID resets to 1
        assert task.id == 1

    def test_list_returns_empty_after_clear_all(self, service):
        """Clearing all done tasks when all are done leaves empty list."""
        service.add_task("A")
        service.add_task("B")
        service.done_task(1)
        service.done_task(2)
        service.clear_done()
        assert service.list_tasks() == []

    def test_error_message_for_done_is_descriptive(self, service):
        """Error message should contain the task ID for debugging."""
        with pytest.raises(TaskNotFoundError) as exc_info:
            service.done_task(42)
        assert "42" in str(exc_info.value)
        assert "not found" in str(exc_info.value).lower() or "not found" in str(exc_info.value)

    def test_error_message_for_delete_is_descriptive(self, service):
        """Error message should contain the task ID for debugging."""
        with pytest.raises(TaskNotFoundError) as exc_info:
            service.delete_task(42)
        assert "42" in str(exc_info.value)
