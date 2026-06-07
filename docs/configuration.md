# Configuration

## Environment variables

| Variable | Purpose |
|---|---|
| `OMOIKANE_API_KEY` | LLM API key. Falls back to `OPENROUTER_API_KEY`, then `ANTHROPIC_API_KEY`. |
| `OMOIKANE_MODEL` | Default model id. |
| `OMOIKANE_PROVIDER` | Default provider (e.g. `openrouter`). |
| `OMOIKANE_HOME` | Override the home directory (default `~/.omoikane`). |
| `OMOIKANE_NO_UPDATE_CHECK` | Set to disable the startup "new version" nag. |

!!! note "Binary location vs data home"
    The installer always places the binary under `~/.omoikane/bin`. If you point
    `OMOIKANE_HOME` elsewhere for data, keep the binary install and the data home
    on the same location, or the scheduled supervisor units may not find the
    binary.

## `~/.omoikane/` layout

```
~/.omoikane/
├── bin/omoikane            symlink to the current version's executable
├── versions/<version>/     installed binary payloads (kept for rollback)
├── config.toml             global configuration
├── index.db                SQLite cross-project index
├── logs/                   supervisor & daemon logs
└── projects/<id>/          per-project state
    ├── book.json           project state (status, phase, tasks, criteria)
    ├── activity.jsonl      event log
    └── inbox.jsonl         operator messages
```

## `config.toml`

Global settings live in `~/.omoikane/config.toml`. Sections that are read:

```toml
[runtime]
# model / iteration defaults

[orchestrator]
# CTO loop behaviour

[supervisor]
# health-check thresholds, respawn policy

[role_toolsets]
# per-role toolset overrides, e.g.:
"agent-backend-engineer" = ["file", "terminal", "browser", "omoikane"]

[transport]
# approval notification backends (slack / telegram)

[origin]
# audit origin tagging
```

Missing sections and a missing file are both fine — defaults apply.
