"""
Omoikane - Agent Registry
Loads all specialized agents bundled inside the package.
No external dependencies.
"""

import re
from importlib import resources
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional


def _resolve_agents_path() -> Path:
    """Locate the bundled ``data/agents/`` directory.

    Uses ``importlib.resources`` so the lookup works both for editable
    (``pip install -e .``) installs and for built wheels where the
    ``omoikane.data`` package data ships under ``site-packages``.
    """
    return Path(str(resources.files("omoikane.data") / "agents"))


# Module-level constant kept for backwards compatibility with the legacy
# plugin layout. Resolved at import time; tests may monkey-patch this.
AGENTS_PATH = _resolve_agents_path()

# Roles that are loadable (their SKILL.md is real and useful) but must never
# be surfaced as routable executors. The orchestrator's role-picker and the
# CTO's team roster filter these out so they cannot be misrouted to.
_LEAF_ONLY_ROLES = frozenset({"agent-manager"})

# Routable (their SKILL.md loads) but never a roster line: orchestrator-protocol
# is the loop's protocol doc, not an assignable executor. agent-manager is
# already filtered upstream by list_routable_roles via _LEAF_ONLY_ROLES.
_NON_ROSTER_ROLES = frozenset({"orchestrator-protocol"})

# Match the ``description:`` line in a SKILL.md frontmatter so the team roster
# stays in sync with each role's actual prompt — no separate metadata file.
_DESC_RE = re.compile(r"^description:\s*(.+?)\s*$", re.MULTILINE)


def _role_description(skill_md: str) -> str:
    """Extract the one-line role description from a SKILL.md frontmatter."""
    if not skill_md:
        return ""
    m = _DESC_RE.search(skill_md)
    return m.group(1).strip() if m else ""


class AgentRegistry:
    """Registry of all available specialized agents (fully bundled)."""

    def __init__(self):
        self._agents: Dict[str, str] = {}  # role_name -> SKILL.md content
        self._load_agents()

    def _load_agents(self):
        """Load all agents from the bundled agents/ directory."""
        if not AGENTS_PATH.exists():
            return

        for agent_dir in sorted(AGENTS_PATH.iterdir()):
            if not agent_dir.is_dir():
                continue

            skill_file = agent_dir / "SKILL.md"
            if skill_file.exists():
                try:
                    content = skill_file.read_text(encoding="utf-8")
                    self._agents[agent_dir.name] = content
                except Exception as e:
                    print(f"[Omoikane] Failed to load {agent_dir.name}: {e}")

    def list_roles(self) -> List[str]:
        """Return every loaded role, including leaf-only ones (e.g. agent-manager).

        Callers building a *routable* roster should use
        :meth:`list_routable_roles` instead so they cannot accidentally send
        general work to a role that should only be dispatched explicitly.
        """
        return list(self._agents.keys())

    def list_routable_roles(self) -> List[str]:
        """Roles eligible for CTO routing / heuristic role-picking.

        Excludes :data:`_LEAF_ONLY_ROLES` — these load (so the supervisor can
        still resolve their SKILL.md when it dispatches them by name) but
        must never be picked by general routing.
        """
        return [r for r in self._agents.keys() if r not in _LEAF_ONLY_ROLES]

    def get_skill_content(self, role: str) -> Optional[str]:
        """Return the full SKILL.md content for a given role."""
        return self._agents.get(role)

    def get_default_team(self) -> List[str]:
        """Return the recommended general-purpose development team.

        Ordering follows a typical project lifecycle: strategy → analysis →
        design → build → review → docs.
        """
        preferred = [
            "orchestrator-protocol",
            "agent-cto",
            "agent-product-analyst",
            "agent-architekt",
            "agent-designer",
            "agent-backend-engineer",
            "agent-frontend-engineer",
            "agent-database-specialist",
            "agent-implementer",
            "agent-devops",
            "agent-security-engineer",
            "agent-ai-engineer",
            "agent-ml-engineer",
            "agent-analytik",
            "agent-qa-reviewer",
            "agent-tech-writer",
        ]
        return [r for r in preferred if r in self._agents]


# Global singleton
_registry: Optional[AgentRegistry] = None


def get_registry() -> AgentRegistry:
    global _registry
    if _registry is None:
        _registry = AgentRegistry()
    return _registry


def reload_registry():
    """Force reload of all agents."""
    global _registry
    _registry = None
    return get_registry()


def render_team_roster(
    book_like: Optional[Mapping[str, Any]],
    *,
    registry: Optional[AgentRegistry] = None,
    exclude: Optional[str] = None,
) -> str:
    """Render the team roster shown to any agent that picks or suggests a role.

    Each line is ``- agent-<role>: <description> (open: N, done: M)``. The
    workload counters come from ``book_like`` (the project book dict:
    ``task_meta`` mapped against ``open_tasks`` / ``completed_tasks``) so the
    reader can see who is already loaded. Roles are listed ``sorted`` and
    exclude both :data:`_LEAF_ONLY_ROLES` (via
    :meth:`AgentRegistry.list_routable_roles`) and :data:`_NON_ROSTER_ROLES`,
    plus the optional ``exclude`` role (used by the CTO router to drop itself).

    ``book_like`` may be ``None`` or workload-free — every role then shows
    ``(open: 0, done: 0)``.
    """
    registry = registry or get_registry()
    book_like = book_like or {}
    meta = book_like.get("task_meta", {}) or {}
    open_set = set(book_like.get("open_tasks", []) or [])
    done_set = set(book_like.get("completed_tasks", []) or [])

    open_load: Dict[str, int] = {}
    done_load: Dict[str, int] = {}
    for task_id, t_meta in meta.items():
        assignee = (t_meta or {}).get("assignee_role")
        if not assignee:
            continue
        if task_id in open_set:
            open_load[assignee] = open_load.get(assignee, 0) + 1
        elif task_id in done_set:
            done_load[assignee] = done_load.get(assignee, 0) + 1

    lines: List[str] = []
    for role in sorted(registry.list_routable_roles()):
        if role == exclude or role in _NON_ROSTER_ROLES:
            continue
        desc = _role_description(registry.get_skill_content(role) or "")
        open_n = open_load.get(role, 0)
        done_n = done_load.get(role, 0)
        lines.append(f"- {role}: {desc} (open: {open_n}, done: {done_n})")
    return "\n".join(lines) if lines else "(no other roles available)"
