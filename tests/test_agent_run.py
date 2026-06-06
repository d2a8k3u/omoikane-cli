"""AgentRun + cto_session — exercised with a fake AIAgent to avoid live LLM."""
from __future__ import annotations

import json
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


class CallbackFiringAgent(FakeAIAgent):
    """Fake that actually invokes the SDK callbacks AgentRun registers.

    AgentRun passes its callbacks into ``AIAgent(**kwargs)`` (see
    ``ensure_agent``). A real SDK calls them while a turn is running; this
    fake captures them from the constructor kwargs and fires them inside
    ``run_conversation`` so the emitter side-effects + the mid-iteration
    ``_on_step`` inbox-drain/steer path are exercised (Finding C3).

    ``on_step_extra`` lets a test stage operator input right before the
    ``step_callback`` fires — modelling an operator typing mid-run."""

    on_step_extra = None  # callable() -> None, run just before step_callback

    def run_conversation(self, **kw):
        cb = self.kwargs
        sd = cb.get("stream_delta_callback")
        if sd:
            sd("hello world")
        ts = cb.get("tool_start_callback")
        if ts:
            ts("tool.started", "shell", "ls -la", {"cmd": "ls -la"})
        tc = cb.get("tool_complete_callback")
        if tc:
            tc("tool.completed", "shell", None, None, 12.5, False, "total 0")
        if type(self).on_step_extra is not None:
            type(self).on_step_extra()
        step = cb.get("step_callback")
        if step:
            step()
        return super().run_conversation(**kw)


def test_callbacks_stream_delta_reaches_activity(temp_hermes_home, fake_sdk):
    book = ProjectBook.create("brief", ["AC1"])
    fake_sdk.AIAgent = CallbackFiringAgent
    sys.modules["run_agent"].AIAgent = CallbackFiringAgent

    run = _build_run(book)
    run.run_iteration("directive", task_id="t-1")

    text = _activity.for_project(book.project_id).path.read_text(encoding="utf-8")
    assert "assistant_delta" in text
    assert "hello world" in text


def test_callbacks_tool_start_and_complete_reach_activity(temp_hermes_home, fake_sdk):
    book = ProjectBook.create("brief", ["AC1"])
    sys.modules["run_agent"].AIAgent = CallbackFiringAgent

    run = _build_run(book)
    run.run_iteration("directive", task_id="t-1")

    lines = _activity.for_project(book.project_id).path.read_text(
        encoding="utf-8"
    ).splitlines()
    kinds = {json.loads(line)["kind"] for line in lines if "actor" not in json.loads(line)}
    assert "tool_call" in kinds
    assert "tool_output" in kinds
    # The tool name survived extraction from the positional callback form.
    tool_lines = [json.loads(l) for l in lines if json.loads(l).get("kind") == "tool_call"]
    assert any(rec.get("tool") == "shell" for rec in tool_lines)


def test_on_step_drains_inbox_and_steers_mid_run(temp_hermes_home, fake_sdk):
    """The operator-inject mechanism from the vision: a message that lands
    *during* a turn must be drained by ``_on_step`` and pushed to
    ``agent.steer`` as the formatted OPERATOR STEER block, with a matching
    ``operator_steer`` activity event emitted."""
    book = ProjectBook.create("brief", ["AC1"])

    class _Agent(CallbackFiringAgent):
        # Stage the operator message right before step_callback fires so the
        # pre-iteration drain in run_iteration doesn't swallow it.
        on_step_extra = staticmethod(
            lambda: write_message(book.project_id, "switch to uuid v7", target="agent-cto")
        )

    sys.modules["run_agent"].AIAgent = _Agent

    run = _build_run(book)
    run.run_iteration("directive", task_id="t-1")

    fake = fake_sdk.instances[-1]
    # _on_step called agent.steer with the formatted inject block.
    assert any("=== OPERATOR STEER ===" in s for s in fake.steers)
    assert any("switch to uuid v7" in s for s in fake.steers)
    # And the steer was mirrored into the activity stream.
    text = _activity.for_project(book.project_id).path.read_text(encoding="utf-8")
    assert "operator_steer" in text
    assert "switch to uuid v7" in text


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
