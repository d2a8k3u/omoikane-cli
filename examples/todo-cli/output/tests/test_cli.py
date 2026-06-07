"""Tests for CLI entry point in cli.py."""

import argparse
import json
import sys
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from todo.cli import (
    _build_parser,
    _format_task_line,
    _handle_add,
    _handle_clear,
    _handle_delete,
    _handle_done,
    _handle_list,
    main,
)
from todo.task_service import TaskService, TaskNotFoundError
from todo.storage import JsonStorage


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def service(tmp_dir):
    storage = JsonStorage(tmp_dir / "tasks.json")
    return TaskService(storage)


# ---------------------------------------------------------------------------
# Parser tests
# ---------------------------------------------------------------------------


class TestBuildParser:
    def test_returns_argparse_parser(self):
        parser = _build_parser()
        assert isinstance(parser, argparse.ArgumentParser)

    def test_no_args_leaves_command_none(self):
        parser = _build_parser()
        args = parser.parse_args([])
        assert args.command is None

    def test_add_subcommand_parses_text(self):
        args = _build_parser().parse_args(["add", "Buy milk"])
        assert args.command == "add"
        assert args.text == "Buy milk"

    def test_list_subcommand(self):
        args = _build_parser().parse_args(["list"])
        assert args.command == "list"

    def test_done_parses_id_as_int(self):
        args = _build_parser().parse_args(["done", "3"])
        assert args.command == "done"
        assert args.id == 3

    def test_delete_parses_id_as_int(self):
        args = _build_parser().parse_args(["delete", "1"])
        assert args.command == "delete"
        assert args.id == 1

    def test_clear_subcommand(self):
        args = _build_parser().parse_args(["clear"])
        assert args.command == "clear"

    def test_custom_file_path(self, tmp_dir):
        custom = tmp_dir / "custom.json"
        args = _build_parser().parse_args(["--file", str(custom), "list"])
        assert args.file == custom

    def test_add_with_spaces_in_text(self):
        args = _build_parser().parse_args(["add", "Buy milk and eggs"])
        assert args.text == "Buy milk and eggs"

    def test_done_rejects_non_int_id(self):
        parser = _build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["done", "abc"])

    def test_delete_rejects_non_int_id(self):
        parser = _build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["delete", "abc"])


# ---------------------------------------------------------------------------
# format_task_line tests
# ---------------------------------------------------------------------------


class TestFormatTaskLine:
    def test_pending_shown_with_empty_box(self):
        from todo.models import Task

        task = Task(id=1, text="Test", status="pending", created_at="2024-01-01T00:00:00")
        line = _format_task_line(task)
        assert line == "[ ] 1. Test"

    def test_done_shown_with_checked_box(self):
        from todo.models import Task

        task = Task(id=2, text="Done", status="done", created_at="2024-01-01T00:00:00")
        line = _format_task_line(task)
        assert line == "[x] 2. Done"


# ---------------------------------------------------------------------------
# Handler tests
# ---------------------------------------------------------------------------


class TestHandleAdd:
    def test_prints_added_message(self, service, capsys):
        args = argparse.Namespace(text="Buy milk")
        _handle_add(service, args)
        out = capsys.readouterr().out
        assert "Added task #1" in out
        assert "Buy milk" in out

    def test_creates_task_in_storage(self, service):
        args = argparse.Namespace(text="Test task")
        _handle_add(service, args)
        tasks = service.list_tasks()
        assert len(tasks) == 1
        assert tasks[0].text == "Test task"


class TestHandleList:
    def test_no_tasks_message(self, service, capsys):
        args = argparse.Namespace()
        _handle_list(service, args)
        out = capsys.readouterr().out
        assert "No tasks" in out

    def test_shows_all_tasks(self, service, capsys):
        service.add_task("A")
        service.add_task("B")
        args = argparse.Namespace()
        _handle_list(service, args)
        out = capsys.readouterr().out
        assert "[ ] 1. A" in out
        assert "[ ] 2. B" in out

    def test_done_tasks_marked_with_x(self, service, capsys):
        service.add_task("Done")
        service.done_task(1)
        args = argparse.Namespace()
        _handle_list(service, args)
        out = capsys.readouterr().out
        assert "[x] 1. Done" in out


