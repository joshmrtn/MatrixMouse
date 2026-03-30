"""
matrixmouse/repository/sqlite_task_repository.py

SQLite-backed implementation of TaskRepository.

Uses the shared connection manager and schema from sqlite_db.py.
One database file per workspace: <workspace>/.matrixmouse/matrixmouse.db

All write operations use context manager transactions (BEGIN/COMMIT/ROLLBACK).
mark_complete handles dependent unblocking atomically in a single transaction.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Callable
import uuid
from datetime import datetime, timezone
from pathlib import Path

from matrixmouse.repository.sqlite_db import get_connection, init_db
from matrixmouse.repository.task_repository import TaskRepository
from matrixmouse.task import AgentRole, Task, TaskStatus, PRState
from matrixmouse.utils.task_utils import detect_cycles

logger = logging.getLogger(__name__)

_TERMINAL = (TaskStatus.COMPLETE.value, TaskStatus.CANCELLED.value)
_PENDING = (TaskStatus.PENDING.value,)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_task(row) -> Task:
    return Task(
        id=row["id"],
        title=row["title"],
        description=row["description"],
        status=TaskStatus(row["status"]),
        role=AgentRole(row["role"]),
        repo=json.loads(row["repo"]),
        target_files=json.loads(row["target_files"]),
        importance=row["importance"],
        urgency=row["urgency"],
        depth=row["depth"],
        parent_task_id=row["parent_task_id"],
        reviews_task_id=row["reviews_task_id"],
        notes=row["notes"],
        pending_question=row["pending_question"],
        last_review_summary=row["last_review_summary"],
        pr_url=row["pr_url"],
        pr_state=PRState(row["pr_state"]),
        pr_poll_next_at=row["pr_poll_next_at"],
        context_messages=json.loads(row["context_messages"]),
        wip_commit_hash=row["wip_commit_hash"],
        merge_resolution_decisions=json.loads(row["merge_resolution_decisions"] or "[]"),
        pending_tool_calls=json.loads(row["pending_tool_calls"] or "[]"),
        branch=row["branch"],
        decomposition_confirmed_depth=row["decomposition_confirmed_depth"],
        turn_limit=row["turn_limit"],
        preempt=bool(row["preempt"]),
        preemptable=bool(row["preemptable"]),
        time_slice_started=row["time_slice_started"],
        started_at=row["started_at"],
        completed_at=row["completed_at"],
        created_at=row["created_at"],
        last_modified=row["last_modified"],
        wait_until=row["wait_until"],
        wait_reason=row["wait_reason"],
    )


def _task_to_params(task: Task) -> dict:
    return {
        "id":                            task.id,
        "title":                         task.title or "",
        "description":                   task.description or "",
        "status":                        task.status.value,
        "role":                          task.role.value,
        "repo":                          json.dumps(task.repo or []),
        "target_files":                  json.dumps(task.target_files or []),
        "importance":                    task.importance,
        "urgency":                       task.urgency,
        "depth":                         task.depth or 0,
        "parent_task_id":                task.parent_task_id or None,
        "reviews_task_id":               task.reviews_task_id or None,
        "notes":                         task.notes or "",
        "pending_question":              task.pending_question or "",
        "last_review_summary":           task.last_review_summary or "",
        "pr_url":                        task.pr_url or "",
        "pr_state":                      task.pr_state.value,
        "pr_poll_next_at":               task.pr_poll_next_at or "",
        "context_messages":              json.dumps(task.context_messages or []),
        "wip_commit_hash":               task.wip_commit_hash,
        "merge_resolution_decisions":    json.dumps(task.merge_resolution_decisions),
        "pending_tool_calls":            json.dumps(task.pending_tool_calls),
        "branch":                        task.branch,
        "decomposition_confirmed_depth": task.decomposition_confirmed_depth or 0,
        "turn_limit":                    task.turn_limit or 0,
        "preempt":                       int(task.preempt or False),
        "preemptable":                   1 if task.preemptable else 0,
        "time_slice_started":            task.time_slice_started,
        "started_at":                    task.started_at or None,
        "completed_at":                  task.completed_at or None,
        "created_at":                    task.created_at,
        "last_modified":                 task.last_modified,
        "wait_until":                    task.wait_until,
        "wait_reason":                   task.wait_reason or "",
    }


_INSERT_SQL = """
    INSERT INTO tasks (
        id, title, description, status, role,
        repo, target_files, importance, urgency,
        depth, parent_task_id, reviews_task_id,
        notes, pending_question, last_review_summary,
        context_messages, wip_commit_hash, merge_resolution_decisions,
        pending_tool_calls,  
        branch, decomposition_confirmed_depth, turn_limit,
        preempt, preemptable, time_slice_started,
        started_at, completed_at, created_at, last_modified,
        pr_url, pr_state, pr_poll_next_at
    ) VALUES (
        :id, :title, :description, :status, :role,
        :repo, :target_files, :importance, :urgency,
        :depth, :parent_task_id, :reviews_task_id,
        :notes, :pending_question, :last_review_summary,
        :context_messages, :wip_commit_hash, :merge_resolution_decisions, 
        :pending_tool_calls, 
        :branch, :decomposition_confirmed_depth, :turn_limit,
        :preempt, :preemptable, :time_slice_started,
        :started_at, :completed_at, :created_at, :last_modified,
        :pr_url, :pr_state, :pr_poll_next_at
    )
