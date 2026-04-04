"""
matrixmouse/inference/availability.py

BackendAvailabilityCache — tracks connection failure state per backend
using exponential backoff.

Persists to WorkspaceStateRepository (existing workspace_state key-value
table, key prefix ``backend_availability:{name}``) so cooldowns survive
service restarts and are visible across workers. No new schema table required.

Storage value schema:
{
    "consecutive_failures": 3,
    "cooldown_until": "2026-04-02T04:30:00+00:00",
    "last_failure_at": "2026-04-02T04:20:00+00:00"
}

Backoff calculation:
    cooldown_duration = min(initial * 2^(consecutive_failures - 1), max)

| Failure # | Duration (defaults) |
|-----------|---------------------|
| 1         | 30s                 |
| 2         | 60s                 |
| 3         | 120s                |
| 4         | 240s                |
| 5+        | 600s (cap)          |

``record_failure`` guards against stale cooldown compounding: if the stored
``cooldown_until`` is already in the past when read, ``consecutive_failures``
is reset to 0 before incrementing. A backend that recovered and then failed
again gets a fresh backoff sequence.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from matrixmouse.repository.workspace_state_repository import (
    WorkspaceStateRepository,
)

# Prefix for storage keys in the workspace state repository.
_AVAILABILITY_PREFIX = "backend_availability:"


class BackendAvailabilityCache:
    """Tracks connection failure state per backend using exponential backoff.

    Persists to WorkspaceStateRepository so cooldowns survive service restarts
    and are visible across workers.
    """

    def __init__(
        self,
        ws_state_repo: WorkspaceStateRepository,
        initial_cooldown_seconds: int = 30,
        max_cooldown_seconds: int = 600,
    ) -> None:
        self._repo = ws_state_repo
        self._initial = initial_cooldown_seconds
        self._max = max_cooldown_seconds

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def is_available(self, backend: str) -> bool:
        """True if the backend has no active cooldown.

        Returns True if no record exists or cooldown_until has passed.

        Args:
            backend: Backend identifier string, e.g. ``"anthropic"``.

        Returns:
            True if the backend is available, False if in cooldown.
        """
        record = self._read_record(backend)
        if record is None:
            return True

        cooldown_until = record.get("cooldown_until")
        if cooldown_until is None:
            return True

        try:
            cooldown_dt = datetime.fromisoformat(cooldown_until)
            return datetime.now(timezone.utc) >= cooldown_dt
        except (ValueError, TypeError):
            return True

    def record_failure(self, backend: str) -> datetime:
        """Record a connection failure and return the new cooldown_until.

        Resets consecutive_failures to 0 first if prior cooldown_until
        has already passed (stale failure run — treat as fresh start).

        Args:
            backend: Backend identifier string.

        Returns:
            The new cooldown_until datetime after this failure.
        """
        now = datetime.now(timezone.utc)
        record = self._read_record(backend)

        if record is not None:
            # Check if prior cooldown has expired — reset if stale
            cooldown_until = record.get("cooldown_until")
            if cooldown_until is not None:
                try:
                    cooldown_dt = datetime.fromisoformat(cooldown_until)
                    if now >= cooldown_dt:
                        # Stale run — treat as fresh start
                        record["consecutive_failures"] = 0
                except (ValueError, TypeError):
                    pass
            consecutive = record.get("consecutive_failures", 0) + 1
        else:
            consecutive = 1

        # Backoff: min(initial * 2^(failures - 1), max)
        backoff = min(
            self._initial * (2 ** (consecutive - 1)),
            self._max,
        )
        cooldown_until = now + timedelta(seconds=backoff)

        new_record: dict[str, Any] = {
            "consecutive_failures": consecutive,
            "cooldown_until": cooldown_until.isoformat(),
            "last_failure_at": now.isoformat(),
        }
        self._write_record(backend, new_record)
        return cooldown_until

    def record_success(self, backend: str) -> None:
        """Clear failure state after successful inference.

        No-op if no record exists.

        Args:
            backend: Backend identifier string.
        """
        record = self._read_record(backend)
        if record is None:
            return

        record["consecutive_failures"] = 0
        record["cooldown_until"] = None
        self._write_record(backend, record)

    def earliest_available_at(self, backends: list[str]) -> datetime | None:
        """Return the earliest time any of the given backends exits cooldown.

        Returns None if any backend is already available.
        Used only when all cascade options have been exhausted.

        Args:
            backends: List of backend identifier strings.

        Returns:
            Earliest cooldown_until across all backends, or None if any
            backend is available or the list is empty.
        """
        if not backends:
            return None

        cooldown_times: list[datetime] = []

        for backend in backends:
            if self.is_available(backend):
                return None  # At least one is available

            record = self._read_record(backend)
            if record is not None and record.get("cooldown_until"):
                cooldown_times.append(
                    datetime.fromisoformat(record["cooldown_until"])
                )

        if not cooldown_times:
            return None

        return min(cooldown_times).isoformat()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _storage_key(self, backend: str) -> str:
        """Build the namespaced storage key for a backend.

        Args:
            backend: Backend identifier string.

        Returns:
            Key like ``backend_availability:anthropic``.
        """
        return f"{_AVAILABILITY_PREFIX}{backend}"

    def _read_record(self, backend: str) -> dict[str, Any] | None:
        """Read and return the availability record for a backend.

        Args:
            backend: Backend identifier string.

        Returns:
            Parsed record dict, or None if no record exists.
        """
        key = self._storage_key(backend)
        return self._repo.get(key)

    def _write_record(self, backend: str, record: dict[str, Any]) -> None:
        """Persist an availability record.

        Args:
            backend: Backend identifier string.
            record: Record dict to store (must be JSON-serialisable).
        """
        key = self._storage_key(backend)
        self._repo.set(key, record)
