"""
matrixmouse/init.py

Everything related to setting up a repo for matrixmouse

"""


def _generate_starter_config() -> str:                                               """                                                                             Generate the contents of a starter config.toml from MatrixMouseConfig field metadata.
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


def _ensure_starter_config(paths) -> None:
    """
    Write a starter config to <repo_root>/.matrixmouse/config.toml if one does
    not already exist. Safe to call on every startup.

    Args:
        repo_root: Root directory of the repo.

    Returns:
        Path to the config file.
    """
    config_dir = repo_root / ".matrixmouse"
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
    """Create AGENT_NOTES.md if it doesn't exist."""

def _ensure_docs_structure(paths: MatrixMousePaths) -> None:
    """Scaffold docs/design/ and docs/adr/ with template files if missing."""

def setup_repo(repo_root: Path) -> MatrixMousePaths:
    """
    Idempotent repo setup. Safe to call on every run.
    Creates .matrixmouse/ structure, writes starter config if missing,
    ensures .gitignore entries, scaffolds docs structure, verifies git.

    Returns:
        MatrixMousePaths object containing relevant paths in the repo.
    """

    paths = _build_paths(repo_root)
    _ensure_matrixmouse_dir(paths)
    _ensure_starter_config(paths)
    _ensure_notes_file(paths)
    _ensure_gitignore(repo_root)
    _ensure_docs_structure(paths)
    _verify_git(repo_root)
    return paths
