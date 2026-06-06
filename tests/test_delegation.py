import json

from omoikane.core.book import ProjectBook
from omoikane.tools import book_delegate, book_record_result


def test_book_delegate_records_node_and_edge(temp_hermes_home):
    book = ProjectBook.create("brief", ["AC"])
    pid = book.project_id

    res = json.loads(book_delegate({
        "project_id": pid,
        "task": "task-0001",
        "to_role": "agent-implementer",
        "expected": "working code",
    }))
    assert res["success"] is True
    assert res["node"] == "n-task-0001"

    tree = json.loads(book.store.delegation_path.read_text())
    assert any(n["id"] == "n-root" for n in tree["nodes"])
    assert any(n["id"] == "n-task-0001" for n in tree["nodes"])
    assert any(e["to"] == "n-task-0001" and e["returned"] == "pending" for e in tree["edges"])


def test_book_record_result_closes_edge(temp_hermes_home):
    book = ProjectBook.create("brief", ["AC"])
    pid = book.project_id

    book_delegate({
        "project_id": pid,
        "task": "task-9001",
        "to_role": "agent-qa-reviewer",
        "expected": "verdict",
    })

    res = json.loads(book_record_result({
        "project_id": pid,
        "task": "task-9001",
        "status": "done",
        "reflection": "Reviewed and approved",
    }))
    assert res["success"] is True
    assert res["reflection_ref"] is not None

    tree = json.loads(book.store.delegation_path.read_text())
    edge = next(e for e in tree["edges"] if e["to"] == "n-task-9001")
    assert edge["returned"] == "done"
    assert edge["reflection_ref"] == res["reflection_ref"]


def test_book_delegate_auto_picks_isolation_mode(temp_hermes_home):
    book = ProjectBook.create("brief", ["AC"])
    res = json.loads(book_delegate({
        "project_id": book.project_id,
        "task": "task-big",
        "to_role": "agent-implementer",
        "expected": "full build",
        # mode omitted → execution.choose_execution_mode runs
    }))
    # "build" keyword triggers isolated mode
    assert res["mode"] == "isolated"
