"""Pluggable transport interface for approval pushes + completion notices.

The supervisor's tick (Phase 4) and the TUI (Phase 5) both call into a
transport to surface pending approvals and project lifecycle events to
the operator. Transports are stateless wrappers around the operator's
chosen channel: stdout for headless boxes, the TUI's pending_approvals
view for attached operators, and Telegram / Slack webhooks for the
"operator is on their phone" workflow.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Protocol

logger = logging.getLogger(__name__)


@dataclass
class ApprovalEnvelope:
    """Data shipped to a transport when an approval needs operator review."""
    project_id: str
    approval_id: str
    requester_role: str
    action: str
    command: str
    reason: str

    @classmethod
    def from_book_entry(cls, project_id: str, entry: Dict[str, Any]) -> "ApprovalEnvelope":
        return cls(
            project_id=project_id,
            approval_id=entry.get("approval_id", "?"),
            requester_role=entry.get("requester_role", ""),
            action=entry.get("action", ""),
            command=entry.get("command", ""),
            reason=entry.get("reason", ""),
        )


@dataclass
class TransportResponse:
    """Operator decisions polled back from the transport."""
    approval_id: str
    decision: str
    note: str = ""


class Transport(Protocol):
    """The minimum surface every transport must implement."""

    name: str

    def send_approval_request(self, envelope: ApprovalEnvelope) -> bool:
        ...

    def send_completion(self, project_id: str, summary: str) -> bool:
        ...

    def poll_responses(self) -> List[TransportResponse]:
        ...


def format_approval_message(envelope: ApprovalEnvelope) -> str:
    """Shared, plain-text approval template — used by every backend."""
    return (
        "🔐 Omoikane approval needed\n"
        f"Project: {envelope.project_id}\n"
        f"Role:    {envelope.requester_role}\n"
        f"Action:  {envelope.action}\n"
        f"Command: `{envelope.command}`\n"
        f"Reason:  {envelope.reason}\n\n"
        f"Reply:\n"
        f"  /approve {envelope.approval_id}\n"
        f"  /deny {envelope.approval_id} [reason]"
    )


def format_completion_message(project_id: str, summary: str) -> str:
    return f"✅ Omoikane project {project_id}\n{summary}"


__all__ = [
    "ApprovalEnvelope",
    "Transport",
    "TransportResponse",
    "format_approval_message",
    "format_completion_message",
]
