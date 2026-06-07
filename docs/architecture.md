# Architecture

## Components

- **CTO orchestrator (daemon).** A long-lived agent that reads the project
  *book*, decides the next task (routing tasks first), and delegates to specialist
  agents. It runs as a detached Unix daemon (double-fork, no re-exec).
- **Team orchestrator (state machine).** One iteration per tick: bootstrap tasks,
  pick the next open task, record the delegation, and return the goal/context the
  CTO should hand to the SDK's `delegate_task`. The plugin owns state; the LLM
  owns agency.
- **Supervisor.** A scheduled health check (launchd / systemd / cron) that
  classifies each project (healthy / stalled / crashed / …) and respawns the
  daemon, with a circuit breaker to stop respawn loops.
- **Operator surface.** CLI commands and a Textual TUI read the book and append to
  the project inbox; gated actions wait for approval.
- **Persistence.** A per-project `book.json` plus `activity.jsonl`, indexed in a
  SQLite cross-project index.

## hermes-agent integration

omoikane registers its own *book tools* (project_start, book_delegate,
book_record_result, …) against the hermes-agent SDK's tool registry, then
constructs an `AIAgent` with the `omoikane` toolset enabled. The SDK is bundled
into the binary, so no separate install is needed.

## Frozen-binary layout

The release artifact is a PyInstaller **onedir** bundle (executable +
`_internal/`), not a single file. This is required because the orchestrator
daemon double-forks and lazily imports the SDK *after* the launching process
exits — a onefile bundle would have already deleted its temporary extraction
directory, crashing the detached daemon. The supervisor also invokes the binary
every few minutes, which a onefile bundle would re-extract each time.

Installs and updates keep `~/.omoikane/bin/omoikane` as a symlink to the active
`versions/<version>/omoikane/omoikane`. `self-update` downloads a new version,
verifies its checksum, extracts it alongside the current one, and atomically
flips the symlink — the running process is never modified mid-run.
