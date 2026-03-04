"""
matrixmouse/_service.py

Persistent service entry point. Called by systemd via ExecStart.
Not a user-facing command — use the matrixmouse CLI for interaction.

Startup sequence:
    1.  Logging initialised (safe defaults)
    2.  Workspace resolved from environment
    3.  PID lockfile acquired
    4.  Configuration loaded (workspace → repo cascade)
    5.  Logging reconfigured with user preferences
    6.  .env secrets file loaded
    7.  Safety module configured (workspace-wide, task-level reconfigured per task)
    8.  Model availability validated
    9.  AST graph built for registered repos
    10. Memory and comms modules configured
    11. Orchestrator instantiated, API state injected
    12. Web server started (background thread)
    13. Orchestrator.run() — blocks forever, woken by condition variable

Signals:
    SIGTERM / SIGINT — clean shutdown: releases PID lock, exits.
"""

import logging
import os
import signal
import sys
from pathlib import Path

from matrixmouse.utils.logging_utils import setup_logging

# ---------------------------------------------------------------------------
# Logging — before any other matrixmouse imports
# ---------------------------------------------------------------------------
setup_logging(log_level="INFO", log_to_file=False, repo_root=Path.cwd())
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Remaining imports
# ---------------------------------------------------------------------------
from matrixmouse.config import load_config
from matrixmouse.init import validate_models
from matrixmouse.graph import analyze_project
from matrixmouse import memory, comms
from matrixmouse.orchestrator import Orchestrator
from matrixmouse.server import start_server
from matrixmouse.tools import _safety, code_tools  # noqa: side-effects


# ---------------------------------------------------------------------------
# PID lockfile
# ---------------------------------------------------------------------------

_pidlock_path: Path | None = None


def _acquire_pidlock(workspace_root: Path) -> None:
    global _pidlock_path
    lock_dir = workspace_root / ".matrixmouse"
    lock_dir.mkdir(parents=True, exist_ok=True)
    _pidlock_path = lock_dir / "agent.pid"

    if _pidlock_path.exists():
        try:
            existing_pid = int(_pidlock_path.read_text().strip())
            os.kill(existing_pid, 0)
            # Process is alive — another instance is running
            logger.error(
                "Another MatrixMouse instance is running (PID %d). "
                "Exiting. If this is wrong, delete: %s",
                existing_pid, _pidlock_path,
            )
            sys.exit(1)
        except (ValueError, ProcessLookupError, PermissionError):
            logger.warning("Stale PID lockfile at %s. Overwriting.", _pidlock_path)

    _pidlock_path.write_text(str(os.getpid()))
    logger.debug("PID lockfile acquired: %s (PID %d)", _pidlock_path, os.getpid())


def _release_pidlock() -> None:
    global _pidlock_path
    if _pidlock_path and _pidlock_path.exists():
        try:
            _pidlock_path.unlink()
            logger.debug("PID lockfile released.")
        except Exception as e:
            logger.warning("Failed to release PID lockfile: %s", e)


# ---------------------------------------------------------------------------
# Secrets loader
# ---------------------------------------------------------------------------

def _load_env_file(env_file_path: str | None) -> None:
    """
    Load a .env file of KEY=VALUE pairs into os.environ.
    Skips lines starting with # and blank lines.
    Does not override existing environment variables — systemd-set
    values take precedence.

    Args:
        env_file_path: Path to the .env file, or None to skip.
    """
    if not env_file_path:
        return

    env_path = Path(env_file_path)
    if not env_path.exists():
        logger.warning("env_file configured but not found: %s", env_path)
        return

    loaded = 0
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
                loaded += 1

    logger.debug("Loaded %d value(s) from %s", loaded, env_path)


# ---------------------------------------------------------------------------
# Workspace and repo resolution
# ---------------------------------------------------------------------------

def _resolve_workspace() -> Path:
    env = os.environ.get("WORKSPACE_PATH")
    if env:
        p = Path(env).resolve()
        if p.exists():
            return p
        logger.error("WORKSPACE_PATH set but directory does not exist: %s", p)
        sys.exit(1)
    default = Path.home() / "matrixmouse-workspace"
    if default.exists():
        return default
    logger.error(
        "Workspace not found. Set WORKSPACE_PATH or create %s", default
    )
    sys.exit(1)


