# Architecture

## Components

- **Orchestration driver (daemon).** A deterministic loop that drives the
  project to completion. It runs as a detached Unix daemon (double-fork, no
  re-exec) and, each round, asks the state machine for the next task, runs one
  focused agent to do it, and records the outcome.
- **Team state machine.** Decides — deterministically — what happens next:
  bootstrap the planning round, pick the next open task (routing tasks first),
  and produce a self-contained delegation plan (role, goal, context, toolsets)
  for that task.
- **Focused agents.** Each task is executed by a single-purpose `AIAgent`: a
  specialist (implementer, backend, QA, tech-writer, …) for executor tasks, or
  the CTO for routing/kickoff tasks. The agent is briefed with exactly that one
  task and writes real files in the project workspace.
- **Supervisor.** A scheduled health check (launchd / systemd / cron) that
  classifies each project (healthy / stalled / crashed / …) and respawns the
  daemon, with a circuit breaker to stop respawn loops.
- **Operator surface.** CLI commands and a Textual TUI read the book and append to
  the project inbox; gated actions wait for approval.
- **Persistence.** A per-project `book.json` plus `activity.jsonl`, indexed in a
  SQLite cross-project index. The book is the shared memory across agents.

## Orchestration loop

Each round of the driver:

1. **Plan** — the state machine selects the next task and builds its delegation
   plan. A fresh project first bootstraps an analyst + architect + kickoff round.
   When the operator supplied no acceptance criteria, the analyst derives them
   from the brief and tags each with its provenance (operator-given, extracted,
   synthesized, or escalated). With `--review-criteria` the driver pauses here
   once, before committing the roadmap, so the operator can inspect them.
2. **Execute** — the driver runs one focused agent for the plan's role with a
   single-task directive. Dispatch is the driver's job, not the model's, so
   progress does not hinge on the model choosing to delegate.
3. **Close** — the driver records the result and completes the task (if the agent
   did not already), so the state machine advances on the next round.
4. **Verify** — when everything is built but acceptance criteria are still
   unverified, a focused QA pass checks each criterion against the produced files,
   marks the ones that pass as satisfied, and files fix tasks for the rest.
5. **Complete** — once every criterion is satisfied and no tasks remain open, a
   bounded completeness pass asks whether the brief implied anything the criteria
   missed: edge cases, error paths, consequences. A clean pass finishes the
   project; a pass that surfaces new work appends criteria or tasks and loops,
   up to three passes. If analysis ever drains with zero criteria, the driver
   re-derives once and then blocks rather than finishing empty. A no-progress
   breaker ends a project that stalls.

Stop is cooperative: a SIGTERM sets a stop flag that a watcher thread maps onto
the in-flight agent's `interrupt()`, so the daemon shuts down within a step.

## hermes-agent integration

omoikane registers its own *book tools* (project_start, book_record_result,
book_open_task, book_satisfy_criterion, book_set_criteria, …) against the
hermes-agent SDK's tool
registry, then constructs each `AIAgent` with the toolsets that role needs (the
`omoikane` toolset plus file/terminal/etc). The SDK is bundled into the binary,
so no separate install is needed.

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
