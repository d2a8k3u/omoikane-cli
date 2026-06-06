# Phase 2: Tools Porting Audit — Omoikane to hermes-agent SDK

**Scope**: Autonomous tool handler migration from Hermes plugin to standalone `omoikane.tools.handlers` module with SDK registration.

**Target**: Each of 19 handlers ported to be registry-compatible with `tools.registry.register()` (SDK-based, not Hermes).

---

## 1. Tool Registration Mappings

All 19 tools registered under toolset **"omoikane"** in Hermes (line 13–67 of `__init__.py`):

| Tool Name | Schema Constant | Handler Function | Lines |
|-----------|-----------------|------------------|-------|
| project_start | PROJECT_START | tools.project_start | 109–167 |
| project_status | PROJECT_STATUS | tools.project_status | 170–192 |
| book_log | BOOK_LOG | tools.book_log | 195–212 |
| book_delegate | BOOK_DELEGATE | tools.book_delegate | 217–273 |
| book_record_result | BOOK_RECORD_RESULT | tools.book_record_result | 276–311 |
| project_continue | PROJECT_CONTINUE | tools.project_continue | 692–724 |
| book_open_task | BOOK_OPEN_TASK | tools.book_open_task | 316–353 |
| book_complete_task | BOOK_COMPLETE_TASK | tools.book_complete_task | 356–370 |
| book_add_artifact | BOOK_ADD_ARTIFACT | tools.book_add_artifact | 373–386 |
| book_reflect | BOOK_REFLECT | tools.book_reflect | 389–401 |
| book_request_task | BOOK_REQUEST_TASK | tools.book_request_task | 406–433 |
| book_assign_task | BOOK_ASSIGN_TASK | tools.book_assign_task | 436–458 |
| book_satisfy_criterion | BOOK_SATISFY_CRITERION | tools.book_satisfy_criterion | 659–687 |
| book_set_roadmap | BOOK_SET_ROADMAP | tools.book_set_roadmap | 461–482 |
| prepare_manager_handoff | PREPARE_MANAGER_HANDOFF | tools.prepare_manager_handoff | 572–656 |
| book_request_approval | BOOK_REQUEST_APPROVAL | tools.book_request_approval | 485–531 |
| book_resolve_approval | BOOK_RESOLVE_APPROVAL | tools.book_resolve_approval | 534–569 |
| book_request_split | BOOK_REQUEST_SPLIT | tools.book_request_split | 726–787 |
| book_split_task | BOOK_SPLIT_TASK | tools.book_split_task | 790–831 |

---

## 2. Per-Handler Porting Table

| Handler Name | Line Range | Hermes Coupling | Port Action |
|---|---|---|---|
| project_start | 109–167 | `_capture_origin()` (env + hermes_cli.config) | REWRITE_ORIGIN |
| project_status | 170–192 | None | VERBATIM |
| book_log | 195–212 | None | VERBATIM |
| book_delegate | 217–273 | `get_registry()` (local) | VERBATIM |
| book_record_result | 276–311 | None | VERBATIM |
| project_continue | 692–724 | None | VERBATIM |
| book_open_task | 316–353 | None | VERBATIM |
| book_complete_task | 356–370 | None | VERBATIM |
| book_add_artifact | 373–386 | None | VERBATIM |
| book_reflect | 389–401 | None | VERBATIM |
| book_request_task | 406–433 | None | VERBATIM |
| book_assign_task | 436–458 | None | VERBATIM |
| book_satisfy_criterion | 659–687 | None | VERBATIM |
| book_set_roadmap | 461–482 | None | VERBATIM |
| prepare_manager_handoff | 572–656 | `get_registry()` (local) | VERBATIM |
| book_request_approval | 485–531 | None | VERBATIM |
| book_resolve_approval | 534–569 | None | VERBATIM |
| book_request_split | 726–787 | None | VERBATIM |
| book_split_task | 790–831 | None | VERBATIM |

**Summary by Action Type**:
- **VERBATIM**: 17 handlers (no Hermes runtime coupling)
- **REWRITE_ORIGIN**: 1 handler (project_start)
- **DROP_CRON**: 0 handlers (cron is internal to handlers, not gated)
- **DROP_TRANSPORT**: 0 handlers (no send_message_tool calls)

---

## 3. Helper Functions (Private)

Located in `tools.py`, lines 18–106. Must ship in `handlers.py`:

| Function | Signature | Purpose | Lines |
|----------|-----------|---------|-------|
| `_ensure_project_cron_safe` | `(project_id: str) -> Tuple[Optional[str], Optional[str]]` | Lazy-import and safely spin up per-project supervisor cron; returns (cron_id, error_msg). Used by project_start only. | 18–32 |
| `_remove_project_cron_safe` | `(project_id: str) -> Tuple[bool, Optional[str]]` | Lazy-import and safely tear down per-project cron; returns (success, error_msg). Defined but unused in tools.py; likely called from hooks or CLI. | 35–44 |
| `_bind_session` | `(kwargs: dict, project_id: str) -> None` | Extract session_id from kwargs or ctx and bind it to project_id via hooks.bind_session_to_project(). Best-effort attribution. Used by project_start and project_continue. | 47–54 |
| `_capture_origin` | `() -> Optional[dict]` | Read Hermes session context vars (HERMES_SESSION_*) via gateway.session_context or os.getenv fallback; fall back to hermes_cli.config → omoikane.default_notify_channel. Returns {platform, chat_id, thread_id, user_id, captured_at} or None. **REQUIRES REWRITE FOR SDK**. | 57–106 |

---

## 4. Schema Constants (Imported from `.schemas`)

All 19 schemas defined in `schemas.py`:

```
PROJECT_START, PROJECT_STATUS, BOOK_LOG,
BOOK_DELEGATE, BOOK_RECORD_RESULT, PROJECT_CONTINUE,
BOOK_OPEN_TASK, BOOK_COMPLETE_TASK, BOOK_ADD_ARTIFACT, BOOK_REFLECT,
BOOK_REQUEST_TASK, BOOK_ASSIGN_TASK, BOOK_SATISFY_CRITERION, BOOK_SET_ROADMAP,
PREPARE_MANAGER_HANDOFF,
BOOK_REQUEST_APPROVAL, BOOK_RESOLVE_APPROVAL,
BOOK_REQUEST_SPLIT, BOOK_SPLIT_TASK
```

All are imported in `__init__.py` line 10 as `from . import schemas` and accessed as `schemas.CONST_NAME`.

---

## 5. Critical Dependencies & Rewrites

### `_capture_origin()` Rewrite Strategy (Lines 57–106)

**Current Flow**:
1. Try `gateway.session_context.get_session_env()` for HERMES_SESSION_* vars
2. Fall back to `os.getenv()` if gateway unavailable
3. If both empty, try `hermes_cli.config.load_config()` → `config["omoikane"]["default_notify_channel"]`
4. Parse platform:chat_id from fallback or return None

**SDK-side Rewrite**:
- Remove gateway.session_context dependency (Hermes-only)
- Keep os.getenv() for HERMES_SESSION_* (standard envvars, SDK-agnostic)
- Replace hermes_cli.config with omoikane-local config file (e.g., `~/.omoikane/config.json` or env var `OMOIKANE_DEFAULT_NOTIFY_CHANNEL`)
- Signature stays same; returns same dict shape

### `_bind_session()` (Lines 47–54)

- Calls `hooks.bind_session_to_project(session_id, project_id)`
- `hooks.bind_session_to_project` is defined in omoikane's own `hooks.py`, not Hermes
- **Port as-is**: SDK doesn't require session binding; remove call or make it no-op in handlers.py

### Cron Functions (`_ensure_project_cron_safe`, `_remove_project_cron_safe`)

- Internal to omoikane: `from .project_cron import ensure_project_cron`
- No Hermes runtime dependency; pure project_cron module call
- **Port as-is**: cron stays; lazy import remains

### `get_registry()` (Lines 10, 234, 604)

- `from .agents_registry import get_registry`
- Omoikane's own local registry (not SDK's tools.registry)
- Used to fetch SKILL.md content by role name
- **Port as-is**: local module, no Hermes coupling

---

## 6. Hermes Coupling Details

### Imports Requiring Removal or Rewrite

| Module | Used in | Status |
|--------|---------|--------|
| `gateway.session_context` | _capture_origin (line 72) | REMOVE; fallback to os.getenv only |
| `hermes_cli.config` | _capture_origin (line 85) | REWRITE; use omoikane config file |
| `ctx.register_tool` | __init__.py (Hermes plugin API) | N/A for SDK version |

### Safe Imports (Omoikane Internal)

```python
from .book import ProjectBook
from .agents_registry import get_registry
from .orchestrator import TeamOrchestrator
from .execution import choose_execution_mode
from .hooks import bind_session_to_project
from .project_cron import ensure_project_cron, remove_project_cron
from .schemas import [all 19 constants]
```

All safe; ship as-is.

---

## 7. Omoikane Toolset Name

**Confirmed toolset**: `"omoikane"` (line 13–67, __init__.py)

All 19 tools registered under this single toolset. SDK registration will use same name:
```python
tools.registry.register(
    name="project_start",
    toolset="omoikane",
    schema=PROJECT_START,
    handler=project_start
)
```

---

## 8. Phase 2 Execution Plan

### Step 1: Create `omoikane/tools/handlers.py`

- Copy all 19 handler functions (project_start → book_split_task)
- Include helper functions: `_ensure_project_cron_safe`, `_remove_project_cron_safe`, `_bind_session`, `_capture_origin`
- Rewrite `_capture_origin()` to remove gateway/hermes_cli; add omoikane config logic
- Import schemas from `.schemas` (or parent package)

### Step 2: Create `omoikane/tools/registry.py` (or `__init__.py`)

```python
from hermes_agent_sdk import tools
from . import handlers
from ..schemas import PROJECT_START, PROJECT_STATUS, ...

def register_all():
    """Register all 19 Omoikane tools with hermes-agent SDK."""
    tools.registry.register(
        name="project_start",
        toolset="omoikane",
        schema=PROJECT_START,
        handler=handlers.project_start
    )
    # ... repeat for 18 more
```

### Step 3: Remove Hermes Plugin Infrastructure

- Delete `__init__.py:register(ctx)` function (Hermes-only)
- Delete hooks registration (move to SDK equivalents if needed)
- Delete CLI handler registration (move to separate CLI module)

### Step 4: Validation

- No import of `gateway`, `hermes_cli`, `ctx.register_tool`
- All 19 handlers pass unit tests with SDK mock
- `_capture_origin()` reads omoikane config file successfully

---

## Notes

1. **Session Binding** (_bind_session): Called in project_start (line 141) and project_continue (line 705). In SDK mode, this can be made optional or removed if session tracking is handled at SDK level.

2. **Project Cron**: Internal module dependency. Lazy-imported in handlers; safe to ship.

3. **Registry (agents_registry)**: Omoikane's own skill registry. Not the SDK's tools.registry. Used only by book_delegate and prepare_manager_handoff to fetch role SKILL content. Keep as-is.

4. **No Transport Layer**: Zero calls to send_message_tool or approval gatefold. Phase 6/7 transport will be added later; handlers stay pure.

---

**Generated**: Phase 2 Tools Audit  
**Project**: Omoikane → hermes-agent SDK  
**Status**: Ready for implementation
