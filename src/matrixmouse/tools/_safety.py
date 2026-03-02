"""
matrixmouse/tools/_safety.py

Path validation for all file operations.

All file tools must call is_safe_path() before reading or writing.
This module enforces that the agent cannot access files outside the
allowed roots or matching the blacklist patterns.

Configuration:
    configure() must be called once at startup.
    For single-repo tasks: pass repo_root only.
    For cross-repo tasks:  pass allowed_roots with all permitted roots.

Blacklist:
    HARDCODED_BLACKLIST — always enforced, cannot be overridden.
    Extra patterns loaded from <repo_root>/.matrixmouse/ignore.
"""

import fnmatch
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Hardcoded blacklist — never overridable
# ---------------------------------------------------------------------------

HARDCODED_BLACKLIST = [
    ".env",
    ".env.*",
    "**/secrets.*",
    "**/*.pem",
    "**/*.key",
    "**/*.cert",
    "**/*.p12",
    "**/*.pfx",
    "/run/secrets/**",          # Docker secrets mount
    "**/.matrixmouse-secrets/**",  # host secrets directory
]


# ---------------------------------------------------------------------------
# Module-level state — set by configure()
# ---------------------------------------------------------------------------

_allowed_roots: list[Path] = []
_extra_patterns: list[str] = []


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def configure(
    repo_root: Path | None = None,
    allowed_roots: list[Path] | None = None,
    ignore_file: Path | None = None,
) -> None:
    """
    Initialise path safety.

    For single-repo tasks pass repo_root. For cross-repo tasks pass
    allowed_roots with all permitted directories. If both are given,
    repo_root is appended to allowed_roots.

    Must be called once at startup before any file tools are used.
    Safe to call again — later calls replace earlier configuration,
    which is needed when the orchestrator switches between tasks that
    span different repo sets.

    Args:
        repo_root:     Primary project root. Shorthand for single-repo use.
        allowed_roots: Explicit list of allowed root directories.
                       Replaces repo_root if both are given.
        ignore_file:   Path to a .matrixmouse/ignore file containing
                       additional blacklist patterns. Defaults to
                       <repo_root>/.matrixmouse/ignore.
    """
    global _allowed_roots, _extra_patterns

    # Build the allowed roots list
    roots: list[Path] = []
    if allowed_roots:
        roots = [r.resolve() for r in allowed_roots]
    if repo_root:
        resolved = repo_root.resolve()
        if resolved not in roots:
            roots.append(resolved)

    if not roots:
        raise ValueError(
            "configure() requires at least one of repo_root or allowed_roots."
        )

    _allowed_roots = roots
    _extra_patterns = []

    # Load extra patterns from ignore file
    if ignore_file is None and repo_root:
        ignore_file = repo_root / ".matrixmouse" / "ignore"

    if ignore_file and ignore_file.exists():
        lines = ignore_file.read_text().splitlines()
        _extra_patterns = [
            line.strip()
            for line in lines
            if line.strip() and not line.strip().startswith("#")
        ]
        logger.info(
            "Loaded %d extra blacklist patterns from %s",
            len(_extra_patterns), ignore_file,
        )
    else:
        logger.debug(
            "No ignore file at %s. Using defaults only.",
            ignore_file or "(none)",
        )

    logger.info(
        "Path safety configured. Allowed roots: %s",
        [str(r) for r in _allowed_roots],
    )


