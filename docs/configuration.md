# Configuration

## Environment variables

| Variable | Purpose |
|---|---|
| `OMOIKANE_API_KEY` | LLM API key. Falls back to `OPENROUTER_API_KEY`, then `ANTHROPIC_API_KEY`. |
| `OMOIKANE_MODEL` | Model id (built-in default `openrouter/owl-alpha`). |
| `OMOIKANE_PROVIDER` | Provider (built-in default `openrouter`). |
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

Global settings live in `~/.omoikane/config.toml`; `omoikane onboard` writes it
for you. Only these sections are read:

```toml
[auth]
api_key = "env:OPENROUTER_API_KEY"   # a literal key, or "env:VAR" to read $VAR

[model]
id       = "openrouter/owl-alpha"
provider = "openrouter"

[transport]
backends = ["stdout"]                 # add "telegram" / "slack" to enable them

[transport.telegram]
bot_token = "env:TELEGRAM_BOT_TOKEN"
chat_id   = "-100123456789"

[transport.slack]
webhook_url = "env:SLACK_WEBHOOK_URL"

[supervisor]
schedule = "*/5 * * * *"              # cron entry written by `supervisor install`
```

Values resolve CLI flag > environment variable > `config.toml` > built-in default.
A missing file or missing section is fine; defaults apply. Supervisor stall and
respawn thresholds are fixed in code, so `schedule` is the only `[supervisor]` key
read from config.
