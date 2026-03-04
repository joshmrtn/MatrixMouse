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

Threading model:
    The API server runs in a background thread (uvicorn).
    The orchestrator runs in the main thread.
    _task_condition bridges them — the API notifies it when a new task
    is created so the orchestrator wakes immediately rather than polling.

Do not add agent logic, inference calls, or tool dispatch here.
"""

import logging
import os
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
    """Return the condition variable for the orchestrator to wait on."""
    return _task_condition


# ---------------------------------------------------------------------------
# Module-level state — injected at startup by the orchestrator
# ---------------------------------------------------------------------------

_queue: Any = None           # TaskQueue
_status: dict = {}           # live agent status dict (mutated by orchestrator)
_workspace_root: Path | None = None
_config: Any = None          # MatrixMouseConfig


def configure(
    queue: Any,
    status: dict,
    workspace_root: Path,
    config: Any,
) -> None:
    """
    Inject runtime state into the API module.
    Called once at startup before uvicorn starts.
    """
    global _queue, _status, _workspace_root, _config
    _queue = queue
    _status = status
    _workspace_root = workspace_root
    _config = config
    logger.info("API module configured. Workspace: %s", workspace_root)


def _require_queue():
    if _queue is None:
        raise HTTPException(status_code=503, detail="Agent not ready.")
    return _queue


def _require_workspace() -> Path:
    if _workspace_root is None:
        raise HTTPException(status_code=503, detail="Workspace not configured.")
    return _workspace_root


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class TaskCreateRequest(BaseModel):
    title: str
    description: str = ""
    repo: list[str] = []
    target_files: list[str] = []
    importance: float = 0.5
    urgency: float = 0.5

class TaskEditRequest(BaseModel):
    title: str | None = None
    description: str | None = None
    repo: list[str] | None = None
    target_files: list[str] | None = None
    importance: float | None = None
    urgency: float | None = None
    notes: str | None = None

class InterjectionRequest(BaseModel):
    message: str
    repo: str | None = None

class RepoAddRequest(BaseModel):
    remote: str
    name: str | None = None

class ConfigPatchRequest(BaseModel):
    values: dict[str, Any]


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    """Liveness check. Returns 200 when the server is up."""
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
    """
    List tasks.

    Query params:
        status: Filter by status value (pending, active, blocked_by_task, etc.)
        repo:   Filter by repo name.
        all:    Include terminal tasks (complete, cancelled). Default false.
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

    tasks.sort(key=lambda t: t.priority_score(), reverse=True)

    return {
        "tasks": [t.to_dict() for t in tasks],
        "count": len(tasks),
    }


@app.get("/tasks/{task_id}")
async def get_task(task_id: str):
    """Get full details of a single task."""
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
    """
    Create a new task and add it to the queue.
    Notifies the orchestrator immediately via the condition variable.
    """
    from matrixmouse.orchestrator import Task, TaskStatus
    from matrixmouse.phases import Phase

    queue = _require_queue()

    if not body.title.strip():
        raise HTTPException(status_code=400, detail="Title cannot be empty.")

    importance = max(0.0, min(1.0, body.importance))
    urgency    = max(0.0, min(1.0, body.urgency))

    task = Task(
        title=body.title.strip(),
        description=body.description.strip(),
        repo=body.repo,
        phase=Phase.DESIGN,
        status=TaskStatus.PENDING,
        target_files=body.target_files,
        importance=importance,
        urgency=urgency,
        source="local",
    )
    queue.add(task)
    notify_task_available()

    logger.info("Task created via API: [%s] %s", task.id, task.title)
    return task.to_dict()


@app.patch("/tasks/{task_id}")
async def edit_task(task_id: str, body: TaskEditRequest):
    """Edit mutable fields of an existing task."""
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
    """Cancel a task."""
    queue = _require_queue()
    task = queue.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found.")

    if task.status.is_terminal:
        return {"ok": True, "message": f"Task already {task.status.value}."}

    from matrixmouse.orchestrator import TaskStatus
    task.status = TaskStatus.CANCELLED
    task.completed_at = datetime.now(timezone.utc).isoformat()
    queue.update(task)

    logger.info("Task cancelled via API: [%s] %s", task.id, task.title)
    return {"ok": True, "id": task_id}


# ---------------------------------------------------------------------------
# Repos
# ---------------------------------------------------------------------------

