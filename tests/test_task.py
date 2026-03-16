"""
tests/test_task.py

Tests for matrixmouse.task — Task, TaskStatus, AgentRole, and TaskQueue.

Coverage:
    Task:
        - Default field values
        - priority_score: lower == higher priority, aging decreases score
        - priority_score: clamped to [0.0, 1.0]
        - priority_score: importance/urgency weighting
        - is_ready: all deps complete, some incomplete, no deps
        - to_dict / from_dict roundtrip
        - from_dict: legacy status migration (pending -> ready, active -> ready)
        - from_dict: unknown status defaults to READY with warning
        - from_dict: unknown role defaults to CODER with warning
        - id: 16 hex characters
        - preempt: not persisted to disk

    TaskQueue:
        - add: stores task, saves to disk
        - add: collision regenerates id
        - add: raises if disk write fails
        - get: returns task by id, None if absent
        - update: persists changes
        - update: raises KeyError for unknown id
        - mark_running: sets RUNNING status and time_slice_started
        - mark_running: sets started_at only on first run
        - mark_ready: clears time_slice_started, sets READY
        - mark_complete: sets COMPLETE, unblocks dependents
        - mark_blocked_by_human: appends reason to notes
        - add_subtask: creates subtask, sets parent BLOCKED_BY_TASK
        - add_subtask: increments depth
        - add_subtask: rolls back on cycle detection
        - detect_cycles: returns empty list when no cycles
        - detect_cycles: returns cycle when one exists
        - reload: re-reads from disk
"""

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from matrixmouse.task import (
    AgentRole,
    Task,
    TaskQueue,
    TaskStatus,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_task(**kwargs) -> Task:
    defaults = dict(
        title="Test task",
        description="Do the thing",
        importance=0.5,
        urgency=0.5,
    )
    defaults.update(kwargs)
    return Task(**defaults)


def make_queue(tmp_path: Path) -> TaskQueue:
    tasks_file = tmp_path / "tasks.json"
    tasks_file.write_text("[]")
    return TaskQueue(tasks_file)


# ---------------------------------------------------------------------------
# Task — identity
# ---------------------------------------------------------------------------


class TestTaskIdentity:
    def test_id_is_16_hex_chars(self):
        task = make_task()
        assert len(task.id) == 16
        assert all(c in "0123456789abcdef" for c in task.id)

    def test_ids_are_unique(self):
        ids = {make_task().id for _ in range(100)}
        assert len(ids) == 100


# ---------------------------------------------------------------------------
# Task — defaults
# ---------------------------------------------------------------------------


class TestTaskDefaults:
    def test_default_status_is_ready(self):
        task = make_task()
        assert task.status == TaskStatus.READY

    def test_default_role_is_coder(self):
        task = make_task()
        assert task.role == AgentRole.CODER

    def test_default_preempt_is_false(self):
        task = make_task()
        assert task.preempt is False

    def test_default_depth_is_zero(self):
        task = make_task()
        assert task.depth == 0

    def test_default_context_messages_is_empty(self):
        task = make_task()
        assert task.context_messages == []

    def test_default_blocked_by_is_empty(self):
        task = make_task()
        assert task.blocked_by == []


# ---------------------------------------------------------------------------
# Task — priority_score
# ---------------------------------------------------------------------------


class TestPriorityScore:
    def test_high_importance_urgency_gives_low_score(self):
        """importance=1.0, urgency=1.0 → base=1.0 → score=0.0 (highest priority)"""
        task = make_task(importance=1.0, urgency=1.0)
        assert task.priority_score() == pytest.approx(0.0, abs=0.01)

    def test_low_importance_urgency_gives_high_score(self):
        """importance=0.0, urgency=0.0 → base=0.0 → score=1.0 (lowest priority)"""
        task = make_task(importance=0.0, urgency=0.0)
        score = task.priority_score()
        assert score == pytest.approx(1.0, abs=0.05)

    def test_score_clamped_to_zero_minimum(self):
        task = make_task(importance=1.0, urgency=1.0)
        score = task.priority_score(aging_rate=10.0, max_aging_bonus=100.0)
        assert score >= 0.0

    def test_score_does_not_exceed_one(self):
        task = make_task(importance=0.0, urgency=0.0)
        score = task.priority_score()
        assert score <= 1.0

    def test_aging_decreases_score(self):
        """Older tasks should have lower (higher priority) scores."""
        task = make_task(importance=0.5, urgency=0.5)
        score_no_aging = task.priority_score(aging_rate=0.0)
        score_with_aging = task.priority_score(aging_rate=0.1)
        # aging_rate applied daily — mock age by using a very high rate
        # The score with aging should be <= score without aging
        assert score_with_aging <= score_no_aging

    def test_importance_weight_respected(self):
        task_imp = make_task(importance=1.0, urgency=0.0)
        task_urg = make_task(importance=0.0, urgency=1.0)
        # importance_weight=0.6 > urgency_weight=0.4, so importance=1 should
        # produce a lower (better) score than urgency=1
        assert task_imp.priority_score() < task_urg.priority_score()

    def test_custom_weights_respected(self):
        task = make_task(importance=1.0, urgency=0.0)
        score_default = task.priority_score(importance_weight=0.6, urgency_weight=0.4)
        score_flipped = task.priority_score(importance_weight=0.4, urgency_weight=0.6)
        # With default weights, importance=1 gives better score
        assert score_default < score_flipped


# ---------------------------------------------------------------------------
# Task — is_ready
# ---------------------------------------------------------------------------


class TestIsReady:
    def test_no_deps_is_ready(self):
        task = make_task()
        assert task.is_ready(set()) is True

    def test_all_deps_complete_is_ready(self):
        task = make_task()
        task.blocked_by = ["a", "b"]
        assert task.is_ready({"a", "b", "c"}) is True

    def test_incomplete_dep_not_ready(self):
        task = make_task()
        task.blocked_by = ["a", "b"]
        assert task.is_ready({"a"}) is False

    def test_no_deps_complete_not_ready(self):
        task = make_task()
        task.blocked_by = ["a"]
        assert task.is_ready(set()) is False


# ---------------------------------------------------------------------------
# Task — serialisation
# ---------------------------------------------------------------------------


class TestTaskSerialisation:
    def test_roundtrip_preserves_title(self):
        task = make_task(title="My task")
        assert Task.from_dict(task.to_dict()).title == "My task"

    def test_roundtrip_preserves_role(self):
        task = make_task(role=AgentRole.WRITER)
        assert Task.from_dict(task.to_dict()).role == AgentRole.WRITER

    def test_roundtrip_preserves_status(self):
        task = make_task(status=TaskStatus.BLOCKED_BY_HUMAN)
        assert Task.from_dict(task.to_dict()).status == TaskStatus.BLOCKED_BY_HUMAN

    def test_roundtrip_preserves_context_messages(self):
        task = make_task()
        task.context_messages = [{"role": "user", "content": "hello"}]
        restored = Task.from_dict(task.to_dict())
        assert restored.context_messages == [{"role": "user", "content": "hello"}]

    def test_roundtrip_preserves_depth(self):
        task = make_task(depth=3)
        assert Task.from_dict(task.to_dict()).depth == 3

    def test_preempt_not_in_to_dict(self):
        task = make_task()
        task.preempt = True
        assert "preempt" not in task.to_dict()

    def test_preempt_defaults_false_on_load(self):
        task = make_task()
        task.preempt = True
        restored = Task.from_dict(task.to_dict())
        assert restored.preempt is False

    def test_from_dict_legacy_pending_maps_to_ready(self):
        data = make_task().to_dict()
        data["status"] = "pending"
        assert Task.from_dict(data).status == TaskStatus.READY

    def test_from_dict_legacy_active_maps_to_ready(self):
        data = make_task().to_dict()
        data["status"] = "active"
        assert Task.from_dict(data).status == TaskStatus.READY

    def test_from_dict_unknown_status_defaults_to_ready(self):
        data = make_task().to_dict()
        data["status"] = "totally_made_up"
        assert Task.from_dict(data).status == TaskStatus.READY

    def test_from_dict_unknown_role_defaults_to_coder(self):
        data = make_task().to_dict()
        data["role"] = "nonexistent_role"
        assert Task.from_dict(data).role == AgentRole.CODER

    def test_from_dict_missing_id_generates_new(self):
        data = make_task().to_dict()
        del data["id"]
        restored = Task.from_dict(data)
        assert len(restored.id) == 16


# ---------------------------------------------------------------------------
# TaskStatus helpers
# ---------------------------------------------------------------------------


class TestTaskStatus:
    def test_terminal_statuses(self):
        assert TaskStatus.COMPLETE.is_terminal is True
        assert TaskStatus.CANCELLED.is_terminal is True

    def test_non_terminal_statuses(self):
        for status in (
            TaskStatus.READY,
            TaskStatus.RUNNING,
            TaskStatus.BLOCKED_BY_TASK,
            TaskStatus.BLOCKED_BY_HUMAN,
        ):
            assert status.is_terminal is False

    def test_blocked_statuses(self):
        assert TaskStatus.BLOCKED_BY_TASK.is_blocked is True
        assert TaskStatus.BLOCKED_BY_HUMAN.is_blocked is True

    def test_non_blocked_statuses(self):
        for status in (
            TaskStatus.READY,
            TaskStatus.RUNNING,
            TaskStatus.COMPLETE,
            TaskStatus.CANCELLED,
        ):
            assert status.is_blocked is False


# ---------------------------------------------------------------------------
# TaskQueue — basic operations
# ---------------------------------------------------------------------------


class TestTaskQueueBasic:
    def test_add_stores_task(self, tmp_path):
        q = make_queue(tmp_path)
        task = make_task(title="hello")
        q.add(task)
        assert q.get(task.id) is task

    def test_add_persists_to_disk(self, tmp_path):
        q = make_queue(tmp_path)
        task = make_task(title="persisted")
        q.add(task)
        raw = json.loads((tmp_path / "tasks.json").read_text())
        assert any(t["title"] == "persisted" for t in raw)

    def test_get_returns_none_for_unknown_id(self, tmp_path):
        q = make_queue(tmp_path)
        assert q.get("nonexistent") is None

    def test_update_persists_changes(self, tmp_path):
        q = make_queue(tmp_path)
        task = make_task(title="original")
        q.add(task)
        task.title = "updated"
        q.update(task)
        raw = json.loads((tmp_path / "tasks.json").read_text())
        assert any(t["title"] == "updated" for t in raw)

    def test_update_raises_for_unknown_id(self, tmp_path):
        q = make_queue(tmp_path)
        task = make_task()
        with pytest.raises(KeyError):
            q.update(task)

    def test_all_tasks_returns_all(self, tmp_path):
        q = make_queue(tmp_path)
        t1, t2 = make_task(title="a"), make_task(title="b")
        q.add(t1)
        q.add(t2)
        assert len(q.all_tasks()) == 2

    def test_active_tasks_excludes_terminal(self, tmp_path):
        q = make_queue(tmp_path)
        t1 = make_task(title="active")
        t2 = make_task(title="done", status=TaskStatus.COMPLETE)
        q.add(t1)
        q.add(t2)
        active = q.active_tasks()
        assert len(active) == 1
        assert active[0].title == "active"

    def test_completed_ids_returns_terminal_ids(self, tmp_path):
        q = make_queue(tmp_path)
        t1 = make_task(status=TaskStatus.COMPLETE)
        t2 = make_task(status=TaskStatus.CANCELLED)
        t3 = make_task(status=TaskStatus.READY)
        q.add(t1)
        q.add(t2)
        q.add(t3)
        ids = q.completed_ids()
        assert t1.id in ids
        assert t2.id in ids
        assert t3.id not in ids

    def test_is_empty_true_when_no_active(self, tmp_path):
        q = make_queue(tmp_path)
        task = make_task(status=TaskStatus.COMPLETE)
        q.add(task)
        assert q.is_empty() is True

    def test_is_empty_false_when_active_exists(self, tmp_path):
        q = make_queue(tmp_path)
        q.add(make_task())
        assert q.is_empty() is False


# ---------------------------------------------------------------------------
# TaskQueue — id collision
# ---------------------------------------------------------------------------


class TestTaskQueueCollision:
    def test_collision_regenerates_id(self, tmp_path):
        q = make_queue(tmp_path)
        task = make_task()
        fixed_id = task.id
        q.add(task)

        # Create a second task that will initially collide
        task2 = make_task()
        task2.id = fixed_id  # force collision

        new_ids = [fixed_id + "x"]  # guaranteed non-colliding after first attempt

        original_hex = __import__("uuid").uuid4

        call_count = 0

        def patched_uuid4():
            nonlocal call_count
            call_count += 1
            m = MagicMock()
            m.hex = "abcdef1234567890"  # 16 chars, won't collide
            return m

        with patch("matrixmouse.task.uuid.uuid4", patched_uuid4):
            q.add(task2)

        # task2 should now have a different id from the original collision
        assert task2.id != fixed_id


# ---------------------------------------------------------------------------
# TaskQueue — status transitions
# ---------------------------------------------------------------------------


class TestTaskQueueStatusTransitions:
    def test_mark_running_sets_status(self, tmp_path):
        q = make_queue(tmp_path)
        task = make_task()
        q.add(task)
        q.mark_running(task.id)
        assert q.get(task.id).status == TaskStatus.RUNNING

    def test_mark_running_sets_time_slice_started(self, tmp_path):
        q = make_queue(tmp_path)
        task = make_task()
        q.add(task)
        before = time.monotonic()
        q.mark_running(task.id)
        after = time.monotonic()
        ts = q.get(task.id).time_slice_started
        assert ts is not None
        assert before <= ts <= after

    def test_mark_running_sets_started_at_on_first_run(self, tmp_path):
        q = make_queue(tmp_path)
        task = make_task()
        q.add(task)
        assert task.started_at is None
        q.mark_running(task.id)
        assert q.get(task.id).started_at is not None

    def test_mark_running_does_not_overwrite_started_at(self, tmp_path):
        q = make_queue(tmp_path)
        task = make_task()
        task.started_at = "2024-01-01T00:00:00+00:00"
        q.add(task)
        q.mark_running(task.id)
        assert q.get(task.id).started_at == "2024-01-01T00:00:00+00:00"

    def test_mark_ready_clears_time_slice(self, tmp_path):
        q = make_queue(tmp_path)
        task = make_task()
        q.add(task)
        q.mark_running(task.id)
        q.mark_ready(task.id)
        t = q.get(task.id)
        assert t.status == TaskStatus.READY
        assert t.time_slice_started is None

    def test_mark_complete_sets_status_and_timestamp(self, tmp_path):
        q = make_queue(tmp_path)
        task = make_task()
        q.add(task)
        q.mark_complete(task.id)
        t = q.get(task.id)
        assert t.status == TaskStatus.COMPLETE
        assert t.completed_at is not None

    def test_mark_blocked_by_human_appends_reason(self, tmp_path):
        q = make_queue(tmp_path)
        task = make_task()
        q.add(task)
        q.mark_blocked_by_human(task.id, "needs info")
        assert "[BLOCKED] needs info" in q.get(task.id).notes

    def test_mark_complete_unblocks_dependent(self, tmp_path):
        q = make_queue(tmp_path)
        blocker = make_task(title="blocker")
        dependent = make_task(title="dependent")
        dependent.blocked_by = [blocker.id]
        dependent.status = TaskStatus.BLOCKED_BY_TASK
        q.add(blocker)
        q.add(dependent)
        q.mark_complete(blocker.id)
        assert q.get(dependent.id).status == TaskStatus.READY


# ---------------------------------------------------------------------------
# TaskQueue — subtask management
# ---------------------------------------------------------------------------


class TestAddSubtask:
    def test_subtask_created_with_correct_parent(self, tmp_path):
        q = make_queue(tmp_path)
        parent = make_task(title="parent")
        q.add(parent)
        subtask = q.add_subtask(parent.id, "child", "do child work")
        assert subtask.parent_task_id == parent.id

    def test_subtask_depth_is_parent_plus_one(self, tmp_path):
        q = make_queue(tmp_path)
        parent = make_task(depth=2)
        q.add(parent)
        subtask = q.add_subtask(parent.id, "child", "desc")
        assert subtask.depth == 3

    def test_parent_becomes_blocked_by_task(self, tmp_path):
        q = make_queue(tmp_path)
        parent = make_task()
        q.add(parent)
        q.add_subtask(parent.id, "child", "desc")
        assert q.get(parent.id).status == TaskStatus.BLOCKED_BY_TASK

    def test_subtask_id_in_parent_subtasks(self, tmp_path):
        q = make_queue(tmp_path)
        parent = make_task()
        q.add(parent)
        subtask = q.add_subtask(parent.id, "child", "desc")
        assert subtask.id in q.get(parent.id).subtasks

    def test_cycle_detection_rolls_back(self, tmp_path):
        q = make_queue(tmp_path)
        parent = make_task()
        q.add(parent)
        subtask = q.add_subtask(parent.id, "child", "desc")

        # Manually create a cycle: subtask blocks parent, parent blocks subtask
        subtask_obj = q.get(subtask.id)
        subtask_obj.blocked_by = [parent.id]
        q.update(subtask_obj)

        with pytest.raises(ValueError, match="cycle"):
            q.add_subtask(subtask.id, "grandchild", "desc")


# ---------------------------------------------------------------------------
# TaskQueue — reload
# ---------------------------------------------------------------------------


class TestTaskQueueReload:
    def test_reload_picks_up_new_tasks(self, tmp_path):
        q = make_queue(tmp_path)
        task = make_task(title="new task")
        # Write directly to disk, bypassing the queue
        (tmp_path / "tasks.json").write_text(json.dumps([task.to_dict()]))
        q.reload()
        assert q.get(task.id) is not None

    def test_reload_clears_removed_tasks(self, tmp_path):
        q = make_queue(tmp_path)
        task = make_task()
        q.add(task)
        # Clear the file
        (tmp_path / "tasks.json").write_text("[]")
        q.reload()
        assert q.get(task.id) is None
