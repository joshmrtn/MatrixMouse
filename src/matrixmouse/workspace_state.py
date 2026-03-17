"""
matrixmouse/workspace_state.py

Persistent workspace-level state that is not per-task.

Stores orchestrator-level state that must survive service restarts:
    last_manager_review_at  — ISO timestamp of the last Manager review task
                              completion. Used by the orchestrator to decide
                              when to inject the next scheduled review.

    stale_clarification_tasks — dict mapping task_id → Manager task id for
                                 any stale clarification tasks currently in
                                 the queue. Used by /tasks/{id}/answer to
                                 cancel the Manager task when the human
                                 answers directly.

Storage: <workspace>/.matrixmouse/workspace_state.json
Owned by the matrixmouse service user. Written atomically via a temp file
to prevent corruption on crash.

All reads return safe defaults if the file is absent or corrupt — the
service must always start cleanly even with a missing state file.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Default state
# ---------------------------------------------------------------------------

_DEFAULT_STATE: dict = {
    "last_manager_review_at":  None,
    "stale_clarification_tasks": {},
}


# ---------------------------------------------------------------------------
# Read / write
# ---------------------------------------------------------------------------

def load(state_file: Path) -> dict:
    """
    Load workspace state from disk.

    Returns a copy of _DEFAULT_STATE if the file is absent or corrupt.
    Never raises — the service must start cleanly regardless of state
    file health.

    Args:
        state_file: Path to workspace_state.json.

    Returns:
        dict with all expected state keys present.
    """
    state = dict(_DEFAULT_STATE)

    if not state_file.exists():
        logger.debug("No workspace state file at %s — using defaults.", state_file)
        return state

    try:
        with open(state_file) as f:
            data = json.load(f)
        # Merge loaded data over defaults so new keys are always present
        state.update(data)
        logger.debug("Workspace state loaded from %s.", state_file)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(
            "Failed to load workspace state from %s: %s. Using defaults.",
            state_file, e,
        )

    return state


def save(state_file: Path, state: dict) -> None:
    """
    Write workspace state to disk atomically.

    Uses a temp file + rename to prevent corruption on crash mid-write.
    Logs a warning and returns normally on failure — a failed state write
    must not crash the service.

    Args:
        state_file: Path to workspace_state.json.
        state:      The full state dict to write.
    """
    try:
        state_file.parent.mkdir(parents=True, exist_ok=True)
        tmp_fd, tmp_path = tempfile.mkstemp(
            dir=state_file.parent, suffix=".tmp"
        )
        try:
            with os.fdopen(tmp_fd, "w") as f:
                json.dump(state, f, indent=2)
            os.replace(tmp_path, state_file)
            logger.debug("Workspace state saved to %s.", state_file)
        except Exception:
            # Clean up temp file if rename failed
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    except Exception as e:
        logger.warning("Failed to save workspace state to %s: %s", state_file, e)


# ---------------------------------------------------------------------------
# Accessors
# ---------------------------------------------------------------------------

def get_last_review_at(state: dict) -> Optional[datetime]:
    """
    Return the last Manager review timestamp as a timezone-aware datetime,
    or None if no review has been run yet.

    Args:
        state: Loaded state dict from load().

    Returns:
        datetime (UTC) or None.
    """
    raw = state.get("last_manager_review_at")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except (ValueError, TypeError) as e:
        logger.warning(
            "Could not parse last_manager_review_at %r: %s. Treating as None.",
            raw, e,
        )
        return None


def set_last_review_at(state: dict, dt: Optional[datetime] = None) -> None:
    """
    Update last_manager_review_at in the state dict (in-place).
    Defaults to now (UTC) if dt is not provided.
    Call save() after this to persist.

    Args:
        state: State dict to mutate.
        dt:    Timestamp to store. Defaults to now.
    """
    if dt is None:
        dt = datetime.now(timezone.utc)
    state["last_manager_review_at"] = dt.isoformat()


def register_stale_clarification_task(
    state: dict,
    blocked_task_id: str,
    manager_task_id: str,
) -> None:
    """
    Record that a stale clarification Manager task has been created for
    a blocked task. Used by /tasks/{id}/answer to cancel it if the human
    answers directly.

    Args:
        state:            State dict to mutate.
        blocked_task_id:  ID of the task waiting for clarification.
        manager_task_id:  ID of the Manager task created to handle it.
    """
    state.setdefault("stale_clarification_tasks", {})
    state["stale_clarification_tasks"][blocked_task_id] = manager_task_id


def get_stale_clarification_task(
    state: dict,
    blocked_task_id: str,
) -> Optional[str]:
    """
    Return the Manager task ID for a stale clarification task, if one exists.

    Args:
        state:           Loaded state dict.
        blocked_task_id: ID of the blocked task.

    Returns:
        Manager task ID string, or None.
    """
    return state.get("stale_clarification_tasks", {}).get(blocked_task_id)


def clear_stale_clarification_task(
    state: dict,
    blocked_task_id: str,
) -> None:
    """
    Remove the stale clarification task record for a blocked task.
    Call save() after this to persist.

    Args:
        state:           State dict to mutate.
        blocked_task_id: ID of the task whose clarification was answered.
    """
    state.get("stale_clarification_tasks", {}).pop(blocked_task_id, None)
    