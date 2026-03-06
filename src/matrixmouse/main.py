"""
matrixmouse/main.py

Entry point for MatrixMouse. Parses CLI arguments and dispatches to
the appropriate command.

All state-mutating commands communicate with the running MatrixMouse
service via its HTTP API (localhost). Commands that do not require a
running service (add-repo bootstrap, estop reset, upgrade) are handled
locally when the service is unreachable.

Commands:
    add-repo    Clone or register a repo into the workspace.
    tasks       View and manage the task queue (list/show/add/edit/cancel).
    interject   Send a message to the running agent.
    answer      Answer a pending clarification request from the agent.
    status      Show current agent status.
    stop        Soft stop — halt after the current tool call completes.
    kill        E-STOP — emergency shutdown, no automatic restart.
    estop       Manage the E-STOP lockfile (status / reset).
    pause       Pause orchestration — agent won't start new tasks.
    resume      Resume orchestration after a pause.
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

setup_logging(log_level="WARNING", log_to_file=False, repo_root=Path.cwd())
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Workspace resolution
# ---------------------------------------------------------------------------

def _resolve_workspace() -> Path:
    env = os.environ.get("WORKSPACE_PATH")
    if env:
        return Path(env).resolve()

    try:
        import tomllib
        global_cfg = Path("/etc/matrixmouse/config.toml")
        if global_cfg.exists():
            with open(global_cfg, "rb") as f:
                data = tomllib.load(f)
            ws = data.get("workspace_path") or data.get("WORKSPACE_PATH")
            if ws:
                return Path(ws).resolve()
    except Exception:
        pass

    default = Path("/var/lib/matrixmouse-workspace")
    if default.exists():
        return default

    print(
        "ERROR: Could not resolve workspace path.\n"
        "Set WORKSPACE_PATH in your environment or in /etc/matrixmouse/config.toml"
    )
    sys.exit(1)


def _resolve_port() -> int:
    return int(os.environ.get("MM_SERVER_PORT", "8080"))


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _agent_post(endpoint: str, payload: dict, port: int) -> dict:
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
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read())
            detail = body.get("detail", str(e))
        except Exception:
            detail = str(e)
        print(f"ERROR: {detail}")
        sys.exit(1)
    except urllib.error.URLError as e:
        print(
            f"ERROR: Could not reach the MatrixMouse service at {url}\n"
            f"Is the service running?  sudo systemctl status matrixmouse\n"
            f"Details: {e.reason}"
        )
        sys.exit(1)


def _agent_get(endpoint: str, port: int) -> dict:
    import urllib.request
    import urllib.error

    url = f"http://localhost:{port}{endpoint}"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read())
            detail = body.get("detail", str(e))
        except Exception:
            detail = str(e)
        print(f"ERROR: {detail}")
        sys.exit(1)
    except urllib.error.URLError as e:
        print(
            f"ERROR: Could not reach the MatrixMouse service at {url}\n"
            f"Is the service running?  sudo systemctl status matrixmouse\n"
            f"Details: {e.reason}"
        )
        sys.exit(1)


def _agent_patch(endpoint: str, payload: dict, port: int) -> dict:
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
# Mirror helpers
# ---------------------------------------------------------------------------

def _mirrors_base() -> Path:
    import getpass
    base = Path("/var/lib/matrixmouse-mirrors") / getpass.getuser()
    if not base.exists():
        base.mkdir(mode=0o750, parents=True)
    return base


def _setup_local_mirror(source: Path, name: str) -> Path:
    import subprocess

    mirror_path = _mirrors_base() / f"{name}.git"

    if mirror_path.exists():
        result = subprocess.run(
            ["git", "remote", "update"],
            cwd=mirror_path, capture_output=True, text=True,
        )
        if result.returncode != 0:
            print(f"Warning: could not update existing mirror: {result.stderr.strip()}")
        return mirror_path

    result = subprocess.run(
        ["git", "clone", "--bare", str(source), str(mirror_path)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"ERROR: Could not create mirror:\n{result.stderr.strip()}")
        sys.exit(1)

    import subprocess as sp
    sp.run(["chmod", "-R", "g+rX", str(mirror_path)], check=True)
    sp.run(
        ["git", "remote", "remove", "origin"],
        cwd=mirror_path, capture_output=True, text=True,
    )

    return mirror_path


def _add_matrixmouse_remote(working_copy: Path, mirror_path: Path) -> None:
    import subprocess

    result = subprocess.run(
        ["git", "remote", "get-url", "matrixmouse"],
        cwd=working_copy, capture_output=True, text=True,
    )
    if result.returncode == 0:
        subprocess.run(
            ["git", "remote", "set-url", "matrixmouse", str(mirror_path)],
            cwd=working_copy, check=True,
        )
    else:
        subprocess.run(
            ["git", "remote", "add", "matrixmouse", str(mirror_path)],
            cwd=working_copy, check=True,
        )


# ---------------------------------------------------------------------------
# cmd_add_repo
# ---------------------------------------------------------------------------

def cmd_add_repo(args):
    port = _resolve_port()
    remote = args.remote
    name = getattr(args, "name", None)

    local_path = Path(remote)
    is_local = remote.startswith("/") or remote.startswith("./") or remote.startswith("~/")
    if is_local:
        local_path = local_path.expanduser().resolve()
        if not local_path.exists():
            print(f"ERROR: Path does not exist: {local_path}")
            sys.exit(1)
        if not local_path.is_dir():
            print(f"ERROR: Not a directory: {local_path}")
            sys.exit(1)
        if not name:
            name = local_path.name

        print(f"Creating mirror of '{local_path}' ...")
        mirror_path = _setup_local_mirror(local_path, name)
        print(f"Mirror ready at {mirror_path}")
        api_remote = f"file://{mirror_path}"
    else:
        api_remote = remote

    try:
        result = _agent_post("/repos", {"remote": api_remote, "name": name}, port)
        if result.get("ok"):
            repo = result["repo"]
            print(f"Repo '{repo['name']}' added to workspace.")

            if is_local:
                try:
                    _add_matrixmouse_remote(local_path, mirror_path)
                    print(
                        f"\nRemote 'matrixmouse' added to {local_path}\n"
                        f"  git push matrixmouse    — share your work with the agent\n"
                        f"  git fetch matrixmouse   — pull agent commits back"
                    )
                except Exception as e:
                    print(f"Warning: could not add matrixmouse remote: {e}")

            _post_add_instructions(repo["name"], Path(repo["local_path"]))
        else:
            print(f"ERROR: {result.get('detail', 'unknown error')}")
            sys.exit(1)
    except SystemExit as e:
        if e.code != 0:
            raise


def _infer_repo_name(remote: str) -> str:
    name = remote.rstrip("/").rsplit("/", 1)[-1]
    return name[:-4] if name.endswith(".git") else name


def _register_repo(workspace_root: Path, name: str, local_path: Path, remote: str) -> None:
    from datetime import datetime, timezone

    repos_file = workspace_root / ".matrixmouse" / "repos.json"
    repos_file.parent.mkdir(parents=True, exist_ok=True)

    repos = []
    if repos_file.exists():
        with open(repos_file) as f:
            repos = json.load(f)

    if any(r.get("name") == name for r in repos):
        return

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
# cmd_repos_list
# ---------------------------------------------------------------------------

def cmd_repos_list(args):
    port = _resolve_port()
    try:
        result = _agent_get("/repos", port)
        repos = result.get("repos", [])
        if not repos:
            print("No repos registered.")
            return
        for r in repos:
            print(f"  {r['name']:20s}  {r['local_path']}")
            if r.get("remote"):
                print(f"  {'':20s}  remote: {r['remote']}")
    except SystemExit:
        workspace = _resolve_workspace()
        repos_file = workspace / ".matrixmouse" / "repos.json"
        if not repos_file.exists():
            print("No repos registered.")
            return
        with open(repos_file) as f:
            repos = json.load(f)
        if not repos:
            print("No repos registered.")
            return
        for r in repos:
            print(f"  {r['name']:20s}  {r['local_path']}")


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
    port = _resolve_port()
    result = _agent_get(f"/tasks/{args.id}", port)
    print(_fmt_task_detail(result))


def cmd_tasks_add(args):
    port = _resolve_port()

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

    result = _agent_post("/tasks", {
        "title": title, "description": description, "repo": repo,
        "target_files": target_files, "importance": importance, "urgency": urgency,
    }, port)
    print(f"\nTask created: [{result['id']}] {result['title']}")
    print("The agent will pick it up shortly.")


def cmd_tasks_edit(args):
    port = _resolve_port()
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
    port = _resolve_port()
    task = _agent_get(f"/tasks/{args.id}", port)
    title = task.get("title", "")

    confirm = input(f"Cancel task [{task['id']}] '{title}'? [y/N]: ").strip().lower()
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
    port = _resolve_port()
    result = _agent_get("/orchestrator/status", port)
    status  = result.get("status", {})
    paused  = result.get("paused", False)
    stopped = result.get("stopped", False)

    task    = status.get("task")  or "—"
    phase   = status.get("phase") or "—"
    model   = status.get("model") or "—"
    turns   = status.get("turns")
    blocked = status.get("blocked", False)
    idle    = status.get("idle", True)

    state = "PAUSED" if paused else "STOPPED" if stopped else \
            "BLOCKED" if blocked else "idle" if idle else "running"

    print(f"Status:  {state}")
    print(f"Task:    {task}")
    print(f"Phase:   {phase}")
    print(f"Model:   {model}")
    if turns is not None:
        print(f"Turns:   {turns}")
    if paused:
        print("\nOrchestrator is paused. Use 'matrixmouse resume' to continue.")


# ---------------------------------------------------------------------------
# cmd_stop  (soft stop)
# ---------------------------------------------------------------------------

def cmd_stop(args):
    """Request a soft stop — agent halts after the current tool call."""
    port = _resolve_port()
    result = _agent_post("/stop", {}, port)
    if result.get("ok"):
        print("Soft stop requested. Agent will halt after the current tool call.")
        print("Use 'matrixmouse status' to confirm it has stopped.")
    else:
        print(f"ERROR: {result.get('message', 'unknown error')}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# cmd_kill  (E-STOP)
# ---------------------------------------------------------------------------

def cmd_kill(args):
    """Emergency stop — writes ESTOP lockfile and shuts down immediately."""
    port = _resolve_port()

    if not getattr(args, "yes", False):
        print("WARNING: This will immediately shut down MatrixMouse.")
        print("The agent will stop mid-task and may leave work in an inconsistent state.")
        print("The service will NOT restart automatically.")
        print()
        confirm = input("Type 'ESTOP' to confirm: ").strip()
        if confirm != "ESTOP":
            print("Aborted.")
            return

    try:
        _agent_post("/kill", {}, port)
        print("E-STOP engaged. Service is shutting down.")
    except SystemExit:
        # Service shut down before responding — expected.
        print("E-STOP signal sent. Service shut down before responding.")

    print()
    print("To reset and restart:")
    print("  matrixmouse estop reset")
    print("  sudo systemctl start matrixmouse")


# ---------------------------------------------------------------------------
# cmd_estop
# ---------------------------------------------------------------------------

def cmd_estop(args):
    subcmd = getattr(args, "estop_subcmd", None)
    if subcmd == "status":
        cmd_estop_status(args)
    elif subcmd == "reset":
        cmd_estop_reset(args)
    else:
        print("Usage: matrixmouse estop <status|reset>")
        sys.exit(1)


def cmd_estop_status(args):
    """Check whether E-STOP is currently engaged."""
    port = _resolve_port()
    try:
        result = _agent_get("/estop", port)
    except SystemExit:
        # Service not running — read lockfile directly (normal post-ESTOP state)
        workspace = _resolve_workspace()
        lockfile  = workspace / ".matrixmouse" / "ESTOP"
        if lockfile.exists():
            print("E-STOP: ENGAGED (service not running)")
            try:
                print(lockfile.read_text())
            except Exception:
                pass
        else:
            print("E-STOP: not engaged (service not running)")
        return

    if result.get("engaged"):
        print("E-STOP: ENGAGED")
        if result.get("message"):
            print(result["message"])
        print()
        print("To reset: matrixmouse estop reset")
        print("Then start: sudo systemctl start matrixmouse")
    else:
        print("E-STOP: not engaged")


def cmd_estop_reset(args):
    """
    Remove the ESTOP lockfile so the service can start again.
    Works whether or not the service is running — reads workspace directly
    when the service is down (the expected post-ESTOP state).
    """
    port = _resolve_port()

    try:
        result = _agent_post("/estop/reset", {}, port)
        print(result.get("message", "E-STOP reset."))
    except SystemExit:
        # Service is down — direct lockfile removal.
        workspace = _resolve_workspace()
        lockfile  = workspace / ".matrixmouse" / "ESTOP"
        if not lockfile.exists():
            print("E-STOP was not engaged.")
            return
        try:
            lockfile.unlink()
            print("E-STOP reset.")
        except Exception as e:
            print(f"ERROR: Could not remove lockfile: {e}")
            print(f"Remove manually: rm {lockfile}")
            sys.exit(1)

    print("Start the service to resume: sudo systemctl start matrixmouse")


# ---------------------------------------------------------------------------
# cmd_pause / cmd_resume
# ---------------------------------------------------------------------------

def cmd_pause(args):
    """Pause the orchestrator — prevent it from starting new tasks."""
    port = _resolve_port()
    result = _agent_post("/orchestrator/pause", {}, port)
    print(result.get("message", "Orchestrator paused."))


def cmd_resume(args):
    """Resume the orchestrator after a pause."""
    port = _resolve_port()
    result = _agent_post("/orchestrator/resume", {}, port)
    print(result.get("message", "Orchestrator resumed."))


# ---------------------------------------------------------------------------
# cmd_upgrade
# ---------------------------------------------------------------------------

def cmd_upgrade(args):
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
    port   = _resolve_port()
    repo   = getattr(args, "repo", None)
    commit = getattr(args, "commit", False)

    raw = args.value
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
        endpoint = f"/config/repos/{repo}"
        if commit:
            endpoint += "?commit=true"
        result = _agent_patch(endpoint, payload, port)
        scope = f"repo '{repo}'" + (" (committed)" if commit else " (local)")
    else:
        result = _agent_patch("/config", payload, port)
        scope = "workspace"

    if result.get("ok"):
        print(f"Set {args.key} = {value!r} in {scope} config.")
        if "path" in result:
            print(f"  Written to: {result['path']}")
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
        "add-repo", help="Clone or register a repo into the workspace.",
    )
    add_parser.add_argument("remote", metavar="URL_OR_PATH")
    add_parser.add_argument("--name", metavar="NAME")
    add_parser.set_defaults(func=cmd_add_repo)

    # --- repos list ---
    repos_p = subparsers.add_parser("repos", help="Manage registered repos.")
    repos_sub = repos_p.add_subparsers(dest="repos_command")
    repos_sub.add_parser("list", help="List registered repos.").set_defaults(func=cmd_repos_list)

    # --- tasks ---
    tasks_parser = subparsers.add_parser("tasks", help="View and manage the task queue.")
    tasks_sub = tasks_parser.add_subparsers(dest="tasks_subcmd", required=True)
    tasks_parser.set_defaults(func=cmd_tasks)

    tlist = tasks_sub.add_parser("list", help="List tasks.")
    tlist.add_argument("--status", help="Filter by status.")
    tlist.add_argument("--repo",   help="Filter by repo name.")
    tlist.add_argument("--all", action="store_true", help="Include completed/cancelled.")

    tshow = tasks_sub.add_parser("show", help="Show task details.")
    tshow.add_argument("id", metavar="ID")

    tasks_sub.add_parser("add", help="Create a new task interactively.")

    tedit = tasks_sub.add_parser("edit", help="Edit a task.")
    tedit.add_argument("id", metavar="ID")

    tcancel = tasks_sub.add_parser("cancel", help="Cancel a task.")
    tcancel.add_argument("id", metavar="ID")

    # --- interject ---
    inj = subparsers.add_parser("interject", help="Send a message to the running agent.")
    inj.add_argument("message", metavar="MESSAGE")
    inj.add_argument("--repo", metavar="NAME")
    inj.set_defaults(func=cmd_interject)

    # --- answer ---
    subparsers.add_parser(
        "answer", help="Answer a pending clarification request.",
    ).set_defaults(func=cmd_answer)

    # --- status ---
    subparsers.add_parser(
        "status", help="Show current agent status.",
    ).set_defaults(func=cmd_status)

    # --- stop ---
    subparsers.add_parser(
        "stop", help="Soft stop — halt after the current tool call completes.",
    ).set_defaults(func=cmd_stop)

    # --- kill ---
    kill_p = subparsers.add_parser(
        "kill", help="E-STOP — emergency shutdown, no automatic restart.",
    )
    kill_p.add_argument(
        "--yes", action="store_true", help="Skip confirmation prompt.",
    )
    kill_p.set_defaults(func=cmd_kill)

    # --- estop ---
    estop_parser = subparsers.add_parser("estop", help="Manage the E-STOP lockfile.")
    estop_sub = estop_parser.add_subparsers(dest="estop_subcmd", required=True)
    estop_parser.set_defaults(func=cmd_estop)
    estop_sub.add_parser("status", help="Check E-STOP state.").set_defaults(func=cmd_estop_status)
    estop_sub.add_parser("reset",  help="Remove ESTOP lockfile so service can start.").set_defaults(func=cmd_estop_reset)

    # --- pause ---
    subparsers.add_parser(
        "pause", help="Pause orchestration — agent won't start new tasks.",
    ).set_defaults(func=cmd_pause)

    # --- resume ---
    subparsers.add_parser(
        "resume", help="Resume orchestration after a pause.",
    ).set_defaults(func=cmd_resume)

    # --- upgrade ---
    subparsers.add_parser(
        "upgrade", help="Upgrade MatrixMouse and restart the service.",
    ).set_defaults(func=cmd_upgrade)

    # --- config ---
    config_parser = subparsers.add_parser("config", help="Read or set configuration values.")
    config_sub = config_parser.add_subparsers(dest="config_subcmd", required=True)
    config_parser.set_defaults(func=cmd_config)

    cget = config_sub.add_parser("get", help="Print config values.")
    cget.add_argument("key", metavar="KEY", nargs="?")
    cget.add_argument("--repo", metavar="NAME")

    cset = config_sub.add_parser("set", help="Set a config value.")
    cset.add_argument("key",   metavar="KEY")
    cset.add_argument("value", metavar="VALUE")
    cset.add_argument("--repo",   metavar="NAME")
    cset.add_argument("--commit", action="store_true", default=False)

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
