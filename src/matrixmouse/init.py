"""
matrixmouse/init.py

Everything related to setting up a repo for matrixmouse

"""

from pathlib import Path
import logging
import ollama

logger = logging.getLogger(__name__)

from matrixmouse.config import MatrixMouseConfig, MatrixMousePaths

def _generate_starter_config() -> str:                                               
    """
    Generate the contents of a starter config.toml from MatrixMouseConfig field metadata.
    All fields are commented out so the file documents available options without
    overriding any defaults.

    Returns:
        A TOML-formatted string ready to write to disk.
    """
    lines = [
        "# MatrixMouse repo-local configuration",
        "# Any values set here override your global config at ~/.config/matrixmouse/config.toml",
        "# Remove the leading '#' from a line to activate that setting.",
        "",
        ]

    for name, field_info in MatrixMouseConfig.model_fields.items():
        if field_info.description:
            lines.append(f"# {field_info.description}")

        default = field_info.default
        if isinstance(default, bool):
            lines.append(f"# {name} = {str(default).lower()}")
        elif isinstance(default, str):
            lines.append(f'# {name} = "{default}"')
        else:
            lines.append(f"# {name} = {default}")

        lines.append("")

    return "\n".join(lines)


def _ensure_starter_config(paths: MatrixMousePaths) -> None:
    """
    Write a starter config to <repo_root>/.matrixmouse/config.toml if one does
    not already exist. Safe to call on every startup.

    Args:
        paths (MatrixMousePaths): Root directory of the repo.

    Returns:
        Path to the config file.
    """
    config_dir = paths.config_dir 
    config_path = config_dir / "config.toml"

    if not config_path.exists():
        config_dir.mkdir(parents=True, exist_ok=True)
        config_path.write_text(_generate_starter_config())

    return config_path


def _verify_git(repo_root: Path) -> None:
    """
    Confirm the repo root is a git repository. Logs a warning if not,
    but does not abort — the agent can still run without git tools.
    """
    import subprocess
    result = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        logger.warning(
            "No git repository detected at %s. Git tools will not function.", repo_root
        )
    else:
        logger.info("Git repository confirmed at %s", repo_root)




def _ensure_gitignore(repo_root: Path) -> None:
    """
    Ensure .matrixmouse/ runtime files are excluded from version control.
    Appends entries to .gitignore only if not already present.
    Never modifies existing entries or reformats the file.
    """
    gitignore_path = repo_root / ".gitignore"

    entries_to_add = [
        (".matrixmouse/AGENT_NOTES.md", "MatrixMouse agent working memory"),
        (".matrixmouse/agent.log",       "MatrixMouse session log"),
    ]

    existing = gitignore_path.read_text() if gitignore_path.exists() else ""

    additions = []
    for pattern, comment in entries_to_add:
        if pattern not in existing:
            additions.append(f"# {comment}\n{pattern}")

    if additions:
        with open(gitignore_path, "a") as f:
            f.write("\n# MatrixMouse\n")
            f.write("\n".join(additions) + "\n")
        logger.info("Updated .gitignore with MatrixMouse entries")

def _ensure_notes_file(paths: MatrixMousePaths) -> None:
    """
    Create AGENT_NOTES.md if it doesn't exist.
    Does not overwrite existing content.
    """
    if paths.agent_notes.exists():
        return

    paths.agent_notes.write_text(
        "# MatrixMouse Agent Notes\n\n"
        "This file is the agent's working memory. "
        "It is volatile and should not be version controlled.\n\n"
        "## file_map\n\n"
        "## key_functions\n\n"
        "## open_questions\n\n"
        "## completed_subtasks\n\n"
        "## known_issues\n\n"
    )
    logger.debug("Created %s", paths.agent_notes)


