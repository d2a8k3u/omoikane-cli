"""Deterministic orchestration driver (cto_session.run_long_session).

The driver — not the LLM — drives delegation: run_once() plans the next task,
a focused AgentRun executes it, and the driver closes it deterministically.
These tests pin: the completion gate, deterministic task-closing even when the
agent does nothing, the QA verification pass, the no-progress breaker, stop
handling, and AgentRun.cancel() wiring.

A fake ``run_agent`` module is installed into ``sys.modules`` so
``AgentRun.ensure_agent`` builds the fake instead of the real hermes SDK.
"""
from __future__ import annotations

import sys
import types
from typing import Any, Dict, List

import pytest

from omoikane.core.book import ProjectBook
from omoikane.runtime import activity_emitter as _activity
from omoikane.runtime.agent_run import AgentRun, RunConfig


@pytest.fixture(autouse=True)
def _reset_emitter_cache():
    _activity.reset_cache_for_tests()
    yield
    _activity.reset_cache_for_tests()


class _BaseFakeAgent:
    """Minimal AIAgent stand-in. By default a no-op turn (touches no book)."""

    instances: List["_BaseFakeAgent"] = []

    def __init__(self, **kwargs: Any):
        self.kwargs = kwargs
        _BaseFakeAgent.instances.append(self)

    def run_conversation(self, *, user_message: str, task_id: str = None,
                         conversation_history=None, **_):
        history = list(conversation_history or [])
        history.append({"role": "user", "content": user_message})
        history.append({"role": "assistant", "content": "ok"})
        return {"final_response": "ok", "messages": history}

    def steer(self, text: str) -> bool:
        return bool(text)

    def interrupt(self, message: str = None) -> None:  # noqa: ARG002
        pass


def _install_fake(monkeypatch, agent_cls) -> None:
    _BaseFakeAgent.instances = []
    fake_module = types.ModuleType("run_agent")
    fake_module.AIAgent = agent_cls
    monkeypatch.setitem(sys.modules, "run_agent", fake_module)


def _cfg() -> RunConfig:
    return RunConfig(model="fake/model", api_key="dummy")


# ---------------------------------------------------------------------------
# Completion gate
# ---------------------------------------------------------------------------
def test_completes_after_a_clean_completeness_pass(
    temp_hermes_home, monkeypatch,
):
    # Criteria satisfied + no open tasks does NOT finish immediately: the
    # bounded completeness pass runs once. A no-op reviewer adds nothing →
    # the pass is clean → the project completes on the next gate check.
    from omoikane.orchestrator import cto_session

    book = ProjectBook.create("brief", ["AC1"])
    book.satisfy_criterion(0)
    book.update_status("in_progress")
    _install_fake(monkeypatch, _BaseFakeAgent)

    iterations = cto_session.run_long_session(book.project_id, config=_cfg())

    assert iterations == 1  # exactly one completeness pass, then done
    assert len(_BaseFakeAgent.instances) == 1  # the completeness reviewer
    data = book.load()
    assert data["status"] == "done"
    assert data["completeness_clean"] is True
    assert data["completeness_passes"] == 1


# ---------------------------------------------------------------------------
# Deterministic execution: the driver closes an executor task even when the
# focused agent does nothing (the weak-model failure mode).
# ---------------------------------------------------------------------------
def test_driver_closes_executor_task_even_if_agent_is_noop(
    temp_hermes_home, monkeypatch,
):
    from omoikane.orchestrator import cto_session

    book = ProjectBook.create("brief", ["AC1"])
    book.update_status("in_progress")
    tid = book.open_task("do the work", assignee_role="agent-backend-engineer",
                         phase="implementation")
    _install_fake(monkeypatch, _BaseFakeAgent)  # no-op agent

    iterations = cto_session.run_long_session(
        book.project_id, config=_cfg(), max_iterations=1,
    )

    assert iterations == 1
    assert _BaseFakeAgent.instances, "a focused specialist run was spawned"
    assert tid in book.load()["completed_tasks"]  # driver closed it deterministically


# ---------------------------------------------------------------------------
# QA pass: built but unverified → qa-reviewer satisfies criteria → done.
# ---------------------------------------------------------------------------
def test_qa_pass_satisfies_criteria_and_completes(temp_hermes_home, monkeypatch):
    from omoikane.orchestrator import cto_session

    book = ProjectBook.create("brief", ["AC1"])
    book.update_status("in_progress")  # no open tasks, criterion pending

    class QASatisfyingAgent(_BaseFakeAgent):
        def run_conversation(self, **kw):
            result = super().run_conversation(**kw)
            book.satisfy_criterion(0)
            return result

    _install_fake(monkeypatch, QASatisfyingAgent)

    cto_session.run_long_session(book.project_id, config=_cfg(), max_iterations=5)

    assert book.all_criteria_satisfied()
    assert book.load()["status"] == "done"


# ---------------------------------------------------------------------------
# No-progress breaker: nothing ever advances → declared blocked, not infinite.
# ---------------------------------------------------------------------------
def test_no_progress_breaker_marks_blocked(temp_hermes_home, monkeypatch):
    from omoikane.orchestrator import cto_session

    book = ProjectBook.create("brief", ["AC1"])
    book.update_status("in_progress")  # no open tasks, criterion pending, no-op QA
    _install_fake(monkeypatch, _BaseFakeAgent)

    iterations = cto_session.run_long_session(book.project_id, config=_cfg())

    assert iterations == cto_session._NO_PROGRESS_LIMIT
    assert book.load()["status"] == "failed"


