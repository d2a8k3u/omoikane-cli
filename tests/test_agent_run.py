"""AgentRun + cto_session — exercised with a fake AIAgent to avoid live LLM."""
from __future__ import annotations

import sys
import types
from typing import Any, Dict, List

import pytest

from omoikane.core.book import ProjectBook
from omoikane.runtime import activity_emitter as _activity
from omoikane.runtime.agent_run import AgentRun, RunConfig
from omoikane.runtime.injection import InboxDrainer, write_message


@pytest.fixture(autouse=True)
def _reset_emitter_cache():
    _activity.reset_cache_for_tests()
    yield
    _activity.reset_cache_for_tests()


class FakeAIAgent:
    """Records constructor kwargs and emulates ``run_conversation`` + ``steer``."""

    instances: List["FakeAIAgent"] = []

    def __init__(self, **kwargs: Any):
        self.kwargs = kwargs
        self.steers: List[str] = []
        self.iterations: List[Dict[str, Any]] = []
        FakeAIAgent.instances.append(self)

    def run_conversation(self, *, user_message: str, task_id: str = None,
                         conversation_history=None, **_):
        history = list(conversation_history or [])
        history.append({"role": "user", "content": user_message})
        history.append({"role": "assistant", "content": "ok"})
        self.iterations.append({
            "user_message": user_message,
            "task_id": task_id,
        })
        return {"final_response": "ok", "messages": history}

    def steer(self, text: str) -> bool:
        if text:
            self.steers.append(text)
            return True
        return False


@pytest.fixture
def fake_sdk(monkeypatch):
    FakeAIAgent.instances.clear()
    fake_module = types.ModuleType("run_agent")
    fake_module.AIAgent = FakeAIAgent
    monkeypatch.setitem(sys.modules, "run_agent", fake_module)
    yield FakeAIAgent
    FakeAIAgent.instances.clear()


def _build_run(book: ProjectBook, **overrides):
    config = RunConfig(model="fake/model", api_key="dummy", max_iterations=5)
    return AgentRun(
        book.project_id,
        role="agent-cto",
        book=book.load(),
        config=config,
        **overrides,
    )


def test_run_iteration_calls_fake_agent(temp_hermes_home, fake_sdk):
    book = ProjectBook.create("brief", ["AC1"])
    run = _build_run(book)
    result = run.run_iteration("hello", task_id="t-1")
    assert result.final_response == "ok"
    assert result.drained_inject_count == 0
    assert fake_sdk.instances[-1].iterations[0]["user_message"].startswith("hello")


def test_drains_inbox_before_iteration(temp_hermes_home, fake_sdk):
    book = ProjectBook.create("brief", ["AC1"])
    write_message(book.project_id, "use uuid v7")

    run = _build_run(book)
    result = run.run_iteration("directive", task_id="t-1")
    assert result.drained_inject_count == 1
    fake = fake_sdk.instances[-1]
    sent_message = fake.iterations[0]["user_message"]
    assert "use uuid v7" in sent_message
    assert sent_message.endswith("directive")
    # Activity stream records the steer event.
    emitter = _activity.for_project(book.project_id)
    assert "operator_steer" in emitter.path.read_text(encoding="utf-8")


def test_subsequent_drains_do_not_repeat(temp_hermes_home, fake_sdk):
    book = ProjectBook.create("brief", ["AC1"])
    write_message(book.project_id, "first")

    run = _build_run(book)
    first = run.run_iteration("directive", task_id="t-1")
    second = run.run_iteration("directive 2", task_id="t-2")
    assert first.drained_inject_count == 1
    assert second.drained_inject_count == 0


def test_steer_buffers_to_inbox_before_agent_exists(temp_hermes_home, fake_sdk):
    book = ProjectBook.create("brief", ["AC1"])
    run = _build_run(book)
    assert run.steer("pre-iteration nudge") is True
    drainer = InboxDrainer(book.project_id)
    drained = drainer.drain(target="agent-cto")
    assert drained and drained[0]["content"] == "pre-iteration nudge"


def test_cto_session_terminates_on_done(temp_hermes_home, fake_sdk):
    from omoikane.orchestrator import cto_session

    book = ProjectBook.create("brief", ["AC1"])
    # Fake agent that marks the project done after its first iteration.
    base_book = book

    class DoneFakeAgent(FakeAIAgent):
        def run_conversation(self, *, user_message, task_id=None,
                             conversation_history=None, **kw):
            result = super().run_conversation(
                user_message=user_message,
                task_id=task_id,
                conversation_history=conversation_history,
                **kw,
            )
            base_book.satisfy_criterion(0)
            return result

    fake_module = sys.modules["run_agent"]
    fake_module.AIAgent = DoneFakeAgent

    config = RunConfig(model="fake/model", api_key="dummy", max_iterations=4)
    iterations = cto_session.run_long_session(
        book.project_id, config=config, max_iterations=4,
    )
    assert iterations == 1
    # Reload and confirm.
    assert book.load()["status"] == "done"


def test_cto_session_respects_max_iterations(temp_hermes_home, fake_sdk):
    from omoikane.orchestrator import cto_session

    book = ProjectBook.create("brief", ["AC1"])
    config = RunConfig(model="fake/model", api_key="dummy", max_iterations=10)
    iterations = cto_session.run_long_session(
        book.project_id, config=config, max_iterations=3,
    )
    assert iterations == 3


def test_cto_session_stop_event_breaks_loop(temp_hermes_home, fake_sdk):
    from omoikane.orchestrator import cto_session

    book = ProjectBook.create("brief", ["AC1"])
    stop = cto_session.SessionStop()

    fake_module = sys.modules["run_agent"]

    class StoppingAgent(FakeAIAgent):
        def run_conversation(self, **kw):
            stop.request("test")
            return super().run_conversation(**kw)

    fake_module.AIAgent = StoppingAgent

    config = RunConfig(model="fake/model", api_key="dummy", max_iterations=10)
    iterations = cto_session.run_long_session(
        book.project_id, config=config, stop=stop, max_iterations=10,
    )
    assert iterations == 1
