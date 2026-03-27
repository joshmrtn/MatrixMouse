"""
matrixmouse/repository/memory_workspace_state_repository.py

In-memory implementation of WorkspaceStateRepository for use in tests.

No disk I/O, no SQLite. State lives entirely in Python dicts for the
duration of the test. Fast, zero setup, zero teardown.

Not for production use. Import directly in test code:

    from matrixmouse.repository.memory_workspace_state_repository import (
        InMemoryWorkspaceStateRepository,
    )

Behaviourally identical to SQLiteWorkspaceStateRepository for the
purposes of test coverage.
"""

from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from typing import Optional

from matrixmouse.repository.workspace_state_repository import (
    WorkspaceStateRepository,
    SessionContext,
    SessionMode,
)


class InMemoryWorkspaceStateRepository(WorkspaceStateRepository):
    """
    Dict-backed workspace state repository for testing.

    All operations are in memory. No threading concerns — tests are
    assumed to be single-threaded unless explicitly testing concurrency.
    """

    def __init__(self) -> None:
        self._store: dict = {}
        self._stale: dict[str, str] = {}
        self._sessions: dict[str, SessionContext] = {}
        self._merge_locks: dict[str, str] = {}
        self._merge_queues: dict[str, deque[str]] = {}
        self._repo_metadata: dict[str, dict] = {}

    # ------------------------------------------------------------------
    # Key-value primitives
    # ------------------------------------------------------------------

    def get(self, key: str):
        return self._store.get(key)

    def set(self, key: str, value) -> None:
        self._store[key] = value

    def delete(self, key: str) -> None:
        self._store.pop(key, None)

    # ------------------------------------------------------------------
    # Stale clarification tasks
    # ------------------------------------------------------------------

    def get_stale_clarification_task(
        self, blocked_task_id: str
    ) -> str | None:
        return self._stale.get(blocked_task_id)

    def register_stale_clarification_task(
        self, blocked_task_id: str, manager_task_id: str
    ) -> None:
        self._stale[blocked_task_id] = manager_task_id

    def clear_stale_clarification_task(self, blocked_task_id: str) -> None:
        self._stale.pop(blocked_task_id, None)

    def all_stale_clarification_tasks(self) -> dict[str, str]:
        return dict(self._stale)

    # ------------------------------------------------------------------
    # Session contexts
    # ------------------------------------------------------------------

    def get_session_context(
        self, task_id: str
    ) -> SessionContext | None:
        return self._sessions.get(task_id)

    def set_session_context(
        self, task_id: str, ctx: SessionContext
    ) -> None:
        self._sessions[task_id] = ctx

    def clear_session_context(self, task_id: str) -> None:
        self._sessions.pop(task_id, None)

    def get_active_session_contexts(
        self,
    ) -> list[tuple[str, SessionContext]]:
        return list(self._sessions.items())

    # ------------------------------------------------------------------
    # Merge locks
    # ------------------------------------------------------------------

    def acquire_merge_lock(self, branch: str, task_id: str) -> bool:
        if branch in self._merge_locks:
            return False
        self._merge_locks[branch] = task_id
        return True

    def release_merge_lock(self, branch: str, task_id: str) -> None:
        if self._merge_locks.get(branch) != task_id:
            return
        del self._merge_locks[branch]
        # Grant lock to next waiter automatically
        next_id = self.dequeue_next_merge_waiter(branch)
        if next_id:
            self._merge_locks[branch] = next_id

    def get_merge_lock_holder(self, branch: str) -> str | None:
        return self._merge_locks.get(branch)

    def enqueue_merge_waiter(self, branch: str, task_id: str) -> None:
        q = self._merge_queues.setdefault(branch, deque())
        if task_id not in q:
            q.append(task_id)

    def dequeue_next_merge_waiter(self, branch: str) -> str | None:
        q = self._merge_queues.get(branch)
        if not q:
            return None
        return q.popleft()

    # ------------------------------------------------------------------
    # Repo metadata and branch protection cache
    # ------------------------------------------------------------------

    def get_repo_metadata(self, repo_name: str) -> dict | None:
        return self._repo_metadata.get(repo_name)

    def set_repo_metadata(
        self,
        repo_name: str,
        provider: str,
        remote_url: str,
    ) -> None:
        existing = self._repo_metadata.get(repo_name, {})
        self._repo_metadata[repo_name] = {
            **existing,
            "provider":   provider,
            "remote_url": remote_url,
        }

    def get_protected_branches_cached(
        self, repo_name: str
    ) -> tuple[list[str], str] | None:
        meta = self._repo_metadata.get(repo_name)
        if not meta or not meta.get("cache_timestamp"):
            return None
        return meta.get("protected_branches", []), meta["cache_timestamp"]

    def set_protected_branches_cached(
        self,
        repo_name: str,
        branches: list[str],
    ) -> None:
        existing = self._repo_metadata.get(repo_name, {})
        self._repo_metadata[repo_name] = {
            **existing,
            "protected_branches": branches,
            "cache_timestamp":    datetime.now(timezone.utc).isoformat(),
        }
        