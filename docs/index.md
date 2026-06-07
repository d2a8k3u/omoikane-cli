# omoikane-cli

A standalone CLI/TUI that runs an **autonomous agent team** — a long-lived CTO
agent that decomposes a project brief, delegates to specialist agents, and drives
the work toward your acceptance criteria. Built on the
[hermes-agent](https://github.com/NousResearch/hermes-agent) SDK.

## Highlights

- **One-command install**, no Python required — a self-contained binary with the
  hermes-agent SDK baked in.
- **Self-updating** — `omoikane self-update`, plus a quiet "new version available"
  nag.
- **Long-lived orchestrator** — a CTO agent runs as a background daemon; a
  supervisor watches it and respawns on stalls/crashes.
- **Operator surface** — inspect, inject messages, and approve gated actions from
  the CLI or a live TUI.
- **Self-contained state** — everything lives under `~/.omoikane/`.

## Install

```sh
curl -fsSL https://d2a8k3u.github.io/omoikane-cli/install.sh | sh
```

See [Install](install.md) for details, then [Quickstart](quickstart.md).

## How it fits together

```
omoikane start ──▶ CTO daemon ──▶ delegates ──▶ specialist agents
                      ▲                              │
        supervisor ───┘ (health, respawn)            ▼
                                              your acceptance criteria
```

Read more in [Architecture](architecture.md).
