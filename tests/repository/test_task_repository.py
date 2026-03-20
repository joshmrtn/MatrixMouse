"""
tests/repository/test_task_repository.py

Shared test suite for TaskRepository implementations.

Both InMemoryTaskRepository and SQLiteTaskRepository are tested against
the same cases via parametrised fixtures. Any behavioural difference
between implementations is a bug.

Coverage:
    add:
        - Task is retrievable after add
        - Duplicate id raises ValueError

    get:
        - Returns None for unknown id
        - Exact match
        - Prefix match returns task when unambiguous
        - Ambiguous prefix raises ValueError

    update:
        - Changes are persisted
        - last_modified is stamped automatically
        - Unknown id raises KeyError

    delete:
        - Task is gone after delete
        - Dependency edges are removed on delete
        - Unknown id raises KeyError

    all_tasks:
        - Returns all tasks regardless of status

    active_tasks:
        - Excludes COMPLETE and CANCELLED

    completed_ids:
        - Returns only terminal task ids

    is_ready:
        - True when no blockers
        - True when all blockers are terminal
        - False when any blocker is non-terminal
        - False for unknown task

    has_blockers:
        - False when no dependencies
        - True when non-terminal blocker exists
        - False when all blockers are terminal

    get_subtasks:
        - Returns direct children only
        - Empty list when no children

    get_blocked_by / get_blocking:
        - Returns correct tasks
        - Empty list when no dependencies

    add_dependency / remove_dependency:
        - Edge exists after add
        - Edge gone after remove
        - add is idempotent
        - remove is no-op for nonexistent edge
        - Unknown task raises KeyError

    mark_running:
        - Status set to RUNNING
        - time_slice_started set
        - started_at set on first run only
        - Unknown id raises KeyError

    mark_ready:
        - Status set to READY
        - time_slice_started cleared

    mark_complete:
        - Status set to COMPLETE
        - completed_at set
        - Dependent with no remaining blockers unblocked to READY
        - Dependent with remaining blockers stays BLOCKED_BY_TASK
        - Dependency edges to completing task removed

    mark_blocked_by_human:
        - Status set to BLOCKED_BY_HUMAN
        - Reason appended to notes
        - Empty reason leaves notes unchanged

    mark_cancelled:
        - Status set to CANCELLED
        - completed_at set

    add_subtask:
        - Subtask created with correct depth
        - Subtask inherits parent role/repo/importance/urgency by default
        - Explicit overrides respected
        - Parent becomes BLOCKED_BY_TASK
        - Dependency edge created: subtask blocks parent
        - Unknown parent raises KeyError
"""

import time
from pathlib import Path

import pytest

from matrixmouse.repository.memory_task_repository import (
    InMemoryTaskRepository,
)
from matrixmouse.repository.sqlite_task_repository import (
    SQLiteTaskRepository,
)
from matrixmouse.repository.task_repository import TaskRepository
from matrixmouse.task import AgentRole, Task, TaskStatus


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(params=["memory", "sqlite"])
def repo(request, tmp_path) -> TaskRepository:
    """Parametrised fixture — runs every test against both implementations."""
    if request.param == "memory":
        return InMemoryTaskRepository()
    db_path = tmp_path / ".matrixmouse" / "matrixmouse.db"
    return SQLiteTaskRepository(db_path)


