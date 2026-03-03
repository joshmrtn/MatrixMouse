"""
matrixmouse/main.py

Entry point for MatrixMouse. Parses CLI arguments and dispatches to
the appropriate command.

All state-mutating commands communicate with the running MatrixMouse
service via its HTTP API (localhost). Commands that do not require a
running service (add-repo bootstrap, upgrade) are handled locally.

Commands:
    add-repo    Clone or register a repo into the workspace.
    tasks       View and manage the task queue (list/show/add/edit/cancel).
    interject   Send a message to the running agent.
    answer      Answer a pending clarification request from the agent.
    status      Show current agent status.
    upgrade     Upgrade MatrixMouse and rebuild the test runner image.
    config      Read or set configuration values.

Service startup is handled by systemd, not by this CLI.
The service is managed with:
    sudo systemctl start|stop|restart|status matrixmouse
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from matrixmouse.utils.logging_utils import setup_logging

# ---------------------------------------------------------------------------
# Logging — minimal setup for CLI use. The service has its own logging config.
# ---------------------------------------------------------------------------
setup_logging(log_level="WARNING", log_to_file=False, repo_root=Path.cwd())
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Workspace resolution
# ---------------------------------------------------------------------------

def _resolve_workspace() -> Path:
    env = os.environ.get("WORKSPACE_PATH")
    if env:
        return Path(env).resolve()
    default = Path.home() / "matrixmouse-workspace"
    if default.exists():
        return default
    return Path.cwd().parent


def _resolve_port() -> int:
    return int(os.environ.get("MM_SERVER_PORT", "8080"))


# ---------------------------------------------------------------------------
# HTTP helpers — all CLI state commands go through the API
# ---------------------------------------------------------------------------

def _agent_post(endpoint: str, payload: dict, port: int) -> dict:
    """
    POST to the running agent's HTTP API.
    Exits with a clear error if the service is not reachable.
    """
    import urllib.request
    import urllib.error

    url = f"http://localhost:{port}{endpoint}"
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.URLError as e:
        print(
            f"ERROR: Could not reach the MatrixMouse service at {url}\n"
            f"Is the service running?  sudo systemctl status matrixmouse\n"
            f"Details: {e.reason}"
        )
        sys.exit(1)


def _agent_get(endpoint: str, port: int) -> dict:
    """GET from the running agent's HTTP API."""
    import urllib.request
    import urllib.error

    url = f"http://localhost:{port}{endpoint}"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.URLError as e:
        print(
            f"ERROR: Could not reach the MatrixMouse service at {url}\n"
            f"Is the service running?  sudo systemctl status matrixmouse\n"
            f"Details: {e.reason}"
        )
        sys.exit(1)


def _agent_patch(endpoint: str, payload: dict, port: int) -> dict:
    """PATCH to the running agent's HTTP API."""
    import urllib.request
    import urllib.error

    url = f"http://localhost:{port}{endpoint}"
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"},
        method="PATCH",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.URLError as e:
        print(
            f"ERROR: Could not reach the MatrixMouse service at {url}\n"
            f"Details: {e.reason}"
        )
        sys.exit(1)


def _agent_delete(endpoint: str, port: int) -> dict:
    """DELETE via the running agent's HTTP API."""
    import urllib.request
    import urllib.error

    url = f"http://localhost:{port}{endpoint}"
    req = urllib.request.Request(url, method="DELETE")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.URLError as e:
        print(
            f"ERROR: Could not reach the MatrixMouse service at {url}\n"
            f"Details: {e.reason}"
        )
        sys.exit(1)


# ---------------------------------------------------------------------------
# cmd_add_repo
# ---------------------------------------------------------------------------

def cmd_add_repo(args):
    """
    Clone or register a repo into the workspace.

    If the service is running, delegates to POST /repos so the agent
    is aware of the new repo immediately.

    If the service is not running (bootstrap case — first repo before
    the service has ever started), clones directly and registers in
    repos.json. This allows a user to set up the workspace before
    starting the service for the first time.
    """
    port = _resolve_port()

    # Try the API first
    try:
        result = _agent_post(
            "/repos",
            {"remote": args.remote, "name": getattr(args, "name", None)},
            port,
        )
        if result.get("ok"):
            repo = result["repo"]
            print(f"Repo '{repo['name']}' added to workspace.")
            _post_add_instructions(repo["name"], Path(repo["local_path"]))
        else:
            print(f"ERROR: {result.get('detail', 'unknown error')}")
            sys.exit(1)
        return
    except SystemExit:
        # Service not running — fall through to bootstrap path
        pass

    # Bootstrap path: service not running, do it directly
    print("Service not running — cloning directly (bootstrap mode).")
    _add_repo_direct(args)


