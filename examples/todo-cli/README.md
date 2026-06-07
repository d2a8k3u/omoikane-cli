# Example: To-Do CLI

A complete, working project produced **autonomously by omoikane**. The agent team read the brief, decomposed it, implemented the modules, wrote tests, and verified every acceptance criterion.

It was generated with `openrouter/owl-alpha`, which is the point: the orchestration drives the work task by task, so even a modest model produces a real, tested, layered project.

## Contents

```
examples/todo-cli/
├── brief.md         # the input: project description + functional requirements
├── criteria.json    # the input: 10 acceptance criteria
└── output/          # the generated project (todo/ package, tests/, README, pyproject)
```

## Reproduce it

```sh
mkdir my-todo && cd my-todo
cp /path/to/examples/todo-cli/brief.md .
cp /path/to/examples/todo-cli/criteria.json .

omoikane start -b brief.md -c criteria.json --detach --max-iterations 40
omoikane status <project-id>         # watch progress
```

The agents write the project into the working directory. Output will vary run to run; `output/` is a snapshot of one such run.

## What this run produced

- **10 / 10 acceptance criteria** satisfied.
- A layered package — `models.py` (data), `storage.py` (JSON persistence), `task_service.py` (logic), `cli.py` (argparse interface).
- A **134-test** suite covering models, storage, service, and CLI.
- A generated `README.md` with install + usage.

## Run the generated project

```sh
cd output
python3 -m todo add "buy milk"
python3 -m todo list
python3 -m todo done 1
python3 -m pytest        # 134 passed
```

> Snapshot of a single machine-generated run. Run its tests from inside
> `output/` (it is a standalone project with its own `pyproject.toml`).
