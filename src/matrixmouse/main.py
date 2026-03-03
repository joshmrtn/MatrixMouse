"""
matrixmouse/main.py

Entry point for MatrixMouse. Parses CLI arguments, initialises all
subsystems in order, and hands control to the orchestrator.

Commands:
    init        Initialise MatrixMouse in a repo directory.
    run         Start the agent against the workspace.
    add-repo    Clone or register a repo into the workspace.

    # Future CLI commands (not yet implemented):
    # interject   Send a message to the running agent.
    # tasks       View and edit the task queue.
    # status      Show current agent status.
    # answer      Answer a pending clarification request.

Startup sequence (cmd_run):
    1.  Logging (safe defaults, before anything else)
    2.  Workspace and repo paths resolved
    3.  PID lockfile acquired
    4.  Configuration loaded (workspace → repo cascade)
    5.  Logging reconfigured with user preferences
    6.  Safety module configured
    7.  Model validation
    8.  AST graph built
    9.  Memory, comms modules configured
    10. Web server started
    11. Orchestrator started

Handles top-level signals (SIGINT, SIGTERM) for clean shutdown.
"""

import logging
import os
import signal
import sys
from pathlib import Path

from matrixmouse.utils.logging_utils import setup_logging

# ---------------------------------------------------------------------------
# Logging — must come before any other matrixmouse imports
# ---------------------------------------------------------------------------
setup_logging(log_level="INFO", log_to_file=False, repo_root=Path.cwd())
logger = logging.getLogger(__name__)
logger.info("MatrixMouse starting up...")

# ---------------------------------------------------------------------------
# Remaining imports — after logging is initialised
# ---------------------------------------------------------------------------
import argparse
import json

from matrixmouse.config import MatrixMouseConfig, MatrixMousePaths, load_config
from matrixmouse.init import setup_repo, validate_models
from matrixmouse.graph import ProjectAnalyzer, analyze_project
from matrixmouse import memory
from matrixmouse import comms
from matrixmouse.orchestrator import Orchestrator
from matrixmouse.server import start_server
from matrixmouse.tools import _safety, code_tools, TOOLS, TOOL_REGISTRY  # noqa
from matrixmouse.utils.file_lock import locked_json, LockTimeoutError


# ---------------------------------------------------------------------------
# Signal handling
# ---------------------------------------------------------------------------

def _handle_shutdown(signum, frame):
    logger.info("Shutdown signal received. Exiting cleanly...")
    _release_pidlock()
    sys.exit(0)

signal.signal(signal.SIGINT, _handle_shutdown)
signal.signal(signal.SIGTERM, _handle_shutdown)


# ---------------------------------------------------------------------------
# PID lockfile — prevents multiple instances per workspace
# ---------------------------------------------------------------------------

_pidlock_path: Path | None = None


def _acquire_pidlock(workspace_root: Path) -> None:
    """
    Write a PID lockfile at <workspace>/.matrixmouse/agent.pid.
    Raises SystemExit if another instance is already running.
    """
    global _pidlock_path
    lock_dir = workspace_root / ".matrixmouse"
    lock_dir.mkdir(parents=True, exist_ok=True)
    _pidlock_path = lock_dir / "agent.pid"

    if _pidlock_path.exists():
        try:
            existing_pid = int(_pidlock_path.read_text().strip())
            # Check if the PID is still alive
            os.kill(existing_pid, 0)
            # If we get here, the process is alive
            print(
                f"ERROR: Another MatrixMouse instance is already running "
                f"(PID {existing_pid}) in this workspace.\n"
                f"If this is wrong, delete: {_pidlock_path}"
            )
            sys.exit(1)
        except (ValueError, ProcessLookupError, PermissionError):
            # Stale lockfile — process is dead
            logger.warning(
                "Stale PID lockfile found at %s. Overwriting.",
                _pidlock_path
            )

    _pidlock_path.write_text(str(os.getpid()))
    logger.debug("PID lockfile acquired at %s (PID %d)", _pidlock_path, os.getpid())


