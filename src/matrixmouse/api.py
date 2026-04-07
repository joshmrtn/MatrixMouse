"""
matrixmouse/api.py

The MatrixMouse REST API.

This module owns the FastAPI application instance and all REST endpoints.
It is the single interface for all reads and writes — CLI commands, the
web UI, and any future integrations all go through here.

The websocket event stream lives in server.py, which imports the app
instance from this module and registers the /ws route.

Endpoints:
    Tasks:   GET/POST /tasks, GET/PATCH/DELETE /tasks/{id}
    Repos:   GET/POST /repos, DELETE /repos/{name}
    Agent:   GET /status, GET /pending, POST /interject
    Control: POST /stop, POST /kill, GET /estop, POST /estop/reset
             POST /orchestrator/pause, POST /orchestrator/resume
    Context: GET /context
    Config:  GET/PATCH /config, GET/PATCH /config/repos/{name}
    System:  GET /health, POST /upgrade, WS /ws (registered by server.py)

Config layer reference:
    Layer 1  /etc/matrixmouse/config.toml                       global
    Layer 2  <workspace>/.matrixmouse/config.toml               workspace-wide
    Layer 3  <workspace>/.matrixmouse/<repo>/config.toml        repo-local, untracked
    Layer 4  <workspace>/<repo>/.matrixmouse/config.toml        repo-local, tracked

    PATCH /config                           → layer 2
    PATCH /config/repos/{name}              → layer 3 (default, untracked)
    PATCH /config/repos/{name}?commit=true  → layer 4 (tracked, in git tree)

    GET /config/repos/{name} returns the merged view of layers 3 + 4,
    with layer 3 values annotated as local and layer 4 as committed.

Control endpoints:
    POST /stop          Soft stop — sets a flag the orchestrator checks at
                        the next loop boundary. Current tool call completes
                        first to avoid leaving filesystem in inconsistent state.
                        Flag is cleared automatically when the next task starts.

    POST /kill          E-STOP — writes ESTOP lockfile then sends SIGTERM.
                        systemd will NOT restart because the process exits
                        with code 0 (Restart=on-failure in the unit file).
                        Requires human intervention to reset via POST /estop/reset
                        or CLI `matrixmouse estop reset`.

    GET  /estop         Returns current ESTOP state.
    POST /estop/reset   Removes the ESTOP lockfile. Service must be manually
                        restarted after reset: `sudo systemctl start matrixmouse`.

Threading model:
    The API server runs in a background thread (uvicorn).
    The orchestrator runs in the main thread.
    _task_condition bridges them — the API notifies it when a new task
    is created so the orchestrator wakes immediately rather than polling.
    _stop_requested is a threading.Event checked by the orchestrator at
    each loop boundary.

Do not add agent logic, inference calls, or tool dispatch here.
"""

import logging
import os
import signal
import subprocess
import threading
import tomllib
import tomli_w
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from matrixmouse.repository.task_repository import TaskRepository
from matrixmouse.repository.workspace_state_repository import WorkspaceStateRepository
from matrixmouse.task import Task

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# FastAPI app — imported by server.py to register the websocket route
# ---------------------------------------------------------------------------

app = FastAPI(title="MatrixMouse", docs_url=None, redoc_url=None)

# ---------------------------------------------------------------------------
# Condition variable — notified when a new task is created.
# Orchestrator waits on this when the queue is empty.
# ---------------------------------------------------------------------------

_task_condition = threading.Condition()


def notify_task_available() -> None:
    """Signal the orchestrator that a new task is available."""
    with _task_condition:
        _task_condition.notify_all()


def get_task_condition() -> threading.Condition:
    """Return the condition variable for the orchestrator to wait on.

    Returns:
        The `threading.Condition` shared between API and orchestrator.
    """
    return _task_condition


# ---------------------------------------------------------------------------
# Soft stop flag — checked by orchestrator at each loop boundary.
# Set by POST /stop. Cleared by the orchestrator when next task starts.
# ---------------------------------------------------------------------------

_stop_requested = threading.Event()


def is_stop_requested() -> bool:
    """Return True if a soft stop has been requested.

    Returns:
        Boolean stop flag state.
    """
    return _stop_requested.is_set()


def clear_stop_requested() -> None:
    """Clear the stop flag.

    Called by the orchestrator when starting a new task to reset the stop
    signal from a previous task run.
    """
    _stop_requested.clear()


# ---------------------------------------------------------------------------
# Module-level state — injected at startup by the orchestrator
# ---------------------------------------------------------------------------

_queue: TaskRepository       # TaskRepository
_scheduler: Any = None       # Scheduler
_status: dict = {}           # live agent status dict (mutated by orchestrator)
_workspace_root: Path | None = None
_config: Any = None          # MatrixMouseConfig
_ws_state_repo: WorkspaceStateRepository | None = None
_budget_tracker: Any = None  # TokenBudgetTracker


def configure(
    queue: Any,
    scheduler: Any,
    status: dict,
    workspace_root: Path,
    config: Any,
    ws_state_repo: WorkspaceStateRepository,
    budget_tracker: Any | None = None,
) -> None:
    """Inject runtime state into the API module.

    Called once at startup before uvicorn starts.

    Args:
        queue: `TaskRepository` for task persistence.
        scheduler: `Scheduler` instance for priority reporting.
        status: Shared agent status dict (mutated by orchestrator).
        workspace_root: Base path for the MatrixMouse workspace.
        config: `MatrixMouseConfig` instance.
        ws_state_repo: `WorkspaceStateRepository` for cross-repo state.
        budget_tracker: `TokenBudgetTracker` for usage reporting.
    """
    global _queue, _scheduler, _status, _workspace_root, _config, _ws_state_repo, _budget_tracker
    _queue = queue
    _scheduler = scheduler
    _status = status
    _workspace_root = workspace_root
    _config = config
    _ws_state_repo = ws_state_repo
    _budget_tracker = budget_tracker
    logger.info("API module configured. Workspace: %s", workspace_root)


def _require_queue() -> TaskRepository:
    """Return the task repository or raise 503 if not configured.

    Returns:
        The active `TaskRepository`.

    Raises:
        HTTPException: 503 if the repository is not ready.
    """
    if _queue is None:
        raise HTTPException(status_code=503, detail="Agent not ready.")
    return _queue


def _require_workspace() -> Path:
    """Return the workspace root path or raise 503 if not configured.

    Returns:
        The workspace root `Path`.

    Raises:
        HTTPException: 503 if the workspace is not configured.
    """
    if _workspace_root is None:
        raise HTTPException(status_code=503, detail="Workspace not configured.")
    return _workspace_root


def _estop_path() -> Path | None:
    """Return the ESTOP lockfile path, or None if workspace is not configured."""
    if _workspace_root is None:
        return None
    return _workspace_root / ".matrixmouse" / "ESTOP"


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class TaskCreateRequest(BaseModel):
    """Payload for creating a new task."""
    title: str
    """The title of the task."""
    description: str = ""
    """Detailed description of the task."""
    repo: list[str] = []
    """List of repository names this task relates to."""
    role: str = "coder"
    """The agent role responsible for this task (e.g., 'coder', 'writer')."""
    target_files: list[str] = []
    """List of specific files the task should focus on."""
    importance: float = 0.5
    """Importance score of the task (0.0-1.0, lower is more important)."""
    urgency: float = 0.5
    """Urgency score of the task (0.0-1.0, lower is more urgent)."""

class TaskEditRequest(BaseModel):
    """Payload for patching an existing task."""
    title: str | None = None
    """The new title for the task."""
    description: str | None = None
    """The new detailed description for the task."""
    repo: list[str] | None = None
    """The new list of repository names this task relates to."""
    target_files: list[str] | None = None
    """The new list of specific files the task should focus on."""
    importance: float | None = None
    """The new importance score for the task."""
    urgency: float | None = None
    """The new urgency score for the task."""
    notes: str | None = None
    """Additional notes for the task."""

class InterjectionRequest(BaseModel):
    """Payload for a deprecated interjection (scoped to repo or workspace)."""
    message: str
    """The interjection message."""
    repo: str | None = None
    """Optional repository name to scope the interjection."""

