"""
matrixmouse/main.py

Entry point for MatrixMouse. Initialises all subsystems in order and
hands control to the orchestrator.

Startup sequence:
    1. Logging (safe defaults, before anything else)
    2. Configuration (from TOML files)
    3. Logging reconfigured with user preferences
    4. Paths resolved and validated
    5. AST graph built
    6. Git connection verified
    7. Web server started
    8. Orchestrator started

Handles top-level signals (shutdown, restart).
"""

import logging
import signal
import sys
from pathlib import Path

from matrixmouse.config import MatrixMouseConfig, MatrixMousePaths, load_config
from matrixmouse.utils.logging_utils import setup_logging

# ---------------------------------------------------------------------------
# Logging — must come before any other matrixmouse imports so that modules
# which call logging.getLogger(__name__) at import time get a configured logger.
# ---------------------------------------------------------------------------
setup_logging(log_level="INFO", log_to_file=False, repo_root=Path.cwd())
logger = logging.getLogger(__name__)
logger.info("MatrixMouse starting up...")


# ---------------------------------------------------------------------------
# Remaining imports — after logging is initialised
# ---------------------------------------------------------------------------
import argparse

from matrixmouse.init import setup_repo, validate_models
from matrixmouse.graph import ProjectAnalyzer, analyze_project
from matrixmouse import memory
from matrixmouse.orchestrator import Orchestrator
from matrixmouse.server import start_server
from matrixmouse.tools import _safety, code_tools, TOOLS, TOOL_REGISTRY  # noqa: F401  (used by orchestrator)


# ---------------------------------------------------------------------------
# Signal handling
# ---------------------------------------------------------------------------
def _handle_shutdown(signum, frame):
    logger.info("Shutdown signal received. Exiting cleanly...")
    sys.exit(0)

signal.signal(signal.SIGINT, _handle_shutdown)
signal.signal(signal.SIGTERM, _handle_shutdown)


# ---------------------------------------------------------------------------
# CLI commands
# ---------------------------------------------------------------------------
def cmd_init(args):
    """
    Initialise MatrixMouse in the current directory.

    Creates .matrixmouse/ with a starter config and empty AGENT_NOTES.md.
    Safe to call when already initialised — reports status and exits.
    """
    repo_root = Path.cwd()
    paths = setup_repo(repo_root)

    logger.info("MatrixMouse initialised at %s", paths.config_dir)
    print(f"Initialized matrixmouse in {repo_root}")


def cmd_run(args):
    """
    Start the agent against the current repository.

    Loads config, builds the AST graph, verifies git, starts the web
    server, and hands control to the orchestrator.
    """
    repo_root = Path.cwd()

    # --- Config ---
    paths = setup_repo(repo_root)
    config = load_config(repo_root)

    # --- Set up safety module ---
    _safety.configure(repo_root=paths.repo_root)

    # --- Reconfigure logging with user preferences ---
    setup_logging(
        log_level=config.log_level,
        log_to_file=config.log_to_file,
        repo_root=repo_root,
    )
    logger.info("Configuration loaded. Log level: %s", config.log_level)

    # --- Validate Ollama Models ---
    validate_models(config)

    # --- AST graph ---
    logger.info("Building AST graph for %s ...", repo_root)
    graph = analyze_project(str(repo_root))
    logger.info(
        "AST graph complete. %d functions, %d classes indexed.",
        len(graph.functions),
        len(graph.classes),
    )

    # --- Configure code_tools with AST graph
    code_tools.configure(graph)

    # --- Configure memory module ---
    memory.configure(paths.agent_notes)

    # --- Web server ---
    # TODO: start_server is currently a stub. Wire up when server.py is ready.
    # start_server(config, paths)

    # --- Orchestrator ---
    logger.info("Handing control to orchestrator...")
    orchestrator = Orchestrator(config=config, paths=paths, graph=graph)
    orchestrator.run()


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="matrixmouse",
        description="Autonomous coding agent.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser(
        "init",
        help="Initialise MatrixMouse in the current directory.",
    ).set_defaults(func=cmd_init)

    run_parser = subparsers.add_parser(
        "run",
        help="Start the agent against the current repository.",
    )
    run_parser.set_defaults(func=cmd_run)
    # Future flags go here, e.g.:
    # run_parser.add_argument("--task", help="Task description or issue number")

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
