"""
matrixmouse/tools/__init__.py

Aggregates all agent tools into a single importable package.
Exposes:
    TOOLS           — full list of all Tool descriptors (fn + schema)
    TOOL_REGISTRY   — dict mapping tool name → Tool descriptor (for loop dispatch)
    tools_for_role  — returns a frozenset of tool names permitted for a given role

To add a new tool:
    1. Define the function and its companion *_SCHEMA dict in the appropriate
       submodule with type hints and a Google-style docstring.
    2. Import both here and add a Tool(fn=..., schema=...) entry to TOOLS.
    3. TOOL_REGISTRY is built automatically from TOOLS — no separate update needed.
    4. Add the tool name to the appropriate role set(s) in _ROLE_TOOL_SETS.

Role-based tool scoping:
    Each AgentRole has an explicit allowlist of tool names. The loop enforces
    this at dispatch time — disallowed tool calls return an error message to
    the agent rather than raising an exception.

Tool schema convention:
    Each tool's schema uses Anthropic's ``input_schema`` key convention
    (JSON Schema object). Inference adapters are responsible for translating
    this into whatever format their backend requires — e.g. OpenAI-compat
    backends use ``parameters`` instead of ``input_schema``.

    Schema dicts follow this shape::

        {
            "name": "tool_name",
            "description": "One-line description.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "arg": {"type": "string", "description": "..."}
                },
                "required": ["arg"]
            }
        }

    The ``Tool`` dataclass (defined in ``inference.base``) pairs each callable
    with its schema.  ``loop.py`` receives ``list[Tool]`` for the current role
    and passes it to the backend via ``LLMBackend.chat(tools=...)``.

    NOTE: ``tools_for_role_list()`` now returns ``list[Tool]``, not a list of
    raw callables.  Any call site that was previously iterating the result as
    plain functions must be updated to access ``tool.fn`` for dispatch and
    ``tool.schema`` for schema extraction.  The primary call site is
    ``loop.py``.

Submodules:
    file_tools       — read, write, str_replace, append
    git_tools        — branch, commit, diff, log, push, PR
    navigation_tools — directory structure, grep, find
    code_tools       — AST-based function and class inspection
    test_tools       — run pytest, parse results
    task_tools       — task lifecycle, Critic approve/deny, Manager task management
    comms_tools      — request_clarification
    merge_tools      — show_conflict, resolve_conflict
    _safety.py       — path validation (internal, not a tool module)
"""
import logging

logger = logging.getLogger(__name__)

from matrixmouse.inference.base import Tool
from matrixmouse.task import AgentRole

from matrixmouse.tools.file_tools import (
    read_file,          READ_FILE_SCHEMA,
    str_replace,        STR_REPLACE_SCHEMA,
    append_to_file,     APPEND_TO_FILE_SCHEMA,
)
from matrixmouse.tools.task_tools import (
    declare_complete,   DECLARE_COMPLETE_SCHEMA,
    create_task,        CREATE_TASK_SCHEMA,
    split_task,         SPLIT_TASK_SCHEMA,
    update_task,        UPDATE_TASK_SCHEMA,
    get_task_info,      GET_TASK_INFO_SCHEMA,
    list_tasks,         LIST_TASKS_SCHEMA,
    approve,            APPROVE_SCHEMA,
    deny,               DENY_SCHEMA,
)
from matrixmouse.tools.git_tools import (
    git_commit,         GIT_COMMIT_SCHEMA,
    get_git_diff,       GET_GIT_DIFF_SCHEMA,
    get_git_log,        GET_GIT_LOG_SCHEMA,
    get_git_status,     GET_GIT_STATUS_SCHEMA,
    push_branch,        PUSH_BRANCH_SCHEMA,
    clone_repo,         CLONE_REPO_SCHEMA,
)
from matrixmouse.tools.merge_tools import (
    show_conflict,      SHOW_CONFLICT_SCHEMA,
    resolve_conflict,   RESOLVE_CONFLICT_SCHEMA,
)
from matrixmouse.tools.code_tools import (
    get_function_def,           GET_FUNCTION_DEF_SCHEMA,
    get_function_list,          GET_FUNCTION_LIST_SCHEMA,
    get_class_summary,          GET_CLASS_SUMMARY_SCHEMA,
    get_dependencies,           GET_DEPENDENCIES_SCHEMA,
    get_call_sites,             GET_CALL_SITES_SCHEMA,
    get_imports,                GET_IMPORTS_SCHEMA,
)
from matrixmouse.tools.navigation_tools import (
    get_project_directory_structure,    GET_PROJECT_DIRECTORY_STRUCTURE_SCHEMA,
    get_file_summary,                   GET_FILE_SUMMARY_SCHEMA,
    project_grep,                       PROJECT_GREP_SCHEMA,
    project_find,                       PROJECT_FIND_SCHEMA,
)
from matrixmouse.tools.test_tools import (
    run_tests,          RUN_TESTS_SCHEMA,
    run_single_test,    RUN_SINGLE_TEST_SCHEMA,
)
from matrixmouse.tools.comms_tools import (
    request_clarification,  REQUEST_CLARIFICATION_SCHEMA,
)


