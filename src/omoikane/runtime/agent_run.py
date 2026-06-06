"""``AgentRun`` — hermes-agent ``AIAgent`` wrapper with Omoikane wiring.

One ``AgentRun`` instance represents either the long-lived CTO or a
delegated specialist that we explicitly drive (rare in Mode A — the SDK's
``delegate_task`` builds child agents itself; we mostly use AgentRun for
the CTO and for unit-test scaffolding).

The wrapper wires every SDK callback into :class:`ActivityEmitter` so
the operator's TUI gets a live view of tool calls, status events, and
streamed assistant text, and drains :class:`InboxDrainer` at iteration
boundaries to feed operator-typed context into ``agent.steer``.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional

from omoikane.runtime import activity_emitter as _activity
from omoikane.runtime import injection as _injection
from omoikane.runtime import prompts as _prompts
from omoikane.runtime import role_toolsets

logger = logging.getLogger(__name__)


@dataclass
class RunConfig:
    """Static configuration passed into :class:`AgentRun`.

    Pulled out of the constructor so callers (CLI, orchestrator, tests)
    can build it once per project and reuse it across iterations.
    """
    model: str
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    provider: Optional[str] = None
    max_iterations: int = 30
    save_trajectories: bool = False
    role_overrides: Optional[Mapping[str, List[str]]] = None
    extra_agent_kwargs: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RunResult:
    """Return value of :meth:`AgentRun.run_iteration`."""
    final_response: str
    messages: List[Dict[str, Any]]
    drained_inject_count: int = 0
    error: Optional[str] = None


class AgentRun:
    """Stateful wrapper around one ``AIAgent`` instance.

    Construction is deferred until :meth:`ensure_agent` so tests can
    inspect the resolved toolsets / system prompt without paying the
    cost of the SDK import.
    """

    def __init__(
        self,
        project_id: str,
        role: str,
        *,
        book: Mapping[str, Any],
        config: RunConfig,
        emitter: Optional[_activity.ActivityEmitter] = None,
        inbox: Optional[_injection.InboxDrainer] = None,
        conversation_history: Optional[List[Dict[str, Any]]] = None,
        system_prompt_builder: Optional[Callable[[str, Mapping[str, Any], List[str]], str]] = None,
    ):
        self.project_id = project_id
        self.role = role
        self.config = config
        self.emitter = emitter or _activity.for_project(project_id)
        self.inbox = inbox or _injection.InboxDrainer(project_id)
        self.history: List[Dict[str, Any]] = list(conversation_history or [])

        if role == "agent-cto":
            self.toolsets = role_toolsets.cto_toolsets(self.config.role_overrides)
        else:
            self.toolsets = role_toolsets.toolsets_for(role, overrides=self.config.role_overrides)

        builder = system_prompt_builder or _prompts.build_cto_system_prompt
        self.system_prompt = builder(project_id, book, enabled_toolsets=self.toolsets)

        self._agent: Any = None  # lazy AIAgent

    # ------------------------------------------------------------------
    # Agent construction
    # ------------------------------------------------------------------
    def ensure_agent(self) -> Any:
        """Build the underlying ``AIAgent`` if needed and return it."""
        if self._agent is not None:
            return self._agent
        from run_agent import AIAgent  # type: ignore

        kwargs: Dict[str, Any] = {
            "model": self.config.model,
            "api_key": self.config.api_key,
            "base_url": self.config.base_url or None,
            "provider": self.config.provider or None,
            "enabled_toolsets": self.toolsets,
            "ephemeral_system_prompt": self.system_prompt,
            "max_iterations": self.config.max_iterations,
            "quiet_mode": True,
            "save_trajectories": self.config.save_trajectories,
            "skip_context_files": True,
            "skip_memory": True,
            "stream_delta_callback": self._on_stream_delta,
            "tool_start_callback": self._on_tool_start,
            "tool_complete_callback": self._on_tool_complete,
            "step_callback": self._on_step,
            "status_callback": self._on_status,
            "notice_callback": self._on_notice,
        }
        kwargs.update(self.config.extra_agent_kwargs)
        kwargs = {k: v for k, v in kwargs.items() if v is not None}
        self._agent = AIAgent(**kwargs)
        return self._agent

    # ------------------------------------------------------------------
    # Iteration
    # ------------------------------------------------------------------
    def run_iteration(
        self,
        user_message: str,
        *,
        task_id: Optional[str] = None,
        drain_target: Optional[str] = None,
    ) -> RunResult:
        """Run one ``AIAgent.run_conversation`` turn.

        Drains the inbox once BEFORE the call (so any messages staged
        while the orchestrator was sleeping land in this iteration's
        directive) and again from within ``_on_step`` to catch live
        operator input across the iteration boundary.
        """
        target = drain_target or self.role
        injects = self.inbox.drain(target=target)
        if injects:
            for entry in injects:
                self.emitter.operator_steer(entry.get("content") or "", target=target)
            user_message = _prompts.prepend_injects(user_message, injects)

        agent = self.ensure_agent()

        started = time.monotonic()
        try:
            result = agent.run_conversation(
                user_message=user_message,
                task_id=task_id or f"{self.project_id}-{self.role}",
                conversation_history=self.history,
            )
        except Exception as exc:  # noqa: BLE001 - rare SDK failures
            logger.exception("AIAgent.run_conversation raised")
            self.emitter.error(self.role, f"agent_error: {exc}")
            return RunResult(
                final_response="",
                messages=list(self.history),
                drained_inject_count=len(injects),
                error=str(exc),
            )
        finally:
            duration = time.monotonic() - started
            logger.debug("iteration finished in %.2fs", duration)

        self.history = result.get("messages", self.history)
        return RunResult(
            final_response=result.get("final_response") or "",
            messages=self.history,
            drained_inject_count=len(injects),
            error=None,
        )

    def steer(self, text: str) -> bool:
        """Forward an inject to the underlying agent's ``steer`` channel.

        Returns ``True`` if the agent accepted the steer text. Safe to
        call before :meth:`ensure_agent` — buffers via the inbox until
        the agent exists.
        """
        if not text:
            return False
        if self._agent is None:
            self.inbox.append(text, target=self.role)
            return True
        try:
            return bool(self._agent.steer(text))
        except Exception:
            logger.exception("agent.steer failed")
            return False

    # ------------------------------------------------------------------
    # Callback wiring — all defensive; failures must never break the run.
    # ------------------------------------------------------------------
    def _on_stream_delta(self, delta: str, *_a: Any, **_k: Any) -> None:
        try:
            self.emitter.stream_delta(self.role, delta or "")
        except Exception:
            logger.exception("stream_delta_callback failed")

    def _on_tool_start(self, *args: Any, **kwargs: Any) -> None:
        # SDK call signature: (event, name, preview, args) per Phase-0 spike D.
        name, args_payload = _extract_tool_args(args, kwargs)
        try:
            self.emitter.tool_start(self.role, name, args_payload)
        except Exception:
            logger.exception("tool_start_callback failed")

    def _on_tool_complete(self, *args: Any, **kwargs: Any) -> None:
        name, result_payload, duration_ms, is_error = _extract_tool_result(args, kwargs)
        try:
            self.emitter.tool_complete(
                self.role, name, result_payload,
                duration_ms=duration_ms, is_error=is_error,
            )
        except Exception:
            logger.exception("tool_complete_callback failed")

    def _on_step(self, *_a: Any, **_k: Any) -> None:
        """Drain inbox between iterations and steer fresh entries."""
        try:
            injects = self.inbox.drain(target=self.role)
            if not injects:
                return
            text = _prompts.format_inject(injects)
            if not text or self._agent is None:
                return
            if self._agent.steer(text):
                for entry in injects:
                    self.emitter.operator_steer(entry.get("content") or "", target=self.role)
        except Exception:
            logger.exception("step_callback drain failed")

    def _on_status(self, *args: Any, **kwargs: Any) -> None:
        try:
            event_type = (args[0] if args else kwargs.get("event_type")) or "lifecycle"
            detail = args[1] if len(args) > 1 else kwargs.get("detail")
            self.emitter.status(self.role, str(event_type), detail and str(detail))
        except Exception:
            logger.exception("status_callback failed")

    def _on_notice(self, *args: Any, **kwargs: Any) -> None:
        try:
            message = args[0] if args else kwargs.get("message") or ""
            self.emitter.notice(self.role, str(message))
        except Exception:
            logger.exception("notice_callback failed")


# ----------------------------------------------------------------------
# Tiny extraction helpers — the SDK's callback positional arguments are
# documented in Phase-0 spike D (tools/delegate_tool.py:1169 region).
# We tolerate both positional + kwarg forms because future SDK versions
# may reshuffle.
# ----------------------------------------------------------------------

def _extract_tool_args(args: tuple, kwargs: dict):
    """Tolerate ``(tool_id, name, args_payload)`` and ``(event, name, preview, args)``."""
    name = kwargs.get("name")
    payload = kwargs.get("args") or kwargs.get("args_preview")
    if args:
        # ("tool.started", name, preview, args)  OR  (name, args)
        if args[0] in {"tool.started", "tool.start"}:
            name = name or (args[1] if len(args) > 1 else "")
            payload = payload if payload is not None else (args[3] if len(args) > 3 else (args[2] if len(args) > 2 else None))
        else:
            name = name or args[0]
            payload = payload if payload is not None else (args[1] if len(args) > 1 else None)
    return str(name or "?"), payload


def _extract_tool_result(args: tuple, kwargs: dict):
    name = kwargs.get("name")
    result = kwargs.get("result")
    duration = kwargs.get("duration_ms") or kwargs.get("duration")
    is_error = bool(kwargs.get("is_error"))
    if args:
        if args[0] in {"tool.completed", "tool.complete"}:
            name = name or (args[1] if len(args) > 1 else "")
            # ("tool.completed", name, None, None, duration=..., is_error=..., result=...)
            for token in args[2:]:
                if isinstance(token, (int, float)) and duration is None:
                    duration = float(token)
                elif isinstance(token, bool):
                    is_error = bool(token)
                elif result is None:
                    result = token
        else:
            name = name or args[0]
            if len(args) > 1 and result is None:
                result = args[1]
            if len(args) > 2 and duration is None:
                duration = args[2]
    return str(name or "?"), result, duration, is_error


__all__ = [
    "AgentRun",
    "RunConfig",
    "RunResult",
]
