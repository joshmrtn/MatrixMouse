"""
matrixmouse/tools/task_tools.py

Tools for managing the task lifecycle from within the agent loop.

Tools exposed to agents:
    declare_complete    — signal that the current task is done
    create_task         — create a new top-level task (Manager only)
    split_task          — decompose a task into subtasks (Manager only)
    update_task         — update fields on any task (Manager only)
    get_task_info       — read details of a task
    list_tasks          — list tasks in the queue (filtered view)
    approve             — approve a reviewed task as complete (Critic only)
    deny                — reject a reviewed task with feedback (Critic only)

Note on declare_complete:
    Intercepted by name in loop.py before dispatch reaches the tool
    registry. The implementation here is authoritative for the tool's
    schema (docstring + arguments) but the actual exit behaviour is
    handled in the loop. Do not add loop control logic here.

Note on approve/deny:
    These tools read _active_task_id to find the Critic task, then
    look up reviews_task_id to find the task under review. Both fields
    must be set correctly by the orchestrator before the Critic loop runs.

Note on JSON schemas:
    When we add explicit JSON tool schemas for non-Ollama backends, the
    Args sections of these docstrings are the authoritative source of
    truth for parameter names, types, and descriptions. Keep them accurate.

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
_config: Optional["MatrixMouseConfig"] = None


def configure(
    queue: "TaskQueue",
    active_task_id: Optional[str] = None,
    config: Optional["MatrixMouseConfig"] = None,
) -> None:
    """
    Inject the task queue, active task ID, and config.

    Called by the orchestrator at the start of each task so tools
    can read and mutate the correct task and respect config values
    such as decomposition_depth_limit.

    Args:
        queue:          The workspace-level TaskQueue.
        active_task_id: ID of the task currently being worked on.
        config:         MatrixMouseConfig instance. Used for depth
                        limit enforcement in split_task. If None,
                        split_task falls back to the default value of 3.
    """
    global _queue, _active_task_id, _config
    _queue = queue
    _active_task_id = active_task_id
    _config = config
    logger.debug("task_tools configured. Active task: %s", active_task_id)


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
    Signal that the current task is complete.

    Call this when your assigned work is genuinely finished. Include a
    concise summary of what was accomplished — this is recorded in the
    task history and used to provide context for dependent tasks and
    future Manager reviews.

    The loop intercepts this call and triggers a Critic review before
    the task is marked COMPLETE. Do not call this speculatively.

    Args:
        summary (str): What was accomplished. Be specific: mention files
            changed, decisions made, tests passed, or design choices taken.

    Returns:
        str: Acknowledgement string (intercepted by loop before return).
    """
    # Intercepted by loop.py before this return is reached.
    return f"Task complete: {summary}"