# ---------------------------------------------------------------------------
# Full tool list — Tool descriptors for all inference backends
# ---------------------------------------------------------------------------

TOOLS: list[Tool] = [
    # file_tools
    Tool(fn=read_file,          schema=READ_FILE_SCHEMA),
    Tool(fn=str_replace,        schema=STR_REPLACE_SCHEMA),
    Tool(fn=append_to_file,     schema=APPEND_TO_FILE_SCHEMA),
    # task_tools
    Tool(fn=declare_complete,   schema=DECLARE_COMPLETE_SCHEMA),
    Tool(fn=create_task,        schema=CREATE_TASK_SCHEMA),
    Tool(fn=split_task,         schema=SPLIT_TASK_SCHEMA),
    Tool(fn=update_task,        schema=UPDATE_TASK_SCHEMA),
    Tool(fn=get_task_info,      schema=GET_TASK_INFO_SCHEMA),
    Tool(fn=list_tasks,         schema=LIST_TASKS_SCHEMA),
    Tool(fn=approve,            schema=APPROVE_SCHEMA),
    Tool(fn=deny,               schema=DENY_SCHEMA),
    # git_tools
    Tool(fn=git_commit,         schema=GIT_COMMIT_SCHEMA),
    Tool(fn=get_git_diff,       schema=GET_GIT_DIFF_SCHEMA),
    Tool(fn=get_git_log,        schema=GET_GIT_LOG_SCHEMA),
    Tool(fn=get_git_status,     schema=GET_GIT_STATUS_SCHEMA),
    Tool(fn=push_branch,        schema=PUSH_BRANCH_SCHEMA),
    Tool(fn=clone_repo,         schema=CLONE_REPO_SCHEMA),
    # merge_tools
    Tool(fn=show_conflict,      schema=SHOW_CONFLICT_SCHEMA),
    Tool(fn=resolve_conflict,   schema=RESOLVE_CONFLICT_SCHEMA),
    # code_tools
    Tool(fn=get_function_def,           schema=GET_FUNCTION_DEF_SCHEMA),
    Tool(fn=get_function_list,          schema=GET_FUNCTION_LIST_SCHEMA),
    Tool(fn=get_class_summary,          schema=GET_CLASS_SUMMARY_SCHEMA),
    Tool(fn=get_dependencies,           schema=GET_DEPENDENCIES_SCHEMA),
    Tool(fn=get_call_sites,             schema=GET_CALL_SITES_SCHEMA),
    Tool(fn=get_imports,                schema=GET_IMPORTS_SCHEMA),
    # navigation_tools
    Tool(fn=get_project_directory_structure,    schema=GET_PROJECT_DIRECTORY_STRUCTURE_SCHEMA),
    Tool(fn=get_file_summary,                   schema=GET_FILE_SUMMARY_SCHEMA),
    Tool(fn=project_grep,                       schema=PROJECT_GREP_SCHEMA),
    Tool(fn=project_find,                       schema=PROJECT_FIND_SCHEMA),
    # test_tools
    Tool(fn=run_tests,          schema=RUN_TESTS_SCHEMA),
    Tool(fn=run_single_test,    schema=RUN_SINGLE_TEST_SCHEMA),
    # comms_tools
    Tool(fn=request_clarification,  schema=REQUEST_CLARIFICATION_SCHEMA),
]

# Built automatically from TOOLS — never update this manually.
# Maps tool name → Tool descriptor.  Loop dispatch uses tool.fn; schema
# extraction uses tool.schema.
TOOL_REGISTRY: dict[str, Tool] = {t.fn.__name__: t for t in TOOLS}


# ---------------------------------------------------------------------------
# Role-based tool allowlists
# ---------------------------------------------------------------------------
#
# Each role has an explicit frozenset of permitted tool names.
# The loop enforces this at dispatch time.
#
# Design notes:
#   - Manager is the only role that can create, split, or update tasks.
#   - Critic is the only role that can call approve() or deny().
#   - Coder and Writer share most file/git tools but Writer has no
#     access to code_tools or test_tools — those are coding concerns.
#   - request_clarification and declare_complete are available to all
#     non-Critic roles. Critic uses approve/deny instead of declare_complete.
#   - get_task_info and list_tasks are read-only and available to all roles
#     so any agent can orient itself in the task graph.

