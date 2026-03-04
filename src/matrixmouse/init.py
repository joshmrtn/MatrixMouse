"""
matrixmouse/init.py

Repo initialisation and model validation.

setup_repo() is idempotent — safe to call on every run and every add-repo.
It creates only what is missing and never overwrites existing content.

Principle: MatrixMouse writes nothing to a repo without explicit opt-in.

What setup_repo ALWAYS creates (workspace only, never touches the repo):
    <workspace>/.matrixmouse/<repo_name>/AGENT_NOTES.md
    <workspace>/.matrixmouse/<repo_name>/ignore

What setup_repo creates ONLY IF the user has opted in via config:
    <repo>/.matrixmouse/config.toml     only if repo_config_file exists already
                                         OR user ran `matrixmouse config set --repo`
    <repo>/docs/design/                 only if create_design_docs = true
    <repo>/docs/adr/                    only if create_adr_docs = true

The .matrixmouse/ directory in the repo is never created by setup_repo.
It is created on demand when the user writes a repo-level config key via
`matrixmouse config set <key> <value> --repo <name>`, which is handled
by the API's PATCH /config/repos/{name} endpoint.
"""

import logging
from pathlib import Path
from typing import Optional

import ollama

from matrixmouse.config import (
    MatrixMouseConfig,
    MatrixMousePaths,
    generate_starter_config,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Path builder
# ---------------------------------------------------------------------------

def _build_paths(
    repo_root: Path,
    workspace_root: Optional[Path] = None,
) -> MatrixMousePaths:
    """
    Resolve all MatrixMouse paths for a given repo.

    Per-repo runtime state sits inside the workspace under the repo's
    directory name, keeping it out of the git tree while maintaining
    clean per-repo separation.

    Args:
        repo_root:       Absolute path to the repo root.
        workspace_root:  Absolute path to the workspace root.
                         Falls back to WORKSPACE_PATH env var,
                         then to repo_root's parent.
    """
    import os

    resolved_repo = repo_root.resolve()
    repo_name = resolved_repo.name

    if workspace_root is None:
        env_workspace = os.environ.get("WORKSPACE_PATH")
        workspace_root = (
            Path(env_workspace).resolve() if env_workspace
            else resolved_repo.parent
        )
    else:
        workspace_root = workspace_root.resolve()

    ws_mm = workspace_root / ".matrixmouse"
    repo_state_dir = ws_mm / repo_name

    return MatrixMousePaths(
        workspace_root=workspace_root,
        repo_root=resolved_repo,
        repo_name=repo_name,
        config_dir=resolved_repo / ".matrixmouse",
        repo_state_dir=repo_state_dir,
        agent_notes=repo_state_dir / "AGENT_NOTES.md",
        log_file=repo_state_dir / "agent.log",
        design_docs=resolved_repo / "docs" / "design",
        tasks_file=ws_mm / "tasks.json",
    )


# ---------------------------------------------------------------------------
# Workspace-side setup (always runs)
# ---------------------------------------------------------------------------

def _ensure_repo_state_dir(paths: MatrixMousePaths) -> None:
    """
    Create <workspace>/.matrixmouse/<repo_name>/ if it doesn't exist.
    This is the only directory setup_repo unconditionally creates.
    """
    if not paths.repo_state_dir.exists():
        paths.repo_state_dir.mkdir(parents=True, exist_ok=True)
        logger.info("Created repo state dir at %s", paths.repo_state_dir)


def _ensure_notes_file(paths: MatrixMousePaths) -> None:
    """
    Create AGENT_NOTES.md in the workspace state dir if missing.
    Scoped to this repo — the agent only reads its own repo's notes.
    """
    if paths.agent_notes.exists():
        return
    paths.agent_notes.write_text(
        "# MatrixMouse Agent Notes\n\n"
        f"Working memory for repo: {paths.repo_name}\n\n"
        "This file lives in the workspace, not the repo, "
        "and is never version controlled.\n\n"
        "## file_map\n\n"
        "## key_functions\n\n"
        "## open_questions\n\n"
        "## completed_subtasks\n\n"
        "## known_issues\n\n"
    )
    logger.debug("Created %s", paths.agent_notes)


def _ensure_workspace_ignore(paths: MatrixMousePaths) -> None:
    """
    Create the per-repo ignore file in the workspace state dir if missing.
    This is the local (untracked) counterpart to <repo>/.matrixmouse/ignore.
    """
    ignore_path = paths.repo_state_dir / "ignore"
    if ignore_path.exists():
        return
    ignore_path.write_text(
        "# MatrixMouse per-repo local ignore file\n"
        "# Patterns here are enforced for this repo on this machine only.\n"
        "# This file is NOT version controlled.\n"
        "# For team-shared patterns, use <repo>/.matrixmouse/ignore instead.\n"
        "# Uses fnmatch syntax. Lines starting with # are comments.\n"
        "#\n"
        "# Add local overrides below:\n"
    )
    logger.debug("Created workspace ignore at %s", ignore_path)


# ---------------------------------------------------------------------------
# Repo-side setup (opt-in only)
# ---------------------------------------------------------------------------

def _ensure_repo_config(paths: MatrixMousePaths) -> None:
    """
    Write a starter config.toml into <repo>/.matrixmouse/ IF that directory
    already exists. Does not create the directory — that only happens via
    `matrixmouse config set --repo`, handled by the API.

    This means: if a user has explicitly set a repo-level config key (which
    creates the dir), we ensure the full starter template is there so they
    can see all available options. If they haven't, we don't touch their repo.
    """
    if not paths.config_dir.exists():
        # User hasn't opted into repo-level config — leave the repo alone.
        return

    config_path = paths.config_dir / "config.toml"
    if not config_path.exists():
        config_path.write_text(generate_starter_config())
        logger.info("Created starter config at %s", config_path)


def _ensure_design_template(design_dir: Path) -> None:
    """Create docs/design/ and write template.md if missing."""
    design_dir.mkdir(parents=True, exist_ok=True)
    template_path = design_dir / "template.md"
    if template_path.exists():
        return
    template_path.write_text(
        "---\n"
        "module: module.name\n"
        "status: draft"
        "  # draft | critique | approved | implementing | complete | superseded\n"
        "depends_on: []\n"
        "implemented: false\n"
        "last_amended: YYYY-MM-DD\n"
        "---\n\n"
        "## Responsibility\n\n"
        "Single paragraph. What this module does and does not do.\n\n"
        "## Public Interface\n\n"
        "Function signatures with type annotations and docstrings. No bodies.\n\n"
        "```python\n"
        "def example(arg: str) -> bool:\n"
        '    """Brief description. Raises XError if ..."""\n'
        "```\n\n"
        "## Design Decisions\n\n"
        "Key choices made and brief rationale. One decision per bullet.\n\n"
        "## Open Questions\n\n"
        "Unresolved ambiguities. Any item here blocks `approved` status.\n\n"
        "## Amendments\n\n"
        "Append-only log of changes after initial approval.\n"
        "Never edit prior entries — add new ones below.\n\n"
        "<!-- YYYY-MM-DD: description of change and reason -->\n"
    )
    logger.debug("Created design template at %s", template_path)


def _ensure_adr_template(adr_dir: Path) -> None:
    """Create docs/adr/ and write template.md if missing."""
    adr_dir.mkdir(parents=True, exist_ok=True)
    template_path = adr_dir / "template.md"
    if template_path.exists():
        return
    template_path.write_text(
        "# NNNN. Title of Decision\n\n"
        "Date: YYYY-MM-DD\n"
        "Status: proposed"
        "  # proposed | accepted | deprecated | superseded by [NNNN](NNNN-title.md)\n\n"
        "## Context\n\n"
        "What is the issue that motivated this decision?\n\n"
        "## Decision\n\n"
        'State it actively: "We will use X because Y."\n\n'
        "## Consequences\n\n"
        "What becomes easier or harder as a result.\n\n"
        "## Alternatives Considered\n\n"
        "What other options were evaluated and why they were not chosen.\n"
    )
    logger.debug("Created ADR template at %s", template_path)


def _ensure_docs_structure(
    paths: MatrixMousePaths,
    config: MatrixMouseConfig,
) -> None:
    """
    Scaffold docs/ in the repo if the user has opted in.

    Both flags default to False — nothing is created unless explicitly
    enabled. Enable per-repo:
        matrixmouse config set create_design_docs true --repo <name>
    """
    if config.create_design_docs:
        _ensure_design_template(paths.design_docs)
        logger.info("Design docs ready at %s", paths.design_docs)

    if config.create_adr_docs:
        _ensure_adr_template(paths.design_docs.parent / "adr")
        logger.info("ADR docs ready at %s", paths.design_docs.parent / "adr")


def _verify_git(repo_root: Path) -> None:
    """
    Confirm the repo root is a git repository.
    Logs a warning if not — does not abort.
    """
    import subprocess
    result = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=repo_root, capture_output=True, text=True,
    )
    if result.returncode != 0:
        logger.warning(
            "No git repository at %s. Git tools will not function.", repo_root
        )
    else:
        logger.info("Git repository confirmed at %s", repo_root)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def setup_repo(
    repo_root: Path,
    workspace_root: Optional[Path] = None,
    config: Optional[MatrixMouseConfig] = None,
) -> MatrixMousePaths:
    """
    Idempotent repo setup. Safe to call on every run and every add-repo.
    Creates only what is missing — never overwrites existing content.

    ALWAYS creates (workspace only, repo untouched):
        <workspace>/.matrixmouse/<repo_name>/AGENT_NOTES.md
        <workspace>/.matrixmouse/<repo_name>/ignore

    ONLY IF <repo>/.matrixmouse/ already exists (user opted in):
        <repo>/.matrixmouse/config.toml     (starter, all fields commented)

    ONLY IF config flag is True (default False, opt-in per-repo):
        <repo>/docs/design/                 create_design_docs = true
        <repo>/docs/adr/                    create_adr_docs    = true

    Args:
        repo_root:       Root directory of the repo.
        workspace_root:  Root of the workspace. Falls back to WORKSPACE_PATH
                         env var or repo parent.
        config:          Loaded config for flag checks. If None, uses field
                         defaults (both doc flags False — nothing in repo).

    Returns:
        MatrixMousePaths with all resolved paths for this session.
    """
    if config is None:
        config = MatrixMouseConfig()

    paths = _build_paths(repo_root, workspace_root)

    # Workspace side — always safe, never touches the repo
    _ensure_repo_state_dir(paths)
    _ensure_notes_file(paths)
    _ensure_workspace_ignore(paths)

    # Repo side — only if user has explicitly opted in
    _ensure_repo_config(paths)
    _ensure_docs_structure(paths, config)

    _verify_git(repo_root)

    return paths