"""

_UPDATE_SQL = """
    UPDATE tasks SET
        title                         = :title,
        description                   = :description,
        status                        = :status,
        role                          = :role,
        repo                          = :repo,
        target_files                  = :target_files,
        importance                    = :importance,
        urgency                       = :urgency,
        depth                         = :depth,
        parent_task_id                = :parent_task_id,
        reviews_task_id               = :reviews_task_id,
        notes                         = :notes,
        pending_question              = :pending_question,
        pr_url                        = :pr_url,
        pr_state                      = :pr_state,
        pr_poll_next_at               = :pr_poll_next_at,
        last_review_summary           = :last_review_summary,
        context_messages              = :context_messages,
        wip_commit_hash               = :wip_commit_hash,
        merge_resolution_decisions    = :merge_resolution_decisions,
        pending_tool_calls            = :pending_tool_calls,
        branch                        = :branch,
        decomposition_confirmed_depth = :decomposition_confirmed_depth,
        turn_limit                    = :turn_limit,
        preempt                       = :preempt,
        preemptable                   = :preemptable,
        time_slice_started            = :time_slice_started,
        started_at                    = :started_at,
        completed_at                  = :completed_at,
        last_modified                 = :last_modified
    WHERE id = :id
"""


# ---------------------------------------------------------------------------
# SQLiteTaskRepository
# ---------------------------------------------------------------------------

class SQLiteTaskRepository(TaskRepository):
    """
    SQLite-backed task repository.

    Thread-safe via the shared per-thread connection manager in sqlite_db.
    All write operations use BEGIN IMMEDIATE transactions.
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        init_db(db_path)
        logger.info("SQLiteTaskRepository ready at %s", db_path)

    def _conn(self):
        return get_connection(self._db_path)

    # ------------------------------------------------------------------
    # Core CRUD
    # ------------------------------------------------------------------

    def add(self, task: Task) -> None:
        self._ensure_unique_id(task)
        conn = self._conn()
        try:
            with conn:
                conn.execute(_INSERT_SQL, _task_to_params(task))
        except Exception as e:
            if "UNIQUE constraint" in str(e):
                raise ValueError(f"Task '{task.id}' already exists.") from e
            raise

    def get(self, task_id: str) -> Task | None:
        conn = self._conn()
        row = conn.execute(
            "SELECT * FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if row:
            return _row_to_task(row)

        rows = conn.execute(
            "SELECT * FROM tasks WHERE id LIKE ?",
            (f"{task_id}%",),
        ).fetchall()
        if len(rows) == 1:
            return _row_to_task(rows[0])
        if len(rows) > 1:
            raise ValueError(
                f"Ambiguous prefix '{task_id}' matches: "
                f"{[r['id'] for r in rows]}"
            )
        return None

    def update(self, task: Task) -> None:
        # Branch immutability — once set, task.branch cannot be changed
        existing = self.get(task.id)
        if existing is None:
            raise KeyError(f"Task '{task.id}' not found.")
        if existing.branch and task.branch != existing.branch:
            raise ValueError(
                f"Task '{task.id}' branch is immutable once set. "
                f"Cannot change '{existing.branch}' to '{task.branch}'."
            )
        task.last_modified = _now_iso()
        params = _task_to_params(task)
        conn = self._conn()
        with conn:
            cursor = conn.execute(_UPDATE_SQL, params)
            if cursor.rowcount == 0:
                raise KeyError(f"Task '{task.id}' not found.")

    def delete(self, task_id: str) -> None:
        conn = self._conn()
        with conn:
            cursor = conn.execute(
                "DELETE FROM tasks WHERE id = ?", (task_id,)
            )
            if cursor.rowcount == 0:
                raise KeyError(f"Task '{task_id}' not found.")

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def all_tasks(self) -> list[Task]:
        rows = self._conn().execute("SELECT * FROM tasks").fetchall()
        return [_row_to_task(r) for r in rows]

    def active_tasks(self) -> list[Task]:
        rows = self._conn().execute(
            "SELECT * FROM tasks WHERE status NOT IN (?, ?, ?)",
            (*_TERMINAL, TaskStatus.PENDING.value),
        ).fetchall()
        return [_row_to_task(r) for r in rows]

    def completed_ids(self) -> set[str]:
        rows = self._conn().execute(
            "SELECT id FROM tasks WHERE status IN (?, ?)", _TERMINAL
        ).fetchall()
        return {r["id"] for r in rows}

    def is_ready(self, task_id: str) -> bool:
        conn = self._conn()
        exists = conn.execute(
            "SELECT status FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if not exists:
            return False
        if exists["status"] == TaskStatus.PENDING.value:
            return False
        row = conn.execute(
            """
            SELECT NOT EXISTS (
                SELECT 1
                FROM task_dependencies td
                JOIN tasks t ON t.id = td.blocking_task_id
                WHERE td.blocked_task_id = ?
                AND t.status NOT IN (?, ?)
            ) AS ready
            """,
            (task_id, *_TERMINAL),
        ).fetchone()
        return bool(row["ready"]) if row else False

    def has_blockers(self, task_id: str) -> bool:
        conn = self._conn()
        exists = conn.execute(
            "SELECT status FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if not exists:
            return False
        if exists["status"] == TaskStatus.PENDING.value:
            return False
        row = conn.execute(
            """
            SELECT EXISTS (
                SELECT 1
                FROM task_dependencies td
                JOIN tasks t ON t.id = td.blocking_task_id
                WHERE td.blocked_task_id = ?
                AND t.status NOT IN (?, ?)
            ) AS blocked
            """,
            (task_id, *_TERMINAL),
        ).fetchone()
        return bool(row["blocked"]) if row else False

    # ------------------------------------------------------------------
    # Dependency graph queries
    # ------------------------------------------------------------------

    def get_subtasks(self, task_id: str) -> list[Task]:
        rows = self._conn().execute(
            "SELECT * FROM tasks WHERE parent_task_id = ?", (task_id,)
        ).fetchall()
        return [_row_to_task(r) for r in rows]

    def get_blocked_by(self, task_id: str) -> list[Task]:
        rows = self._conn().execute(
            """
            SELECT t.* FROM tasks t
            JOIN task_dependencies td ON t.id = td.blocking_task_id
            WHERE td.blocked_task_id = ?
            """,
            (task_id,),
        ).fetchall()
        return [_row_to_task(r) for r in rows]

    def get_blocking(self, task_id: str) -> list[Task]:
        rows = self._conn().execute(
            """
            SELECT t.* FROM tasks t
            JOIN task_dependencies td ON t.id = td.blocked_task_id
            WHERE td.blocking_task_id = ?
            """,
            (task_id,),
        ).fetchall()
        return [_row_to_task(r) for r in rows]

    # ------------------------------------------------------------------
    # Dependency graph mutations
    # ------------------------------------------------------------------

    def add_dependency(
        self,
        blocking_task_id: str,
        blocked_task_id: str,
    ) -> None:
        for tid in (blocking_task_id, blocked_task_id):
            if not self.get(tid):
                raise KeyError(f"Task '{tid}' not found.")

        now = _now_iso()
        conn = self._conn()

        with conn:
            # Check for existing edge — no-op if already present
            existing = conn.execute(
                """
                SELECT 1 FROM task_dependencies
                WHERE blocking_task_id = ? AND blocked_task_id = ?
                """,
                (blocking_task_id, blocked_task_id),
            ).fetchone()
            if existing:
                return

            # Cycle check inside the transaction using the same connection.
            # BEGIN IMMEDIATE means no other writer can modify the graph
            # between this check and the INSERT below.
            def _get_blocked_by_ids(tid: str) -> list[str]:
                rows = conn.execute(
                    """
                    SELECT blocking_task_id FROM task_dependencies
                    WHERE blocked_task_id = ?
                    """,
                    (tid,),
                ).fetchall()
                return [r[0] for r in rows]

            if detect_cycles(blocking_task_id, blocked_task_id,
                             _get_blocked_by_ids):
                raise ValueError(
                    f"Adding dependency '{blocking_task_id}' → "
                    f"'{blocked_task_id}' would create a cycle. "
                    f"No changes made."
                )

            conn.execute(
                """
                INSERT INTO task_dependencies
                    (blocking_task_id, blocked_task_id)
                VALUES (?, ?)
                """,
                (blocking_task_id, blocked_task_id),
            )
            conn.execute(
                """
                UPDATE tasks SET
                    status        = ?,
                    last_modified = ?
                WHERE id = ?
                  AND status NOT IN (?, ?)
                """,
                (
                    TaskStatus.BLOCKED_BY_TASK.value,
                    now,
                    blocked_task_id,
                    *_TERMINAL,
                ),
            )

    def remove_dependency(
        self,
        blocking_task_id: str,
        blocked_task_id: str,
    ) -> None:
        now = _now_iso()
        conn = self._conn()
        with conn:
            conn.execute(
                """
                DELETE FROM task_dependencies
                WHERE blocking_task_id = ? AND blocked_task_id = ?
                """,
                (blocking_task_id, blocked_task_id),
            )
            # If blocked_task_id has no remaining non-terminal blockers,
            # transition it to READY. Atomic in the same transaction.
            still_blocked = conn.execute(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM task_dependencies td
                    JOIN tasks t ON t.id = td.blocking_task_id
                    WHERE td.blocked_task_id = ?
                    AND t.status NOT IN (?, ?)
                )
                """,
                (blocked_task_id, *_TERMINAL),
            ).fetchone()[0]

            if not still_blocked:
                conn.execute(
                    """
                    UPDATE tasks SET
                        status        = ?,
                        last_modified = ?
                    WHERE id = ?
                    AND status = ?
                    """,
                    (
                        TaskStatus.READY.value,
                        now,
                        blocked_task_id,
                        TaskStatus.BLOCKED_BY_TASK.value,
                    ),
                )

    # ------------------------------------------------------------------
    # Named state transitions
    # ------------------------------------------------------------------

    def mark_running(self, task_id: str) -> None:
        now_iso = _now_iso()
        now_mono = time.monotonic()
        conn = self._conn()
        with conn:
            # Branch guard — non-Manager tasks must have a branch before running
            row = conn.execute(
                "SELECT branch, role, status FROM tasks WHERE id = ?",
                (task_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"Task '{task_id}' not found.")
            if not row["branch"] and row["role"] != AgentRole.MANAGER.value:
                raise ValueError(
                    f"Task '{task_id}' (role={row['role']}) cannot start: "
                    f"no branch assigned. Set a branch before running."
                )
            if row["status"] != TaskStatus.READY.value:
                raise ValueError(
                    f"Task '{task_id}' cannot transition to RUNNING from "
                    f"{row['status']}. Only READY tasks can become RUNNING."
                )
            cursor = conn.execute(
                """
                UPDATE tasks SET
                    status             = ?,
                    time_slice_started = ?,
                    started_at         = CASE
                                        WHEN started_at IS NULL THEN ?
                                        ELSE started_at
                                        END,
                    last_modified      = ?
                WHERE id = ?
                AND status = ?
                """,
                (
                    TaskStatus.RUNNING.value,
                    now_mono,
                    now_iso,
                    now_iso,
                    task_id,
                    TaskStatus.READY.value,
                ),
            )
            if cursor.rowcount == 0:
                raise ValueError(
                    f"Task '{task_id}' cannot transition to RUNNING from "
                    f"{row['status']}. Only READY tasks can become RUNNING."
                )

    def mark_ready(self, task_id: str) -> None:
        now = _now_iso()
        conn = self._conn()
        with conn:
            cursor = conn.execute(
                """
                UPDATE tasks SET
                    status             = ?,
                    time_slice_started = NULL,
                    last_modified      = ?
                WHERE id = ?
                AND status NOT IN (?, ?)
                """,
                (TaskStatus.READY.value, now, task_id, *_TERMINAL),
            )
            if cursor.rowcount == 0:
                task = self.get(task_id)
                if task is None:
                    raise KeyError(f"Task '{task_id}' not found.")
                raise ValueError(
                    f"Task '{task_id}' is {task.status.value} and cannot "
                    f"be returned to READY."
                )

    def mark_complete(self, task_id: str) -> None:
        now = _now_iso()
        conn = self._conn()
        with conn:
            cursor = conn.execute(
                """
                UPDATE tasks SET
                    status        = ?,
                    completed_at  = ?,
                    last_modified = ?
                WHERE id = ?
                AND status NOT IN (?, ?)
                """,
                (TaskStatus.COMPLETE.value, now, now, task_id, *_TERMINAL),
            )
            if cursor.rowcount == 0:
                task = self.get(task_id)
                if task is None:
                    raise KeyError(f"Task '{task_id}' not found.")
                # Already terminal — no-op is acceptable, not an error
                return

            previously_blocked = conn.execute(
                "SELECT blocked_task_id FROM task_dependencies "
                "WHERE blocking_task_id = ?",
                (task_id,),
            ).fetchall()

            conn.execute(
                "DELETE FROM task_dependencies WHERE blocking_task_id = ?",
                (task_id,),
            )

            for row in previously_blocked:
                cid = row["blocked_task_id"]
                still_blocked = conn.execute(
                    """
                    SELECT EXISTS (
                        SELECT 1
                        FROM task_dependencies td
                        JOIN tasks t ON t.id = td.blocking_task_id
                        WHERE td.blocked_task_id = ?
                        AND t.status NOT IN (?, ?)
                    )
                    """,
                    (cid, *_TERMINAL),
                ).fetchone()[0]
                if not still_blocked:
                    conn.execute(
                        """
                        UPDATE tasks SET
                            status        = ?,
                            last_modified = ?
                        WHERE id = ?
                        AND status = ?
                        """,
                        (
                            TaskStatus.READY.value,
                            now,
                            cid,
                            TaskStatus.BLOCKED_BY_TASK.value,
                        ),
                    )

    def mark_blocked_by_human(
        self, task_id: str, reason: str = ""
    ) -> None:
        now = _now_iso()
        conn = self._conn()
        with conn:
            if reason:
                cursor = conn.execute(
                    """
                    UPDATE tasks SET
                        status        = ?,
                        notes         = CASE
                                        WHEN notes = '' THEN ?
                                        ELSE notes || char(10) || ?
                                        END,
                        last_modified = ?
                    WHERE id = ?
                    AND status NOT IN (?, ?)
                    """,
                    (
                        TaskStatus.BLOCKED_BY_HUMAN.value,
                        f"[BLOCKED] {reason}",
                        f"[BLOCKED] {reason}",
                        now,
                        task_id,
                        *_TERMINAL,
                    ),
                )
            else:
                cursor = conn.execute(
                    """
                    UPDATE tasks SET
                        status        = ?,
                        last_modified = ?
                    WHERE id = ?
                    AND status NOT IN (?, ?)
                    """,
                    (TaskStatus.BLOCKED_BY_HUMAN.value, now, task_id, *_TERMINAL),
                )
            if cursor.rowcount == 0:
                task = self.get(task_id)
                if task is None:
                    raise KeyError(f"Task '{task_id}' not found.")
                raise ValueError(
                    f"Task '{task_id}' is {task.status.value} and cannot "
                    f"be marked BLOCKED_BY_HUMAN."
                )

    def mark_cancelled(self, task_id: str) -> None:
        now = _now_iso()
        conn = self._conn()
        with conn:
            cursor = conn.execute(
                """
                UPDATE tasks SET
                    status        = ?,
                    completed_at  = ?,
                    last_modified = ?
                WHERE id = ?
                AND status != ?
                """,
                (
                    TaskStatus.CANCELLED.value,
                    now,
                    now,
                    task_id,
                    TaskStatus.COMPLETE.value,
                ),
            )
            if cursor.rowcount == 0:
                task = self.get(task_id)
                if task is None:
                    raise KeyError(f"Task '{task_id}' not found.")
                # Already COMPLETE — no-op, cannot cancel a completed task
                return

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
        task = self.get(task_id)
        if task is None:
            raise KeyError(f"Task '{task_id}' not found.")
        if task.branch:
            raise ValueError(
                f"Task '{task_id}' already has branch '{task.branch}'. "
                f"Branch names are permanent."
            )

        # Create git branch first — outside the DB transaction
        # so we can roll back cleanly if it fails
        git_ok, git_err, head_hash = create_git_branch(
            full_branch_name, base_branch
        )
        if not git_ok:
            raise ValueError(
                f"Failed to create git branch '{full_branch_name}': {git_err}"
            )

        # Persist to DB
        now = _now_iso()
        conn = self._conn()
        try:
            with conn:
                conn.execute(
                    """
                    UPDATE tasks SET
                        branch           = ?,
                        wip_commit_hash  = ?,
                        last_modified    = ?
                    WHERE id = ?
                      AND branch = ''
                    """,
                    (full_branch_name, head_hash, now, task_id),
                )
        except Exception as e:
            # DB write failed — roll back the git branch
            del_ok, del_err = delete_git_branch(full_branch_name)
            if not del_ok:
                logger.error(
                    "DB write failed AND git branch deletion failed for '%s': "
                    "DB error: %s | Git error: %s. "
                    "Manual cleanup of orphaned branch may be required.",
                    full_branch_name, e, del_err,
                )
            raise ValueError(
                f"Failed to persist branch assignment: {e}. "
                f"Git branch rolled back."
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
        parent = self.get(parent_id)
        if parent is None:
            raise KeyError(f"Parent task '{parent_id}' not found.")
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

        conn = self._conn()
        try:
            with conn:
                conn.execute(_INSERT_SQL, _task_to_params(subtask))
                conn.execute(
                    "INSERT INTO task_dependencies "
                    "(blocking_task_id, blocked_task_id) VALUES (?, ?)",
                    (subtask.id, parent_id),
                )
                conn.execute(
                    "UPDATE tasks SET status = ?, last_modified = ? "
                    "WHERE id = ?",
                    (TaskStatus.BLOCKED_BY_TASK.value, now, parent_id),
                )
        except Exception as e:
            del_ok, del_err = delete_git_branch(branch_name)
            if not del_ok:
                logger.error(
                    "DB write failed AND git branch deletion failed for '%s': "
                    "DB: %s | Git: %s. Orphaned branch requires manual cleanup.",
                    branch_name, e, del_err,
                )
            raise ValueError(
                f"Failed to create subtask: {e}. Git branch rolled back."
            ) from e

        return subtask

    def add_subtasks(
        self,
        parent_id: str,
        subtasks: list[Task],
        create_git_branch: Callable[[str, str], tuple[bool, str, str]],
        delete_git_branch: Callable[[str], tuple[bool, str]],
    ) -> list[Task]:
        parent = self.get(parent_id)
        if parent is None:
            raise KeyError(f"Parent task '{parent_id}' not found.")
        if not parent.branch:
            raise ValueError(
                f"Parent task '{parent_id}' has no branch. "
                f"Set a branch before creating subtasks."
            )
        if not subtasks:
            return []

        now = _now_iso()
        conn = self._conn()

        # Assign unique IDs and branch names, create git branches
        # outside the DB transaction so we can track which branches
        # to roll back on failure.
        created_branches: list[str] = []

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
                        f"Failed to create git branch '{branch_name}': {git_err}"
                    )
                subtask.branch = branch_name
                subtask.wip_commit_hash = head_hash
                created_branches.append(branch_name)

        except Exception:
            # Roll back all git branches created so far
            for branch_name in created_branches:
                del_ok, del_err = delete_git_branch(branch_name)
                if not del_ok:
                    logger.error(
                        "Git rollback failed for '%s': %s. "
                        "Orphaned branch requires manual cleanup.",
                        branch_name, del_err,
                    )
            raise

        # All git branches created — now write to DB atomically
        def _get_blocked_by_ids(tid: str) -> list[str]:
            rows = conn.execute(
                "SELECT blocking_task_id FROM task_dependencies "
                "WHERE blocked_task_id = ?",
                (tid,),
            ).fetchall()
            return [r[0] for r in rows]

        try:
            with conn:
                for subtask in subtasks:
                    if detect_cycles(subtask.id, parent_id, _get_blocked_by_ids):
                        raise ValueError(
                            f"Adding subtask '{subtask.id}' would create a cycle."
                        )
                    conn.execute(_INSERT_SQL, _task_to_params(subtask))
                    conn.execute(
                        "INSERT INTO task_dependencies "
                        "(blocking_task_id, blocked_task_id) VALUES (?, ?)",
                        (subtask.id, parent_id),
                    )
                conn.execute(
                    "UPDATE tasks SET status = ?, last_modified = ? WHERE id = ?",
                    (TaskStatus.BLOCKED_BY_TASK.value, now, parent_id),
                )
        except Exception as e:
            # DB transaction rolled back automatically — roll back git branches
            for branch_name in created_branches:
                del_ok, del_err = delete_git_branch(branch_name)
                if not del_ok:
                    logger.error(
                        "DB write failed AND git rollback failed for '%s': "
                        "DB: %s | Git: %s. Orphaned branch requires manual cleanup.",
                        branch_name, e, del_err,
                    )
            raise ValueError(
                f"Failed to create subtasks: {e}. "
                f"All git branches rolled back."
            ) from e

        return subtasks
    
    
    def commit_pending_subtree(self, root_task_id: str) -> list[str]:
        if not self.get(root_task_id):
            raise KeyError(f"Task '{root_task_id}' not found.")

        now = _now_iso()
        conn = self._conn()
        transitioned = []

        with conn:
            # Find all PENDING descendants via recursive CTE
            rows = conn.execute(
                """
                WITH RECURSIVE descendants(id) AS (
                    SELECT id FROM tasks WHERE parent_task_id = ?
                    UNION ALL
                    SELECT t.id FROM tasks t
                    JOIN descendants d ON t.parent_task_id = d.id
                )
                SELECT id FROM descendants
                JOIN tasks USING (id)
                WHERE status = ?
                """,
                (root_task_id, TaskStatus.PENDING.value),
            ).fetchall()

            for row in rows:
                task_id = row["id"]
                # Check if task has any non-terminal blockers
                has_blockers = conn.execute(
                    """
                    SELECT EXISTS (
                        SELECT 1 FROM task_dependencies td
                        JOIN tasks t ON t.id = td.blocking_task_id
                        WHERE td.blocked_task_id = ?
                        AND t.status NOT IN (?, ?)
                    )
                    """,
                    (task_id, *_TERMINAL),
                ).fetchone()[0]

                new_status = (
                    TaskStatus.BLOCKED_BY_TASK.value
                    if has_blockers
                    else TaskStatus.READY.value
                )
                conn.execute(
                    """
                    UPDATE tasks SET status = ?, last_modified = ?
                    WHERE id = ? AND status = ?
                    """,
                    (new_status, now, task_id, TaskStatus.PENDING.value),
                )
                transitioned.append(task_id)

        return transitioned