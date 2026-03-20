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
from datetime import datetime, timezone
from pathlib import Path

from matrixmouse.repository.sqlite_db import get_connection, init_db
from matrixmouse.repository.task_repository import TaskRepository
from matrixmouse.task import AgentRole, Task, TaskStatus

logger = logging.getLogger(__name__)

_TERMINAL = (TaskStatus.COMPLETE.value, TaskStatus.CANCELLED.value)


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
        context_messages=json.loads(row["context_messages"]),
        wip_commit_hash=row["wip_commit_hash"],
        branch=row["branch"],
        decomposition_confirmed_depth=row["decomposition_confirmed_depth"],
        turn_limit=row["turn_limit"],
        preempt=bool(row["preempt"]),
        time_slice_started=row["time_slice_started"],
        started_at=row["started_at"],
        completed_at=row["completed_at"],
        created_at=row["created_at"],
        last_modified=row["last_modified"],
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
        "context_messages":              json.dumps(task.context_messages or []),
        "wip_commit_hash":               task.wip_commit_hash,
        "branch":                        task.branch,
        "decomposition_confirmed_depth": task.decomposition_confirmed_depth or 0,
        "turn_limit":                    task.turn_limit or 0,
        "preempt":                       int(task.preempt or False),
        "time_slice_started":            task.time_slice_started,
        "started_at":                    task.started_at or None,
        "completed_at":                  task.completed_at or None,
        "created_at":                    task.created_at,
        "last_modified":                 task.last_modified,
    }


_INSERT_SQL = """
    INSERT INTO tasks (
        id, title, description, status, role,
        repo, target_files, importance, urgency,
        depth, parent_task_id, reviews_task_id,
        notes, pending_question, last_review_summary,
        context_messages, wip_commit_hash, branch,
        decomposition_confirmed_depth, turn_limit,
        preempt, time_slice_started,
        started_at, completed_at, created_at, last_modified
    ) VALUES (
        :id, :title, :description, :status, :role,
        :repo, :target_files, :importance, :urgency,
        :depth, :parent_task_id, :reviews_task_id,
        :notes, :pending_question, :last_review_summary,
        :context_messages, :wip_commit_hash, :branch,
        :decomposition_confirmed_depth, :turn_limit,
        :preempt, :time_slice_started,
        :started_at, :completed_at, :created_at, :last_modified
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
        last_review_summary           = :last_review_summary,
        context_messages              = :context_messages,
        wip_commit_hash               = :wip_commit_hash,
        branch                        = :branch,
        decomposition_confirmed_depth = :decomposition_confirmed_depth,
        turn_limit                    = :turn_limit,
        preempt                       = :preempt,
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
        try:
            conn = self._conn()
            with conn:
                conn.execute(_INSERT_SQL, _task_to_params(task))
        except Exception as e:
            if "UNIQUE constraint" in str(e):
                raise ValueError(
                    f"Task '{task.id}' already exists."
                ) from e
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
            "SELECT * FROM tasks WHERE status NOT IN (?, ?)", _TERMINAL
        ).fetchall()
        return [_row_to_task(r) for r in rows]

    def completed_ids(self) -> set[str]:
        rows = self._conn().execute(
            "SELECT id FROM tasks WHERE status IN (?, ?)", _TERMINAL
        ).fetchall()
        return {r["id"] for r in rows}

    def is_ready(self, task_id: str) -> bool:
        conn = self._conn()
        # First check the task exists
        exists = conn.execute(
            "SELECT 1 FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if not exists:
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
        row = self._conn().execute(
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
        conn = self._conn()
        with conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO task_dependencies
                    (blocking_task_id, blocked_task_id)
                VALUES (?, ?)
                """,
                (blocking_task_id, blocked_task_id),
            )

    def remove_dependency(
        self,
        blocking_task_id: str,
        blocked_task_id: str,
    ) -> None:
        conn = self._conn()
        with conn:
            conn.execute(
                """
                DELETE FROM task_dependencies
                WHERE blocking_task_id = ? AND blocked_task_id = ?
                """,
                (blocking_task_id, blocked_task_id),
            )

    # ------------------------------------------------------------------
    # Named state transitions
    # ------------------------------------------------------------------

    def mark_running(self, task_id: str) -> None:
        now_iso = _now_iso()
        now_mono = time.monotonic()
        conn = self._conn()
        with conn:
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
                """,
                (TaskStatus.RUNNING.value, now_mono, now_iso, now_iso, task_id),
            )
            if cursor.rowcount == 0:
                raise KeyError(f"Task '{task_id}' not found.")

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
                """,
                (TaskStatus.READY.value, now, task_id),
            )
            if cursor.rowcount == 0:
                raise KeyError(f"Task '{task_id}' not found.")

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
                """,
                (TaskStatus.COMPLETE.value, now, now, task_id),
            )
            if cursor.rowcount == 0:
                raise KeyError(f"Task '{task_id}' not found.")

            # Tasks that were waiting on this one
            previously_blocked = conn.execute(
                "SELECT blocked_task_id FROM task_dependencies "
                "WHERE blocking_task_id = ?",
                (task_id,),
            ).fetchall()

            # Remove all edges where this task was the blocker
            conn.execute(
                "DELETE FROM task_dependencies WHERE blocking_task_id = ?",
                (task_id,),
            )

            # Unblock any that now have zero non-terminal blockers
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
                    """,
                    (
                        TaskStatus.BLOCKED_BY_HUMAN.value,
                        f"[BLOCKED] {reason}",
                        f"[BLOCKED] {reason}",
                        now,
                        task_id,
                    ),
                )
            else:
                cursor = conn.execute(
                    """
                    UPDATE tasks SET
                        status        = ?,
                        last_modified = ?
                    WHERE id = ?
                    """,
                    (TaskStatus.BLOCKED_BY_HUMAN.value, now, task_id),
                )
            if cursor.rowcount == 0:
                raise KeyError(f"Task '{task_id}' not found.")

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
                """,
                (TaskStatus.CANCELLED.value, now, now, task_id),
            )
            if cursor.rowcount == 0:
                raise KeyError(f"Task '{task_id}' not found.")

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
            importance=importance if importance is not None
                       else parent.importance,
            urgency=urgency if urgency is not None else parent.urgency,
            depth=parent.depth + 1,
            parent_task_id=parent_id,
            created_at=now,
            last_modified=now,
            **kwargs,
        )

        conn = self._conn()
        with conn:
            conn.execute(_INSERT_SQL, _task_to_params(subtask))

            conn.execute(
                """
                INSERT INTO task_dependencies
                    (blocking_task_id, blocked_task_id)
                VALUES (?, ?)
                """,
                (subtask.id, parent_id),
            )

            conn.execute(
                """
                UPDATE tasks SET
                    status        = ?,
                    last_modified = ?
                WHERE id = ?
                """,
                (TaskStatus.BLOCKED_BY_TASK.value, now, parent_id),
            )

        return subtask
    