def reconfigure_for_task(repos: list[str], workspace_root: Path) -> None:
    """
    Reconfigure allowed roots for a specific task's repo list.

    Called by the orchestrator when starting a new task, so the safety
    module only permits access to the repos that task names.

    Args:
        repos:          List of repo subdirectory names from task.repo.
        workspace_root: Workspace root containing all repo subdirectories.
    """
    if not repos:
        logger.warning(
            "reconfigure_for_task called with empty repo list. "
            "Keeping existing safety configuration."
        )
        return

    roots = []
    for repo_name in repos:
        root = (workspace_root / repo_name).resolve()
        if not root.exists():
            logger.warning(
                "Repo '%s' does not exist at %s. "
                "Skipping from allowed roots.",
                repo_name, root,
            )
            continue
        roots.append(root)

    if not roots:
        logger.error(
            "No valid repo directories found for task repos: %s",
            repos,
        )
        return

    # Preserve the existing ignore file from the first repo
    ignore_file = roots[0] / ".matrixmouse" / "ignore"
    configure(allowed_roots=roots, ignore_file=ignore_file)


# ---------------------------------------------------------------------------
# Path validation
# ---------------------------------------------------------------------------

def is_safe_path(filepath: str | Path, write: bool = False) -> tuple[bool, str]:
    """
    Check whether a path is safe for the agent to access.

    A path is safe if:
        1. It resolves to within one of the allowed roots.
        2. It does not match any hardcoded or extra blacklist pattern.

    Args:
        filepath: Path to validate. May be relative (resolved from cwd)
                  or absolute.
        write:    If True, apply stricter write-specific checks in future.
                  Currently unused but reserved for per-pattern read/write
                  distinctions.

    Returns:
        (True, resolved_path_str) if safe.
        (False, reason_str) if not safe.
    """
    if not _allowed_roots:
        return False, (
            "Path safety not configured. "
            "Call _safety.configure() before using file tools."
        )

    try:
        resolved = Path(filepath).resolve()
    except Exception as e:
        return False, f"Could not resolve path '{filepath}': {e}"

    # Check against allowed roots — must be within at least one
    within_root = any(
        _is_within(resolved, root) for root in _allowed_roots
    )
    if not within_root:
        allowed = ", ".join(str(r) for r in _allowed_roots)
        return False, (
            f"Path '{resolved}' is outside the allowed roots ({allowed}). "
            f"The agent can only access files within the project."
        )

    # Check hardcoded blacklist
    for pattern in HARDCODED_BLACKLIST:
        if _matches(resolved, pattern):
            return False, (
                f"Path '{resolved}' matches a protected pattern ('{pattern}'). "
                f"This file cannot be accessed by the agent."
            )

    # Check extra patterns from ignore file
    for pattern in _extra_patterns:
        if _matches(resolved, pattern):
            return False, (
                f"Path '{resolved}' matches an ignored pattern ('{pattern}'). "
                f"Add or remove patterns in .matrixmouse/ignore."
            )

    return True, str(resolved)


def project_root() -> Path:
    """
    Return the primary project root (first in allowed_roots list).
    Used by tools that only need a single root for subprocess cwd.
    """
    if not _allowed_roots:
        raise RuntimeError(
            "Path safety not configured. "
            "Call _safety.configure() before using file tools."
        )
    return _allowed_roots[0]


def allowed_roots() -> list[Path]:
    """Return all currently allowed roots."""
    return list(_allowed_roots)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _is_within(path: Path, root: Path) -> bool:
    """Return True if path is root or a descendant of root."""
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _matches(path: Path, pattern: str) -> bool:
    """
    Return True if path matches a blacklist pattern.

    Patterns starting with / are matched against the absolute path string.
    All other patterns are matched against each component and the full
    path using fnmatch, so '*.key' matches any .key file anywhere.
    """
    path_str = str(path)

    if pattern.startswith("/"):
        # Absolute pattern — match against full path
        return fnmatch.fnmatch(path_str, pattern)

    # Match against full path
    if fnmatch.fnmatch(path_str, f"*/{pattern}") or fnmatch.fnmatch(path_str, pattern):
        return True

    # Match against filename only
    if fnmatch.fnmatch(path.name, pattern):
        return True

    # Match ** glob patterns against full path
    if "**" in pattern:
        import re
        regex = fnmatch.translate(pattern).replace(r"(?s:.*)", ".*")
        if re.search(regex, path_str):
            return True

    return False
