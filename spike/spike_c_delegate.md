# Spike C: Child Toolset Propagation in delegate_task

**Question:** Does the child agent spawned by `delegate_task` see custom "omoikane" toolset?  
**Answer:** CONDITIONAL YES — but only if parent agent has "omoikane" in `enabled_toolsets`.

---

## 1. delegate_task Handler Implementation

**File:** `/Users/davidkulhanek/WorkingLibrary/Github/omoikane/.venv/lib/python3.11/site-packages/tools/delegate_tool.py`

### Handler Signature (line 1968–1978)
```python
def delegate_task(
    goal: Optional[str] = None,
    context: Optional[str] = None,
    toolsets: Optional[List[str]] = None,
    tasks: Optional[List[Dict[str, Any]]] = None,
    max_iterations: Optional[int] = None,
    acp_command: Optional[str] = None,
    acp_args: Optional[List[str]] = None,
    role: Optional[str] = None,
    parent_agent=None,
) -> str:
```

### Schema Parameters (lines 2719–2836)
- `goal` (string): Task for subagent
- `context` (string): Background info
- `toolsets` (array of strings): **LLM-provided toolset names** — this is how a child requests specific toolsets
- `tasks` (array): Batch mode with per-task toolsets
- `role` (enum: "leaf" | "orchestrator"): Whether child can delegate further

**Critical:** `toolsets` is **optional** — the LLM can omit it, forcing default behavior.

---

## 2. Child Toolset Propagation Logic

### Default (LLM Doesn't Specify Toolsets)

**Location:** Lines 960–995 in `_build_child_agent()`

```python
parent_enabled = getattr(parent_agent, "enabled_toolsets", None)
if parent_enabled is not None:
    parent_toolsets = set(parent_enabled)
elif parent_agent and hasattr(parent_agent, "valid_tool_names"):
    # enabled_toolsets is None (all tools) — derive from loaded tool names
    import model_tools
    parent_toolsets = {
        ts
        for name in parent_agent.valid_tool_names
        if (ts := model_tools.get_toolset_for_tool(name)) is not None
    }
else:
    parent_toolsets = set(DEFAULT_TOOLSETS)
```

**Behavior:** Child inherits **parent's entire enabled_toolsets** set.

If parent has `enabled_toolsets=["file", "web", "delegation", "omoikane"]`:
- Child gets `["file", "web", "delegation", "omoikane"]` **by default** (no toolsets arg needed).

If parent has `enabled_toolsets=None` (all tools enabled):
- Child derives toolsets from `valid_tool_names` (loaded tools discovered at parent startup).

### Explicit (LLM Specifies `toolsets=["omoikane"]`)

**Location:** Lines 979–995

```python
if toolsets:
    # Intersect with parent — subagent must not gain tools the parent lacks.
    expanded_parent = _expand_parent_toolsets(parent_toolsets)
    child_toolsets = [t for t in toolsets if t in expanded_parent]
    if _get_inherit_mcp_toolsets():
        child_toolsets = _preserve_parent_mcp_toolsets(
            child_toolsets, parent_toolsets
        )
    child_toolsets = _strip_blocked_tools(child_toolsets)
```

**Behavior:** **Intersection** — child gets only toolsets it explicitly requests **AND** parent has.

- LLM calls: `delegate_task(goal="...", toolsets=["omoikane"])`
- Child receives: `["omoikane"]` ✓ (if parent has "omoikane")
- Child receives: `[]` ✗ (if parent lacks "omoikane" — intersection fails)

### Custom Toolset Inclusion: When Will Child See "omoikane"?

**Precondition:** Parent must have "omoikane" in `enabled_toolsets`.

Two paths:

1. **Parent initializes with:** `AIAgent(..., enabled_toolsets=["file", "web", "delegation", "omoikane"])`
   - Child (no toolsets arg): inherits all four toolsets ✓
   - Child (toolsets=["omoikane"]): gets ["omoikane"] ✓