# ---------------------------------------------------------------------------
# Stop handling
# ---------------------------------------------------------------------------
def test_stop_requested_before_loop_returns_immediately(temp_hermes_home, monkeypatch):
    from omoikane.orchestrator import cto_session

    book = ProjectBook.create("brief", ["AC1"])
    book.update_status("in_progress")
    book.open_task("work", assignee_role="agent-backend-engineer", phase="implementation")
    _install_fake(monkeypatch, _BaseFakeAgent)

    stop = cto_session.SessionStop()
    stop.request("preempt")
    iterations = cto_session.run_long_session(book.project_id, config=_cfg(), stop=stop)

    assert iterations == 0
    assert _BaseFakeAgent.instances == []


# ---------------------------------------------------------------------------
# Empty-criteria backstop: a brief-only project whose analyst never writes
# criteria must fail loudly after one derivation retry, NOT spin the QA pass.
# ---------------------------------------------------------------------------
def test_empty_criteria_backstop_blocks_after_one_retry(temp_hermes_home, monkeypatch):
    from omoikane.orchestrator import cto_session

    book = ProjectBook.create("brief", [])  # no completion contract
    book.update_status("in_progress")
    _install_fake(monkeypatch, _BaseFakeAgent)  # never writes criteria

    iterations = cto_session.run_long_session(
        book.project_id, config=_cfg(), max_iterations=20,
    )

    data = book.load()
    assert data["status"] == "failed"
    assert data["derivation_retries"] >= 1
    assert iterations < 10  # bounded — did not loop the QA pass against zero criteria


# ---------------------------------------------------------------------------
# Completeness loop: a pass that finds a gap appends a criterion; QA satisfies
# it; the next pass is clean → done (loop-until-clean, bounded).
# ---------------------------------------------------------------------------
def test_completeness_loop_appends_gap_then_converges(temp_hermes_home, monkeypatch):
    from omoikane.orchestrator import cto_session

    book = ProjectBook.create("brief", ["AC1"])
    book.satisfy_criterion(0)
    book.update_status("in_progress")

    class CompletenessFake(_BaseFakeAgent):
        gaps_added = 0

        def run_conversation(self, *, user_message, **kw):
            result = super().run_conversation(user_message=user_message, **kw)
            if "COMPLETENESS pass" in user_message:
                if type(self).gaps_added == 0:
                    type(self).gaps_added += 1
                    book.set_criteria([
                        {"text": "edge case covered", "provenance": "synthesized"},
                    ])
            elif "QA reviewer for project" in user_message:
                d = book.load()
                for i in range(len(d["acceptance_criteria"])):
                    if d["criteria_status"].get(str(i)) != "satisfied":
                        book.satisfy_criterion(i, evidence="verified")
            return result

    _install_fake(monkeypatch, CompletenessFake)
    cto_session.run_long_session(book.project_id, config=_cfg(), max_iterations=20)

    data = book.load()
    assert data["status"] == "done"
    assert data["completeness_clean"] is True
    assert len(data["acceptance_criteria"]) == 2  # the gap was appended exactly once
    assert CompletenessFake.gaps_added == 1


# ---------------------------------------------------------------------------
# Completeness cap: an over-eager reviewer that finds a "gap" every pass must
# still terminate at the cap — bounded, never an infinite loop.
# ---------------------------------------------------------------------------
def test_completeness_cap_stops_unbounded_gap_finding(temp_hermes_home, monkeypatch):
    from omoikane.orchestrator import cto_session

    book = ProjectBook.create("brief", ["AC1"])
    book.satisfy_criterion(0)
    book.update_status("in_progress")

    class NeverCleanFake(_BaseFakeAgent):
        n = 0

        def run_conversation(self, *, user_message, **kw):
            result = super().run_conversation(user_message=user_message, **kw)
            if "COMPLETENESS pass" in user_message:
                type(self).n += 1
                book.set_criteria([
                    {"text": f"gap {type(self).n}", "provenance": "synthesized"},
                ])
            elif "QA reviewer for project" in user_message:
                d = book.load()
                for i in range(len(d["acceptance_criteria"])):
                    if d["criteria_status"].get(str(i)) != "satisfied":
                        book.satisfy_criterion(i, evidence="v")
            return result

    _install_fake(monkeypatch, NeverCleanFake)
    cto_session.run_long_session(book.project_id, config=_cfg(), max_iterations=50)

    data = book.load()
    assert data["status"] == "done"
    assert data["completeness_clean"] is False
    assert data["completeness_passes"] == cto_session._COMPLETENESS_PASS_CAP


def test_cancel_interrupts_the_live_agent(temp_hermes_home, monkeypatch):
    book = ProjectBook.create("brief", ["AC1"])

    class InterruptibleAgent(_BaseFakeAgent):
        interrupted = False

        def interrupt(self, message: str = None) -> None:  # noqa: ARG002
            type(self).interrupted = True

    _install_fake(monkeypatch, InterruptibleAgent)

    run = AgentRun(book.project_id, role="agent-backend-engineer",
                   book=book.load(), config=_cfg())
    run.ensure_agent()
    run.cancel()

    assert InterruptibleAgent.interrupted is True
