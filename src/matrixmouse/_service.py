"""
matrixmouse/_service.py

Persistent service entry point. Called by systemd via ExecStart.
Not a user-facing command — use the matrixmouse CLI for interaction.

Startup sequence:
    1.  Logging initialised (safe defaults)
    2.  Workspace resolved from environment
    3.  ESTOP lockfile checked — exits cleanly if engaged
    4.  PID lockfile acquired
    5.  Configuration loaded (workspace → repo cascade)
    6.  Logging reconfigured with user preferences
    7.  .env secrets file loaded
    8.  Safety module configured (workspace-wide, task-level reconfigured per task)
    9.  Model availability validated
    10. AST graph built for registered repos
    11. Memory and comms modules configured
    12. Orchestrator instantiated, API state injected
    13. Web server started (background thread)
    14. Orchestrator.run() — blocks forever, woken by condition variable

Signals:
    SIGTERM / SIGINT — clean shutdown: stops loaded ollama models,
                       releases PID lock, exits with code 0.
                       systemd will NOT restart on code 0 (Restart=on-failure).
"""

import logging
import os
import signal
import subprocess
import sys
from pathlib import Path

from matrixmouse.repository.sqlite_task_repository import SQLiteTaskRepository
from matrixmouse.repository.sqlite_workspace_state_repository import SQLiteWorkspaceStateRepository
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
# Module-level config reference — set after load_config(), used by shutdown
# ---------------------------------------------------------------------------
_config = None


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
# Ollama model unload — called on every shutdown path
# ---------------------------------------------------------------------------

