"""
matrixmouse/tools/_safety.py

Path validation for all file-touching tools. Internal helper — not a tool module.

All file tools should call is_safe_path() before any filesystem operation.
Never import this module's PROJECT_ROOT directly — use is_safe_path() instead.

Safety model:
    - All paths must resolve to within PROJECT_ROOT (set at startup via configure())
    - HARDCODED_BLACKLIST patterns are always enforced, regardless of config
    - Additional patterns can be added via .matrixmouse/ignore (gitignore-style)
    - Patterns in .matrixmouse/ignore cannot override HARDCODED_BLACKLIST

Call configure(repo_root) once at startup before any tools are used.
"""

import logging
from fnmatch import fnmatch
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Hardcoded safety floor — these are NEVER overridable by config or ignore file
# ---------------------------------------------------------------------------
HARDCODED_BLACKLIST: list[str] = [
    ".env",
    ".env.*",
    "**/.env",
    "**/.env.*",
    "**/secrets.*",
    "**/*.pem",
    "**/*.key",
    "**/*.cert",
    "**/*.p12",
    "**/*.pfx",
    "/run/secrets/**",
    "**/.matrixmouse-secrets/**",
]

# ---------------------------------------------------------------------------
# Module state — set once at startup via configure()
# ---------------------------------------------------------------------------
_project_root: Path | None = None
_extra_patterns: list[str] = []


def configure(repo_root: Path, ignore_file: Path | None = None) -> None:
    """
    Initialise path safety with the project root and optional ignore file.

    Must be called once at startup before any file tools are used.
    Safe to call multiple times — later calls replace earlier configuration.

    Args:
        repo_root:   Absolute path to the project root. All file operations
                     must resolve to within this directory.
        ignore_file: Path to a .matrixmouse/ignore file containing additional
                     blacklist patterns (gitignore-style). If None, defaults to
                     <repo_root>/.matrixmouse/ignore. Missing file is silently ignored.
    """
    global _project_root, _extra_patterns

    _project_root = repo_root.resolve()
    _extra_patterns = []

    # Load extra patterns from ignore file
    if ignore_file is None:
        ignore_file = repo_root / ".matrixmouse" / "ignore"

    if ignore_file.exists():
        lines = ignore_file.read_text().splitlines()
        _extra_patterns = [
            line.strip()
            for line in lines
            if line.strip() and not line.strip().startswith("#")
        ]
        logger.info(
            "Loaded %d extra blacklist patterns from %s",
            len(_extra_patterns), ignore_file
        )
    else:
        logger.debug("No ignore file found at %s. Using defaults only.", ignore_file)

    logger.info("Path safety configured. Project root: %s", _project_root)


def is_safe_path(filepath: str, write: bool = False) -> tuple[bool, str]:
    """
    Validate that a path is safe to access.

    Checks:
        1. Path resolves successfully (no broken symlinks or invalid chars)
        2. Resolved path is inside PROJECT_ROOT
        3. Path does not match any hardcoded blacklist pattern
        4. Path does not match any pattern from .matrixmouse/ignore

    Args:
        filepath: The path to validate (absolute or relative).
        write:    True if this is a write operation. Reserved for future
                  use (e.g. read-only patterns). Currently unused.

    Returns:
        (True, resolved_path_str)  if the path is safe to access.
        (False, reason_str)        if the path should be rejected.
    """
    if _project_root is None:
        return False, (
            "Path safety not configured. "
            "Call _safety.configure(repo_root) at startup."
        )

    # --- Resolve the path ---
    try:
        resolved = Path(filepath).resolve()
    except Exception as e:
        return False, f"Could not resolve path: {e}"

    # --- Must be inside project root ---
    try:
        relative = resolved.relative_to(_project_root)
    except ValueError:
        return False, f"Path is outside project root ({_project_root}): {resolved}"

    relative_str = str(relative)

    # --- Check hardcoded blacklist (always enforced) ---
    for pattern in HARDCODED_BLACKLIST:
        if fnmatch(relative_str, pattern) or fnmatch(resolved.name, pattern):
            return False, (
                f"Path matches protected pattern '{pattern}'. "
                "This pattern cannot be overridden."
            )

    # --- Check extra patterns from ignore file ---
    for pattern in _extra_patterns:
        if fnmatch(relative_str, pattern) or fnmatch(resolved.name, pattern):
            return False, f"Path matches blacklisted pattern '{pattern}'"

    return True, str(resolved)


def project_root() -> Path:
    """
    Return the configured project root.
    Raises RuntimeError if configure() has not been called.
    """
    if _project_root is None:
        raise RuntimeError(
            "Path safety not configured. "
            "Call _safety.configure(repo_root) at startup."
        )
    return _project_root
