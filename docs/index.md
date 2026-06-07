# omoikane-cli

A standalone CLI/TUI that runs an **autonomous agent team** — it decomposes a
project brief, runs specialist agents to do the work, and drives it toward your
acceptance criteria. Built on the
[hermes-agent](https://github.com/NousResearch/hermes-agent) SDK.

## Highlights

- **One-command install**, no Python required — a self-contained binary with the
  hermes-agent SDK baked in.
- **Self-updating** — `omoikane self-update`, plus a quiet "new version available"
  nag.
- **Deterministic orchestration** — a background daemon drives the work task by
  task, so even small models produce real, tested code; a supervisor watches it
  and respawns on stalls/crashes.
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
omoikane start ──▶ orchestration daemon ──▶ runs ──▶ specialist agents
                      ▲                                    │
        supervisor ───┘ (health, respawn)                  ▼
                                              your acceptance criteria
```

Read more in [Architecture](architecture.md).
