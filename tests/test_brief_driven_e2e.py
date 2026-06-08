"""End-to-end: a brief-ONLY project (no acceptance criteria supplied) drives
itself to done through the real deterministic driver.

Flow exercised:
  bootstrap → analyst derives criteria (book_set_criteria) → architect →
  CTO kickoff (roadmap + QA task) → QA satisfies criteria → bounded
  completeness pass (clean) → done.

A fake AIAgent plays whichever role the directive addresses, detected by
substrings in the dispatched user_message. The driver itself does the
routing, blocking, closing, and gating.
"""
from __future__ import annotations

import sys
import types
from typing import Any, List

from omoikane.core.book import ProjectBook
from omoikane.runtime import activity_emitter as _activity
from omoikane.runtime.agent_run import RunConfig


def _install(monkeypatch, agent_cls) -> None:
    fake_module = types.ModuleType("run_agent")
    fake_module.AIAgent = agent_cls
    monkeypatch.setitem(sys.modules, "run_agent", fake_module)


def test_brief_only_project_derives_criteria_and_reaches_done(temp_hermes_home, monkeypatch):
    _activity.reset_cache_for_tests()
    from omoikane.orchestrator import cto_session

    book = ProjectBook.create("Build a tiny greeter CLI", [])  # NO criteria
    book.update_status("created")  # let the driver bootstrap it

    seen = {"analyst": False, "architect": False, "kickoff": False, "qa": False}

    class TeamFake:
        instances: List[Any] = []
        roadmap_done = False

        def __init__(self, **kwargs: Any):
            TeamFake.instances.append(self)

        def run_conversation(self, *, user_message: str, task_id: str = None,
                             conversation_history=None, **_):
            msg = user_message
            # Detect the CURRENT assignment by its "Title:" line — upstream task
            # titles now leak into downstream context (that IS the cooperation
            # feature), so a substring-anywhere match would misfire.
            title = ""
            for line in msg.splitlines():
                if line.strip().startswith("Title:"):
                    title = line.split("Title:", 1)[1].strip()
                    break

            if title.startswith("Derive and extract acceptance criteria"):
                seen["analyst"] = True
                book.set_criteria([
                    {"text": "greeter prints 'hello, <name>'", "provenance": "synthesized"},
                    {"text": "missing name exits non-zero", "provenance": "synthesized"},
                ])
                book.reflect("User stories: greet by name.", task="analyst")
            elif title.startswith("Propose architecture"):
                seen["architect"] = True
                book.reflect("ADR: single-file argparse CLI.", task="architect")
            elif title.startswith("Kickoff:") and not TeamFake.roadmap_done:
                seen["kickoff"] = True
                TeamFake.roadmap_done = True
                n = len(book.load()["acceptance_criteria"])
                book.set_roadmap([{
                    "milestone_id": "m1", "title": "Greeter",
                    "description": "Implement + verify", "criteria_indices": list(range(n)),
                    "status": "planned",
                }])
                book.open_task("QA: verify greeter acceptance criteria",
                               assignee_role="agent-qa-reviewer", phase="review",
                               milestone_id="m1")
            elif title.startswith("QA: verify greeter") or "QA reviewer for project" in msg:
                seen["qa"] = True
                d = book.load()
                for i in range(len(d["acceptance_criteria"])):
                    if d["criteria_status"].get(str(i)) != "satisfied":
                        book.satisfy_criterion(i, evidence="manual check passes")
            # "COMPLETENESS pass" → no gaps → clean
            history = list(conversation_history or [])
            history.append({"role": "assistant", "content": "ok"})
            return {"final_response": "ok", "messages": history}

        def steer(self, text: str) -> bool:
            return bool(text)

        def interrupt(self, message: str = None) -> None:  # noqa: ARG002
            pass

    _install(monkeypatch, TeamFake)
    cfg = RunConfig(model="fake/model", api_key="dummy")
    cto_session.run_long_session(book.project_id, config=cfg, max_iterations=40)

    data = book.load()
    assert data["status"] == "done", f"did not finish: {data['status']}"
    # Criteria were derived from the brief (none were supplied).
    assert len(data["acceptance_criteria"]) == 2
    assert all(p == "synthesized" for p in data["criteria_provenance"].values())
    assert book.all_criteria_satisfied()
    assert data["completeness_clean"] is True
    # The full cooperation chain was traversed, not short-circuited.
    assert seen["analyst"] and seen["architect"] and seen["kickoff"] and seen["qa"]

    _activity.reset_cache_for_tests()
