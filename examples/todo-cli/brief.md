# To-Do CLI — task manager

## Project description

A command-line application that lets a user manage a list of tasks. Tasks are stored in a local JSON file so they
persist between runs. The goal is a simple but fully working tool with a clean separation between the data layer,
application logic, and the user interface (CLI).

## Functional requirements

The application must support these commands:

- `add "<task text>"` — add a new task
- `list` — list all tasks with their ID, status, and text
- `done <id>` — mark a task as done
- `delete <id>` — delete a task
- (optional) `clear` — remove all completed tasks

Each task has: a unique ID, text, status (done / not done), and a creation date.

## Acceptance criteria

- [ ] The `add` command creates a new task with a unique ID and saves it to the file.
- [ ] The `list` command shows all tasks clearly; completed ones are visually distinct.
- [ ] The `done <id>` command changes an existing task's status to "done".
- [ ] The `delete <id>` command removes a task from the list.
- [ ] Data persists between runs (stored in a JSON file).
- [ ] Given a non-existent ID, the program prints a clear error and does not crash.
- [ ] With no arguments or an unknown command, help is shown.
- [ ] If the data file does not exist, the app creates it automatically on first run.
- [ ] The code is split into logical parts (file handling / logic / CLI interface).
- [ ] The project includes a README describing installation and usage.

## Optional extensions

- Task priorities (low / medium / high)
- Due dates and filtering by date
- Colored terminal output
- An automated test suite
