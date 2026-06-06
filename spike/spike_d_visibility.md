# Spike D — child activity callback visibility

## Findings

### Child agent callback isolation
**`tools/delegate_tool.py:1169`**

When `_build_child_agent()` constructs child AIAgent, it passes:
- `tool_progress_callback=child_progress_cb` (wrapper from `_build_child_progress_callback`)
- **NO** `tool_start_callback` or `tool_complete_callback` forwarding
- `quiet_mode=True` (line 1154)

**Child's start/complete callbacks isolated from parent.** Only `tool_progress_callback` relays through custom wrapper.

### Tool dispatch
`agent/tool_executor.py` invokes handlers with:
- `function_args` (schema params)
- `parent_agent` parameter (explicit, for tools like `delegate_task`)

Handler does NOT receive `_agent_self`, `_callbacks`, `_session_id` in kwargs — only via explicit `parent_agent` reference.

### `tool_progress_callback`
**`tool_executor.py:437, 895, 689-693, 1320-1324`**

| Event | Args |
|---|---|
| `tool.started` | `("tool.started", name, preview, args)` |
| `tool.completed` | `("tool.completed", name, None, None, duration=..., is_error=..., result=...)` |

Pair of events — start + complete. Not progress within a tool. Suitable for TUI live tail.

### `status_callback` / `notice_callback` / `notice_clear_callback`
**`run_agent.py:779-813`**

| Callback | Event | Trigger |
|---|---|---|
| `status_callback` | "lifecycle" | `_emit_status()` — state transitions (start, model selection) |
| `status_callback` | "warn" | `_emit_warning()` — non-fatal warnings |
| `notice_callback` | (custom) | `_emit_notice()` — structured notices |
| `notice_clear_callback` | N/A | Paired with notice — dismiss |

All synchronous, per-iteration, try/except guarded.

### `pass_session_id` flag
**`agent/agent_init.py:283`**
```python
agent.pass_session_id = pass_session_id
```
Default `False`. When True, session ID forwarded into tool-handler kwargs. Enables nested delegation tracing.

## Visibility chain

**Parent sees from child:**
- ✅ `tool_progress_callback` events (start/complete) IF wrapper passes them through
- ✅ Final summary string of child as `delegate_task` tool result
- ✅ `delegate_task`'s own start/complete events in parent's `tool_start/complete_callback`
- ❌ Child's `tool_start_callback` events
- ❌ Child's `tool_complete_callback` events
- ❌ Child's `stream_delta_callback` text

## Recommended visibility pattern

**Primary:** custom `omoikane` toolset handlers emit activity directly when invoked.

Since `omoikane` tools run in OUR registered handler code (regardless of whether parent or child calls them), we control the emission point:

```python
def book_log_handler(args, **kwargs):
    project_id = args["project_id"]
    role = kwargs.get("agent_role", "unknown")  # if SDK injects
    emitter = ActivityEmitter(project_id)
    emitter.emit("book_log", {"role": role, **args})
    return tool_result(...)
```

Every `book_*` call lands in activity.jsonl regardless of agent depth. The protocol surface (book_* calls) IS our audit trail.

**Secondary:** parent's `tool_start_callback` captures `delegate_task` call → emits `delegation_spawned` event with role + brief. Parent's `tool_complete_callback` captures `delegate_task` result → emits `delegation_returned` with summary.

**Tertiary:** parent's `tool_progress_callback` may carry child events if wrapper chains it.

## Verdict

- ❌ Child's individual tool calls NOT directly visible in parent's start/complete callbacks
- ✅ Workable visibility via custom-tool handler self-emission + delegation tool aggregation
- ✅ `tool_progress_callback` wrapping may give richer view (verify in practice)

## Implementation implication

- `ActivityEmitter` must be importable and usable from handler context (process-wide singleton or per-project lookup)
- Each `book_*` handler emits its own activity entry
- CTO's parent agent emits `delegation_spawned` / `delegation_returned` via tool_start/complete callbacks
- Stream deltas: only parent CTO's stream visible; child's stream lost (acceptable — child final summary captured)

## Risk note
For roles with `terminal` or `code_execution` (built-in, NOT omoikane), child's individual tool calls NOT visible. Mitigated by:
1. Specialist self-emits status to parent via `book_log` calls (instructed in SKILL.md)
2. Final `delegate_task` result captures all outcomes
3. Daemon process can tail child session_id logs if SDK writes them