2. **Parent initializes with:** `AIAgent(..., enabled_toolsets=["file", "web"])`
   - Child (no toolsets arg): gets ["file", "web"] ✗ (no omoikane)
   - Child (toolsets=["omoikane"]): gets [] ✗ (intersection with parent's ["file", "web"] = empty)

---

## 3. Toolset Whitelist Constraint (Safety)

**Blocked Toolsets (Hard Coded):** Lines 44–53 and 706–714

```python
DELEGATE_BLOCKED_TOOLS = frozenset([
    "delegate_task",  # no recursive delegation
    "clarify",        # no user interaction
    "memory",         # no writes to shared MEMORY.md
    "send_message",   # no cross-platform side effects
    "execute_code",   # children should reason step-by-step
])

def _strip_blocked_tools(toolsets: List[str]) -> List[str]:
    blocked_toolset_names = {
        "delegation",   # stripped before re-adding for orchestrators
        "clarify",
        "memory",
        "code_execution",
    }
    return [t for t in toolsets if t not in blocked_toolset_names]
```

**Leaf children cannot have:** delegation, clarify, memory, code_execution, send_message tools.

**Orchestrators re-gain delegation:** Lines 1001–1002
```python
if effective_role == "orchestrator" and "delegation" not in child_toolsets:
    child_toolsets.append("delegation")
```

**"omoikane" is NOT blocked** — if parent has it and child requests it, child gets it. ✓

---

## 4. Sub-AIAgent Construction Args

**Location:** Lines 1140–1171 in `_build_child_agent()`

```python
child = AIAgent(
    base_url=effective_base_url,
    api_key=effective_api_key,
    model=effective_model,
    provider=effective_provider,
    api_mode=effective_api_mode,
    acp_command=effective_acp_command,
    acp_args=effective_acp_args,
    max_iterations=max_iterations,
    enabled_toolsets=child_toolsets,          # <-- TOOLSET PROPAGATION
    quiet_mode=True,
    ephemeral_system_prompt=child_prompt,
    skip_context_files=True,
    skip_memory=True,
    clarify_callback=None,
    thinking_callback=child_thinking_cb,
    session_db=getattr(parent_agent, "_session_db", None),
    parent_session_id=getattr(parent_agent, "session_id", None),
    tool_progress_callback=child_progress_cb,
    iteration_budget=None,  # fresh budget per subagent
)
```

| Aspect | Parent → Child |
|--------|---|
| Callbacks (tool_progress_callback) | ✓ Propagated (new progress callback created for each child) |
| API key / base_url / model | ✓ **Propagated by default** (lines 1055–1070); config overrides can replace |
| Reasoning config | ✓ **Inherited** (lines 1095–1111); config override can change |
| Fallback provider chain | ✓ **Inherited** (line 1117) |
| session_id/task_id | ✗ **NOT inherited** — each child gets a fresh `subagent_id` (line 954) and separate `session_db` |
| Conversation history | ✗ **NOT shared** — child starts fresh (line 1151: `ephemeral_system_prompt` replaces full system prompt) |
| enabled_toolsets | ✓ **Propagated, then filtered** (lines 960–1002, passed at line 1153) |

---

## 5. Trace Visibility: Where Child Activity Shows Up

**Parent can see:**
- Child **final summary** in `delegate_task` result (line 2362: `results` array)
- Child **token usage** + cost (lines 1742–1767)
- Child **tool trace** (metadata: tool name, arg bytes, result bytes, error status) — lines 1687–1720
- Child **output tail** (last 8 tool results for observability) — line 1831

**Parent CANNOT see:**
- Child's intermediate tool results (line 16 in docstring: "only the final summary is returned")
- Child's conversation messages (child's `messages` list is extracted once for the summary, then discarded)
- Child's `tool_start_callback` events (child is separate AIAgent instance in ThreadPoolExecutor)

**Activity observability:** Child emits `tool_progress_callback` events (line 1169) that relay to parent's UI overlay, but parent's `tool_start_callback` is NOT invoked.

---

## 6. WILL Child See "omoikane"? — Concrete Decision Tree

### Parent CTO Checklist

**MUST do:**
1. Register "omoikane" globally: `tools.registry.register(...)`  ✓ (already done in plugin)
2. Pass `enabled_toolsets=[..., "omoikane"]` when creating parent AIAgent
3. Ensure parent has "omoikane" in its `valid_tool_names` at runtime

**LLM-facing prompt:**
```
When delegating work, always include 'omoikane' in the toolsets arg if the task
requires booking or managing resources:

delegate_task(
    goal="Book 3 hotel rooms for the team",
    context="Company is headquartered in San Francisco...",
    toolsets=["terminal", "file", "web", "omoikane"]  # <-- INCLUDE OMOIKANE HERE
)

If you omit 'omoikane', the child will not have access to book_* tools.
```

**Sample delegate_task call form LLM would issue:**
```python
{
  "goal": "Book three hotels in San Francisco for 2025-06-10...",
  "context": "Company is on a Friday-trip summit. Budget: $200/night per room.",
  "toolsets": ["terminal", "file", "web", "omoikane"],
  "role": "leaf"
}
```

---

## 7. Risk & Fallback: If Children CANNOT Call book_*

**Scenario:** Parent delegates a booking task but forgets to include "omoikane" in toolsets.

**Fallback:** Parent CTO **calls book_* tools itself** after each delegation completes:

```python
# Parent delegates research
result = delegate_task(
    goal="Find best hotels...",
    toolsets=["terminal", "file", "web"]  # OOPS: forgot "omoikane"
)
# Child returns: "Best hotel: Marriott, 123 Market St, $189/night"

# Parent calls book_* directly
book_hotel(
    name="Marriott",
    address="123 Market St, San Francisco",
    nights=3,
    date="2025-06-10"
)
```

**Cost:** One extra parent turn, but **orchestration protocol doesn't break** — parent is responsible for the final booking.

**Mitigation:** Update parent's system prompt to remind LLM: *"Always include 'omoikane' when delegating booking tasks."*

---

## Summary

| Question | Answer |
|----------|--------|
| Will child see omoikane? | **CONDITIONAL YES** — only if parent has it in `enabled_toolsets` AND LLM requests it in `toolsets` arg |
| Default (no toolsets arg)? | Child inherits parent's full `enabled_toolsets` ✓ |
| Explicit (toolsets=["omoikane"])? | Child gets it IF parent has it (intersection), otherwise empty ✗ |
| Blocked toolsets? | No — "omoikane" is NOT in DELEGATE_BLOCKED_TOOLS |
| Fallback if child can't access? | Parent CTO calls book_* tools after child returns summary |

**Code proof:** Lines 960–995 (_build_child_agent) show intersection + inheritance logic.

