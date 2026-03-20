"""
matrixmouse/utils/task_utils.py

Pure utility functions for task graph analysis.

No persistence concerns here — these functions operate on task data
passed in by the caller. The repository is only accessed via the
callable argument, keeping these functions testable in isolation.
"""

from __future__ import annotations

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
