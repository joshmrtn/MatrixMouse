"""
matrixmouse/tools/_safety.py

Path validation for all file operations.

All file tools must call is_safe_path() before reading or writing.
This module enforces that the agent cannot access files outside the
allowed roots or matching any blacklist pattern.

Configuration:
    configure() must be called once at startup with workspace-level roots.
    reconfigure_for_task() is called per-task to scope allowed roots to
    the repos named in that task.

Ignore file loading — three layers, all additive:
    1. <workspace>/.matrixmouse/ignore          workspace-wide rules
    2. <workspace>/.matrixmouse/<repo>/ignore   per-repo local rules (untracked)
    3. <repo>/.matrixmouse/ignore               team-shared rules (version controlled)

All three pattern sets are unioned — a path is blocked if it matches
any pattern from any layer. There is no override or precedence;
blacklists are always additive.
"""

import fnmatch
import logging
from pathlib import Path
from typing import Optional

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
    "/run/secrets/**",
    "**/.matrixmouse-secrets/**",
    "/etc/matrixmouse/**",      # service config + credentials — never accessible
]


# ---------------------------------------------------------------------------
# Module-level state — set by configure() / reconfigure_for_task()
# ---------------------------------------------------------------------------

_allowed_roots: list[Path] = []
_extra_patterns: list[str] = []


# ---------------------------------------------------------------------------
# Ignore file loading
# ---------------------------------------------------------------------------

