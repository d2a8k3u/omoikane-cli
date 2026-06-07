"""Data / persistence layer — JSON file storage."""

import json
from pathlib import Path


class JsonStorage:
    """Persists task data as a JSON file, auto-creating on first save."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> list[dict]:
        """Return all tasks from the JSON file, or [] if the file does not exist or is empty."""
        if not self._path.exists():
            return []
        text = self._path.read_text(encoding="utf-8").strip()
        if not text:
            return []
        data = json.loads(text)
        if not isinstance(data, list):
            return []
        return data

    def save(self, tasks: list[dict]) -> None:
        """Write *tasks* as JSON, creating parent directories if needed."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(tasks, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