def _load_registered_repos(workspace_root: Path) -> list[Path]:
    """
    Return the local_path for each registered repo in repos.json.
    Skips entries whose directory no longer exists.
    """
    import json
    repos_file = workspace_root / ".matrixmouse" / "repos.json"
    if not repos_file.exists():
        return []
    with open(repos_file) as f:
        repos = json.load(f)
    paths = []
    for r in repos:
        p = Path(r.get("local_path", ""))
        if p.exists():
            paths.append(p)
        else:
            logger.warning(
                "Registered repo '%s' not found at %s — skipping.",
                r.get("name"), p,
            )
    return paths


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    logger.info("MatrixMouse service starting.")

    # --- Workspace ---
    workspace_root = _resolve_workspace()
    logger.info("Workspace: %s", workspace_root)

    # --- PID lock ---
    _acquire_pidlock(workspace_root)

    # --- Signal handlers ---
    def _shutdown(signum, frame):
        logger.info("Signal %d received. Shutting down.", signum)
        _release_pidlock()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    try:
        # --- Config (workspace-level, no specific repo yet) ---
        config = load_config(repo_root=None, workspace_root=workspace_root)

        # Expose config to git_tools and other modules that read _loaded_config
        import matrixmouse.config as _cfg_module
        _cfg_module._loaded_config = config

        # --- Logging (reconfigure with user prefs) ---
        setup_logging(
            log_level=config.log_level,
            log_to_file=config.log_to_file,
            repo_root=workspace_root,
        )
        logger.info("Logging configured: level=%s file=%s",
                    config.log_level, config.log_to_file)

        # --- Secrets (.env file) ---
        env_file = getattr(config, "env_file", None)
        _load_env_file(env_file)

        # --- Safety module (workspace-wide baseline) ---
        # Reconfigured per-task in orchestrator._run_task via reconfigure_for_task()
        _safety.configure(
            allowed_roots=_load_registered_repos(workspace_root),
            workspace_root=workspace_root,
        )

        # --- Model validation ---
        validate_models(config)

        # --- AST graphs for all registered repos ---
        repo_paths = _load_registered_repos(workspace_root)
        graphs = {}
        for repo_path in repo_paths:
            try:
                logger.info("Building AST graph for %s...", repo_path.name)
                graph = analyze_project(str(repo_path))
                graphs[repo_path.name] = graph
                logger.info(
                    "  %s: %d functions, %d classes",
                    repo_path.name,
                    len(graph.functions),
                    len(graph.classes),
                )
            except Exception as e:
                logger.warning(
                    "AST graph failed for %s: %s. Continuing.", repo_path.name, e
                )

        # Configure code_tools with the first available graph as default.
        # Per-task graph switching is a future improvement.
        if graphs:
            code_tools.configure(next(iter(graphs.values())))

        # --- Memory and comms ---
        agent_notes = workspace_root / ".matrixmouse" / "AGENT_NOTES.md"
        memory.configure(agent_notes)
        comms.configure(config)

        # --- Build paths object for orchestrator ---
        from matrixmouse.config import MatrixMousePaths
        paths = MatrixMousePaths(
            workspace_root=workspace_root,
            tasks_file=workspace_root / ".matrixmouse" / "tasks.json",
        )

        # --- Orchestrator ---
        orchestrator = Orchestrator(config=config, paths=paths, graph=graphs)

        # Inject live state into api.py before the server starts
        orchestrator.configure_api()

        # --- Web server (background thread) ---
        start_server(config, paths)
        logger.info(
            "Web server started on port %d",
            getattr(config, "server_port", 8080),
        )

        # --- Run forever ---
        logger.info("MatrixMouse service ready. Waiting for tasks.")
        orchestrator.run()

    except Exception as e:
        logger.exception("Fatal error during startup: %s", e)
        _release_pidlock()
        sys.exit(1)


if __name__ == "__main__":
    main()
