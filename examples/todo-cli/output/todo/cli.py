"""CLI entry point — argument parsing, command dispatch, and error handling."""

import argparse
import json
import sys
from pathlib import Path

from todo.task_service import TaskService, TaskNotFoundError
from todo.storage import JsonStorage

DEFAULT_DATA_PATH = Path.home() / ".todo" / "tasks.json"

EXIT_SUCCESS = 0
EXIT_NOT_FOUND = 1
EXIT_IO_ERROR = 2
EXIT_USAGE = 3


def _build_parser() -> argparse.ArgumentParser:
    """Create the top-level argument parser with subcommands."""
    parser = argparse.ArgumentParser(
        prog="todo",
        description="A simple command-line task manager.",
    )
    parser.add_argument(
        "--file",
        type=Path,
        default=DEFAULT_DATA_PATH,
        help=f"Path to the JSON data file (default: {DEFAULT_DATA_PATH})",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # add
    add_parser = subparsers.add_parser("add", help="Add a new task")
    add_parser.add_argument("text", help="Task description text")

    # list
    subparsers.add_parser("list", help="List all tasks")

    # done
    done_parser = subparsers.add_parser("done", help="Mark a task as done")
    done_parser.add_argument("id", type=int, help="Task ID to mark as done")

    # delete
    del_parser = subparsers.add_parser("delete", help="Delete a task")
    del_parser.add_argument("id", type=int, help="Task ID to delete")

    # clear
    subparsers.add_parser("clear", help="Remove all completed (done) tasks")

    return parser


def _format_task_line(task) -> str:
    """Return a single formatted list line, e.g. '[x] 1. Buy milk'."""
    checkbox = "[x]" if task.status == "done" else "[ ]"
    return f"{checkbox} {task.id}. {task.text}"


def _handle_add(service: TaskService, args: argparse.Namespace) -> None:
    task = service.add_task(args.text)
    print(f"Added task #{task.id}: {task.text}")


def _handle_list(service: TaskService, args: argparse.Namespace) -> None:
    tasks = service.list_tasks()
    if not tasks:
        print("No tasks yet. Use 'todo add \"<text>\"' to create one.")
        return
    for task in tasks:
        print(_format_task_line(task))


def _handle_done(service: TaskService, args: argparse.Namespace) -> None:
    task = service.done_task(args.id)
    print(f"Marked task #{task.id} as done: {task.text}")


def _handle_delete(service: TaskService, args: argparse.Namespace) -> None:
    service.delete_task(args.id)
    print(f"Deleted task #{args.id}")


def _handle_clear(service: TaskService, args: argparse.Namespace) -> None:
    removed = service.clear_done()
    if removed == 0:
        print("No done tasks to clear.")
    elif removed == 1:
        print("Cleared 1 done task.")
    else:
        print(f"Cleared {removed} done tasks.")


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(EXIT_SUCCESS)

    storage = JsonStorage(args.file)
    service = TaskService(storage)

    try:
        if args.command == "add":
            _handle_add(service, args)
        elif args.command == "list":
            _handle_list(service, args)
        elif args.command == "done":
            _handle_done(service, args)
        elif args.command == "delete":
            _handle_delete(service, args)
        elif args.command == "clear":
            _handle_clear(service, args)
        else:
            parser.print_help()
            sys.exit(EXIT_USAGE)
    except TaskNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)
    except (OSError, IOError) as e:
        print(f"File error: {e}", file=sys.stderr)
        sys.exit(EXIT_IO_ERROR)
    except json.JSONDecodeError as e:
        print(f"Data error: the task file contains invalid JSON ({e})", file=sys.stderr)
        sys.exit(EXIT_IO_ERROR)


if __name__ == "__main__":
    main()