def _ensure_design_template(design_dir: Path) -> None:
    """Create docs/design/ and write template.md if missing."""
    design_dir.mkdir(parents=True, exist_ok=True)

    template_path = design_dir / "template.md"
    if template_path.exists():
        return

    template_path.write_text(
        "---\n"
        "module: module.name\n"
        "status: draft              # draft | critique | approved | implementing | complete | superseded\n"
        "depends_on: []\n"
        "implemented: false\n"
        "last_amended: YYYY-MM-DD\n"
        "---\n"
        "\n"
        "## Responsibility\n"
        "\n"
        "Single paragraph. What this module does and does not do.\n"
        "\n"
        "## Public Interface\n"
        "\n"
        "Function signatures with type annotations and docstrings. No bodies.\n"
        "\n"
        "```python\n"
        "def example(arg: str) -> bool:\n"
        '    """Brief description. Raises XError if ..."""\n'
        "```\n"
        "\n"
        "## Design Decisions\n"
        "\n"
        "Key choices made and brief rationale. One decision per bullet.\n"
        "\n"
        "## Open Questions\n"
        "\n"
        "Unresolved ambiguities. Any item here blocks `approved` status.\n"
        "\n"
        "## Amendments\n"
        "\n"
        "Append-only log of changes after initial approval.\n"
        "Never edit prior entries — add new ones below.\n"
        "\n"
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
        "# NNNN. Title of Decision\n"
        "\n"
        "Date: YYYY-MM-DD\n"
        "Status: proposed  # proposed | accepted | deprecated | superseded by [NNNN](NNNN-title.md)\n"
        "\n"
        "## Context\n"
        "\n"
        "What is the issue that motivated this decision?\n"
        "Describe the forces at play: technical, political, social, project-specific.\n"
        "\n"
        "## Decision\n"
        "\n"
        "What was decided. State it in full sentences, actively:\n"
        "\"We will use X because Y.\"\n"
        "\n"
        "## Consequences\n"
        "\n"
        "What becomes easier or harder as a result of this decision.\n"
        "Include both positive and negative consequences.\n"
        "\n"
        "## Alternatives Considered\n"
        "\n"
        "What other options were evaluated and why they were not chosen.\n"
    )
    logger.debug("Created ADR template at %s", template_path)



def _ensure_docs_structure(paths: MatrixMousePaths) -> None:
    """
    Scaffold the docs/ directory structure at repo root if it doesn't exist.

    Creates:
        docs/design/    — per-module design artifacts (one file per module)
        docs/adr/       — Architectural Decision Records (MADR format)

    Template files are written only if they don't already exist.
    Existing content is never overwritten.
    """
    _ensure_design_template(paths.design_docs)
    _ensure_adr_template(paths.design_docs.parent / "adr")


def _ensure_matrixmouse_dir(paths: MatrixMousePaths) -> None:
    """
    Create the .matrixmouse/ directory if it doesn't exist.
    Must be called before any other _ensure_* functions since they all
    write files into this directory.

    Args:
        paths: Resolved MatrixMousePaths for the current session.
    """
    if not paths.config_dir.exists():
        paths.config_dir.mkdir(parents=True, exist_ok=True)
        logger.info("Created .matrixmouse/ at %s", paths.config_dir)
    else:
        logger.debug(".matrixmouse/ already exists at %s", paths.config_dir)


def _build_paths(repo_root: Path, workspace_root: Path | None = None) -> MatrixMousePaths:
    """
    Resolve all standard MatrixMouse paths from the repo root.

    Args:
        repo_root:      Absolute path to the root of the repo being worked on.
        workspace_root: Absolute path to the MatrixMouse workspace root.
                        If None, falls back to WORKSPACE_PATH env var,
                        then defaults to repo_root's parent.

    Returns:
        A MatrixMousePaths instance with all paths resolved.
    """
    import os

    resolved_repo = repo_root.resolve()

    if workspace_root is None:
        env_workspace = os.environ.get("WORKSPACE_PATH")
        workspace_root = Path(env_workspace).resolve() if env_workspace \
                         else resolved_repo.parent

    return MatrixMousePaths(
        workspace_root=workspace_root.resolve(),
        repo_root=resolved_repo,
        config_dir=resolved_repo / ".matrixmouse",
        log_file=resolved_repo / ".matrixmouse" / "agent.log",
        agent_notes=resolved_repo / ".matrixmouse" / "AGENT_NOTES.md",
        design_docs=resolved_repo / "docs" / "design",
    )

