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

    # Future commands stubbed here for discoverability:
    # subparsers.add_parser("interject", help="Send a message to the running agent.")
    # subparsers.add_parser("tasks",     help="View and manage the task queue.")
    # subparsers.add_parser("status",    help="Show current agent status.")
    # subparsers.add_parser("answer",    help="Answer a pending clarification request.")

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
