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
from enum import Enum
from typing import Any

from dataclasses import dataclass
from matrixmouse.task import TaskStatus


@dataclass
class TokenUsageRecord:
    """A single token usage entry from the `token_usage` table.

    Attributes:
        provider: Provider name, e.g. "anthropic".
        model: Backend-local model identifier.
        input_tokens: Tokens consumed from the prompt.
        output_tokens: Tokens produced in the response.
        recorded_at: UTC datetime when the usage was recorded.
    """
    provider:      str
    model:         str
    input_tokens:  int
    output_tokens: int
    recorded_at:   datetime


@dataclass
class SessionContext:
    """Transient execution context for special agent sessions.

    Attached to a running task by the orchestrator when the task enters
    a non-normal execution mode. Cleared when the session ends.

    Attributes:
        mode: The session mode — `BRANCH_SETUP`, `MERGE_RESOLUTION`, or `PLANNING`.
        allowed_tools: Tool names available in this session. Overrides
            the role's default tool set entirely.
        system_prompt_addendum: Text appended to the role's base system prompt.
            Explains the current situation to the agent.
        turn_limit_override: If > 0, overrides config turn limit for this
            session. 0 means use config default.
    """
    mode:                   "SessionMode"
    allowed_tools:          set[str]
    system_prompt_addendum: str = ""
    turn_limit_override:    int = 0


class SessionMode(str, Enum):
    """Execution modes that restrict or modify agent tool access."""
    NORMAL           = "normal"
    BRANCH_SETUP     = "branch_setup"     # Manager before branch named
    MERGE_RESOLUTION = "merge_resolution" # Any role during conflict resolution
    PLANNING         = "planning"         # Manager during task decomposition


BRANCH_SETUP_TOOLS: frozenset[str] = frozenset({
    "get_task_info",
    "list_tasks",
    "set_branch",
    "declare_complete",
})

PLANNING_TOOLS: frozenset[str] = frozenset({
    "get_task_info",
    "list_tasks",
    "create_task",
    "split_task",
    "update_task",
    "set_branch",
    "declare_complete",
    "request_clarification",
})

MERGE_RESOLUTION_TOOLS: frozenset[str] = frozenset({
    "show_conflict",
    "resolve_conflict",
})