class RepoAddRequest(BaseModel):
    """Payload for cloning/registering a new repository."""
    remote: str
    """The remote URL or path of the repository to clone."""
    name: str | None = None
    """Optional name for the repository. If omitted, it's inferred from the remote."""

class ConfigPatchRequest(BaseModel):
    """Payload for updating configuration keys."""
    values: dict[str, Any]
    """A dictionary where keys are configuration field names and values are their new settings."""

class TurnLimitResponseRequest(BaseModel):
    """Payload for responding to a turn-limit block."""
    action: str          # "extend" | "respec" | "cancel"
    """The action to take (extend turns, respec task, or cancel)."""
    note: str = ""       # required for respec, optional for extend/cancel
    """An optional note providing context or instructions."""
    extend_by: int = 0   # only used when action="extend", 0 means use config default
    """Number of additional turns to grant if action is 'extend'."""

class WorkspaceInterjectionRequest(BaseModel):
    """Payload for sending a message to the Manager at workspace level."""
    message: str
    """The interjection message."""

class RepoInterjectionRequest(BaseModel):
    """Payload for sending a message to the Manager scoped to a repo."""
    message: str
    """The interjection message."""

class TaskInterjectionRequest(BaseModel):
    """Payload for sending a message to a specific running task's agent."""
    message: str
    """The interjection message."""

class TaskAnswerRequest(BaseModel):
    """Payload for answering a clarification question."""
    message: str
    """The answer message."""

class CriticReviewResponseRequest(BaseModel):
    """Payload for human response to a Critic review task."""
    action: str          # "approve_task" | "extend_critic" | "block_task"
    """The action to take (approve_task, extend_critic, or block_task)."""
    feedback: str = ""   # optional feedback appended to reviewed task context
    """Optional feedback to provide."""
 
class DecisionRequest(BaseModel):
    """Payload for responding to any structured decision event."""
    decision_type: str   # maps to the emitted event name, e.g. "pr_approval_required"
    """The type of decision being responded to."""
    choice: str          # one of the offered choice values, e.g. "approve"
    """The chosen option from the decision, e.g. 'approve'"""
    note: str = ""       # optional free-form human text
    """Optional free-form text for additional context."""
    metadata: dict = {}  # decision-type-specific structured data
    """Metadata specific to the decision type."""
 
# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    """Liveness check.

    Returns:
        Dict with "ok" status and current UTC timestamp.
    """
    return {"ok": True, "timestamp": datetime.now(timezone.utc).isoformat()}


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------

@app.get("/tasks")
async def list_tasks(
    status: str | None = None,
    repo: str | None = None,
    all: bool = False,
):
    """List tasks with optional filtering.

    Args:
        status: Filter by task status (pending, ready, running, etc.).
        repo: Filter by repository name.
        all: If True, include terminal tasks (complete, cancelled).

    Returns:
        Dict containing the list of tasks and the total count.
    """
    queue = _require_queue()
    tasks = queue.all_tasks()

    terminal = {"complete", "cancelled"}

    if not all and not status:
        tasks = [t for t in tasks if t.status.value not in terminal]

    if status:
        tasks = [t for t in tasks if t.status.value == status]

    if repo:
        tasks = [t for t in tasks if repo in t.repo]

    tasks.sort(key=lambda t: t.priority_score())  # ascending: lower score = higher priority

    return {
        "tasks": [t.to_dict() for t in tasks],
        "count": len(tasks),
    }


@app.get("/tasks/{task_id}")
async def get_task(task_id: str):
    """Get full details of a single task.

    Supports prefix matching: if `task_id` is a unique prefix of exactly
    one task ID, that task is returned.

    Args:
        task_id: Full task ID or unique prefix.

    Returns:
        The task details as a dictionary.

    Raises:
        HTTPException: 400 if prefix is ambiguous, 404 if not found.
    """
    queue = _require_queue()

    task = queue.get(task_id)
    if task is None:
        matches = [t for t in queue.all_tasks() if t.id.startswith(task_id)]
        if len(matches) == 1:
            task = matches[0]
        elif len(matches) > 1:
            raise HTTPException(
                status_code=400,
                detail=f"Ambiguous ID prefix '{task_id}' matches: "
                       f"{[t.id for t in matches]}"
            )

    if task is None:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found.")

    return task.to_dict()


@app.post("/tasks", status_code=201)
async def create_task(body: TaskCreateRequest):
    """Create a new task and add it to the queue.

    Notifies the orchestrator immediately via the condition variable.

    Args:
        body: `TaskCreateRequest` payload.

    Returns:
        The created task details.

    Raises:
        HTTPException: 400 if title is empty or role is invalid.
    """
    from matrixmouse.task import Task, TaskStatus, AgentRole

    queue = _require_queue()

    if not body.title.strip():
        raise HTTPException(status_code=400, detail="Title cannot be empty.")

    importance = max(0.0, min(1.0, body.importance))
    urgency    = max(0.0, min(1.0, body.urgency))

    try:
        role_enum = AgentRole(body.role.lower())
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid role '{body.role}'. Valid: coder, writer."
        )
    if role_enum in (AgentRole.MANAGER, AgentRole.CRITIC):
        raise HTTPException(
            status_code=400,
            detail="Tasks cannot be assigned manager or critic role via the API."
        )

    task = Task(
        title=body.title.strip(),
        description=body.description.strip(),
        repo=body.repo,
        role=role_enum,
        status=TaskStatus.READY,
        target_files=body.target_files,
        importance=importance,
        urgency=urgency,
    )
    queue.add(task)
    notify_task_available()

    logger.info("Task created via API: [%s] %s", task.id, task.title)
    return task.to_dict()


@app.patch("/tasks/{task_id}")
async def edit_task(task_id: str, body: TaskEditRequest):
    """Edit mutable fields of an existing task.

    Args:
        task_id: ID of the task to edit.
        body: `TaskEditRequest` payload.

    Returns:
        The updated task details.

    Raises:
        HTTPException: 404 if not found, 400 if task is terminal or field is not editable.
    """
    queue = _require_queue()
    task = queue.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found.")

    if task.status.is_terminal:
        raise HTTPException(
            status_code=400,
            detail=f"Task '{task_id}' is {task.status.value} and cannot be edited."
        )

    editable = {
        "title", "description", "repo", "target_files",
        "importance", "urgency", "notes",
    }
    updates = body.model_dump(exclude_none=True)

    for field, value in updates.items():
        if field not in editable:
            raise HTTPException(
                status_code=400,
                detail=f"Field '{field}' is not editable via the API."
            )
        if field in ("importance", "urgency"):
            value = max(0.0, min(1.0, float(value)))
        setattr(task, field, value)

    queue.update(task)
    return task.to_dict()


@app.delete("/tasks/{task_id}")
async def cancel_task(task_id: str):
    """Cancel a task.

    Args:
        task_id: ID of the task to cancel.

    Returns:
        Confirmation dict with "ok" status.

    Raises:
        HTTPException: 404 if not found.
    """
    queue = _require_queue()
    task = queue.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found.")

    if task.status.is_terminal:
        return {"ok": True, "message": f"Task already {task.status.value}."}

    queue.mark_cancelled(task.id)

    logger.info("Task cancelled via API: [%s] %s", task.id, task.title)
    return {"ok": True, "id": task_id}


# ---------------------------------------------------------------------------
# Repos
# ---------------------------------------------------------------------------

@app.get("/repos")
async def list_repos():
    """List registered repositories.

    Returns:
        Dict containing the list of registered repositories.
    """
    workspace = _require_workspace()
    repos_file = workspace / ".matrixmouse" / "repos.json"

    if not repos_file.exists():
        return {"repos": []}

    import json
    with open(repos_file) as f:
        repos = json.load(f)
    return {"repos": repos}


@app.post("/repos", status_code=201)
async def add_repo(body: RepoAddRequest):
    """Clone or register a repository into the workspace.

    Runs synchronously — blocks until the clone completes.
    Automatically initialises the repository's workspace state.

    Args:
        body: `RepoAddRequest` payload.

    Returns:
        Confirmation dict with repository details.

    Raises:
        HTTPException: 400 if remote is empty, 409 if directory exists, 500 if clone fails.
    """
    import json
    from matrixmouse.init import setup_repo

    workspace = _require_workspace()
    remote = body.remote.strip()

    if not remote:
        raise HTTPException(status_code=400, detail="Remote URL or path is required.")

    name = body.name or _infer_repo_name(remote)
    if not name:
        raise HTTPException(
            status_code=400,
            detail="Could not infer repo name. Pass 'name' explicitly."
        )

    if ".." in name or "/" in name:
        raise HTTPException(
            status_code=400,
            detail="Repo name must not contain '..' or '/'."
        )

    dest = workspace / name
    env = _git_env()

    if dest.exists():
        raise HTTPException(
            status_code=409,
            detail=f"Directory '{dest}' already exists. "
                   f"Remove it first or choose a different name."
        )

    src = remote
    # If it looks like an absolute path, use file:// so git treats it as local
    if remote.startswith("/"):
        src = f"file://{remote}"

    result = subprocess.run(
        ["git", "clone", src, str(dest)],
        env=env, capture_output=True, text=True,
    )

    if result.returncode != 0:
        raise HTTPException(
            status_code=500,
            detail=f"git clone failed: {result.stderr.strip()}"
        )

    try:
        setup_repo(dest, workspace, config=_config)
        logger.info("Repo initialised at %s", dest)
    except Exception as e:
        logger.warning("setup_repo failed for %s: %s", dest, e)

    repos_file = workspace / ".matrixmouse" / "repos.json"
    repos = []
    if repos_file.exists():
        import json as _json
        with open(repos_file) as f:
            repos = _json.load(f)

    entry = {
        "name": name,
        "remote": remote,
        "local_path": str(dest),
        "added": datetime.now(timezone.utc).date().isoformat(),
    }
    repos.append(entry)
    with open(repos_file, "w") as f:
        import json as _json
        _json.dump(repos, f, indent=2)

    logger.info("Repo registered: %s -> %s", name, dest)
    return {"ok": True, "repo": entry}


@app.delete("/repos/{name}")
async def remove_repo(name: str):
    """Remove a repository from the registry.

    Does NOT delete the cloned directory — that requires manual action.

    Args:
        name: Name of the repository to remove.

    Returns:
        Confirmation dict with "ok" status.

    Raises:
        HTTPException: 404 if repository not found.
    """
    import json

    workspace = _require_workspace()
    repos_file = workspace / ".matrixmouse" / "repos.json"

    if not repos_file.exists():
        raise HTTPException(status_code=404, detail=f"Repo '{name}' not found.")

    with open(repos_file) as f:
        repos = json.load(f)

    original_count = len(repos)
    repos = [r for r in repos if r.get("name") != name]

    if len(repos) == original_count:
        raise HTTPException(status_code=404, detail=f"Repo '{name}' not found.")

    with open(repos_file, "w") as f:
        json.dump(repos, f, indent=2)

    logger.info("Repo deregistered: %s", name)
    return {
        "ok": True,
        "message": f"Repo '{name}' removed from registry. "
                   f"The directory at {workspace / name} was not deleted."
    }


# ---------------------------------------------------------------------------
# Agent control
# ---------------------------------------------------------------------------

@app.get("/status")
async def get_status():
    """Return the current agent status dictionary.

    Returns:
        The status dict containing active task, role, model, turns, etc.
    """
    return dict(_status)


@app.get("/blocked")
async def get_blocked():
    """Return a summary of all blocked and waiting tasks.

    Includes:
    - Tasks blocked by human intervention (`BLOCKED_BY_HUMAN`)
    - Tasks blocked by dependencies (`BLOCKED_BY_TASK`)
    - Tasks waiting on budget or time conditions (`WAITING`)

    Returns:
        Dict containing the human-readable report.

    Raises:
        HTTPException: 503 if the scheduler is not configured.
    """
    if _scheduler is None:
        raise HTTPException(status_code=503, detail="Scheduler not configured.")
    
    report = _scheduler.report_blocked(_queue)
    return {"report": report}


@app.get("/token_usage")
async def get_token_usage():
    """Return rolling-window token usage per provider.

    Returns:
        Dict with hour and day totals for each configured provider.

    Raises:
        HTTPException: 503 if the budget tracker is not configured.
    """
    if _budget_tracker is None:
        raise HTTPException(status_code=503, detail="Budget tracker not configured.")
    
    usage = {
        "anthropic": _budget_tracker.current_usage("anthropic"),
        "openai": _budget_tracker.current_usage("openai"),
    }
    return usage


@app.get("/pending")
async def get_pending():
    """Return the current pending clarification question, if any.

    Returns:
        Dict containing the question text or None.
    """
    from matrixmouse import comms as comms_module
    m = comms_module.get_manager()
    question = m.get_pending_question() if m else None
    return {"pending": question}


@app.post("/interject")
async def interject(body: InterjectionRequest):
    """Inject a human message into the agent loop.

    Deprecated: Use specific interjection endpoints instead.

    Args:
        body: `InterjectionRequest` payload.

    Returns:
        Confirmation dict with "ok" status.

    Raises:
        HTTPException: 503 if comms not configured, 400 if message is empty.
    """
    from matrixmouse import comms as comms_module
    m = comms_module.get_manager()
    if m is None:
        raise HTTPException(status_code=503, detail="Comms not configured.")

    msg = body.message.strip()
    if not msg:
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    m.put_interjection(msg, repo=body.repo)
    scope = f"repo='{body.repo}'" if body.repo else "workspace-wide"
    logger.info("Interjection received via API (%s): %s", scope, msg[:80])
    return {"ok": True}

 
async def _handle_turn_limit_response(
    task_id: str,
    action: str,
    note: str = "",
    extend_by: int = 0,
) -> dict:
    """Handle a turn limit decision for a blocked task.

    Actions:
        - extend: grant additional turns.
        - respec: append the note as a user message and reset the turn count.
        - cancel: mark the task `CANCELLED`.

    Args:
        task_id: ID of the blocked task.
        action: One of "extend", "respec", "cancel".
        note: Required for respec, optional for others.
        extend_by: Number of turns to add (0 uses default).

    Returns:
        Dict confirming the action taken.

    Raises:
        HTTPException: 404 if not found, 400 if status is invalid or action unknown.
    """
    from matrixmouse.task import TaskStatus
 
    queue = _require_queue()
    task = queue.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found.")
 
    if task.status != TaskStatus.BLOCKED_BY_HUMAN:
        raise HTTPException(
            status_code=400,
            detail=f"Task '{task_id}' is not BLOCKED_BY_HUMAN "
                   f"(current status: {task.status.value})."
        )
 
    action = action.lower()
 
    if action == "extend":
        default_turns = _config.agent_max_turns if _config else 50
        extension = extend_by if extend_by > 0 else default_turns
        task.turn_limit = task.turn_limit + extension
        task.status = TaskStatus.READY
        if note:
            task.context_messages.append({
                "role": "user",
                "content": f"[Operator note on turn limit extension]: {note}",
            })
        queue.update(task)
        notify_task_available()
        logger.info("Turn limit extended by %d for task [%s].", extension, task_id)
        return {
            "ok": True,
            "action": "extend",
            "new_turn_limit": task.turn_limit,
            "task_id": task_id,
        }
 
    elif action == "respec":
        if not note.strip():
            raise HTTPException(
                status_code=400,
                detail="note is required for respec action."
            )
        task.context_messages.append({
            "role": "user",
            "content": (
                f"[Operator respec — please re-read and adjust your approach]:\n"
                f"{note.strip()}"
            ),
        })
        task.turn_limit = 0
        task.status = TaskStatus.READY
        queue.update(task)
        notify_task_available()
        logger.info("Task [%s] respec'd and returned to READY.", task_id)
        return {"ok": True, "action": "respec", "task_id": task_id}
 
    elif action == "cancel":
        task.status = TaskStatus.CANCELLED
        task.completed_at = datetime.now(timezone.utc).isoformat()
        if note:
            task.notes = (task.notes + f"\n[Cancelled]: {note}").strip()
        queue.update(task)
        logger.info("Task [%s] cancelled via turn-limit response.", task_id)
        return {"ok": True, "action": "cancel", "task_id": task_id}
 
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid action '{action}'. Valid: extend, respec, cancel."
        )
 

# ---------------------------------------------------------------------------
# Interjection routing
# ---------------------------------------------------------------------------

@app.post("/interject/workspace", status_code=201)
async def interject_workspace(body: WorkspaceInterjectionRequest):
    """Send a workspace-scoped message directly to the Manager agent.

    Creates a Manager task with `preempt=True` so it is picked up at the
    next inference boundary.

    Args:
        body: `WorkspaceInterjectionRequest` payload.

    Returns:
        Dict with the created Manager task ID.

    Raises:
        HTTPException: 400 if message is empty.
    """
    from matrixmouse.task import AgentRole, Task, TaskStatus

    queue = _require_queue()
    msg = body.message.strip()
    if not msg:
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    task = _build_interjection_task(
        message=msg,
        repo=[],
        title_prefix="[Interjection]",
    )
    queue.add(task)
    notify_task_available()

    logger.info(
        "Workspace interjection received — Manager task [%s] created.",
        task.id,
    )
    return {"ok": True, "manager_task_id": task.id}


@app.post("/interject/repo/{repo_name}", status_code=201)
async def interject_repo(repo_name: str, body: RepoInterjectionRequest):
    """Send a repo-scoped message to the Manager agent.

    Creates a Manager task with `preempt=True` scoped to the named repository.

    Args:
        repo_name: Name of the target repository.
        body: `RepoInterjectionRequest` payload.

    Returns:
        Dict with the created Manager task ID.

    Raises:
        HTTPException: 400 if message or repo_name is empty.
    """
    from matrixmouse.task import AgentRole, Task, TaskStatus

    queue = _require_queue()
    msg = body.message.strip()
    if not msg:
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    if not repo_name.strip():
        raise HTTPException(status_code=400, detail="repo_name cannot be empty.")

    task = _build_interjection_task(
        message=msg,
        repo=[repo_name],
        title_prefix=f"[Interjection/{repo_name}]",
    )
    queue.add(task)
    notify_task_available()

    logger.info(
        "Repo interjection received for '%s' — Manager task [%s] created.",
        repo_name, task.id,
    )
    return {"ok": True, "manager_task_id": task.id, "repo": repo_name}


@app.post("/tasks/{task_id}/interject")
async def interject_task(task_id: str, body: TaskInterjectionRequest):
    """Send a message directly to a specific task's agent.

    Appends the message to the task's context messages.

    Args:
        task_id: ID of the target task.
        body: `TaskInterjectionRequest` payload.

    Returns:
        Confirmation dict with "ok" status.

    Raises:
        HTTPException: 404 if not found, 400 if task is terminal or message empty.
    """
    queue = _require_queue()
    task = queue.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found.")

    if task.status.is_terminal:
        raise HTTPException(
            status_code=400,
            detail=f"Task '{task_id}' is {task.status.value} — cannot interject."
        )

    msg = body.message.strip()
    if not msg:
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    task.context_messages.append({
        "role": "user",
        "content": (
            f"[Human operator note — please incorporate before continuing]: {msg}"
        ),
    })
    queue.update(task)

    logger.info(
        "Task interjection received for [%s]: %s", task_id, msg[:80]
    )
    return {"ok": True, "task_id": task_id}


@app.post("/tasks/{task_id}/answer")
async def answer_task(task_id: str, body: TaskAnswerRequest):
    """Answer a clarification question for a blocked task.

    Appends the answer to the task's context messages and unblocks it if needed.

    Args:
        task_id: ID of the blocked task.
        body: `TaskAnswerRequest` payload.

    Returns:
        Dict confirming the answer was received and if the task was unblocked.

    Raises:
        HTTPException: 404 if not found, 400 if message is empty.
    """
    from matrixmouse.task import TaskStatus

    queue = _require_queue()
    task = queue.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found.")

    msg = body.message.strip()
    if not msg:
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    task.context_messages.append({
        "role": "user",
        "content": msg,
    })

    task.pending_question = ""

    was_blocked = task.status == TaskStatus.BLOCKED_BY_HUMAN
    if was_blocked:
        task.status = TaskStatus.READY

    queue.update(task)

    # Cancel any stale clarification Manager task created for this task
    if _ws_state_repo is not None:
        try:
            stale_manager_task_id = _ws_state_repo.get_stale_clarification_task(
                task_id
            )
            if stale_manager_task_id:
                stale_task = queue.get(stale_manager_task_id)
                if stale_task is not None and not stale_task.status.is_terminal:
                    queue.mark_cancelled(stale_manager_task_id)
                    logger.info(
                        "Cancelled stale clarification Manager task [%s] "
                        "after direct answer for task [%s].",
                        stale_manager_task_id, task_id,
                    )
                _ws_state_repo.clear_stale_clarification_task(task_id)
        except Exception as e:
            logger.warning(
                "Failed to cancel stale clarification task for [%s]: %s",
                task_id, e,
            )

    if was_blocked:
        notify_task_available()

    logger.info(
        "Answer received for task [%s]%s: %s",
        task_id,
        " (unblocked)" if was_blocked else "",
        msg[:80],
    )
    return {
        "ok":        True,
        "task_id":   task_id,
        "unblocked": was_blocked,
    }

 
@app.post("/tasks/{task_id}/decision")
async def task_decision(task_id: str, body: DecisionRequest):
    """Submit a human decision in response to a structured choice event.

    Unified endpoint for multi-choice decision events emitted by the orchestrator.

    Supported decision types:
        - `pr_approval_required`: approve or reject a PR.
        - `pr_rejection`: rework or manual resolution after PR closure.
        - `critic_turn_limit_reached`: approve, extend, or block after review turns.
        - `turn_limit_reached`: extend, respec, or cancel after agent turns.
        - `merge_conflict_resolution_turn_limit_reached`: extend or abort merge.
        - `planning_turn_limit_reached`: extend, commit, or cancel planning.
        - `decomposition_confirmation_required`: allow or deny task decomposition.

    Args:
        task_id: ID of the blocked task.
        body: `DecisionRequest` payload.

    Returns:
        Dict confirming the decision outcome.

    Raises:
        HTTPException: 404 if not found, 400 if status is invalid or choice is unknown.
    """
    from matrixmouse.task import TaskStatus, PRState
 
    queue = _require_queue()
    task = queue.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found.")
 
    dt = body.decision_type
    choice = body.choice.lower()
    note = body.note.strip()
 
    # ------------------------------------------------------------------
    # PR approval
    # ------------------------------------------------------------------
    if dt == "pr_approval_required":
        if task.status != TaskStatus.BLOCKED_BY_HUMAN:
            raise HTTPException(
                status_code=400,
                detail=f"Task '{task_id}' is not BLOCKED_BY_HUMAN.",
            )
 
        if choice == "approve":
            # Determine parent branch and repo root from task metadata
            if not task.repo:
                raise HTTPException(
                    status_code=400,
                    detail=f"Task '{task_id}' has no repo configured.",
                )
            if not task.branch:
                raise HTTPException(
                    status_code=400,
                    detail=f"Task '{task_id}' has no branch assigned.",
                )
 
            # Look up the parent branch — same logic as orchestrator
            parent_branch: str | None = None
            if task.parent_task_id:
                parent_task = queue.get(task.parent_task_id)
                if parent_task and parent_task.branch:
                    parent_branch = parent_task.branch
            if not parent_branch and _config:
                parent_branch = _config.default_merge_target or None
            if not parent_branch:
                raise HTTPException(
                    status_code=400,
                    detail="Cannot determine PR base branch — no parent task branch "
                           "and default_merge_target is not configured.",
                )
 
            repo_root = (
                _workspace_root / task.repo[0] if _workspace_root else None
            )
            if repo_root is None or not repo_root.exists():
                raise HTTPException(
                    status_code=400,
                    detail=f"Repo root for '{task.repo[0]}' not found.",
                )
 
            # Delegate push + PR creation to orchestrator helper via import
            # The orchestrator is not directly accessible here, so we call
            # the git and provider logic directly.
            from matrixmouse.tools.git_tools import push_to_remote
            from matrixmouse.git.git_remote_provider import GitRemoteError
 
            # Resolve provider
            provider = None
            owner_repo = ""
            if _ws_state_repo:
                try:
                    metadata = _ws_state_repo.get_repo_metadata(task.repo[0])
                    if metadata and metadata.get("provider") == "github":
                        import os
                        from matrixmouse.git.github_provider import GitHubProvider
                        token = os.environ.get("GITHUB_TOKEN", "")
                        if token:
                            provider = GitHubProvider(token=token)
                            owner_repo = _parse_owner_repo_api(
                                metadata.get("remote_url", "")
                            )
                except Exception as e:
                    logger.warning("Failed to resolve provider for PR: %s", e)
 
            if not provider or not owner_repo:
                raise HTTPException(
                    status_code=503,
                    detail="No git provider configured for this repo. "
                           "Set provider and remote_url in repo_metadata.",
                )
 
            # Push branch to origin
            ok, err = push_to_remote(task.branch, "origin", repo_root)
            if not ok:
                raise HTTPException(
                    status_code=500,
                    detail=f"git push failed: {err}",
                )
 
            # Create PR
            try:
                pr_url = provider.create_pull_request(
                    repo=owner_repo,
                    head=task.branch,
                    base=parent_branch,
                    title=task.title,
                    body=task.description[:2000] if task.description else "",
                )
            except GitRemoteError as e:
                raise HTTPException(
                    status_code=502,
                    detail=f"PR creation failed: {e}",
                )
 
            # Store PR state
            from datetime import datetime, timedelta, timezone
            next_poll = (
                datetime.now(timezone.utc)
                + timedelta(
                    minutes=_config.pr_poll_interval_minutes if _config else 10
                )
            ).isoformat()
 
            task.pr_url = pr_url
            task.pr_state = PRState.OPEN
            task.pr_poll_next_at = next_poll
            if note:
                task.context_messages.append({
                    "role": "user",
                    "content": f"[Operator note on PR submission]: {note}",
                })
            queue.update(task)
            # Task stays BLOCKED_BY_HUMAN — the poll loop unblocks it on merge
 
            logger.info("PR created for task [%s] via decision endpoint: %s", task_id, pr_url)
            return {
                "ok": True,
                "action": "approve",
                "pr_url": pr_url,
                "task_id": task_id,
            }
 
        elif choice == "reject":
            # Keep blocked, optionally append note
            if note:
                task.context_messages.append({
                    "role": "user",
                    "content": f"[Operator note — PR rejected manually]: {note}",
                })
                queue.update(task)
            logger.info(
                "PR approval rejected by operator for task [%s].", task_id
            )
            return {
                "ok": True,
                "action": "reject",
                "task_id": task_id,
            }
 
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid choice '{choice}' for pr_approval_required. "
                       f"Valid: approve, reject.",
            )
 
    # ------------------------------------------------------------------
    # PR rejection (rework or manual)
    # ------------------------------------------------------------------
    elif dt == "pr_rejection":
        if task.status != TaskStatus.BLOCKED_BY_HUMAN:
            raise HTTPException(
                status_code=400,
                detail=f"Task '{task_id}' is not BLOCKED_BY_HUMAN.",
            )
 
        if choice == "rework":
            if note:
                task.context_messages.append({
                    "role": "user",
                    "content": f"[Operator note on rework]: {note}",
                })
            # Clear PR fields so a new PR can be created after rework
            task.pr_state = PRState.NONE
            task.pr_url = ""
            task.pr_poll_next_at = ""
            task.status = TaskStatus.READY
            queue.update(task)
            notify_task_available()
            logger.info("Task [%s] unblocked for PR rework.", task_id)
            return {
                "ok": True,
                "action": "rework",
                "task_id": task_id,
            }
 
        elif choice == "manual":
            if note:
                task.notes = (task.notes + f"\n[Manual resolution note]: {note}").strip()
                queue.update(task)
            logger.info(
                "Task [%s] kept blocked for manual PR resolution.", task_id
            )
            return {
                "ok": True,
                "action": "manual",
                "task_id": task_id,
            }
 
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid choice '{choice}' for pr_rejection. "
                       f"Valid: rework, manual.",
            )
 
    # ------------------------------------------------------------------
    # Critic turn limit — delegate to existing helper
    # ------------------------------------------------------------------
    elif dt == "critic_turn_limit_reached":
        return await _handle_critic_review_response(task_id, choice, note)
 
    # ------------------------------------------------------------------
    # Generic turn limit
    # ------------------------------------------------------------------
    elif dt == "turn_limit_reached":
        extend_by = int(body.metadata.get("extend_by", 0))
        return await _handle_turn_limit_response(task_id, choice, note, extend_by)
 
    # ------------------------------------------------------------------
    # Merge conflict turn limit
    # ------------------------------------------------------------------
    elif dt == "merge_conflict_resolution_turn_limit_reached":
        if task.status != TaskStatus.BLOCKED_BY_HUMAN:
            raise HTTPException(
                status_code=400,
                detail=f"Task '{task_id}' is not BLOCKED_BY_HUMAN.",
            )
 
        if choice == "extend":
            default_turns = _config.merge_conflict_max_turns if _config else 5
            task.turn_limit = task.turn_limit + default_turns
            task.status = TaskStatus.READY
            if note:
                task.context_messages.append({
                    "role": "user",
                    "content": f"[Operator note on merge extension]: {note}",
                })
            queue.update(task)
            notify_task_available()
            return {
                "ok": True,
                "action": "extend",
                "new_turn_limit": task.turn_limit,
                "task_id": task_id,
            }
 
        elif choice == "abort":
            if note:
                task.notes = (task.notes + f"\n[Merge aborted]: {note}").strip()
            queue.mark_cancelled(task_id)
            logger.info("Merge task [%s] aborted by operator.", task_id)
            return {"ok": True, "action": "abort", "task_id": task_id}
 
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid choice '{choice}' for merge_conflict_resolution_turn_limit_reached. "
                       f"Valid: extend, abort.",
            )
 
    # ------------------------------------------------------------------
    # Planning turn limit
    # ------------------------------------------------------------------
    elif dt == "planning_turn_limit_reached":
        if task.status != TaskStatus.BLOCKED_BY_HUMAN:
            raise HTTPException(
                status_code=400,
                detail=f"Task '{task_id}' is not BLOCKED_BY_HUMAN.",
            )
 
        if choice == "extend":
            default_turns = _config.manager_planning_max_turns if _config else 10
            task.turn_limit = task.turn_limit + default_turns
            task.status = TaskStatus.READY
            if note:
                task.context_messages.append({
                    "role": "user",
                    "content": f"[Operator note on planning extension]: {note}",
                })
            queue.update(task)
            notify_task_available()
            return {
                "ok": True,
                "action": "extend",
                "new_turn_limit": task.turn_limit,
                "task_id": task_id,
            }
 
        elif choice == "commit":
            # Commit partial plan as-is and mark task complete
            if _ws_state_repo:
                try:
                    _ws_state_repo.clear_session_context(task_id)
                except Exception:
                    pass
            queue.mark_complete(task_id)
            notify_task_available()
            logger.info("Planning task [%s] committed as-is by operator.", task_id)
            return {"ok": True, "action": "commit", "task_id": task_id}
 
        elif choice == "cancel":
            if note:
                task.notes = (task.notes + f"\n[Planning cancelled]: {note}").strip()
                queue.update(task)
            queue.mark_cancelled(task_id)
            logger.info("Planning task [%s] cancelled by operator.", task_id)
            return {"ok": True, "action": "cancel", "task_id": task_id}
 
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid choice '{choice}' for planning_turn_limit_reached. "
                       f"Valid: extend, commit, cancel.",
            )
        
    # ------------------------------------------------------------------
    # Decomposition confirmation
    # ------------------------------------------------------------------
    elif dt == "decomposition_confirmation_required":
        if task.status != TaskStatus.BLOCKED_BY_HUMAN:
            raise HTTPException(
                status_code=400,
                detail=f"Task '{task_id}' is not BLOCKED_BY_HUMAN.",
            )

        if choice == "allow":
            # Increment confirmed depth so the replayed split_task call
            # passes the depth check on resume.
            task.decomposition_confirmed_depth += 1
            if note:
                task.context_messages.append({
                    "role": "user",
                    "content": f"[Operator note on decomposition approval]: {note}",
                })
            # Return to READY — pending_tool_calls replay handles the rest.
            task.status = TaskStatus.READY
            queue.update(task)
            notify_task_available()
            logger.info(
                "Decomposition approved for task [%s] "
                "(confirmed_depth now %d).",
                task_id, task.decomposition_confirmed_depth,
            )
            return {
                "ok": True,
                "action": "allow",
                "decomposition_confirmed_depth": task.decomposition_confirmed_depth,
                "task_id": task_id,
            }

        elif choice == "deny":
            if not note:
                raise HTTPException(
                    status_code=400,
                    detail="note is required when denying decomposition — "
                           "provide a reason for the Manager.",
                )
            # Clear pending_tool_calls so the split_task replay doesn't run.
            # Inject a denial message so the agent knows to work within
            # the current depth.
            task.pending_tool_calls = []
            task.context_messages.append({
                "role": "user",
                "content": (
                    "[Decomposition denied by operator]\n"
                    "You may not decompose this task further. "
                    "Complete the work within the current task depth, "
                    "adjusting scope or descriptions as needed."
                    + (f"\nOperator note: {note}" if note else "")
                ),
            })
            task.status = TaskStatus.READY
            queue.update(task)
            notify_task_available()
            logger.info(
                "Decomposition denied for task [%s].", task_id
            )
            return {
                "ok": True,
                "action": "deny",
                "task_id": task_id,
            }

        else:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid choice '{choice}' for "
                       f"decomposition_confirmation_required. Valid: allow, deny.",
            )
        
    # ------------------------------------------------------------------
    # Unknown decision type
    # ------------------------------------------------------------------
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown decision_type '{dt}'.",
        )
 
 
def _parse_owner_repo_api(remote_url: str) -> str:
    """Extract owner/repo from a remote URL.

    Mirrors the orchestrator helper but lives in `api.py` to avoid a
    circular import.

    Args:
        remote_url: Git remote URL string.

    Returns:
        "owner/repo" string, or "" if unparseable.
    """
    if not remote_url:
        return ""
    url = remote_url.rstrip("/")
    if url.endswith(".git"):
        url = url[:-4]
    if "@" in url and ":" in url:
        return url.split(":", 1)[-1]
    parts = url.split("/")
    if len(parts) >= 2:
        return "/".join(parts[-2:])
    return ""

 
async def _handle_critic_review_response(
    task_id: str,
    action: str,
    feedback: str = "",
) -> dict:
    """Handle a Critic turn-limit decision.

    Actions:
        - approve_task: mark the reviewed task `COMPLETE` directly.
        - extend_critic: give the Critic more turns.
        - block_task: cancel the Critic and move reviewed task to `BLOCKED_BY_HUMAN`.

    Args:
        task_id: ID of the Critic task (not the reviewed task).
        action: One of "approve_task", "extend_critic", "block_task".
        feedback: Optional feedback appended to reviewed task context.

    Returns:
        Dict confirming the action taken.

    Raises:
        HTTPException: 404 if not found, 400 if status is invalid or reviews_task_id missing.
    """
    from matrixmouse.task import TaskStatus
 
    queue = _require_queue()
    critic_task = queue.get(task_id)
    if critic_task is None:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found.")
 
    if critic_task.status != TaskStatus.BLOCKED_BY_HUMAN:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Task '{task_id}' is not BLOCKED_BY_HUMAN "
                f"(current status: {critic_task.status.value})."
            )
        )
 
    if not critic_task.reviews_task_id:
        raise HTTPException(
            status_code=400,
            detail=f"Task '{task_id}' has no reviews_task_id — not a Critic task."
        )
 
    reviewed_task = queue.get(critic_task.reviews_task_id)
    if reviewed_task is None:
        raise HTTPException(
            status_code=404,
            detail=f"Reviewed task '{critic_task.reviews_task_id}' not found."
        )
 
    action = action.lower()
    feedback = feedback.strip()
 
    if action == "approve_task":
        if feedback:
            reviewed_task.context_messages.append({
                "role": "user",
                "content": f"[Human operator approval note]: {feedback}",
            })
        queue.remove_dependency(task_id, reviewed_task.id)
        queue.mark_complete(reviewed_task.id)
        queue.mark_cancelled(task_id)
        notify_task_available()
        logger.info(
            "Critic [%s] — operator approved reviewed task [%s] directly.",
            task_id, reviewed_task.id,
        )
        return {
            "ok": True,
            "action": "approve_task",
            "reviewed_task_id": reviewed_task.id,
        }
 
    elif action == "extend_critic":
        critic_task.turn_limit = (
            critic_task.turn_limit
            + (_config.critic_max_turns if _config else 5)
        )
        critic_task.status = TaskStatus.READY
        if feedback:
            critic_task.context_messages.append({
                "role": "user",
                "content": f"[Human operator note on Critic review extension]: {feedback}",
            })
        queue.update(critic_task)
        notify_task_available()
        logger.info(
            "Critic [%s] — operator extended turn limit to %d.",
            task_id, critic_task.turn_limit,
        )
        return {
            "ok": True,
            "action": "extend_critic",
            "new_turn_limit": critic_task.turn_limit,
        }
 
    elif action == "block_task":
        queue.mark_cancelled(task_id)
        queue.remove_dependency(task_id, reviewed_task.id)
        if feedback:
            refreshed = queue.get(reviewed_task.id)
            if refreshed is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"Reviewed task '{reviewed_task.id}' not found."
                )
            refreshed.notes = (
                refreshed.notes + f"\n[Critic review blocked]: {feedback}"
            ).strip()
            queue.update(refreshed)
        queue.mark_blocked_by_human(reviewed_task.id)
        logger.info(
            "Critic [%s] — operator blocked reviewed task [%s] for manual review.",
            task_id, reviewed_task.id,
        )
        return {
            "ok": True,
            "action": "block_task",
            "reviewed_task_id": reviewed_task.id,
        }
 
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid action '{action}'. Valid: approve_task, extend_critic, block_task."
        )
 
 
@app.post("/stop")
async def soft_stop():
    """Request the orchestrator to stop after the current tool call completes.

    The flag is cleared automatically when the next task starts.

    Returns:
        Confirmation dict with "ok" status.
    """
    _stop_requested.set()
    logger.info("Soft stop requested via API.")
    return {
        "ok": True,
        "message": "Stop requested. Agent will halt after the current tool call completes.",
    }


@app.post("/kill")
async def estop():
    """Emergency stop — immediately shuts down the service.

    Writes an `ESTOP` lockfile then sends `SIGTERM`. The service will not
    restart until the lockfile is manually removed.

    Returns:
        Confirmation dict with "ok" status.

    Raises:
        HTTPException: 503 if workspace not configured, 500 if lockfile write fails.
    """
    estop_file = _estop_path()
    if estop_file is None:
        raise HTTPException(status_code=503, detail="Workspace not configured.")

    try:
        estop_file.parent.mkdir(parents=True, exist_ok=True)
        estop_file.write_text(
            f"ESTOP engaged at {datetime.now(timezone.utc).isoformat()}\n"
            f"Remove this file and restart the service to resume:\n"
            f"  sudo systemctl start matrixmouse\n"
        )
        logger.critical("E-STOP engaged via API. Writing lockfile and shutting down.")
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to write ESTOP lockfile: {e}"
        )

    # Send SIGTERM to ourselves — triggers the clean shutdown handler in
    # _service.py, which releases the PID lock and exits with code 0.
    # systemd will not restart because Restart=on-failure and exit code is 0.
    os.kill(os.getpid(), signal.SIGTERM)

    # This response may or may not reach the client depending on timing,
    # but we return it anyway for CLI usage where the connection may survive.
    return {
        "ok": True,
        "message": "E-STOP engaged. Service is shutting down and will not restart.",
    }


@app.get("/estop")
async def estop_status():
    """Return current E-STOP state.

    Returns:
        Dict with "engaged" boolean and "message" details.
    """
    estop_file = _estop_path()
    if estop_file is None:
        return {"engaged": False, "message": None}

    if estop_file.exists():
        try:
            message = estop_file.read_text()
        except Exception:
            message = "ESTOP engaged."
        return {"engaged": True, "message": message}

    return {"engaged": False, "message": None}


@app.post("/estop/reset")
async def estop_reset():
    """Reset the E-STOP — remove the lockfile so the service can start again.

    Returns:
        Confirmation dict with "ok" status.

    Raises:
        HTTPException: 503 if workspace not configured, 500 if removal fails.
    """
    estop_file = _estop_path()
    if estop_file is None:
        raise HTTPException(status_code=503, detail="Workspace not configured.")

    if not estop_file.exists():
        return {"ok": True, "message": "E-STOP was not engaged."}

    try:
        estop_file.unlink()
        logger.info("E-STOP reset via API.")
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to remove ESTOP lockfile: {e}"
        )

    return {
        "ok": True,
        "message": (
            "E-STOP reset. Start the service manually to resume: "
            "sudo systemctl start matrixmouse"
        ),
    }


# ---------------------------------------------------------------------------
# Orchestrator pause / resume
# ---------------------------------------------------------------------------

# Threading event — set means the orchestrator should not start new tasks.
# Unlike _stop_requested (which halts mid-loop), pause prevents loop entry.
# The orchestrator checks is_paused() before picking up the next task.
_orchestrator_paused = threading.Event()


def is_paused() -> bool:
    """Return True if the orchestrator is paused."""
    return _orchestrator_paused.is_set()


@app.post("/orchestrator/pause")
async def pause_orchestrator():
    """Pause the orchestrator — prevent it from starting new tasks.

    Returns:
        Confirmation dict with "ok" status.
    """
    _orchestrator_paused.set()
    logger.info("Orchestrator paused via API.")
    return {
        "ok": True,
        "paused": True,
        "message": (
            "Orchestrator paused. The agent will not start new tasks until "
            "POST /orchestrator/resume is called."
        ),
    }


@app.post("/orchestrator/resume")
async def resume_orchestrator():
    """Resume the orchestrator after a pause.

    Returns:
        Confirmation dict with "ok" status.
    """
    _orchestrator_paused.clear()
    notify_task_available()  # wake the orchestrator immediately
    logger.info("Orchestrator resumed via API.")
    return {
        "ok": True,
        "paused": False,
        "message": "Orchestrator resumed. The agent will pick up the next task.",
    }


@app.get("/orchestrator/status")
async def orchestrator_status():
    """Return the orchestrator pause/stop state and agent status.

    Returns:
        Dict with "paused", "stopped" and "status" details.
    """
    return {
        "paused":   is_paused(),
        "stopped":  is_stop_requested(),
        "status":   dict(_status),
    }


# ---------------------------------------------------------------------------
# Context
# ---------------------------------------------------------------------------

@app.get("/context")
async def get_context(repo: str | None = None):
    """Return the current agent context messages for display.

    The context is stored in the shared `_status` dict under the
    `context_messages` key.

    Args:
        repo: Optional repository name to scope the context.

    Returns:
        Dict with "messages", "count", and "estimated_tokens".
    """
    messages = _status.get("context_messages") or []

    # Sanitise — ensure each message is a plain dict with role + content.
    # The orchestrator may store ollama Message objects or raw dicts.
    safe_messages = []
    for m in messages:
        if isinstance(m, dict):
            role    = m.get("role", "unknown")
            content = m.get("content") or ""
        else:
            role    = getattr(m, "role",    "unknown")
            content = getattr(m, "content", "") or ""
        safe_messages.append({"role": role, "content": content})

    # Rough token estimate (same heuristic as context.py)
    total_chars = sum(len(m["content"]) for m in safe_messages)
    estimated_tokens = total_chars // 4

    return {
        "messages":         safe_messages,
        "count":            len(safe_messages),
        "estimated_tokens": estimated_tokens,
        "repo":             repo,
    }


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@app.get("/config")
async def get_config():
    """Return the current merged configuration (workspace-level).

    Secrets are never included in the response.

    Returns:
        Dict containing safe configuration fields.

    Raises:
        HTTPException: 503 if configuration is not loaded.
    """
    if _config is None:
        raise HTTPException(status_code=503, detail="Config not loaded.")

    safe_fields = {
        k: v for k, v in _config.model_dump().items()
        if k not in {"github_token", "github_token_file"}
    }
    return safe_fields


@app.patch("/config")
async def patch_config(body: ConfigPatchRequest):
    """Set one or more workspace-level config values.

    Writes to `<workspace>/.matrixmouse/config.toml` (layer 2).
    Changes take effect after service restart.

    Args:
        body: `ConfigPatchRequest` payload.

    Returns:
        Dict with "ok" status and the patched values.

    Raises:
        HTTPException: 503 if workspace not configured.
    """
    workspace = _require_workspace()
    return _patch_config_file(
        workspace / ".matrixmouse" / "config.toml",
        body.values,
    )


@app.get("/config/repos/{repo_name}")
async def get_repo_config(repo_name: str):
    """Return repo-level configuration, showing both tracked and untracked layers.

    Args:
        repo_name: Name of the repository.

    Returns:
        Dict with "local", "committed", and "merged" layers.

    Raises:
        HTTPException: 503 if workspace not configured.
    """
    workspace = _require_workspace()

    # Layer 3 — untracked, machine-local
    local_path = workspace / ".matrixmouse" / repo_name / "config.toml"
    local: dict = {}
    if local_path.exists():
        with open(local_path, "rb") as f:
            local = tomllib.load(f)

    # Layer 4 — tracked, in git tree
    committed_path = workspace / repo_name / ".matrixmouse" / "config.toml"
    committed: dict = {}
    if committed_path.exists():
        with open(committed_path, "rb") as f:
            committed = tomllib.load(f)

    merged = {**committed, **local}  # layer 3 wins over layer 4

    return {
        "local": local,
        "committed": committed,
        "merged": merged,
    }


@app.patch("/config/repos/{repo_name}")
async def patch_repo_config(
    repo_name: str,
    body: ConfigPatchRequest,
    commit: bool = Query(
        default=False,
        description=(
            "Write to the repo tree (<repo>/.matrixmouse/config.toml) "
            "for version control. Default writes to the workspace state "
            "dir (untracked, machine-local)."
        ),
    ),
):
    """Set one or more repo-level config values.

    Without `commit=true` (default): writes to layer 3 (local, untracked).
    With `commit=true`: writes to layer 4 (tracked in git).

    Args:
        repo_name: Name of the repository.
        body: `ConfigPatchRequest` payload.
        commit: Whether to write to the tracked repo config.

    Returns:
        Dict with "ok" status and the patched values.

    Raises:
        HTTPException: 503 if workspace not configured.
    """
    workspace = _require_workspace()

    if commit:
        config_path = workspace / repo_name / ".matrixmouse" / "config.toml"
        logger.info(
            "Writing committed repo config for '%s': %s",
            repo_name, list(body.values.keys()),
        )
    else:
        config_path = workspace / ".matrixmouse" / repo_name / "config.toml"
        logger.info(
            "Writing local repo config for '%s': %s",
            repo_name, list(body.values.keys()),
        )

    return _patch_config_file(config_path, body.values)


# ---------------------------------------------------------------------------
# System
# ---------------------------------------------------------------------------

@app.post("/upgrade")
async def upgrade():
    """Upgrade MatrixMouse to the latest version.

    Runs `uv tool upgrade matrixmouse` then rebuilds the test runner
    Docker image if `Dockerfile.testrunner` has changed.

    The service must be restarted after upgrading for changes to take effect.

    Returns:
        Dict with "ok" status and results for each upgrade step.
    """
    results = {}

    try:
        result = subprocess.run(
            ["uv", "tool", "upgrade", "matrixmouse"],
            capture_output=True, text=True, timeout=120,
        )
        results["package"] = {
            "ok": result.returncode == 0,
            "output": result.stdout.strip() or result.stderr.strip(),
        }
    except subprocess.TimeoutExpired:
        results["package"] = {"ok": False, "output": "Timed out after 120s."}
    except FileNotFoundError:
        results["package"] = {"ok": False, "output": "uv not found in PATH."}

    dockerfile_path = _find_testrunner_dockerfile()
    if dockerfile_path:
        rebuild, reason = _should_rebuild_testrunner(dockerfile_path)
        if rebuild:
            try:
                result = subprocess.run(
                    ["docker", "build", "-f", str(dockerfile_path),
                     "-t", "matrixmouse-test-runner",
                     str(dockerfile_path.parent)],
                    capture_output=True, text=True, timeout=300,
                )
                if result.returncode == 0:
                    _record_testrunner_hash(dockerfile_path)
                results["test_runner"] = {
                    "ok": result.returncode == 0,
                    "rebuilt": True,
                    "output": result.stdout.strip() or result.stderr.strip(),
                }
            except subprocess.TimeoutExpired:
                results["test_runner"] = {
                    "ok": False, "rebuilt": False,
                    "output": "Docker build timed out after 300s.",
                }
        else:
            results["test_runner"] = {"ok": True, "rebuilt": False, "reason": reason}
    else:
        results["test_runner"] = {
            "ok": True, "rebuilt": False,
            "reason": "Dockerfile.testrunner not found — skipping.",
        }

    overall_ok = all(v.get("ok", False) for v in results.values())
    return {
        "ok": overall_ok,
        "results": results,
        "note": "Restart the service for changes to take effect: "
                "sudo systemctl restart matrixmouse",
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _infer_repo_name(remote: str) -> str:
    """Infer a repository name from its remote URL.

    Args:
        remote: Git remote URL or path.

    Returns:
        The inferred repository name.
    """
    name = remote.rstrip("/").rsplit("/", 1)[-1]
    if name.endswith(".git"):
        name = name[:-4]
    return name or ""


def _git_env() -> dict:
    """Build the environment dictionary for git subprocesses.

    Includes `GIT_SSH_COMMAND` if an SSH key is configured.

    Returns:
        Environment dict copy.
    """
    env = os.environ.copy()

    from matrixmouse import config as config_module
    cfg = getattr(config_module, "_loaded_config", None)
    if cfg:
        secrets_dir = Path("/etc/matrixmouse/secrets")
        key_path = secrets_dir / cfg.gh_ssh_key_file
        if key_path.exists():
            env["GIT_SSH_COMMAND"] = (
                f"ssh -i {key_path} -o IdentitiesOnly=yes "
                f"-o StrictHostKeyChecking=accept-new"
            )
        else:
            logger.warning(
                "SSH key not found at %s — git clone may fail for private repos.",
                key_path,
            )

    return env
def _patch_config_file(config_path: Path, values: dict) -> dict:
    """Write key-value pairs into a TOML config file.

    Rejects secret-looking keys. Creates parent directories if needed.

    Args:
        config_path: Path to the TOML file.
        values: Dictionary of values to set.

    Returns:
        Dict with "ok" status and the patched values.
    """
    SECRET_SUFFIXES = ("_token", "_key", "_file", "_secret", "_password")
    rejected = [k for k in values if any(k.endswith(s) for s in SECRET_SUFFIXES)]
    if rejected:
        raise HTTPException(
            status_code=400,
            detail=f"Secret fields cannot be set via the API: {rejected}. "
                   f"Edit the .env file directly."
        )

    existing = {}
    if config_path.exists():
        with open(config_path, "rb") as f:
            existing = tomllib.load(f)

    existing.update(values)

    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "wb") as f:
        tomli_w.dump(existing, f)

    return {
        "ok": True,
        "updated": list(values.keys()),
        "path": str(config_path),
        "note": "Restart the service for changes to take effect: "
                "sudo systemctl restart matrixmouse",
    }


def _find_testrunner_dockerfile() -> Path | None:
    """Locate the test runner Dockerfile within the package.

    Returns:
        The `Path` to the Dockerfile, or None if not found.
    """
    import matrixmouse
    package_dir = Path(matrixmouse.__file__).parent
    candidates = [
        package_dir / "docker" / "Dockerfile.testrunner",
        package_dir.parent / "Dockerfile.testrunner",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def _sha256(path: Path) -> str:
    """Compute the SHA256 hash of a file.

    Args:
        path: Path to the file.

    Returns:
        The hex-encoded hash string.
    """
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _should_rebuild_testrunner(dockerfile_path: Path) -> tuple[bool, str]:
    """Determine if the test runner Docker image should be rebuilt.

    Args:
        dockerfile_path: Path to the test runner Dockerfile.

    Returns:
        Tuple of (rebuild_needed, reason_string).
    """
    if _workspace_root is None:
        return True, "No workspace root configured — rebuilding to be safe."
    hash_file = _workspace_root / ".matrixmouse" / "testrunner.image.sha256"
    current_hash = _sha256(dockerfile_path)
    if not hash_file.exists():
        return True, "No recorded hash found — first build."
    try:
        recorded_hash = hash_file.read_text().strip()
    except OSError:
        return True, "Could not read recorded hash — rebuilding to be safe."
    if current_hash != recorded_hash:
        return True, "Dockerfile.testrunner has changed since last build."
    return False, "Dockerfile.testrunner unchanged."


def _record_testrunner_hash(dockerfile_path: Path) -> None:
    """Persist the current Dockerfile hash to the workspace state.

    Args:
        dockerfile_path: Path to the test runner Dockerfile.
    """
    if _workspace_root is None:
        logger.warning("No workspace root — cannot record testrunner hash.")
        return
    hash_file = _workspace_root / ".matrixmouse" / "testrunner.image.sha256"
    try:
        hash_file.write_text(_sha256(dockerfile_path))
    except OSError as e:
        logger.warning("Failed to record testrunner hash: %s", e)


def _inject_decomposition_response(
    queue,
    confirmation_id: str,
    approved: bool,
    reason: str,
) -> None:
    """Inject a decomposition confirmation response into the active Manager task.

    Finds the `RUNNING` or `READY` Manager task and appends a user message.

    Args:
        queue: The `TaskRepository`.
        confirmation_id: The unique ID for the decomposition request.
        approved: Whether the operator approved the split.
        reason: Operator's reason (required on denial).
    """
    from matrixmouse.task import AgentRole, TaskStatus

    manager_tasks = [
        t for t in queue.active_tasks()
        if t.role == AgentRole.MANAGER
        and t.status in (TaskStatus.RUNNING, TaskStatus.READY,
                         TaskStatus.BLOCKED_BY_HUMAN)
    ]

    if not manager_tasks:
        logger.warning(
            "No active Manager task found to inject decomposition response "
            "(confirmation_id=%s).", confirmation_id,
        )
        return

    # Inject into the most recently started Manager task
    manager_task = sorted(
        manager_tasks,
        key=lambda t: t.started_at or "",
        reverse=True,
    )[0]

    if approved:
        content = (
            f"[Decomposition confirmed — confirmation_id={confirmation_id}]\n"
            f"The operator has approved splitting further at this depth. "
            f"You may proceed with the split you proposed."
            + (f"\nOperator note: {reason}" if reason else "")
        )
    else:
        content = (
            f"[Decomposition denied — confirmation_id={confirmation_id}]\n"
            f"The operator has denied further splitting at this depth.\n"
            f"Reason: {reason}\n"
            f"Do not split this branch further. Adjust task descriptions "
            f"or scoping within the existing depth instead."
        )

    manager_task.context_messages.append({
        "role": "user",
        "content": content,
    })

    try:
        queue.update(manager_task)
        notify_task_available()
    except Exception as e:
        logger.warning(
            "Failed to inject decomposition response into Manager task [%s]: %s",
            manager_task.id, e,
        )

def _build_interjection_task(
    message: str,
    repo: list[str],
    title_prefix: str,
) -> Task:
    """Build a Manager task from a human interjection message.

    The task is created with `preempt=True` for high priority execution.

    Args:
        message: The human's message.
        repo: Repository list scope (empty for workspace-wide).
        title_prefix: Prefix for the task title.

    Returns:
        A READY, preempting Manager `Task`.
    """
    from matrixmouse.task import AgentRole, Task, TaskStatus

    # Truncate long messages for the title
    title_body = message[:60] + "..." if len(message) > 60 else message
    title = f"{title_prefix} {title_body}"

    description = (
        f"A human operator has sent a message requiring your attention.\n\n"
        f"Message:\n{message}\n\n"
        f"Interpret the intent, gather context if needed, and take appropriate "
        f"action: create tasks, update existing tasks, answer questions, or "
        f"request clarification if the intent is ambiguous. "
        f"Call declare_complete with a summary of what you did."
    )

    task = Task(
        title=title,
        description=description,
        role=AgentRole.MANAGER,
        repo=repo,
        importance=0.1,   # very high priority (low score)
        urgency=0.1,
    )
    task.preempt = True
    return task
