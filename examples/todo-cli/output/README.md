# todo-cli — Command-Line Task Manager

A simple CLI tool for managing a to-do list. Tasks are stored in a JSON file so they persist between runs.

## Installation

From the project directory:

```bash
pip install -e .
```

Or run directly without installing:

```bash
python3 -m todo
```

## Usage

```bash
todo add "<text>"       # Add a new task
todo list               # List all tasks
todo done <id>          # Mark a task as done
todo delete <id>        # Delete a task
todo clear              # Remove all completed tasks
todo --help             # Show help
```

Use a custom data file:

```bash
todo --file /path/to/tasks.json list
```

## Examples

```bash
$ todo add "Buy milk"
Added task #1: Buy milk

$ todo add "Walk the dog"
Added task #2: Walk the dog

$ todo list
[ ] 1. Buy milk
[ ] 2. Walk the dog

$ todo done 1
Marked task #1 as done: Buy milk

$ todo list
[x] 1. Buy milk
[ ] 2. Walk the dog

$ todo clear
Cleared 1 done task.

$ todo list
[ ] 2. Walk the dog

$ todo delete 2
Deleted task #2

$ todo list
No tasks yet. Use 'todo add "<text>"' to create one.
```

## Exit Codes

| Code | Meaning                        |
|------|--------------------------------|
| 0    | Success                        |
| 1    | Task not found (bad ID)        |
| 2    | File / I/O error               |
| 3    | Unknown command / usage error  |

## Data Storage

Tasks are stored as JSON in `~/.todo/tasks.json` by default. The file is created automatically on first use. The directory structure looks like:

```
~/.todo/
└── tasks.json
```

Each task has:
- **id** — unique integer identifier
- **text** — task description
- **status** — `pending` or `done`
- **created_at** — ISO 8601 timestamp

## Project Structure

```
todo-cli/
├── todo/
│   ├── __init__.py        # Package init
│   ├── __main__.py        # Entry point for `python -m todo`
│   ├── cli.py             # CLI: argument parsing, dispatch, error handling
│   ├── models.py          # Task dataclass
│   ├── storage.py         # JSON file persistence
│   └── task_service.py    # Business logic
├── tests/
│   ├── test_cli.py
│   ├── test_models.py
│   ├── test_storage.py
│   └── test_task_service.py
├── pyproject.toml
└── README.md
```

## Running Tests

```bash
python3 -m pytest tests/ -v
```
