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
import subprocess
from pathlib import Path

from matrixmouse.utils.logging_utils import setup_logging

# Module-level constants
CONTEXT_MESSAGE_TRUNCATE_LENGTH = 500
DEFAULT_MESSAGE_LIMIT = 50

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
    """
    Resolve the API port from the global config file.
    Falls back to MM_SERVER_PORT env var, then 8080.
    The global config is readable by the matrixmouse group.
    """
    import tomllib
    global_config = Path("/etc/matrixmouse/config.toml")
    try:
        if global_config.exists():
            with open(global_config, "rb") as f:
                data = tomllib.load(f)
            if "server_port" in data:
                return int(data["server_port"])
    except PermissionError:
        print(
            "Warning: Cannot read /etc/matrixmouse/config.toml — "
            "you may need to log out and back in for group membership to take effect. "
            "Falling back to MM_SERVER_PORT or default 8080."
        )
    except Exception:
        pass
    return int(os.environ.get("MM_SERVER_PORT", "8080"))


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _agent_post(endpoint: str, payload: dict, port: int) -> dict:
    """
    POST to the running agent's HTTP API.
    Exits with clear error if service not reachable.
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
    """GET from the running agent's HTTP API."""
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


def _agent_get_params(endpoint: str, port: int, params: dict | None = None) -> dict:
    """GET with query parameters."""
    import urllib.request
    import urllib.error
    import urllib.parse

    if params:
        qs = urllib.parse.urlencode(params)
        endpoint = f"{endpoint}?{qs}"
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


# ---------------------------------------------------------------------------
# Mirror helpers
# ---------------------------------------------------------------------------

def _mirrors_base() -> Path:
    """
    Per-user mirror directory under /var/lib/matrixmouse-mirrors.
    Created on first use, owned by the invoking user, group-readable
    by matrixmouse via the matrixmouse-mirrors group.
    """
    import getpass
    base = Path("/var/lib/matrixmouse-mirrors") / getpass.getuser()
    if not base.exists():
        base.mkdir(mode=0o750, parents=True)
    return base


def _setup_local_mirror(source: Path, name: str) -> Path:
    """
    Create a bare mirror of a local repo in the per-user mirrors directory.
    Runs as the invoking user — can read the source, owns the mirror.

    Args:
        source: Absolute path to the user's working repo.
        name:   Repo name (used as mirror directory name).

    Returns:
        Path to the bare mirror (e.g. /var/lib/matrixmouse-mirrors/ubuntu/name.git)
    """
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
    """
    Add or update the 'matrixmouse' remote in the user's working copy
    to point at the bare mirror.

    After this, the user can:
        git push matrixmouse          # share work with the agent
        git fetch matrixmouse         # pull agent commits back
    """
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
    """
    Clone or register a repo into the workspace.

    For remote URLs (https://, git@, etc.):
        Delegates to POST /repos — service clones directly.

    For local paths:
        1. CLI creates a bare mirror in /var/lib/matrixmouse-mirrors/<user>/
        2. CLI calls POST /repos with the file:// mirror URL
        3. Service clones from the mirror into the workspace
        4. CLI adds 'matrixmouse' remote to the user's working copy

    The 'matrixmouse' remote allows the user to share work with the agent:
        git push matrixmouse    # agent sees your latest commits
        git fetch matrixmouse   # you see the agent's commits
    """
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
    """List repos registered in the workspace."""
    port = _resolve_port()
    fmt = getattr(args, "format", "table")
    try:
        result = _agent_get("/repos", port)
        repos = result.get("repos", [])
    except SystemExit:
        workspace = _resolve_workspace()
        repos_file = workspace / ".matrixmouse" / "repos.json"
        if not repos_file.exists():
            repos = []
        else:
            with open(repos_file) as f:
                repos = json.load(f)

    if fmt == "json":
        print(json.dumps(repos, indent=2))
        return

    if not repos:
        print("No repos registered.")
        return
    for r in repos:
        print(f"  {r['name']:20s}  {r['local_path']}")
        if r.get("remote"):
            print(f"  {'':20s}  remote: {r['remote']}")


