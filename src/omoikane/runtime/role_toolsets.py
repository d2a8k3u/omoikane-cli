"""Role → hermes-agent SDK toolset mapping.

The standalone Omoikane CLI dispatches specialists by calling the SDK's
built-in ``delegate_task`` from the CTO. Spike C in Phase 0 verified two
constraints we encode here:

1. The SDK's ``DELEGATE_BLOCKED_TOOLS`` strips ``code_execution`` from
   any child agent — so specialists that previously requested it must
   work through the ``terminal`` toolset instead (running ``python``,
   ``pytest``, ``npm`` etc. as shell commands).
2. The child agent's ``enabled_toolsets`` is intersected with the
   parent's, so the CTO itself must enable the union of every toolset
   any specialist might need. Anything missing from the CTO's set is
   silently dropped from the child by the SDK.

Operator overrides live in ``~/.omoikane/config.toml``:

.. code-block:: toml

    [role_toolsets]
    "agent-backend-engineer" = ["file", "terminal", "browser", "omoikane"]

Missing roles fall back to :data:`_BASE_TOOLSETS`. The ``omoikane`` toolset
is auto-appended to every role so they always have access to ``book_*``
tools for state persistence.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional

OMOIKANE_TOOLSET = "omoikane"

# Per-role default toolset assignments. Derived from
# ``plugins/omoikane/orchestrator.py:67-83`` with the Phase-0 substitution
# of ``code_execution`` → ``terminal`` for specialist roles (the SDK's
# delegate_task blocks code_execution for children regardless of intent).
_BASE_TOOLSETS: Dict[str, List[str]] = {
    "agent-product-analyst":     ["file", "web"],
    "agent-architekt":           ["file", "web"],
    "agent-designer":            ["file", "web", "browser"],
    "agent-backend-engineer":    ["file", "terminal"],
    "agent-frontend-engineer":   ["file", "terminal", "browser"],
    "agent-database-specialist": ["file", "terminal"],
    "agent-implementer":         ["file", "terminal"],
    "agent-devops":              ["file", "terminal"],
    "agent-security-engineer":   ["file", "terminal"],
    "agent-ai-engineer":         ["file", "terminal", "web"],
    "agent-ml-engineer":         ["file", "terminal"],
    "agent-analytik":            ["file", "terminal"],
    "agent-qa-reviewer":         ["file", "terminal"],
    "agent-tech-writer":         ["file", "web"],
    # Routable orchestrator that the CTO might delegate planning to.
    "orchestrator-protocol":     ["file"],
    # Manager runs as a leaf cleanup pass — same surface as a senior
    # reviewer plus terminal so it can verify acceptance.
    "agent-manager":             ["file", "terminal"],
    # CTO needs delegation + a superset of every specialist toolset so
    # child intersections preserve the requested tools.
    "agent-cto":                 ["file", "web", "browser", "terminal", "delegation"],
}

# Fallback used when an unknown role is requested. Intentionally narrow —
# better to fail closed than to grant terminal access by accident.
_FALLBACK = ["file"]


def base_toolsets() -> Mapping[str, List[str]]:
    """Read-only view of the built-in defaults."""
    return dict(_BASE_TOOLSETS)


def _ensure_omoikane(toolsets: Iterable[str]) -> List[str]:
    seen = []
    for ts in toolsets:
        if ts and ts not in seen:
            seen.append(ts)
    if OMOIKANE_TOOLSET not in seen:
        seen.append(OMOIKANE_TOOLSET)
    return seen


def toolsets_for(
    role: str,
    overrides: Optional[Mapping[str, Iterable[str]]] = None,
) -> List[str]:
    """Return the enabled-toolsets list for ``role``.

    ``overrides`` typically comes from ``config.toml`` (``[role_toolsets]``
    section). Empty list ``[]`` in the overrides means "use defaults".
    """
    if overrides and role in overrides:
        override = list(overrides[role] or [])
        if override:
            return _ensure_omoikane(override)
    base = _BASE_TOOLSETS.get(role) or list(_FALLBACK)
    return _ensure_omoikane(base)


def cto_toolsets(
    overrides: Optional[Mapping[str, Iterable[str]]] = None,
) -> List[str]:
    """Return the CTO's enabled-toolsets — superset of every specialist.

    Built from ``toolsets_for(role)`` over every defined role plus the
    ``delegation`` toolset, so an LLM-issued ``delegate_task`` can pass
    any specialist's required toolset through the parent intersection
    without losing tools.
    """
    union: List[str] = ["delegation"]
    for role in _BASE_TOOLSETS:
        for ts in toolsets_for(role, overrides=overrides):
            if ts not in union:
                union.append(ts)
    if OMOIKANE_TOOLSET not in union:
        union.append(OMOIKANE_TOOLSET)
    return union


def known_roles() -> List[str]:
    """List every role with a built-in default toolset."""
    return list(_BASE_TOOLSETS.keys())


def merge_overrides_from_config(config: Optional[Mapping[str, Any]]) -> Dict[str, List[str]]:
    """Validate and normalise the ``[role_toolsets]`` config section.

    Accepts ``None`` (no overrides) or a mapping ``role -> sequence``.
    Coerces each value into a list of strings, dropping empties. Unknown
    role names are kept so user-defined roles still register cleanly.
    """
    if not config:
        return {}
    out: Dict[str, List[str]] = {}
    for role, raw in config.items():
        if not isinstance(role, str) or not role:
            continue
        if isinstance(raw, str):
            values = [raw]
        else:
            try:
                values = list(raw)
            except TypeError:
                continue
        cleaned = [str(v) for v in values if isinstance(v, (str, bytes)) and str(v).strip()]
        if cleaned:
            out[role] = cleaned
    return out
