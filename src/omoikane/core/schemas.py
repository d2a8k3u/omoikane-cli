"""
Omoikane - Tool schemas
"""

# === M1 ===
PROJECT_START = {
    "name": "project_start",
    "description": (
        "Start an autonomous project run with Omoikane. "
        "Provide the brief, acceptance criteria, and whether starting from scratch or continuation. "
        "Returns a project_id."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "brief": {"type": "string", "description": "The full project brief / final-state definition"},
            "acceptance_criteria": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Concrete, checkable conditions for completion"
            },
            "starting_state": {
                "type": "string",
                "enum": ["scratch", "continuation"],
                "description": "Where the team begins",
                "default": "scratch"
            }
        },
        "required": ["brief", "acceptance_criteria"]
    }
}

PROJECT_STATUS = {
    "name": "project_status",
    "description": "Get current status of a project (phase, tasks, blockers, last activity).",
    "parameters": {
        "type": "object",
        "properties": {
            "project_id": {"type": "string", "description": "The project ID returned by project_start"}
        },
        "required": ["project_id"]
    }
}

BOOK_LOG = {
    "name": "book_log",
    "description": "Append a decision, note or phase change to a Project Book.",
    "parameters": {
        "type": "object",
        "properties": {
            "project_id": {"type": "string", "description": "Project the entry belongs to"},
            "kind": {"type": "string", "enum": ["decision", "note", "phase_change"]},
            "summary": {"type": "string"},
            "data": {"type": "object"}
        },
        "required": ["project_id", "kind", "summary"]
    }
}

# === M3 ===
BOOK_DELEGATE = {
    "name": "book_delegate",
    "description": (
        "Record a delegation in the Project Book and decide execution mode (M5). "
        "Used by the orchestrator to assign work to specialist agents."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "project_id": {"type": "string"},
            "task": {"type": "string", "description": "Task identifier"},
            "to_role": {"type": "string", "description": "Target agent role"},
            "expected": {"type": "string", "description": "What output is expected"},
            "mode": {"type": "string", "enum": ["in_process", "isolated"], "description": "Execution mode (auto-detected if omitted)"}
        },
        "required": ["project_id", "task", "to_role", "expected"]
    }
}

BOOK_RECORD_RESULT = {
    "name": "book_record_result",
    "description": "Record the result of a delegated task back into the Project Book.",
    "parameters": {
        "type": "object",
        "properties": {
            "project_id": {"type": "string"},
            "task": {"type": "string"},
            "status": {"type": "string", "enum": ["done", "failed", "needs_revision"]},
            "reflection": {"type": "string", "description": "Optional reflection / lessons learned"}
        },
        "required": ["project_id", "task", "status"]
    }
}

# === M5 ===
PROJECT_CONTINUE = {
    "name": "project_continue",
    "description": "Resume a paused or long-running project.",
    "parameters": {
        "type": "object",
        "properties": {
            "project_id": {"type": "string", "description": "Project to resume"}
        },
        "required": ["project_id"]
    }
}

# === Task & artifact tools (spec §8) ===
BOOK_OPEN_TASK = {
    "name": "book_open_task",
    "description": (
        "Create a task in the Book's open list. Used by CTO during kickoff to "
        "file roadmap executor tasks (with phase + milestone_id). Other agents "
        "should call book_request_task instead so CTO can route."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "project_id": {"type": "string"},
            "title": {"type": "string", "description": "Short task title"},
            "assignee_role": {"type": "string", "description": "Agent role to assign", "nullable": True},
            "parent": {"type": "string", "description": "Parent task id", "nullable": True},
            "phase": {
                "type": "string",
                "description": (
                    "Phase tag: analysis | design | implementation | testing | review | meta. "
                    "Drives current_phase auto-advance."
                ),
                "nullable": True,
            },
            "blocked_by": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Task ids that must close before this task is dispatched.",
                "nullable": True,
            },
            "milestone_id": {
                "type": "string",
                "description": "Roadmap milestone id this task belongs to (set via book_set_roadmap).",
                "nullable": True,
            },
            "execution_metadata": {
                "type": "object",
                "description": (
                    "Structured signals for choose_execution_mode: estimated_minutes, "
                    "requires_network, dangerous_commands, background."
                ),
                "nullable": True,
            }
        },
        "required": ["project_id", "title"]
    }
}

BOOK_COMPLETE_TASK = {
    "name": "book_complete_task",
    "description": "Move a task from open to completed (only if its acceptance check passes).",
    "parameters": {
        "type": "object",
        "properties": {
            "project_id": {"type": "string"},
            "task": {"type": "string", "description": "Task id to close"}
        },
        "required": ["project_id", "task"]
    }
}

BOOK_ADD_ARTIFACT = {
    "name": "book_add_artifact",
    "description": "Register an artifact (code, doc, test) produced by the team under the project's artifacts/.",
    "parameters": {
        "type": "object",
        "properties": {
            "project_id": {"type": "string"},
            "path": {"type": "string", "description": "Relative path inside artifacts/ or absolute source path"},
            "kind": {"type": "string", "description": "Artifact kind: code | doc | test | data | other"},
            "note": {"type": "string", "description": "Optional human description"}
        },
        "required": ["project_id", "path", "kind"]
    }
}

