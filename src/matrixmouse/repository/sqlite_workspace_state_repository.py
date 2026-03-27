"""
matrixmouse/repository/sqlite_workspace_state_repository.py

SQLite-backed implementation of WorkspaceStateRepository.

Shares the matrixmouse.db file with SQLiteTaskRepository via the
shared connection manager in sqlite_db. Schema is initialised by
init_db() which is called by both repositories on startup.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
from typing import Any

from matrixmouse.repository.sqlite_db import get_connection, init_db
from matrixmouse.repository.workspace_state_repository import (
    WorkspaceStateRepository, SessionContext, SessionMode
)
from matrixmouse.task import TaskStatus

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()



class SQLiteWorkspaceStateRepository(WorkspaceStateRepository):
    """
    SQLite-backed workspace state repository.

    Thread-safe via the shared per-thread connection manager in sqlite_db.
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        init_db(db_path)
        logger.debug(
            "SQLiteWorkspaceStateRepository ready at %s", db_path
        )

    def _conn(self):
        return get_connection(self._db_path)

    # ------------------------------------------------------------------
    # General key-value store
    # ------------------------------------------------------------------

    def get(self, key: str) -> Any | None:
        row = self._conn().execute(
            "SELECT value FROM workspace_state WHERE key = ?",
            (key,),
        ).fetchone()
        if row is None:
            return None
        try:
            return json.loads(row["value"])
        except (json.JSONDecodeError, TypeError):
            return row["value"]

    def set(self, key: str, value: Any) -> None:
        conn = self._conn()
        with conn:
            conn.execute(
                """
                INSERT INTO workspace_state (key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, json.dumps(value)),
            )

    def delete(self, key: str) -> None:
        conn = self._conn()
        with conn:
            conn.execute(
                "DELETE FROM workspace_state WHERE key = ?", (key,)
            )

    # ------------------------------------------------------------------
    # Stale clarification task registry
    # ------------------------------------------------------------------

    def get_stale_clarification_task(
        self, blocked_task_id: str
    ) -> str | None:
        row = self._conn().execute(
            """
            SELECT manager_task_id FROM stale_clarification_tasks
            WHERE blocked_task_id = ?
            """,
            (blocked_task_id,),
        ).fetchone()
        return row["manager_task_id"] if row else None

    def register_stale_clarification_task(
        self,
        blocked_task_id: str,
        manager_task_id: str,
    ) -> None:
        conn = self._conn()
        with conn:
            conn.execute(
                """
                INSERT INTO stale_clarification_tasks
                    (blocked_task_id, manager_task_id)
                VALUES (?, ?)
                ON CONFLICT(blocked_task_id)
                    DO UPDATE SET
                        manager_task_id = excluded.manager_task_id
                """,
                (blocked_task_id, manager_task_id),
            )

    def clear_stale_clarification_task(
        self, blocked_task_id: str
    ) -> None:
        conn = self._conn()
        with conn:
            conn.execute(
                """
                DELETE FROM stale_clarification_tasks
                WHERE blocked_task_id = ?
                """,
                (blocked_task_id,),
            )

    def all_stale_clarification_tasks(self) -> dict[str, str]:
        rows = self._conn().execute(
            "SELECT blocked_task_id, manager_task_id "
            "FROM stale_clarification_tasks"
        ).fetchall()
        return {
            r["blocked_task_id"]: r["manager_task_id"] for r in rows
        }
    

    # ------------------------------------------------------------------
    # Session contexts
    # ------------------------------------------------------------------

    def get_session_context(self, task_id: str) -> SessionContext | None:
        row = self._conn().execute(
            "SELECT * FROM session_contexts WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        if row is None:
            return None
        return SessionContext(
            mode=SessionMode(row["mode"]),
            allowed_tools=set(json.loads(row["allowed_tools"])),
            system_prompt_addendum=row["system_prompt_addendum"],
            turn_limit_override=row["turn_limit_override"],
        )

    def set_session_context(self, task_id: str, ctx: SessionContext) -> None:
        now = _now_iso()
        conn = self._conn()
        with conn:
            conn.execute(
                """
                INSERT INTO session_contexts
                    (task_id, mode, allowed_tools,
                     system_prompt_addendum, turn_limit_override, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    mode                   = excluded.mode,
                    allowed_tools          = excluded.allowed_tools,
                    system_prompt_addendum = excluded.system_prompt_addendum,
                    turn_limit_override    = excluded.turn_limit_override
                """,
                (
                    task_id,
                    ctx.mode.value,
                    json.dumps(sorted(ctx.allowed_tools)),
                    ctx.system_prompt_addendum,
                    ctx.turn_limit_override,
                    now,
                ),
            )

    def clear_session_context(self, task_id: str) -> None:
        conn = self._conn()
        with conn:
            conn.execute(
                "DELETE FROM session_contexts WHERE task_id = ?",
                (task_id,),
            )

    def get_active_session_contexts(
        self,
    ) -> list[tuple[str, SessionContext]]:
        rows = self._conn().execute(
            "SELECT * FROM session_contexts"
        ).fetchall()
        result = []
        for row in rows:
            ctx = SessionContext(
                mode=SessionMode(row["mode"]),
                allowed_tools=set(json.loads(row["allowed_tools"])),
                system_prompt_addendum=row["system_prompt_addendum"],
                turn_limit_override=row["turn_limit_override"],
            )
            result.append((row["task_id"], ctx))
        return result

    # ------------------------------------------------------------------
    # Merge locks
    # ------------------------------------------------------------------

    def acquire_merge_lock(self, branch: str, task_id: str) -> bool:
        """
        Acquire the merge lock for the given branch atomically.

        Clears stale locks (holder is terminal/missing or lock is > 24h old)
        before attempting acquisition.
        """
        from datetime import timedelta
        now = _now_iso()
        now_dt = datetime.now(timezone.utc)
        conn = self._conn()

        with conn:
            row = conn.execute(
                "SELECT locked_by, locked_at FROM merge_locks WHERE branch = ?",
                (branch,),
            ).fetchone()

            if row is not None:
                locked_by = row["locked_by"]
                locked_at_str = row["locked_at"]

                # Check if lock is stale
                stale = False

                # 24-hour hard ceiling
                try:
                    locked_at_dt = datetime.fromisoformat(locked_at_str)
                    if locked_at_dt.tzinfo is None:
                        locked_at_dt = locked_at_dt.replace(tzinfo=timezone.utc)
                    if (now_dt - locked_at_dt) > timedelta(hours=24):
                        stale = True
                except (ValueError, TypeError):
                    stale = True

                # Check holder task status
                if not stale:
                    holder_row = conn.execute(
                        "SELECT status FROM tasks WHERE id = ?",
                        (locked_by,),
                    ).fetchone()
                    if holder_row is None:
                        stale = True
                    else:
                        holder_status = TaskStatus(holder_row["status"])
                        if holder_status not in (
                            TaskStatus.RUNNING,
                            TaskStatus.BLOCKED_BY_HUMAN,
                        ):
                            stale = True

                if stale:
                    conn.execute(
                        "DELETE FROM merge_locks WHERE branch = ?",
                        (branch,),
                    )
                else:
                    return False  # lock is live, cannot acquire

            # Lock is free (or was stale and cleared) — acquire it
            conn.execute(
                "INSERT INTO merge_locks (branch, locked_by, locked_at) "
                "VALUES (?, ?, ?)",
                (branch, task_id, now),
            )
            return True

    def enqueue_merge_waiter(self, branch: str, task_id: str) -> None:
        conn = self._conn()
        with conn:
            row = conn.execute(
                "SELECT queue FROM merge_locks WHERE branch = ?",
                (branch,),
            ).fetchone()
            if row is None:
                # No lock row exists yet — create one with this task in queue
                # It will be granted the lock immediately on next acquire attempt
                conn.execute(
                    "INSERT OR IGNORE INTO merge_locks "
                    "(branch, locked_by, locked_at, queue) VALUES (?, '', '', ?)",
                    (branch, json.dumps([task_id])),
                )
            else:
                queue = json.loads(row["queue"] or "[]")
                if task_id not in queue:
                    queue.append(task_id)
                conn.execute(
                    "UPDATE merge_locks SET queue = ? WHERE branch = ?",
                    (json.dumps(queue), branch),
                )

    def dequeue_next_merge_waiter(self, branch: str) -> str | None:
        conn = self._conn()
        with conn:
            row = conn.execute(
                "SELECT queue FROM merge_locks WHERE branch = ?",
                (branch,),
            ).fetchone()
            if row is None:
                return None
            queue = json.loads(row["queue"] or "[]")
            if not queue:
                return None
            next_task_id = queue.pop(0)
            conn.execute(
                "UPDATE merge_locks SET queue = ? WHERE branch = ?",
                (json.dumps(queue), branch),
            )
            return next_task_id

    def release_merge_lock(self, branch: str, task_id: str) -> None:
        now = _now_iso()
        conn = self._conn()
        with conn:
            # Check if there's a next waiter before deleting the lock row
            row = conn.execute(
                "SELECT queue FROM merge_locks "
                "WHERE branch = ? AND locked_by = ?",
                (branch, task_id),
            ).fetchone()
            if row is None:
                return  # not the lock holder — no-op

            queue = json.loads(row["queue"] or "[]")
            if queue:
                # Grant lock to next waiter atomically
                next_task_id = queue.pop(0)
                conn.execute(
                    "UPDATE merge_locks SET "
                    "locked_by = ?, locked_at = ?, queue = ? "
                    "WHERE branch = ?",
                    (next_task_id, now, json.dumps(queue), branch),
                )
                logger.info(
                    "Merge lock on '%s' transferred from [%s] to [%s].",
                    branch, task_id, next_task_id,
                )
            else:
                # No waiters — release entirely
                conn.execute(
                    "DELETE FROM merge_locks WHERE branch = ? AND locked_by = ?",
                    (branch, task_id),
                )

    def get_merge_lock_holder(self, branch: str) -> str | None:
        row = self._conn().execute(
            "SELECT locked_by FROM merge_locks WHERE branch = ?",
            (branch,),
        ).fetchone()
        return row["locked_by"] if row else None

    # ------------------------------------------------------------------
    # Repo metadata and branch protection cache
    # ------------------------------------------------------------------

    def get_repo_metadata(self, repo_name: str) -> dict | None:
        row = self._conn().execute(
            "SELECT * FROM repo_metadata WHERE repo_name = ?",
            (repo_name,),
        ).fetchone()
        if row is None:
            return None
        return {
            "provider":           row["provider"],
            "remote_url":         row["remote_url"],
            "protected_branches": json.loads(row["protected_branches"]),
            "cache_timestamp":    row["cache_timestamp"],
        }

    def set_repo_metadata(
        self,
        repo_name: str,
        provider: str,
        remote_url: str,
    ) -> None:
        conn = self._conn()
        with conn:
            conn.execute(
                """
                INSERT INTO repo_metadata
                    (repo_name, provider, remote_url,
                     protected_branches, cache_timestamp)
                VALUES (?, ?, ?, '[]', '')
                ON CONFLICT(repo_name) DO UPDATE SET
                    provider   = excluded.provider,
                    remote_url = excluded.remote_url
                """,
                (repo_name, provider, remote_url),
            )

    def get_protected_branches_cached(
        self, repo_name: str
    ) -> tuple[list[str], str] | None:
        row = self._conn().execute(
            "SELECT protected_branches, cache_timestamp "
            "FROM repo_metadata WHERE repo_name = ?",
            (repo_name,),
        ).fetchone()
        if row is None or not row["cache_timestamp"]:
            return None
        return json.loads(row["protected_branches"]), row["cache_timestamp"]

    def set_protected_branches_cached(
        self,
        repo_name: str,
        branches: list[str],
    ) -> None:
        now = _now_iso()
        conn = self._conn()
        with conn:
            conn.execute(
                """
                INSERT INTO repo_metadata
                    (repo_name, provider, remote_url,
                     protected_branches, cache_timestamp)
                VALUES (?, '', '', ?, ?)
                ON CONFLICT(repo_name) DO UPDATE SET
                    protected_branches = excluded.protected_branches,
                    cache_timestamp    = excluded.cache_timestamp
                """,
                (repo_name, json.dumps(branches), now),
            )