# omoikane-cli

A standalone CLI/TUI that runs an **autonomous agent team**. It breaks a project
brief into tasks, runs specialist agents to do the work, and drives the project
toward acceptance criteria you supply or that it derives from the brief. Built on
the [hermes-agent](https://github.com/NousResearch/hermes-agent) SDK.

## Highlights

- **One-command install.** A self-contained binary with the hermes-agent SDK
  bundled in, so there is no Python to set up.
- **Self-updating.** Run `omoikane self-update`, or take the quiet "new version
  available" prompt.
- **Deterministic orchestration.** A background daemon drives the work task by
  task, so even small models produce real, tested code. A supervisor watches the
  daemon and respawns it on stalls or crashes.
- **Operator surface.** Inspect runs, inject messages, and approve gated actions
  from the CLI or a live TUI.
- **Self-contained state.** Everything lives under `~/.omoikane/`.

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