def _ensure_ignore_file(paths: MatrixMousePaths) -> None:
    """
    Write a starter .matrixmouse/ignore file if one does not exist.
    Patterns here are appended to the hardcoded safety blacklist in _safety.py.
    """
    ignore_path = paths.config_dir / "ignore"
    if ignore_path.exists():
        return

    ignore_path.write_text(
        "# MatrixMouse ignore file\n"
        "# Paths matching these patterns cannot be read or written by the agent.\n"
        "# Uses fnmatch syntax (same as .gitignore glob patterns).\n"
        "# Lines starting with # are comments.\n"
        "#\n"
        "# The following patterns are always enforced regardless of this file:\n"
        "#   .env, .env.*, **/secrets.*, **/*.pem, **/*.key\n"
        "#\n"
        "# Add project-specific patterns below:\n"
        "# pyproject.toml\n"
        "# src/matrixmouse/main.py\n"
    )
    logger.debug("Created .matrixmouse/ignore at %s", ignore_path)


def setup_repo(repo_root: Path, workspace_root: Path | None = None) -> MatrixMousePaths:
    """
    Idempotent repo setup. Safe to call on every run.
    Creates .matrixmouse/ structure, writes starter config if missing,
    ensures .gitignore entries, scaffolds docs structure, verifies git.

    Args:
        repo_root:      Root directory of the repo being worked on.
        workspace_root: Root of the MatrixMouse workspace. Optional —
                        falls back to WORKSPACE_PATH env var or repo parent.

    Returns:
        MatrixMousePaths object containing relevant paths in the repo.
    """
    paths = _build_paths(repo_root, workspace_root)
    _ensure_matrixmouse_dir(paths)
    _ensure_starter_config(paths)
    _ensure_notes_file(paths)
    _ensure_gitignore(repo_root)
    _ensure_docs_structure(paths)
    _ensure_ignore_file(paths)
    _verify_git(repo_root)
    return paths


def validate_models(config: MatrixMouseConfig) -> None:
    """
    Verify all configured models are available and support tools.
    Attempts to pull missing models. Raises on unsupported capabilities.
    Called once at startup in cmd_run before the orchestrator starts.
    """
    models_to_check = {
        "coder": config.coder,
        "planner": config.planner,
        "judge": config.judge,
        # summarizer doesn't need tool support
        "summarizer": (config.summarizer, False),
    }

    for role, model_name in models_to_check.items():
        requires_tools = True
        if isinstance(model_name, tuple):
            model_name, requires_tools = model_name

        _ensure_model_available(model_name)

        if requires_tools:
            _ensure_model_supports_tools(model_name, role)


def _ensure_model_available(model_name: str) -> None:
    """Pull the model if not already present."""
    try:
        ollama.show(model_name)
        logger.info("Model available: %s", model_name)
    except ollama.ResponseError as e:
        if e.status_code == 404:
            logger.info("Model %s not found locally. Pulling...", model_name)
            print(f"Pulling model {model_name}...")
            ollama.pull(model_name)
            logger.info("Model %s pulled successfully.", model_name)
        else:
            raise


def _ensure_model_supports_tools(model_name: str, role: str) -> None:
    """Raise a clear error if the model doesn't support tool calling."""
    info = ollama.show(model_name)
    capabilities = getattr(info, "capabilities", []) or []
    if "tools" not in capabilities:
        raise ValueError(
            f"Model '{model_name}' (configured for role '{role}') does not support "
            f"tool calling. Choose a model with 'tools' in its capabilities. "
            f"Run 'ollama show {model_name}' to check."
        )
