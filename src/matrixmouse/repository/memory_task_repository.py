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
import logging
from datetime import datetime, timezone
from typing import Optional

from matrixmouse.repository.task_repository import TaskRepository
from matrixmouse.task import AgentRole, Task, TaskStatus
from matrixmouse.utils.task_utils import detect_cycles

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


_TERMINAL = {TaskStatus.COMPLETE, TaskStatus.CANCELLED}


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
        while task.id in self._tasks:
            old_id = task.id
            task.id = uuid.uuid4().hex[:16]
            logger.warning(
                "Task id collision on %r — regenerating to %r.",
                old_id, task.id,
            )
        self._tasks[task.id] = task
        self._blocked_by.setdefault(task.id, set())
        self._blocking.setdefault(task.id, set())

    def get(self, task_id: str) -> Task | None:
        # Exact match
        if task_id in self._tasks:
            return self._tasks[task_id]
        # Prefix match
        matches = [
            t for tid, t in self._tasks.items()
            if tid.startswith(task_id)
        ]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise ValueError(
                f"Ambiguous prefix '{task_id}' matches: "
                f"{[t.id for t in matches]}"
            )
        return None

    def update(self, task: Task) -> None:
        if task.id not in self._tasks:
            raise KeyError(f"Task '{task.id}' not found.")
        task.last_modified = _now_iso()
        self._tasks[task.id] = task

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
        return list(self._tasks.values())

    def active_tasks(self) -> list[Task]:
        return [
            t for t in self._tasks.values()
            if t.status not in _TERMINAL
        ]

    def completed_ids(self) -> set[str]:
        return {
            t.id for t in self._tasks.values()
            if t.status in _TERMINAL
        }

    def is_ready(self, task_id: str) -> bool:
        if task_id not in self._tasks:
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
            t for t in self._tasks.values()
            if t.parent_task_id == task_id
        ]

    def get_blocked_by(self, task_id: str) -> list[Task]:
        return [
            self._tasks[bid]
            for bid in self._blocked_by.get(task_id, set())
            if bid in self._tasks
        ]

    def get_blocking(self, task_id: str) -> list[Task]:
        return [
            self._tasks[bid]
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
            # No-op if already present
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
            blocked_task = self._tasks[blocked_task_id]
            if blocked_task.status not in _TERMINAL:
                blocked_task.status = TaskStatus.BLOCKED_BY_TASK
                blocked_task.last_modified = _now_iso()

    def remove_dependency(
        self,
        blocking_task_id: str,
        blocked_task_id: str,
    ) -> None:
        self._blocked_by.get(blocked_task_id, set()).discard(
            blocking_task_id
        )
        self._blocking.get(blocking_task_id, set()).discard(
            blocked_task_id
        )

    # ------------------------------------------------------------------
    # Named state transitions
    # ------------------------------------------------------------------

    def mark_running(self, task_id: str) -> None:
        task = self._require(task_id)
        now = _now_iso()
        task.status = TaskStatus.RUNNING
        task.time_slice_started = time.monotonic()
        if task.started_at is None:
            task.started_at = now
        task.last_modified = now

    def mark_ready(self, task_id: str) -> None:
        task = self._require(task_id)
        now = _now_iso()
        task.status = TaskStatus.READY
        task.time_slice_started = None
        task.last_modified = now

    def mark_complete(self, task_id: str) -> None:
        task = self._require(task_id)
        now = _now_iso()
        task.status = TaskStatus.COMPLETE
        task.completed_at = now
        task.last_modified = now

        # Find tasks this task was blocking, remove edges, unblock if clear
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
        now = _now_iso()
        task.status = TaskStatus.CANCELLED
        task.completed_at = now
        task.last_modified = now

    # ------------------------------------------------------------------
    # Subtask creation
    # ------------------------------------------------------------------

    def add_subtask(
        self,
        parent_id: str,
        title: str,
        description: str,
        role: AgentRole | None = None,
        repo: list[str] | None = None,
        importance: float | None = None,
        urgency: float | None = None,
        **kwargs,
    ) -> Task:
        parent = self.get(parent_id)
        if parent is None:
            raise KeyError(f"Parent task '{parent_id}' not found.")

        now = _now_iso()
        subtask = Task(
            title=title,
            description=description,
            role=role if role is not None else parent.role,
            repo=repo if repo is not None else list(parent.repo),
            importance=(
                importance if importance is not None else parent.importance
            ),
            urgency=(
                urgency if urgency is not None else parent.urgency
            ),
            depth=parent.depth + 1,
            parent_task_id=parent_id,
            created_at=now,
            last_modified=now,
            **kwargs,
        )

        self.add(subtask)
        self.add_dependency(subtask.id, parent_id)
        parent.status = TaskStatus.BLOCKED_BY_TASK
        parent.last_modified = now

        return subtask
    

    def add_subtasks(
        self,
        parent_id: str,
        subtasks: list[Task],
    ) -> list[Task]:
        if parent_id not in self._tasks:
            raise KeyError(f"Parent task '{parent_id}' not found.")

        if not subtasks:
            return []

        now = _now_iso()

        with self._lock:
            # Assign unique IDs inside the lock
            for subtask in subtasks:
                self._ensure_unique_id(subtask)
                subtask.created_at = now
                subtask.last_modified = now

            def _get_blocked_by_ids(tid: str) -> list[str]:
                return list(self._blocked_by.get(tid, set()))

            # Cycle check before any mutations
            for subtask in subtasks:
                if detect_cycles(subtask.id, parent_id, _get_blocked_by_ids):
                    raise ValueError(
                        f"Adding subtask '{subtask.id}' under '{parent_id}' "
                        f"would create a cycle. No subtasks were created."
                    )

            # All checks passed — mutate
            for subtask in subtasks:
                self._tasks[subtask.id] = subtask
                self._blocked_by.setdefault(subtask.id, set())
                self._blocking.setdefault(subtask.id, set())
                self._blocked_by.setdefault(parent_id, set()).add(subtask.id)
                self._blocking.setdefault(subtask.id, set()).add(parent_id)

            parent = self._tasks[parent_id]
            parent.status = TaskStatus.BLOCKED_BY_TASK
            parent.last_modified = now

        return subtasks

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _require(self, task_id: str) -> Task:
        task = self._tasks.get(task_id)
        if task is None:
            raise KeyError(f"Task '{task_id}' not found.")
        return task
    