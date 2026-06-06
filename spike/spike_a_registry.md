# Spike A — tools.registry.register runtime mutation

## Findings

### Registry class
**`tools/registry.py:151-306`** — `ToolRegistry` is thread-safe singleton (instantiated line 544). Stores tools in `self._tools: Dict[str, ToolEntry]`. Each mutation bumps `_generation` counter for cache invalidation.

Attributes:
- `_tools`: name → ToolEntry
- `_toolset_checks`: toolset → check_fn
- `_lock`: threading.RLock

### `register()` signature
**`tools/registry.py:234-248`**

```python
def register(self,
    name: str,                       # unique tool name
    toolset: str,                    # group e.g. "omoikane"
    schema: dict,                    # JSON Schema with parameters
    handler: Callable,               # (args: dict, **kwargs) -> str
    check_fn: Callable = None,       # optional: () -> bool
    requires_env: list = None,
    is_async: bool = False,
    description: str = "",
    emoji: str = "",
    max_result_size_chars: int | float | None = None,
    dynamic_schema_overrides: Callable = None,
    override: bool = False,
):
```

Safety (lines 257-289): rejects accidental overwrites from different toolsets unless `override=True`.

### Tool snapshot timing — CRITICAL
**`agent/agent_init.py:920-924`**

```python
agent.tools = _ra().get_tool_definitions(
    enabled_toolsets=enabled_toolsets,
    disabled_toolsets=disabled_toolsets,
    quiet_mode=agent.quiet_mode,
)
```

**Snapshot is captured ONCE at AIAgent construction.** Tools registered AFTER construction NOT visible to that agent.

### Discovery
- `discover_builtin_tools()` called at `model_tools.py:180` (module import)
- Plugin discovery at `model_tools.py:198`
- **Custom tools must be registered BEFORE `import run_agent` or `AIAgent()` construction**

### Handler contract
**`tools/registry.py:390-416`**

```python
def handler(args: Dict[str, Any], **kwargs) -> str:
    """
    args   — validated JSON Schema params
    kwargs — task_id (str), user_task (Optional[str]), other middleware fields
    Returns: JSON string (use tool_result() / tool_error() helpers)
    Exceptions: caught by registry.dispatch(), wrapped as {"error": "..."}
    """
```

Async handlers: `is_async=True`. Registry uses `_run_async()` bridge (`model_tools.py:84-173`).

### check_fn
**`tools/registry.py:121-149`** (TTL cache, ~30s) & `182-190` (eval)

- Invoked BEFORE tool included in agent's available set
- Returns bool; False → entire toolset omitted
- Cannot block per-call or modify args (per-toolset only)
- Exceptions → unavailable

### Canonical pattern (from `tools/browser_tool.py:3782-3823`)

```python
from tools.registry import registry, tool_result, tool_error

def book_log_handler(args: dict, **kwargs) -> str:
    try:
        from omoikane.tools.handlers import book_log
        return tool_result(book_log(args, **kwargs))
    except Exception as e:
        return tool_error(str(e))

registry.register(
    name="book_log",
    toolset="omoikane",
    schema={
        "name": "book_log",
        "description": "...",
        "parameters": {
            "type": "object",
            "properties": {...},
            "required": [...],
        },
    },
    handler=book_log_handler,
    emoji="📓",
)
```

## Verdict

- ✅ Custom tools via `registry.register()` BEFORE AIAgent construction → visible
- ✅ Registry is module singleton, all agents share it
- ❌ Registration AFTER construction NOT visible to that agent — snapshot taken
- ✅ Handler signature matches plan (`(args, **kwargs) -> str`)
- ✅ check_fn TTL-cached, fail-closed

## Implementation implication
`src/omoikane/__init__.py` must call `register_book_tools()` at import time. Any code path that constructs `AIAgent` must first `import omoikane` (or call `register_book_tools()` explicitly).