def _load_ignore_file(path: Path) -> list[str]:
    """
    Load non-comment, non-empty lines from a single ignore file.
    Returns an empty list if the file does not exist.
    """
    if not path.exists():
        return []
    patterns = [
        line.strip()
        for line in path.read_text().splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    if patterns:
        logger.debug("Loaded %d pattern(s) from %s", len(patterns), path)
    return patterns


def _load_all_ignore_patterns(
    workspace_root: Path,
    repo_roots: list[Path],
) -> list[str]:
    """
    Merge ignore patterns from all three layers for the given repo set.

    Layer 1 — workspace-wide (applies to all repos):
        <workspace>/.matrixmouse/ignore

    Layer 2 — per-repo local (untracked, machine-local overrides):
        <workspace>/.matrixmouse/<repo_name>/ignore  for each repo

    Layer 3 — team-shared (version controlled, per-repo):
        <repo_root>/.matrixmouse/ignore  for each repo (may not exist)

    All patterns are collected into a single list. A path is blocked
    if it matches any pattern from any layer.

    Args:
        workspace_root: Root of the MatrixMouse workspace.
        repo_roots:     Resolved paths to each repo in the current task.

    Returns:
        Deduplicated list of all extra blacklist patterns.
    """
    all_patterns: list[str] = []

    # Layer 1 — workspace-wide
    ws_ignore = workspace_root / ".matrixmouse" / "ignore"
    all_patterns.extend(_load_ignore_file(ws_ignore))

    for repo_root in repo_roots:
        repo_name = repo_root.name

        # Layer 2 — per-repo local (workspace state dir)
        local_ignore = workspace_root / ".matrixmouse" / repo_name / "ignore"
        all_patterns.extend(_load_ignore_file(local_ignore))

        # Layer 3 — team-shared (inside the repo, version controlled)
        repo_ignore = repo_root / ".matrixmouse" / "ignore"
        all_patterns.extend(_load_ignore_file(repo_ignore))

    # Deduplicate while preserving order
    seen: set[str] = set()
    deduped = []
    for p in all_patterns:
        if p not in seen:
            seen.add(p)
            deduped.append(p)

    logger.info(
        "Loaded %d extra blacklist pattern(s) across %d repo(s).",
        len(deduped), len(repo_roots),
    )
    return deduped


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def configure(
    repo_root: Optional[Path] = None,
    allowed_roots: Optional[list[Path]] = None,
    workspace_root: Optional[Path] = None,
) -> None:
    """
    Initialise path safety.

    For single-repo use, pass repo_root. For cross-repo tasks, pass
    allowed_roots with all permitted directories. If both are given,
    repo_root is appended to allowed_roots.

    Pass workspace_root to enable multi-layer ignore file loading.
    Without it, only Layer 3 (repo-side) ignore files are loaded.

    Must be called once at startup before any file tools are used.
    Safe to call again — later calls replace earlier configuration.

    Args:
        repo_root:       Primary project root. Shorthand for single-repo use.
        allowed_roots:   Explicit list of allowed root directories.
        workspace_root:  Workspace root for loading all three ignore layers.
    """
    global _allowed_roots, _extra_patterns

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

    if workspace_root is not None:
        _extra_patterns = _load_all_ignore_patterns(workspace_root, roots)
    else:
        # Fallback: load only repo-side ignore files (Layer 3 only)
        patterns: list[str] = []
        for root in roots:
            patterns.extend(_load_ignore_file(root / ".matrixmouse" / "ignore"))
        _extra_patterns = patterns
        if not workspace_root:
            logger.debug(
                "workspace_root not provided — loaded repo-side ignore files only."
            )

    logger.info(
        "Path safety configured. Allowed roots: %s",
        [str(r) for r in _allowed_roots],
    )


def reconfigure_for_task(
    repos: list[str],
    workspace_root: Path,
) -> None:
    """
    Reconfigure allowed roots and ignore patterns for a specific task.

    Called by the orchestrator at the start of each task so the safety
    module only permits access to the repos that task names, and loads
    all three ignore layers for those repos.

    Args:
        repos:          Repo directory names from task.repo.
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
                "Repo '%s' not found at %s — skipping.", repo_name, root
            )
            continue
        roots.append(root)

    if not roots:
        logger.error(
            "No valid repo directories found for task repos: %s", repos
        )
        return

    configure(allowed_roots=roots, workspace_root=workspace_root)


# ---------------------------------------------------------------------------
# Path validation
# ---------------------------------------------------------------------------

def is_safe_path(
    filepath: str | Path,
    write: bool = False,
) -> tuple[bool, str]:
    """
    Check whether a path is safe for the agent to access.

    A path is safe if:
        1. It resolves to within one of the allowed roots.
        2. It does not match any hardcoded blacklist pattern.
        3. It does not match any loaded extra pattern.

    Args:
        filepath: Path to validate. May be relative or absolute.
        write:    Reserved for future per-pattern read/write distinctions.

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

    # Must be within at least one allowed root
    within_root = any(_is_within(resolved, root) for root in _allowed_roots)
    if not within_root:
        allowed = ", ".join(str(r) for r in _allowed_roots)
        return False, (
            f"Path '{resolved}' is outside the allowed roots ({allowed}). "
            f"The agent can only access files within the configured repos."
        )

    # Hardcoded blacklist — always enforced
    for pattern in HARDCODED_BLACKLIST:
        if _matches(resolved, pattern):
            return False, (
                f"Path '{resolved}' matches a protected pattern ('{pattern}'). "
                f"This file cannot be accessed by the agent."
            )

    # Extra patterns from ignore files
    for pattern in _extra_patterns:
        if _matches(resolved, pattern):
            return False, (
                f"Path '{resolved}' matches an ignored pattern ('{pattern}'). "
                f"See workspace or repo .matrixmouse/ignore to adjust."
            )

    return True, str(resolved)


def project_root() -> Path:
    """
    Return the primary project root (first in allowed_roots).
    Used by tools that need a single root for subprocess cwd.
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
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _matches(path: Path, pattern: str) -> bool:
    """
    Return True if path matches a blacklist pattern.

    Patterns starting with / are matched against the absolute path string.
    All other patterns are matched against the full path and filename
    using fnmatch, so '*.key' matches any .key file anywhere.
    """
    import re

    path_str = str(path)

    if pattern.startswith("/"):
        return fnmatch.fnmatch(path_str, pattern)

    # Full path match
    if fnmatch.fnmatch(path_str, f"*/{pattern}") or fnmatch.fnmatch(path_str, pattern):
        return True

    # Filename-only match
    if fnmatch.fnmatch(path.name, pattern):
        return True

    # ** glob match against full path
    if "**" in pattern:
        regex = fnmatch.translate(pattern).replace(r"(?s:.*)", ".*")
        if re.search(regex, path_str):
            return True

    return False
