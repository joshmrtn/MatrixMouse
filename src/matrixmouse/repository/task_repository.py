"""
matrixmouse/repository/task_repository.py

Abstract base class for task persistence.

The TaskRepository defines the full interface for task storage and retrieval.
Concrete implementations (SQLite, in-memory for testing) must satisfy this
interface without exposing storage details to callers.

Design principles:
    - All mutations are atomic. A partial write on crash must never leave
      the repository in an inconsistent state.
    - last_modified is stamped automatically by the repository on every
      mutation. Callers never set it directly.
    - Named state transitions enforce invariants and handle side effects
      atomically within a single transaction. mark_complete unblocks
      dependents in the same transaction.
    - The dependency graph (blocked_by / blocking relationships) lives
      entirely in the database. Task objects are lean — they do not carry
      blocked_by, blocking, or subtasks lists. Callers query the repository
      for dependency information just-in-time.
    - Cycle detection is the caller's responsibility before calling
      add_subtask or add_dependency. The repository does not re-run
      cycle detection internally.
    - is_ready is a repository query, not a method on Task, because it
      requires a live view of the dependency graph.

Do not add scheduling logic, agent logic, or tool dispatch here.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
import uuid
import logging
logger = logging.getLogger(__name__)

from matrixmouse.task import AgentRole, Task


class TaskRepository(ABC):
    """
    Abstract interface for task persistence.

    All concrete implementations must be thread-safe. Write operations
    must use transactions so that concurrent access from multiple worker
    threads cannot produce partial or corrupt state.
    """

    def _ensure_unique_id(self, task: Task) -> None:
        """
        Regenerate task.id until it is globally unique in this repository.

        Modifies task in place. Collision is astronomically unlikely with
        16-char hex IDs but handled cleanly rather than surfacing an
        IntegrityError to the caller.

        This method is called by all creation paths (add, add_subtask,
        add_subtasks) so uniqueness is guaranteed regardless of how a
        task enters the repository.
        """
        while self.get(task.id) is not None:
            old_id = task.id
            task.id = uuid.uuid4().hex[:16]
            logger.warning(
                "Task id collision on %r — regenerating to %r.",
                old_id, task.id,
            )

    # ------------------------------------------------------------------
    # Core CRUD
    # ------------------------------------------------------------------

    @abstractmethod
    def add(self, task: Task) -> None:
        """
        Persist a new task.

        Raises:
            ValueError: If a task with this ID already exists.
        """

    @abstractmethod
    def get(self, task_id: str) -> Task | None:
        """
        Return the task with the given ID, or None if not found.

        Supports prefix matching: if task_id is a unique prefix of exactly
        one task ID, that task is returned. If the prefix matches multiple
        tasks, raises ValueError.

        Args:
            task_id: Full task ID or unique prefix.

        Raises:
            ValueError: If task_id is an ambiguous prefix.
        """

    @abstractmethod
    def update(self, task: Task) -> None:
        """
        Persist changes to an existing task.

        Automatically stamps task.last_modified to the current UTC time.
        Callers must not set last_modified directly.

        Raises:
            KeyError: If no task with this ID exists.
        """

    @abstractmethod
    def delete(self, task_id: str) -> None:
        """
        Remove a task permanently.

        Also removes all dependency edges involving this task from
        task_dependencies, and any stale clarification record for this
        task, via CASCADE.

        Raises:
            KeyError: If no task with this ID exists.
        """

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    @abstractmethod
    def all_tasks(self) -> list[Task]:
        """Return all tasks regardless of status."""

    @abstractmethod
    def active_tasks(self) -> list[Task]:
        """
        Return all non-terminal tasks.

        Terminal statuses are COMPLETE and CANCELLED.
        """

    @abstractmethod
    def completed_ids(self) -> set[str]:
        """
        Return the IDs of all terminal tasks (COMPLETE or CANCELLED).

        Used by is_ready to evaluate dependency satisfaction without
        loading full task objects for every dependency check.
        """

    @abstractmethod
    def is_ready(self, task_id: str) -> bool:
        """
        Return True if the task has no outstanding blockers.

        A task is ready when all tasks in its blocked_by set are terminal.
        A task with no dependencies is always ready (subject to its status).

        Returns False if the task does not exist.
        """

    @abstractmethod
    def has_blockers(self, task_id: str) -> bool:
        """
        Return True if any non-terminal task is blocking the given task.

        Used by the scheduler on every iteration to filter READY candidates.
        Equivalent to len(get_blocked_by(task_id)) > 0 but cheaper —
        implementations should use EXISTS rather than a full JOIN.

        Returns False if the task does not exist.
        """

    # ------------------------------------------------------------------
    # Dependency graph queries
    # ------------------------------------------------------------------

    @abstractmethod
    def get_subtasks(self, task_id: str) -> list[Task]:
        """
        Return all direct children of the given task.

        Queries tasks WHERE parent_task_id = task_id.
        Returns an empty list if the task has no subtasks or does not exist.
        """

    @abstractmethod
    def get_blocked_by(self, task_id: str) -> list[Task]:
        """
        Return all tasks that are directly blocking the given task.

        These are the tasks that must reach a terminal status before
        task_id can transition to READY.

        Returns an empty list if the task has no blockers or does not exist.
        """

    @abstractmethod
    def get_blocking(self, task_id: str) -> list[Task]:
        """
        Return all tasks that the given task is directly blocking.

        Returns an empty list if the task blocks nothing or does not exist.
        """

    # ------------------------------------------------------------------
    # Dependency graph mutations
    # ------------------------------------------------------------------

    @abstractmethod
    def add_dependency(
        self,
        blocking_task_id: str,
        blocked_task_id: str,
    ) -> None:
        """
        Record that blocked_task_id is blocked by blocking_task_id,
        and transition blocked_task_id to BLOCKED_BY_TASK status.

        Cycle detection runs inside the transaction before any rows are
        written. If adding this edge would create a cycle in the dependency
        graph, the transaction is rolled back and ValueError is raised.
        No partial state is written.

        Because the cycle check and the write share a single transaction,
        there is no window for a concurrent writer to introduce a cycle
        between the check and the commit.

        If the dependency already exists this is a no-op.

        Args:
            blocking_task_id: The task that will block blocked_task_id.
            blocked_task_id:  The task that will become blocked.

        Raises:
            KeyError:   If either task does not exist.
            ValueError: If adding this edge would create a dependency cycle.
        """

    @abstractmethod
    def remove_dependency(
        self,
        blocking_task_id: str,
        blocked_task_id: str,
    ) -> None:
        """
        Remove the dependency between blocking_task_id and blocked_task_id.

        No-op if the dependency does not exist.

        Raises:
            KeyError: If either task does not exist.
        """

    # ------------------------------------------------------------------
    # Named state transitions
    # ------------------------------------------------------------------

    @abstractmethod
    def mark_running(self, task_id: str) -> None:
        """
        Transition a task to RUNNING status.

        Sets time_slice_started to the current monotonic time.
        Sets started_at to the current UTC time on the first transition
        to RUNNING only — subsequent re-runs do not overwrite started_at.

        Raises:
            KeyError: If no task with this ID exists.
        """

    @abstractmethod
    def mark_ready(self, task_id: str) -> None:
        """
        Transition a task to READY status.

        Clears time_slice_started.

        Raises:
            KeyError: If no task with this ID exists.
        """

    @abstractmethod
    def mark_complete(self, task_id: str) -> None:
        """
        Transition a task to COMPLETE status.

        Sets completed_at to the current UTC time.

        Side effect: removes all dependency edges where this task is the
        blocker, then transitions any previously-blocked tasks that now
        have no remaining blockers to READY. All within one transaction.

        Raises:
            KeyError: If no task with this ID exists.
        """

    @abstractmethod
    def mark_blocked_by_human(self, task_id: str, reason: str = "") -> None:
        """
        Transition a task to BLOCKED_BY_HUMAN status.

        Appends "[BLOCKED] {reason}" to task.notes if reason is non-empty.

        Raises:
            KeyError: If no task with this ID exists.
        """

    @abstractmethod
    def mark_cancelled(self, task_id: str) -> None:
        """
        Transition a task to CANCELLED status.

        Sets completed_at to the current UTC time.

        Raises:
            KeyError: If no task with this ID exists.
        """

    # ------------------------------------------------------------------
    # Subtask creation
    # ------------------------------------------------------------------

    @abstractmethod
    def add_subtask(
        self,
        parent_id: str,
        title: str,
        description: str,
        role: "AgentRole | None" = None,
        repo: "list[str] | None" = None,
        importance: float | None = None,
        urgency: float | None = None,
        **kwargs,
    ) -> Task:
        """
        Create a subtask under the given parent and persist both atomically.

        The subtask inherits role, repo, importance, and urgency from the
        parent unless explicitly overridden. depth is always parent.depth + 1.
        parent_task_id is always set to parent_id.

        The parent task is updated atomically in the same transaction:
            - status set to BLOCKED_BY_TASK
            - dependency edge added: subtask blocks parent

        Callers are responsible for running cycle detection before calling
        this method. The repository does not re-check for cycles.

        Args:
            parent_id:   ID of the parent task.
            title:       Title of the new subtask.
            description: Description of the new subtask.
            role:        Agent role. Defaults to parent's role.
            repo:        Repo scope. Defaults to parent's repo.
            importance:  Priority importance. Defaults to parent's importance.
            urgency:     Priority urgency. Defaults to parent's urgency.
            **kwargs:    Additional Task fields for edge cases.

        Returns:
            The newly created subtask.

        Raises:
            KeyError: If no task with parent_id exists.
        """
        
    @abstractmethod
    def add_subtasks(
        self,
        parent_id: str,
        subtasks: list[Task],
    ) -> list[Task]:
        """
        Add multiple subtasks under a parent in a single atomic transaction.

        All subtasks are inserted, all dependency edges (subtask blocks
        parent) are added, and the parent is set to BLOCKED_BY_TASK — or
        none of it happens. If any operation fails the entire transaction
        is rolled back.

        Cycle detection runs inside the transaction for each subtask before
        any rows are written. Since subtasks are new nodes with no existing
        edges, cycles cannot form from this operation alone. The check is
        present as a defensive guard against ID collision after retry.

        ID uniqueness is guaranteed: _ensure_unique_id() is called on each
        subtask before insertion, regenerating any colliding IDs in place.

        Callers are responsible for constructing Task objects with correct
        fields (depth, parent_task_id, role, importance, urgency, etc.)
        before calling this method.

        Args:
            parent_id: ID of the parent task.
            subtasks:  List of Task objects to create as children.
                       task.id and timestamps are managed by the repository.

        Returns:
            The list of created Task objects with their final IDs assigned.

        Raises:
            KeyError:   If parent_id does not exist.
            ValueError: If adding any subtask would create a dependency cycle.
        """