"""
Omoikane - Project Index.

Aggregated read-only data about Omoikane projects (project list, detail,
activity tail) for the CLI and TUI. Despite the historical name, this is a
data reader over the SQLite index + per-project books, not web UI code.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any, Optional
from omoikane.config import paths

from . import store as _store


def _health_indicator(book: Dict[str, Any]) -> Dict[str, Any]:
    """Compress the supervisor sub-dict into a 4-color bullet for the UI.

    * ``green``  — healthy (recent activity, no breaker)
    * ``amber``  — supervisor is actively respawning (stalled/crashed
                   in flight, no breaker yet)
    * ``red``    — circuit breaker tripped; operator must intervene
    * ``grey``   — no supervisor data yet OR project terminal
    """
    sup = book.get("supervisor") or {}
    status = (book.get("status") or "").lower()
    if sup.get("circuit_breaker_tripped"):
        return {"color": "red", "label": "blocked",
                "reason": sup.get("circuit_breaker_reason") or "circuit breaker"}
    if status not in {"created", "in_progress", "review"}:
        return {"color": "grey", "label": status or "unknown", "reason": None}
    last_action = sup.get("last_action") or ""
    if last_action in {"stalled_respawn", "crashed_respawn", "race_skipped",
                       "resurrect_failed"}:
        return {"color": "amber", "label": "respawning",
                "reason": last_action}
    if sup.get("last_tick_at"):
        return {"color": "green", "label": "healthy",
                "reason": last_action or "noop"}
    return {"color": "grey", "label": "no supervisor data", "reason": None}


class ProjectIndex:
    """Provides aggregated read-only data about Omoikane projects."""

    def list_projects(self) -> List[Dict[str, Any]]:
        """Return list of all projects with basic status + health bullet."""
        conn = self._get_conn()
        rows = conn.execute("""
            SELECT id, title, status, current_phase, last_activity
            FROM projects
            ORDER BY last_activity DESC
        """).fetchall()
        conn.close()

        projects = []
        for row in rows:
            pid = row["id"]
            health = {"color": "grey", "label": "unknown", "reason": None}
            try:
                book_path = paths.project_dir(pid) / "book.json"
                if book_path.exists():
                    with open(book_path) as fh:
                        health = _health_indicator(json.load(fh))
            except Exception:
                pass
            projects.append({
                "id": pid,
                "title": row["title"],
                "status": row["status"],
                "current_phase": row["current_phase"],
                "last_activity": row["last_activity"],
                "supervisor_health": health,
            })
        return projects

    def project_detail(self, project_id: str) -> Dict[str, Any]:
        """Return detailed information about one project."""
        book_path = paths.project_dir(project_id) / "book.json"
        if not book_path.exists():
            return {"error": "Project not found"}

        with open(book_path) as f:
            book = json.load(f)

        activity = self.tail_activity(project_id, limit=10)
        health = _health_indicator(book)

        return {
            "id": project_id,
            "book": book,
            "recent_activity": activity,
            "delegation_tree": self.delegation_tree(project_id),
            "supervisor_health": health,
            "supervisor": book.get("supervisor") or {},
        }

    def delegation_tree(self, project_id: str) -> Dict[str, Any]:
        """Return delegation tree for visualization."""
        delegation_path = paths.project_dir(project_id) / "delegation.json"
        if delegation_path.exists():
            with open(delegation_path) as f:
                return json.load(f)
        return {"nodes": [], "edges": []}

    def tail_activity(self, project_id: str, after_ts: Optional[str] = None, limit: int = 20) -> List[Dict]:
        """Return recent activity entries (tail of activity.jsonl)."""
        activity_path = paths.project_dir(project_id) / "activity.jsonl"
        if not activity_path.exists():
            return []

        lines = activity_path.read_text().strip().split("\n")
        entries = []
        for line in lines[-limit:]:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue

        if after_ts:
            entries = [e for e in entries if e.get("ts", "") > after_ts]

        return entries

    def _get_conn(self):
        # Delegate to the store so the dashboard shares one cold-start
        # path with the tools — _store._get_conn runs _ensure_dirs() and
        # _ensure_db() before connecting, so loading the Omoikane tab
        # on a fresh install can't hit "no such table: projects".
        return _store._get_conn()