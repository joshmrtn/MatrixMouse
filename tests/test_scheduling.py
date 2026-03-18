"""
tests/test_scheduling.py

Tests for matrixmouse.scheduling — Scheduler and SchedulingDecision.

Coverage:
    Queue level assignment:
        - Score below p1_threshold → P1
        - Score between thresholds → P2
        - Score at or above p2_threshold → P3

    Task selection:
        - Selects highest priority (lowest score) ready task
        - Skips BLOCKED_BY_TASK and BLOCKED_BY_HUMAN tasks
        - Skips RUNNING tasks (not READY)
        - Returns task=None when queue is empty
        - Returns task=None when all tasks are blocked
        - P1 tasks selected before P2, P2 before P3

    Preemption:
        - Preempting task jumps queue regardless of score
        - Non-preempting tasks unaffected when no preempt flag set
        - SchedulingDecision.preempted is True when preemption occurs

    Time slice:
        - time_slice_expired returns False when slice not started
        - time_slice_expired returns False within slice
        - time_slice_expired returns True when slice exceeded
        - Slice length respects config per level

    Adaptive heuristic:
        - record_switch_time is no-op when adaptive=False
        - Switch overhead > max_pct increases slice
        - Switch overhead < min_pct decreases slice
        - Slice never decreases below floor

    report_blocked:
        - Returns "No blocked tasks." when none blocked
        - Lists BLOCKED_BY_HUMAN tasks
        - Lists BLOCKED_BY_TASK tasks with their blockers

    Stale clarification detection:
        - Skips detection if callback not registered
        - Callback not called when no pending question
        - Callback not called for non-blocked task
        - Callback called only when past the timeout period
        - Callback receives Task info (id, question text, blocked since)
        - Callback called exactly once per each stale task
        - Callback exception should not propogate
        - Stale detection fires during scheduler.next()
        - Timeout respected from config
"""

import time
from unittest.mock import MagicMock, patch

import pytest

from matrixmouse.task import AgentRole, Task, TaskQueue, TaskStatus
from matrixmouse.scheduling import Scheduler, P1, P2, P3


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_config(**kwargs) -> MagicMock:
    """Mock config with scheduler defaults."""
    cfg = MagicMock()
    cfg.scheduler_p1_threshold = kwargs.get("p1_threshold", 0.35)
    cfg.scheduler_p2_threshold = kwargs.get("p2_threshold", 0.65)
    cfg.scheduler_p1_slice_minutes = kwargs.get("p1_slice", 120.0)
    cfg.scheduler_p2_slice_minutes = kwargs.get("p2_slice", 90.0)
    cfg.scheduler_p3_slice_minutes = kwargs.get("p3_slice", 60.0)
    cfg.scheduler_adaptive = kwargs.get("adaptive", False)
    cfg.scheduler_adaptive_step_minutes = kwargs.get("step", 10.0)
    cfg.scheduler_adaptive_min_pct = kwargs.get("min_pct", 0.05)
    cfg.scheduler_adaptive_max_pct = kwargs.get("max_pct", 0.15)
    cfg.scheduler_adaptive_min_slice_minutes = kwargs.get("floor", 30.0)
    cfg.priority_aging_rate = kwargs.get("aging_rate", 0.0)
    cfg.priority_max_aging_bonus = kwargs.get("max_aging", 0.0)
    cfg.priority_importance_weight = kwargs.get("imp_weight", 0.6)
    cfg.priority_urgency_weight = kwargs.get("urg_weight", 0.4)
    return cfg


def make_task(
    importance=0.5, urgency=0.5, status=TaskStatus.READY, preempt=False, **kwargs
) -> Task:
    task = Task(
        title=kwargs.get("title", "test"),
        importance=importance,
        urgency=urgency,
        status=status,
    )
    task.preempt = preempt
    return task


def make_queue_with_tasks(tasks: list[Task]) -> MagicMock:
    """Mock TaskQueue returning the given task list."""
    q = MagicMock()
    q.active_tasks.return_value = list(tasks)
    q.completed_ids.return_value = set()
    return q


# ---------------------------------------------------------------------------
# Queue level assignment
# ---------------------------------------------------------------------------


