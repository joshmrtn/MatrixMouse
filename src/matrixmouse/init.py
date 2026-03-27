"""
matrixmouse/init.py

Repo initialisation and model validation.

setup_repo() is idempotent — safe to call on every run and every add-repo.
It creates only what is missing and never overwrites existing content.

Principle: MatrixMouse writes nothing to a repo without explicit opt-in.

What setup_repo ALWAYS creates (workspace state dir only, repo untouched):
    <workspace>/.matrixmouse/<repo_name>/AGENT_NOTES.md
    <workspace>/.matrixmouse/<repo_name>/ignore

What setup_repo creates ONLY IF the user has opted in:
    <repo>/.matrixmouse/config.toml     only if <repo>/.matrixmouse/ already exists
                                         (created by `matrixmouse config set --repo`)
    <repo>/docs/design/                 only if create_design_docs = true
    <repo>/docs/adr/                    only if create_adr_docs = true

The .matrixmouse/ directory in the repo is never created by setup_repo.
It is created on demand when the user writes a repo-level config key via
`matrixmouse config set <key> <value> --repo <name>`, handled by the
API's PATCH /config/repos/{name} endpoint.
"""

import logging
import os
from pathlib import Path
from typing import Optional

import ollama

from matrixmouse.config import (
    MatrixMouseConfig,
    MatrixMousePaths,
    RepoPaths,
    generate_starter_config,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Workspace-side setup (always runs, never touches the repo)
# ---------------------------------------------------------------------------

def _ensure_repo_state_dir(paths: RepoPaths) -> None:
    """
    Create <workspace>/.matrixmouse/<repo_name>/ if it doesn't exist.
    This is the only directory setup_repo unconditionally creates.
    """
    if not paths.state_dir.exists():
        paths.state_dir.mkdir(parents=True, exist_ok=True)
        logger.info("Created repo state dir at %s", paths.state_dir)


def _ensure_notes_file(paths: RepoPaths) -> None:
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


def _ensure_workspace_ignore(paths: RepoPaths) -> None:
    """
    Create the per-repo local ignore file in the workspace state dir.
    Untracked counterpart to <repo>/.matrixmouse/ignore.
    """
    if paths.local_ignore.exists():
        return
    paths.local_ignore.write_text(
        "# MatrixMouse per-repo local ignore file\n"
        "# Patterns here are enforced for this repo on this machine only.\n"
        "# This file is NOT version controlled.\n"
        "# For team-shared patterns, use <repo>/.matrixmouse/ignore instead.\n"
        "# Uses fnmatch syntax. Lines starting with # are comments.\n"
        "#\n"
        "# Add local overrides below:\n"
    )
    logger.debug("Created local ignore at %s", paths.local_ignore)


# ---------------------------------------------------------------------------
# Repo-side setup (opt-in only)
# ---------------------------------------------------------------------------

def _ensure_repo_config(paths: RepoPaths) -> None:
    """
    Write a starter config.toml into <repo>/.matrixmouse/ IF that directory
    already exists. Does not create the directory.

    If a user has set a repo-level config key (which creates the dir via the
    API), we ensure the full commented starter template is present so they
    can discover all available options.
    """
    if not paths.config_dir.exists():
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


def _ensure_docs_structure(paths: RepoPaths, config: MatrixMouseConfig) -> None:
    """
    Scaffold docs/ in the repo if the user has opted in.
    Both flags default to False — nothing created unless explicitly enabled.
    """
    if config.create_design_docs:
        _ensure_design_template(paths.design_docs)
        logger.info("Design docs ready at %s", paths.design_docs)

    if config.create_adr_docs:
        _ensure_adr_template(paths.adr_docs)
        logger.info("ADR docs ready at %s", paths.adr_docs)


def _verify_git(repo_root: Path) -> None:
    """Confirm repo_root is a git repository. Logs a warning if not."""
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


MIRROR_REMOTE = "mm-mirror"

def _ensure_mirror(repo_root: Path, workspace_root: Path, repo_name: str) -> None:
    """
    Ensure the local bare mirror exists and is registered as a remote.

    The mirror lives at /var/lib/matrixmouse-mirrors/<repo_name>.git.
    If it doesn't exist, it is created as a bare clone of the repo.
    If the remote 'mm-mirror' is not registered, it is added.

    This is idempotent — safe to call on every setup_repo invocation.

    Args:
        repo_root:      Root directory of the repo.
        workspace_root: Workspace root (used to build MatrixMousePaths).
        repo_name:      Name of the repo (directory name).
    """
    import subprocess
    from matrixmouse.config import MatrixMousePaths

    ws_paths = MatrixMousePaths(workspace_root=workspace_root)
    mirror_path = ws_paths.mirror_path(repo_name)

    env = _git_env_for_init()

    # Create bare mirror if it doesn't exist
    if not mirror_path.exists():
        mirror_path.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            ["git", "clone", "--bare", str(repo_root), str(mirror_path)],
            capture_output=True, text=True, env=env,
        )
        if result.returncode != 0:
            logger.error(
                "Failed to create mirror for %s at %s: %s",
                repo_name, mirror_path, result.stderr.strip(),
            )
            return
        logger.info("Created bare mirror at %s", mirror_path)
    else:
        logger.debug("Mirror already exists at %s", mirror_path)

    # Register mm-mirror remote if not present
    check = subprocess.run(
        ["git", "remote", "get-url", MIRROR_REMOTE],
        cwd=repo_root, capture_output=True, text=True, env=env,
    )
    if check.returncode != 0:
        # Remote not registered — add it
        add = subprocess.run(
            ["git", "remote", "add", MIRROR_REMOTE, str(mirror_path)],
            cwd=repo_root, capture_output=True, text=True, env=env,
        )
        if add.returncode != 0:
            logger.error(
                "Failed to add %s remote for %s: %s",
                MIRROR_REMOTE, repo_name, add.stderr.strip(),
            )
            return
        logger.info("Added %s remote pointing to %s", MIRROR_REMOTE, mirror_path)
    else:
        existing_url = check.stdout.strip()
        if existing_url != str(mirror_path):
            logger.warning(
                "%s remote for %s points to %s, expected %s. "
                "Not updating — manual intervention may be needed.",
                MIRROR_REMOTE, repo_name, existing_url, mirror_path,
            )
        else:
            logger.debug(
                "%s remote already configured for %s", MIRROR_REMOTE, repo_name
            )


