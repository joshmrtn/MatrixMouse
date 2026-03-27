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
# Remove the local class definition entirely, replace with:
from matrixmouse.repository.memory_workspace_state_repository import (
    InMemoryWorkspaceStateRepository,
)


@pytest.fixture(params=["sqlite", "memory"])
def ws_repo(request, tmp_path):
    if request.param == "sqlite":
        db_path = tmp_path / ".matrixmouse" / "matrixmouse.db"
        db_path.parent.mkdir(parents=True)
        return SQLiteWorkspaceStateRepository(db_path)
    else:
        return InMemoryWorkspaceStateRepository()

@pytest.fixture(params=["sqlite"])
def ws_repo_with_tasks(request, tmp_path):
    """
    Workspace state repo alongside a task repo sharing the same DB.
    SQLite-only — the shared database is required for cross-repo FK constraints
    and stale lock detection that checks task status via JOIN.
    """
    db_path = tmp_path / ".matrixmouse" / "matrixmouse.db"
    db_path.parent.mkdir(parents=True)
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


# ---------------------------------------------------------------------------
# Session contexts
# ---------------------------------------------------------------------------

class TestSessionContexts:
    def test_get_returns_none_when_absent(self, ws_repo):
        assert ws_repo.get_session_context("nonexistent") is None

    def test_set_and_get_roundtrip(self, ws_repo):
        from matrixmouse.repository.workspace_state_repository import (
            SessionContext, SessionMode
        )
        ctx = SessionContext(
            mode=SessionMode.BRANCH_SETUP,
            allowed_tools={"get_task_info", "set_branch"},
            system_prompt_addendum="You must name the branch first.",
            turn_limit_override=5,
        )
        ws_repo.set_session_context("task123", ctx)
        retrieved = ws_repo.get_session_context("task123")
        assert retrieved is not None
        assert retrieved.mode == SessionMode.BRANCH_SETUP
        assert retrieved.allowed_tools == {"get_task_info", "set_branch"}
        assert retrieved.system_prompt_addendum == "You must name the branch first."
        assert retrieved.turn_limit_override == 5

    def test_set_overwrites_existing(self, ws_repo):
        from matrixmouse.repository.workspace_state_repository import (
            SessionContext, SessionMode
        )
        ctx1 = SessionContext(mode=SessionMode.BRANCH_SETUP, allowed_tools={"a"})
        ctx2 = SessionContext(mode=SessionMode.PLANNING, allowed_tools={"b"})
        ws_repo.set_session_context("task123", ctx1)
        ws_repo.set_session_context("task123", ctx2)
        retrieved = ws_repo.get_session_context("task123")
        assert retrieved is not None
        assert retrieved.mode == SessionMode.PLANNING

    def test_clear_removes_context(self, ws_repo):
        from matrixmouse.repository.workspace_state_repository import (
            SessionContext, SessionMode
        )
        ctx = SessionContext(mode=SessionMode.PLANNING, allowed_tools=set())
        ws_repo.set_session_context("task123", ctx)
        ws_repo.clear_session_context("task123")
        assert ws_repo.get_session_context("task123") is None

    def test_clear_noop_when_absent(self, ws_repo):
        ws_repo.clear_session_context("nonexistent")  # should not raise

    def test_get_active_returns_all(self, ws_repo):
        from matrixmouse.repository.workspace_state_repository import (
            SessionContext, SessionMode
        )
        ctx1 = SessionContext(mode=SessionMode.BRANCH_SETUP, allowed_tools=set())
        ctx2 = SessionContext(mode=SessionMode.PLANNING, allowed_tools=set())
        ws_repo.set_session_context("t1", ctx1)
        ws_repo.set_session_context("t2", ctx2)
        active = dict(ws_repo.get_active_session_contexts())
        assert "t1" in active
        assert "t2" in active

    def test_all_session_modes_roundtrip(self, ws_repo):
        from matrixmouse.repository.workspace_state_repository import (
            SessionContext, SessionMode
        )
        for mode in SessionMode:
            ctx = SessionContext(mode=mode, allowed_tools=set())
            ws_repo.set_session_context(f"task_{mode.value}", ctx)
            retrieved = ws_repo.get_session_context(f"task_{mode.value}")
            assert retrieved is not None
            assert retrieved.mode == mode