class TestQueueLevel:
    def test_high_priority_task_is_p1(self):
        s = Scheduler(make_config())
        # importance=1.0, urgency=1.0 → score ≈ 0.0 → P1
        task = make_task(importance=1.0, urgency=1.0)
        assert s._queue_level(task) == P1

    def test_medium_priority_task_is_p2(self):
        s = Scheduler(make_config())
        # importance=0.5, urgency=0.5 → score ≈ 0.5 → P2
        task = make_task(importance=0.5, urgency=0.5)
        assert s._queue_level(task) == P2

    def test_low_priority_task_is_p3(self):
        s = Scheduler(make_config())
        # importance=0.0, urgency=0.0 → score ≈ 1.0 → P3
        task = make_task(importance=0.0, urgency=0.0)
        assert s._queue_level(task) == P3

    def test_score_at_p1_threshold_is_p2(self):
        s = Scheduler(make_config(p1_threshold=0.35))
        # score exactly at threshold → P2 (not P1, threshold is exclusive)
        task = MagicMock()
        task.priority_score.return_value = 0.35
        assert s._queue_level(task) == P2

    def test_score_just_below_p1_threshold_is_p1(self):
        s = Scheduler(make_config(p1_threshold=0.35))
        task = MagicMock()
        task.priority_score.return_value = 0.34
        assert s._queue_level(task) == P1


# ---------------------------------------------------------------------------
# Task selection
# ---------------------------------------------------------------------------


class TestTaskSelection:
    def test_selects_highest_priority_ready_task(self):
        s = Scheduler(make_config())
        high = make_task(importance=1.0, urgency=1.0, title="high")
        low = make_task(importance=0.1, urgency=0.1, title="low")
        q = make_queue_with_tasks([low, high])
        decision = s.next(q)
        decision_task = decision.task
        assert decision_task is not None
        assert decision_task.title == "high"

    def test_skips_blocked_by_task(self):
        s = Scheduler(make_config())
        blocked = make_task(
            importance=1.0, urgency=1.0, status=TaskStatus.BLOCKED_BY_TASK
        )
        ready = make_task(importance=0.5, urgency=0.5)
        q = make_queue_with_tasks([blocked, ready])
        decision = s.next(q)
        assert decision.task is ready

    def test_skips_blocked_by_human(self):
        s = Scheduler(make_config())
        blocked = make_task(
            importance=1.0, urgency=1.0, status=TaskStatus.BLOCKED_BY_HUMAN
        )
        ready = make_task(importance=0.5, urgency=0.5)
        q = make_queue_with_tasks([blocked, ready])
        decision = s.next(q)
        assert decision.task is ready

    def test_skips_running_task(self):
        s = Scheduler(make_config())
        running = make_task(importance=1.0, urgency=1.0, status=TaskStatus.RUNNING)
        ready = make_task(importance=0.5, urgency=0.5)
        q = make_queue_with_tasks([running, ready])
        # running task has no time_slice_started so slice check skipped
        decision = s.next(q)
        assert decision.task is ready

    def test_returns_none_when_queue_empty(self):
        s = Scheduler(make_config())
        q = make_queue_with_tasks([])
        decision = s.next(q)
        assert decision.task is None

    def test_returns_none_when_all_blocked(self):
        s = Scheduler(make_config())
        tasks = [
            make_task(status=TaskStatus.BLOCKED_BY_TASK),
            make_task(status=TaskStatus.BLOCKED_BY_HUMAN),
        ]
        q = make_queue_with_tasks(tasks)
        decision = s.next(q)
        assert decision.task is None

    def test_p1_selected_before_p2(self):
        s = Scheduler(make_config())
        p1_task = make_task(importance=1.0, urgency=1.0, title="p1")  # score ≈ 0.0
        p2_task = make_task(importance=0.5, urgency=0.5, title="p2")  # score ≈ 0.5
        q = make_queue_with_tasks([p2_task, p1_task])
        decision = s.next(q)
        decision_task = decision.task
        assert decision_task is not None
        assert decision_task.title == "p1"
        assert decision.queue_level == P1

    def test_p2_selected_before_p3(self):
        s = Scheduler(make_config())
        p2_task = make_task(importance=0.5, urgency=0.5, title="p2")  # score ≈ 0.5
        p3_task = make_task(importance=0.0, urgency=0.0, title="p3")  # score ≈ 1.0
        q = make_queue_with_tasks([p3_task, p2_task])
        decision = s.next(q)
        decision_task = decision.task
        assert decision_task is not None
        assert decision_task.title == "p2"
        assert decision.queue_level == P2

    def test_decision_includes_candidate_count(self):
        s = Scheduler(make_config())
        tasks = [make_task() for _ in range(3)]
        q = make_queue_with_tasks(tasks)
        decision = s.next(q)
        assert decision.candidates_considered == 3

    def test_decision_includes_total_active(self):
        s = Scheduler(make_config())
        tasks = [make_task() for _ in range(2)]
        q = make_queue_with_tasks(tasks)
        decision = s.next(q)
        assert decision.total_active == 2


