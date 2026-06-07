# Omoikane

Standalone CLI/TUI orchestrator for autonomous agent teams, built on the
[hermes-agent](https://hermes-agent.nousresearch.com) Python SDK.

You hand Omoikane a project brief and acceptance criteria. A long-lived CTO
agent decomposes the work, delegates specialists via `delegate_task`, validates
each result, and loops until every criterion is satisfied. Every decision,
delegation, tool call, and result is appended to a per-project Activity Book
on disk, and an operator-attached TUI streams the work as it happens — with a
slash-prefixed input bar that injects new context into the running CTO without
killing the loop.

## Status

**Beta.** The full stack lands in this tree: core Book, tools layer,
runtime, daemon + supervisor, TUI, approvals, transports, and on-disk
migration. A web dashboard was scoped but deliberately dropped — the
textual TUI covers the operator UX.

## Install

### Binary (recommended)

No Python required — a self-contained binary with the hermes-agent SDK bundled.
The installer places everything under `~/.omoikane/` and points
`~/.omoikane/bin/omoikane` at the current version:

```sh
curl -fsSL https://d2a8k3u.github.io/omoikane-cli/install.sh | sh
```

Prebuilt for **macOS (Apple Silicon, arm64)** and **Linux (x86_64)**. Add
`~/.omoikane/bin` to your `PATH` (the installer prints the exact line), then:

```sh
omoikane --version
omoikane self-update      # upgrade in place; re-running install.sh also upgrades
```

Full guide (PATH setup, macOS Gatekeeper, update opt-out) is in the
[documentation](https://d2a8k3u.github.io/omoikane-cli/install/).

### From source (development)

```bash
git clone https://github.com/d2a8k3u/omoikane-cli.git
cd omoikane-cli
python3.11 -m venv .venv
.venv/bin/pip install -e ".[runtime,tui,transport,dev]"
.venv/bin/pytest tests/ -v
```

The distribution is named `omoikane-cli`; the import package and the
installed command both stay `omoikane`. A source install is managed by pip —
`omoikane self-update` defers to `pip install -U` there.

The extras are intentionally narrow so a core-only contributor (someone who
just wants to hack on the Book layer) does not need to bring the SDK,
textual, or httpx into their environment:

| Extra        | When you need it                              |
|--------------|------------------------------------------------|
| `runtime`    | Running the CTO (`start`, `resume`, `supervisor tick`) |
| `tui`        | `omoikane open` (textual + watchfiles + rich) |
| `transport`  | Telegram / Slack push (httpx)                 |
| `dev`        | pytest, pytest-cov                            |

## Quick start

```bash
export OPENROUTER_API_KEY="sk-or-..."

# Bootstrap + run the CTO attached to this terminal.
echo "Build a CLI greeter in Python" > /tmp/brief.md
cat > /tmp/criteria.txt <<EOF
Prints "Hello, world!"
Has a --name flag overriding the greeting
EOF
omoikane start --brief /tmp/brief.md --criteria /tmp/criteria.txt --foreground

# Or run it detached and watch it in the TUI:
omoikane start --brief /tmp/brief.md --criteria /tmp/criteria.txt --detach
omoikane open <project_id>

# Inject context into the running CTO without leaving the TUI:
> use uuid v7 instead of v4
> /backend-engineer add a benchmark
> /approve a-7
```

## Subcommand surface

```
omoikane start             create + run a project (--foreground / --detach / --no-run)
omoikane resume <pid>      continue a project's CTO loop with its persisted history
omoikane open <pid>        attach the textual TUI (--start-if-stopped for daemon)
omoikane stop <pid>        send SIGTERM to the daemon (--force escalates to SIGKILL)
omoikane delete-project <pid>   permanently remove a project, dir + index (--force stops a live daemon + skips the prompt)

omoikane supervisor install     write launchd / systemd timer / cron entry
omoikane supervisor tick        run the no-LLM watchdog pass (used by the scheduler)
omoikane supervisor status      report the active backend + installation status
omoikane supervisor uninstall   remove the recurring entry

omoikane approvals list [pid]            enumerate pending approvals
omoikane approvals approve <pid> <aid>   resolve with optional --note
omoikane approvals deny    <pid> <aid>   resolve with optional --note

omoikane status <pid>            print the Book summary
omoikane list                    list every project from the SQLite index
omoikane inject <pid> 'msg'      append to inbox.jsonl (--target ROLE)

omoikane init-project            create a Book without running the CTO (CI helper)
omoikane migrate-from-hermes     copy ~/.hermes/omoikane/* → ~/.omoikane/*
```

## File layout

```
~/.omoikane/
├── config.toml                # [runtime] [orchestrator] [supervisor] [transport]
├── index.db                   # SQLite project index
├── logs/                      # supervisor logs
└── projects/<project_id>/
    ├── book.json              # source of truth
    ├── activity.jsonl         # SDK callbacks + orchestrator events (TUI tail)
    ├── inbox.jsonl            # operator → CTO messages
    ├── inbox.jsonl.consumed   # dedup sidecar
    ├── delegation.json        # delegation graph
    ├── cto_history.json       # CTO conversation history (cross-restart)
    ├── orchestrator.pid       # daemon lockfile (fcntl.flock)
    ├── orchestrator.log       # daemon stdout/stderr
    ├── reflections/
    └── artifacts/
```

## Architecture

- **Mode A — long-lived CTO.** One `AIAgent` per project gets the union of
  every specialist toolset (`file`, `web`, `browser`, `terminal`,
  `delegation`, `omoikane`). The CTO calls `delegate_task` to spawn child
  agents; the SDK intersects the child's requested toolsets with the
  parent's, so child specialists inherit the toolsets they need without
  losing them. `code_execution` is blocked for children by the
  SDK — specialists use `terminal` for shell-driven code instead.
- **Operator inject.** TUI and CLI feed inbox.jsonl; the orchestrator drains
  it before every CTO iteration and via `step_callback` between iterations,
  then calls `agent.steer(text)` so the model sees the inject on its next
  API call (sub-iteration latency).
- **Single supervisor tick.** A no-LLM classifier iterates every project in
  the SQLite index, asks `watchdog.classify` what state it's in (using
  `os.kill(pid, 0)` as the liveness probe), and respawns the daemon on
  STALLED/CRASHED — no per-project crons, no Hermes gateway HTTP.
- **Approvals are self-gated.** The SDK has no pre-tool-execution hook, so
  every role with `terminal` or `code_execution` gets a prompt addendum
  demanding `book_request_approval` before any dangerous command. This is a
  **trust-based** mechanism, not a sandbox; operators must treat the CTO
  delegation graph as a privileged surface.

## Configuration

`~/.omoikane/config.toml`:

```toml
[runtime]
model       = "anthropic/claude-sonnet-4.6"
api_key     = "env:ANTHROPIC_API_KEY"
base_url    = ""
max_iterations_per_chunk = 12

[orchestrator]
mode               = "long_session"
inbox_poll_seconds = 2

[supervisor]
schedule                = "*/5 * * * *"
stall_minutes           = 10
healthy_minutes         = 3
circuit_breaker_minutes = 60

[role_toolsets]
"agent-backend-engineer" = ["file", "terminal", "code_execution", "omoikane"]

[transport]
backends = ["stdout", "telegram"]

[transport.telegram]
bot_token = "env:TELEGRAM_BOT_TOKEN"
chat_id   = "-100123456789"

[transport.slack]
webhook_url = "env:SLACK_WEBHOOK_URL"
```

## Tests

```bash
.venv/bin/python -m pytest tests/ -v   # 280+ passing
```

The suite covers every layer: Book persistence + lock semantics, the
hermes-agent SDK plumbing (registry round-trip + a tiny live OpenRouter
smoke), runtime callbacks under a FakeAIAgent, supervisor classification
with a local pid probe, install renderers for every backend, transport
fakes, migration sanitisation, and a textual `Pilot` smoke for the TUI.

## Acknowledgement

Derived from the Hermes plugin "omoikane" by David Kulhanek (2026), with
heavy debts to the orchestration-protocol SKILL.md briefs developed
alongside that plugin.
