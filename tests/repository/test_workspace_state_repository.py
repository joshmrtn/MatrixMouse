"""
tests/repository/test_workspace_state_repository.py

Shared test suite for WorkspaceStateRepository implementations.

Parametrised against SQLiteWorkspaceStateRepository. An in-memory
implementation can be added later if needed.

Coverage:
    get / set / delete:
        - get returns None for missing key
        - set stores value retrievable by get
        - set overwrites existing value
        - delete removes key
        - delete is no-op for missing key
        - values round-trip through JSON (dict, list, int, str)

    get/set_last_review_at:
        - Returns None when not set
        - Returns timezone-aware datetime after set
        - Defaults to now when no dt provided
        - Provided datetime is stored and retrieved accurately

    get/set_last_review_summary:
        - Returns empty string when not set
        - Stores and retrieves summary string

    stale clarification registry:
        - get returns None for unknown task
        - register stores mapping
        - register overwrites existing mapping
        - clear removes mapping
        - clear is no-op for unknown task
        - all_stale_clarification_tasks returns full mapping
        - multiple entries are independent
"""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from matrixmouse.repository.sqlite_task_repository import SQLiteTaskRepository
from matrixmouse.repository.sqlite_workspace_state_repository import (
    SQLiteWorkspaceStateRepository,
)
from matrixmouse.repository.workspace_state_repository import (
    WorkspaceStateRepository,
)


@pytest.fixture
def ws_repo(tmp_path) -> WorkspaceStateRepository:
    db_path = tmp_path / ".matrixmouse" / "matrixmouse.db"
    return SQLiteWorkspaceStateRepository(db_path)

@pytest.fixture
def ws_repo_with_tasks(tmp_path):
    """Workspace state repo alongside a task repo sharing the same DB."""
    db_path = tmp_path / ".matrixmouse" / "matrixmouse.db"
    task_repo = SQLiteTaskRepository(db_path)
    ws_repo = SQLiteWorkspaceStateRepository(db_path)
    return ws_repo, task_repo

# ---------------------------------------------------------------------------
# get / set / delete
# ---------------------------------------------------------------------------

class TestPrimitives:
    def test_get_returns_none_for_missing(self, ws_repo):
        assert ws_repo.get("nonexistent") is None

    def test_set_and_get_string(self, ws_repo):
        ws_repo.set("key", "value")
        assert ws_repo.get("key") == "value"

    def test_set_and_get_dict(self, ws_repo):
        ws_repo.set("data", {"a": 1, "b": [1, 2, 3]})
        result = ws_repo.get("data")
        assert result == {"a": 1, "b": [1, 2, 3]}

    def test_set_and_get_int(self, ws_repo):
        ws_repo.set("count", 42)
        assert ws_repo.get("count") == 42

    def test_set_overwrites_existing(self, ws_repo):
        ws_repo.set("key", "first")
        ws_repo.set("key", "second")
        assert ws_repo.get("key") == "second"

    def test_delete_removes_key(self, ws_repo):
        ws_repo.set("key", "value")
        ws_repo.delete("key")
        assert ws_repo.get("key") is None

    def test_delete_noop_for_missing(self, ws_repo):
        ws_repo.delete("nonexistent")  # should not raise


# ---------------------------------------------------------------------------
# last_review_at
# ---------------------------------------------------------------------------

class TestLastReviewAt:
    def test_returns_none_when_not_set(self, ws_repo):
        assert ws_repo.get_last_review_at() is None

    def test_returns_timezone_aware_datetime(self, ws_repo):
        ws_repo.set_last_review_at()
        dt = ws_repo.get_last_review_at()
        assert dt is not None
        assert dt.tzinfo is not None

    def test_defaults_to_now(self, ws_repo):
        before = datetime.now(timezone.utc)
        ws_repo.set_last_review_at()
        after = datetime.now(timezone.utc)
        dt = ws_repo.get_last_review_at()
        assert dt is not None
        assert before <= dt <= after

    def test_stores_provided_datetime(self, ws_repo):
        target = datetime(2026, 3, 1, 9, 0, 0, tzinfo=timezone.utc)
        ws_repo.set_last_review_at(target)
        result = ws_repo.get_last_review_at()
        assert result is not None
        assert result.year == 2026
        assert result.month == 3
        assert result.day == 1