def _stop_ollama_models() -> None:
    """
    Unload all configured models from Ollama VRAM.

    Uses the config model fields (coder_model, manager_model, etc.) rather
    than `ollama ps` so we don't accidentally stop unrelated models running
    on the same machine.

    If config hasn't loaded yet (very early crash), this is a no-op.
    Each stop is attempted independently — one failure doesn't block others.
    """
    if _config is None:
        logger.debug("Config not loaded — skipping ollama model unload.")
        return

    # Collect all unique model names across all roles
    model_fields = [
        _config.coder_model,
        _config.manager_model,
        _config.summarizer_model,
        _config.critic_model,
        _config.writer_model,
    ]

    # coder_cascade is a list — flatten it
    cascade = _config.coder_cascade or []
    if isinstance(cascade, str):
        cascade = [m.strip() for m in cascade.split(",") if m.strip()]
    model_fields.extend(cascade)

    models = list(dict.fromkeys(m for m in model_fields if m))  # unique, ordered

    if not models:
        logger.debug("No models configured — skipping ollama model unload.")
        return

    logger.info("Unloading %d ollama model(s): %s", len(models), ", ".join(models))
    for model in models:
        try:
            result = subprocess.run(
                ["ollama", "stop", model],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                logger.info("Unloaded model: %s", model)
            else:
                # Not an error — model may not have been loaded
                logger.debug(
                    "ollama stop %s: %s", model,
                    (result.stderr or result.stdout).strip() or "no output"
                )
        except FileNotFoundError:
            logger.debug("ollama not found in PATH — skipping model unload.")
            break  # No point trying further models
        except subprocess.TimeoutExpired:
            logger.warning("ollama stop %s timed out.", model)
        except Exception as e:
            logger.warning("Failed to stop model %s: %s", model, e)


# ---------------------------------------------------------------------------
# Secrets loader
# ---------------------------------------------------------------------------

def _load_env_file(env_file_path: str | None) -> None:
    """
    Load a .env file of KEY=VALUE pairs into os.environ.
    Skips lines starting with # and blank lines.
    Does not override existing environment variables — systemd-set
    values take precedence.
    """
    if not env_file_path:
        return

    env_path = Path(env_file_path)
    if not env_path.exists():
        logger.warning("Environment file not found: %s", env_path)
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
    default = Path("/var/lib/matrixmouse-workspace")
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
# ESTOP check
# ---------------------------------------------------------------------------

def _check_estop(workspace_root: Path) -> None:
    """
    Check for an ESTOP lockfile. If found, log and exit with code 0.

    Exit code 0 prevents systemd from restarting the service
    (Restart=on-failure only restarts on non-zero exit codes).

    To resume after an ESTOP:
        1. matrixmouse estop reset
        2. sudo systemctl start matrixmouse
    """
    estop_path = workspace_root / ".matrixmouse" / "ESTOP"
    if estop_path.exists():
        try:
            message = estop_path.read_text().strip()
        except Exception:
            message = "(could not read lockfile)"
        logger.critical(
            "E-STOP is engaged. Service will not start.\n"
            "Lockfile: %s\n"
            "%s\n"
            "To reset: matrixmouse estop reset && sudo systemctl start matrixmouse",
            estop_path, message,
        )
        sys.exit(0)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    global _config
    logger.info("MatrixMouse service starting.")

    # --- Workspace ---
    workspace_root = _resolve_workspace()
    logger.info("Workspace: %s", workspace_root)

    # --- ESTOP check (before PID lock — no cleanup needed if engaged) ---
    _check_estop(workspace_root)

    # --- PID lock ---
    _acquire_pidlock(workspace_root)

    # --- Signal handlers ---
    def _shutdown(signum, frame):
        logger.info("Signal %d received. Shutting down.", signum)
        _stop_ollama_models()
        _release_pidlock()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    try:
        # --- Config ---
        _config = load_config(repo_root=None, workspace_root=workspace_root)

        # Expose config to git_tools and other modules that read _loaded_config
        import matrixmouse.config as _cfg_module
        _cfg_module._loaded_config = _config

        # --- Logging (reconfigure with user prefs) ---
        setup_logging(
            log_level=_config.log_level,
            log_to_file=_config.log_to_file,
            repo_root=workspace_root,
        )
        logger.info("Logging configured: level=%s file=%s",
                    _config.log_level, _config.log_to_file)

        # --- Secrets ---
        _load_env_file("/etc/matrixmouse/secrets/github_token")
        _load_env_file("/etc/matrixmouse/secrets/ntfy")

        # --- Git tools check
        from matrixmouse.tools.git_tools import _require_ssh_key
        _require_ssh_key()

        # --- Safety module (workspace-wide baseline) ---
        registered = _load_registered_repos(workspace_root)
        if registered:
            _safety.configure(
                allowed_roots=registered,
                workspace_root=workspace_root,
            )
        else:
            logger.info(
                "No repos registered yet — skipping safety module baseline configure. "
                "Will be configured per-task via reconfigure_for_task()."
            )

        # --- Model validation ---
        validate_models(_config)

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

        if graphs:
            code_tools.configure(next(iter(graphs.values())))

        # --- Build paths object ---
        from matrixmouse.config import MatrixMousePaths
        paths = MatrixMousePaths(workspace_root=workspace_root)

        # --- Memory and comms ---
        memory.configure(paths.agent_notes)
        comms.configure(_config)

        # --- Orchestrator ---
        queue = SQLiteTaskRepository(paths.db_file)
        ws_state_repo = SQLiteWorkspaceStateRepository(paths.db_file)
        orchestrator = Orchestrator(
            config=_config,
            paths=paths,
            queue=queue,
            ws_state_repo=ws_state_repo,
            graph=graphs,
        )
        orchestrator.configure_api()

        # --- Pause on startup ---
        start_paused = _config.start_paused or os.environ.get("MATRIXMOUSE_START_PAUSED") == "1"
        if start_paused:
            from matrixmouse.api import pause_orchestrator
            pause_orchestrator()
            logger.info(
                "Orchestrator started in paused state. "
                "Resume via: matrixmouse resume"
            )

        # --- Web server (background thread) ---
        start_server(_config, paths)
        logger.info(
            "Web server started on port %d",
            _config.server_port,
        )

        # --- Run forever ---
        logger.info("MatrixMouse service ready. Waiting for tasks.")
        orchestrator.run()

    except Exception as e:
        logger.exception("Fatal error during startup: %s", e)
        _stop_ollama_models()
        _release_pidlock()
        sys.exit(1)


if __name__ == "__main__":
    main()
