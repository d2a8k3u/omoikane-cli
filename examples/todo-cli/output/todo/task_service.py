"""Business logic layer — TaskService."""

from todo.models import Task
from todo.storage import JsonStorage


class TaskNotFoundError(Exception):
    """Raised when a task ID does not exist."""
    pass


class TaskService:
    def __init__(self, storage: JsonStorage) -> None:
        self._storage = storage

    def add_task(self, text: str) -> Task:
        raw = self._storage.load()
        next_id = max((t["id"] for t in raw), default=0) + 1
        task = Task(id=next_id, text=text)
        raw.append(task.to_dict())
        self._storage.save(raw)
        return task

    def list_tasks(self) -> list[Task]:
        return [Task.from_dict(d) for d in self._storage.load()]

    def done_task(self, task_id: int) -> Task:
        raw = self._storage.load()
        for entry in raw:
            if entry["id"] == task_id:
                entry["status"] = "done"
                self._storage.save(raw)
                return Task.from_dict(entry)
        raise TaskNotFoundError(f"Task with id {task_id} not found")

    def delete_task(self, task_id: int) -> None:
        raw = self._storage.load()
        for i, entry in enumerate(raw):
            if entry["id"] == task_id:
                raw.pop(i)
                self._storage.save(raw)
                return
        raise TaskNotFoundError(f"Task with id {task_id} not found")

    def clear_done(self) -> int:
        raw = self._storage.load()
        remaining = [entry for entry in raw if entry.get("status") != "done"]
        removed = len(raw) - len(remaining)
        self._storage.save(remaining)
        return removed