def cmd_repos_remove(args):
    """Remove a repo from the registry."""
    port = _resolve_port()
    name = args.name

    if not getattr(args, "yes", False):
        print(f"Remove repo '{name}' from the registry?")
        print("Note: This does NOT delete the cloned directory.")
        confirm = input("Confirm [y/N]: ").strip().lower()
        if confirm != "y":
            print("Aborted.")
            return

    result = _agent_delete(f"/repos/{name}", port)
    if result.get("ok"):
        print(f"Repo '{name}' removed from registry.")
    else:
        print(f"ERROR: {result.get('detail', 'unknown error')}")
        sys.exit(1)


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
    Create a task. Supports both interactive and non-interactive modes.

    Non-interactive mode:
        matrixmouse tasks add --title "..." --description "..." --repo repo1

    Interactive mode (default if no --title):
        Prompts for all fields.

    Description can be read from file with @filename, or stdin with @-.
    """
    port = _resolve_port()

    # Check if we're in non-interactive mode
    title = getattr(args, "title", None)

    try:
        repos_result = _agent_get("/repos", port)
        known_repos = [r.get("name", "") for r in repos_result.get("repos", [])]
    except SystemExit:
        known_repos = []

    if title is not None:
        # Non-interactive mode
        if not title.strip():
            print("ERROR: Title cannot be empty.")
            sys.exit(1)

        description = getattr(args, "description", "")
        # Handle @file or @- for description
        if description.startswith("@"):
            path_or_stdin = description[1:]
            if path_or_stdin == "-":
                description = sys.stdin.read()
            else:
                desc_path = Path(path_or_stdin).expanduser()
                if not desc_path.exists():
                    print(f"ERROR: Description file not found: {desc_path}")
                    sys.exit(1)
                description = desc_path.read_text()

        repo_input = getattr(args, "repo", None)
        repo = [r.strip() for r in repo_input.split(",") if r.strip()] if repo_input else []

        files_input = getattr(args, "target_files", None)
        target_files = [f.strip() for f in files_input.split(",") if f.strip()] if files_input else []

        importance = getattr(args, "importance", 0.5)
        urgency = getattr(args, "urgency", 0.5)
    else:
        # Interactive mode
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
    """
    Edit a task. Supports both interactive and non-interactive modes.

    Non-interactive mode:
        matrixmouse tasks edit <id> --title "..." --description "..."

    Interactive mode (default if no flags):
        Prompts for all editable fields.
    """
    port = _resolve_port()
    task = _agent_get(f"/tasks/{args.id}", port)

    updates = {}

    # Check for non-interactive flags
    title = getattr(args, "title", None)
    description = getattr(args, "description", None)
    importance = getattr(args, "importance", None)
    urgency = getattr(args, "urgency", None)
    notes = getattr(args, "notes", None)
    repo = getattr(args, "repo", None)
    target_files = getattr(args, "target_files", None)

    if any(v is not None for v in [title, description, importance, urgency, notes, repo, target_files]):
        # Non-interactive mode
        if title is not None:
            updates["title"] = title
        if description is not None:
            # Handle @file or @- for description
            if description.startswith("@"):
                path_or_stdin = description[1:]
                if path_or_stdin == "-":
                    description = sys.stdin.read()
                else:
                    desc_path = Path(path_or_stdin).expanduser()
                    if not desc_path.exists():
                        print(f"ERROR: Description file not found: {desc_path}")
                        sys.exit(1)
                    description = desc_path.read_text()
            updates["description"] = description
        if importance is not None:
            updates["importance"] = max(0.0, min(1.0, float(importance)))
        if urgency is not None:
            updates["urgency"] = max(0.0, min(1.0, float(urgency)))
        if notes is not None:
            updates["notes"] = notes
        if repo is not None:
            updates["repo"] = [r.strip() for r in repo.split(",") if r.strip()]
        if target_files is not None:
            updates["target_files"] = [f.strip() for f in target_files.split(",") if f.strip()]
    else:
        # Interactive mode
        print(f"Editing task [{task['id']}]: {task.get('title', '')}")
        print("Press Enter to keep current value. Press Ctrl+C to cancel.\n")

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
    task = _agent_get(f"/tasks/{args.id}", port)
    title = task.get("title", "")

    if not getattr(args, "yes", False):
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
        f"Role:         {t.get('role', '?')}",
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
# New monitoring commands
# ---------------------------------------------------------------------------

def cmd_blocked(args):
    """Show blocked and waiting tasks report."""
    port = _resolve_port()
    fmt = getattr(args, "format", "table")
    result = _agent_get("/blocked", port)
    report = result.get("report", [])

    if fmt == "json":
        print(json.dumps(report, indent=2))
        return

    if not report:
        print("No blocked or waiting tasks.")
        return

    for entry in report:
        task_id = entry.get("task_id", "?")
        title = entry.get("title", "")
        status = entry.get("status", "")
        reason = entry.get("reason", "")
        print(f"[{task_id}] {title}")
        print(f"  Status: {status}")
        print(f"  Reason: {reason}")
        if entry.get("note"):
            print(f"  Note:   {entry['note']}")
        print()


def cmd_token_usage(args):
    """Show token usage for remote providers."""
    port = _resolve_port()
    fmt = getattr(args, "format", "table")
    result = _agent_get("/token_usage", port)
    usage = result

    if fmt == "json":
        print(json.dumps(usage, indent=2))
        return

    print("Token Usage (rolling window):")
    print(f"  {'Provider':<12} {'Last Hour':>12} {'Last Day':>12}")
    print(f"  {'-'*12} {'-'*12} {'-'*12}")
    for provider, counts in usage.items():
        hour = counts.get("hour", 0)
        day = counts.get("day", 0)
        print(f"  {provider:<12} {hour:>12,} {day:>12,}")


def cmd_context(args):
    """Show context messages for a specific task via GET /tasks/{id}."""
    port = _resolve_port()
    fmt = getattr(args, "format", "table")
    task_id = args.id
    last = getattr(args, "last", None)
    show_all = getattr(args, "all", False)

    result = _agent_get(f"/tasks/{task_id}", port)

    # Validate task exists
    if not result or "id" not in result:
        print(f"ERROR: Task '{task_id}' not found.")
        sys.exit(1)

    messages = result.get("context_messages") or []
    title = result.get("title", "(no title)")
    total_messages = len(messages)

    # Apply --last limit or default limit
    if show_all:
        # Show all messages, no limit
        pass
    elif last is not None:
        # User-specified limit
        if last <= 0:
            print("ERROR: --last must be a positive integer.")
            sys.exit(1)
        messages = messages[-last:]
    elif total_messages > DEFAULT_MESSAGE_LIMIT:
        # Apply default limit and inform user
        print(f"Showing last {DEFAULT_MESSAGE_LIMIT} of {total_messages} messages. Use --all for full context.\n")
        messages = messages[-DEFAULT_MESSAGE_LIMIT:]

    if fmt == "json":
        print(json.dumps({
            "task_id": task_id,
            "title": title,
            "messages": messages,
            "count": len(messages),
            "total": total_messages,
            "truncated": not show_all and (last is not None or total_messages > DEFAULT_MESSAGE_LIMIT),
        }, indent=2))
        return

    print(f"Task [{task_id}]: {title}")
    print(f"Context Messages ({len(messages)} messages):\n")
    for msg in messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        # Handle both string content and block-based content
        if isinstance(content, list):
            # Block-based content (Anthropic format)
            for block in content:
                if isinstance(block, dict):
                    block_type = block.get("type", "unknown")
                    if block_type == "tool_use":
                        tool_name = block.get("name", "unknown")
                        tool_input = block.get("input", {})
                        print(f"[{role}/{block_type}:{tool_name}]: {tool_input or '(no input)'}")
                    else:
                        block_content = block.get("text", block.get("thinking", ""))
                        if block_content:
                            preview = block_content[:CONTEXT_MESSAGE_TRUNCATE_LENGTH] + "..." if len(block_content) > CONTEXT_MESSAGE_TRUNCATE_LENGTH else block_content
                            print(f"[{role}/{block_type}]: {preview}")
                elif isinstance(block, str):
                    # Handle string blocks
                    preview = block[:CONTEXT_MESSAGE_TRUNCATE_LENGTH] + "..." if len(block) > CONTEXT_MESSAGE_TRUNCATE_LENGTH else block
                    print(f"[{role}]: {preview}")
        elif isinstance(content, str):
            # String content (simpler format)
            preview = content[:CONTEXT_MESSAGE_TRUNCATE_LENGTH] + "..." if len(content) > CONTEXT_MESSAGE_TRUNCATE_LENGTH else content
            print(f"[{role}]: {preview}")
        print()


def cmd_health(args):
    """Check API health."""
    port = _resolve_port()
    try:
        result = _agent_get("/health", port)
        print(f"Health: OK")
        print(f"Timestamp: {result.get('timestamp', 'unknown')}")
    except SystemExit as e:
        if e.code != 0:
            print("Health: UNREACHABLE")
            sys.exit(1)


# ---------------------------------------------------------------------------
# cmd_interject (legacy - kept for backwards compatibility)
# ---------------------------------------------------------------------------

def cmd_interject(args):
    """Send a message to the running agent (legacy endpoint)."""
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
# Scoped interject commands (new)
# ---------------------------------------------------------------------------

def cmd_interject_workspace(args):
    """Send a workspace-scoped message to the Manager agent."""
    port = _resolve_port()
    result = _agent_post("/interject/workspace", {"message": args.message}, port)
    if result.get("ok"):
        print(f"Message sent to Manager (workspace-wide). Task ID: {result.get('manager_task_id')}")
    else:
        print(f"ERROR: {result.get('detail', 'unknown error')}")
        sys.exit(1)


def cmd_interject_repo(args):
    """Send a repo-scoped message to the Manager agent."""
    port = _resolve_port()
    result = _agent_post(f"/interject/repo/{args.repo}", {"message": args.message}, port)
    if result.get("ok"):
        print(f"Message sent to Manager (repo='{args.repo}'). Task ID: {result.get('manager_task_id')}")
    else:
        print(f"ERROR: {result.get('detail', 'unknown error')}")
        sys.exit(1)


def cmd_interject_task(args):
    """Send a message to a specific task's agent."""
    port = _resolve_port()
    result = _agent_post(f"/tasks/{args.id}/interject", {"message": args.message}, port)
    if result.get("ok"):
        print(f"Message sent to task [{args.id}].")
    else:
        print(f"ERROR: {result.get('detail', 'unknown error')}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# cmd_tasks_answer (answer a specific task's clarification)
# ---------------------------------------------------------------------------

def cmd_tasks_answer(args):
    """Answer a clarification question for a specific task."""
    port = _resolve_port()
    task_id = args.id
    message = getattr(args, "message", None)

    if message is None:
        # Interactive mode - fetch the pending question from the task
        task = _agent_get(f"/tasks/{task_id}", port)
        pending_question = task.get("pending_question", "")
        if not pending_question:
            print(f"No pending question for task [{task_id}].")
            return
        print(f"Task [{task_id}] is asking:\n\n  {pending_question}\n")
        try:
            reply = input("Your answer: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nAborted.")
            return
        if not reply:
            print("Aborted — reply cannot be empty.")
            return
        message = reply

    if not message.strip():
        print("ERROR: Message cannot be empty.")
        sys.exit(1)

    result = _agent_post(f"/tasks/{task_id}/answer", {"message": message}, port)
    if result.get("ok"):
        unblocked = result.get("unblocked", False)
        if unblocked:
            print(f"Answer sent to task [{task_id}]. Task unblocked and returned to queue.")
        else:
            print(f"Answer sent to task [{task_id}].")
    else:
        print(f"ERROR: {result.get('detail', 'unknown error')}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# cmd_tasks_decision
# ---------------------------------------------------------------------------

DECISION_TYPES = {
    "pr_approval_required": ["approve", "reject"],
    "pr_rejection": ["rework", "manual"],
    "turn_limit_reached": ["extend", "respec", "cancel"],
    "critic_turn_limit_reached": ["approve_task", "extend_critic", "block_task"],
    "merge_conflict_resolution_turn_limit_reached": ["extend", "abort"],
    "planning_turn_limit_reached": ["extend", "commit", "cancel"],
    "decomposition_confirmation_required": ["allow", "deny"],
}


def cmd_tasks_decision(args):
    """Submit a decision for a blocked task."""
    port = _resolve_port()
    task_id = args.id
    decision_type = args.decision_type
    choice = args.choice
    note = getattr(args, "note", "")

    # Validate decision type
    if decision_type not in DECISION_TYPES:
        print(f"ERROR: Unknown decision type '{decision_type}'.")
        print(f"Valid types: {', '.join(DECISION_TYPES.keys())}")
        sys.exit(1)

    # Validate choice
    valid_choices = DECISION_TYPES[decision_type]
    if choice not in valid_choices:
        print(f"ERROR: Invalid choice '{choice}' for '{decision_type}'.")
        print(f"Valid choices: {', '.join(valid_choices)}")
        sys.exit(1)

    # Build request payload
    payload = {
        "decision_type": decision_type,
        "choice": choice,
    }
    if note:
        payload["note"] = note

    # Add extend_by for turn_limit_reached if provided
    if decision_type == "turn_limit_reached":
        extend_by = getattr(args, "extend_by", 0)
        if extend_by:
            payload["metadata"] = {"extend_by": extend_by}

    result = _agent_post(f"/tasks/{task_id}/decision", payload, port)
    if result.get("ok"):
        action = result.get("action", "unknown")
        print(f"Decision submitted for task [{task_id}]: {decision_type} -> {choice}")
        print(f"Action taken: {action}")
        if result.get("pr_url"):
            print(f"PR created: {result['pr_url']}")
        if result.get("new_turn_limit"):
            print(f"New turn limit: {result['new_turn_limit']}")
    else:
        print(f"ERROR: {result.get('detail', 'unknown error')}")
        sys.exit(1)


def cmd_decisions_list(args):
    """List available decision types and their choices."""
    fmt = getattr(args, "format", "table")

    if fmt == "json":
        print(json.dumps(DECISION_TYPES, indent=2))
        return

    print("Decision Types and Choices:\n")
    for dtype, choices in DECISION_TYPES.items():
        print(f"  {dtype}:")
        for choice in choices:
            print(f"    - {choice}")
        print()


# ---------------------------------------------------------------------------
# cmd_status
# ---------------------------------------------------------------------------

def cmd_status(args):
    """Show current agent status."""
    port = _resolve_port()
    result = _agent_get("/orchestrator/status", port)
    status  = result.get("status", {})
    paused  = result.get("paused", False)
    stopped = result.get("stopped", False)

    task    = status.get("task")  or "—"
    role    = status.get("role") or "—"
    model   = status.get("model") or "—"
    turns   = status.get("turns")
    blocked = status.get("blocked", False)
    idle    = status.get("idle", True)

    state = "PAUSED" if paused else "STOPPED" if stopped else \
            "BLOCKED" if blocked else "idle" if idle else "running"

    print(f"Status:  {state}")
    print(f"Task:    {task}")
    print(f"Role:    {role}")
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
    workspace = _resolve_workspace()
    lockfile  = workspace / ".matrixmouse" / "ESTOP"
    if _sudo_needs_password():
        print("Checking E-STOP requires sudo privileges.")
    exists = subprocess.run(
        ["sudo", "test", "-f", str(lockfile)],
        capture_output=True,
    ).returncode == 0
    if exists:
        print("E-STOP: ENGAGED")
        content = subprocess.run(["sudo", "cat", str(lockfile)],
                                 capture_output=True, text=True)
        if content.returncode == 0:
            print(content.stdout.strip())
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
    workspace = _resolve_workspace()
    lockfile  = workspace / ".matrixmouse" / "ESTOP"
    if _sudo_needs_password():
        print("Resetting E-STOP requires sudo privileges.")
    exists = subprocess.run(
        ["sudo", "test", "-f", str(lockfile)],
        capture_output=True,
    ).returncode == 0
    if not exists:
        print("E-STOP is not engaged.")
        return
    result = subprocess.run(
        ["sudo", "rm", str(lockfile)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"ERROR: {result.stderr.strip() or 'Could not remove lockfile.'}")
        print(f"Remove manually: sudo rm {lockfile}")
        sys.exit(1)
    print("E-STOP reset.")
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
# sudoers helper
# ---------------------------------------------------------------------------

def _sudo_needs_password() -> bool:
    """Return True if sudo will prompt for a password."""
    return subprocess.run(
            ["sudo", "-n", "true"], capture_output=True
            ).returncode != 0

# ---------------------------------------------------------------------------
# cmd_upgrade
# ---------------------------------------------------------------------------

def cmd_upgrade(args):
    """
    Upgrade MatrixMouse to the latest version.
    Sends POST /upgrade to the running service.
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

    print("\nRestarting service...")
    import subprocess
    if _sudo_needs_password():
        print("Restarting the service requires sudo privileges.")
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
        matrixmouse config set coder ollama:qwen2.5-coder:14b
        matrixmouse config set --repo myrepo coder ollama:qwen2.5-coder:7b
        matrixmouse config set --repo myrepo --commit create_design_docs true
    """
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
            "  sudo systemctl start|stop|restart|status matrixmouse\n\n"
            "Run 'matrixmouse' without arguments to show this help."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=False)

    # --- add-repo ---
    add_parser = subparsers.add_parser(
        "add-repo", help="Clone or register a repo into the workspace.",
    )
    add_parser.add_argument("remote", metavar="URL_OR_PATH")
    add_parser.add_argument("--name", metavar="NAME")
    add_parser.set_defaults(func=cmd_add_repo)

    # --- repos ---
    repos_p = subparsers.add_parser("repos", help="Manage registered repos.")
    repos_sub = repos_p.add_subparsers(dest="repos_command")

    rlist = repos_sub.add_parser("list", help="List registered repos.")
    rlist.add_argument("--format", choices=["table", "json"], default="table", help="Output format.")
    rlist.set_defaults(func=cmd_repos_list)

    rremove = repos_sub.add_parser("remove", help="Remove a repo from the registry.")
    rremove.add_argument("name", metavar="NAME")
    rremove.add_argument("--yes", action="store_true", help="Skip confirmation.")
    rremove.set_defaults(func=cmd_repos_remove)

    # --- tasks ---
    tasks_parser = subparsers.add_parser("tasks", help="View and manage the task queue.")
    tasks_sub = tasks_parser.add_subparsers(dest="tasks_subcmd")
    tasks_parser.set_defaults(func=cmd_tasks)

    tlist = tasks_sub.add_parser("list", help="List tasks.")
    tlist.add_argument("--status", help="Filter by status.")
    tlist.add_argument("--repo", help="Filter by repo name.")
    tlist.add_argument("--all", action="store_true", help="Include completed/cancelled.")
    tlist.add_argument("--format", choices=["table", "json"], default="table", help="Output format.")
    tlist.set_defaults(func=cmd_tasks_list)

    tshow = tasks_sub.add_parser("show", help="Show task details.")
    tshow.add_argument("id", metavar="ID", help="Task ID or prefix.")
    tshow.add_argument("--format", choices=["table", "json"], default="table", help="Output format.")
    tshow.set_defaults(func=cmd_tasks_show)

    tadd = tasks_sub.add_parser("add", help="Create a new task.")
    tadd.add_argument("--title", metavar="TITLE", help="Task title (non-interactive mode).")
    tadd.add_argument("--description", metavar="DESC", help="Task description. Use @file or @- for stdin.")
    tadd.add_argument("--repo", metavar="REPOS", help="Comma-separated repo names.")
    tadd.add_argument("--target-files", metavar="FILES", help="Comma-separated target files.")
    tadd.add_argument("--importance", type=float, default=0.5, help="Importance 0.0-1.0 (default: 0.5).")
    tadd.add_argument("--urgency", type=float, default=0.5, help="Urgency 0.0-1.0 (default: 0.5).")
    tadd.set_defaults(func=cmd_tasks_add)

    tedit = tasks_sub.add_parser("edit", help="Edit a task.")
    tedit.add_argument("id", metavar="ID", help="Task ID or prefix.")
    tedit.add_argument("--title", metavar="TITLE", help="New title.")
    tedit.add_argument("--description", metavar="DESC", help="New description. Use @file or @- for stdin.")
    tedit.add_argument("--importance", type=float, help="New importance 0.0-1.0.")
    tedit.add_argument("--urgency", type=float, help="New urgency 0.0-1.0.")
    tedit.add_argument("--notes", metavar="NOTES", help="Add notes.")
    tedit.add_argument("--repo", metavar="REPOS", help="Comma-separated repo names.")
    tedit.add_argument("--target-files", metavar="FILES", help="Comma-separated target files.")
    tedit.set_defaults(func=cmd_tasks_edit)

    tcancel = tasks_sub.add_parser("cancel", help="Cancel a task.")
    tcancel.add_argument("id", metavar="ID")
    tcancel.add_argument("--yes", action="store_true", help="Skip confirmation.")
    tcancel.set_defaults(func=cmd_tasks_cancel)

    tanswer = tasks_sub.add_parser("answer", help="Answer a task's clarification question.")
    tanswer.add_argument("id", metavar="ID", help="Task ID or prefix.")
    tanswer.add_argument("--message", metavar="MESSAGE", help="Answer message (non-interactive).")
    tanswer.set_defaults(func=cmd_tasks_answer)

    tdecision = tasks_sub.add_parser("decision", help="Submit a decision for a blocked task.")
    tdecision.add_argument("id", metavar="ID", help="Task ID or prefix.")
    tdecision.add_argument("decision_type", metavar="TYPE",
                          help=f"Decision type. Run 'matrixmouse decisions list' for options.")
    tdecision.add_argument("choice", metavar="CHOICE", help="Choice value.")
    tdecision.add_argument("--note", metavar="NOTE", help="Optional note.")
    tdecision.add_argument("--extend-by", type=int, dest="extend_by", help="Turns to extend (for turn_limit_reached).")
    tdecision.set_defaults(func=cmd_tasks_decision)

    tcontext = tasks_sub.add_parser("context", help="View context messages for a task.")
    tcontext.add_argument("id", metavar="ID", help="Task ID or prefix.")
    tcontext.add_argument("--last", type=int, metavar="N", help="Show only last N messages.")
    tcontext.add_argument("--all", action="store_true", help="Show all messages (no limit).")
    tcontext.add_argument("--format", choices=["table", "json"], default="table", help="Output format.")
    tcontext.set_defaults(func=cmd_context)

    # --- decisions ---
    decisions_p = subparsers.add_parser("decisions", help="Manage decision types.")
    decisions_sub = decisions_p.add_subparsers(dest="decisions_command")

    dlist = decisions_sub.add_parser("list", help="List available decision types and choices.")
    dlist.add_argument("--format", choices=["table", "json"], default="table", help="Output format.")
    dlist.set_defaults(func=cmd_decisions_list)

    # --- interject ---
    inj_p = subparsers.add_parser("interject", help="Send messages to the agent.")
    inj_sub = inj_p.add_subparsers(dest="interject_command")

    inj_ws = inj_sub.add_parser("workspace", help="Send workspace-scoped message to Manager.")
    inj_ws.add_argument("message", metavar="MESSAGE")
    inj_ws.set_defaults(func=cmd_interject_workspace)

    inj_repo = inj_sub.add_parser("repo", help="Send repo-scoped message to Manager.")
    inj_repo.add_argument("repo", metavar="REPO_NAME")
    inj_repo.add_argument("message", metavar="MESSAGE")
    inj_repo.set_defaults(func=cmd_interject_repo)

    inj_task = inj_sub.add_parser("task", help="Send message to a specific task.")
    inj_task.add_argument("id", metavar="ID", help="Task ID or prefix.")
    inj_task.add_argument("message", metavar="MESSAGE")
    inj_task.set_defaults(func=cmd_interject_task)

    # --- status ---
    subparsers.add_parser("status", help="Show current agent status.").set_defaults(func=cmd_status)

    # --- stop ---
    subparsers.add_parser("stop", help="Soft stop — halt after the current tool call completes.").set_defaults(func=cmd_stop)

    # --- kill ---
    kill_p = subparsers.add_parser("kill", help="E-STOP — emergency shutdown, no automatic restart.")
    kill_p.add_argument("--yes", action="store_true", help="Skip confirmation prompt.")
    kill_p.set_defaults(func=cmd_kill)

    # --- estop ---
    estop_parser = subparsers.add_parser("estop", help="Manage the E-STOP lockfile.")
    estop_sub = estop_parser.add_subparsers(dest="estop_subcmd", required=True)
    estop_parser.set_defaults(func=cmd_estop)
    estop_sub.add_parser("status", help="Check E-STOP state.").set_defaults(func=cmd_estop_status)
    estop_sub.add_parser("reset", help="Remove ESTOP lockfile so service can start.").set_defaults(func=cmd_estop_reset)

    # --- pause ---
    subparsers.add_parser("pause", help="Pause orchestration — agent won't start new tasks.").set_defaults(func=cmd_pause)

    # --- resume ---
    subparsers.add_parser("resume", help="Resume orchestration after a pause.").set_defaults(func=cmd_resume)

    # --- upgrade ---
    subparsers.add_parser("upgrade", help="Upgrade MatrixMouse and restart the service.").set_defaults(func=cmd_upgrade)

    # --- config ---
    config_parser = subparsers.add_parser("config", help="Read or set configuration values.")
    config_sub = config_parser.add_subparsers(dest="config_subcmd", required=True)
    config_parser.set_defaults(func=cmd_config)

    cget = config_sub.add_parser("get", help="Print config values.")
    cget.add_argument("key", metavar="KEY", nargs="?", help="Specific key to read. Omit to show all.")
    cget.add_argument("--repo", metavar="NAME", help="Read repo-level config instead of workspace.")

    cset = config_sub.add_parser("set", help="Set a config value.")
    cset.add_argument("key", metavar="KEY", help="Config key to set.")
    cset.add_argument("value", metavar="VALUE", help="New value.")
    cset.add_argument("--repo", metavar="NAME", help="Set in repo-level config instead of workspace.")
    cset.add_argument("--commit", action="store_true", default=False, help="Write to the repo tree so it is version controlled.")

    # --- blocked ---
    blocked_p = subparsers.add_parser("blocked", help="Show blocked and waiting tasks report.")
    blocked_p.add_argument("--format", choices=["table", "json"], default="table", help="Output format.")
    blocked_p.set_defaults(func=cmd_blocked)

    # --- token-usage ---
    token_p = subparsers.add_parser("token-usage", help="Show token usage for remote providers.")
    token_p.add_argument("--format", choices=["table", "json"], default="table", help="Output format.")
    token_p.set_defaults(func=cmd_token_usage)

    # --- health ---
    subparsers.add_parser("health", help="Check API health.").set_defaults(func=cmd_health)

    return parser


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = build_parser()
    args = parser.parse_args()

    # No command given - print help
    if args.command is None:
        parser.print_help()
        return

    # Handle commands with subcommands
    subcmd_dispatch = {
        "tasks": cmd_tasks,
        "repos": lambda a: cmd_repos(a) if hasattr(a, "repos_command") else None,
        "estop": cmd_estop,
        "config": cmd_config,
        "interject": lambda a: cmd_interject_dispatch(a),
        "decisions": lambda a: cmd_decisions_dispatch(a),
    }

    if args.command in subcmd_dispatch:
        handler = subcmd_dispatch[args.command]
        # Check if subcommand was provided
        subcmd_attr = f"{args.command}_subcmd" if args.command != "interject" else "interject_command"
        if args.command == "decisions":
            subcmd_attr = "decisions_command"
        elif args.command == "repos":
            subcmd_attr = "repos_command"
        elif args.command == "config":
            subcmd_attr = "config_subcmd"
        elif args.command == "estop":
            subcmd_attr = "estop_subcmd"

        subcmd = getattr(args, subcmd_attr, None)
        if subcmd is None:
            # No subcommand - show help
            parser.parse_args([args.command, "--help"])
            return

    # Dispatch to the command handler
    if hasattr(args, "func"):
        args.func(args)
    else:
        parser.print_help()


def cmd_repos(args):
    """Dispatch repos subcommands."""
    subcmd = getattr(args, "repos_command", None)
    dispatch = {
        "list": cmd_repos_list,
        "remove": cmd_repos_remove,
    }
    if subcmd not in dispatch:
        print("Usage: matrixmouse repos <list|remove>")
        sys.exit(1)
    dispatch[subcmd](args)


def cmd_decisions_dispatch(args):
    """Dispatch decisions subcommands."""
    subcmd = getattr(args, "decisions_command", None)
    dispatch = {
        "list": cmd_decisions_list,
    }
    if subcmd not in dispatch:
        print("Usage: matrixmouse decisions <list>")
        sys.exit(1)
    dispatch[subcmd](args)


def cmd_interject_dispatch(args):
    """Dispatch interject subcommands."""
    subcmd = getattr(args, "interject_command", None)
    dispatch = {
        "workspace": cmd_interject_workspace,
        "repo": cmd_interject_repo,
        "task": cmd_interject_task,
        "legacy": cmd_interject,
    }
    if subcmd not in dispatch:
        print("Usage: matrixmouse interject <workspace|repo|task>")
        sys.exit(1)
    dispatch[subcmd](args)


if __name__ == "__main__":
    main()