def _add_repo_direct(args) -> None:
    """
    Clone and register a repo without a running service.
    Used for bootstrap (first install) only.
    """
    import subprocess

    workspace_root = _resolve_workspace()
    remote = args.remote
    local_path = Path(remote)
    is_local = local_path.exists() and local_path.is_dir()

    name = getattr(args, "name", None)
    if not name:
        name = local_path.name if is_local else _infer_repo_name(remote)

    dest = workspace_root / name
    workspace_root.mkdir(parents=True, exist_ok=True)

    if dest.exists():
        print(f"Directory '{dest}' already exists.")
        answer = input(
            "(u)pdate with git pull, (s)kip clone + register, or (a)bort? [u/s/a]: "
        ).strip().lower()
        if answer == "a":
            sys.exit(0)
        elif answer == "s":
            _register_repo(workspace_root, name, dest, remote)
            print(f"Registered '{name}'.")
            _post_add_instructions(name, dest)
            return
        elif answer == "u":
            result = subprocess.run(
                ["git", "pull"], cwd=dest, capture_output=True, text=True
            )
            if result.returncode != 0:
                print(f"ERROR: git pull failed:\n{result.stderr}")
                sys.exit(1)
            print(result.stdout.strip())
            _register_repo(workspace_root, name, dest, remote)
            _post_add_instructions(name, dest)
            return
        else:
            print("Unrecognised option. Aborted.")
            sys.exit(1)

    # Build SSH env if key is configured
    env = os.environ.copy()
    key_file = os.environ.get("MATRIXMOUSE_AGENT_GH_KEY_FILE")
    secrets_path = os.environ.get("SECRETS_PATH", str(Path.home() / ".matrixmouse-secrets"))
    if key_file:
        key_path = Path(secrets_path) / key_file
        if key_path.exists():
            env["GIT_SSH_COMMAND"] = (
                f"ssh -i {key_path} -o IdentitiesOnly=yes "
                f"-o StrictHostKeyChecking=accept-new"
            )

    src = str(local_path.resolve()) if is_local else remote
    print(f"Cloning '{src}' into '{dest}'...")
    result = subprocess.run(
        ["git", "clone", src, str(dest)],
        env=env, capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"ERROR: git clone failed:\n{result.stderr.strip()}")
        sys.exit(1)

    print("Cloned successfully.")

    # Auto-init
    try:
        from matrixmouse.init import setup_repo
        setup_repo(dest, workspace_root)
        print(f"Initialised .matrixmouse/ in {dest}")
    except Exception as e:
        print(f"Warning: auto-init failed ({e}). Run manually if needed.")

    _register_repo(workspace_root, name, dest, remote)
    _post_add_instructions(name, dest)


def _infer_repo_name(remote: str) -> str:
    name = remote.rstrip("/").rsplit("/", 1)[-1]
    return name[:-4] if name.endswith(".git") else name


def _register_repo(
    workspace_root: Path, name: str, local_path: Path, remote: str
) -> None:
    from datetime import datetime, timezone

    repos_file = workspace_root / ".matrixmouse" / "repos.json"
    repos_file.parent.mkdir(parents=True, exist_ok=True)

    repos = []
    if repos_file.exists():
        with open(repos_file) as f:
            repos = json.load(f)

    if any(r.get("name") == name for r in repos):
        return  # already registered

    repos.append({
        "name": name,
        "remote": remote,
        "local_path": str(local_path),
        "added": datetime.now(timezone.utc).date().isoformat(),
    })
    with open(repos_file, "w") as f:
        json.dump(repos, f, indent=2)


def _post_add_instructions(name: str, dest: Path) -> None:
    print(f"\nRepo '{name}' is ready at {dest}")
    print(f"\nNext steps:")
    print(f"  Add a task:   matrixmouse tasks add")
    print(f"  Check status: matrixmouse status")
    print(f"  Web UI:       http://localhost:{_resolve_port()}/")


# ---------------------------------------------------------------------------
# cmd_tasks
# ---------------------------------------------------------------------------

