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

TODO: As the system matures, consider extracting a TaskService layer that 
owns domain invariants and orchestration, leaving TaskRespository as pure 
persistence. The repository currently handles both concerns as a pragmatic 
early-stage decision. 

Do not add scheduling logic, agent logic, or tool dispatch here.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable
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

        If blocked_task_id has no remaining non-terminal blockers after
        removal, and its status is BLOCKED_BY_TASK, it is automatically
        transitioned to READY. This is a domain invariant: a task with no
        blockers must not remain in BLOCKED_BY_TASK status.

        Both the edge removal and the status transition are atomic within
        a single transaction.

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

        Only READY tasks can become RUNNING. Raises ValueError if the task
        is in any other status.

        Sets time_slice_started to the current monotonic time.
        Sets started_at to the current UTC time on the first transition
        to RUNNING only.

        Raises:
            KeyError:   If no task with this ID exists.
            ValueError: If the task is not in READY status.
        """

    @abstractmethod
    def mark_ready(self, task_id: str) -> None:
        """
        Transition a task to READY status.

        Cannot be applied to terminal tasks (COMPLETE, CANCELLED).
        Raises ValueError if the task is already terminal.

        Clears time_slice_started.

        Raises:
            KeyError:   If no task with this ID exists.
            ValueError: If the task is in a terminal status.
        """

    @abstractmethod
    def mark_complete(self, task_id: str) -> None:
        """
        Transition a task to COMPLETE status.

        No-op if the task is already terminal (idempotent for terminal
        states — the orchestrator may attempt to complete an already-complete
        task in edge cases).

        Sets completed_at to the current UTC time.

        Side effect: removes all dependency edges where this task is the
        blocker, then transitions any previously-blocked tasks that now
        have no remaining non-terminal blockers to READY. All within one
        transaction.

        Raises:
            KeyError: If no task with this ID exists.
        """

    @abstractmethod
    def mark_blocked_by_human(self, task_id: str, reason: str = "") -> None:
        """
        Transition a task to BLOCKED_BY_HUMAN status.

        Cannot be applied to terminal tasks. Raises ValueError if the
        task is already COMPLETE or CANCELLED.

        Appends "[BLOCKED] {reason}" to task.notes if reason is non-empty.

        Raises:
            KeyError:   If no task with this ID exists.
            ValueError: If the task is in a terminal status.
        """

    @abstractmethod
    def mark_cancelled(self, task_id: str) -> None:
        """
        Transition a task to CANCELLED status.

        No-op if the task is already COMPLETE (a completed task cannot
        be cancelled — the work is done).

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
        create_git_branch: Callable[[str, str], tuple[bool, str, str]],
        delete_git_branch: Callable[[str], tuple[bool, str]],
        role: AgentRole | None = None,
        repo: list[str] | None = None,
        importance: float | None = None,
        urgency: float | None = None,
        **kwargs,
    ) -> Task:
        """
        Create a single subtask under parent_id atomically.

        The subtask's branch is created via create_git_branch inside the
        same transaction as the task row. If either the git operation or
        the DB write fails, neither is committed.

        Args:
            parent_id:          ID of the parent task.
            title:              Subtask title.
            description:        Subtask description.
            create_git_branch:  Callable(branch_name, base_branch)
                                -> (success, error_msg, head_hash).
                                Called inside the transaction.
            delete_git_branch:  Callable(branch_name) -> (success, error_msg).
                                Called on rollback if git branch was created
                                before the transaction failed.
            role:               Agent role. Defaults to parent's role.
            repo:               Repo list. Defaults to parent's repo.
            importance:         Defaults to parent's importance.
            urgency:            Defaults to parent's urgency.
            **kwargs:           Additional Task fields.

        Returns:
            The created Task with branch and wip_commit_hash set.

        Raises:
            KeyError:   Parent task not found.
            ValueError: Branch creation failed or would create a cycle.
        """

    @abstractmethod
    def add_subtasks(
        self,
        parent_id: str,
        subtasks: list[Task],
        create_git_branch: Callable[[str, str], tuple[bool, str, str]],
        delete_git_branch: Callable[[str], tuple[bool, str]],
    ) -> list[Task]:
        """
        Add multiple subtasks under parent_id in a single atomic transaction.

        For each subtask:
          1. Assigns branch name as <parent_branch>/<subtask_id>
          2. Calls create_git_branch(branch_name, parent_branch)
          3. Sets subtask.wip_commit_hash from returned head_hash
          4. Inserts task row and dependency edge

        If any step fails, all git branches created so far are deleted via
        delete_git_branch, and no DB changes are committed.

        Args:
            parent_id:          ID of the parent task.
            subtasks:           Task objects to create. IDs may be regenerated
                                by _ensure_unique_id before branch assignment.
            create_git_branch:  Callable(branch_name, base_branch)
                                -> (success, error_msg, head_hash).
            delete_git_branch:  Callable(branch_name) -> (success, error_msg).
                                Called for each successfully created branch
                                on rollback.

        Returns:
            List of created Task objects with branch and wip_commit_hash set.

        Raises:
            KeyError:   Parent task not found.
            ValueError: Branch creation failed, cycle detected, or parent
                        has no branch assigned.
        """

    @abstractmethod
    def set_task_branch(
        self,
        task_id: str,
        full_branch_name: str,
        base_branch: str,
        create_git_branch: Callable[[str, str], tuple[bool, str, str]],
        delete_git_branch: Callable[[str], tuple[bool, str]],
    ) -> str:
        """
        Assign a branch to a task that currently has no branch.

        This is the only method that sets task.branch on an existing task.
        Used by the Manager in BRANCH_SETUP session mode to name the top-level
        interjection task before decomposition begins.

        Atomicity guarantee: the git branch is created and the DB is updated
        in a single operation. If either fails, neither is committed.

        Args:
            task_id:            Task to assign the branch to. Must have
                                branch == "".
            full_branch_name:   Full branch name including prefix,
                                e.g. 'mm/refactor/foobar'.
            base_branch:        Branch to base the new branch on.
            create_git_branch:  Callable(branch_name, base_branch)
                                -> (success, error_msg, head_hash).
            delete_git_branch:  Callable(branch_name) -> (success, error_msg).
                                Called on rollback if git branch was created
                                before the DB write failed.

        Returns:
            The full branch name on success.

        Raises:
            KeyError:   Task not found.
            ValueError: Task already has a branch, git operation failed,
                        or branch name is invalid.
        """

    @abstractmethod
    def commit_pending_subtree(self, root_task_id: str) -> list[str]:
        """
        Transition all PENDING descendants of root_task_id to their
        correct schedulable status in a single atomic operation.

        For each PENDING descendant:
        - If it has no non-terminal blockers: READY
        - If it has non-terminal blockers: BLOCKED_BY_TASK

        Called by the orchestrator when a Manager declares_complete
        in PLANNING session mode, committing the planned task graph.

        Args:
            root_task_id: Root of the subtree to commit.

        Returns:
            List of task IDs that were transitioned.

        Raises:
            KeyError: If root_task_id does not exist.
        """