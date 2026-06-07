"""Foreground orchestrator entry-point.

A synchronous, terminal-attached driver that creates / resumes a
project, then runs :func:`cto_session.run_long_session` until the
project finishes or the operator hits ``Ctrl+C``.

Foreground mode is useful for debugging and for CI checks that want to
drive a project without any background processes.
"""
from __future__ import annotations

import logging
import signal
from typing import Mapping, Optional

from omoikane.runtime.agent_run import RunConfig
from omoikane.tools import register_book_tools

from .cto_session import SessionStop, run_long_session

logger = logging.getLogger(__name__)


def run_foreground(
    project_id: str,
    *,
    config: RunConfig,
    max_iterations: Optional[int] = None,
    iteration_pause_seconds: float = 0.0,
) -> int:
    """Run the CTO session attached to the current shell.

    Installs a small ``SIGINT`` handler so Ctrl+C drops a graceful
    ``stop_requested`` event into the loop rather than killing mid-tool.
    Returns the iteration count.
    """
    # Tools must be in the SDK registry before any AIAgent() spins up.
    register_book_tools()

    stop = SessionStop()

    previous_handler = signal.getsignal(signal.SIGINT)

    def _on_sigint(signum, frame):  # noqa: ARG001
        if stop.requested():
            # Second Ctrl+C inside the grace window — restore default and
            # let the next signal terminate the process.
            signal.signal(signal.SIGINT, signal.SIG_DFL)
            return
        print("\n[omoikane] stop requested; finishing current iteration...", flush=True)
        stop.request("sigint")

    signal.signal(signal.SIGINT, _on_sigint)
    try:
        return run_long_session(
            project_id,
            config=config,
            stop=stop,
            max_iterations=max_iterations,
            iteration_pause_seconds=iteration_pause_seconds,
        )
    finally:
        signal.signal(signal.SIGINT, previous_handler)


__all__ = ["run_foreground"]
