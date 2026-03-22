"""
matrixmouse/tools/__init__.py

Aggregates all agent tools into a single importable package.
Exposes:
    TOOLS           — full list of all tool functions (for Ollama schema generation)
    TOOL_REGISTRY   — dict mapping tool name → function (for loop dispatch)
    tools_for_role  — returns a frozenset of tool names permitted for a given role

To add a new tool:
    1. Define it in the appropriate submodule with type hints and a docstring.
    2. Import it here and add it to the TOOLS list.
    3. TOOL_REGISTRY is built automatically from TOOLS — no separate update needed.
    4. Add the tool name to the appropriate role set(s) in _ROLE_TOOL_SETS.

Role-based tool scoping:
    Each AgentRole has an explicit allowlist of tool names. The loop enforces
    this at dispatch time — disallowed tool calls return an error message to
    the agent rather than raising an exception.

    When explicit JSON schemas are added for non-Ollama backends, TOOLS and
    TOOL_REGISTRY remain the source of truth. The schema layer will be built
    on top of this structure.

Submodules:
    file_tools       — read, write, str_replace, append
    git_tools        — branch, commit, diff, log, push, PR
    navigation_tools — directory structure, grep, find
    code_tools       — AST-based function and class inspection
    test_tools       — run pytest, parse results
    task_tools       — task lifecycle, Critic approve/deny, Manager task management
    comms_tools      — request_clarification
    _safety.py       — path validation (internal, not a tool module)
"""
import logging
logger = logging.getLogger(__name__)

from matrixmouse.tools.file_tools import read_file, str_replace, append_to_file
from matrixmouse.tools.task_tools import (
    declare_complete,
    create_task,
    split_task,
    update_task,
    get_task_info,
    list_tasks,
    approve,
    deny,
)
from matrixmouse.tools.git_tools import (
    git_commit,
    get_git_diff,
    get_git_log,
    get_git_status,
    push_branch,
    clone_repo,
)
from matrixmouse.tools.code_tools import (
    get_function_def,
    get_function_list,
    get_class_summary,
    get_dependencies,
    get_call_sites,
    get_imports,
)
from matrixmouse.tools.navigation_tools import (
    get_project_directory_structure,
    get_file_summary,
    project_grep,
    project_find,
)
from matrixmouse.tools.test_tools import run_tests, run_single_test
from matrixmouse.tools.comms_tools import request_clarification


# ---------------------------------------------------------------------------
# Full tool list — used by Ollama for schema generation
# ---------------------------------------------------------------------------

TOOLS = [
    # file_tools
    read_file,
    str_replace,
    append_to_file,
    # task_tools
    declare_complete,
    create_task,
    split_task,
    update_task,
    get_task_info,
    list_tasks,
    approve,
    deny,
    # git_tools
    git_commit,
    get_git_diff,
    get_git_log,
    get_git_status,
    push_branch,
    clone_repo,
    # code_tools
    get_function_def,
    get_function_list,
    get_class_summary,
    get_dependencies,
    get_call_sites,
    get_imports,
    # navigation_tools
    get_project_directory_structure,
    get_file_summary,
    project_grep,
    project_find,
    # test_tools
    run_tests,
    run_single_test,
    # comms_tools
    request_clarification,
]

# Built automatically from TOOLS — never update this manually
TOOL_REGISTRY: dict[str, callable] = {fn.__name__: fn for fn in TOOLS}


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

_ROLE_TOOL_SETS: dict = {}  # populated after imports resolve


def _build_role_tool_sets() -> None:
    """
    Build the role → frozenset mapping after all imports are resolved.
    Called once at module load time.
    """
    from matrixmouse.task import AgentRole
    global _ROLE_TOOL_SETS
    _ROLE_TOOL_SETS = {
        AgentRole.MANAGER: _MANAGER_TOOLS,
        AgentRole.CODER:   _CODER_TOOLS,
        AgentRole.WRITER:  _WRITER_TOOLS,
        AgentRole.CRITIC:  _CRITIC_TOOLS,
    }


_build_role_tool_sets()


def tools_for_role(role: "AgentRole") -> frozenset[str]:
    """
    Return the set of tool names permitted for a given agent role.

    Used by AgentLoop to filter tool calls at dispatch time. Any tool
    call whose name is not in this set is intercepted and returns an
    error message to the agent — it does not raise an exception.

    Args:
        role (AgentRole): The role of the currently running agent.

    Returns:
        frozenset[str]: Tool names the role is permitted to call.
            Returns an empty frozenset for unknown roles, which will
            block all tool calls and is logged as a warning.
    """
    from matrixmouse.task import AgentRole
    result = _ROLE_TOOL_SETS.get(role)
    if result is None:
        logger.warning(
            "tools_for_role called with unknown role %r — "
            "returning empty tool set. All tool calls will be blocked.",
            role,
        )
        return frozenset()
    return result


def tools_for_role_list(role: "AgentRole") -> list:
    """
    Return the subset of TOOLS permitted for a given role.

    Used when constructing the tools list to pass to the inference
    backend (e.g. ollama.chat(tools=...)). Returns actual function
    objects, not names.

    Args:
        role (AgentRole): The role of the currently running agent.

    Returns:
        list: Tool functions the role is permitted to use.
    """
    allowed = tools_for_role(role)
    return [fn for fn in TOOLS if fn.__name__ in allowed]