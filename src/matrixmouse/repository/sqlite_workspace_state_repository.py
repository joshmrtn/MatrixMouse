"""
matrixmouse/repository/sqlite_workspace_state_repository.py

SQLite-backed implementation of WorkspaceStateRepository.

Shares the matrixmouse.db file with SQLiteTaskRepository via the
shared connection manager in sqlite_db. Schema is initialised by
init_db() which is called by both repositories on startup.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from matrixmouse.repository.sqlite_db import get_connection, init_db
from matrixmouse.repository.workspace_state_repository import (
    WorkspaceStateRepository,
)

logger = logging.getLogger(__name__)


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
    