# ---------------------------------------------------------------------------
# Merge locks
# ---------------------------------------------------------------------------

class TestMergeLocks:
    def test_acquire_succeeds_when_unlocked(self, ws_repo):
        assert ws_repo.acquire_merge_lock("mm/refactor/foo", "task1") is True

    def test_acquire_fails_when_locked_by_active_task(self, tmp_path):
        from matrixmouse.repository.sqlite_task_repository import SQLiteTaskRepository
        from matrixmouse.repository.sqlite_workspace_state_repository import (
            SQLiteWorkspaceStateRepository,
        )
        db_path = tmp_path / ".matrixmouse" / "matrixmouse.db"
        task_repo = SQLiteTaskRepository(db_path)
        ws = SQLiteWorkspaceStateRepository(db_path)

        from matrixmouse.task import Task, AgentRole
        t = Task(
            title="t", description="d",
            role=AgentRole.MANAGER,
            repo=["r"]
        )
        task_repo.add(t)
        task_repo.mark_running(t.id)

        assert ws.acquire_merge_lock("mm/refactor/foo", t.id) is True
        assert ws.acquire_merge_lock("mm/refactor/foo", "other_task") is False

    def test_release_frees_lock(self, ws_repo):
        ws_repo.acquire_merge_lock("mm/refactor/foo", "task1")
        ws_repo.release_merge_lock("mm/refactor/foo", "task1")
        assert ws_repo.acquire_merge_lock("mm/refactor/foo", "task2") is True

    def test_release_noop_when_not_holder(self, ws_repo):
        ws_repo.acquire_merge_lock("mm/refactor/foo", "task1")
        ws_repo.release_merge_lock("mm/refactor/foo", "task2")  # wrong holder
        assert ws_repo.get_merge_lock_holder("mm/refactor/foo") == "task1"

    def test_get_lock_holder_returns_none_when_unlocked(self, ws_repo):
        assert ws_repo.get_merge_lock_holder("mm/refactor/foo") is None

    def test_get_lock_holder_returns_task_id(self, ws_repo):
        ws_repo.acquire_merge_lock("mm/refactor/foo", "task1")
        assert ws_repo.get_merge_lock_holder("mm/refactor/foo") == "task1"

    def test_different_branches_independent(self, ws_repo):
        assert ws_repo.acquire_merge_lock("mm/feature/a", "task1") is True
        assert ws_repo.acquire_merge_lock("mm/feature/b", "task2") is True
        assert ws_repo.get_merge_lock_holder("mm/feature/a") == "task1"
        assert ws_repo.get_merge_lock_holder("mm/feature/b") == "task2"


# ---------------------------------------------------------------------------
# Repo metadata and branch protection cache
# ---------------------------------------------------------------------------

class TestRepoMetadata:
    def test_get_returns_none_when_absent(self, ws_repo):
        assert ws_repo.get_repo_metadata("nonexistent") is None

    def test_set_and_get_roundtrip(self, ws_repo):
        ws_repo.set_repo_metadata("my-repo", "github",
                                   "https://github.com/user/my-repo")
        meta = ws_repo.get_repo_metadata("my-repo")
        assert meta is not None
        assert meta["provider"] == "github"
        assert meta["remote_url"] == "https://github.com/user/my-repo"

    def test_set_overwrites_provider(self, ws_repo):
        ws_repo.set_repo_metadata("my-repo", "github", "https://github.com/a/b")
        ws_repo.set_repo_metadata("my-repo", "gitlab", "https://gitlab.com/a/b")
        meta = ws_repo.get_repo_metadata("my-repo")
        assert meta is not None
        assert meta["provider"] == "gitlab"

    def test_set_does_not_clear_cache(self, ws_repo):
        ws_repo.set_repo_metadata("my-repo", "github", "https://github.com/a/b")
        ws_repo.set_protected_branches_cached("my-repo", ["main", "master"])
        ws_repo.set_repo_metadata("my-repo", "github", "https://github.com/a/b")
        cached = ws_repo.get_protected_branches_cached("my-repo")
        assert cached is not None
        assert "main" in cached[0]

    def test_get_protected_branches_returns_none_when_absent(self, ws_repo):
        assert ws_repo.get_protected_branches_cached("nonexistent") is None

    def test_get_protected_branches_returns_none_when_no_cache(self, ws_repo):
        ws_repo.set_repo_metadata("my-repo", "github", "https://github.com/a/b")
        assert ws_repo.get_protected_branches_cached("my-repo") is None

    def test_set_protected_branches_stores_and_timestamps(self, ws_repo):
        ws_repo.set_protected_branches_cached("my-repo", ["main", "develop"])
        result = ws_repo.get_protected_branches_cached("my-repo")
        assert result is not None
        branches, timestamp = result
        assert "main" in branches
        assert "develop" in branches
        assert timestamp != ""

    def test_set_protected_branches_overwrites_existing(self, ws_repo):
        ws_repo.set_protected_branches_cached("my-repo", ["main"])
        ws_repo.set_protected_branches_cached("my-repo", ["main", "release"])
        result = ws_repo.get_protected_branches_cached("my-repo")
        assert result is not None
        assert "release" in result[0]

    def test_multiple_repos_independent(self, ws_repo):
        ws_repo.set_repo_metadata("repo-a", "github", "https://github.com/a")
        ws_repo.set_repo_metadata("repo-b", "gitlab", "https://gitlab.com/b")
        assert ws_repo.get_repo_metadata("repo-a")["provider"] == "github"
        assert ws_repo.get_repo_metadata("repo-b")["provider"] == "gitlab"

