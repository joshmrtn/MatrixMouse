"""
tests/test_task.py

Tests for matrixmouse.task — Task, TaskStatus, and AgentRole.

Coverage:
    Task:
        - Default field values
        - priority_score: lower == higher priority, aging decreases score
        - priority_score: clamped to [0.0, 1.0]
        - priority_score: importance/urgency weighting
        - to_dict / from_dict roundtrip
        - from_dict: legacy status migration (pending -> ready, active -> ready)
        - from_dict: unknown status defaults to READY with warning
        - from_dict: unknown role defaults to CODER with warning
        - id: 16 hex characters
        - preempt: not persisted to disk
        - last_modified: auto-set on creation, included in serialisation
        - pending_question: default empty, persisted correctly

    TaskStatus:
        - is_terminal for COMPLETE and CANCELLED
        - is_blocked for BLOCKED_BY_TASK and BLOCKED_BY_HUMAN

    Note: TaskQueue has been replaced by TaskRepository.
    Repository persistence tests live in tests/repository/.
"""

import time as time_mod
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from matrixmouse.task import (
    AgentRole,
    Task,
    TaskStatus,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_task(
    title: str = "Test task",
    description: str = "Do the thing carefully.",
    role: AgentRole = AgentRole.CODER,
    repo: list[str] | None = None,
    **kwargs,
) -> Task:
    return Task(
        title=title,
        description=description,
        role=role,
        repo=repo if repo is not None else ["repo"],
        **kwargs,
    )


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
        assert make_task().status == TaskStatus.READY

    def test_default_role_is_coder(self):
        assert make_task().role == AgentRole.CODER

    def test_default_preempt_is_false(self):
        assert make_task().preempt is False

    def test_default_depth_is_zero(self):
        assert make_task().depth == 0

    def test_default_context_messages_is_empty(self):
        assert make_task().context_messages == []

    def test_default_pending_question_is_empty(self):
        assert make_task().pending_question == ""

    def test_default_wip_commit_hash_is_empty(self):
        assert make_task().wip_commit_hash == ""

    def test_default_branch_is_empty(self):
        assert make_task().branch == ""

    def test_default_parent_task_id_is_none(self):
        assert make_task().parent_task_id is None

    def test_default_reviews_task_id_is_none(self):
        assert make_task().reviews_task_id is None


# ---------------------------------------------------------------------------
# Task — priority_score
# ---------------------------------------------------------------------------

class TestPriorityScore:
    def test_high_importance_urgency_gives_low_score(self):
        task = make_task(importance=1.0, urgency=1.0)
        assert task.priority_score() == pytest.approx(0.0, abs=0.01)

    def test_low_importance_urgency_gives_high_score(self):
        task = make_task(importance=0.0, urgency=0.0)
        assert task.priority_score() == pytest.approx(1.0, abs=0.05)

    def test_score_clamped_to_zero_minimum(self):
        task = make_task(importance=1.0, urgency=1.0)
        assert task.priority_score(aging_rate=10.0, max_aging_bonus=100.0) >= 0.0

    def test_score_does_not_exceed_one(self):
        assert make_task(importance=0.0, urgency=0.0).priority_score() <= 1.0

    def test_aging_decreases_score(self):
        task = make_task(importance=0.5, urgency=0.5)
        assert task.priority_score(aging_rate=0.1) <= task.priority_score(aging_rate=0.0)

    def test_importance_weight_respected(self):
        assert (
            make_task(importance=1.0, urgency=0.0).priority_score()
            < make_task(importance=0.0, urgency=1.0).priority_score()
        )

    def test_custom_weights_respected(self):
        task = make_task(importance=1.0, urgency=0.0)
        assert (
            task.priority_score(importance_weight=0.6, urgency_weight=0.4)
            < task.priority_score(importance_weight=0.4, urgency_weight=0.6)
        )


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
        assert Task.from_dict(task.to_dict()).context_messages == [
            {"role": "user", "content": "hello"}
        ]

    def test_roundtrip_preserves_depth(self):
        assert Task.from_dict(make_task(depth=3).to_dict()).depth == 3

    def test_roundtrip_preserves_importance_urgency(self):
        task = make_task(importance=0.8, urgency=0.3)
        restored = Task.from_dict(task.to_dict())
        assert restored.importance == 0.8
        assert restored.urgency == 0.3

    def test_roundtrip_preserves_pending_question(self):
        task = make_task()
        task.pending_question = "Which approach?"
        assert Task.from_dict(task.to_dict()).pending_question == "Which approach?"

    def test_roundtrip_preserves_wip_commit_hash(self):
        task = make_task()
        task.wip_commit_hash = "abc123"
        assert Task.from_dict(task.to_dict()).wip_commit_hash == "abc123"

    def test_preempt_persisted_in_to_dict(self):
        task = make_task()
        task.preempt = True
        assert "preempt" in task.to_dict()
        assert task.to_dict()["preempt"] is True

    def test_preempt_roundtrips_through_dict(self):
        task = make_task()
        task.preempt = True
        restored = Task.from_dict(task.to_dict())
        assert restored.preempt is True

    def test_preempt_defaults_false_when_absent_in_dict(self):
        task = make_task()
        data = task.to_dict()
        data.pop("preempt", None)
        restored = Task.from_dict(data)
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
        assert len(Task.from_dict(data).id) == 16

    def test_last_modified_falls_back_to_created_at_on_load(self):
        task = make_task()
        data = task.to_dict()
        del data["last_modified"]
        assert Task.from_dict(data).last_modified == task.created_at

    def test_pending_question_defaults_empty_on_missing_key(self):
        data = make_task().to_dict()
        del data["pending_question"]
        assert Task.from_dict(data).pending_question == ""


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
# Task — last_modified
# ---------------------------------------------------------------------------

class TestLastModified:
    def test_set_on_creation(self):
        task = make_task()
        assert task.last_modified is not None
        assert isinstance(task.last_modified, str)

    def test_is_valid_iso(self):
        dt = datetime.fromisoformat(make_task().last_modified)
        assert dt is not None

    def test_persisted_in_to_dict(self):
        assert "last_modified" in make_task().to_dict()

    def test_restored_from_dict(self):
        task = make_task()
        assert Task.from_dict(task.to_dict()).last_modified == task.last_modified