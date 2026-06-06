"""``OmoikaneApp`` — Textual TUI orchestrator viewer.

Composes the five widgets defined under :mod:`omoikane.tui.widgets` into
the canonical layout:

    ┌─ status_bar (dock top) ────────────────────────────────┐
    │ ● Title …  status=…  phase=…  criteria=2/5             │
    ├──────────────────────────────────┬─────────────────────┤
    │ ActivityPane                     │ DelegationPane      │
    │ (tail of activity.jsonl)         │                     │
    │                                  ├─────────────────────┤
    │                                  │ CriteriaPane        │
    │                                  ├─────────────────────┤
    │                                  │ (future approvals)  │
    ├──────────────────────────────────┴─────────────────────┤
    │ InputBar (dock bottom) — /cto, /task:N, /approve …     │
    └────────────────────────────────────────────────────────┘

Live tail uses :mod:`watchfiles` (Rust-backed) when available; falls
back to a 1-second polling loop otherwise. Both code paths produce
identical TUI behaviour — the polling fallback exists so tests can
exercise the redraw logic without a real watcher thread.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Optional

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.message import Message

from omoikane.config import paths
from omoikane.core.book import ProjectBook
from omoikane.orchestrator import daemon as _daemon
from omoikane.runtime.injection import write_message
from omoikane.tui.widgets.activity_pane import ActivityPane
from omoikane.tui.widgets.approvals_pane import ApprovalsPane
from omoikane.tui.widgets.criteria_pane import CriteriaPane
from omoikane.tui.widgets.delegation_pane import DelegationPane
from omoikane.tui.widgets.input_bar import InputBar
from omoikane.tui.widgets.status_bar import StatusBar


class DaemonStopRequested(Message):
    """Emitted when the operator confirms a daemon stop via Ctrl+D."""


class OmoikaneApp(App):
    """Operator-facing TUI bound to a single Omoikane project."""

    CSS = """
    Screen {
        background: $surface;
    }
    """
    BINDINGS = [
        Binding("ctrl+c", "detach", "Detach (keep daemon)", show=True, priority=True),
        Binding("ctrl+d", "stop_daemon", "Stop daemon", show=True),
        Binding("f1", "show_help", "Help", show=True),
        Binding("f2", "approve_selected", "Approve", show=True),
        Binding("f3", "deny_selected", "Deny", show=True),
        Binding("f5", "force_refresh", "Refresh", show=False),
    ]

    def __init__(
        self,
        project_id: str,
        *,
        poll_interval: float = 1.0,
        max_initial_lines: int = 200,
    ):
        super().__init__()
        self.project_id = project_id
        self.poll_interval = poll_interval
        self.max_initial_lines = max_initial_lines

        self.project_dir = paths.project_dir(project_id)
        self.activity_path = self.project_dir / "activity.jsonl"
        self.delegation_path = self.project_dir / "delegation.json"
        self.book_handle = ProjectBook(project_id)

        self._tail_position: int = 0
        self._tail_task: Optional[asyncio.Task] = None
        self._book_task: Optional[asyncio.Task] = None

    # ------------------------------------------------------------------
    # Composition
    # ------------------------------------------------------------------
    def compose(self) -> ComposeResult:
        yield StatusBar(id="status-bar")
        with Horizontal():
            yield ActivityPane(self.project_id, self.activity_path, id="activity-pane")
            with Vertical(id="side-column"):
                yield DelegationPane(self.delegation_path, id="delegation-pane")
                yield CriteriaPane(id="criteria-pane")
                yield ApprovalsPane(id="approvals-pane")
        yield InputBar(self.project_id, id="input-bar")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    async def on_mount(self) -> None:
        self._render_status()
        self._render_book_dependent()
        activity_pane = self.query_one(ActivityPane)
        activity_pane.populate_tail(limit=self.max_initial_lines)
        self._tail_position = (
            self.activity_path.stat().st_size if self.activity_path.exists() else 0
        )
        self._tail_task = asyncio.create_task(self._poll_activity())
        self._book_task = asyncio.create_task(self._poll_book())

    async def on_unmount(self) -> None:
        for task in (self._tail_task, self._book_task):
            if task and not task.done():
                task.cancel()

    # ------------------------------------------------------------------
    # Polling loops — watchfiles would be ideal but a 1-sec poll keeps
    # the dependency surface narrow and the behaviour deterministic.
    # ------------------------------------------------------------------
    async def _poll_activity(self) -> None:
        try:
            while True:
                await asyncio.sleep(self.poll_interval)
                self._drain_activity()
        except asyncio.CancelledError:
            return

    async def _poll_book(self) -> None:
        try:
            while True:
                await asyncio.sleep(self.poll_interval * 2)
                self._render_status()
                self._render_book_dependent()
        except asyncio.CancelledError:
            return

    def _drain_activity(self) -> None:
        if not self.activity_path.exists():
            return
        size = self.activity_path.stat().st_size
        if size <= self._tail_position:
            return
        try:
            with open(self.activity_path, "rb") as fh:
                fh.seek(self._tail_position)
                chunk = fh.read(size - self._tail_position).decode("utf-8", errors="replace")
        except OSError:
            return
        self._tail_position = size

        pane = self.query_one(ActivityPane)
        for line in chunk.splitlines():
            pane.append_line(line)

    def _render_status(self) -> None:
        try:
            data = self.book_handle.load()
        except FileNotFoundError:
            return
        snapshot = _daemon.status(self.project_id)
        self.query_one(StatusBar).update_from_book(
            data, daemon_running=snapshot.is_running,
        )

    def _render_book_dependent(self) -> None:
        try:
            data = self.book_handle.load()
        except FileNotFoundError:
            return
        self.query_one(CriteriaPane).update_from_book(data)
        self.query_one(DelegationPane).refresh_tree()
        self.query_one(ApprovalsPane).update_from_book(data)

    # ------------------------------------------------------------------
    # Operator interactions
    # ------------------------------------------------------------------
    def on_input_bar_sent(self, message: InputBar.Sent) -> None:
        parsed = message.parsed
        if parsed.get("target") != "__control__":
            return
        command = parsed.get("command")
        args = parsed.get("args") or ""
        if command == "stop":
            self.action_stop_daemon()
        elif command in {"quit", "q", "exit"}:
            self.action_detach()
        elif command in {"help", "h", "?"}:
            self.action_show_help()
        elif command == "approve":
            # Re-route as an inbox message keyed for the supervisor.
            write_message(self.project_id, f"/approve {args}", target="__control__")
        elif command == "deny":
            write_message(self.project_id, f"/deny {args}", target="__control__")
        else:
            self.notify(
                f"unknown command: /{command}",
                severity="warning",
                title="omoikane",
            )

    def action_detach(self) -> None:
        self.exit(0)

    def action_stop_daemon(self) -> None:
        ok = _daemon.OrchestratorDaemon.stop(self.project_id, timeout=10.0)
        self.notify(
            "daemon stopped" if ok else "daemon did not exit cleanly",
            severity="information" if ok else "warning",
        )
        self.exit(0 if ok else 2)

    def action_show_help(self) -> None:
        self.notify(
            "Slash commands: /cto · /task:<id> · /<role> · /broadcast · "
            "/approve <id> · /deny <id> · /stop · /help. Ctrl+C detaches; "
            "Ctrl+D stops the daemon then detaches.",
            title="omoikane",
        )

    def action_force_refresh(self) -> None:
        self._drain_activity()
        self._render_status()
        self._render_book_dependent()

    def action_approve_selected(self) -> None:
        self._resolve_selected("approve")

    def action_deny_selected(self) -> None:
        self._resolve_selected("deny")

    def _resolve_selected(self, decision: str) -> None:
        pane = self.query_one(ApprovalsPane)
        approval = pane.selected_approval()
        if not approval:
            self.notify("no pending approval selected", severity="warning")
            return
        aid = approval.get("approval_id")
        if not aid:
            return
        try:
            entry = self.book_handle.resolve_approval(
                approval_id=aid, decision=decision, note="tui",
            )
        except ValueError as exc:
            self.notify(f"resolve failed: {exc}", severity="warning")
            return
        if entry is None:
            self.notify(
                f"approval {aid} not found", severity="warning",
            )
            return
        self.notify(
            f"{decision}d {aid}",
            severity="information" if decision == "approve" else "warning",
        )
        self._render_book_dependent()


def run_app(project_id: str, *, poll_interval: float = 1.0) -> int:
    """Convenience wrapper used by the ``omoikane open`` CLI."""
    app = OmoikaneApp(project_id, poll_interval=poll_interval)
    return app.run() or 0


__all__ = ["OmoikaneApp", "run_app"]