def cmd_tasks(args):
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
    """List tasks via GET /tasks."""
    port = _resolve_port()

    params = []
    if getattr(args, "status", None):
        params.append(f"status={args.status}")
    if getattr(args, "repo", None):
        params.append(f"repo={args.repo}")
    if getattr(args, "all", False):
        params.append("all=true")

    qs = ("?" + "&".join(params)) if params else ""
    result = _agent_get(f"/tasks{qs}", port)

    tasks = result.get("tasks", [])
    if not tasks:
        print("No tasks found. Add one with: matrixmouse tasks add")
        return

    for t in tasks:
        print(_fmt_task_row(t))

    print(f"\n{result.get('count', len(tasks))} task(s) shown.")


def cmd_tasks_show(args):
    """Show task details via GET /tasks/{id}."""
    port = _resolve_port()
    result = _agent_get(f"/tasks/{args.id}", port)
    print(_fmt_task_detail(result))


def cmd_tasks_add(args):
    """
    Create a task interactively, then POST to /tasks.
    Prompts for essential fields. The agent picks it up immediately
    via the condition variable notification in the API handler.
    """
    port = _resolve_port()

    # Show known repos as a hint
    try:
        repos_result = _agent_get("/repos", port)
        known_repos = [r.get("name", "") for r in repos_result.get("repos", [])]
    except SystemExit:
        known_repos = []
    repo_hint = f" (known: {', '.join(known_repos)})" if known_repos else ""

    print("Adding a new task. Press Ctrl+C to cancel.\n")

    title = input("Title: ").strip()
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

    payload = {
        "title": title,
        "description": description,
        "repo": repo,
        "target_files": target_files,
        "importance": importance,
        "urgency": urgency,
    }

    result = _agent_post("/tasks", payload, port)
    print(f"\nTask created: [{result['id']}] {result['title']}")
    print("The agent will pick it up shortly.")


def cmd_tasks_edit(args):
    """Edit a task interactively, then PATCH /tasks/{id}."""
    port = _resolve_port()

    # Fetch current values to show as defaults
    task = _agent_get(f"/tasks/{args.id}", port)

    print(f"Editing task [{task['id']}]: {task.get('title', '')}")
    print("Press Enter to keep current value. Press Ctrl+C to cancel.\n")

    updates = {}

    EDITABLE = [
        ("title",       "Title",       str),
        ("description", "Description", str),
        ("importance",  "Importance",  float),
        ("urgency",     "Urgency",     float),
        ("notes",       "Notes",       str),
    ]
    for field, label, ftype in EDITABLE:
        current = task.get(field, "")
        display = str(current)[:60] + ("..." if len(str(current)) > 60 else "")
        new_val = input(f"{label} [{display}]: ").strip()
        if not new_val:
            continue
        try:
            updates[field] = max(0.0, min(1.0, float(new_val))) if ftype == float else new_val
        except ValueError:
            print(f"  Invalid value for {label}, keeping current.")

    current_repo = ", ".join(task.get("repo", []))
    new_repo = input(f"Repo [{current_repo}]: ").strip()
    if new_repo:
        updates["repo"] = [r.strip() for r in new_repo.split(",") if r.strip()]

    current_files = ", ".join(task.get("target_files", []))
    new_files = input(f"Target files [{current_files}]: ").strip()
    if new_files:
        updates["target_files"] = [f.strip() for f in new_files.split(",") if f.strip()]

    if not updates:
        print("No changes made.")
        return

    result = _agent_patch(f"/tasks/{args.id}", updates, port)
    print(f"\nTask [{result['id']}] updated.")


def cmd_tasks_cancel(args):
    """Cancel a task via DELETE /tasks/{id}."""
    port = _resolve_port()

    # Fetch title for the confirmation prompt
    task = _agent_get(f"/tasks/{args.id}", port)
    title = task.get("title", "")

    confirm = input(
        f"Cancel task [{task['id']}] '{title}'? [y/N]: "
    ).strip().lower()
    if confirm != "y":
        print("Aborted.")
        return

    result = _agent_delete(f"/tasks/{args.id}", port)
    if result.get("ok"):
        print(f"Task [{args.id}] cancelled.")
    else:
        print(f"ERROR: {result.get('detail', 'unknown error')}")
        sys.exit(1)


def _fmt_task_row(t: dict) -> str:
    status  = t.get("status", "pending")
    title   = t.get("title", "(no title)")
    tid     = t.get("id", "?")
    repo    = ", ".join(t.get("repo", [])) or "—"
    imp     = t.get("importance", 0.5)
    urg     = t.get("urgency", 0.5)
    blocked = " [BLOCKED]" if "blocked" in status else ""
    return f"[{tid}] {title}{blocked}  repo={repo}  i={imp:.1f} u={urg:.1f}  ({status})"