_MANAGER_TOOLS: frozenset[str] = frozenset({
    # Task management (Manager-exclusive write access)
    "create_task",
    "split_task",
    "update_task",
    # Task reading (shared)
    "get_task_info",
    "list_tasks",
    # Git (read-only for Manager — it orchestrates, doesn't implement)
    "get_git_log",
    "get_git_status",
    # Navigation (for gathering context during planning)
    "get_project_directory_structure",
    "get_file_summary",
    "project_grep",
    "project_find",
    # File reading (for gathering context, not writing)
    "read_file",
    # Communication
    "request_clarification",
    "declare_complete",
})

_CODER_TOOLS: frozenset[str] = frozenset({
    # File tools
    "read_file",
    "str_replace",
    "append_to_file",
    # Git tools
    "git_commit",
    "get_git_diff",
    "get_git_log",
    "get_git_status",
    "push_branch",
    "clone_repo",
    # Code tools
    "get_function_def",
    "get_function_list",
    "get_class_summary",
    "get_dependencies",
    "get_call_sites",
    "get_imports",
    # Navigation
    "get_project_directory_structure",
    "get_file_summary",
    "project_grep",
    "project_find",
    # Test tools
    "run_tests",
    "run_single_test",
    # Task reading
    "get_task_info",
    "list_tasks",
    # Communication
    "request_clarification",
    "declare_complete",
})

_WRITER_TOOLS: frozenset[str] = frozenset({
    # File tools
    "read_file",
    "str_replace",
    "append_to_file",
    # Git tools
    "git_commit",
    "get_git_diff",
    "get_git_log",
    "get_git_status",
    "push_branch",
    "clone_repo",
    # Navigation (Writers need to explore the project for context)
    "get_project_directory_structure",
    "get_file_summary",
    "project_grep",
    "project_find",
    # Task reading
    "get_task_info",
    "list_tasks",
    # Communication
    "request_clarification",
    "declare_complete",
    # Note: no code_tools or test_tools — those are coding concerns
})

_CRITIC_TOOLS: frozenset[str] = frozenset({
    # File reading (Critic reads but never writes)
    "read_file",
    # Git (read-only — Critic inspects diffs and logs)
    "get_git_diff",
    "get_git_log",
    "get_git_status",
    # Code tools (read-only — Critic may inspect structure)
    "get_function_def",
    "get_function_list",
    "get_class_summary",
    "get_dependencies",
    "get_call_sites",
    "get_imports",
    # Navigation
    "get_project_directory_structure",
    "get_file_summary",
    "project_grep",
    "project_find",
    # Task reading
    "get_task_info",
    "list_tasks",
    # Critic disposition tools (Critic-exclusive)
    "approve",
    "deny",
    # Note: no declare_complete — Critic uses approve/deny instead
    # Note: no request_clarification — Critic either approves, denies, or
    #       escalates to BLOCKED_BY_HUMAN via turn limit. It does not ask
    #       questions mid-review as that would stall task completion.
})

_MERGE_TOOLS: frozenset[str] = frozenset({
    "show_conflict",
    "resolve_conflict",
})

_ROLE_TOOL_SETS: dict[AgentRole, frozenset[str]] = {
    AgentRole.MANAGER: _MANAGER_TOOLS,
    AgentRole.CODER:   _CODER_TOOLS,
    AgentRole.WRITER:  _WRITER_TOOLS,
    AgentRole.CRITIC:  _CRITIC_TOOLS,
    AgentRole.MERGE:   _MERGE_TOOLS,
}


def tools_for_role(role: AgentRole) -> frozenset[str]:
    """Return the set of tool names permitted for a given agent role.

    Used by AgentLoop to filter tool calls at dispatch time. Any tool
    call whose name is not in this set is intercepted and returns an
    error message to the agent — it does not raise an exception.

    Args:
        role: The role of the currently running agent.

    Returns:
        Tool names the role is permitted to call.  Returns an empty
        frozenset for unknown roles, which will block all tool calls
        and is logged as a warning.
    """
    result = _ROLE_TOOL_SETS.get(role)
    if result is None:
        logger.warning(
            "tools_for_role called with unknown role %r — "
            "returning empty tool set. All tool calls will be blocked.",
            role,
        )
        return frozenset()
    return result


def tools_for_role_list(role: AgentRole) -> list[Tool]:
    """Return the subset of TOOLS permitted for a given role.

    Used when constructing the tools list to pass to the inference
    backend via ``LLMBackend.chat(tools=...)``.  Returns ``Tool``
    descriptors — callers access ``tool.fn`` for dispatch and
    ``tool.schema`` for schema extraction.

    Args:
        role: The role of the currently running agent.

    Returns:
        Tool descriptors the role is permitted to use.
    """
    allowed = tools_for_role(role)
    return [t for t in TOOLS if t.fn.__name__ in allowed]


def tools_for_names(names: set[str]) -> list[Tool]:
    """Return Tool descriptors matching the given name set.

    Args:
        names: Set of tool name strings to look up.

    Returns:
        Tool descriptors whose function names are in ``names``.
        Names not present in the registry are silently skipped.
    """
    return [t for t in TOOLS if t.fn.__name__ in names]