# ---------------------------------------------------------------------------
# Preemption
# ---------------------------------------------------------------------------


class TestPreemption:
    def test_preempting_task_jumps_queue(self):
        s = Scheduler(make_config())
        normal = make_task(importance=1.0, urgency=1.0, title="normal")
        preempt = make_task(importance=0.0, urgency=0.0, title="preempt", preempt=True)
        q = make_queue_with_tasks([normal, preempt])
        decision = s.next(q)
        decision_task = decision.task
        assert decision_task is not None
        assert decision_task.title == "preempt"

    def test_preemption_flag_set_in_decision(self):
        s = Scheduler(make_config())
        preempt = make_task(preempt=True)
        q = make_queue_with_tasks([preempt])
        decision = s.next(q)
        assert decision.preempted is True

    def test_no_preemption_flag_when_normal(self):
        s = Scheduler(make_config())
        task = make_task()
        q = make_queue_with_tasks([task])
        decision = s.next(q)
        assert decision.preempted is False

    def test_non_preempting_tasks_unaffected(self):
        s = Scheduler(make_config())
        t1 = make_task(importance=1.0, urgency=1.0, title="high")
        t2 = make_task(importance=0.5, urgency=0.5, title="medium")
        # Neither has preempt=True
        q = make_queue_with_tasks([t2, t1])
        decision = s.next(q)
        decision_task = decision.task
        assert decision_task is not None
        assert decision_task.title == "high"
        assert decision.preempted is False


# ---------------------------------------------------------------------------
# Time slice
# ---------------------------------------------------------------------------


class TestTimeSlice:
    def test_expired_returns_false_when_not_started(self):
        s = Scheduler(make_config())
        task = make_task()
        task.time_slice_started = None
        assert s.time_slice_expired(task) is False

    def test_expired_returns_false_within_slice(self):
        s = Scheduler(make_config(p1_slice=120.0))
        task = make_task(importance=1.0, urgency=1.0)  # P1
        task.time_slice_started = time.monotonic()  # just started
        assert s.time_slice_expired(task) is False

    def test_expired_returns_true_when_exceeded(self):
        s = Scheduler(make_config(p1_slice=0.0))  # zero-minute slice
        task = make_task(importance=1.0, urgency=1.0)  # P1
        task.time_slice_started = time.monotonic() - 1  # 1 second ago
        assert s.time_slice_expired(task) is True

    def test_slice_length_respects_config_per_level(self):
        s = Scheduler(make_config(p1_slice=60.0, p2_slice=45.0, p3_slice=30.0))
        assert s._slice_minutes(P1) == 60.0
        assert s._slice_minutes(P2) == 45.0
        assert s._slice_minutes(P3) == 30.0


# ---------------------------------------------------------------------------
# Adaptive heuristic
# ---------------------------------------------------------------------------


