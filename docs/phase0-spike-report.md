# Phase 0 — hermes-agent SDK Spike Report

**Date:** 2026-06-07  
**SDK version:** hermes-agent 0.16.0 (pip git+https://github.com/NousResearch/hermes-agent.git)  
**Source root:** `/Users/davidkulhanek/WorkingLibrary/Github/omoikane/.venv/lib/python3.11/site-packages/`

## Verdict

**GO for Mode A (long-lived CTO with `delegate_task`).** All four spike questions resolved positively or with workable mitigation. Plan needs three updates (documented below).

## Spike summary

### Spike A — `tools.registry.register` runtime mutation ✅
- Custom `omoikane` toolset registers via `tools.registry.register(name, toolset, schema, handler, ...)`
- **Snapshot is taken at AIAgent construction** (`agent_init.py:920-924`) — must register BEFORE constructing AIAgent
- Registry is module singleton, all agents share it
- Handler signature: `(args: dict, **kwargs) -> str`. kwargs includes `task_id`, `user_task`
- Use `tool_result(...)` / `tool_error(...)` helpers for return
- Plan implication: `src/omoikane/__init__.py` calls `register_book_tools()` at import time

### Spike B — operator inject via `steer()` ✅
- `AIAgent.steer(text)` is thread-safe, drained pre-API-call (`conversation_loop.py:887`)
- Latency: next iteration after current tool batch (sub-second)
- Appends to LAST tool result content (NOT new user message)
- Multiple calls concatenate
- `interrupt()` exists for harder break (kills running tools too)
- `step_callback` is read-only observer — NOT needed for inject
- Plan implication: drop the chunked-execution + step_callback workaround. Use `agent.steer()` from TUI/daemon thread directly. Inbox.jsonl still needed for detached-mode IPC.

### Spike C — `delegate_task` child toolset propagation ⚠️ CONDITIONAL
- **Default behavior:** child inherits parent's `enabled_toolsets` fully (`tools/delegate_tool.py:960-995`)
- **Explicit `toolsets=[...]`:** intersected with parent — child cannot gain tools parent lacks
- **`omoikane` NOT in `DELEGATE_BLOCKED_TOOLS`** — propagates fine
- **`DELEGATE_BLOCKED_TOOLS` strips:** `delegation` (unless `role=orchestrator`), `clarify`, `memory`, `code_execution`, `send_message`
- **CRITICAL CONSEQUENCE: children CANNOT use `code_execution` (execute_code).** Specialists needing code run must use `terminal` toolset (shell + process), which is NOT blocked.
- Plan implication: role_toolsets map for backend/frontend/implementer/ai-engineer/ml-engineer needs `terminal` instead of (or alongside) `code_execution`. Update `runtime/role_toolsets.py:_BASE`.

### Spike D — child activity visibility ⚠️ INDIRECT
- Parent's `tool_start_callback` / `tool_complete_callback` do NOT fire for child's inner tool calls
- Parent SEES: child final summary, tool trace metadata (name, arg bytes, result bytes, error), token usage
- Parent's `tool_start_callback` DOES fire for the `delegate_task` call itself
- `tool_progress_callback` chain: child's progress events relay to parent via `_build_child_progress_callback`
- **Workaround:** `omoikane` handlers self-emit to `activity.jsonl` from their own handler code. `book_*` calls show up regardless of caller depth. Process-wide singleton `ActivityEmitter` keyed by project_id.
- Plan implication: `ActivityEmitter` must be importable from any handler context. Lookup current project_id via either (a) handler args, (b) `kwargs.get("task_id")` → session map, or (c) module-level "active project" set when daemon starts.

## Architecture updates (vs original plan)

### Update 1 — inject mechanism simplified
**Was:** chunked AIAgent runs with `max_iterations=8`, drain inbox between chunks via step_callback hack.  
**Now:** single `agent.run_conversation` per CTO turn with full `max_iterations` (e.g. 30-90). Inject via `agent.steer(text)` called from:
- TUI thread directly when attached
- Daemon watchfiles handler when detached (watches `inbox.jsonl`, drains, calls `agent.steer()`)

**Impact:** simpler runtime, sub-second latency, fewer moving parts. `runtime/injection.py:InboxDrainer` still needed for detached IPC but its consumer changes.

### Update 2 — role toolsets revised
SDK blocks `code_execution` for delegated children. Replace with `terminal` where needed:

```python
# runtime/role_toolsets.py
_BASE = {
    "agent-product-analyst":     ["file", "web", "omoikane"],
    "agent-architekt":           ["file", "web", "omoikane"],
    "agent-designer":            ["file", "web", "browser", "omoikane"],
    "agent-backend-engineer":    ["file", "terminal", "omoikane"],      # was code_execution
    "agent-frontend-engineer":   ["file", "terminal", "browser", "omoikane"],
    "agent-database-specialist": ["file", "terminal", "omoikane"],
    "agent-implementer":         ["file", "terminal", "omoikane"],      # was code_execution
    "agent-devops":              ["file", "terminal", "omoikane"],
    "agent-security-engineer":   ["file", "terminal", "omoikane"],
    "agent-ai-engineer":         ["file", "terminal", "web", "omoikane"],
    "agent-ml-engineer":         ["file", "terminal", "omoikane"],
    "agent-analytik":            ["file", "terminal", "omoikane"],
    "agent-qa-reviewer":         ["file", "terminal", "omoikane"],
    "agent-tech-writer":         ["file", "web", "omoikane"],
    "agent-cto":                 ["file", "web", "delegation", "omoikane"],
}
```

CTO must call `delegate_task(role="leaf", toolsets=[...])` per specialist. The leaf children inherit only what CTO passes (intersection with CTO's enabled toolsets — so CTO needs everything in its enabled_toolsets that any child might need).

**Revised CTO enabled_toolsets** = union of all roles' toolsets:
```python
CTO_TOOLSETS = ["file", "web", "browser", "terminal", "delegation", "omoikane"]
```

### Update 3 — activity emission inside handlers
Original plan: `AgentRun._on_tool_start` callback writes activity.jsonl. That covers PARENT (CTO) tool calls only.

Revised: every `omoikane` toolset handler emits its own activity entry. Plus `AgentRun._on_tool_start` for parent CTO tool calls (e.g. `delegate_task` itself). Both stream into the same activity.jsonl.

```python
# tools/handlers.py
def book_log_handler(args, **kwargs):
    pid = args["project_id"]
    emitter = ActivityEmitter.for_project(pid)  # process-wide cache
    emitter.emit("book_log", {
        "summary": args.get("summary", ""),
        "kind": args.get("kind", "info"),
        "from_role": kwargs.get("agent_role", "unknown"),  # if SDK injects
    })
    return _call_core_book_log(args, **kwargs)
```

`ActivityEmitter.for_project(pid)` is a process-local cache (orchestrator daemon is single process).

## Open questions (resolved via source)

| Original risk | Resolution |
|---|---|
| `step_callback` interrupt semantics | N/A — `steer()` is the right hook |
| `delegate_task` child sees omoikane | YES if parent enabled_toolsets includes it |
| Child activity in parent callbacks | NO direct, YES indirect via handler self-emission |
| Long CTO token cost | Same as before — auto-summarize at milestone boundaries |
| Approval gating | Specialists self-gate; SDK has no pre-tool hook (confirmed) |

## Remaining risks

1. **`tool_progress_callback` chain richness** — verified in source (it relays), but exact event format unconfirmed. Phase 3 integration test will catch if events are too sparse.
2. **Handler kwargs `agent_role` injection** — SDK may not pass role into handlers. Workaround: parent CTO calls `book_*` with explicit `from_role` arg; specialists call `book_*` from their child agent context with explicit `from_role` in args.
3. **Session ID for activity correlation** — SDK doesn't auto-inject session_id into handler kwargs unless `pass_session_id=True`. We'll need to enable that flag and use it to thread project_id through.

These are integration-test items, not blockers.

## Decision

**Mode A (long-lived CTO) is viable and recommended.** Proceed to Phase 1.

**Mode B (chunked specialists) deferred to fallback role.** If integration testing in Phase 3 reveals operator latency or visibility issues, we can switch.

## Files produced

- `spike/00_inspect_sdk.py` — SDK surface inspector
- `spike/01_inspect_steer.py` — interrupt/steer/clear_interrupt inspection
- `spike/spike_a_registry.md` — registry findings
- `spike/spike_b_steer.md` — steer/interrupt findings
- `spike/spike_c_delegate.md` — delegate_task propagation findings
- `spike/spike_d_visibility.md` — callback visibility findings
- `docs/phase0-spike-report.md` — this report
