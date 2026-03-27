"""
matrixmouse/utils/task_utils.py

Pure utility functions for task graph analysis.

No persistence concerns here — these functions operate on task data
passed in by the caller. The repository is only accessed via the
callable argument, keeping these functions testable in isolation.
"""

from __future__ import annotations

import re
from typing import Callable


def detect_cycles(
    proposed_blocking_id: str,
    proposed_blocked_id: str,
    get_blocked_by: Callable[[str], list[str]],
) -> bool:
    """
    Returns True if adding the edge proposed_blocking_id -> proposed_blocked_id
    would create a cycle.

    A cycle exists if proposed_blocked_id is already an ancestor of
    proposed_blocking_id — i.e. proposed_blocking_id is reachable by
    following blocked_by edges from proposed_blocked_id.

    We detect this by traversing blocked_by edges starting from
    proposed_blocking_id and checking if we reach proposed_blocked_id.
    If we can reach proposed_blocked_id from proposed_blocking_id via
    existing edges, then adding the reverse edge creates a cycle.
    """
    if proposed_blocking_id == proposed_blocked_id:
        return True

    visited: set[str] = set()
    stack: list[str] = [proposed_blocking_id]

    while stack:
        current = stack.pop()
        if current in visited:
            continue
        visited.add(current)

        for blocker_id in get_blocked_by(current):
            if blocker_id == proposed_blocked_id:
                return True
            if blocker_id not in visited:
                stack.append(blocker_id)

    return False


# ---------------------------------------------------------------------------
# Branch slug validation
# ---------------------------------------------------------------------------

# Valid slug characters: lowercase letters, digits, hyphens, forward slashes.
# No consecutive hyphens, no consecutive slashes, no leading/trailing
# hyphens or slashes on any segment.
_SLUG_SEGMENT_RE = re.compile(r'^[a-z0-9][a-z0-9-]*[a-z0-9]$|^[a-z0-9]$')
_INVALID_CHARS_RE = re.compile(r'[^a-z0-9\-/]')

MAX_SLUG_LENGTH = 50


def validate_branch_slug(slug: str, prefix: str) -> str:
    """
    Validate a branch slug and return the full branch name.

    The slug is the human-meaningful part supplied by the Manager, e.g.
    'refactor/foobar'. The full branch name is '<prefix>/<slug>', e.g.
    'mm/refactor/foobar'.

    Validation rules:
        - Slug must not be empty
        - Slug length must not exceed MAX_SLUG_LENGTH characters
        - Only lowercase letters, digits, hyphens, and forward slashes allowed
        - No consecutive hyphens (--)
        - No consecutive slashes (//)
        - No leading or trailing hyphens or slashes
        - Each path segment (split by /) must be at least one character
          and must not start or end with a hyphen

    Args:
        slug:   The human-meaningful slug, e.g. 'refactor/foobar'.
        prefix: The agent branch prefix from config, e.g. 'mm'.

    Returns:
        The full branch name: '<prefix>/<slug>'.

    Raises:
        ValueError: With a descriptive message if validation fails.
    """
    if not slug:
        raise ValueError("Branch slug cannot be empty.")

    if len(slug) > MAX_SLUG_LENGTH:
        raise ValueError(
            f"Branch slug '{slug}' is {len(slug)} characters — "
            f"maximum is {MAX_SLUG_LENGTH}."
        )

    if _INVALID_CHARS_RE.search(slug):
        invalid = set(_INVALID_CHARS_RE.findall(slug))
        raise ValueError(
            f"Branch slug '{slug}' contains invalid characters: "
            f"{sorted(invalid)}. "
            f"Only lowercase letters, digits, hyphens, and forward slashes "
            f"are allowed."
        )

    if slug.startswith('/') or slug.endswith('/'):
        raise ValueError(
            f"Branch slug '{slug}' must not start or end with a slash."
        )

    if slug.startswith('-') or slug.endswith('-'):
        raise ValueError(
            f"Branch slug '{slug}' must not start or end with a hyphen."
        )

    if '//' in slug:
        raise ValueError(
            f"Branch slug '{slug}' must not contain consecutive slashes (//)."
        )

    if '--' in slug:
        raise ValueError(
            f"Branch slug '{slug}' must not contain consecutive hyphens (--)."
        )

    segments = slug.split('/')
    for segment in segments:
        if not segment:
            raise ValueError(
                f"Branch slug '{slug}' contains an empty path segment."
            )
        if not _SLUG_SEGMENT_RE.match(segment):
            raise ValueError(
                f"Branch slug segment '{segment}' in '{slug}' must not "
                f"start or end with a hyphen."
            )

    return f"{prefix}/{slug}"