class TestAdaptiveHeuristic:
    def test_noop_when_adaptive_disabled(self):
        s = Scheduler(make_config(adaptive=False))
        initial = s._switch_ema
        s.record_switch_time(999.0)
        assert s._switch_ema == initial
        assert s._slice_overrides == {}

    def test_high_overhead_increases_slice(self):
        # switch_ema after one call with alpha=0.2:
        # ema = 0.2 * seconds + 0.8 * 30.0
        # Use a very large switch time to push ema clearly above max_pct * slice
        s = Scheduler(
            make_config(adaptive=True, p1_slice=60.0, max_pct=0.15, step=10.0)
        )
        # Force ema to be very high by calling with huge value repeatedly
        for _ in range(50):
            s.record_switch_time(600.0)  # 10 minutes
        assert s._slice_minutes(P1) > 60.0

    def test_low_overhead_decreases_slice(self):
        s = Scheduler(
            make_config(
                adaptive=True, p1_slice=120.0, min_pct=0.05, step=10.0, floor=30.0
            )
        )
        # Force ema to near zero
        for _ in range(50):
            s.record_switch_time(0.001)
        assert s._slice_minutes(P1) < 120.0

    def test_slice_never_below_floor(self):
        s = Scheduler(
            make_config(
                adaptive=True, p1_slice=35.0, min_pct=0.05, step=10.0, floor=30.0
            )
        )
        for _ in range(200):
            s.record_switch_time(0.001)
        assert s._slice_minutes(P1) >= 30.0


# ---------------------------------------------------------------------------
# report_blocked
# ---------------------------------------------------------------------------


class TestReportBlocked:
    def test_no_blocked_tasks_message(self, tmp_path):
        s = Scheduler(make_config())
        tasks_file = tmp_path / "tasks.json"
        tasks_file.write_text("[]")
        q = TaskQueue(tasks_file)
        q.add(make_task())
        assert s.report_blocked(q) == "No blocked tasks."

    def test_lists_blocked_by_human(self, tmp_path):
        s = Scheduler(make_config())
        tasks_file = tmp_path / "tasks.json"
        tasks_file.write_text("[]")
        q = TaskQueue(tasks_file)
        task = make_task(title="waiting for human")
        q.add(task)
        q.mark_blocked_by_human(task.id, "needs decision")
        report = s.report_blocked(q)
        assert "waiting for human" in report
        assert "Blocked by human" in report

    def test_lists_blocked_by_task(self, tmp_path):
        s = Scheduler(make_config())
        tasks_file = tmp_path / "tasks.json"
        tasks_file.write_text("[]")
        q = TaskQueue(tasks_file)
        blocker = make_task(title="blocker")
        blocked = make_task(title="blocked task")
        blocked.status = TaskStatus.BLOCKED_BY_TASK
        blocked.blocked_by = [blocker.id]
        q.add(blocker)
        q.add(blocked)
        report = s.report_blocked(q)
        assert "blocked task" in report
        assert "Blocked by dependencies" in report

# ---------------------------------------------------------------------------
# Stale clarification detection
# ---------------------------------------------------------------------------