def _fmt_task_detail(t: dict) -> str:
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
# cmd_interject
# ---------------------------------------------------------------------------

def cmd_interject(args):
    """Send a message to the running agent."""
    port = _resolve_port()
    payload = {"message": args.message}
    repo = getattr(args, "repo", None)
    if repo:
        payload["repo"] = repo

    result = _agent_post("/interject", payload, port)
    if result.get("ok"):
        scope = f"repo '{repo}'" if repo else "workspace"
        print(f"Message sent to agent ({scope}).")
    else:
        print(f"ERROR: {result.get('detail', 'unknown error')}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# cmd_answer
# ---------------------------------------------------------------------------

def cmd_answer(args):
    """Answer a pending clarification request from the agent."""
    port = _resolve_port()

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

    result = _agent_post("/interject", {"message": reply, "repo": None}, port)
    if result.get("ok"):
        print("Reply sent to agent.")
    else:
        print(f"ERROR: {result.get('detail', 'unknown error')}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# cmd_status
# ---------------------------------------------------------------------------

def cmd_status(args):
    """Show current agent status."""
    port = _resolve_port()
    status = _agent_get("/status", port)

    task    = status.get("task")  or "—"
    phase   = status.get("phase") or "—"
    model   = status.get("model") or "—"
    turns   = status.get("turns")
    blocked = status.get("blocked", False)
    idle    = status.get("idle", True)

    print(f"Status:  {'blocked' if blocked else 'idle' if idle else 'running'}")
    print(f"Task:    {task}")
    print(f"Phase:   {phase}")
    print(f"Model:   {model}")
    if turns is not None:
        print(f"Turns:   {turns}")


# ---------------------------------------------------------------------------
# cmd_upgrade
# ---------------------------------------------------------------------------

def cmd_upgrade(args):
    """
    Upgrade MatrixMouse to the latest version.

    Sends POST /upgrade to the running service, which handles the
    uv tool upgrade and Docker image rebuild. Then restarts the
    systemd service so the new version takes effect.
    """
    port = _resolve_port()

    print("Upgrading MatrixMouse...")
    result = _agent_post("/upgrade", {}, port)

    pkg = result.get("results", {}).get("package", {})
    tr  = result.get("results", {}).get("test_runner", {})

    print(f"\nPackage upgrade: {'ok' if pkg.get('ok') else 'FAILED'}")
    if pkg.get("output"):
        print(f"  {pkg['output']}")

    print(f"Test runner:     {'rebuilt' if tr.get('rebuilt') else tr.get('reason', 'unchanged')}")
    if tr.get("output"):
        print(f"  {tr['output']}")

    if not result.get("ok"):
        print("\nUpgrade encountered errors. Check output above.")
        sys.exit(1)

    # Restart the service so the new version loads
    print("\nRestarting service...")
    import subprocess
    restart = subprocess.run(
        ["sudo", "systemctl", "restart", "matrixmouse"],
        capture_output=True, text=True,
    )
    if restart.returncode == 0:
        print("Service restarted. MatrixMouse is now running the latest version.")
    else:
        print(
            "WARNING: Could not restart the service automatically.\n"
            "Restart manually with: sudo systemctl restart matrixmouse\n"
            f"Details: {restart.stderr.strip()}"
        )


# ---------------------------------------------------------------------------
# cmd_config
# ---------------------------------------------------------------------------

def cmd_config(args):
    subcmd = getattr(args, "config_subcmd", None)
    if subcmd == "get":
        cmd_config_get(args)
    elif subcmd == "set":
        cmd_config_set(args)
    else:
        print("Usage: matrixmouse config <get|set>")
        sys.exit(1)


def cmd_config_get(args):
    """Print current config values."""
    port = _resolve_port()
    repo = getattr(args, "repo", None)

    if repo:
        result = _agent_get(f"/config/repos/{repo}", port)
        print(f"Config for repo '{repo}':")
    else:
        result = _agent_get("/config", port)
        print("Workspace config:")

    if not result:
        print("  (empty — using defaults)")
        return

    key_filter = getattr(args, "key", None)
    for k, v in sorted(result.items()):
        if key_filter and k != key_filter:
            continue
        print(f"  {k} = {v!r}")


def cmd_config_set(args):
    """
    Set a config value via PATCH /config.

    Usage:
        matrixmouse config set coder qwen2.5-coder:14b
        matrixmouse config set --repo myrepo coder qwen2.5-coder:7b
    """
    port = _resolve_port()
    repo = getattr(args, "repo", None)

    # Coerce the value to the most sensible type
    raw = args.value
    value: str | int | float | bool
    if raw.lower() == "true":
        value = True
    elif raw.lower() == "false":
        value = False
    else:
        try:
            value = int(raw)
        except ValueError:
            try:
                value = float(raw)
            except ValueError:
                value = raw

    payload = {"values": {args.key: value}}

    if repo:
        result = _agent_patch(f"/config/repos/{repo}", payload, port)
    else:
        result = _agent_patch("/config", payload, port)

    if result.get("ok"):
        print(f"Set {args.key} = {value!r}")
        print(result.get("note", ""))
    else:
        print(f"ERROR: {result.get('detail', 'unknown error')}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="matrixmouse",
        description=(
            "Autonomous coding agent.\n\n"
            "The MatrixMouse service is managed by systemd:\n"
            "  sudo systemctl start|stop|restart|status matrixmouse"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # --- add-repo ---
    add_parser = subparsers.add_parser(
        "add-repo",
        help="Clone or register a repo into the workspace.",
    )
    add_parser.add_argument(
        "remote",
        metavar="URL_OR_PATH",
        help="Git remote URL or local path.",
    )
    add_parser.add_argument(
        "--name",
        metavar="NAME",
        help="Override directory name in workspace. Defaults to repo name.",
    )
    add_parser.set_defaults(func=cmd_add_repo)

    # --- tasks ---
    tasks_parser = subparsers.add_parser(
        "tasks",
        help="View and manage the task queue.",
    )
    tasks_sub = tasks_parser.add_subparsers(dest="tasks_subcmd", required=True)
    tasks_parser.set_defaults(func=cmd_tasks)

    tlist = tasks_sub.add_parser("list", help="List tasks.")
    tlist.add_argument("--status", help="Filter by status.")
    tlist.add_argument("--repo",   help="Filter by repo name.")
    tlist.add_argument("--all", action="store_true",
                       help="Include completed and cancelled tasks.")

    tshow = tasks_sub.add_parser("show", help="Show task details.")
    tshow.add_argument("id", metavar="ID", help="Task ID or prefix.")

    tasks_sub.add_parser("add", help="Create a new task interactively.")

    tedit = tasks_sub.add_parser("edit", help="Edit a task.")
    tedit.add_argument("id", metavar="ID", help="Task ID or prefix.")

    tcancel = tasks_sub.add_parser("cancel", help="Cancel a task.")
    tcancel.add_argument("id", metavar="ID", help="Task ID or prefix.")

    # --- interject ---
    inj = subparsers.add_parser(
        "interject",
        help="Send an unsolicited message to the running agent.",
    )
    inj.add_argument("message", metavar="MESSAGE")
    inj.add_argument(
        "--repo", metavar="NAME",
        help="Scope to a specific repo. Default: workspace-wide.",
    )
    inj.set_defaults(func=cmd_interject)

    # --- answer ---
    subparsers.add_parser(
        "answer",
        help="Answer a pending clarification request from the agent.",
    ).set_defaults(func=cmd_answer)

    # --- status ---
    subparsers.add_parser(
        "status",
        help="Show current agent status.",
    ).set_defaults(func=cmd_status)

    # --- upgrade ---
    subparsers.add_parser(
        "upgrade",
        help="Upgrade MatrixMouse and restart the service.",
    ).set_defaults(func=cmd_upgrade)

    # --- config ---
    config_parser = subparsers.add_parser(
        "config",
        help="Read or set configuration values.",
    )
    config_sub = config_parser.add_subparsers(dest="config_subcmd", required=True)
    config_parser.set_defaults(func=cmd_config)

    cget = config_sub.add_parser("get", help="Print config values.")
    cget.add_argument("key", metavar="KEY", nargs="?",
                      help="Specific key to read. Omit to show all.")
    cget.add_argument("--repo", metavar="NAME",
                      help="Read repo-level config instead of workspace.")

    cset = config_sub.add_parser("set", help="Set a config value.")
    cset.add_argument("key",   metavar="KEY",   help="Config key to set.")
    cset.add_argument("value", metavar="VALUE", help="New value.")
    cset.add_argument("--repo", metavar="NAME",
                      help="Set in repo-level config instead of workspace.")

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