def create_task(
    title: str,
    description: str,
    role: str,
    repo: list[str],
    target_files: Optional[list[str]] = None,
    importance: float = 0.5,
    urgency: float = 0.5,
) -> str:
    """
    Create a new top-level task and add it to the queue.

    Use this to create tasks that address human intent or system needs.
    For decomposing an existing task into subtasks, use split_task instead.

    Role assignment guidance:
        - Use 'coder' for any task that touches source code files.
        - Use 'writer' for documentation, copy, configuration prose, or
          any task whose primary output is non-code text.

    Priority guidance:
        - importance: how much this task matters to the overall goal (0-1).
        - urgency: how time-sensitive this task is (0-1).
        - Both default to 0.5. Reserve values above 0.8 for genuinely
          critical or time-sensitive work.

    Args:
        title (str): Short descriptive title. Should be actionable, e.g.
            'Add input validation to the login endpoint'.
        description (str): Full specification of the work to be done.
            Include: what to build, constraints, definition of done,
            and any relevant context the implementing agent will need.
            The agent will only see this description — be precise.
        role (str): Agent role to assign. One of: 'coder', 'writer'.
        repo (list[str]): List of repository names this task applies to.
            Most tasks have one entry. Use multiple for cross-repo tasks.
        target_files (list[str], optional): Files the agent should focus
            on. Helps scope the task. Defaults to empty (no restriction).
        importance (float, optional): Importance weight 0.0-1.0.
            Defaults to 0.5.
        urgency (float, optional): Urgency weight 0.0-1.0.
            Defaults to 0.5.

    Returns:
        str: Confirmation with the new task ID, or an error message.
    """
    from matrixmouse.task import AgentRole, Task, TaskStatus

    queue = _require_queue()

    if not title.strip():
        return "ERROR: Task title cannot be empty."
    if not description.strip():
        return "ERROR: Task description cannot be empty."
    if not repo:
        return "ERROR: At least one repo must be specified."

    try:
        role_enum = AgentRole(role.lower())
    except ValueError:
        valid = ", ".join(r.value for r in AgentRole
                         if r not in (AgentRole.MANAGER, AgentRole.CRITIC))
        return f"ERROR: Invalid role '{role}'. Valid values for task assignment: {valid}"

    if role_enum in (AgentRole.MANAGER, AgentRole.CRITIC):
        return (
            f"ERROR: Role '{role}' cannot be assigned to a task directly. "
            f"Use 'coder' or 'writer'."
        )

    task = Task(
        title=title,
        description=description,
        role=role_enum,
        repo=repo,
        target_files=target_files or [],
        importance=max(0.0, min(1.0, importance)),
        urgency=max(0.0, min(1.0, urgency)),
        status=TaskStatus.READY,
    )

    queue.add(task)
    logger.info("Task created by Manager: [%s] %s", task.id, task.title)

    return (
        f"OK: Task created.\n"
        f"ID:    {task.id}\n"
        f"Title: {task.title}\n"
        f"Role:  {role_enum.value}\n"
        f"Repo:  {', '.join(repo)}"
    )


