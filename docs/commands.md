# Commands

Run `omoikane <command> --help` for full per-command flags. Global flags:

- `--version` — print the version and exit.
- `-v` / `-vv` — increase log verbosity (INFO / DEBUG).

## Project lifecycle

| Command | Purpose |
|---|---|
| `start -b <brief> [-c <criteria>]` | Create a project and (optionally) run the CTO. `-c` is optional; without it the analyst derives the criteria from the brief. `--review-criteria` pauses after derivation so you can inspect them; `--foreground`, `--detach`, `--no-run`. |
| `resume <project-id>` | Continue an existing project's CTO loop from persisted history. |
| `stop <project-id>` | Send SIGTERM to the daemon (`--force` escalates to SIGKILL). |
| `open <project-id>` | Attach the live TUI (`--start-if-stopped`). |
| `delete-project <project-id>` | Permanently remove a project (dir + index rows). Refuses while a daemon is live; `-f`/`--force` skips the prompt **and** stops a running daemon (SIGTERM) first. Irreversible. |

## Inspection

| Command | Purpose |
|---|---|
| `list` | Enumerate projects from the index. `--status <s>`, `--json`. |
| `status <project-id>` | Print the project book + phase summary. `--json`. |

## Operator inbox & approvals

| Command | Purpose |
|---|---|
| `inject <project-id> <text>` | Append a message to the project inbox. `--target` to route (e.g. a role or `task:<id>`). |
| `approvals list\|approve\|deny` | Review and resolve gated actions. |

## Background supervisor

| Command | Purpose |
|---|---|
| `supervisor install\|uninstall` | Install/remove the scheduled health check (launchd on macOS, systemd/cron on Linux). |
| `supervisor tick` | Run one supervision pass (what the scheduler invokes). |
| `supervisor status` | Show supervisor state. |

## Maintenance

| Command | Purpose |
|---|---|
| `init-project -b <brief> [-c <criteria>]` | Create a project book without running the CTO (CI helper). `-c` optional; omit it to have the analyst derive the criteria. |
| `migrate-from-hermes` | Migrate legacy `~/.hermes/omoikane/*` data into `~/.omoikane/`. |
| `self-update` | Upgrade the standalone binary. `--check`, `--force`. |

## Slash syntax (TUI input & `inject`)

The TUI input bar and `inject --target` share a parser:

- `/cto <text>` → route to the CTO
- `/<role> <text>` → route to a specialist role
- `/task:<id> <text>` → route to a specific task
- `/approve <id>`, `/deny <id>` → resolve an approval
- bare text → defaults to the CTO