class TestMergeLockQueue:
    def test_enqueue_adds_waiter(self, ws_repo):
        ws_repo.acquire_merge_lock("mm/feature/foo", "task1")
        ws_repo.enqueue_merge_waiter("mm/feature/foo", "task2")
        next_id = ws_repo.dequeue_next_merge_waiter("mm/feature/foo")
        assert next_id == "task2"

    def test_fifo_ordering_preserved(self, ws_repo):
        ws_repo.acquire_merge_lock("mm/feature/foo", "task1")
        ws_repo.enqueue_merge_waiter("mm/feature/foo", "task2")
        ws_repo.enqueue_merge_waiter("mm/feature/foo", "task3")
        ws_repo.enqueue_merge_waiter("mm/feature/foo", "task4")
        assert ws_repo.dequeue_next_merge_waiter("mm/feature/foo") == "task2"
        assert ws_repo.dequeue_next_merge_waiter("mm/feature/foo") == "task3"
        assert ws_repo.dequeue_next_merge_waiter("mm/feature/foo") == "task4"

    def test_dequeue_returns_none_on_empty(self, ws_repo):
        ws_repo.acquire_merge_lock("mm/feature/foo", "task1")
        assert ws_repo.dequeue_next_merge_waiter("mm/feature/foo") is None

    def test_release_grants_lock_to_next_waiter(self, ws_repo):
        ws_repo.acquire_merge_lock("mm/feature/foo", "task1")
        ws_repo.enqueue_merge_waiter("mm/feature/foo", "task2")
        ws_repo.release_merge_lock("mm/feature/foo", "task1")
        assert ws_repo.get_merge_lock_holder("mm/feature/foo") == "task2"

    def test_release_with_no_waiters_frees_lock(self, ws_repo):
        ws_repo.acquire_merge_lock("mm/feature/foo", "task1")
        ws_repo.release_merge_lock("mm/feature/foo", "task1")
        assert ws_repo.get_merge_lock_holder("mm/feature/foo") is None

    def test_release_grants_first_waiter_only(self, ws_repo):
        ws_repo.acquire_merge_lock("mm/feature/foo", "task1")
        ws_repo.enqueue_merge_waiter("mm/feature/foo", "task2")
        ws_repo.enqueue_merge_waiter("mm/feature/foo", "task3")
        ws_repo.release_merge_lock("mm/feature/foo", "task1")
        assert ws_repo.get_merge_lock_holder("mm/feature/foo") == "task2"
        # task3 still waiting
        assert ws_repo.dequeue_next_merge_waiter("mm/feature/foo") == "task3"

    def test_duplicate_not_enqueued(self, ws_repo):
        ws_repo.acquire_merge_lock("mm/feature/foo", "task1")
        ws_repo.enqueue_merge_waiter("mm/feature/foo", "task2")
        ws_repo.enqueue_merge_waiter("mm/feature/foo", "task2")
        assert ws_repo.dequeue_next_merge_waiter("mm/feature/foo") == "task2"
        assert ws_repo.dequeue_next_merge_waiter("mm/feature/foo") is None