"""Shared data model — Task dataclass."""

from dataclasses import dataclass, field, asdict
from datetime import datetime


def _now_iso() -> str:
    return datetime.now().isoformat()


@dataclass
class Task:
    id: int
    text: str
    status: str = "pending"  # "pending" | "done"
    created_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Task":
        return cls(**d)