def split_task(
    task_id: str,
    subtasks: list[dict],
) -> str:
    """
    Decompose a task into subtasks.

    Use this when a task is too large or broad to be completed safely
    in one pass, and can be cleanly divided into independent units of
    work. Each subtask should target a single function, method, or
    self-contained concern.

    The parent task is automatically set to BLOCKED_BY_TASK until all
    subtasks reach a terminal state.

    Guards:
        - The task must exist and must not be RUNNING. Splitting a
          running task is not permitted — wait for its time slice to
          expire or for it to become BLOCKED before splitting.
        - Each subtask is checked for dependency cycles before any are
          created. If a cycle is detected, no subtasks are created.
        - If the parent task's depth would exceed the decomposition
          depth limit, a confirmation event is emitted instead of
          creating subtasks. Task creation is suspended until the
          human operator confirms.

    Subtask dict fields:
        title (str, required): Short descriptive title.
        description (str, required): Full specification. Include what
            the parent task has already attempted if relevant.
        role (str, required): 'coder' or 'writer'.
        target_files (list[str], optional): Files to focus on.
        importance (float, optional): Defaults to parent's importance.
        urgency (float, optional): Defaults to parent's urgency.

    Args:
        task_id (str): ID of the task to decompose. Can be any non-RUNNING
            task — does not need to be the currently active task.
        subtasks (list[dict]): List of subtask specification dicts.
            Must contain at least one entry.

    Returns:
        str: Confirmation with all created subtask IDs, a
            PENDING_CONFIRMATION sentinel if depth limit applies, or
            an error message if the operation failed.
    """
    # TODO: Handle concurrent write race condition when multi-threading is implemented
    # TODO: Handle transactional (atomic) updates to task graph with thread-safe logic
    from matrixmouse.task import AgentRole, Task, TaskStatus

    queue = _require_queue()

    if not task_id:
        return "ERROR: task_id is required."
    if not subtasks:
        return "ERROR: subtasks list cannot be empty."

    parent = queue.get(task_id)
    if parent is None:
        return f"ERROR: Task '{task_id}' not found."

    if parent.status == TaskStatus.RUNNING:
        return (
            f"ERROR: Task '{task_id}' is currently RUNNING and cannot be split. "
            f"Wait for its time slice to expire or for it to become blocked."
        )

    if parent.status.is_terminal:
        return (
            f"ERROR: Task '{task_id}' is {parent.status.value} and cannot be split."
        )

    # --- Depth limit check ---
    depth_limit = (
        getattr(_config, "decomposition_depth_limit", 3)
        if _config is not None else 3
    )
    # decomposition_confirmed_depth tracks how many confirmation events
    # have been granted on this branch, each granting depth_limit additional levels.
    allowed_depth = depth_limit + (parent.decomposition_confirmed_depth * depth_limit)
    if parent.depth >= allowed_depth:
        import uuid
        confirmation_id = uuid.uuid4().hex[:16]
        logger.info(
            "Depth limit reached for task [%s] at depth %d. "
            "Emitting decomposition_confirmation_required (confirmation_id=%s).",
            task_id, parent.depth, confirmation_id,
        )
        _emit_decomposition_confirmation(
            task_id=task_id,
            depth=parent.depth,
            proposed_subtasks=subtasks,
            confirmation_id=confirmation_id,
        )
        return (
            f"PENDING_CONFIRMATION:{confirmation_id}\n"
            f"Task '{task_id}' is at decomposition depth {parent.depth}, "
            f"which requires human confirmation before splitting further.\n"
            f"A confirmation request has been sent. Resume after the operator "
            f"confirms or denies the split."
        )

    # --- Validate all subtasks before creating any ---
    validated = []
    for i, sub in enumerate(subtasks):
        sub_title = sub.get("title", "").strip()
        sub_desc  = sub.get("description", "").strip()
        sub_role  = sub.get("role", "").strip().lower()

        if not sub_title:
            return f"ERROR: subtask[{i}] title cannot be empty."
        if not sub_desc:
            return f"ERROR: subtask[{i}] description cannot be empty."

        try:
            role_enum = AgentRole(sub_role)
        except ValueError:
            valid = ", ".join(r.value for r in AgentRole
                             if r not in (AgentRole.MANAGER, AgentRole.CRITIC))
            return (
                f"ERROR: subtask[{i}] has invalid role '{sub_role}'. "
                f"Valid values: {valid}"
            )

        if role_enum in (AgentRole.MANAGER, AgentRole.CRITIC):
            return (
                f"ERROR: subtask[{i}] role '{sub_role}' cannot be assigned "
                f"to a task. Use 'coder' or 'writer'."
            )

        validated.append({
            "title":        sub_title,
            "description":  sub_desc,
            "role":         role_enum,
            "target_files": sub.get("target_files", []),
            "importance":   max(0.0, min(1.0, sub.get("importance", parent.importance))),
            "urgency":      max(0.0, min(1.0, sub.get("urgency",    parent.urgency))),
        })

    # --- Create subtasks atomically ---
    # All validation passed. Create them all. If any fails (e.g. a cycle
    # that wasn't caught in pre-validation due to a concurrent write),
    # roll back by marking the parent unblocked if no subtasks were added.
    created_ids = []
    try:
        for sub in validated:
            subtask = queue.add_subtask(
                parent_id=task_id,
                title=sub["title"],
                description=sub["description"],
                role=sub["role"],
                target_files=sub["target_files"],
                importance=sub["importance"],
                urgency=sub["urgency"],
            )
            created_ids.append(subtask.id)
            logger.info(
                "Subtask [%s] '%s' created under [%s].",
                subtask.id, subtask.title, task_id,
            )
    except ValueError as e:
        # Cycle detected mid-creation. The queue rolled back the failing
        # subtask but previously created subtasks in this batch are not
        # automatically rolled back. Log which ones were created.
        if created_ids:
            logger.error(
                "Cycle detected during split_task on task [%s]. "
                "Partially created subtasks: %s. Manual cleanup may be required.",
                task_id, created_ids,
            )
            return (
                f"ERROR: Dependency cycle detected while creating subtask. "
                f"Some subtasks were created before the cycle was detected: "
                f"{created_ids}. Please review the task graph."
            )
        return f"ERROR: Dependency cycle detected: {e}"
    except Exception as e:
        logger.error(
            "Unexpected error during split_task on task [%s]: %s",
            task_id, e,
        )
        return f"ERROR: Failed to create subtasks: {e}"

    lines = [
        f"OK: Task '{task_id}' split into {len(created_ids)} subtask(s).",
        f"Parent task is now BLOCKED_BY_TASK until all subtasks complete.",
        "",
        "Subtasks created:",
    ]
    for sid, sub in zip(created_ids, validated):
        lines.append(f"  [{sid}] ({sub['role'].value}) {sub['title']}")

    return "\n".join(lines)