def make_task(
    title: str = "Test task",
    description: str = "desc",
    role: AgentRole = AgentRole.CODER,
    repo: list[str] | None = None,
    importance: float = 0.5,
    urgency: float = 0.5,
    status: TaskStatus = TaskStatus.READY,
    **kwargs,
) -> Task:
    return Task(
        title=title,
        description=description,
        role=role,
        repo=repo or ["my-repo"],
        importance=importance,
        urgency=urgency,
        status=status,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# add
# ---------------------------------------------------------------------------

class TestAdd:
    def test_task_retrievable_after_add(self, repo):
        task = make_task(title="hello")
        repo.add(task)
        assert repo.get(task.id) is not None
        assert repo.get(task.id).title == "hello"

    def test_duplicate_id_raises_value_error(self, repo):
        task = make_task()
        repo.add(task)
        with pytest.raises(ValueError):
            repo.add(task)


# ---------------------------------------------------------------------------
# get
# ---------------------------------------------------------------------------

class TestGet:
    def test_returns_none_for_unknown(self, repo):
        assert repo.get("nonexistent") is None

    def test_exact_match(self, repo):
        task = make_task()
        repo.add(task)
        assert repo.get(task.id).id == task.id

    def test_prefix_match_unambiguous(self, repo):
        task = make_task()
        repo.add(task)
        prefix = task.id[:8]
        result = repo.get(prefix)
        assert result is not None
        assert result.id == task.id

    def test_ambiguous_prefix_raises(self, repo):
        # Force two tasks with the same prefix by manipulating ids
        t1 = make_task(title="a")
        t2 = make_task(title="b")
        t1.id = "aabbccdd11223344"
        t2.id = "aabbccdd55667788"
        repo.add(t1)
        repo.add(t2)
        with pytest.raises(ValueError):
            repo.get("aabbccdd")


# ---------------------------------------------------------------------------
# update
# ---------------------------------------------------------------------------

class TestUpdate:
    def test_changes_persisted(self, repo):
        task = make_task(title="original")
        repo.add(task)
        task.title = "updated"
        repo.update(task)
        assert repo.get(task.id).title == "updated"

    def test_last_modified_stamped(self, repo):
        task = make_task()
        repo.add(task)
        original = repo.get(task.id).last_modified
        time.sleep(0.01)
        task.title = "changed"
        repo.update(task)
        assert repo.get(task.id).last_modified != original

    def test_unknown_id_raises_key_error(self, repo):
        with pytest.raises(KeyError):
            repo.update(make_task())


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------

class TestDelete:
    def test_task_gone_after_delete(self, repo):
        task = make_task()
        repo.add(task)
        repo.delete(task.id)
        assert repo.get(task.id) is None

    def test_dependency_edges_removed_on_delete(self, repo):
        blocker = make_task(title="blocker")
        blocked = make_task(title="blocked")
        repo.add(blocker)
        repo.add(blocked)
        repo.add_dependency(blocker.id, blocked.id)
        repo.delete(blocker.id)
        assert repo.get_blocked_by(blocked.id) == []

    def test_unknown_id_raises_key_error(self, repo):
        with pytest.raises(KeyError):
            repo.delete("nonexistent")


# ---------------------------------------------------------------------------
# all_tasks / active_tasks / completed_ids
# ---------------------------------------------------------------------------

class TestQueries:
    def test_all_tasks_returns_all(self, repo):
        t1 = make_task(title="a")
        t2 = make_task(title="b", status=TaskStatus.COMPLETE)
        repo.add(t1)
        repo.add(t2)
        assert len(repo.all_tasks()) == 2

    def test_active_tasks_excludes_terminal(self, repo):
        active = make_task(title="active")
        done = make_task(title="done", status=TaskStatus.COMPLETE)
        cancelled = make_task(title="cancelled", status=TaskStatus.CANCELLED)
        for t in (active, done, cancelled):
            repo.add(t)
        result = repo.active_tasks()
        assert len(result) == 1
        assert result[0].title == "active"

    def test_completed_ids_terminal_only(self, repo):
        t1 = make_task(status=TaskStatus.COMPLETE)
        t2 = make_task(status=TaskStatus.CANCELLED)
        t3 = make_task(status=TaskStatus.READY)
        for t in (t1, t2, t3):
            repo.add(t)
        ids = repo.completed_ids()
        assert t1.id in ids
        assert t2.id in ids
        assert t3.id not in ids


# ---------------------------------------------------------------------------
# is_ready / has_blockers
# ---------------------------------------------------------------------------

class TestReadiness:
    def test_is_ready_no_blockers(self, repo):
        task = make_task()
        repo.add(task)
        assert repo.is_ready(task.id) is True

    def test_is_ready_all_blockers_terminal(self, repo):
        blocker = make_task(status=TaskStatus.COMPLETE)
        blocked = make_task()
        repo.add(blocker)
        repo.add(blocked)
        repo.add_dependency(blocker.id, blocked.id)
        assert repo.is_ready(blocked.id) is True

    def test_is_ready_false_with_active_blocker(self, repo):
        blocker = make_task(status=TaskStatus.RUNNING)
        blocked = make_task()
        repo.add(blocker)
        repo.add(blocked)
        repo.add_dependency(blocker.id, blocked.id)
        assert repo.is_ready(blocked.id) is False

    def test_is_ready_false_for_unknown(self, repo):
        assert repo.is_ready("nonexistent") is False

    def test_has_blockers_false_no_deps(self, repo):
        task = make_task()
        repo.add(task)
        assert repo.has_blockers(task.id) is False

    def test_has_blockers_true_with_active_blocker(self, repo):
        blocker = make_task()
        blocked = make_task()
        repo.add(blocker)
        repo.add(blocked)
        repo.add_dependency(blocker.id, blocked.id)
        assert repo.has_blockers(blocked.id) is True

    def test_has_blockers_false_when_all_terminal(self, repo):
        blocker = make_task(status=TaskStatus.COMPLETE)
        blocked = make_task()
        repo.add(blocker)
        repo.add(blocked)
        repo.add_dependency(blocker.id, blocked.id)
        assert repo.has_blockers(blocked.id) is False


# ---------------------------------------------------------------------------
# Dependency graph queries
# ---------------------------------------------------------------------------

class TestDependencyQueries:
    def test_get_subtasks_returns_children(self, repo):
        parent = make_task(title="parent")
        repo.add(parent)
        child = repo.add_subtask(parent.id, "child", "desc")
        subtasks = repo.get_subtasks(parent.id)
        assert len(subtasks) == 1
        assert subtasks[0].id == child.id

    def test_get_subtasks_empty_when_none(self, repo):
        task = make_task()
        repo.add(task)
        assert repo.get_subtasks(task.id) == []

    def test_get_subtasks_direct_children_only(self, repo):
        grandparent = make_task(title="grandparent")
        repo.add(grandparent)
        parent = repo.add_subtask(grandparent.id, "parent", "desc")
        repo.add_subtask(parent.id, "child", "desc")
        # grandparent should only see parent, not grandchild
        assert len(repo.get_subtasks(grandparent.id)) == 1

    def test_get_blocked_by(self, repo):
        blocker = make_task(title="blocker")
        blocked = make_task(title="blocked")
        repo.add(blocker)
        repo.add(blocked)
        repo.add_dependency(blocker.id, blocked.id)
        result = repo.get_blocked_by(blocked.id)
        assert len(result) == 1
        assert result[0].id == blocker.id

    def test_get_blocking(self, repo):
        blocker = make_task(title="blocker")
        blocked = make_task(title="blocked")
        repo.add(blocker)
        repo.add(blocked)
        repo.add_dependency(blocker.id, blocked.id)
        result = repo.get_blocking(blocker.id)
        assert len(result) == 1
        assert result[0].id == blocked.id

    def test_get_blocked_by_empty(self, repo):
        task = make_task()
        repo.add(task)
        assert repo.get_blocked_by(task.id) == []

    def test_get_blocking_empty(self, repo):
        task = make_task()
        repo.add(task)
        assert repo.get_blocking(task.id) == []


# ---------------------------------------------------------------------------
# add_dependency / remove_dependency
# ---------------------------------------------------------------------------

class TestDependencyMutations:
    def test_add_dependency_creates_edge(self, repo):
        t1 = make_task(title="a")
        t2 = make_task(title="b")
        repo.add(t1)
        repo.add(t2)
        repo.add_dependency(t1.id, t2.id)
        assert repo.has_blockers(t2.id) is True

    def test_add_dependency_idempotent(self, repo):
        t1 = make_task()
        t2 = make_task()
        repo.add(t1)
        repo.add(t2)
        repo.add_dependency(t1.id, t2.id)
        repo.add_dependency(t1.id, t2.id)
        assert len(repo.get_blocked_by(t2.id)) == 1

    def test_remove_dependency_removes_edge(self, repo):
        t1 = make_task()
        t2 = make_task()
        repo.add(t1)
        repo.add(t2)
        repo.add_dependency(t1.id, t2.id)
        repo.remove_dependency(t1.id, t2.id)
        assert repo.has_blockers(t2.id) is False

    def test_remove_dependency_noop_for_nonexistent(self, repo):
        t1 = make_task()
        t2 = make_task()
        repo.add(t1)
        repo.add(t2)
        repo.remove_dependency(t1.id, t2.id)  # no-op, should not raise

    def test_add_dependency_unknown_task_raises(self, repo):
        task = make_task()
        repo.add(task)
        with pytest.raises(KeyError):
            repo.add_dependency("nonexistent", task.id)
        with pytest.raises(KeyError):
            repo.add_dependency(task.id, "nonexistent")


# ---------------------------------------------------------------------------
# Named state transitions
# ---------------------------------------------------------------------------

class TestMarkRunning:
    def test_sets_running_status(self, repo):
        task = make_task()
        repo.add(task)
        repo.mark_running(task.id)
        assert repo.get(task.id).status == TaskStatus.RUNNING

    def test_sets_time_slice_started(self, repo):
        task = make_task()
        repo.add(task)
        before = time.monotonic()
        repo.mark_running(task.id)
        after = time.monotonic()
        ts = repo.get(task.id).time_slice_started
        assert ts is not None
        assert before <= ts <= after

    def test_sets_started_at_on_first_run(self, repo):
        task = make_task()
        repo.add(task)
        assert task.started_at is None
        repo.mark_running(task.id)
        assert repo.get(task.id).started_at is not None

    def test_does_not_overwrite_started_at(self, repo):
        task = make_task()
        task.started_at = "2026-01-01T00:00:00+00:00"
        repo.add(task)
        repo.mark_running(task.id)
        assert repo.get(task.id).started_at == "2026-01-01T00:00:00+00:00"

    def test_unknown_id_raises(self, repo):
        with pytest.raises(KeyError):
            repo.mark_running("nonexistent")


class TestMarkReady:
    def test_sets_ready_status(self, repo):
        task = make_task(status=TaskStatus.RUNNING)
        repo.add(task)
        repo.mark_ready(task.id)
        assert repo.get(task.id).status == TaskStatus.READY

    def test_clears_time_slice_started(self, repo):
        task = make_task()
        repo.add(task)
        repo.mark_running(task.id)
        repo.mark_ready(task.id)
        assert repo.get(task.id).time_slice_started is None

    def test_unknown_id_raises(self, repo):
        with pytest.raises(KeyError):
            repo.mark_ready("nonexistent")


class TestMarkComplete:
    def test_sets_complete_status(self, repo):
        task = make_task()
        repo.add(task)
        repo.mark_complete(task.id)
        assert repo.get(task.id).status == TaskStatus.COMPLETE

    def test_sets_completed_at(self, repo):
        task = make_task()
        repo.add(task)
        repo.mark_complete(task.id)
        assert repo.get(task.id).completed_at is not None

    def test_unblocks_dependent_when_last_blocker(self, repo):
        blocker = make_task(title="blocker")
        blocked = make_task(
            title="blocked", status=TaskStatus.BLOCKED_BY_TASK
        )
        repo.add(blocker)
        repo.add(blocked)
        repo.add_dependency(blocker.id, blocked.id)
        repo.mark_complete(blocker.id)
        assert repo.get(blocked.id).status == TaskStatus.READY

    def test_does_not_unblock_when_other_blockers_remain(self, repo):
        b1 = make_task(title="blocker1")
        b2 = make_task(title="blocker2")
        blocked = make_task(
            title="blocked", status=TaskStatus.BLOCKED_BY_TASK
        )
        repo.add(b1)
        repo.add(b2)
        repo.add(blocked)
        repo.add_dependency(b1.id, blocked.id)
        repo.add_dependency(b2.id, blocked.id)
        repo.mark_complete(b1.id)
        assert repo.get(blocked.id).status == TaskStatus.BLOCKED_BY_TASK

    def test_removes_dependency_edges(self, repo):
        blocker = make_task()
        blocked = make_task(status=TaskStatus.BLOCKED_BY_TASK)
        repo.add(blocker)
        repo.add(blocked)
        repo.add_dependency(blocker.id, blocked.id)
        repo.mark_complete(blocker.id)
        assert repo.get_blocked_by(blocked.id) == []

    def test_unknown_id_raises(self, repo):
        with pytest.raises(KeyError):
            repo.mark_complete("nonexistent")


class TestMarkBlockedByHuman:
    def test_sets_blocked_status(self, repo):
        task = make_task()
        repo.add(task)
        repo.mark_blocked_by_human(task.id, "needs input")
        assert repo.get(task.id).status == TaskStatus.BLOCKED_BY_HUMAN

    def test_appends_reason_to_notes(self, repo):
        task = make_task()
        repo.add(task)
        repo.mark_blocked_by_human(task.id, "needs input")
        assert "[BLOCKED] needs input" in repo.get(task.id).notes

    def test_appends_to_existing_notes(self, repo):
        task = make_task()
        task.notes = "existing note"
        repo.add(task)
        repo.mark_blocked_by_human(task.id, "second block")
        notes = repo.get(task.id).notes
        assert "existing note" in notes
        assert "[BLOCKED] second block" in notes

    def test_empty_reason_leaves_notes_unchanged(self, repo):
        task = make_task()
        task.notes = "original"
        repo.add(task)
        repo.mark_blocked_by_human(task.id)
        assert repo.get(task.id).notes == "original"

    def test_unknown_id_raises(self, repo):
        with pytest.raises(KeyError):
            repo.mark_blocked_by_human("nonexistent")


class TestMarkCancelled:
    def test_sets_cancelled_status(self, repo):
        task = make_task()
        repo.add(task)
        repo.mark_cancelled(task.id)
        assert repo.get(task.id).status == TaskStatus.CANCELLED

    def test_sets_completed_at(self, repo):
        task = make_task()
        repo.add(task)
        repo.mark_cancelled(task.id)
        assert repo.get(task.id).completed_at is not None

    def test_unknown_id_raises(self, repo):
        with pytest.raises(KeyError):
            repo.mark_cancelled("nonexistent")


# ---------------------------------------------------------------------------
# add_subtask
# ---------------------------------------------------------------------------

class TestAddSubtask:
    def test_subtask_has_correct_depth(self, repo):
        parent = make_task(title="parent")
        repo.add(parent)
        subtask = repo.add_subtask(parent.id, "child", "desc")
        assert subtask.depth == 1

    def test_nested_depth(self, repo):
        grandparent = make_task()
        repo.add(grandparent)
        parent = repo.add_subtask(grandparent.id, "parent", "desc")
        child = repo.add_subtask(parent.id, "child", "desc")
        assert child.depth == 2

    def test_inherits_parent_role(self, repo):
        parent = make_task(role=AgentRole.WRITER)
        repo.add(parent)
        subtask = repo.add_subtask(parent.id, "child", "desc")
        assert subtask.role == AgentRole.WRITER

    def test_inherits_parent_repo(self, repo):
        parent = make_task(repo=["special-repo"])
        repo.add(parent)
        subtask = repo.add_subtask(parent.id, "child", "desc")
        assert subtask.repo == ["special-repo"]

    def test_inherits_parent_importance_urgency(self, repo):
        parent = make_task(importance=0.8, urgency=0.9)
        repo.add(parent)
        subtask = repo.add_subtask(parent.id, "child", "desc")
        assert subtask.importance == 0.8
        assert subtask.urgency == 0.9

    def test_explicit_role_override(self, repo):
        parent = make_task(role=AgentRole.CODER)
        repo.add(parent)
        subtask = repo.add_subtask(
            parent.id, "doc child", "desc", role=AgentRole.WRITER
        )
        assert subtask.role == AgentRole.WRITER

    def test_parent_becomes_blocked_by_task(self, repo):
        parent = make_task()
        repo.add(parent)
        repo.add_subtask(parent.id, "child", "desc")
        assert repo.get(parent.id).status == TaskStatus.BLOCKED_BY_TASK

    def test_subtask_blocks_parent(self, repo):
        parent = make_task()
        repo.add(parent)
        subtask = repo.add_subtask(parent.id, "child", "desc")
        assert repo.has_blockers(parent.id) is True
        blockers = repo.get_blocked_by(parent.id)
        assert any(t.id == subtask.id for t in blockers)

    def test_subtask_persisted(self, repo):
        parent = make_task()
        repo.add(parent)
        subtask = repo.add_subtask(parent.id, "child", "desc")
        assert repo.get(subtask.id) is not None

    def test_parent_task_id_set(self, repo):
        parent = make_task()
        repo.add(parent)
        subtask = repo.add_subtask(parent.id, "child", "desc")
        assert subtask.parent_task_id == parent.id

    def test_unknown_parent_raises(self, repo):
        with pytest.raises(KeyError):
            repo.add_subtask("nonexistent", "child", "desc")
            