def _release_pidlock() -> None:
    """Remove the PID lockfile on clean exit."""
    global _pidlock_path
    if _pidlock_path and _pidlock_path.exists():
        try:
            _pidlock_path.unlink()
            logger.debug("PID lockfile released.")
        except Exception as e:
            logger.warning("Failed to release PID lockfile: %s", e)


# ---------------------------------------------------------------------------
# Workspace resolution
# ---------------------------------------------------------------------------

def _resolve_workspace() -> Path:
    """
    Resolve the workspace root from environment or default.
    """
    env = os.environ.get("WORKSPACE_PATH")
    if env:
        return Path(env).resolve()
    default = Path.home() / "matrixmouse-workspace"
    if default.exists():
        return default
    # Fall back to parent of cwd — useful in development
    return Path.cwd().parent


def _resolve_repo(args, workspace_root: Path) -> Path | None:
    """
    Resolve the repo directory from --repo argument or cwd.

    If --repo is an absolute path or starts with ./ or ../, use it
    directly. Otherwise treat it as a subdirectory of the workspace.
    Falls back to cwd if no --repo argument given.
    """
    repo_arg = getattr(args, "repo", None)

    if not repo_arg:
        # No --repo flag — use cwd if it looks like a repo
        cwd = Path.cwd()
        mm_dir = cwd / ".matrixmouse"
        if mm_dir.exists() or (cwd.parent == workspace_root):
            return cwd
        return None

    repo_path = Path(repo_arg)
    if repo_path.is_absolute() or repo_arg.startswith(("./", "../")):
        return repo_path.resolve()
    return (workspace_root / repo_arg).resolve()


# ---------------------------------------------------------------------------
# CLI commands
# ---------------------------------------------------------------------------

def cmd_init(args):
    """
    Initialise MatrixMouse in a repo directory.

    Creates .matrixmouse/ with starter config and AGENT_NOTES.md.
    Safe to run repeatedly — never overwrites existing files.
    """
    workspace_root = _resolve_workspace()
    repo_root = _resolve_repo(args, workspace_root)

    if repo_root is None:
        repo_root = Path.cwd()
        logger.info("No --repo specified. Initialising in current directory.")

    if not repo_root.exists():
        print(f"ERROR: Repo directory does not exist: {repo_root}")
        sys.exit(1)

    paths = setup_repo(repo_root, workspace_root)
    print(f"Initialized MatrixMouse in {repo_root}")
    print(f"  Config:      {paths.config_dir / 'config.toml'}")
    print(f"  Agent notes: {paths.agent_notes}")
    print(f"  Design docs: {paths.design_docs}")
    print(f"\nNext: add tasks to {workspace_root / '.matrixmouse' / 'tasks.json'}")


def cmd_run(args):
    """
    Start the agent against the workspace.

    Loads config, builds the AST graph, starts the web server,
    and hands control to the orchestrator.
    """
    workspace_root = _resolve_workspace()
    repo_root = _resolve_repo(args, workspace_root)

    if repo_root is None:
        print(
            "ERROR: Could not determine repo to run against.\n"
            "Either run from inside a repo directory, or pass --repo <name>."
        )
        sys.exit(1)

    # --- PID lockfile ---
    _acquire_pidlock(workspace_root)

    try:
        # --- Setup ---
        paths = setup_repo(repo_root, workspace_root)
        config = load_config(repo_root, workspace_root)
        import matrixmouse.config as _cfg
        _cfg._loaded_config = config

        # --- Reconfigure logging ---
        setup_logging(
            log_level=config.log_level,
            log_to_file=config.log_to_file,
            repo_root=repo_root,
        )
        logger.info("Workspace: %s", workspace_root)
        logger.info("Repo:      %s", repo_root)

        # --- Safety module ---
        _safety.configure(repo_root=paths.repo_root)

        # --- Model validation ---
        validate_models(config)

        # --- AST graph ---
        logger.info("Building AST graph for %s...", repo_root)
        graph = analyze_project(str(repo_root))
        logger.info(
            "AST graph complete. %d functions, %d classes indexed.",
            len(graph.functions), len(graph.classes),
        )
        code_tools.configure(graph)

        # --- Memory and comms ---
        memory.configure(paths.agent_notes)
        comms.configure(config)

        # --- Web server ---
        start_server(config, paths)

        # --- Orchestrator ---
        logger.info("Handing control to orchestrator...")
        orchestrator = Orchestrator(config=config, paths=paths, graph=graph)
        orchestrator.run()

    finally:
        _release_pidlock()