def _git_env_for_init() -> dict:
    """
    Build git environment for init-time operations.
    Mirrors _git_env() from git_tools but without the import dependency.
    """
    import os
    from pathlib import Path

    env = os.environ.copy()
    from matrixmouse import config as config_module
    cfg = getattr(config_module, "_loaded_config", None)
    if cfg:
        secrets_dir = Path("/etc/matrixmouse/secrets")
        key_path = secrets_dir / cfg.gh_ssh_key_file
        if key_path.exists():
            env["GIT_SSH_COMMAND"] = (
                f"ssh -i {key_path} "
                f"-o IdentitiesOnly=yes "
                f"-o StrictHostKeyChecking=accept-new"
            )
        env["GIT_AUTHOR_NAME"]    = cfg.agent_git_name
        env["GIT_AUTHOR_EMAIL"]   = cfg.agent_git_email
        env["GIT_COMMITTER_NAME"] = cfg.agent_git_name
        env["GIT_COMMITTER_EMAIL"] = cfg.agent_git_email
    return env


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def setup_repo(
    repo_root: Path,
    workspace_root: Optional[Path] = None,
    config: Optional[MatrixMouseConfig] = None,
) -> RepoPaths:
    """
    Idempotent repo setup. Safe to call on every run and every add-repo.
    Creates only what is missing — never overwrites existing content.

    ALWAYS creates (workspace state dir only, repo untouched):
        <workspace>/.matrixmouse/<repo_name>/AGENT_NOTES.md
        <workspace>/.matrixmouse/<repo_name>/ignore

    ONLY IF <repo>/.matrixmouse/ already exists (user opted in via API):
        <repo>/.matrixmouse/config.toml     starter config, all fields commented

    ONLY IF config flag is True (default False):
        <repo>/docs/design/                 create_design_docs = true
        <repo>/docs/adr/                    create_adr_docs    = true

    Args:
        repo_root:       Root directory of the repo.
        workspace_root:  Root of the workspace. Falls back to WORKSPACE_PATH
                         env var or repo parent.
        config:          Loaded config for flag checks. Defaults to
                         MatrixMouseConfig() (both doc flags False).

    Returns:
        RepoPaths with all resolved paths for this repo.
    """
    if config is None:
        config = MatrixMouseConfig()

    # Resolve workspace_root the same way MatrixMousePaths.repo_paths() would,
    # so the paths are consistent whether called from the service or the CLI.
    if workspace_root is None:
        env_workspace = os.environ.get("WORKSPACE_PATH")
        workspace_root = (
            Path(env_workspace).resolve() if env_workspace
            else Path(repo_root).resolve().parent
        )
    else:
        workspace_root = Path(workspace_root).resolve()

    ws_paths = MatrixMousePaths(workspace_root=workspace_root)
    repo_name = Path(repo_root).resolve().name
    paths = ws_paths.repo_paths(repo_name)

    # Workspace side — always safe, never touches the repo
    _ensure_repo_state_dir(paths)
    _ensure_notes_file(paths)
    _ensure_workspace_ignore(paths)

    # Repo side — only if user has explicitly opted in
    _ensure_repo_config(paths)
    _ensure_docs_structure(paths, config)

    _verify_git(repo_root)
    _ensure_mirror(repo_root, workspace_root, repo_name)

    return paths


# ---------------------------------------------------------------------------
# Model validation
# ---------------------------------------------------------------------------

def validate_models(config: MatrixMouseConfig) -> None:
    """
    Verify all configured models are available and support tool calling.
    Pulls missing models automatically (Ollama only).
    Called once at service startup before the orchestrator starts.

    TODO: When LLM backend flexibility is implemented (#10), this function
    will delegate to the backend adapter's ensure_model() and
    is_model_available() methods rather than calling ollama directly.
    """
    models_to_check = {
        "coder":      (config.coder_model,       True),
        "manager":    (config.manager_model,     True),
        "critic":     (config.critic_model,     True), 
        "writer":     (config.writer_model,     True),
        "summarizer": (config.summarizer_model,  False),
    }
    # Deduplicate — same model may serve multiple roles
    seen: set[str] = set()
    for role, (model_name, requires_tools) in models_to_check.items():
        if model_name in seen:
            continue
        seen.add(model_name)
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
