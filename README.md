# Omoikane

Standalone CLI/TUI orchestrator for autonomous agent teams, built on the [hermes-agent](https://hermes-agent.nousresearch.com) Python SDK.

You hand Omoikane a project brief and acceptance criteria. A long-lived CTO agent decomposes the work, delegates specialists via `delegate_task`, validates each result, and loops until every criterion is satisfied. Every decision, delegation, tool call, and result is appended to a per-project Activity Book on disk.

## Status

**Pre-alpha.** Phase 1 (core extraction) underway. See `docs/phase0-spike-report.md` for SDK feasibility analysis.

## Install (development)

```bash
git clone https://github.com/davidkulh/omoikane.git
cd omoikane
python3.11 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest tests/ -v
```

## Architecture

- **Mode A — long-lived CTO**: one `AIAgent` per project with `delegation` toolset. CTO calls `delegate_task` to spawn specialists. All agents share `omoikane` toolset (book_* tools).
- **Operator inject**: TUI/CLI calls `agent.steer(text)` directly; sub-iteration latency. Detached mode: `inbox.jsonl` + watchfiles.
- **IPC**: file-based — `activity.jsonl` (tail), `inbox.jsonl` (operator writes), `orchestrator.pid` (daemon lock).
- **Supervisor**: launchd / systemd timer / cron fallback. No per-project crons.

See `.claude/plans/` for the full design plan.

## Acknowledgement

Derived from the [Hermes plugin "omoikane"](https://github.com/NousResearch/hermes-agent) by David Kulhanek (2026).