def update_task(
    task_id: str,
    title: Optional[str] = None,
    description: Optional[str] = None,
    role: Optional[str] = None,
    importance: Optional[float] = None,
    urgency: Optional[float] = None,
    notes: Optional[str] = None,
    add_blocked_by: Optional[list[str]] = None,
    remove_blocked_by: Optional[list[str]] = None,
) -> str:
    """
    Update fields on a task.

    Only the Manager should call this tool. All parameters except
    task_id are optional — only specified fields are updated.

    Dependency updates (add_blocked_by / remove_blocked_by) run a
    cycle detection check after every modification. If a cycle is
    detected, the change is rejected and the task is left unchanged.

    Args:
        task_id (str): ID of the task to update.
        title (str, optional): New title.
        description (str, optional): New description.
        role (str, optional): New role. One of: 'coder', 'writer'.
            Cannot reassign to 'manager' or 'critic'.
        importance (float, optional): New importance weight 0.0-1.0.
        urgency (float, optional): New urgency weight 0.0-1.0.
        notes (str, optional): Append this text to the task's notes
            field. Notes are cumulative — this does not replace
            existing notes, it adds to them.
        add_blocked_by (list[str], optional): Task IDs to add as
            blocking dependencies. Cycle detection runs after adding.
        remove_blocked_by (list[str], optional): Task IDs to remove
            from the blocking dependencies list.

    Returns:
        str: Confirmation of changes made, or an error message.
    """
    from matrixmouse.task import AgentRole, TaskStatus

    queue = _require_queue()

    task = queue.get(task_id)
    if task is None:
        return f"ERROR: Task '{task_id}' not found."

    changes = []

    if title is not None:
        if not title.strip():
            return "ERROR: title cannot be empty."
        task.title = title.strip()
        changes.append("title")

    if description is not None:
        if not description.strip():
            return "ERROR: description cannot be empty."
        task.description = description.strip()
        changes.append("description")

    if role is not None:
        try:
            role_enum = AgentRole(role.lower())
        except ValueError:
            valid = ", ".join(r.value for r in AgentRole
                             if r not in (AgentRole.MANAGER, AgentRole.CRITIC))
            return f"ERROR: Invalid role '{role}'. Valid values: {valid}"
        if role_enum in (AgentRole.MANAGER, AgentRole.CRITIC):
            return (
                f"ERROR: Cannot reassign task to role '{role}'. "
                f"Use 'coder' or 'writer'."
            )
        task.role = role_enum
        changes.append("role")

    if importance is not None:
        task.importance = max(0.0, min(1.0, importance))
        changes.append("importance")

    if urgency is not None:
        task.urgency = max(0.0, min(1.0, urgency))
        changes.append("urgency")

    if notes is not None:
        task.notes = (task.notes + f"\n{notes}").strip() if task.notes else notes
        changes.append("notes")

    # --- Dependency graph updates ---
    if remove_blocked_by:
        for dep_id in remove_blocked_by:
            if dep_id in task.blocked_by:
                task.blocked_by.remove(dep_id)
                # Also remove the reverse reference
                dep_task = queue.get(dep_id)
                if dep_task and task_id in dep_task.blocking:
                    dep_task.blocking.remove(task_id)
                    try:
                        queue.update(dep_task)
                    except Exception as e:
                        logger.warning(
                            "Failed to update reverse blocking ref on [%s]: %s",
                            dep_id, e,
                        )
        changes.append("blocked_by (removed)")

        # If task was BLOCKED_BY_TASK and is now unblocked, set to READY
        if (task.status == TaskStatus.BLOCKED_BY_TASK
                and task.is_ready(queue.completed_ids())):
            task.status = TaskStatus.READY
            changes.append("status → READY")

    if add_blocked_by:
        for dep_id in add_blocked_by:
            dep_task = queue.get(dep_id)
            if dep_task is None:
                return f"ERROR: Cannot add dependency on '{dep_id}' — task not found."
            if dep_id not in task.blocked_by:
                task.blocked_by.append(dep_id)
            # Add reverse reference
            if task_id not in dep_task.blocking:
                dep_task.blocking.append(task_id)
                try:
                    queue.update(dep_task)
                except Exception as e:
                    logger.warning(
                        "Failed to update reverse blocking ref on [%s]: %s",
                        dep_id, e,
                    )

        # Cycle check after adding all new dependencies
        cycle = queue._find_cycle(task_id)
        if cycle:
            # Roll back: remove the deps we just added
            for dep_id in add_blocked_by:
                if dep_id in task.blocked_by:
                    task.blocked_by.remove(dep_id)
                dep_task = queue.get(dep_id)
                if dep_task and task_id in dep_task.blocking:
                    dep_task.blocking.remove(task_id)
                    try:
                        queue.update(dep_task)
                    except Exception:
                        pass
            return (
                f"ERROR: Adding these dependencies would create a cycle: "
                f"{' → '.join(cycle)}. No changes made."
            )

        if task.status == TaskStatus.READY:
            task.status = TaskStatus.BLOCKED_BY_TASK
            changes.append("status → BLOCKED_BY_TASK")
        changes.append("blocked_by (added)")

    if not changes:
        return "No changes specified. Provide at least one field to update."

    try:
        queue.update(task)
    except Exception as e:
        return f"ERROR: Failed to save task: {e}"

    logger.info(
        "Task [%s] updated by Manager. Fields changed: %s",
        task_id, ", ".join(changes),
    )
    return f"OK: Task '{task_id}' updated. Changed: {', '.join(changes)}."


