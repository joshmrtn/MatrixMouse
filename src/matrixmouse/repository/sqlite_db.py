"""
matrixmouse/repository/sqlite_db.py

Shared SQLite infrastructure for the repository layer.

Provides a per-thread connection manager and idempotent schema
initialisation. All SQLite-backed repositories use get_connection()
rather than managing their own connections, ensuring:

    - One connection per worker thread (not one per repository per thread)
    - Cross-repository operations can share transactions
    - WAL journal mode: readers never block writers
    - Foreign key enforcement on every connection
    - Schema is created once per database file, idempotently

If a different database backend is added in the future (PostgreSQL,
MySQL, etc.), it gets its own infrastructure module (postgres_db.py,
etc.) following the same pattern. The repository ABCs are backend-agnostic.
"""

import sqlite3
import threading
from pathlib import Path

_local = threading.local()

_SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS tasks (
    id                              TEXT PRIMARY KEY,
    title                           TEXT NOT NULL,
    description                     TEXT NOT NULL DEFAULT '',
    status                          TEXT NOT NULL,
    role                            TEXT NOT NULL,
    repo                            TEXT NOT NULL DEFAULT '[]',
    target_files                    TEXT NOT NULL DEFAULT '[]',
    importance                      REAL NOT NULL DEFAULT 0.5,
    urgency                         REAL NOT NULL DEFAULT 0.5,
    depth                           INTEGER NOT NULL DEFAULT 0,
    parent_task_id                  TEXT REFERENCES tasks(id),
    reviews_task_id                 TEXT REFERENCES tasks(id),
    notes                           TEXT NOT NULL DEFAULT '',
    pending_question                TEXT NOT NULL DEFAULT '',
    last_review_summary             TEXT NOT NULL DEFAULT '',
    context_messages                TEXT NOT NULL DEFAULT '[]',
    wip_commit_hash                 TEXT NOT NULL DEFAULT '',
    branch                          TEXT NOT NULL DEFAULT '',
    decomposition_confirmed_depth   INTEGER NOT NULL DEFAULT 0,
    turn_limit                      INTEGER NOT NULL DEFAULT 0,
    preempt                         INTEGER NOT NULL DEFAULT 0,
    time_slice_started              REAL,
    started_at                      TEXT,
    completed_at                    TEXT,
    created_at                      TEXT NOT NULL,
    last_modified                   TEXT NOT NULL,
    data                            TEXT
);

CREATE TABLE IF NOT EXISTS task_dependencies (
    blocking_task_id    TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    blocked_task_id     TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    PRIMARY KEY (blocking_task_id, blocked_task_id)
);

CREATE TABLE IF NOT EXISTS stale_clarification_tasks (
    blocked_task_id     TEXT PRIMARY KEY
                            REFERENCES tasks(id) ON DELETE CASCADE,
    manager_task_id     TEXT NOT NULL
                            REFERENCES tasks(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS workspace_state (
    key     TEXT PRIMARY KEY,
    value   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tasks_status
    ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_parent
    ON tasks(parent_task_id);
CREATE INDEX IF NOT EXISTS idx_tasks_last_modified
    ON tasks(last_modified);
CREATE INDEX IF NOT EXISTS idx_dependencies_blocked
    ON task_dependencies(blocked_task_id);
"""


def get_connection(db_path: Path) -> sqlite3.Connection:
    """
    Return the per-thread SQLite connection for db_path.

    Creates the connection on first call for this thread. Subsequent
    calls on the same thread return the existing connection.

    Multiple repositories targeting the same db_path on the same thread
    share one connection, making cross-repository transactions possible.

    Args:
        db_path: Absolute path to the SQLite database file.

    Returns:
        A configured sqlite3.Connection with WAL mode and foreign keys.
    """
    key = f"conn_{db_path}"
    conn = getattr(_local, key, None)
    if conn is None:
        conn = sqlite3.connect(
            str(db_path),
            check_same_thread=False,
            timeout=30,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA foreign_keys = ON")
        setattr(_local, key, conn)
    return conn


def init_db(db_path: Path) -> None:
    """
    Create all tables and indexes if they do not exist.

    Idempotent — safe to call on every startup and from multiple
    repositories targeting the same file. Uses CREATE TABLE IF NOT EXISTS
    throughout so repeated calls are harmless.

    Args:
        db_path: Absolute path to the SQLite database file.
                 Parent directories are created if needed.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = get_connection(db_path)
    conn.executescript(_SCHEMA)
    conn.commit()
    