class TestStaleClarificationDetection:
    def _make_scheduler(self, callback=None, timeout_minutes=60):
        cfg = make_config()
        cfg.clarification_timeout_minutes = timeout_minutes
        return Scheduler(cfg, stale_clarification_callback=callback)

    def _make_blocked_task(
        self,
        question="Which approach?",
        minutes_ago=90,
        status=TaskStatus.BLOCKED_BY_HUMAN,
    ) -> Task:
        from datetime import datetime, timezone, timedelta
        task = make_task(status=status)
        task.pending_question = question
        blocked_time = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
        task.last_modified = blocked_time.isoformat()
        task.started_at = blocked_time.isoformat()
        task.created_at = blocked_time.isoformat()
        return task

    def test_callback_not_called_when_none(self):
        """No callback registered — detection should be skipped silently."""
        s = self._make_scheduler(callback=None)
        task = self._make_blocked_task()
        # Should not raise
        s._check_stale_clarifications([task])

    def test_callback_not_called_when_no_pending_question(self):
        callback = MagicMock()
        s = self._make_scheduler(callback=callback, timeout_minutes=60)
        task = make_task(status=TaskStatus.BLOCKED_BY_HUMAN)
        task.pending_question = ""
        s._check_stale_clarifications([task])
        callback.assert_not_called()

    def test_callback_not_called_for_non_blocked_task(self):
        callback = MagicMock()
        s = self._make_scheduler(callback=callback, timeout_minutes=60)
        task = self._make_blocked_task(minutes_ago=120)
        task.status = TaskStatus.READY  # not blocked
        s._check_stale_clarifications([task])
        callback.assert_not_called()

    def test_callback_not_called_within_timeout(self):
        callback = MagicMock()
        s = self._make_scheduler(callback=callback, timeout_minutes=60)
        # Only 30 minutes old — within 60 minute timeout
        task = self._make_blocked_task(minutes_ago=30)
        s._check_stale_clarifications([task])
        callback.assert_not_called()

    def test_callback_called_when_stale(self):
        callback = MagicMock()
        s = self._make_scheduler(callback=callback, timeout_minutes=60)
        # 90 minutes old — past 60 minute timeout
        task = self._make_blocked_task(minutes_ago=90,
                                       question="Which module to use?")
        s._check_stale_clarifications([task])
        callback.assert_called_once()

    def test_callback_receives_task_id(self):
        callback = MagicMock()
        s = self._make_scheduler(callback=callback, timeout_minutes=60)
        task = self._make_blocked_task(minutes_ago=90)
        s._check_stale_clarifications([task])
        called_task_id = callback.call_args[0][0]
        assert called_task_id == task.id

    def test_callback_receives_question_text(self):
        callback = MagicMock()
        s = self._make_scheduler(callback=callback, timeout_minutes=60)
        task = self._make_blocked_task(
            minutes_ago=90, question="What is the expected output?"
        )
        s._check_stale_clarifications([task])
        called_question = callback.call_args[0][1]
        assert called_question == "What is the expected output?"

    def test_callback_receives_blocked_since_iso_string(self):
        callback = MagicMock()
        s = self._make_scheduler(callback=callback, timeout_minutes=60)
        task = self._make_blocked_task(minutes_ago=90)
        s._check_stale_clarifications([task])
        called_blocked_since = callback.call_args[0][2]
        # Must be parseable ISO string
        from datetime import datetime
        dt = datetime.fromisoformat(called_blocked_since)
        assert dt is not None

    def test_callback_called_once_per_stale_task(self):
        callback = MagicMock()
        s = self._make_scheduler(callback=callback, timeout_minutes=60)
        task = self._make_blocked_task(minutes_ago=90)
        # Call twice — should fire on both since deduplication is
        # handled by orchestrator via workspace state, not scheduler
        s._check_stale_clarifications([task])
        s._check_stale_clarifications([task])
        assert callback.call_count == 2

    def test_multiple_stale_tasks_each_trigger_callback(self):
        callback = MagicMock()
        s = self._make_scheduler(callback=callback, timeout_minutes=60)
        tasks = [self._make_blocked_task(minutes_ago=90) for _ in range(3)]
        s._check_stale_clarifications(tasks)
        assert callback.call_count == 3

    def test_callback_exception_does_not_propagate(self):
        def bad_callback(task_id, question, blocked_since):
            raise RuntimeError("callback error")

        s = self._make_scheduler(callback=bad_callback, timeout_minutes=60)
        task = self._make_blocked_task(minutes_ago=90)
        # Should not raise
        s._check_stale_clarifications([task])

    def test_stale_detection_fires_during_next(self):
        """Stale detection is called as part of scheduler.next()."""
        callback = MagicMock()
        s = self._make_scheduler(callback=callback, timeout_minutes=60)
        stale = self._make_blocked_task(minutes_ago=90)
        q = make_queue_with_tasks([stale])
        s.next(q)
        callback.assert_called_once()

    def test_no_stale_detection_without_callback(self):
        """Scheduler with no callback skips detection entirely."""
        s = Scheduler(make_config())  # no callback
        stale = self._make_blocked_task(minutes_ago=999)
        q = make_queue_with_tasks([stale])
        # Should not raise even with very stale task
        s.next(q)

    def test_timeout_respected_from_config(self):
        """A 10-minute timeout fires for a task blocked 15 minutes."""
        callback = MagicMock()
        s = self._make_scheduler(callback=callback, timeout_minutes=10)
        task = self._make_blocked_task(minutes_ago=15)
        s._check_stale_clarifications([task])
        callback.assert_called_once()

    def test_timeout_respected_from_config_not_fired(self):
        """A 120-minute timeout does not fire for a task blocked 90 minutes."""
        callback = MagicMock()
        s = self._make_scheduler(callback=callback, timeout_minutes=120)
        task = self._make_blocked_task(minutes_ago=90)
        s._check_stale_clarifications([task])
        callback.assert_not_called()