def get_task_info(task_id: Optional[str] = None) -> str:
    """
    Read details of a task.

    Defaults to the current active task if no ID is given. Use this
    to understand what a task requires, check its dependencies, or
    review its current status and history.

    Args:
        task_id (str, optional): Task ID to look up. Defaults to the
            current active task.

    Returns:
        str: Formatted task details, or an error message if not found.
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
        f"Status:   {task.status.value}",
        f"Role:     {task.role.value}",
        f"Repo:     {', '.join(task.repo) if task.repo else '(none)'}",
        f"Branch:   {task.branch or '(none)'}",
        f"Priority: importance={task.importance}, urgency={task.urgency}",
        f"Depth:    {task.depth}",
        f"Created:  {task.created_at}",
    ]

    if task.started_at:
        lines.append(f"Started:  {task.started_at}")
    if task.completed_at:
        lines.append(f"Completed: {task.completed_at}")
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
    if task.parent_task_id:
        lines.append(f"Parent:     {task.parent_task_id}")
    if task.reviews_task_id:
        lines.append(f"Reviews task: {task.reviews_task_id}")

    return "\n".join(lines)


def list_tasks(
    status: Optional[str] = None,
    repo: Optional[str] = None,
    role: Optional[str] = None,
) -> str:
    """
    List tasks in the queue with optional filters.

    Use this to understand what work is pending, what is blocked, and
    what has been completed recently. The Manager uses this during
    planning and review to get an overview of the task graph.

    Args:
        status (str, optional): Filter by status. One of: ready, running,
            blocked_by_task, blocked_by_human, complete, cancelled.
            Defaults to showing all non-terminal tasks.
        repo (str, optional): Filter by repository name.
            Defaults to all repos.
        role (str, optional): Filter by agent role. One of: manager,
            coder, writer, critic.
            Defaults to all roles.

    Returns:
        str: Formatted task list sorted by priority score (highest
            priority first), or a message if no tasks match.
    """
    from matrixmouse.task import AgentRole, TaskStatus

    queue = _require_queue()
    tasks = queue.all_tasks()

    if status:
        try:
            status_filter = TaskStatus(status.lower())
            tasks = [t for t in tasks if t.status == status_filter]
        except ValueError:
            valid = ", ".join(s.value for s in TaskStatus)
            return f"ERROR: Unknown status '{status}'. Valid values: {valid}"
    else:
        tasks = [t for t in tasks if not t.status.is_terminal]

    if repo:
        tasks = [t for t in tasks if repo in t.repo]

    if role:
        try:
            role_filter = AgentRole(role.lower())
            tasks = [t for t in tasks if t.role == role_filter]
        except ValueError:
            valid = ", ".join(r.value for r in AgentRole)
            return f"ERROR: Unknown role '{role}'. Valid values: {valid}"

    if not tasks:
        return "No tasks match the filter."

    lines = []
    for t in sorted(tasks, key=lambda x: x.priority_score()):
        blocked_note = ""
        if t.status.is_blocked:
            blocked_note = f" [blocked: {t.status.value}]"
        lines.append(
            f"[{t.id}] ({t.role.value}) {t.title}{blocked_note}\n"
            f"       status={t.status.value} "
            f"importance={t.importance} urgency={t.urgency} "
            f"score={t.priority_score():.3f}"
        )

    return "\n".join(lines)


def approve() -> str:
    """
    Approve the reviewed task as complete.

    Call this when the task's work meets the definition of done and
    no significant issues were found. This marks both the reviewed
    task and this Critic review task as COMPLETE.

    Only callable by the Critic role. The orchestrator wires the
    reviewed task ID via the reviews_task_id field on the active task.

    Returns:
        str: Confirmation, or an error if the approval could not
            be applied.
    """
    from matrixmouse.task import TaskStatus

    queue = _require_queue()

    if not _active_task_id:
        return "ERROR: No active task. approve() must be called from a Critic task."

    critic_task = queue.get(_active_task_id)
    if critic_task is None:
        return f"ERROR: Active Critic task '{_active_task_id}' not found."

    if not critic_task.reviews_task_id:
        return (
            "ERROR: This task has no reviews_task_id set. "
            "approve() can only be called from a Critic review task."
        )

    reviewed_task = queue.get(critic_task.reviews_task_id)
    if reviewed_task is None:
        return (
            f"ERROR: Reviewed task '{critic_task.reviews_task_id}' not found."
        )

    # Remove the Critic task from the reviewed task's blocked_by
    if _active_task_id in reviewed_task.blocked_by:
        reviewed_task.blocked_by.remove(_active_task_id)

    # Mark reviewed task COMPLETE
    reviewed_task.status = TaskStatus.COMPLETE
    from datetime import datetime, timezone
    reviewed_task.completed_at = datetime.now(timezone.utc).isoformat()
    try:
        queue.update(reviewed_task)
        queue._unblock_dependents(reviewed_task.id)
    except Exception as e:
        return f"ERROR: Failed to mark reviewed task complete: {e}"

    # Mark Critic task COMPLETE — loop will also see COMPLETE exit reason
    # but setting it here ensures consistency if the loop exits via other paths
    try:
        queue.mark_complete(_active_task_id)
    except Exception as e:
        logger.warning("Failed to mark Critic task complete: %s", e)

    logger.info(
        "Critic [%s] approved task [%s].",
        _active_task_id, reviewed_task.id,
    )
    return (
        f"OK: Task '{reviewed_task.id}' approved and marked COMPLETE.\n"
        f"Critic review task '{_active_task_id}' is also complete."
    )


def deny(feedback: str) -> str:
    """
    Reject the reviewed task and send it back for rework.

    Call this when the task's work does not meet the definition of done,
    contains errors, or has scope violations that must be addressed.
    The feedback is appended to the reviewed task's conversation history
    so the implementing agent understands what needs to change.

    Be specific in feedback: name the files, functions, or behaviours
    that are problematic and explain what the correct outcome should be.
    Vague feedback wastes turns.

    Only callable by the Critic role.

    Args:
        feedback (str): Required. Specific, actionable description of
            what is wrong and what must change before the task can be
            approved. Must not be empty.

    Returns:
        str: Confirmation, or an error message.
    """
    from matrixmouse.task import TaskStatus

    queue = _require_queue()

    if not feedback or not feedback.strip():
        return "ERROR: feedback cannot be empty. Provide specific, actionable feedback."

    if not _active_task_id:
        return "ERROR: No active task. deny() must be called from a Critic task."

    critic_task = queue.get(_active_task_id)
    if critic_task is None:
        return f"ERROR: Active Critic task '{_active_task_id}' not found."

    if not critic_task.reviews_task_id:
        return (
            "ERROR: This task has no reviews_task_id set. "
            "deny() can only be called from a Critic review task."
        )

    reviewed_task = queue.get(critic_task.reviews_task_id)
    if reviewed_task is None:
        return f"ERROR: Reviewed task '{critic_task.reviews_task_id}' not found."

    # Append feedback to reviewed task's context as a system message
    reviewed_task.context_messages.append({
        "role": "user",
        "content": (
            f"[Critic review feedback — address this before declaring complete]\n"
            f"{feedback.strip()}"
        ),
    })

    # Remove Critic task from reviewed task's blocked_by and set back to READY
    if _active_task_id in reviewed_task.blocked_by:
        reviewed_task.blocked_by.remove(_active_task_id)

    reviewed_task.status = TaskStatus.READY
    try:
        queue.update(reviewed_task)
    except Exception as e:
        return f"ERROR: Failed to return reviewed task to READY: {e}"

    # Mark Critic task COMPLETE
    try:
        queue.mark_complete(_active_task_id)
    except Exception as e:
        logger.warning("Failed to mark Critic task complete: %s", e)

    logger.info(
        "Critic [%s] denied task [%s]. Feedback: %s",
        _active_task_id, reviewed_task.id, feedback[:80],
    )
    return (
        f"OK: Task '{reviewed_task.id}' returned to READY with feedback.\n"
        f"Critic review task '{_active_task_id}' is complete.\n"
        f"The implementing agent will see your feedback on next execution."
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _emit_decomposition_confirmation(
    task_id: str,
    depth: int,
    proposed_subtasks: list[dict],
    confirmation_id: str,
) -> None:
    """
    Emit a decomposition_confirmation_required WebSocket event.

    Called by split_task when depth limit is reached. The UI renders
    a confirmation modal for the human operator. The agent receives a
    PENDING_CONFIRMATION sentinel and waits for the operator response
    to be injected into its context.

    Args:
        task_id (str): ID of the task being split.
        depth (int): Current depth of the task in the decomposition tree.
        proposed_subtasks (list[dict]): The subtask specs the Manager
            proposed, shown in the confirmation modal.
        confirmation_id (str): Unique ID for this confirmation request,
            used to match the response back to the pending split.
    """
    try:
        from matrixmouse.comms import get_manager
        m = get_manager()
        if m:
            m.emit("decomposition_confirmation_required", {
                "task_id":           task_id,
                "depth":             depth,
                "proposed_subtasks": proposed_subtasks,
                "confirmation_id":   confirmation_id,
            })
    except Exception as e:
        logger.warning(
            "Failed to emit decomposition_confirmation_required: %s", e
        )