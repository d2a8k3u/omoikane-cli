"""``stdout`` transport — prints to the supervisor's terminal / log file."""
from __future__ import annotations

import sys
from typing import List

from .base import (
    ApprovalEnvelope,
    TransportResponse,
    format_approval_message,
    format_completion_message,
)


class StdoutTransport:
    """Simplest possible backend: write to stdout, ignore inbound."""

    name = "stdout"

    def send_approval_request(self, envelope: ApprovalEnvelope) -> bool:
        sys.stdout.write(format_approval_message(envelope))
        sys.stdout.write("\n")
        sys.stdout.flush()
        return True

    def send_completion(self, project_id: str, summary: str) -> bool:
        sys.stdout.write(format_completion_message(project_id, summary))
        sys.stdout.write("\n")
        sys.stdout.flush()
        return True

    def poll_responses(self) -> List[TransportResponse]:
        # Stdout is a one-way channel — operator responses come back
        # through the CLI / TUI, not this transport.
        return []


__all__ = ["StdoutTransport"]
