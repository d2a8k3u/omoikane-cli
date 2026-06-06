# Spike B — interrupt/steer/clear_interrupt semantics

## Findings

### State mutation

**`interrupt()` — `run_agent.py:2262-2329`**
- Mutates: `_interrupt_requested` (bool), `_interrupt_message` (str), `_interrupt_thread_signal_pending` (bool)
- Calls `tools.interrupt.set_interrupt(tid)` for tool-level signals
- Fans out to worker thread IDs via `_tool_worker_threads` + `_tool_worker_threads_lock`
- Propagates to child agents
- Lock-protected; safe from concurrent callers

**`steer()` — `run_agent.py:2363-2397`**
- Mutates: `_pending_steer` (str | None)
- Protected by `_pending_steer_lock` (threading.Lock, init `agent_init.py:430`)
- Multiple calls concatenate with newlines
- Thread-safe from TUI/gateway threads

**`clear_interrupt()` — `run_agent.py:2330-2361`**
- Clears both interrupt and steer atomically
- `interrupt()` also clears `_pending_steer` (line 2361) — interrupt supersedes pending steer

### Drain points

**`conversation_loop.py:887`** — Pre-API-call drain:
```python
_pre_api_steer = agent._drain_pending_steer()
if _pre_api_steer:
    # Scan backwards for last tool-role message
    # Append steered text to tool result content (line 897)
    _sm["content"] = existing + marker
```
- Happens BEFORE each API call → model sees steer on next iteration
- **Latency: sub-second** (next iteration after current tool batch)
- Appended to LAST tool result content, NOT as new user message
- If no tool results yet (first iteration), steer stays pending until next tool batch

**`conversation_loop.py:4873`** — Post-conversation drain:
- Hands undrained steer back to caller via `result["pending_steer"]`

### `step_callback` (deprioritized)
**`conversation_loop.py:865`**
```python
agent.step_callback(api_call_count, prev_tools)
```
- AFTER API call, BEFORE tool execution
- Args: (iteration_count, tool_calls_list)
- No return value — cannot abort
- Exceptions caught + logged as debug
- **Read-only observer** — `steer()` is correct injection hook

### Callback signatures

| Callback | Args | Thread | Deadlock risk |
|---|---|---|---|
| `step_callback` | (iteration, tool_list) | main | low |
| `stream_delta_callback` | (delta_text) | streaming | low |
| `tool_start_callback` | (tool_id, name, args) | main | medium |
| `tool_complete_callback` | (tool_id, name, args, result) | main | medium |

Tool callbacks fire synchronously from `agent/tool_executor.py:446, 719, 901, 1338`.
Calling `steer()` from within tool callbacks is **safe** (separate lock).
`interrupt()` from tool callbacks may race with worker-thread tracking.

### Persistence across run_conversation
- NOT auto-cleared between calls
- `conversation_loop.py:4883` calls `agent.clear_interrupt()` at turn boundary
- `_pending_steer` may leak if undrained — gets returned in `result["pending_steer"]`

## Recommended TUI pattern

```python
def on_operator_input(agent: AIAgent, text: str):
    formatted = f"\n[OPERATOR STEER] {text}"
    if agent.steer(formatted):
        emit_activity("operator_steer", {"text": text})
    # else: empty text ignored
```

## Verdict

- ✅ `steer()` is sufficient for operator-inject UX with sub-iteration latency
- ✅ Thread-safe (explicit lock)
- ✅ Non-interrupting (current tools finish)
- ✅ Observable at iteration boundary
- ✅ Multiple calls concatenate cleanly
- ❌ NOT needed: `step_callback` fallback for inject

## Gotchas

1. First iteration before any tool calls → steer waits until next tool batch lands
2. `interrupt()` clears pending steer (by design)
3. `clear_interrupt()` auto-called by conversation_loop at turn boundary
4. Avoid `steer()` from tight loops inside tool callbacks (unnecessary lock contention)

## Implementation implication
TUI input handler:
- Attached mode: directly call `agent.steer(text)` (need shared agent ref)
- Detached mode: append to `inbox.jsonl`; orchestrator daemon's watchfiles handler calls `agent.steer()` when inbox grows
- `step_callback` can stay as no-op (or used for periodic heartbeat)
