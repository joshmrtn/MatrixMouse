"""
matrixmouse/init.py

Everything related to setting up a repo for matrixmouse

"""


def ensure_gitignore(repo_root: Path) -> None:
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


def ensure_notes_file(paths: MatrixMousePaths) -> None:
    """Create AGENT_NOTES.md if it doesn't exist."""

def ensure_docs_structure(paths: MatrixMousePaths) -> None:
    """Scaffold docs/design/ and docs/adr/ with template files if missing."""

def setup_repo(repo_root: Path) -> MatrixMousePaths:
    """
    Idempotent repo setup. Safe to call on every run.
    Creates .matrixmouse/ structure, writes starter config if missing,
    ensures .gitignore entries, scaffolds docs structure, verifies git.
    """

    paths = _build_paths(repo_root)
    _ensure_matrixmouse_dir(paths)
    _ensure_starter_config(paths)
    _ensure_notes_file(paths)
    _ensure_gitignore(repo_root)
    _ensure_docs_structure(paths)
    _verify_git(repo_root)
    return paths