# ---------------------------------------------------------------------------
# last_review_summary
# ---------------------------------------------------------------------------

class TestLastReviewSummary:
    def test_returns_empty_string_when_not_set(self, ws_repo):
        assert ws_repo.get_last_review_summary() == ""

    def test_stores_and_retrieves_summary(self, ws_repo):
        ws_repo.set_last_review_summary("All tasks look healthy.")
        assert ws_repo.get_last_review_summary() == "All tasks look healthy."

    def test_overwrites_existing_summary(self, ws_repo):
        ws_repo.set_last_review_summary("first")
        ws_repo.set_last_review_summary("second")
        assert ws_repo.get_last_review_summary() == "second"


# ---------------------------------------------------------------------------
# Stale clarification registry
# ---------------------------------------------------------------------------

class TestStaleClarificationRegistry:
    @pytest.fixture
    def repos(self, tmp_path):
        db_path = tmp_path / ".matrixmouse" / "matrixmouse.db"
        task_repo = SQLiteTaskRepository(db_path)
        ws_repo = SQLiteWorkspaceStateRepository(db_path)
        return ws_repo, task_repo

    def _add_tasks(self, task_repo, *ids):
        """Add placeholder tasks with the given IDs."""
        from matrixmouse.task import Task, AgentRole
        for tid in ids:
            t = Task(title=f"task {tid}", description="d",
                     role=AgentRole.CODER, repo=["r"])
            t.id = tid
            task_repo.add(t)

    def test_get_returns_none_for_unknown(self, repos):
        ws_repo, _ = repos
        assert ws_repo.get_stale_clarification_task("unknown") is None

    def test_register_stores_mapping(self, repos):
        ws_repo, task_repo = repos
        self._add_tasks(task_repo, "blocked1", "manager1")
        ws_repo.register_stale_clarification_task("blocked1", "manager1")
        assert ws_repo.get_stale_clarification_task("blocked1") == "manager1"

    def test_register_overwrites_existing(self, repos):
        ws_repo, task_repo = repos
        self._add_tasks(task_repo, "blocked1", "manager1", "manager2")
        ws_repo.register_stale_clarification_task("blocked1", "manager1")
        ws_repo.register_stale_clarification_task("blocked1", "manager2")
        assert ws_repo.get_stale_clarification_task("blocked1") == "manager2"

    def test_clear_removes_mapping(self, repos):
        ws_repo, task_repo = repos
        self._add_tasks(task_repo, "blocked1", "manager1")
        ws_repo.register_stale_clarification_task("blocked1", "manager1")
        ws_repo.clear_stale_clarification_task("blocked1")
        assert ws_repo.get_stale_clarification_task("blocked1") is None

    def test_clear_noop_for_unknown(self, repos):
        ws_repo, _ = repos
        ws_repo.clear_stale_clarification_task("nonexistent")

    def test_all_returns_full_mapping(self, repos):
        ws_repo, task_repo = repos
        self._add_tasks(task_repo, "b1", "m1", "b2", "m2")
        ws_repo.register_stale_clarification_task("b1", "m1")
        ws_repo.register_stale_clarification_task("b2", "m2")
        result = ws_repo.all_stale_clarification_tasks()
        assert result == {"b1": "m1", "b2": "m2"}

    def test_multiple_entries_independent(self, repos):
        ws_repo, task_repo = repos
        self._add_tasks(task_repo, "b1", "m1", "b2", "m2")
        ws_repo.register_stale_clarification_task("b1", "m1")
        ws_repo.register_stale_clarification_task("b2", "m2")
        ws_repo.clear_stale_clarification_task("b1")
        assert ws_repo.get_stale_clarification_task("b1") is None
        assert ws_repo.get_stale_clarification_task("b2") == "m2"
