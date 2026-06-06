"""
Omoikane - Execution mode decision logic (M5)

Provides ``choose_execution_mode`` and a structured ``ExecutionMetadata``
datatype so callers can supply explicit signals (estimated minutes, network
needs, dangerous commands, etc.) instead of relying solely on title-keyword
heuristics.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional

ExecutionMode = Literal["in_process", "isolated"]

_ISOLATED_KEYWORDS: List[str] = [
    # Build / compile
    "build",
    "compile",
    "docker build",
    "container build",
    "image build",
    # Test suites & long-running verification
    "test suite",
    "integration test",
    "e2e test",
    "end to end test",
    "benchmark",
    "performance test",
    "load test",
    "stress test",
    "security scan",
    "audit",
    # Deploy / release
    "deploy",
    "release",
    "publish",
    # Package / network installs
    "npm install",
    "pip install",
    "poetry install",
    "apt-get install",
    "yarn install",
    # Background / long-running
    "long running",
    "background",
    "cron job",
    "scheduled task",
    "recurring",
    "daemon",
    # Multi-agent / cross-project
    "multiple agents",
    "full project",
    "cross-project",
    "multi-service",
    # Infrastructure / destructive
    "terraform apply",
    "terraform destroy",
    "provision",
    "infrastructure",
    "restart service",
    "reboot server",
    "systemctl",
    "wipe",
    "delete all",
    # Data / ML heavy
    "database migration",
    "schema migration",
    "seed data",
    "train model",
    "fine-tune",
    "dataset preparation",
    "large file",
    "multi-gb",
    "batch process",
]


@dataclass
class ExecutionMetadata:
    """Structured metadata used to drive execution-mode decisions.

    Optional boolean fields distinguish "explicitly set to False" from
    "not present at all".  This matters for the
    ``has_explicit_metadata`` gate that suppresses the keyword fallback.
    """
    title: str = ""
    expected: str = ""
    estimated_minutes: Optional[int] = None
    requires_network: Optional[bool] = None
    dangerous_commands: Optional[bool] = None
    background: Optional[bool] = None

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "ExecutionMetadata":
        """Coerce an arbitrary dict (e.g. ``task_meta``) into an
        ``ExecutionMetadata`` instance. Unknown keys are ignored."""
        if data is None:
            return cls()
        return cls(
            title=str(data.get("title") or ""),
            expected=str(data.get("expected") or ""),
            estimated_minutes=data.get("estimated_minutes"),
            requires_network=data.get("requires_network"),
            dangerous_commands=data.get("dangerous_commands"),
            background=data.get("background"),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a plain dict, dropping ``None`` entries."""
        out: Dict[str, Any] = {
            "title": self.title,
            "expected": self.expected,
        }
        if self.estimated_minutes is not None:
            out["estimated_minutes"] = self.estimated_minutes
        if self.requires_network is not None:
            out["requires_network"] = self.requires_network
        if self.dangerous_commands is not None:
            out["dangerous_commands"] = self.dangerous_commands
        if self.background is not None:
            out["background"] = self.background
        return out

    def has_explicit_metadata(self) -> bool:
        """True when any structured field was explicitly set."""
        return (
            self.estimated_minutes is not None
            or self.requires_network is not None
            or self.dangerous_commands is not None
            or self.background is not None
        )


def choose_execution_mode(task_meta: Optional[Dict[str, Any]] = None) -> ExecutionMode:
    """Decide whether a task should run in-process or isolated.

    Structured metadata (``task_meta``) wins over keyword heuristics.
    Supported metadata fields:
      - ``estimated_minutes`` (int): >= 10 forces isolated
      - ``requires_network`` (bool): True forces isolated
      - ``dangerous_commands`` (bool): True forces isolated
      - ``background`` (bool): True forces isolated
      - ``title`` (str): used for keyword fallback when no metadata is provided
      - ``expected`` (str): additional text checked for keywords when title
        is vague

    If any structured metadata field is explicitly provided and does not
    indicate isolation, the task defaults to ``in_process`` (skipping
    keyword matching). This gives the CTO / agent explicit control.
    """
    meta = ExecutionMetadata.from_dict(task_meta)
    text = f"{meta.title} {meta.expected}".strip().lower()

    # 1. Explicit isolation metadata — always wins
    if meta.estimated_minutes is not None and meta.estimated_minutes >= 10:
        return "isolated"
    if meta.requires_network is True:
        return "isolated"
    if meta.dangerous_commands is True:
        return "isolated"
    if meta.background is True:
        return "isolated"

    # 2. Metadata was explicitly provided and does not indicate isolation
    #    → trust metadata and skip keyword fallback (metadata wins).
    if meta.has_explicit_metadata():
        return "in_process"

    # 3. No metadata — fall back to title + expected keyword heuristics.
    for keyword in _ISOLATED_KEYWORDS:
        if keyword in text:
            return "isolated"

    return "in_process"