# ---------------------------------------------------------------------------
# Model validation
# ---------------------------------------------------------------------------

def validate_models(config: MatrixMouseConfig) -> None:
    """
    Verify all configured models are available and support tool calling.
    Attempts to pull missing models automatically.
    Called once at service startup before the orchestrator starts.
    """
    models_to_check = {
        "coder":      (config.coder,      True),
        "planner":    (config.planner,    True),
        "judge":      (config.judge,      True),
        "summarizer": (config.summarizer, False),
    }
    for role, (model_name, requires_tools) in models_to_check.items():
        _ensure_model_available(model_name)
        if requires_tools:
            _ensure_model_supports_tools(model_name, role)


def _ensure_model_available(model_name: str) -> None:
    try:
        ollama.show(model_name)
        logger.info("Model available: %s", model_name)
    except ollama.ResponseError as e:
        if e.status_code == 404:
            logger.info("Pulling model %s...", model_name)
            print(f"Pulling model {model_name}...")
            ollama.pull(model_name)
            logger.info("Model %s pulled successfully.", model_name)
        else:
            raise


def _ensure_model_supports_tools(model_name: str, role: str) -> None:
    info = ollama.show(model_name)
    capabilities = getattr(info, "capabilities", []) or []
    if "tools" not in capabilities:
        raise ValueError(
            f"Model '{model_name}' (role '{role}') does not support tool calling. "
            f"Check with: ollama show {model_name}"
        )
