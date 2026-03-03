"""
matrixmouse/utils/file_lock.py

File locking utility for safe concurrent access to shared JSON files.

Uses fcntl.flock() for exclusive locking, which provides:
    - Automatic release on process death (lock tied to file descriptor)
    - Blocking acquisition with configurable timeout
    - Safe concurrent access between the CLI and the running agent

LINUX ONLY — fcntl is not available on Windows. MatrixMouse is
explicitly a Linux application and portability to Windows is not a goal.
If porting to Windows, replace with msvcrt.locking() or a lock file
approach using pathlib.

Typical usage:
    with locked_json(path) as (data, save):
        data.append(new_item)
        save(data)
"""

import contextlib
import fcntl
import json
import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Default timeout before giving up on acquiring the lock.
# 10 seconds is generous — normal operations complete in milliseconds.
# A hung process holding the lock longer than this is a bug worth surfacing.
DEFAULT_LOCK_TIMEOUT = 10.0

# How long to wait between lock attempts (seconds)
_RETRY_INTERVAL = 0.05  # 50ms — responsive without busy-waiting


class LockTimeoutError(Exception):
    """Raised when a file lock cannot be acquired within the timeout."""
    pass


@contextlib.contextmanager
def locked_json(
    path: Path,
    timeout: float = DEFAULT_LOCK_TIMEOUT,
):
    """
    Open a JSON file with an exclusive lock, yield its parsed contents
    and a save callable, then release the lock.

    The lock is held for the entire duration of the with block.
    Keep the block short — do not do inference or network calls inside it.

    Args:
        path:    Path to the JSON file. Created (empty list) if missing.
        timeout: Seconds to wait for the lock before raising LockTimeoutError.

    Yields:
        (data, save) where:
            data: Parsed JSON content (list or dict).
            save: Callable that accepts new data and writes it back.

    Raises:
        LockTimeoutError: If the lock cannot be acquired within timeout.

    Example:
        with locked_json(tasks_file) as (tasks, save):
            tasks.append(new_task)
            save(tasks)
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    # Open for read+write, create if missing
    mode = "r+" if path.exists() else "w+"
    with open(path, mode) as f:
        _acquire_lock(f, path, timeout)
        try:
            # Read current content
            f.seek(0)
            content = f.read().strip()
            data = json.loads(content) if content else []

            # save() writes back to the same file descriptor
            def save(new_data: Any) -> None:
                f.seek(0)
                f.truncate()
                json.dump(new_data, f, indent=2)
                f.flush()

            yield data, save

        finally:
            fcntl.flock(f, fcntl.LOCK_UN)
            logger.debug("Lock released: %s", path)


def _acquire_lock(f, path: Path, timeout: float) -> None:
    """
    Acquire an exclusive lock on file f within timeout seconds.

    Uses non-blocking attempts with a retry loop rather than blocking
    indefinitely, so we can surface a clear timeout error instead of
    hanging forever.

    Args:
        f:       Open file object to lock.
        path:    Path of the file (for error messages only).
        timeout: Maximum seconds to wait.

    Raises:
        LockTimeoutError: If lock not acquired within timeout.
    """
    deadline = time.monotonic() + timeout
    attempt = 0

    while True:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if attempt > 0:
                logger.debug(
                    "Lock acquired on %s after %d attempt(s).", path.name, attempt
                )
            return  # Lock acquired

        except BlockingIOError:
            # File is locked by another process
            attempt += 1
            remaining = deadline - time.monotonic()

            if remaining <= 0:
                raise LockTimeoutError(
                    f"Could not acquire lock on '{path}' within {timeout}s. "
                    f"Another process may be holding it. "
                    f"If MatrixMouse crashed, the lock will release automatically. "
                    f"If the problem persists, check for stuck processes."
                )

            if attempt == 1:
                logger.debug("Waiting for lock on %s...", path.name)

            time.sleep(min(_RETRY_INTERVAL, remaining))