class WorkspaceStateRepository(ABC):
    """Abstract interface for workspace state persistence.

    Thread-safe. All writes must be atomic.
    """

    # ------------------------------------------------------------------
    # General key-value store — implement in concrete classes
    # ------------------------------------------------------------------

    @abstractmethod
    def get(self, key: str) -> Any | None:
        """Return the value stored under `key`, or None if absent.

        Values are returned as their original Python types — the
        implementation handles deserialisation from `TEXT` storage.

        Args:
            key: The storage key to look up.

        Returns:
            The stored value, or None if not found.
        """

    @abstractmethod
    def set(self, key: str, value: Any) -> None:
        """Store `value` under `key`, overwriting any existing value.

        Args:
            key: The storage key.
            value: The value to store. Must be JSON-serialisable.
        """

    @abstractmethod
    def delete(self, key: str) -> None:
        """Remove the entry for `key`. No-op if `key` does not exist.

        Args:
            key: The storage key to delete.
        """

    # ------------------------------------------------------------------
    # Stale clarification task registry — normalised table
    # Implement separately from the key-value store in concrete classes
    # ------------------------------------------------------------------

    @abstractmethod
    def get_stale_clarification_task(
        self, blocked_task_id: str
    ) -> str | None:
        """Return the Manager task ID registered for the given blocked task.

        Args:
            blocked_task_id: ID of the blocked task to look up.

        Returns:
            The registered Manager task ID, or None if no record exists.
        """

    @abstractmethod
    def register_stale_clarification_task(
        self,
        blocked_task_id: str,
        manager_task_id: str,
    ) -> None:
        """Record that `manager_task_id` was created to handle the stale clarification.

        If a record already exists for `blocked_task_id`, it is overwritten.

        Args:
            blocked_task_id: ID of the blocked task.
            manager_task_id: ID of the Manager task created to handle it.
        """

    @abstractmethod
    def clear_stale_clarification_task(self, blocked_task_id: str) -> None:
        """Remove the stale clarification record for `blocked_task_id`.

        No-op if no record exists.

        Args:
            blocked_task_id: ID of the blocked task.
        """

    @abstractmethod
    def all_stale_clarification_tasks(self) -> dict[str, str]:
        """Return all registered stale clarification task mappings.

        Used on startup to reconstruct in-memory state if needed.

        Returns:
            Dict of `blocked_task_id` -> `manager_task_id`.
        """

    # ------------------------------------------------------------------
    # Session contexts
    # ------------------------------------------------------------------

    @abstractmethod
    def get_session_context(self, task_id: str) -> SessionContext | None:
        """Return the active `SessionContext` for the given task.

        Args:
            task_id: ID of the task.

        Returns:
            The active SessionContext, or None if the task has no active session.
        """

    @abstractmethod
    def set_session_context(self, task_id: str, ctx: SessionContext) -> None:
        """Store or replace the `SessionContext` for the given task.

        Args:
            task_id: ID of the task.
            ctx: The SessionContext to store.
        """

    @abstractmethod
    def clear_session_context(self, task_id: str) -> None:
        """Remove the `SessionContext` for the given task. No-op if absent.

        Args:
            task_id: ID of the task.
        """

    @abstractmethod
    def get_active_session_contexts(self) -> list[tuple[str, SessionContext]]:
        """Return all active session contexts.

        Useful for orchestrator auditing and the web UI.

        Returns:
            List of `(task_id, SessionContext)` pairs.
        """

    # ------------------------------------------------------------------
    # Merge locks
    # ------------------------------------------------------------------

    @abstractmethod
    def acquire_merge_lock(self, branch: str, task_id: str) -> bool:
        """Attempt to acquire the merge lock for the given parent branch.

        Stale locks (held by a terminal or missing task, or older than
        24 hours) are cleared and re-acquired atomically.

        Args:
            branch: The parent branch being merged into.
            task_id: The task attempting the merge.

        Returns:
            True if the lock was acquired, False if it is held by another
            active task.
        """

    @abstractmethod
    def release_merge_lock(self, branch: str, task_id: str) -> None:
        """Release the merge lock for the given branch.

        No-op if the lock is not held by `task_id`.

        Args:
            branch: The parent branch.
            task_id: The task releasing the lock.
        """

    @abstractmethod
    def enqueue_merge_waiter(self, branch: str, task_id: str) -> None:
        """Add `task_id` to the FIFO queue of tasks waiting to merge into `branch`.

        Called when a task wants to merge into a branch that is currently
        locked. The task will be granted the lock automatically when the
        current holder releases it.

        Args:
            branch: The parent branch being merged into.
            task_id: The task waiting for the lock.
        """

    @abstractmethod
    def dequeue_next_merge_waiter(self, branch: str) -> str | None:
        """Remove and return the next `task_id` from the merge queue for `branch`.

        Called by `release_merge_lock` to grant the lock to the next waiter.

        Args:
            branch: The parent branch whose queue to pop from.

        Returns:
            The next task ID, or None if the queue is empty.
        """

    @abstractmethod
    def get_merge_lock_holder(self, branch: str) -> str | None:
        """Return the `task_id` currently holding the merge lock for the given branch.

        Args:
            branch: The parent branch to check.

        Returns:
            The holding task ID, or None if the branch is not locked.
        """

    # ------------------------------------------------------------------
    # Repo metadata and branch protection cache
    # ------------------------------------------------------------------

    @abstractmethod
    def get_repo_metadata(self, repo_name: str) -> dict | None:
        """Return metadata for the named repo, or None if not registered.

        Args:
            repo_name: Name of the repository.

        Returns:
            Metadata dict with keys: `provider`, `remote_url`, `protected_branches`,
            `cache_timestamp`.
        """

    @abstractmethod
    def set_repo_metadata(
        self,
        repo_name: str,
        provider: str,
        remote_url: str,
    ) -> None:
        """Store or update provider config for the named repo.

        Does not touch the protected_branches cache.

        Args:
            repo_name: Name of the repository.
            provider: Provider name (e.g. "github").
            remote_url: Remote URL of the repository.
        """

    @abstractmethod
    def get_protected_branches_cached(
        self, repo_name: str
    ) -> tuple[list[str], str] | None:
        """Return the cached protected branch list and its cache timestamp.

        Args:
            repo_name: Name of the repository.

        Returns:
            Tuple of `(branches, iso_timestamp)`, or None if no cache entry exists.
        """

    @abstractmethod
    def set_protected_branches_cached(
        self,
        repo_name: str,
        branches: list[str],
    ) -> None:
        """Update the protected branches cache for the named repo.

        Stamps `cache_timestamp` to now.

        Args:
            repo_name: Name of the repository.
            branches: List of protected branch names.
        """

    # ------------------------------------------------------------------
    # Typed convenience accessors — concrete, built on get/set
    # ------------------------------------------------------------------

    def get_last_review_at(self) -> datetime | None:
        """Return the last Manager review timestamp as a timezone-aware datetime.

        Returns:
            The timestamp, or None if no review has been run yet.
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
        """Store the last Manager review timestamp.

        Args:
            dt: The timestamp to store. Defaults to now (UTC).
        """
        if dt is None:
            dt = datetime.now(timezone.utc)
        self.set("last_manager_review_at", dt.isoformat())

    def get_last_review_summary(self) -> str:
        """Return the summary from the last Manager review.

        Returns:
            The summary string, or empty string if none exists.
        """
        return self.get("last_review_summary") or ""

    def set_last_review_summary(self, summary: str) -> None:
        """Store the summary from the last Manager review.

        Args:
            summary: The review summary string.
        """
        self.set("last_review_summary", summary)

    @abstractmethod
    def record_token_usage(
        self,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> None:
        """Record a token usage event.

        Also prunes rows older than `max_retention_hours` to keep the
        table bounded. Pruning is best-effort — failure is logged but
        does not prevent the record from being written.

        Args:
            provider: Provider name, e.g. "anthropic".
            model: Backend-local model identifier.
            input_tokens: Tokens consumed from the prompt.
            output_tokens: Tokens produced in the response.
        """

    @abstractmethod
    def get_token_usage_since(
        self,
        provider: str,
        since: datetime,
    ) -> list[TokenUsageRecord]:
        """Return all token usage records for the given provider since `since`.

        Used by `TokenBudgetTracker` to calculate rolling window usage
        and to determine when the budget will next be available.

        Args:
            provider: Provider name to filter by.
            since: Earliest `recorded_at` to include (UTC datetime).

        Returns:
            List of `TokenUsageRecord`, oldest first.
        """

    @abstractmethod
    def prune_token_usage(self, max_retention_hours: int = 25) -> int:
        """Delete token usage rows older than `max_retention_hours`.

        Called automatically by `record_token_usage`. Can also be called
        explicitly on startup to recover from a crash that left stale rows.

        The default retention of 25 hours is one hour beyond the longest
        standard rolling window (24h/day), ensuring no data needed for
        budget calculations is lost.

        Args:
            max_retention_hours: Rows older than this are deleted.

        Returns:
            Number of rows deleted.
        """