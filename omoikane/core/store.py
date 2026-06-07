"""
Omoikane Store - Persistence layer (M1)
SQLite + JSONL + filesystem for Project Activity Book
"""

import fcntl
import json
import os
import random
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from omoikane.config import paths

from .redact import redact, redact_text


def _ensure_dirs():
    paths.project_root().mkdir(parents=True, exist_ok=True)
    paths.index_db().parent.mkdir(parents=True, exist_ok=True)


def _atomic_json_write(path: Path, data: Dict[str, Any]) -> None:
    """Write JSON atomically via temp file + fsync + rename."""
    tmp = path.with_suffix(f".tmp-{os.getpid()}")
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(path)
    # Ensure the directory entry is committed (metadata durability).
    dir_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def _get_conn() -> sqlite3.Connection:
    _ensure_dirs()
    _ensure_db()
    conn = sqlite3.connect(paths.index_db())
    conn.row_factory = sqlite3.Row
    return conn


_SCHEMA_DDL = """
    CREATE TABLE IF NOT EXISTS projects (
        id TEXT PRIMARY KEY,
        title TEXT,
        status TEXT,
        current_phase TEXT,
        starting_state TEXT,
        created_at TEXT,
        last_activity TEXT
    );

    CREATE TABLE IF NOT EXISTS tasks (
        id TEXT PRIMARY KEY,
        project_id TEXT,
        title TEXT,
        status TEXT,
        assignee_role TEXT,
        parent_task TEXT,
        created_at TEXT,
        closed_at TEXT
    );

    CREATE TABLE IF NOT EXISTS delegations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id TEXT,
        from_node TEXT,
        to_node TEXT,
        expected TEXT,
        returned TEXT,
        delegated_at TEXT
    );

    CREATE VIRTUAL TABLE IF NOT EXISTS activity_fts USING fts5(
        project_id, ts, kind, actor, task, summary
    );
"""


def init_index_db():
    """Initialize the shared index database (idempotent).

    Safe to call multiple times. Resets the lazy-init guard so a fresh
    pytest fixture (which redirects ``OMOIKANE_HOME``) can re-prime the
    schema in a new temp directory.
    """
    global _DB_READY
    _DB_READY = False
    _ensure_dirs()
    _init_schema()
    _DB_READY = True


_DB_READY = False


def _ensure_db():
    """Initialize the index DB on first use (lazy), guarded by a cross-process
    file lock so concurrent cron / supervisor processes do not race DDL."""
    global _DB_READY
    if _DB_READY:
        return
    _ensure_dirs()
    lock_path = paths.index_db().with_suffix(".init.lock")
    with open(lock_path, "w") as lockfile:
        fcntl.flock(lockfile.fileno(), fcntl.LOCK_EX)
        try:
            if not _DB_READY:
                _init_schema()
                _DB_READY = True
        finally:
            fcntl.flock(lockfile.fileno(), fcntl.LOCK_UN)


def _init_schema():
    """Internal schema setup — called by ``_ensure_db`` under file lock.

    Splits the public ``init_index_db`` (which intentionally resets the
    lazy-init guard) from the lock-protected setup invoked on cold start.
    """
    conn = sqlite3.connect(paths.index_db())
    try:
        conn.executescript(_SCHEMA_DDL)
        conn.commit()
    finally:
        conn.close()


def generate_project_id() -> str:
    """Generate sortable project ID: proj-YYYYMMDD-HHMMSS-xxxx"""
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y%m%d-%H%M%S")
    suffix = f"{random.randint(0, 0xffff):04x}"
    return f"proj-{ts}-{suffix}"