BOOK_REFLECT = {
    "name": "book_reflect",
    "description": "Write a reflection (lesson learned) tied to a project, optionally to a specific task.",
    "parameters": {
        "type": "object",
        "properties": {
            "project_id": {"type": "string"},
            "lesson": {"type": "string", "description": "The reflection text"},
            "task": {"type": "string", "description": "Optional task id this reflection is about"}
        },
        "required": ["project_id", "lesson"]
    }
}

# === Sub-agent routing + criteria gating ===

BOOK_REQUEST_TASK = {
    "name": "book_request_task",
    "description": (
        "File a new task that lands on CTO's desk for routing. Any agent can "
        "call this to surface work they cannot or should not handle "
        "themselves. CTO inspects the task next tick and assigns the real "
        "executor via book_assign_task. Do NOT call book_open_task directly — "
        "CTO owns routing."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "project_id": {"type": "string"},
            "title": {
                "type": "string",
                "description": "Short, actionable title of the work being requested",
            },
            "rationale": {
                "type": "string",
                "description": (
                    "Why this task is needed. Reference acceptance criteria, "
                    "blockers, or upstream findings so CTO can route without "
                    "re-investigating."
                ),
            },
            "requester_role": {
                "type": "string",
                "description": "The agent role filing the request (e.g. agent-implementer)",
            },
            "suggested_role": {
                "type": "string",
                "description": "Optional hint about which role should own this. CTO may override.",
            },
        },
        "required": ["project_id", "title", "rationale", "requester_role"],
    },
}

BOOK_ASSIGN_TASK = {
    "name": "book_assign_task",
    "description": (
        "Route a CTO-queued task to its actual executor. Used exclusively by "
        "agent-cto when handling a routing task. Flips routing_status from "
        "'routing' to 'assigned' and overwrites assignee_role; the task then "
        "appears in the orchestrator's next executor slot."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "project_id": {"type": "string"},
            "task": {"type": "string", "description": "Routing task id to assign"},
            "role": {
                "type": "string",
                "description": "Target agent role to own the task",
            },
        },
        "required": ["project_id", "task", "role"],
    },
}

PREPARE_MANAGER_HANDOFF = {
    "name": "prepare_manager_handoff",
    "description": (
        "Build the delegate_task payload for dispatching agent-manager to "
        "ingest a specialist's final report. Returns {goal, context, "
        "toolsets, expected} with the manager's SKILL.md and the report "
        "fields baked into context. Call this from the orchestrator-protocol "
        "session after every specialist return, then pass the payload "
        "straight into delegate_task(role='leaf')."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "project_id": {"type": "string"},
            "task_id": {
                "type": "string",
                "description": "The delegation task the specialist just finished",
            },
            "subagent_role": {
                "type": "string",
                "description": "The role that just ran (e.g. agent-implementer)",
            },
            "subagent_summary": {
                "type": "string",
                "description": "Verbatim final assistant message from the specialist",
            },
            "subagent_exit_status": {
                "type": "string",
                "description": (
                    "success | error | max_iters_reached | timeout — drives "
                    "the manager's decision tree"
                ),
                "default": "success",
            },
        },
        "required": ["project_id", "task_id", "subagent_role", "subagent_summary"],
    },
}


BOOK_SET_ROADMAP = {
    "name": "book_set_roadmap",
    "description": (
        "Commit a roadmap of milestones. Reserved for agent-cto during the "
        "kickoff procedure (or roadmap revision). Overwrites the prior roadmap "
        "in full. Each milestone needs milestone_id and title; optional "
        "description, criteria_indices, status."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "project_id": {"type": "string"},
            "milestones": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "milestone_id": {"type": "string"},
                        "title": {"type": "string"},
                        "description": {"type": "string"},
                        "criteria_indices": {
                            "type": "array",
                            "items": {"type": "integer"},
                        },
                        "status": {
                            "type": "string",
                            "enum": ["planned", "in_progress", "done"],
                        },
                    },
                    "required": ["milestone_id", "title"],
                },
            },
        },
        "required": ["project_id", "milestones"],
    },
}

BOOK_SATISFY_CRITERION = {
    "name": "book_satisfy_criterion",
    "description": (
        "Mark one acceptance criterion as satisfied. Reserved for "
        "agent-qa-reviewer — only after running the actual verification "
        "(command, test, manual check) that backs the verdict. The plugin "
        "stops the project once every criterion is satisfied; do not flip "
        "criteria you have not personally checked."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "project_id": {"type": "string"},
            "index": {
                "type": "integer",
                "description": "Zero-based index into acceptance_criteria",
            },
            "evidence": {
                "type": "string",
                "description": (
                    "Concrete evidence the criterion is met — command + output, "
                    "file path + line numbers, log excerpt, or screenshot path."
                ),
            },
        },
        "required": ["project_id", "index", "evidence"],
    },
}


