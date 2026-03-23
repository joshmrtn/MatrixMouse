"""
matrixmouse/repository/memory_task_repository.py

In-memory implementation of TaskRepository for use in tests.

No disk I/O, no SQLite. State lives entirely in Python dicts and sets
for the duration of the test. Fast, zero setup, zero teardown.

Not for production use. Import directly in test code:

    from matrixmouse.repository.memory_task_repository import (
        InMemoryTaskRepository,
    )

Behaviourally identical to SQLiteTaskRepository — the shared test suite
in tests/repository/ runs against both implementations to enforce this.
"""

from __future__ import annotations

import threading
import time
import uuid
import copy
import logging
from datetime import datetime, timezone
from typing import Callable, Optional

from matrixmouse.repository.task_repository import TaskRepository
from matrixmouse.task import AgentRole, Task, TaskStatus
from matrixmouse.utils.task_utils import detect_cycles

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


_TERMINAL = {TaskStatus.COMPLETE, TaskStatus.CANCELLED}
_NON_SCHEDULABLE = {TaskStatus.COMPLETE, TaskStatus.CANCELLED, TaskStatus.PENDING}

class InMemoryTaskRepository(TaskRepository):
    """
    Dict-backed task repository for testing.

    All operations are in memory. threading.Lock() is used as a simple 
    mutex lock to validate multi-threaded tests
    """

    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}
        # blocked_task_id -> set of blocking_task_ids
        self._blocked_by: dict[str, set[str]] = {}
        # blocking_task_id -> set of blocked_task_ids
        self._blocking: dict[str, set[str]] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Core CRUD
    # ------------------------------------------------------------------

    def add(self, task: Task) -> None:
        self._ensure_unique_id(task)
        self._tasks[task.id] = copy.copy(task)  # store a shallow copy
        self._blocked_by.setdefault(task.id, set())
        self._blocking.setdefault(task.id, set())

    def get(self, task_id: str) -> Task | None:
        # Exact match
        if task_id in self._tasks:
            return copy.copy(self._tasks[task_id])
        # Prefix match
        matches = [tid for tid in self._tasks if tid.startswith(task_id)]
        if len(matches) == 1:
            return copy.copy(self._tasks[matches[0]])
        if len(matches) > 1:
            raise ValueError(
                f"Ambiguous prefix '{task_id}' matches: "
                f"{[self._tasks[m].id for m in matches]}"
            )
        return None

    def update(self, task: Task) -> None:
        if task.id not in self._tasks:
            raise KeyError(f"Task '{task.id}' not found.")
        existing = self._tasks[task.id]
        if existing.branch and task.branch != existing.branch:
            raise ValueError(
                f"Task '{task.id}' branch is immutable once set. "
                f"Cannot change '{existing.branch}' to '{task.branch}'."
            )
        task.last_modified = _now_iso()
        self._tasks[task.id] = copy.copy(task)  # store a copy, don't alias

    def delete(self, task_id: str) -> None:
        if task_id not in self._tasks:
            raise KeyError(f"Task '{task_id}' not found.")
        # Remove all dependency edges
        for blocked_id in list(self._blocking.get(task_id, set())):
            self._blocked_by.get(blocked_id, set()).discard(task_id)
        for blocking_id in list(self._blocked_by.get(task_id, set())):
            self._blocking.get(blocking_id, set()).discard(task_id)
        self._blocking.pop(task_id, None)
        self._blocked_by.pop(task_id, None)
        del self._tasks[task_id]

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def all_tasks(self) -> list[Task]:
        return [copy.copy(t) for t in self._tasks.values()]

    def active_tasks(self) -> list[Task]:
        return [
            copy.copy(t) for t in self._tasks.values()
            if t.status not in _NON_SCHEDULABLE
        ]

    def completed_ids(self) -> set[str]:
        return {
            t.id for t in self._tasks.values()
            if t.status in _TERMINAL
        }

    def is_ready(self, task_id: str) -> bool:
        if task_id not in self._tasks:
            return False
        task = self._tasks[task_id]
        if task.status == TaskStatus.PENDING:
            return False
        blockers = self._blocked_by.get(task_id, set())
        return all(
            self._tasks[bid].status in _TERMINAL
            for bid in blockers
            if bid in self._tasks
        )

    def has_blockers(self, task_id: str) -> bool:
        if task_id not in self._tasks:
            return False
        task = self._tasks[task_id]
        if task.status == TaskStatus.PENDING:
            return False
        blockers = self._blocked_by.get(task_id, set())
        return any(
            self._tasks[bid].status not in _TERMINAL
            for bid in blockers
            if bid in self._tasks
        )

    # ------------------------------------------------------------------
    # Dependency graph queries
    # ------------------------------------------------------------------

    def get_subtasks(self, task_id: str) -> list[Task]:
        return [
            copy.copy(t) for t in self._tasks.values()
            if t.parent_task_id == task_id
        ]

    def get_blocked_by(self, task_id: str) -> list[Task]:
        return [
            copy.copy(self._tasks[bid])
            for bid in self._blocked_by.get(task_id, set())
            if bid in self._tasks
        ]

    def get_blocking(self, task_id: str) -> list[Task]:
        return [
            copy.copy(self._tasks[bid])
            for bid in self._blocking.get(task_id, set())
            if bid in self._tasks
        ]

    # ------------------------------------------------------------------
    # Dependency graph mutations
    # ------------------------------------------------------------------

    def add_dependency(
        self,
        blocking_task_id: str,
        blocked_task_id: str,
    ) -> None:
        for tid in (blocking_task_id, blocked_task_id):
            if tid not in self._tasks:
                raise KeyError(f"Task '{tid}' not found.")

        with self._lock:
            if blocking_task_id in self._blocked_by.get(blocked_task_id, set()):
                return

            def _get_blocked_by_ids(tid: str) -> list[str]:
                return list(self._blocked_by.get(tid, set()))

            if detect_cycles(blocking_task_id, blocked_task_id,
                            _get_blocked_by_ids):
                raise ValueError(
                    f"Adding dependency '{blocking_task_id}' → "
                    f"'{blocked_task_id}' would create a cycle. "
                    f"No changes made."
                )

            self._blocked_by.setdefault(blocked_task_id, set()).add(
                blocking_task_id
            )
            self._blocking.setdefault(blocking_task_id, set()).add(
                blocked_task_id
            )
            # Mutate stored object directly
            blocked_task = self._tasks[blocked_task_id]
            if blocked_task.status not in _TERMINAL:
                blocked_task.status = TaskStatus.BLOCKED_BY_TASK
                blocked_task.last_modified = _now_iso()

    def remove_dependency(
        self,
        blocking_task_id: str,
        blocked_task_id: str,
    ) -> None:
        self._blocked_by.get(blocked_task_id, set()).discard(blocking_task_id)
        self._blocking.get(blocking_task_id, set()).discard(blocked_task_id)

        if blocked_task_id in self._tasks:
            blocked_task = self._tasks[blocked_task_id]  # live reference
            if (
                blocked_task.status == TaskStatus.BLOCKED_BY_TASK
                and not self.has_blockers(blocked_task_id)
            ):
                blocked_task.status = TaskStatus.READY
                blocked_task.last_modified = _now_iso()

    # ------------------------------------------------------------------
    # Named state transitions
    # ------------------------------------------------------------------

    def mark_running(self, task_id: str) -> None:
        task = self._require(task_id)
        if not task.branch and task.role != AgentRole.MANAGER:
            raise ValueError(
                f"Task '{task_id}' (role={task.role.value}) cannot start: "
                f"no branch assigned. Set a branch before running."
            )
        if task.status != TaskStatus.READY:
            raise ValueError(
                f"Task '{task_id}' cannot transition to RUNNING from "
                f"{task.status.value}. Only READY tasks can become RUNNING."
            )
        now = _now_iso()
        task.status = TaskStatus.RUNNING
        task.time_slice_started = time.monotonic()
        if task.started_at is None:
            task.started_at = now
        task.last_modified = now

    def mark_ready(self, task_id: str) -> None:
        task = self._require(task_id)
        if task.status in _TERMINAL:
            raise ValueError(
                f"Task '{task_id}' is {task.status.value} and cannot "
                f"be returned to READY."
            )
        now = _now_iso()
        task.status = TaskStatus.READY
        task.time_slice_started = None
        task.last_modified = now

    def mark_complete(self, task_id: str) -> None:
        task = self._require(task_id)
        if task.status in _TERMINAL:
            # Already terminal — no-op
            return
        now = _now_iso()
        task.status = TaskStatus.COMPLETE
        task.completed_at = now
        task.last_modified = now

        previously_blocked = list(self._blocking.get(task_id, set()))
        self._blocking.get(task_id, set()).clear()
        for bid in previously_blocked:
            self._blocked_by.get(bid, set()).discard(task_id)
            if not self.has_blockers(bid) and bid in self._tasks:
                blocked_task = self._tasks[bid]
                if blocked_task.status == TaskStatus.BLOCKED_BY_TASK:
                    blocked_task.status = TaskStatus.READY
                    blocked_task.last_modified = now

    def mark_blocked_by_human(
        self, task_id: str, reason: str = ""
    ) -> None:
        task = self._require(task_id)
        if task.status in _TERMINAL:
            raise ValueError(
                f"Task '{task_id}' is {task.status.value} and cannot "
                f"be marked BLOCKED_BY_HUMAN."
            )
        now = _now_iso()
        task.status = TaskStatus.BLOCKED_BY_HUMAN
        if reason:
            entry = f"[BLOCKED] {reason}"
            task.notes = (
                entry if not task.notes
                else f"{task.notes}\n{entry}"
            )
        task.last_modified = now

    def mark_cancelled(self, task_id: str) -> None:
        task = self._require(task_id)
        if task.status == TaskStatus.COMPLETE:
            # Cannot cancel a completed task — no-op
            return
        now = _now_iso()
        task.status = TaskStatus.CANCELLED
        task.completed_at = now
        task.last_modified = now

    # ------------------------------------------------------------------
    # Subtask creation
    # ------------------------------------------------------------------

    def set_task_branch(
        self,
        task_id: str,
        full_branch_name: str,
        base_branch: str,
        create_git_branch: Callable[[str, str], tuple[bool, str, str]],
        delete_git_branch: Callable[[str], tuple[bool, str]],
    ) -> str:
        if task_id not in self._tasks:
            raise KeyError(f"Task '{task_id}' not found.")
        task = self._tasks[task_id]
        if task.branch:
            raise ValueError(
                f"Task '{task_id}' already has branch '{task.branch}'. "
                f"Branch names are permanent."
            )

        git_ok, git_err, head_hash = create_git_branch(
            full_branch_name, base_branch
        )
        if not git_ok:
            raise ValueError(
                f"Failed to create git branch '{full_branch_name}': {git_err}"
            )

        try:
            task.branch = full_branch_name
            task.wip_commit_hash = head_hash
            task.last_modified = _now_iso()
        except Exception as e:
            del_ok, del_err = delete_git_branch(full_branch_name)
            if not del_ok:
                logger.error(
                    "State update failed AND git rollback failed for '%s': "
                    "%s | %s",
                    full_branch_name, e, del_err,
                )
            task.branch = ""
            task.wip_commit_hash = ""
            raise ValueError(
                f"Failed to persist branch: {e}. Git branch rolled back."
            ) from e

        return full_branch_name

    def add_subtask(
        self,
        parent_id: str,
        title: str,
        description: str,
        create_git_branch: Callable[[str, str], tuple[bool, str, str]],
        delete_git_branch: Callable[[str], tuple[bool, str]],
        role: AgentRole | None = None,
        repo: list[str] | None = None,
        importance: float | None = None,
        urgency: float | None = None,
        **kwargs,
    ) -> Task:
        if parent_id not in self._tasks:
            raise KeyError(f"Parent task '{parent_id}' not found.")
        parent = self._tasks[parent_id]
        if not parent.branch:
            raise ValueError(
                f"Parent task '{parent_id}' has no branch. "
                f"Set a branch before creating subtasks."
            )

        now = _now_iso()
        subtask = Task(
            title=title,
            description=description,
            role=role if role is not None else parent.role,
            repo=repo if repo is not None else list(parent.repo),
            importance=importance if importance is not None else parent.importance,
            urgency=urgency if urgency is not None else parent.urgency,
            depth=parent.depth + 1,
            parent_task_id=parent_id,
            created_at=now,
            last_modified=now,
            **kwargs,
        )
        self._ensure_unique_id(subtask)

        branch_name = f"{parent.branch}/{subtask.id}"
        git_ok, git_err, head_hash = create_git_branch(branch_name, parent.branch)
        if not git_ok:
            raise ValueError(
                f"Failed to create git branch '{branch_name}': {git_err}"
            )

        subtask.branch = branch_name
        subtask.wip_commit_hash = head_hash

        try:
            self._tasks[subtask.id] = copy.copy(subtask)
            self._blocked_by.setdefault(subtask.id, set())
            self._blocking.setdefault(subtask.id, set())
            self._blocked_by.setdefault(parent_id, set()).add(subtask.id)
            self._blocking.setdefault(subtask.id, set()).add(parent_id)
            parent.status = TaskStatus.BLOCKED_BY_TASK
            parent.last_modified = now
        except Exception as e:
            del_ok, del_err = delete_git_branch(branch_name)
            if not del_ok:
                logger.error(
                    "State update failed AND git rollback failed for '%s': "
                    "%s | %s",
                    branch_name, e, del_err,
                )
            # Clean up partial state
            self._tasks.pop(subtask.id, None)
            self._blocked_by.get(subtask.id, set()).clear()
            self._blocking.get(subtask.id, set()).clear()
            self._blocked_by.get(parent_id, set()).discard(subtask.id)
            raise ValueError(
                f"Failed to create subtask: {e}. Git branch rolled back."
            ) from e

        return copy.copy(subtask)

    def add_subtasks(
        self,
        parent_id: str,
        subtasks: list[Task],
        create_git_branch: Callable[[str, str], tuple[bool, str, str]],
        delete_git_branch: Callable[[str], tuple[bool, str]],
    ) -> list[Task]:
        if parent_id not in self._tasks:
            raise KeyError(f"Parent task '{parent_id}' not found.")
        parent = self._tasks[parent_id]
        if not parent.branch:
            raise ValueError(
                f"Parent task '{parent_id}' has no branch. "
                f"Set a branch before creating subtasks."
            )
        if not subtasks:
            return []

        now = _now_iso()
        created_branches: list[str] = []

        with self._lock:
            try:
                for subtask in subtasks:
                    self._ensure_unique_id(subtask)
                    subtask.created_at = now
                    subtask.last_modified = now
                    branch_name = f"{parent.branch}/{subtask.id}"

                    git_ok, git_err, head_hash = create_git_branch(
                        branch_name, parent.branch
                    )
                    if not git_ok:
                        raise ValueError(
                            f"Failed to create git branch '{branch_name}': "
                            f"{git_err}"
                        )
                    subtask.branch = branch_name
                    subtask.wip_commit_hash = head_hash
                    created_branches.append(branch_name)

            except Exception:
                for branch_name in created_branches:
                    del_ok, del_err = delete_git_branch(branch_name)
                    if not del_ok:
                        logger.error(
                            "Git rollback failed for '%s': %s.",
                            branch_name, del_err,
                        )
                raise

            def _get_blocked_by_ids(tid: str) -> list[str]:
                return list(self._blocked_by.get(tid, set()))

            try:
                for subtask in subtasks:
                    if detect_cycles(subtask.id, parent_id, _get_blocked_by_ids):
                        raise ValueError(
                            f"Adding subtask '{subtask.id}' would create a cycle."
                        )
                    self._tasks[subtask.id] = copy.copy(subtask)
                    self._blocked_by.setdefault(subtask.id, set())
                    self._blocking.setdefault(subtask.id, set())
                    self._blocked_by.setdefault(parent_id, set()).add(subtask.id)
                    self._blocking.setdefault(subtask.id, set()).add(parent_id)

                parent.status = TaskStatus.BLOCKED_BY_TASK
                parent.last_modified = now

            except Exception as e:
                # Roll back in-memory state
                for subtask in subtasks:
                    self._tasks.pop(subtask.id, None)
                    self._blocked_by.pop(subtask.id, None)
                    self._blocking.pop(subtask.id, None)
                    self._blocked_by.get(parent_id, set()).discard(subtask.id)
                # Roll back git branches
                for branch_name in created_branches:
                    del_ok, del_err = delete_git_branch(branch_name)
                    if not del_ok:
                        logger.error(
                            "State rollback AND git rollback failed for '%s': "
                            "%s | %s. Orphaned branch requires manual cleanup.",
                            branch_name, e, del_err,
                        )
                raise ValueError(
                    f"Failed to create subtasks: {e}. "
                    f"All git branches rolled back."
                ) from e

        return [copy.copy(t) for t in subtasks]


    def commit_pending_subtree(self, root_task_id: str) -> list[str]:
        if root_task_id not in self._tasks:
            raise KeyError(f"Task '{root_task_id}' not found.")

        now = _now_iso()
        transitioned = []

        def collect_pending_descendants(task_id: str) -> list[str]:
            result = []
            for t in self._tasks.values():
                if t.parent_task_id == task_id and t.status == TaskStatus.PENDING:
                    result.append(t.id)
                    result.extend(collect_pending_descendants(t.id))
            return result

        pending_ids = collect_pending_descendants(root_task_id)

        for task_id in pending_ids:
            task = self._tasks[task_id]
            blockers = self._blocked_by.get(task_id, set())
            has_blockers = any(
                self._tasks[bid].status not in _TERMINAL
                for bid in blockers
                if bid in self._tasks
            )
            task.status = (
                TaskStatus.BLOCKED_BY_TASK
                if has_blockers
                else TaskStatus.READY
            )
            task.last_modified = now
            transitioned.append(task_id)

        return transitioned
    
    
    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _require(self, task_id: str) -> Task:
        """Return the live stored task object for internal mutation."""
        task = self._tasks.get(task_id)
        if task is None:
            raise KeyError(f"Task '{task_id}' not found.")
        return task  # intentionally returns live reference for mutation
    