def cmd_add_repo(args):
    """
    Clone a remote repo into the workspace and register it.

    Accepts a git remote URL or a local path.
    Writes an entry to <workspace>/.matrixmouse/repos.json.

    Examples:
        matrixmouse add-repo git@github.com:joshmrtn/MatrixMouse.git
        matrixmouse add-repo https://github.com/joshmrtn/MatrixMouse
        matrixmouse add-repo /path/to/existing/local/repo
    """
    workspace_root = _resolve_workspace()
    remote = args.remote

    # Determine if this is a local path or a remote URL
    local_path = Path(remote)
    is_local = local_path.exists() and local_path.is_dir()

    if is_local:
        _add_local_repo(local_path, workspace_root, args)
    else:
        _add_remote_repo(remote, workspace_root, args)


def _infer_repo_name(remote: str) -> str:
    """Infer a directory name from a remote URL."""
    name = remote.rstrip("/").rsplit("/", 1)[-1]
    if name.endswith(".git"):
        name = name[:-4]
    return name


def _register_repo(
    workspace_root: Path,
    name: str,
    local_path: Path,
    remote: str,
) -> None:
    """Write an entry to repos.json."""
    repos_file = workspace_root / ".matrixmouse" / "repos.json"
    repos_file.parent.mkdir(parents=True, exist_ok=True)

    repos = []
    if repos_file.exists():
        with open(repos_file) as f:
            repos = json.load(f)

    # Check if already registered
    for repo in repos:
        if repo.get("name") == name:
            logger.info("Repo '%s' already registered.", name)
            return

    from datetime import datetime, timezone
    repos.append({
        "name": name,
        "remote": remote,
        "local_path": str(local_path),
        "added": datetime.now(timezone.utc).date().isoformat(),
    })

    with open(repos_file, "w") as f:
        json.dump(repos, f, indent=2)

    logger.info("Registered repo '%s' in %s", name, repos_file)


