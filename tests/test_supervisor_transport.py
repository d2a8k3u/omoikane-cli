"""Supervisor ↔ transport wiring and circuit-breaker progress semantics.

Covers two findings:

* A1 — a project that stays STALLED across many ticks (respawn after
  respawn, no real work) MUST eventually trip the circuit breaker.
  Respawn success is not progress.
* A2 — the supervisor must push pending approvals to the configured
  transports and apply polled responses back into the Book.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import List

from omoikane.core.book import ProjectBook
from omoikane.orchestrator import daemon as _daemon
from omoikane.runtime.agent_run import RunConfig
from omoikane.supervisor import tick as _tick
from omoikane.transport.base import (
    ApprovalEnvelope,
    TransportResponse,
)


def _force_idle(book: ProjectBook, minutes: float) -> None:
    """Drop last_activity far into the past, directly in book.json.

    ``ProjectStore`` rewrites ``last_activity`` on every flush, so going
    through the public API would clobber the cutoff. Preserves the
    supervisor sub-dict (counter) untouched.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    raw = json.loads(book.store.book_path.read_text(encoding="utf-8"))
    raw["last_activity"] = cutoff.isoformat()
    book.store.book_path.write_text(json.dumps(raw))


def _set_breaker_threshold(book: ProjectBook, minutes: float) -> None:
    """Shrink the circuit-breaker threshold (book-scoped) for a fast test."""
    raw = json.loads(book.store.book_path.read_text(encoding="utf-8"))
    raw.setdefault("supervisor", {})["circuit_breaker_threshold_minutes"] = minutes
    book.store.book_path.write_text(json.dumps(raw))


class FakeTransport:
    """In-memory transport: records sends, replays canned responses."""

    name = "fake"

    def __init__(self, responses: List[TransportResponse] | None = None) -> None:
        self.sent: List[ApprovalEnvelope] = []
        self.completions: List[tuple] = []
        self._responses = list(responses or [])
        self._polled = False

    def send_approval_request(self, envelope: ApprovalEnvelope) -> bool:
        self.sent.append(envelope)
        return True

    def send_completion(self, project_id: str, summary: str) -> bool:
        self.completions.append((project_id, summary))
        return True

    def poll_responses(self) -> List[TransportResponse]:
        # Replay responses once, then nothing (simulates consumed inbox).
        if self._polled:
            return []
        self._polled = True
        return list(self._responses)


# --------------------------------------------------------------------------
# A1 — circuit breaker trips when respawn never yields real progress.
# --------------------------------------------------------------------------

def test_repeated_respawn_trips_circuit_breaker(temp_hermes_home, monkeypatch):
    book = ProjectBook.create("brief", ["AC"])
    book.open_task("Do something", "agent-implementer")
    # budget = threshold // tick_interval = 10 // 5 = 2 ticks.
    _set_breaker_threshold(book, minutes=10)

    def fake_start(project_id, *, config, detach=True, **kwargs):
        # Successful respawn, but it does NOT advance the book / close tasks.
        return 4242

    monkeypatch.setattr(
        _daemon.OrchestratorDaemon, "start", staticmethod(fake_start),
    )

    config = RunConfig(model="x", api_key="y")

    # Budget is 2; run more than that. Re-apply idleness before each tick
    # because every flush rewrites last_activity to now. Once the breaker
    # trips, status flips to 'blocked' and the classifier reports TERMINAL,
    # so we stop driving ticks at that point.
    seen_stalled = False
    for _ in range(4):
        if ProjectBook(book.project_id).load()["supervisor"].get(
            "circuit_breaker_tripped"
        ):
            break
        _force_idle(book, minutes=30)
        outcomes = _tick.run_tick(
            config=config,
            project_ids=[book.project_id],
            stall_minutes=10.0,
            circuit_breaker_minutes=10.0,
            tick_interval_minutes=5.0,
        )
        assert outcomes[0].state == "stalled"
        seen_stalled = True

    assert seen_stalled
    sup = ProjectBook(book.project_id).load()["supervisor"]
    assert sup.get("circuit_breaker_tripped") is True


# --------------------------------------------------------------------------
# A2 — supervisor pushes pending approvals and applies polled responses.
# --------------------------------------------------------------------------

def test_pending_approval_pushed_to_transport(temp_hermes_home):
    book = ProjectBook.create("brief", ["AC"])
    task_id = book.open_task("Do something", "agent-implementer")
    approval_id = book.request_approval(
        task_id=task_id,
        requester_role="agent-implementer",
        action="run_command",
        command="rm -rf /tmp/x",
        reason="cleanup",
    )

    transport = FakeTransport()
    _tick.push_and_poll_approvals([transport], project_ids=[book.project_id])

    assert len(transport.sent) == 1
    envelope = transport.sent[0]
    assert envelope.approval_id == approval_id
    assert envelope.command == "rm -rf /tmp/x"
    assert envelope.project_id == book.project_id


def test_polled_response_resolves_approval(temp_hermes_home):
    book = ProjectBook.create("brief", ["AC"])
    task_id = book.open_task("Do something", "agent-implementer")
    approval_id = book.request_approval(
        task_id=task_id,
        requester_role="agent-implementer",
        action="run_command",
        command="echo hi",
        reason="needed",
    )

    transport = FakeTransport(
        responses=[TransportResponse(approval_id, "approve", "via-test")]
    )
    _tick.push_and_poll_approvals([transport], project_ids=[book.project_id])

    entry = next(
        a for a in ProjectBook(book.project_id).load()["pending_approvals"]
        if a["approval_id"] == approval_id
    )
    assert entry["status"] in {"approve", "approved"}


def test_run_tick_wires_transports(temp_hermes_home):
    """run_tick(transports=...) should push pending approvals."""
    book = ProjectBook.create("brief", ["AC"])
    task_id = book.open_task("Do something", "agent-implementer")
    book.request_approval(
        task_id=task_id,
        requester_role="agent-implementer",
        action="run_command",
        command="ls",
        reason="r",
    )

    transport = FakeTransport()
    _tick.run_tick(project_ids=[book.project_id], transports=[transport])
    assert len(transport.sent) == 1