class TestHandleDone:
    def test_marks_task_done(self, service, capsys):
        service.add_task("Finish me")
        args = argparse.Namespace(id=1)
        _handle_done(service, args)
        out = capsys.readouterr().out
        assert "Marked task #1 as done" in out
        assert service.list_tasks()[0].status == "done"

    def test_nonexistent_id_raises_error(self, service, capsys):
        args = argparse.Namespace(id=999)
        with pytest.raises(TaskNotFoundError):
            _handle_done(service, args)


class TestHandleDelete:
    def test_deletes_task(self, service, capsys):
        service.add_task("Delete me")
        args = argparse.Namespace(id=1)
        _handle_delete(service, args)
        out = capsys.readouterr().out
        assert "Deleted task #1" in out
        assert service.list_tasks() == []

    def test_nonexistent_id_raises_error(self, service, capsys):
        args = argparse.Namespace(id=42)
        with pytest.raises(TaskNotFoundError):
            _handle_delete(service, args)


class TestHandleClear:
    def test_clears_done_tasks(self, service, capsys):
        service.add_task("Keep")
        service.add_task("Done")
        service.done_task(2)
        args = argparse.Namespace()
        _handle_clear(service, args)
        out = capsys.readouterr().out
        assert "Cleared 1 done task" in out
        assert len(service.list_tasks()) == 1

    def test_no_done_tasks(self, service, capsys):
        service.add_task("Pending")
        args = argparse.Namespace()
        _handle_clear(service, args)
        out = capsys.readouterr().out
        assert "No done tasks" in out

    def test_multiple_done_tasks(self, service, capsys):
        service.add_task("A")
        service.add_task("B")
        service.done_task(1)
        service.done_task(2)
        args = argparse.Namespace()
        _handle_clear(service, args)
        out = capsys.readouterr().out
        assert "Cleared 2 done tasks" in out


# ---------------------------------------------------------------------------
# Integration tests — main() end-to-end
# ---------------------------------------------------------------------------


class TestMainEndToEnd:
    @pytest.fixture
    def env(self, tmp_dir, monkeypatch):
        """Patch DEFAULT_DATA_PATH to a temp file and set sys.argv."""
        data_file = tmp_dir / "tasks.json"
        monkeypatch.setattr("todo.cli.DEFAULT_DATA_PATH", data_file)
        return data_file

    def test_add_command(self, env, capsys):
        with mock.patch.object(sys, "argv", ["todo", "add", "Buy milk"]):
            main()
        out = capsys.readouterr().out
        assert "Added task #1: Buy milk" in out

    def test_list_after_add(self, env, capsys):
        with mock.patch.object(sys, "argv", ["todo", "add", "Buy milk"]):
            main()
        with mock.patch.object(sys, "argv", ["todo", "list"]):
            main()
        out = capsys.readouterr().out
        assert "[ ] 1. Buy milk" in out

    def test_done_command(self, env, capsys):
        with mock.patch.object(sys, "argv", ["todo", "add", "Task"]):
            main()
        with mock.patch.object(sys, "argv", ["todo", "done", "1"]):
            main()
        out = capsys.readouterr().out
        assert "Marked task #1 as done" in out

    def test_delete_command(self, env, capsys):
        with mock.patch.object(sys, "argv", ["todo", "add", "Task"]):
            main()
        with mock.patch.object(sys, "argv", ["todo", "delete", "1"]):
            main()
        out = capsys.readouterr().out
        assert "Deleted task #1" in out

    def test_clear_command(self, env, capsys):
        with mock.patch.object(sys, "argv", ["todo", "add", "Task"]):
            main()
        with mock.patch.object(sys, "argv", ["todo", "done", "1"]):
            main()
        with mock.patch.object(sys, "argv", ["todo", "clear"]):
            main()
        out = capsys.readouterr().out
        assert "Cleared 1 done task" in out

    def test_no_args_prints_help(self, env, capsys):
        with mock.patch.object(sys, "argv", ["todo"]):
            with pytest.raises(SystemExit) as exc:
                main()
            assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "usage" in out.lower()

    def test_done_nonexistent_exits_1(self, env):
        with mock.patch.object(sys, "argv", ["todo", "done", "999"]):
            with pytest.raises(SystemExit) as exc:
                main()
            assert exc.value.code == 1

    def test_delete_nonexistent_exits_1(self, env):
        with mock.patch.object(sys, "argv", ["todo", "delete", "999"]):
            with pytest.raises(SystemExit) as exc:
                main()
            assert exc.value.code == 1

    def test_data_persists_between_calls(self, env, capsys):
        with mock.patch.object(sys, "argv", ["todo", "add", "Persist me"]):
            main()
        # Second invocation — list should show the task from first call
        with mock.patch.object(sys, "argv", ["todo", "list"]):
            main()
        out = capsys.readouterr().out
        assert "Persist me" in out

    def test_full_lifecycle(self, env, capsys):
        """add → done → list → clear → list"""
        with mock.patch.object(sys, "argv", ["todo", "add", "A"]):
            main()
        with mock.patch.object(sys, "argv", ["todo", "add", "B"]):
            main()
        with mock.patch.object(sys, "argv", ["todo", "done", "1"]):
            main()

        with mock.patch.object(sys, "argv", ["todo", "list"]):
            main()
        out = capsys.readouterr().out
        assert "[x] 1. A" in out
        assert "[ ] 2. B" in out

        with mock.patch.object(sys, "argv", ["todo", "clear"]):
            main()
        out = capsys.readouterr().out
        assert "Cleared 1" in out

        with mock.patch.object(sys, "argv", ["todo", "list"]):
            main()
        out = capsys.readouterr().out
        assert "[ ] 2. B" in out
        assert "A" not in out


