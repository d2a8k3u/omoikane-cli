"""cto_session.run_long_session — VISION dual exit gate.

The natural exit gate is: the loop ends when ``all_criteria_satisfied()``
AND there are no ``open_tasks`` — *without* relying on a ``max_iterations``
cap. These tests pin that dual-gate so a regression in either half of the
condition is caught (Finding C1).

Reuses the ``FakeAIAgent`` pattern + ``fake_sdk`` fixture shape from
``test_agent_run.py``: a fake ``run_agent`` module is installed into
``sys.modules`` so :meth:`AgentRun.ensure_agent` builds the fake instead
of importing the real hermes-agent SDK.
"""
from __future__ import annotations

import sys
import types
from typing import Any, Dict, List

import pytest

from omoikane.core.book import ProjectBook
from omoikane.runtime import activity_emitter as _activity
from omoikane.runtime.agent_run import RunConfig


@pytest.fixture(autouse=True)
def _reset_emitter_cache():
    _activity.reset_cache_for_tests()
    yield
    _activity.reset_cache_for_tests()


class _BaseFakeAgent:
    """Minimal AIAgent stand-in mirroring the one in test_agent_run.py."""

    instances: List["_BaseFakeAgent"] = []

    def __init__(self, **kwargs: Any):
        self.kwargs = kwargs
        self.steers: List[str] = []
        self.iterations: List[Dict[str, Any]] = []
        _BaseFakeAgent.instances.append(self)

    def run_conversation(self, *, user_message: str, task_id: str = None,
                         conversation_history=None, **_):
        history = list(conversation_history or [])
        history.append({"role": "user", "content": user_message})
        history.append({"role": "assistant", "content": "ok"})
        self.iterations.append({"user_message": user_message, "task_id": task_id})
        return {"final_response": "ok", "messages": history}

    def steer(self, text: str) -> bool:
        if text:
            self.steers.append(text)
            return True
        return False


def _install_fake(monkeypatch, agent_cls) -> None:
    fake_module = types.ModuleType("run_agent")
    fake_module.AIAgent = agent_cls
    monkeypatch.setitem(sys.modules, "run_agent", fake_module)


def test_natural_exit_when_criteria_satisfied_and_no_open_tasks(
    temp_hermes_home, monkeypatch,
):
    """Gate fires with max_iterations=None — both halves of the dual gate
    are satisfied after the first iteration, so the loop must stop."""
    from omoikane.orchestrator import cto_session

    book = ProjectBook.create("brief", ["AC1", "AC2"])

    class SatisfyingAgent(_BaseFakeAgent):
        def run_conversation(self, **kw):
            result = super().run_conversation(**kw)
            # Satisfy every criterion; leave open_tasks empty (none opened).
            book.satisfy_criterion(0)
            book.satisfy_criterion(1)
            return result

    _install_fake(monkeypatch, SatisfyingAgent)

    config = RunConfig(model="fake/model", api_key="dummy", max_iterations=4)
    iterations = cto_session.run_long_session(
        book.project_id, config=config, max_iterations=None,
    )

    assert iterations == 1
    assert book.load()["status"] == "done"


def test_no_exit_when_criteria_satisfied_but_open_task_remains(
    temp_hermes_home, monkeypatch,
):
    """Criteria satisfied but an open task remains → the gate must NOT fire
    on that account. The loop only ends because max_iterations caps it,
    and the book stays out of the terminal 'done' state."""
    from omoikane.orchestrator import cto_session

    book = ProjectBook.create("brief", ["AC1"])

    class SatisfyButLeaveTaskAgent(_BaseFakeAgent):
        _opened = False

        def run_conversation(self, **kw):
            result = super().run_conversation(**kw)
            book.satisfy_criterion(0)
            # Keep exactly one open task alive across every iteration so the
            # dual gate's "no open_tasks" half is always False.
            if not SatisfyButLeaveTaskAgent._opened:
                book.open_task("leftover work", assignee_role="agent-backend-engineer")
                SatisfyButLeaveTaskAgent._opened = True
            return result

    _install_fake(monkeypatch, SatisfyButLeaveTaskAgent)

    config = RunConfig(model="fake/model", api_key="dummy", max_iterations=10)
    iterations = cto_session.run_long_session(
        book.project_id, config=config, max_iterations=3,
    )

    assert iterations == 3
    assert book.all_criteria_satisfied()
    assert book.load()["open_tasks"]  # the leftover task is still open
    assert book.load()["status"] != "done"