class ProjectStore:
    """Low-level persistence for one project."""

    def __init__(self, project_id: str):
        _ensure_db()
        self.project_id = project_id
        self.project_dir = paths.project_dir(project_id)
        self.project_dir.mkdir(parents=True, exist_ok=True)

        self.book_path = self.project_dir / "book.json"
        self.activity_path = self.project_dir / "activity.jsonl"
        self.delegation_path = self.project_dir / "delegation.json"

    def _book_lock_path(self) -> Path:
        return self.book_path.with_suffix(".lock")

    def _delegation_lock_path(self) -> Path:
        return self.delegation_path.with_suffix(".lock")

    def _activity_lock_path(self) -> Path:
        return self.activity_path.with_suffix(".lock")

    def create_book(self, brief: str, acceptance_criteria: List[str],
                    starting_state: str = "scratch", title: Optional[str] = None) -> Dict[str, Any]:
        """Create initial book.json atomically under an exclusive lock."""
        lock_path = self._book_lock_path()
        with open(lock_path, "w") as lockfile:
            fcntl.flock(lockfile.fileno(), fcntl.LOCK_EX)
            try:
                if self.book_path.exists():
                    raise FileExistsError(f"Project {self.project_id} already exists")

                book = {
                    "id": self.project_id,
                    "title": title or brief[:60],
                    "brief": brief,
                    "acceptance_criteria": acceptance_criteria,
                    "criteria_status": {str(i): "pending" for i in range(len(acceptance_criteria))},
                    "status": "created",
                    "current_phase": "planning",
                    "starting_state": starting_state,
                    "team": {},
                    "open_tasks": [],
                    "completed_tasks": [],
                    "task_meta": {},
                    "roadmap": [],
                    "pending_approvals": [],
                    "approved_commands": [],
                    "origin": None,
                    "active_resurrect_run_id": None,
                    "active_resurrect_started_at": None,
                    "artifacts": [],
                    "blockers": [],
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "last_activity": datetime.now(timezone.utc).isoformat(),
                    "schema_version": 1,
                }

                _atomic_json_write(self.book_path, book)
                _atomic_json_write(self.delegation_path, {"nodes": [], "edges": []})
                self.activity_path.touch()
                self._index_project(book)
                return book
            finally:
                fcntl.flock(lockfile.fileno(), fcntl.LOCK_UN)

    def load_book(self) -> Dict[str, Any]:
        """Load current book state (shared-locked)."""
        lock_path = self._book_lock_path()
        with open(lock_path, "w") as lockfile:
            fcntl.flock(lockfile.fileno(), fcntl.LOCK_SH)
            try:
                try:
                    with open(self.book_path) as f:
                        return json.load(f)
                except FileNotFoundError:
                    raise FileNotFoundError(f"book.json not found for project {self.project_id}") from None
                except json.JSONDecodeError as exc:
                    raise ValueError(f"Corrupted book.json for {self.project_id}: {exc}") from exc
            finally:
                fcntl.flock(lockfile.fileno(), fcntl.LOCK_UN)

    def _save_book_locked(self, book: Dict[str, Any]) -> None:
        """Persist book under an already-held exclusive lock."""
        book["last_activity"] = datetime.now(timezone.utc).isoformat()
        _atomic_json_write(self.book_path, book)
        self._index_project(book)

    def save_book(self, book: Dict[str, Any]):
        """Save book state (exclusive-locked + atomic rename)."""
        lock_path = self._book_lock_path()
        with open(lock_path, "w") as lockfile:
            fcntl.flock(lockfile.fileno(), fcntl.LOCK_EX)
            try:
                self._save_book_locked(book)
            finally:
                fcntl.flock(lockfile.fileno(), fcntl.LOCK_UN)

    def update_book(self, updater: Callable[[Dict[str, Any]], Any]) -> Tuple[Dict[str, Any], Any]:
        """Atomic read-modify-write under a single exclusive lock.

        The ``updater`` receives the current book dict, mutates it in-place,
        and may return any value.  This method returns ``(book, updater_result)``.
        """
        lock_path = self._book_lock_path()
        with open(lock_path, "w") as lockfile:
            fcntl.flock(lockfile.fileno(), fcntl.LOCK_EX)
            try:
                try:
                    with open(self.book_path) as f:
                        data = json.load(f)
                except FileNotFoundError:
                    raise FileNotFoundError(f"book.json not found for project {self.project_id}") from None
                except json.JSONDecodeError as exc:
                    raise ValueError(f"Corrupted book.json for {self.project_id}: {exc}") from exc

                result = updater(data)
                self._save_book_locked(data)
                return data, result
            finally:
                fcntl.flock(lockfile.fileno(), fcntl.LOCK_UN)

    def append_activity(self, kind: str, summary: str,
                        actor: str = "system", task: Optional[str] = None,
                        data: Optional[Dict] = None):
        """Append one event to activity.jsonl.

        Secret redaction is a hard gate per spec §11.2 — applied before any
        write hits disk. The Book may be shared, zipped, or replayed; live
        credentials must never persist there.
        """
        event = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "kind": kind,
            "actor": actor,
            "task": task,
            "summary": redact_text(summary),
            "data": redact(data or {})
        }
        lock_path = self._activity_lock_path()
        with open(lock_path, "w") as lockfile:
            fcntl.flock(lockfile.fileno(), fcntl.LOCK_EX)
            try:
                with open(self.activity_path, "a") as f:
                    f.write(json.dumps(event) + "\n")
                    f.flush()
                    os.fsync(f.fileno())
            finally:
                fcntl.flock(lockfile.fileno(), fcntl.LOCK_UN)

    # === Delegation tree (spec §5.5) ===

    def _load_delegation(self) -> Dict[str, Any]:
        if not self.delegation_path.exists():
            return {"nodes": [], "edges": []}
        lock_path = self._delegation_lock_path()
        with open(lock_path, "w") as lockfile:
            fcntl.flock(lockfile.fileno(), fcntl.LOCK_SH)
            try:
                try:
                    with open(self.delegation_path) as f:
                        return json.load(f)
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        f"Corrupted delegation.json for {self.project_id}: {exc}"
                    ) from exc
            finally:
                fcntl.flock(lockfile.fileno(), fcntl.LOCK_UN)

    def _save_delegation(self, tree: Dict[str, Any]):
        lock_path = self._delegation_lock_path()
        with open(lock_path, "w") as lockfile:
            fcntl.flock(lockfile.fileno(), fcntl.LOCK_EX)
            try:
                _atomic_json_write(self.delegation_path, tree)
            finally:
                fcntl.flock(lockfile.fileno(), fcntl.LOCK_UN)

    def add_delegation(self, task: str, to_role: str, expected: str,
                       mode: str = "in_process", from_node: str = "n-root",
                       label: Optional[str] = None) -> str:
        """Add a node + edge for a new delegation. Returns the new node id."""
        tree = self._load_delegation()
        # Ensure root node
        if not any(n["id"] == "n-root" for n in tree["nodes"]):
            tree["nodes"].append({
                "id": "n-root", "actor": "orchestrator",
                "task": None, "label": "Project root"
            })
        node_id = f"n-{task}"
        if not any(n["id"] == node_id for n in tree["nodes"]):
            tree["nodes"].append({
                "id": node_id,
                "actor": to_role,
                "task": task,
                "label": label or task,
            })
        tree["edges"].append({
            "from": from_node,
            "to": node_id,
            "delegated_at": datetime.now(timezone.utc).isoformat(),
            "expected": expected,
            "returned": "pending",
            "mode": mode,
            "reflection_ref": None,
        })
        self._save_delegation(tree)

        # Mirror into SQLite index (spec §5.6)
        conn = _get_conn()
        conn.execute(
            "INSERT INTO delegations (project_id, from_node, to_node, expected, returned, delegated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (self.project_id, from_node, node_id, expected, "pending",
             datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        conn.close()
        return node_id

    def record_delegation_result(self, task: str, status: str,
                                 reflection_ref: Optional[str] = None):
        """Close the most recent pending edge for ``task`` with ``status``."""
        tree = self._load_delegation()
        node_id = f"n-{task}"
        # Close the latest pending edge ending at this node
        for edge in reversed(tree["edges"]):
            if edge["to"] == node_id and edge["returned"] == "pending":
                edge["returned"] = status
                edge["reflection_ref"] = reflection_ref
                break
        self._save_delegation(tree)

        conn = _get_conn()
        # Update only the most recent pending row so SQLite stays consistent
        # with the JSON tree (which only closes the latest edge).
        conn.execute(
            "UPDATE delegations SET returned = ? WHERE id = ("
            "  SELECT id FROM delegations WHERE project_id = ? AND to_node = ? AND returned = 'pending'"
            "  ORDER BY id DESC LIMIT 1"
            ")",
            (status, self.project_id, node_id),
        )
        conn.commit()
        conn.close()

    def compare_and_set_resurrect_run_id(self, run_id: str) -> bool:
        """Atomic check-and-set for active_resurrect_run_id.

        Returns True if the slot was empty and we claimed it, False if
        another run is already in flight.
        """
        lock_path = self._book_lock_path()
        with open(lock_path, "w") as lockfile:
            fcntl.flock(lockfile.fileno(), fcntl.LOCK_EX)
            try:
                try:
                    with open(self.book_path) as f:
                        data = json.load(f)
                except FileNotFoundError:
                    raise FileNotFoundError(f"book.json not found for project {self.project_id}") from None
                if data.get("active_resurrect_run_id"):
                    return False
                data["active_resurrect_run_id"] = run_id
                data["active_resurrect_started_at"] = datetime.now(timezone.utc).isoformat()
                data["last_activity"] = datetime.now(timezone.utc).isoformat()
                _atomic_json_write(self.book_path, data)
                self._index_project(data)
                return True
            finally:
                fcntl.flock(lockfile.fileno(), fcntl.LOCK_UN)

    def _index_project(self, book: Dict[str, Any]):
        """Mirror essential data into SQLite index."""
        conn = _get_conn()
        conn.execute("""
            INSERT OR REPLACE INTO projects
            (id, title, status, current_phase, starting_state, created_at, last_activity)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            book["id"],
            book.get("title"),
            book.get("status"),
            book.get("current_phase"),
            book.get("starting_state"),
            book.get("created_at"),
            book.get("last_activity")
        ))
        conn.commit()
        conn.close()