@app.get("/repos")
async def list_repos():
    """List registered repos."""
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
    """
    Clone or register a repo into the workspace.
    Runs synchronously — blocks until the clone completes.
    Auto-inits the repo (workspace state dir only — repo tree untouched).
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

    local = Path(remote)
    is_local = local.exists() and local.is_dir()
    workspace.mkdir(parents=True, exist_ok=True)

    result = subprocess.run(
        ["git", "clone", str(local.resolve()) if is_local else remote, str(dest)],
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
    """
    Remove a repo from the registry.
    Does NOT delete the cloned directory — that requires manual action.
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
    """Return the current agent status."""
    return dict(_status)


@app.get("/pending")
async def get_pending():
    """Return the current pending clarification question, if any."""
    from matrixmouse import comms as comms_module
    m = comms_module.get_manager()
    question = m.get_pending_question() if m else None
    return {"pending": question}


@app.post("/interject")
async def interject(body: InterjectionRequest):
    """
    Inject a human message into the agent loop.
    If repo is set, the message is scoped to that repo's context.
    Without repo, the message is workspace-wide.
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


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@app.get("/config")
async def get_config():
    """
    Return the current merged configuration (workspace-level).
    Secrets are never included in the response.
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
    """
    Set one or more workspace-level config values.
    Writes to <workspace>/.matrixmouse/config.toml (layer 2).
    Changes take effect after service restart.
    """
    workspace = _require_workspace()
    return _patch_config_file(
        workspace / ".matrixmouse" / "config.toml",
        body.values,
    )


@app.get("/config/repos/{repo_name}")
async def get_repo_config(repo_name: str):
    """
    Return repo-level config, showing both tracked and untracked layers.

    Response shape:
        {
            "local":     { ... }   # layer 3: workspace state dir (untracked)
            "committed": { ... }   # layer 4: repo tree (tracked)
            "merged":    { ... }   # layer 3 over layer 4 (effective values)
        }
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
    """
    Set one or more repo-level config values.

    Without ?commit=true (default):
        Writes to <workspace>/.matrixmouse/<repo>/config.toml
        Layer 3 — untracked, local machine only.

    With ?commit=true:
        Writes to <workspace>/<repo>/.matrixmouse/config.toml
        Layer 4 — tracked, in the git tree.
        Creates <repo>/.matrixmouse/ if it doesn't exist.

    CLI equivalent:
        matrixmouse config set <key> <value> --repo <name>           # layer 3
        matrixmouse config set <key> <value> --repo <name> --commit  # layer 4
    """
    workspace = _require_workspace()

    if commit:
        # Layer 4 — tracked, inside the git repo
        config_path = workspace / repo_name / ".matrixmouse" / "config.toml"
        logger.info(
            "Writing committed repo config for '%s': %s",
            repo_name, list(body.values.keys()),
        )
    else:
        # Layer 3 — untracked, workspace state dir
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
    """
    Upgrade MatrixMouse to the latest version.

    Runs `uv tool upgrade matrixmouse` then rebuilds the test runner
    Docker image if Dockerfile.testrunner has changed since the last build.

    The service must be restarted after upgrading for changes to take effect.
    The caller (CLI cmd_upgrade) is responsible for triggering the restart.
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
    name = remote.rstrip("/").rsplit("/", 1)[-1]
    if name.endswith(".git"):
        name = name[:-4]
    return name or ""


def _git_env() -> dict:
    env = os.environ.copy()
    key_file = os.environ.get("MATRIXMOUSE_AGENT_GH_KEY_FILE")
    secrets_path = os.environ.get("SECRETS_PATH", "/run/secrets")
    if key_file:
        key_path = Path(secrets_path) / key_file
        if key_path.exists():
            env["GIT_SSH_COMMAND"] = (
                f"ssh -i {key_path} -o IdentitiesOnly=yes "
                f"-o StrictHostKeyChecking=accept-new"
            )
    return env


def _patch_config_file(config_path: Path, values: dict) -> dict:
    """
    Write key-value pairs into a TOML config file.
    Rejects secret-looking keys. Creates parent directories if needed.
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
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _should_rebuild_testrunner(dockerfile_path: Path) -> tuple[bool, str]:
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
    if _workspace_root is None:
        logger.warning("No workspace root — cannot record testrunner hash.")
        return
    hash_file = _workspace_root / ".matrixmouse" / "testrunner.image.sha256"
    try:
        hash_file.write_text(_sha256(dockerfile_path))
    except OSError as e:
        logger.warning("Failed to record testrunner hash: %s", e)
