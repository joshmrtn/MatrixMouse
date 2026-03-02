"""
matrixmouse/tools/task_tools.py

Tools for managing the task lifecycle from within the agent loop.

Replaces system_tools.py — declare_complete is a task lifecycle
concern and belongs here alongside the other task management tools.

Tools exposed:
    declare_complete    — signal that the current task phase is done
    add_subtask         — decompose the current task into a subtask
    get_task_info       — read details of the current task
    list_tasks          — list tasks in the queue (filtered view)

Note on declare_complete:
    This tool is intercepted by name in loop.py before dispatch reaches
    the tool registry. The implementation here is authoritative for the
    tool's schema (docstring + arguments), but the actual exit behaviour
    is handled in the loop. Do not add loop control logic here.

Do not add file, git, or navigation tools here.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Module-level state — set by configure()
# ---------------------------------------------------------------------------

_queue: Optional["TaskQueue"] = None
_active_task_id: Optional[str] = None


def configure(queue: "TaskQueue", active_task_id: Optional[str] = None) -> None:
    """
    Inject the task queue and active task ID.

    Called by the orchestrator at the start of each task so tools
    can read and mutate the correct task.

    Args:
        queue:          The workspace-level TaskQueue.
        active_task_id: ID of the task currently being worked on.
    """
    global _queue, _active_task_id
    _queue = queue
    _active_task_id = active_task_id
    logger.debug(
        "task_tools configured. Active task: %s", active_task_id
    )


def _require_queue() -> "TaskQueue":
    if _queue is None:
        raise RuntimeError(
            "task_tools not configured. "
            "Call task_tools.configure(queue, task_id) at task start."
        )
    return _queue


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

def declare_complete(summary: str) -> str:
    """
    Signal that the current phase of the task is complete.

    Call this when your assigned role for this phase is finished.
    Include a concise summary of what was accomplished — this is
    recorded in the task history and used to brief the next phase.

    The loop will intercept this call and advance to the next phase.
    Do not call this speculatively — only call it when the work is
    genuinely done.

    Args:
        summary: What was accomplished in this phase. Be specific:
                 mention files changed, decisions made, or tests passed.

    Returns:
        Acknowledgement string (intercepted by loop before return).
    """
    # Intercepted by loop.py before this return is reached.
    # The return value is never seen by the agent.
    return f"Phase complete: {summary}"


def add_subtask(
    title: str,
    description: str,
    target_files: Optional[list] = None,
    importance: float = 0.5,
    urgency: float = 0.5,
    repo: Optional[list] = None,
) -> str:
    """
    Decompose the current task by creating a subtask.

    Use this during DESIGN or IMPLEMENT phases when a task is too large
    to complete safely in one pass. The current task will be blocked
    until the subtask is complete.

    Guidelines for when to create subtasks:
        - The work would modify or create an entire file
        - More than ~200 lines of code need to change
        - The change introduces new execution paths in a module
        - Multiple independent concerns can be cleanly separated

    The subtask inherits the current task's repo by default.
    The current task is automatically set to BLOCKED_BY_TASK.
    A dependency cycle check runs immediately — you will be told if
    the subtask would create a cycle.

    Args:
        title:        Short descriptive title for the subtask.
        description:  Full specification. Be precise: include function
                      signatures, expected behaviour, and constraints.
                      The implementer agent will only see this description.
        target_files: Files the subtask should focus on.
        importance:   Priority importance 0.0-1.0. Defaults to parent's value.
        urgency:      Priority urgency 0.0-1.0. Defaults to parent's value.
        repo:         Override repo list. Defaults to parent task's repo.

    Returns:
        Confirmation with the new subtask ID, or an error if a cycle
        was detected.
    """
    queue = _require_queue()

    if not _active_task_id:
        return "ERROR: No active task. Cannot create subtask outside of an active task."

    if not title.strip():
        return "ERROR: Subtask title cannot be empty."

    if not description.strip():
        return "ERROR: Subtask description cannot be empty."

    try:
        subtask = queue.add_subtask(
            parent_id=_active_task_id,
            title=title,
            description=description,
            repo=repo,
            target_files=target_files or [],
            importance=importance,
            urgency=urgency,
        )
        logger.info(
            "Subtask %s created under %s: %s",
            subtask.id, _active_task_id, title,
        )
        return (
            f"OK: Subtask '{subtask.id}' created: '{title}'.\n"
            f"The current task is now blocked until this subtask is complete.\n"
            f"Subtask ID: {subtask.id}"
        )
    except ValueError as e:
        # Cycle detected — queue rolled back the change
        return f"ERROR: {e}"
    except Exception as e:
        return f"ERROR: Failed to create subtask: {e}"


def get_task_info(task_id: Optional[str] = None) -> str:
    """
    Read details of a task.

    Defaults to the current active task if no ID is given.
    Use this to understand what the task requires, check its
    dependencies, or see its current status.

    Args:
        task_id: Task ID to look up. Defaults to current active task.

    Returns:
        Formatted task details, or an error if not found.
    """
    queue = _require_queue()

    tid = task_id or _active_task_id
    if not tid:
        return "ERROR: No active task and no task_id provided."

    task = queue.get(tid)
    if task is None:
        return f"ERROR: Task '{tid}' not found."

    lines = [
        f"Task {task.id}: {task.title}",
        f"Status:      {task.status.value}",
        f"Phase:       {task.phase.name if task.phase else 'unknown'}",
        f"Repo:        {', '.join(task.repo) if task.repo else '(none)'}",
        f"Priority:    importance={task.importance}, urgency={task.urgency}",
        f"Created:     {task.created_at}",
    ]

    if task.target_files:
        lines.append(f"Target files: {', '.join(task.target_files)}")

    if task.description:
        lines.append(f"\nDescription:\n{task.description}")

    if task.notes:
        lines.append(f"\nNotes:\n{task.notes}")

    if task.blocked_by:
        lines.append(f"\nBlocked by: {', '.join(task.blocked_by)}")

    if task.subtasks:
        lines.append(f"Subtasks:   {', '.join(task.subtasks)}")

    if task.parent_task:
        lines.append(f"Parent:     {task.parent_task}")

    return "\n".join(lines)


def list_tasks(
    status: Optional[str] = None,
    repo: Optional[str] = None,
) -> str:
    """
    List tasks in the queue.

    Use this to understand what work is pending, what is blocked,
    and what has been completed recently.

    Args:
        status: Filter by status. One of: pending, active, blocked_by_task,
                blocked_by_human, complete, cancelled.
                Defaults to showing all non-terminal tasks.
        repo:   Filter by repo name. Defaults to all repos.

    Returns:
        Formatted task list, or a message if no tasks match.
    """
    from matrixmouse.orchestrator import TaskStatus

    queue = _require_queue()
    tasks = queue.all_tasks()

    # Filter by status
    if status:
        try:
            status_filter = TaskStatus(status.lower())
            tasks = [t for t in tasks if t.status == status_filter]
        except ValueError:
            valid = ", ".join(s.value for s in TaskStatus)
            return f"ERROR: Unknown status '{status}'. Valid values: {valid}"
    else:
        # Default: non-terminal only
        tasks = [t for t in tasks if not t.status.is_terminal]

    # Filter by repo
    if repo:
        tasks = [t for t in tasks if repo in t.repo]

    if not tasks:
        return "No tasks match the filter."

    lines = []
    for t in sorted(tasks, key=lambda x: x.priority_score(), reverse=True):
        blocked_note = ""
        if t.status.is_blocked:
            blocked_note = f" [blocked: {t.status.value}]"
        lines.append(
            f"[{t.id}] {t.title}{blocked_note}\n"
            f"       status={t.status.value} "
            f"importance={t.importance} urgency={t.urgency} "
            f"score={t.priority_score():.3f}"
        )

    return "\n".join(lines)