def _add_remote_repo(remote: str, workspace_root: Path, args) -> None:
    """Clone a remote URL into the workspace."""
    import subprocess

    name = getattr(args, "name", None) or _infer_repo_name(remote)
    dest = workspace_root / name

    if dest.exists():
        print(f"Directory '{dest}' already exists.")
        answer = input("(u)pdate with git pull, (s)kip registration, or (a)bort? [u/s/a]: ").strip().lower()
        if answer == "a":
            print("Aborted.")
            sys.exit(0)
        elif answer == "s":
            _register_repo(workspace_root, name, dest, remote)
            print(f"Registered existing directory '{dest}' as '{name}'.")
            _post_add_instructions(name, dest, workspace_root)
            return
        elif answer == "u":
            print(f"Pulling latest changes in '{dest}'...")
            result = subprocess.run(
                ["git", "pull"],
                cwd=dest,
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                print(f"ERROR: git pull failed:\n{result.stderr}")
                sys.exit(1)
            print(result.stdout.strip())
            _register_repo(workspace_root, name, dest, remote)
            _post_add_instructions(name, dest, workspace_root)
            return
        else:
            print("Unrecognised option. Aborted.")
            sys.exit(1)

    # Build git clone command with agent SSH key if configured
    key_file = os.environ.get("MATRIXMOUSE_AGENT_GH_KEY_FILE")
    env = os.environ.copy()
    if key_file:
        key_path = f"/run/secrets/{key_file}"
        if Path(key_path).exists():
            env["GIT_SSH_COMMAND"] = (
                f"ssh -i {key_path} -o IdentitiesOnly=yes "
                f"-o StrictHostKeyChecking=accept-new"
            )

    workspace_root.mkdir(parents=True, exist_ok=True)
    print(f"Cloning '{remote}' into '{dest}'...")

    result = subprocess.run(
        ["git", "clone", remote, str(dest)],
        env=env,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        print(f"ERROR: git clone failed:\n{result.stderr.strip()}")
        sys.exit(1)

    print(f"Cloned successfully.")
    _register_repo(workspace_root, name, dest, remote)
    _post_add_instructions(name, dest, workspace_root)


def _add_local_repo(local_path: Path, workspace_root: Path, args) -> None:
    """Register a local repo that already exists on disk."""
    import subprocess

    name = getattr(args, "name", None) or local_path.name
    dest = workspace_root / name

    if dest.exists() and dest != local_path.resolve():
        print(f"ERROR: '{dest}' already exists in the workspace.")
        print(f"Pass --name to use a different name.")
        sys.exit(1)

    if not dest.exists():
        # Copy the repo into the workspace
        print(f"Copying '{local_path}' into workspace as '{name}'...")
        result = subprocess.run(
            ["git", "clone", str(local_path.resolve()), str(dest)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print(f"ERROR: Failed to copy repo:\n{result.stderr.strip()}")
            sys.exit(1)

    _register_repo(workspace_root, name, dest, str(local_path.resolve()))
    _post_add_instructions(name, dest, workspace_root)


def _post_add_instructions(name: str, dest: Path, workspace_root: Path) -> None:
    """Print next-step instructions after a repo is added."""
    print(f"\nRepo '{name}' is ready at {dest}")
    print(f"\nNext steps:")
    print(f"  1. Initialise MatrixMouse in the repo:")
    print(f"       matrixmouse init --repo {name}")
    print(f"  2. Add tasks to:")
    print(f"       {workspace_root / '.matrixmouse' / 'tasks.json'}")
    print(f"  3. Run the agent:")
    print(f"       matrixmouse run --repo {name}")



# ---------------------------------------------------------------------------
# Shared HTTP helper
# ---------------------------------------------------------------------------

def _agent_post(endpoint: str, payload: dict, port: int) -> dict:
    """
    POST to the running agent's web server.

    Args:
        endpoint: Path including leading slash, e.g. '/interject'
        payload:  JSON-serialisable dict to send as request body.
        port:     Server port from config or env.

    Returns:
        Parsed JSON response dict.

    Raises:
        SystemExit on connection failure or non-200 response.
    """
    import json
    import urllib.request
    import urllib.error

    url = f"http://localhost:{port}{endpoint}"
    data = json.dumps(payload).encode()

    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read())
    except urllib.error.URLError as e:
        print(
            f"ERROR: Could not reach the agent at {url}\n"
            f"Is MatrixMouse running? (matrixmouse run)\n"
            f"Details: {e.reason}"
        )
        sys.exit(1)


def _agent_get(endpoint: str, port: int) -> dict:
    """GET from the running agent's web server."""
    import json
    import urllib.request
    import urllib.error

    url = f"http://localhost:{port}{endpoint}"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            return json.loads(resp.read())
    except urllib.error.URLError as e:
        print(
            f"ERROR: Could not reach the agent at {url}\n"
            f"Is MatrixMouse running? (matrixmouse run)\n"
            f"Details: {e.reason}"
        )
        sys.exit(1)


def _resolve_port() -> int:
    """Read the server port from environment or fall back to default."""
    return int(os.environ.get("MM_SERVER_PORT", "8080"))


# ---------------------------------------------------------------------------
# cmd_interject
# ---------------------------------------------------------------------------

def cmd_interject(args):
    """
    Send a message to the running agent.

    The message is injected into the agent loop at the next iteration
    boundary. If --repo is given, the message is scoped to that repo's
    context. Without --repo, the message goes to the workspace-level queue.

    The agent will see the message as a user interjection and can
    respond to it before continuing its current task.
    """
    port = _resolve_port()
    message = args.message
    repo = getattr(args, "repo", None)

    payload = {"message": message}
    if repo:
        payload["repo"] = repo

    result = _agent_post("/interject", payload, port)

    if result.get("ok"):
        scope = f"repo '{repo}'" if repo else "workspace"
        print(f"Message sent to agent ({scope}).")
    else:
        print(f"ERROR: Agent rejected the message: {result.get('error', 'unknown error')}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# cmd_status
# ---------------------------------------------------------------------------

def cmd_status(args):
    """
    Show the current agent status — task, phase, model, and blocked tasks.
    """
    port = _resolve_port()
    status = _agent_get("/status", port)

    if "error" in status:
        print(f"ERROR: {status['error']}")
        sys.exit(1)

    task    = status.get("task")    or "—"
    phase   = status.get("phase")   or "—"
    model   = status.get("model")   or "—"
    turns   = status.get("turns")
    blocked = status.get("blocked", False)

    print(f"Task:    {task}")
    print(f"Phase:   {phase}")
    print(f"Model:   {model}")
    if turns is not None:
        print(f"Turns:   {turns}")
    print(f"Blocked: {'yes' if blocked else 'no'}")





def _load_tasks_file() -> tuple["Path", list[dict]]:
    """
    Load tasks.json from the workspace with an exclusive file lock.
    Does not require the agent to be running — reads the file directly.
    Safe to call concurrently with a running agent.

    Returns:
        (tasks_file_path, list_of_raw_task_dicts)
    """
    workspace_root = _resolve_workspace()
    tasks_file = workspace_root / ".matrixmouse" / "tasks.json"

    if not tasks_file.exists():
        return tasks_file, []

    try:
        with locked_json(tasks_file) as (tasks, _):
            return tasks_file, list(tasks)
    except LockTimeoutError as e:
        print(f"ERROR: {e}")
        sys.exit(1)


def _save_tasks_file(tasks_file: "Path", tasks: list[dict]) -> None:
    """
    Write tasks back to tasks.json with an exclusive file lock.
    Safe to call concurrently with a running agent.
    """
    try:
        with locked_json(tasks_file) as (_, save):
            save(tasks)
    except LockTimeoutError as e:
        print(f"ERROR: {e}")
        sys.exit(1)


def _find_task(tasks: list[dict], task_id: str) -> dict | None:
    """Find a task by ID prefix match (allows short IDs like 'a1b2')."""
    exact = next((t for t in tasks if t.get("id") == task_id), None)
    if exact:
        return exact
    # Prefix match
    matches = [t for t in tasks if t.get("id", "").startswith(task_id)]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        ids = ", ".join(t["id"] for t in matches)
        print(f"Ambiguous ID '{task_id}' matches: {ids}")
        return None
    return None


def _fmt_task_row(t: dict) -> str:
    """Format a task as a single-line summary row."""
    status  = t.get("status", "pending")
    title   = t.get("title", "(no title)")
    tid     = t.get("id", "?")
    repo    = ", ".join(t.get("repo", [])) or "—"
    imp     = t.get("importance", 0.5)
    urg     = t.get("urgency", 0.5)
    blocked = " [BLOCKED]" if "blocked" in status else ""
    return f"[{tid}] {title}{blocked}  repo={repo}  i={imp} u={urg}  ({status})"


def _fmt_task_detail(t: dict) -> str:
    """Format a task as a full detail block."""
    lines = [
        f"ID:           {t.get('id', '?')}",
        f"Title:        {t.get('title', '')}",
        f"Status:       {t.get('status', 'pending')}",
        f"Phase:        {t.get('phase', '?')}",
        f"Repo:         {', '.join(t.get('repo', [])) or '—'}",
        f"Importance:   {t.get('importance', 0.5)}",
        f"Urgency:      {t.get('urgency', 0.5)}",
        f"Created:      {t.get('created_at', '?')}",
    ]
    if t.get("target_files"):
        lines.append(f"Target files: {', '.join(t['target_files'])}")
    if t.get("blocked_by"):
        lines.append(f"Blocked by:   {', '.join(t['blocked_by'])}")
    if t.get("blocking"):
        lines.append(f"Blocking:     {', '.join(t['blocking'])}")
    if t.get("parent_task"):
        lines.append(f"Parent:       {t['parent_task']}")
    if t.get("subtasks"):
        lines.append(f"Subtasks:     {', '.join(t['subtasks'])}")
    if t.get("notes"):
        lines.append(f"\nNotes:\n{t['notes']}")
    if t.get("description"):
        lines.append(f"\nDescription:\n{t['description']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# cmd_tasks dispatcher
# ---------------------------------------------------------------------------

def cmd_tasks(args):
    """Route to the appropriate tasks subcommand."""
    subcmd = getattr(args, "tasks_subcmd", None)
    dispatch = {
        "list":   cmd_tasks_list,
        "show":   cmd_tasks_show,
        "add":    cmd_tasks_add,
        "edit":   cmd_tasks_edit,
        "cancel": cmd_tasks_cancel,
    }
    if subcmd not in dispatch:
        print("Usage: matrixmouse tasks <list|show|add|edit|cancel>")
        sys.exit(1)
    dispatch[subcmd](args)


def cmd_tasks_list(args):
    """
    List tasks in the queue.

    Filters:
        --status:  pending, active, blocked_by_task, blocked_by_human,
                   complete, cancelled. Default: all non-terminal.
        --repo:    Filter by repo name.
        --all:     Include terminal (complete/cancelled) tasks.
    """
    _, tasks = _load_tasks_file()

    if not tasks:
        print("No tasks found. Add one with: matrixmouse tasks add")
        return

    status_filter = getattr(args, "status", None)
    repo_filter   = getattr(args, "repo", None)
    show_all      = getattr(args, "all", False)

    terminal = {"complete", "cancelled"}
    filtered = tasks

    if not show_all and not status_filter:
        filtered = [t for t in filtered if t.get("status", "pending") not in terminal]

    if status_filter:
        filtered = [t for t in filtered if t.get("status") == status_filter]

    if repo_filter:
        filtered = [t for t in filtered if repo_filter in t.get("repo", [])]

    if not filtered:
        print("No tasks match the filter.")
        return

    # Sort by priority score approximation (importance * 0.6 + urgency * 0.4)
    filtered.sort(
        key=lambda t: t.get("importance", 0.5) * 0.6 + t.get("urgency", 0.5) * 0.4,
        reverse=True,
    )

    for t in filtered:
        print(_fmt_task_row(t))

    print(f"\n{len(filtered)} task(s) shown.")


def cmd_tasks_show(args):
    """Show full details of a single task."""
    _, tasks = _load_tasks_file()

    task = _find_task(tasks, args.id)
    if task is None:
        print(f"ERROR: Task '{args.id}' not found.")
        sys.exit(1)

    print(_fmt_task_detail(task))


def cmd_tasks_add(args):
    """
    Interactively create a new task and append it to tasks.json.
    Prompts for essential fields only — dependency links can be set
    later with 'matrixmouse tasks edit'.
    """
    import uuid
    from datetime import datetime, timezone

    workspace_root = _resolve_workspace()
    tasks_file, tasks = _load_tasks_file()

    print("Adding a new task. Press Ctrl+C to cancel.\n")

    # Discover registered repos for the prompt hint
    repos_file = workspace_root / ".matrixmouse" / "repos.json"
    known_repos = []
    if repos_file.exists():
        with open(repos_file) as f:
            known_repos = [r.get("name", "") for r in json.load(f)]
    repo_hint = f" (known: {', '.join(known_repos)})" if known_repos else ""

    title = input(f"Title: ").strip()
    if not title:
        print("Aborted — title is required.")
        sys.exit(1)

    print("Description (end with a line containing only '.'):")
    desc_lines = []
    while True:
        line = input()
        if line == ".":
            break
        desc_lines.append(line)
    description = "\n".join(desc_lines).strip()

    repo_input = input(f"Repo{repo_hint} (comma-separated, or leave blank): ").strip()
    repo = [r.strip() for r in repo_input.split(",") if r.strip()] if repo_input else []

    files_input = input("Target files (comma-separated, or leave blank): ").strip()
    target_files = [f.strip() for f in files_input.split(",") if f.strip()] if files_input else []

    try:
        importance = float(input("Importance 0.0-1.0 [0.5]: ").strip() or "0.5")
        importance = max(0.0, min(1.0, importance))
    except ValueError:
        importance = 0.5

    try:
        urgency = float(input("Urgency 0.0-1.0 [0.5]: ").strip() or "0.5")
        urgency = max(0.0, min(1.0, urgency))
    except ValueError:
        urgency = 0.5

    task = {
        "id": str(uuid.uuid4())[:8],
        "title": title,
        "description": description,
        "repo": repo,
        "phase": "DESIGN",
        "status": "pending",
        "target_files": target_files,
        "notes": "",
        "blocked_by": [],
        "blocking": [],
        "parent_task": None,
        "subtasks": [],
        "importance": importance,
        "urgency": urgency,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "started_at": None,
        "completed_at": None,
        "source": "local",
    }

    tasks.append(task)
    _save_tasks_file(tasks_file, tasks)

    print(f"\nTask created: [{task['id']}] {title}")
    print(f"Saved to: {tasks_file}")


def cmd_tasks_edit(args):
    """
    Edit mutable fields of an existing task.

    Editable fields: title, description, importance, urgency,
    target_files, repo, notes.

    Non-editable via this command: status, phase, dependency links
    (managed by the agent or orchestrator).
    """
    tasks_file, tasks = _load_tasks_file()

    task = _find_task(tasks, args.id)
    if task is None:
        print(f"ERROR: Task '{args.id}' not found.")
        sys.exit(1)

    print(f"Editing task [{task['id']}]: {task.get('title', '')}")
    print("Press Enter to keep current value. Press Ctrl+C to cancel.\n")

    EDITABLE = [
        ("title",        "Title",        str),
        ("description",  "Description",  str),
        ("importance",   "Importance",   float),
        ("urgency",      "Urgency",      float),
        ("notes",        "Notes",        str),
    ]

    for field, label, ftype in EDITABLE:
        current = task.get(field, "")
        display = str(current)[:60] + ("..." if len(str(current)) > 60 else "")
        new_val = input(f"{label} [{display}]: ").strip()
        if not new_val:
            continue
        try:
            if ftype == float:
                task[field] = max(0.0, min(1.0, float(new_val)))
            else:
                task[field] = new_val
        except ValueError:
            print(f"  Invalid value for {label}, keeping current.")

    # Repo edit
    current_repo = ", ".join(task.get("repo", []))
    new_repo = input(f"Repo [{current_repo}]: ").strip()
    if new_repo:
        task["repo"] = [r.strip() for r in new_repo.split(",") if r.strip()]

    # Target files edit
    current_files = ", ".join(task.get("target_files", []))
    new_files = input(f"Target files [{current_files}]: ").strip()
    if new_files:
        task["target_files"] = [f.strip() for f in new_files.split(",") if f.strip()]

    _save_tasks_file(tasks_file, tasks)
    print(f"\nTask [{task['id']}] updated.")


def cmd_tasks_cancel(args):
    """Cancel a task, setting its status to 'cancelled'."""
    from datetime import datetime, timezone

    tasks_file, tasks = _load_tasks_file()

    task = _find_task(tasks, args.id)
    if task is None:
        print(f"ERROR: Task '{args.id}' not found.")
        sys.exit(1)

    current_status = task.get("status", "pending")
    if current_status in ("complete", "cancelled"):
        print(f"Task [{task['id']}] is already {current_status}.")
        return

    confirm = input(
        f"Cancel task [{task['id']}] '{task.get('title', '')}'? [y/N]: "
    ).strip().lower()

    if confirm != "y":
        print("Aborted.")
        return

    task["status"] = "cancelled"
    task["completed_at"] = datetime.now(timezone.utc).isoformat()

    _save_tasks_file(tasks_file, tasks)
    print(f"Task [{task['id']}] cancelled.")


# ---------------------------------------------------------------------------
# cmd_answer
# ---------------------------------------------------------------------------

def cmd_answer(args):
    """
    Answer a pending clarification request from the agent.

    First fetches the pending question from the running agent so you
    know what you're replying to, then sends your reply as an interjection
    routed to the blocking wait in request_clarification().
    """
    port = _resolve_port()

    # Fetch the pending question
    pending = _agent_get("/pending", port)
    question = pending.get("pending")

    if not question:
        print("No pending clarification request from the agent.")
        print("Use 'matrixmouse interject' to send an unsolicited message.")
        return

    print(f"Agent is asking:\n\n  {question}\n")

    try:
        reply = input("Your answer: ").strip()
    except (KeyboardInterrupt, EOFError):
        print("\nAborted.")
        return

    if not reply:
        print("Aborted — reply cannot be empty.")
        return

    # Send as a workspace-wide interjection — clarification replies
    # are always workspace-wide since the agent is blocked waiting for them
    result = _agent_post("/interject", {"message": reply, "repo": None}, port)

    if result.get("ok"):
        print("Reply sent to agent.")
    else:
        print(f"ERROR: {result.get('error', 'unknown error')}")
        sys.exit(1)




# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="matrixmouse",
        description="Autonomous coding agent.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # --- init ---
    init_parser = subparsers.add_parser(
        "init",
        help="Initialise MatrixMouse in a repo directory.",
    )
    init_parser.add_argument(
        "--repo",
        metavar="NAME_OR_PATH",
        help="Repo subdirectory name or path. Defaults to current directory.",
    )
    init_parser.set_defaults(func=cmd_init)

    # --- run ---
    run_parser = subparsers.add_parser(
        "run",
        help="Start the agent.",
    )
    run_parser.add_argument(
        "--repo",
        metavar="NAME_OR_PATH",
        help="Repo to run against. Defaults to current directory.",
    )
    run_parser.set_defaults(func=cmd_run)

    # --- add-repo ---
    add_parser = subparsers.add_parser(
        "add-repo",
        help="Clone or register a repo into the workspace.",
    )
    add_parser.add_argument(
        "remote",
        metavar="URL_OR_PATH",
        help=(
            "Remote URL or local path. Examples:\n"
            "  git@github.com:you/repo.git\n"
            "  https://github.com/you/repo\n"
            "  /path/to/local/repo"
        ),
    )
    add_parser.add_argument(
        "--name",
        metavar="NAME",
        help="Override the directory name in the workspace. Defaults to repo name.",
    )
    add_parser.set_defaults(func=cmd_add_repo)

    

    # --- tasks ---
    tasks_parser = subparsers.add_parser(
        "tasks",
        help="View and manage the task queue.",
    )
    tasks_subparsers = tasks_parser.add_subparsers(
        dest="tasks_subcmd",
        required=True,
    )
    tasks_parser.set_defaults(func=cmd_tasks)

    # tasks list
    tlist = tasks_subparsers.add_parser("list", help="List tasks.")
    tlist.add_argument("--status", help="Filter by status.")
    tlist.add_argument("--repo",   help="Filter by repo name.")
    tlist.add_argument("--all",    action="store_true",
                       help="Include completed and cancelled tasks.")

    # tasks show
    tshow = tasks_subparsers.add_parser("show", help="Show task details.")
    tshow.add_argument("id", metavar="ID", help="Task ID (or prefix).")

    # tasks add
    tasks_subparsers.add_parser("add", help="Create a new task interactively.")

    # tasks edit
    tedit = tasks_subparsers.add_parser("edit", help="Edit a task.")
    tedit.add_argument("id", metavar="ID", help="Task ID (or prefix).")

    # tasks cancel
    tcancel = tasks_subparsers.add_parser("cancel", help="Cancel a task.")
    tcancel.add_argument("id", metavar="ID", help="Task ID (or prefix).")

    # --- answer ---
    subparsers.add_parser(
        "answer",
        help="Answer a pending clarification request from the agent.",
    ).set_defaults(func=cmd_answer)



    # --- interject ---
    interject_parser = subparsers.add_parser(
        "interject",
        help="Send a message to the running agent.",
    )
    interject_parser.add_argument(
        "message",
        metavar="MESSAGE",
        help="Message to send to the agent.",
    )
    interject_parser.add_argument(
        "--repo",
        metavar="NAME",
        help="Scope the message to a specific repo. Defaults to workspace-wide.",
    )
    interject_parser.set_defaults(func=cmd_interject)

    # --- status ---
    status_parser = subparsers.add_parser(
        "status",
        help="Show current agent status.",
    )
    status_parser.set_defaults(func=cmd_status)

    return parser


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