BOOK_REQUEST_APPROVAL = {
    "name": "book_request_approval",
    "description": (
        "File a one-shot approval request from a specialist subagent when a "
        "Hermes tool call returned ``pending_approval`` (typically the cron "
        "dangerous-command gate). Do NOT loop retrying the blocked command — "
        "file one request, then return your task summary including the "
        "returned approval id. The supervisor surfaces pending approvals to "
        "the operator via the project's delivery channel; the operator "
        "resolves via dashboard or ``hermes omoikane approvals``."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "project_id": {"type": "string"},
            "task_id": {
                "type": "string",
                "description": "The delegation task whose run was blocked.",
            },
            "requester_role": {
                "type": "string",
                "description": "Your agent role (e.g. agent-implementer).",
            },
            "action": {
                "type": "string",
                "description": "Short human description of what you wanted to do.",
            },
            "command": {
                "type": "string",
                "description": "The exact tool input/command Hermes blocked.",
            },
            "reason": {
                "type": "string",
                "description": "One sentence: why this command is necessary for the task.",
            },
        },
        "required": ["project_id", "task_id", "requester_role", "action", "command", "reason"],
    },
}


BOOK_RESOLVE_APPROVAL = {
    "name": "book_resolve_approval",
    "description": (
        "Operator resolves a pending approval. ``decision`` is ``'approve'`` "
        "or ``'deny'``. On approve, the command is appended to the project's "
        "scoped ``approved_commands`` list so the next specialist dispatch "
        "sees it in context; the Hermes-wide ``command_allowlist`` is NOT "
        "modified. Reserved for operator use (CLI / dashboard); subagents "
        "must not call this."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "project_id": {"type": "string"},
            "approval_id": {"type": "string"},
            "decision": {"type": "string", "enum": ["approve", "deny"]},
            "note": {
                "type": "string",
                "description": "Optional operator note recorded with the decision.",
            },
        },
        "required": ["project_id", "approval_id", "decision"],
    },
}

BOOK_REQUEST_SPLIT = {
    "name": "book_request_split",
    "description": (
        "Flag a task as too large to finish in one specialist session and "
        "file a routing task to CTO so it gets split. Call this when you "
        "realise (mid-flight or after a timeout / max_iters return) that "
        "the task as scoped will not fit. The original task is paused — "
        "the orchestrator will NOT re-dispatch it until CTO acts. Do not "
        "use this for clarifying questions or scope changes; this is "
        "specifically for size."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "project_id": {"type": "string"},
            "task": {
                "type": "string",
                "description": "Original task id that is too large.",
            },
            "requester_role": {
                "type": "string",
                "description": (
                    "Role calling for the split (e.g. 'agent-implementer', "
                    "'agent-manager')."
                ),
            },
            "reason": {
                "type": "string",
                "description": (
                    "One-paragraph explanation: what you saw, why you "
                    "believe the task is too big, how far you got."
                ),
            },
            "suggested_subtasks": {
                "type": "array",
                "description": (
                    "Optional structured suggestions for CTO. Each entry: "
                    "{title, estimated_minutes?, suggested_role?, "
                    "rationale?}. CTO is free to ignore or modify them."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "estimated_minutes": {"type": "integer"},
                        "suggested_role": {"type": "string"},
                        "rationale": {"type": "string"},
                    },
                    "required": ["title"],
                },
            },
        },
        "required": ["project_id", "task", "requester_role", "reason"],
    },
}

BOOK_SPLIT_TASK = {
    "name": "book_split_task",
    "description": (
        "CTO replaces an oversized task with N smaller children atomically. "
        "Original task closes as ``closure_kind='split'`` and the children "
        "open with optional ``blocked_by`` chains. Call this in response to "
        "a routing task whose ``execution_metadata.kind == 'split_request'``. "
        "Only CTO should invoke this — manager and specialists use "
        "``book_request_split`` instead."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "project_id": {"type": "string"},
            "task": {
                "type": "string",
                "description": "Original (oversized) task id being replaced.",
            },
            "requester_role": {
                "type": "string",
                "description": "Role performing the split (typically 'agent-cto').",
            },
            "replacement_tasks": {
                "type": "array",
                "description": (
                    "Children to open. Each entry MUST carry "
                    "``title`` and ``assignee_role``. Optional: "
                    "``phase``, ``estimated_minutes``, "
                    "``execution_metadata``, ``milestone_id``, "
                    "``blocked_by`` (list of indices into this array or "
                    "explicit task ids)."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "assignee_role": {"type": "string"},
                        "phase": {"type": "string"},
                        "estimated_minutes": {"type": "integer"},
                        "execution_metadata": {"type": "object"},
                        "milestone_id": {"type": "string"},
                        "blocked_by": {
                            "type": "array",
                            "items": {
                                "oneOf": [
                                    {"type": "integer"},
                                    {"type": "string"},
                                ],
                            },
                        },
                    },
                    "required": ["title", "assignee_role"],
                },
            },
            "reflection": {
                "type": "string",
                "description": (
                    "Optional one-paragraph CTO note explaining the chosen "
                    "split. Persisted under ``reflections/`` so future "
                    "ticks can see the rationale."
                ),
            },
        },
        "required": ["project_id", "task", "requester_role", "replacement_tasks"],
    },
}