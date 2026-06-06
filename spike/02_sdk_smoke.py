"""Phase 2 SDK live smoke — prove an AIAgent can call our book tools.

Run with the project venv active and ``OPENROUTER_API_KEY`` set:

    .venv/bin/python spike/02_sdk_smoke.py

Cost: a single ``owl-alpha`` short turn. The agent is asked to call
``book_log`` for an existing project; we assert the activity file grew
afterwards.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


def main() -> int:
    if not os.environ.get("OPENROUTER_API_KEY"):
        print("OPENROUTER_API_KEY not set — skipping live SDK smoke.", file=sys.stderr)
        return 0

    tmp = Path(tempfile.mkdtemp(prefix="omoikane-sdk-smoke-"))
    os.environ["OMOIKANE_HOME"] = str(tmp)

    from omoikane.core import store
    store._DB_READY = False
    store.init_index_db()

    from omoikane.core.book import ProjectBook
    from omoikane.tools import register_book_tools, reset_registration_for_tests

    reset_registration_for_tests()
    register_book_tools(override=True)

    book = ProjectBook.create("SDK smoke project", ["AC1"])
    pid = book.project_id
    print(f"Created project {pid} under {tmp}")

    from run_agent import AIAgent  # type: ignore

    agent = AIAgent(
        model="openrouter/owl-alpha",
        api_key=os.environ["OPENROUTER_API_KEY"],
        provider="openrouter",
        enabled_toolsets=["omoikane"],
        quiet_mode=True,
        skip_context_files=True,
        skip_memory=True,
        max_iterations=4,
    )

    prompt = (
        f"You manage the Omoikane Project Book for project_id={pid!r}. "
        "Call book_log exactly once with kind='decision' and "
        "summary='SDK smoke OK', then stop. Do not call any other tool."
    )
    print("Running AIAgent...")
    result = agent.run_conversation(prompt, task_id="sdk-smoke")
    print("Final response:", result.get("final_response", "")[:200])

    activity_lines = (book.store.activity_path).read_text(encoding="utf-8").splitlines()
    saw_smoke = any("SDK smoke OK" in line for line in activity_lines)
    print(f"book_log persisted: {saw_smoke}")
    if not saw_smoke:
        print("FAIL — model did not call book_log with expected summary.", file=sys.stderr)
        for line in activity_lines:
            print("  -", line)
        return 2
    print("--- SDK SMOKE OK ---")
    return 0


if __name__ == "__main__":
    sys.exit(main())