# ---------------------------------------------------------------------------
# Exit code constants
# ---------------------------------------------------------------------------


class TestExitCodes:
    EXIT_SUCCESS = 0
    EXIT_NOT_FOUND = 1
    EXIT_IO_ERROR = 2
    EXIT_USAGE = 3

    def test_constants_match_expected(self):
        from todo.cli import EXIT_SUCCESS, EXIT_NOT_FOUND, EXIT_IO_ERROR, EXIT_USAGE
        assert EXIT_SUCCESS == 0
        assert EXIT_NOT_FOUND == 1
        assert EXIT_IO_ERROR == 2
        assert EXIT_USAGE == 3


# ---------------------------------------------------------------------------
# Error handling in main() — IO errors, corrupt data
# ---------------------------------------------------------------------------


class TestMainErrorHandling:
    @pytest.fixture
    def env(self, tmp_dir, monkeypatch):
        data_file = tmp_dir / "tasks.json"
        monkeypatch.setattr("todo.cli.DEFAULT_DATA_PATH", data_file)
        return data_file

    def test_corrupt_json_file_exits_2(self, env):
        """When the task file contains invalid JSON, main exits with code 2."""
        env.write_text("{invalid json [")
        with mock.patch.object(sys, "argv", ["todo", "list"]):
            with pytest.raises(SystemExit) as exc:
                main()
            assert exc.value.code == 2

    def test_corrupt_json_file_prints_error_to_stderr(self, env, capsys):
        """Corrupt data file should print a helpful error message."""
        env.write_text("not valid json")
        with mock.patch.object(sys, "argv", ["todo", "list"]):
            with pytest.raises(SystemExit):
                main()
        err = capsys.readouterr().err
        assert "Data error" in err
        assert "JSON" in err

    def test_done_nonexistent_via_main_exits_1(self, env):
        """main() wraps TaskNotFoundError and exits 1."""
        with mock.patch.object(sys, "argv", ["todo", "done", "999"]):
            with pytest.raises(SystemExit) as exc:
                main()
            assert exc.value.code == 1

    def test_delete_nonexistent_via_main_exits_1(self, env):
        """main() wraps TaskNotFoundError and exits 1."""
        with mock.patch.object(sys, "argv", ["todo", "delete", "999"]):
            with pytest.raises(SystemExit) as exc:
                main()
            assert exc.value.code == 1

    def test_done_nonexistent_prints_error_to_stderr(self, env, capsys):
        """Error message for missing task goes to stderr."""
        with mock.patch.object(sys, "argv", ["todo", "done", "42"]):
            with pytest.raises(SystemExit):
                main()
        err = capsys.readouterr().err
        assert "Error" in err
        assert "42" in err

    def test_delete_nonexistent_prints_error_to_stderr(self, env, capsys):
        """Error message for missing task goes to stderr."""
        with mock.patch.object(sys, "argv", ["todo", "delete", "42"]):
            with pytest.raises(SystemExit):
                main()
        err = capsys.readouterr().err
        assert "Error" in err
        assert "42" in err
