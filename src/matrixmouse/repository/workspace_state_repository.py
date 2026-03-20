"""
matrixmouse/repository/workspace_state_repository.py

Abstract base class for workspace state persistence.

WorkspaceStateRepository manages orchestrator-level state that must survive
service restarts. It has two concerns:

    1. A general key-value store for simple scalar and structured values
       (last_manager_review_at, last_review_summary, etc.)

    2. A normalised stale_clarification_tasks table mapping blocked task IDs
       to the Manager task IDs created to handle them. Stored as a proper
       table rather than a JSON blob to avoid read-modify-write races when
       multiple workers are running.

Both concerns live in the same SQLite database as the task repository,
in separate tables.

Do not add scheduling logic, agent logic, or tool dispatch here.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any


class WorkspaceStateRepository(ABC):
    """
    Abstract interface for workspace state persistence.

    Thread-safe. All writes must be atomic.
    """

    # ------------------------------------------------------------------
    # General key-value store — implement in concrete classes
    # ------------------------------------------------------------------

    @abstractmethod
    def get(self, key: str) -> Any | None:
        """
        Return the value stored under key, or None if absent.

        Values are returned as their original Python types — the
        implementation handles deserialisation from TEXT storage.
        """

    @abstractmethod
    def set(self, key: str, value: Any) -> None:
        """
        Store value under key, overwriting any existing value.

        Value must be JSON-serialisable.
        """

    @abstractmethod
    def delete(self, key: str) -> None:
        """
        Remove the entry for key. No-op if key does not exist.
        """

    # ------------------------------------------------------------------
    # Stale clarification task registry — normalised table
    # Implement separately from the key-value store in concrete classes
    # ------------------------------------------------------------------

    @abstractmethod
    def get_stale_clarification_task(
        self, blocked_task_id: str
    ) -> str | None:
        """
        Return the Manager task ID registered for the given blocked task,
        or None if no record exists.
        """

    @abstractmethod
    def register_stale_clarification_task(
        self,
        blocked_task_id: str,
        manager_task_id: str,
    ) -> None:
        """
        Record that manager_task_id was created to handle the stale
        clarification for blocked_task_id.

        If a record already exists for blocked_task_id, it is overwritten.
        """

    @abstractmethod
    def clear_stale_clarification_task(self, blocked_task_id: str) -> None:
        """
        Remove the stale clarification record for blocked_task_id.
        No-op if no record exists.
        """

    @abstractmethod
    def all_stale_clarification_tasks(self) -> dict[str, str]:
        """
        Return all registered stale clarification task mappings as a dict
        of blocked_task_id -> manager_task_id.

        Used on startup to reconstruct in-memory state if needed.
        """

    # ------------------------------------------------------------------
    # Typed convenience accessors — concrete, built on get/set
    # ------------------------------------------------------------------

    def get_last_review_at(self) -> datetime | None:
        """
        Return the last Manager review timestamp as a timezone-aware
        datetime, or None if no review has been run yet.
        """
        raw = self.get("last_manager_review_at")
        if not raw:
            return None
        try:
            dt = datetime.fromisoformat(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except (ValueError, TypeError):
            return None

    def set_last_review_at(self, dt: datetime | None = None) -> None:
        """
        Store the last Manager review timestamp.
        Defaults to now (UTC) if dt is not provided.
        """
        if dt is None:
            dt = datetime.now(timezone.utc)
        self.set("last_manager_review_at", dt.isoformat())

    def get_last_review_summary(self) -> str:
        """Return the summary from the last Manager review, or empty string."""
        return self.get("last_review_summary") or ""

    def set_last_review_summary(self, summary: str) -> None:
        """Store the summary from the last Manager review."""
        self.set("last_review_summary", summary)