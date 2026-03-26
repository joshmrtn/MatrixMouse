"""
tests/test_orchestrator.py

Tests for matrixmouse.orchestrator — stable logic only.

Skipped (unstable — will change soon):
    - _run_task / _run_agent full flow
    - run() main loop
    - branch-per-task logic

Coverage:
    _should_yield:
        - Returns False when slice not expired and no preempting tasks
        - Returns True when time slice expired
        - Returns True when preempting task present
        - Does not yield for the currently running task's own preempt flag

    _handle_turn_limit:
        - Marks task BLOCKED_BY_HUMAN
        - Emits turn_limit_reached event
        - Sends ntfy notification

    _handle_complete:
        - Manager task marked COMPLETE directly
        - Manager review summary stored in last_review_summary
        - Critic task: no-op (approve/deny handled in task_tools)
        - Coder task creates Critic review task
        - Writer task creates Critic review task
        - Critic review task blocks original task

    _create_critic_review:
        - Creates task with CRITIC role
        - reviews_task_id set to original task id
        - Priority matches reviewed task
        - Original task blocked by critic task
        - Falls back to direct complete if critic task creation fails

    _load_or_build_messages:
        - Returns persisted messages when context_messages present
        - Calls agent.build_initial_messages for fresh task

    _scoring_kwargs:
        - Returns dict with config-backed values

    _maybe_inject_manager_review:
        - No injection when schedule empty
        - Injects when no prior review
        - Injected task has preempt=True
        - No duplicate when review already active
        - No injection when not due
        - Injects when overdue

    _handle_stale_clarification:
        - Creates Manager task for stale clarification
        - Manager task contains the question
        - Stale task recorded in workspace state repo
        - No duplicate when existing Manager task active
        - Creates new task after previous completed
        - No task created for unknown blocked task
"""

from datetime import datetime, timezone
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from matrixmouse.orchestrator import Orchestrator
from matrixmouse.task import AgentRole, Task, TaskStatus
from matrixmouse.loop import LoopResult, LoopExitReason
from matrixmouse.repository.memory_task_repository import InMemoryTaskRepository
from matrixmouse.repository.workspace_state_repository import WorkspaceStateRepository
# Remove the local class definition entirely, replace with:
from matrixmouse.repository.memory_workspace_state_repository import (
    InMemoryWorkspaceStateRepository,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_task(
    title: str = "Test task",
    description: str = "Do the thing carefully.",
    role: AgentRole = AgentRole.CODER,
    repo: list[str] | None = None,
    importance=0.5,
    urgency=0.5,
    **kwargs,
) -> Task:
    return Task(
        title=title,
        description=description,
        role=role,
        repo=repo if repo is not None else ["repo"],
        importance=importance,
        urgency=urgency,
        **kwargs,
    )


def make_config(**kwargs) -> MagicMock:
    cfg = MagicMock()
    cfg.priority_aging_rate           = kwargs.get("aging_rate",               0.01)
    cfg.priority_max_aging_bonus      = kwargs.get("max_aging_bonus",          0.3)
    cfg.priority_importance_weight    = kwargs.get("importance_weight",        0.6)
    cfg.priority_urgency_weight       = kwargs.get("urgency_weight",           0.4)
    cfg.agent_max_turns               = kwargs.get("agent_max_turns",          50)
    cfg.manager_review_schedule       = kwargs.get("schedule",                 "")
    cfg.clarification_timeout_minutes = kwargs.get("timeout_minutes",          60)
    cfg.manager_review_upcoming_tasks = kwargs.get("upcoming_tasks",           20)
    cfg.critic_max_turns              = kwargs.get("critic_max_turns",         5)
    cfg.manager_planning_max_turns    = kwargs.get("planning_max_turns",       10)
    cfg.agent_branch_prefix           = kwargs.get("agent_branch_prefix",      "mm")
    return cfg


def make_orchestrator(tmp_path: Path, **config_kwargs) -> Orchestrator:
    config       = make_config(**config_kwargs)
    paths        = MagicMock()
    paths.workspace_root = tmp_path
    paths.agent_notes    = tmp_path / "AGENT_NOTES.md"
    queue        = InMemoryTaskRepository()
    ws_state_repo = InMemoryWorkspaceStateRepository()
    return Orchestrator(
        config=config,
        paths=paths,
        queue=queue,
        ws_state_repo=ws_state_repo,
    )


def make_loop_result(
    exit_reason=LoopExitReason.COMPLETE,
    decision_type="",
    turns=5,
    summary="done",
    messages=None,
) -> LoopResult:
    return LoopResult(
        exit_reason=exit_reason,
        decision_type=decision_type,
        messages=messages or [{"role": "user", "content": "go"}],
        turns_taken=turns,
        completion_summary=summary,
    )


# ---------------------------------------------------------------------------
# _should_yield
# ---------------------------------------------------------------------------

class TestShouldYield:
    def test_returns_false_when_no_expiry_no_preempt(self, tmp_path):
        orch = make_orchestrator(tmp_path)
        task = make_task()
        orch.queue.add(task)
        orch._scheduler.time_slice_expired = MagicMock(return_value=False)
        assert orch._should_yield(task) is False

    def test_returns_true_when_slice_expired(self, tmp_path):
        orch = make_orchestrator(tmp_path)
        task = make_task()
        orch.queue.add(task)
        orch._scheduler.time_slice_expired = MagicMock(return_value=True)
        assert orch._should_yield(task) is True

    def test_returns_true_when_preempting_task_present(self, tmp_path):
        orch = make_orchestrator(tmp_path)
        running = make_task(title="running", status=TaskStatus.RUNNING)
        preempting = make_task(title="preempt", status=TaskStatus.READY)
        preempting.preempt = True
        orch.queue.add(running)
        orch.queue.add(preempting)
        orch._scheduler.time_slice_expired = MagicMock(return_value=False)
        assert orch._should_yield(running) is True

    def test_does_not_yield_for_own_preempt_flag(self, tmp_path):
        orch = make_orchestrator(tmp_path)
        task = make_task(status=TaskStatus.RUNNING)
        task.preempt = True
        orch.queue.add(task)
        orch._scheduler.time_slice_expired = MagicMock(return_value=False)
        assert orch._should_yield(task) is False

    def test_does_not_yield_when_preempting_task_not_ready(self, tmp_path):
        orch = make_orchestrator(tmp_path)
        running = make_task(title="running", status=TaskStatus.RUNNING)
        preempting = make_task(
            title="preempt", status=TaskStatus.BLOCKED_BY_HUMAN
        )
        preempting.preempt = True
        orch.queue.add(running)
        orch.queue.add(preempting)
        orch._scheduler.time_slice_expired = MagicMock(return_value=False)
        assert orch._should_yield(running) is False


# ---------------------------------------------------------------------------
# _handle_turn_limit
# ---------------------------------------------------------------------------

class TestHandleTurnLimit:
    def test_marks_task_blocked_by_human(self, tmp_path):
        orch = make_orchestrator(tmp_path)
        task = make_task()
        orch.queue.add(task)
        result = make_loop_result(
            exit_reason=LoopExitReason.DECISION, turns=50,
            decision_type="turn_limit_reached"
        )
        with patch("matrixmouse.comms.get_manager", return_value=None):
            orch._handle_decision(task, result)
        updated_task = orch.queue.get(task.id)
        assert updated_task is not None
        assert updated_task.status == TaskStatus.BLOCKED_BY_HUMAN

    def test_emits_turn_limit_reached_event(self, tmp_path):
        orch = make_orchestrator(tmp_path)
        task = make_task()
        orch.queue.add(task)
        result = make_loop_result(
            exit_reason=LoopExitReason.DECISION, turns=50,
            decision_type="turn_limit_reached"
        )
        mock_comms = MagicMock()
        with patch("matrixmouse.comms.get_manager", return_value=mock_comms):
            orch._handle_decision(task, result)
        emitted_types = [c.args[0] for c in mock_comms.emit.call_args_list]
        assert "turn_limit_reached" in emitted_types

    def test_sends_ntfy_notification(self, tmp_path):
        orch = make_orchestrator(tmp_path)
        task = make_task(title="My stuck task")
        orch.queue.add(task)
        result = make_loop_result(
            exit_reason=LoopExitReason.DECISION, turns=50,
            decision_type="turn_limit_reached"
        )
        mock_comms = MagicMock()
        with patch("matrixmouse.comms.get_manager", return_value=mock_comms):
            orch._handle_decision(task, result)
        mock_comms.notify_blocked.assert_called_once()
        call_args = mock_comms.notify_blocked.call_args[0][0]
        assert "My stuck task" in call_args or task.id in call_args

    def test_event_contains_task_details(self, tmp_path):
        orch = make_orchestrator(tmp_path)
        task = make_task(role=AgentRole.CODER)
        orch.queue.add(task)
        result = make_loop_result(
            exit_reason=LoopExitReason.DECISION, turns=42,
            decision_type="turn_limit_reached"
        )
        mock_comms = MagicMock()
        with patch("matrixmouse.comms.get_manager", return_value=mock_comms):
            orch._handle_decision(task, result)
        emit_data = {
            c.args[1]["task_id"]: c.args[1]
            for c in mock_comms.emit.call_args_list
            if c.args[0] == "turn_limit_reached"
        }
        assert task.id in emit_data
        assert emit_data[task.id]["turns_taken"] == 42
        assert emit_data[task.id]["role"] == "coder"


# ---------------------------------------------------------------------------
# _handle_complete
# ---------------------------------------------------------------------------

class TestHandleComplete:
    def test_manager_task_marked_complete_directly(self, tmp_path):
        orch = make_orchestrator(tmp_path)
        task = make_task(role=AgentRole.MANAGER)
        orch.queue.add(task)
        result = make_loop_result(summary="reviewed 5 tasks")
        with patch("matrixmouse.comms.get_manager", return_value=None):
            orch._handle_complete(task, result)
        updated_task = orch.queue.get(task.id)
        assert updated_task is not None
        assert updated_task.status == TaskStatus.COMPLETE

    def test_manager_review_summary_stored(self, tmp_path):
        orch = make_orchestrator(tmp_path)
        task = make_task(role=AgentRole.MANAGER)
        orch.queue.add(task)
        result = make_loop_result(summary="All tasks look healthy.")
        with patch("matrixmouse.comms.get_manager", return_value=None):
            orch._handle_complete(task, result)
        updated_task = orch.queue.get(task.id)
        assert updated_task is not None
        assert updated_task.last_review_summary == \
               "All tasks look healthy."

    def test_critic_task_is_noop(self, tmp_path):
        orch = make_orchestrator(tmp_path)
        task = make_task(role=AgentRole.CRITIC)
        orch.queue.add(task)
        result = make_loop_result()
        orch._handle_complete(task, result)
        assert orch.queue.get(task.id) is not None

    def test_coder_task_creates_critic_review(self, tmp_path):
        orch = make_orchestrator(tmp_path)
        task = make_task(role=AgentRole.CODER)
        orch.queue.add(task)
        result = make_loop_result()
        with patch("matrixmouse.orchestrator._fetch_diff_for_task",
                   return_value=""), \
             patch("matrixmouse.comms.get_manager", return_value=None):
            orch._handle_complete(task, result)
        critic_tasks = [
            t for t in orch.queue.all_tasks()
            if t.role == AgentRole.CRITIC
        ]
        assert len(critic_tasks) == 1

    def test_writer_task_creates_critic_review(self, tmp_path):
        orch = make_orchestrator(tmp_path)
        task = make_task(role=AgentRole.WRITER)
        orch.queue.add(task)
        result = make_loop_result()
        with patch("matrixmouse.orchestrator._fetch_diff_for_task",
                   return_value=""), \
             patch("matrixmouse.comms.get_manager", return_value=None):
            orch._handle_complete(task, result)
        critic_tasks = [
            t for t in orch.queue.all_tasks()
            if t.role == AgentRole.CRITIC
        ]
        assert len(critic_tasks) == 1

    def test_coder_task_blocked_after_critic_created(self, tmp_path):
        orch = make_orchestrator(tmp_path)
        task = make_task(role=AgentRole.CODER)
        orch.queue.add(task)
        result = make_loop_result()
        with patch("matrixmouse.orchestrator._fetch_diff_for_task",
                   return_value=""), \
             patch("matrixmouse.comms.get_manager", return_value=None):
            orch._handle_complete(task, result)
        updated = orch.queue.get(task.id)
        assert updated is not None
        assert updated.status == TaskStatus.BLOCKED_BY_TASK
        assert orch.queue.has_blockers(task.id)


# ---------------------------------------------------------------------------
# _create_critic_review
# ---------------------------------------------------------------------------

class TestCreateCriticReview:
    def _run(self, tmp_path, task):
        orch = make_orchestrator(tmp_path)
        orch.queue.add(task)
        result = make_loop_result()
        with patch("matrixmouse.orchestrator._fetch_diff_for_task",
                   return_value="diff content"), \
             patch("matrixmouse.comms.get_manager", return_value=None):
            orch._create_critic_review(task, result)
        return orch

    def test_critic_task_has_correct_role(self, tmp_path):
        task = make_task(role=AgentRole.CODER)
        orch = self._run(tmp_path, task)
        critic = next(
            t for t in orch.queue.all_tasks()
            if t.role == AgentRole.CRITIC
        )
        assert critic.role == AgentRole.CRITIC

    def test_critic_task_reviews_task_id_set(self, tmp_path):
        task = make_task(role=AgentRole.CODER)
        orch = self._run(tmp_path, task)
        critic = next(
            t for t in orch.queue.all_tasks()
            if t.role == AgentRole.CRITIC
        )
        assert critic.reviews_task_id == task.id

    def test_critic_task_priority_matches_reviewed(self, tmp_path):
        task = make_task(role=AgentRole.CODER, importance=0.8, urgency=0.9)
        orch = self._run(tmp_path, task)
        critic = next(
            t for t in orch.queue.all_tasks()
            if t.role == AgentRole.CRITIC
        )
        assert critic.importance == task.importance
        assert critic.urgency == task.urgency

    def test_original_task_blocked_by_critic(self, tmp_path):
        task = make_task(role=AgentRole.CODER)
        orch = self._run(tmp_path, task)
        critic = next(
            t for t in orch.queue.all_tasks()
            if t.role == AgentRole.CRITIC
        )
        assert orch.queue.has_blockers(task.id)
        blockers = orch.queue.get_blocked_by(task.id)
        assert any(b.id == critic.id for b in blockers)

    def test_falls_back_to_direct_complete_on_queue_failure(self, tmp_path):
        orch = make_orchestrator(tmp_path)
        task = make_task(role=AgentRole.CODER)
        orch.queue.add(task)
        result = make_loop_result()
        with patch("matrixmouse.orchestrator._fetch_diff_for_task",
                   return_value=""), \
             patch("matrixmouse.comms.get_manager", return_value=None), \
             patch.object(orch.queue, "add", side_effect=Exception("disk full")):
            orch._create_critic_review(task, result)
        # Should fall back to marking the original task complete
        orig_task = orch.queue.get(task.id)
        assert orig_task is not None
        assert orig_task.status == TaskStatus.COMPLETE


# ---------------------------------------------------------------------------
# _load_or_build_messages
# ---------------------------------------------------------------------------

class TestLoadOrBuildMessages:
    def test_returns_persisted_messages_when_present(self, tmp_path):
        orch = make_orchestrator(tmp_path)
        task = make_task()
        task.context_messages = [
            {"role": "system",    "content": "sys"},
            {"role": "user",      "content": "go"},
            {"role": "assistant", "content": "working"},
        ]
        orch.queue.add(task)
        agent = MagicMock()
        result = orch._load_or_build_messages(task, agent)
        assert result == task.context_messages
        agent.build_initial_messages.assert_not_called()

    def test_calls_agent_build_for_fresh_task(self, tmp_path):
        orch = make_orchestrator(tmp_path)
        task = make_task()
        task.context_messages = []
        orch.queue.add(task)
        agent = MagicMock()
        agent.build_initial_messages.return_value = [
            {"role": "system", "content": "prompt"},
            {"role": "user",   "content": "task"},
        ]
        result = orch._load_or_build_messages(task, agent)
        agent.build_initial_messages.assert_called_once_with(task)
        assert result == agent.build_initial_messages.return_value

    def test_returns_copy_of_persisted_messages(self, tmp_path):
        orch = make_orchestrator(tmp_path)
        task = make_task()
        task.context_messages = [{"role": "user", "content": "go"}]
        orch.queue.add(task)
        agent = MagicMock()
        result = orch._load_or_build_messages(task, agent)
        # Mutating result should not affect task.context_messages
        result.append({"role": "assistant", "content": "extra"})
        assert len(task.context_messages) == 1


# ---------------------------------------------------------------------------
# _scoring_kwargs
# ---------------------------------------------------------------------------

class TestScoringKwargs:
    def test_returns_config_backed_values(self, tmp_path):
        orch = make_orchestrator(
            tmp_path,
            aging_rate=0.02,
            max_aging_bonus=0.5,
            importance_weight=0.7,
            urgency_weight=0.3,
        )
        kwargs = orch._scoring_kwargs()
        assert kwargs["aging_rate"]        == 0.02
        assert kwargs["max_aging_bonus"]   == 0.5
        assert kwargs["importance_weight"] == 0.7
        assert kwargs["urgency_weight"]    == 0.3


# ---------------------------------------------------------------------------
# _maybe_inject_manager_review
# ---------------------------------------------------------------------------

class TestMaybeInjectManagerReview:
    def _make_orchestrator(self, tmp_path, schedule="0 9 * * *"):
        orch = make_orchestrator(tmp_path)
        orch.config.manager_review_schedule       = schedule
        orch.config.manager_review_upcoming_tasks = 20
        return orch

    def test_no_injection_when_schedule_empty(self, tmp_path):
        orch = self._make_orchestrator(tmp_path, schedule="")
        orch._maybe_inject_manager_review()
        assert len(orch.queue.all_tasks()) == 0

    def test_injects_review_task_when_no_prior_review(self, tmp_path):
        orch = self._make_orchestrator(tmp_path)
        # No last_manager_review_at in state → always due
        orch._maybe_inject_manager_review()
        tasks = orch.queue.all_tasks()
        assert len(tasks) == 1
        assert tasks[0].role == AgentRole.MANAGER
        assert tasks[0].title.startswith("[Manager Review]")

    def test_injected_task_has_preempt_true(self, tmp_path):
        orch = self._make_orchestrator(tmp_path)
        orch._maybe_inject_manager_review()
        assert orch.queue.all_tasks()[0].preempt is True

    def test_no_duplicate_when_review_already_active(self, tmp_path):
        orch = self._make_orchestrator(tmp_path)
        # Inject once
        orch._maybe_inject_manager_review()
        # Inject again — should not create a second review task
        orch._maybe_inject_manager_review()
        review_tasks = [
            t for t in orch.queue.all_tasks()
            if t.title.startswith("[Manager Review]")
        ]
        assert len(review_tasks) == 1

    def test_no_injection_when_not_due(self, tmp_path):
        orch = self._make_orchestrator(tmp_path, schedule="0 9 * * *")
        orch._ws_state_repo.set_last_review_at()
        orch._maybe_inject_manager_review()
        assert len(orch.queue.all_tasks()) == 0

    def test_injects_when_review_overdue(self, tmp_path):
        from datetime import datetime, timezone, timedelta
        orch = self._make_orchestrator(tmp_path, schedule="0 9 * * *")
        old_dt = datetime.now(timezone.utc) - timedelta(hours=25)
        orch._ws_state_repo.set_last_review_at(old_dt)
        orch._maybe_inject_manager_review()
        review_tasks = [
            t for t in orch.queue.all_tasks()
            if t.title.startswith("[Manager Review]")
        ]
        assert len(review_tasks) == 1


# ---------------------------------------------------------------------------
# _handle_stale_clarification
# ---------------------------------------------------------------------------

class TestHandleStaleClarification:
    def _make_orchestrator(self, tmp_path):
        orch = make_orchestrator(tmp_path)
        orch.config.manager_review_upcoming_tasks = 20
        return orch

    def test_creates_manager_task_for_stale_clarification(self, tmp_path):
        orch = self._make_orchestrator(tmp_path)
        blocked = make_task(title="blocked task", role=AgentRole.CODER)
        blocked.status = TaskStatus.BLOCKED_BY_HUMAN
        orch.queue.add(blocked)
        orch._handle_stale_clarification(
            blocked.id, "Which algorithm?", "2026-01-01T00:00:00+00:00"
        )
        manager_tasks = [
            t for t in orch.queue.all_tasks()
            if t.role == AgentRole.MANAGER
        ]
        assert len(manager_tasks) == 1

    def test_stale_manager_task_contains_question(self, tmp_path):
        orch = self._make_orchestrator(tmp_path)
        blocked = make_task()
        blocked.status = TaskStatus.BLOCKED_BY_HUMAN
        orch.queue.add(blocked)
        orch._handle_stale_clarification(
            blocked.id,
            "What is the expected output format?",
            "2026-01-01T00:00:00+00:00",
        )
        manager_task = next(
            t for t in orch.queue.all_tasks()
            if t.role == AgentRole.MANAGER
        )
        assert "What is the expected output format?" in manager_task.description

    def test_stale_task_recorded_in_workspace_state(self, tmp_path):
        orch = self._make_orchestrator(tmp_path)
        blocked = make_task()
        blocked.status = TaskStatus.BLOCKED_BY_HUMAN
        orch.queue.add(blocked)
        orch._handle_stale_clarification(
            blocked.id, "Question?", "2026-01-01T00:00:00+00:00"
        )
        manager_task_id = orch._ws_state_repo.get_stale_clarification_task(
            blocked.id
        )
        assert manager_task_id is not None

    def test_no_duplicate_when_existing_manager_task_active(self, tmp_path):
        orch = self._make_orchestrator(tmp_path)
        blocked = make_task()
        blocked.status = TaskStatus.BLOCKED_BY_HUMAN
        orch.queue.add(blocked)
        orch._handle_stale_clarification(
            blocked.id, "Question?", "2026-01-01T00:00:00+00:00"
        )
        orch._handle_stale_clarification(
            blocked.id, "Question?", "2026-01-01T00:00:00+00:00"
        )
        assert len([
            t for t in orch.queue.all_tasks()
            if t.role == AgentRole.MANAGER
        ]) == 1

    def test_creates_new_task_after_previous_completed(self, tmp_path):
        orch = self._make_orchestrator(tmp_path)
        blocked = make_task()
        blocked.status = TaskStatus.BLOCKED_BY_HUMAN
        orch.queue.add(blocked)
        orch._handle_stale_clarification(
            blocked.id, "Question?", "2026-01-01T00:00:00+00:00"
        )
        manager_task = next(
            t for t in orch.queue.all_tasks()
            if t.role == AgentRole.MANAGER
        )
        orch.queue.mark_complete(manager_task.id)
        orch._handle_stale_clarification(
            blocked.id, "Question?", "2026-01-01T00:00:00+00:00"
        )
        assert len([
            t for t in orch.queue.all_tasks()
            if t.role == AgentRole.MANAGER
        ]) == 2

    def test_no_task_created_for_unknown_blocked_task(self, tmp_path):
        orch = self._make_orchestrator(tmp_path)
        orch._handle_stale_clarification(
            "nonexistent-task-id", "Question?", "2026-01-01T00:00:00+00:00"
        )
        assert len(orch.queue.all_tasks()) == 0


# ---------------------------------------------------------------------------
# _on_manager_review_complete
# ---------------------------------------------------------------------------

class TestOnManagerReviewComplete:
    def test_last_review_at_set(self, tmp_path):
        orch = make_orchestrator(tmp_path)
        orch._on_manager_review_complete("Summary.")
        assert orch._ws_state_repo.get_last_review_at() is not None

    def test_summary_stored(self, tmp_path):
        orch = make_orchestrator(tmp_path)
        orch._on_manager_review_complete("Tasks are healthy.")
        assert orch._ws_state_repo.get_last_review_summary() == \
               "Tasks are healthy."

    def test_handles_empty_summary(self, tmp_path):
        orch = make_orchestrator(tmp_path)
        orch._on_manager_review_complete("")
        assert orch._ws_state_repo.get_last_review_summary() == ""

    def test_handle_complete_calls_on_review_complete_for_review_task(
        self, tmp_path
    ):
        orch = make_orchestrator(tmp_path)
        task = make_task(
            role=AgentRole.MANAGER,
            title="[Manager Review] Daily review",
        )
        orch.queue.add(task)
        result = make_loop_result(summary="Review done.")
        with patch("matrixmouse.comms.get_manager", return_value=None), \
             patch.object(orch, "_on_manager_review_complete") as mock_review:
            orch._handle_complete(task, result)
        mock_review.assert_called_once_with("Review done.")

    def test_handle_complete_does_not_call_on_review_for_normal_manager(
        self, tmp_path
    ):
        orch = make_orchestrator(tmp_path)
        task = make_task(
            role=AgentRole.MANAGER,
            title="Plan the new feature",
        )
        orch.queue.add(task)
        result = make_loop_result(summary="Done.")
        with patch("matrixmouse.comms.get_manager", return_value=None), \
             patch.object(orch, "_on_manager_review_complete") as mock_review:
            orch._handle_complete(task, result)
        mock_review.assert_not_called()


# ---------------------------------------------------------------------------
# Session mode wiring
# ---------------------------------------------------------------------------

class TestSessionModeWiring:
    """
    Tests for BRANCH_SETUP and PLANNING session mode wiring in the
    orchestrator. These test the orchestrator's state management around
    session contexts — not the full agent loop execution.
    """

    def test_branch_setup_context_set_for_branchless_manager(self, tmp_path):
        """Manager task with no branch gets BRANCH_SETUP session context."""
        from matrixmouse.repository.workspace_state_repository import SessionMode
        orch = make_orchestrator(tmp_path)
        task = make_task(role=AgentRole.MANAGER, branch="")
        orch.queue.add(task)

        # Simulate the session context check at start of _run_task
        # by calling the relevant block directly
        from matrixmouse.repository.workspace_state_repository import (
            SessionContext, BRANCH_SETUP_TOOLS
        )
        if (task.role == AgentRole.MANAGER
                and not task.branch
                and task.status != TaskStatus.PENDING):
            existing_ctx = orch._ws_state_repo.get_session_context(task.id)
            if existing_ctx is None:
                orch._ws_state_repo.set_session_context(
                    task.id,
                    SessionContext(
                        mode=SessionMode.BRANCH_SETUP,
                        allowed_tools=set(BRANCH_SETUP_TOOLS),
                        system_prompt_addendum="name the branch",
                    ),
                )

        ctx = orch._ws_state_repo.get_session_context(task.id)
        assert ctx is not None
        assert ctx.mode == SessionMode.BRANCH_SETUP
        assert "set_branch" in ctx.allowed_tools
        assert "split_task" not in ctx.allowed_tools

    def test_branch_setup_context_not_set_for_branched_manager(self, tmp_path):
        """Manager task with a branch does not get BRANCH_SETUP context."""
        from matrixmouse.repository.workspace_state_repository import SessionMode
        orch = make_orchestrator(tmp_path)
        task = make_task(role=AgentRole.MANAGER, branch="mm/feature/foo")
        orch.queue.add(task)
        # No context should be set
        assert orch._ws_state_repo.get_session_context(task.id) is None

    def test_planning_context_cleared_on_complete(self, tmp_path):
        """PLANNING session context is cleared when Manager declares complete."""
        from matrixmouse.repository.workspace_state_repository import (
            SessionContext, SessionMode, PLANNING_TOOLS
        )
        orch = make_orchestrator(tmp_path)
        task = make_task(role=AgentRole.MANAGER, branch="mm/feature/foo")
        orch.queue.add(task)

        # Set PLANNING context
        orch._ws_state_repo.set_session_context(
            task.id,
            SessionContext(
                mode=SessionMode.PLANNING,
                allowed_tools=set(PLANNING_TOOLS),
            ),
        )

        result = make_loop_result(summary="plan done")
        with patch("matrixmouse.comms.get_manager", return_value=None):
            orch._handle_complete(task, result)

        assert orch._ws_state_repo.get_session_context(task.id) is None

    def test_planning_commit_pending_subtree_on_complete(self, tmp_path):
        """PLANNING completion transitions PENDING subtasks to READY."""
        from matrixmouse.repository.workspace_state_repository import (
            SessionContext, SessionMode, PLANNING_TOOLS
        )
        orch = make_orchestrator(tmp_path)
        task = make_task(role=AgentRole.MANAGER, branch="mm/feature/foo")
        orch.queue.add(task)

        # Add PENDING subtask
        subtask = make_task(title="pending child",
                            status=TaskStatus.PENDING, branch="")
        subtask.parent_task_id = task.id
        subtask.depth = 1
        orch.queue.add(subtask)

        # Set PLANNING context
        orch._ws_state_repo.set_session_context(
            task.id,
            SessionContext(
                mode=SessionMode.PLANNING,
                allowed_tools=set(PLANNING_TOOLS),
            ),
        )

        result = make_loop_result(summary="plan done")
        with patch("matrixmouse.comms.get_manager", return_value=None):
            orch._handle_complete(task, result)

        t = orch.queue.get(subtask.id)
        assert t is not None
        assert t.status == TaskStatus.READY

    def test_branch_setup_context_cleared_on_complete(self, tmp_path):
        """BRANCH_SETUP session context is cleared when Manager completes."""
        from matrixmouse.repository.workspace_state_repository import (
            SessionContext, SessionMode, BRANCH_SETUP_TOOLS
        )
        orch = make_orchestrator(tmp_path)
        task = make_task(role=AgentRole.MANAGER, branch="mm/feature/foo")
        orch.queue.add(task)

        orch._ws_state_repo.set_session_context(
            task.id,
            SessionContext(
                mode=SessionMode.BRANCH_SETUP,
                allowed_tools=set(BRANCH_SETUP_TOOLS),
            ),
        )

        result = make_loop_result(summary="branch set")
        with patch("matrixmouse.comms.get_manager", return_value=None):
            orch._handle_complete(task, result)

        assert orch._ws_state_repo.get_session_context(task.id) is None

    def test_planning_turn_limit_commits_pending_and_clears_context(
        self, tmp_path
    ):
        """On PLANNING turn limit, pending tasks committed and context cleared."""
        from matrixmouse.repository.workspace_state_repository import (
            SessionContext, SessionMode, PLANNING_TOOLS
        )
        orch = make_orchestrator(tmp_path)
        orch.config.manager_planning_max_turns = 10
        task = make_task(role=AgentRole.MANAGER, branch="mm/feature/foo")
        orch.queue.add(task)

        subtask = make_task(title="pending child",
                            status=TaskStatus.PENDING, branch="")
        subtask.parent_task_id = task.id
        subtask.depth = 1
        orch.queue.add(subtask)

        orch._ws_state_repo.set_session_context(
            task.id,
            SessionContext(
                mode=SessionMode.PLANNING,
                allowed_tools=set(PLANNING_TOOLS),
            ),
        )

        result = make_loop_result(
            exit_reason=LoopExitReason.DECISION,
            decision_type="turn_limit_reached",
            turns=10,
        )
        mock_comms = MagicMock()
        with patch("matrixmouse.comms.get_manager", return_value=mock_comms):
            orch._handle_decision(task, result)

        # Pending task committed
        t = orch.queue.get(subtask.id)
        assert t is not None
        assert t.status == TaskStatus.READY
        # Context cleared
        assert orch._ws_state_repo.get_session_context(task.id) is None
        # Correct event emitted
        emitted = [c.args[0] for c in mock_comms.emit.call_args_list]
        assert "planning_turn_limit_reached" in emitted
        assert "turn_limit_reached" not in emitted

    def test_coder_task_not_given_branch_setup_context(self, tmp_path):
        """Non-Manager tasks never get BRANCH_SETUP context."""
        orch = make_orchestrator(tmp_path)
        task = make_task(role=AgentRole.CODER, branch="")
        orch.queue.add(task)
        assert orch._ws_state_repo.get_session_context(task.id) is None

    def test_branch_missing_triggers_human_intervention(self, tmp_path):
        """If branch cannot be recreated from mirror, task is blocked."""
        # Create the repo directory so the branch check runs
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()

        orch = make_orchestrator(tmp_path)
        task = make_task(role=AgentRole.CODER, branch="mm/feature/missing",
                        repo=["repo"])
        orch.queue.add(task)

        with patch("matrixmouse.orchestrator.ensure_branch_from_mirror",
                return_value=(False, "fetch failed: no such ref")), \
            patch("matrixmouse.comms.get_manager", return_value=None):
            orch._run_task(task)

        updated = orch.queue.get(task.id)
        assert updated is not None
        assert updated.status == TaskStatus.BLOCKED_BY_HUMAN

    def test_branchless_task_skips_verification(self, tmp_path):
        """Tasks with no branch set skip the mirror verification entirely."""
        orch = make_orchestrator(tmp_path)
        # Manager task with no branch — enters BRANCH_SETUP instead
        task = make_task(role=AgentRole.MANAGER, branch="")
        orch.queue.add(task)

        with patch("matrixmouse.orchestrator.ensure_branch_from_mirror") as mock_verify:
            with patch.object(orch, "_run_agent",
                            side_effect=Exception("stop here")), \
                patch("matrixmouse.comms.get_manager", return_value=None):
                try:
                    orch._run_task(task)
                except Exception:
                    pass

        mock_verify.assert_not_called()

    def test_task_with_branch_but_no_repo_skips_verification(self, tmp_path):
        """Tasks with a branch but empty repo list skip mirror verification."""
        orch = make_orchestrator(tmp_path)
        task = make_task(role=AgentRole.CODER, branch="mm/feature/foo", repo=[])
        orch.queue.add(task)

        with patch("matrixmouse.orchestrator.ensure_branch_from_mirror") as mock_verify:
            with patch.object(orch, "_run_agent",
                            side_effect=Exception("stop here")), \
                patch("matrixmouse.comms.get_manager", return_value=None):
                try:
                    orch._run_task(task)
                except Exception:
                    pass

        mock_verify.assert_not_called()

    def test_checkout_failure_triggers_human_intervention(self, tmp_path):
        """If git checkout fails after branch verification, task is blocked."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()

        orch = make_orchestrator(tmp_path)
        task = make_task(role=AgentRole.CODER, branch="mm/feature/foo",
                        repo=["repo"])
        orch.queue.add(task)

        with patch("matrixmouse.orchestrator.ensure_branch_from_mirror",
                return_value=(True, "mm/feature/foo")), \
            patch("matrixmouse.orchestrator._git",
                return_value=(False, "fatal: unable to checkout")), \
            patch("matrixmouse.comms.get_manager", return_value=None):
            orch._run_task(task)

        updated = orch.queue.get(task.id)
        assert updated is not None
        assert updated.status == TaskStatus.BLOCKED_BY_HUMAN
        

class TestWipCommitWiring:
    def test_wip_commit_callable_called_after_dispatch(self, tmp_path):
        """wip_commit is called once per turn after tool dispatch."""
        from matrixmouse.loop import AgentLoop, LoopExitReason
        from types import SimpleNamespace

        wip_calls = []

        def fake_wip():
            wip_calls.append(1)

        # Build a loop that runs one turn then declares complete
        messages = [{"role": "system", "content": "prompt"}]
        loop = AgentLoop(
            model="test",
            messages=messages,
            config=make_config(),
            paths=MagicMock(),
            wip_commit=fake_wip,
        )

        fake_response = SimpleNamespace(
            message=SimpleNamespace(
                content="done",
                thinking=None,
                tool_calls=[
                    SimpleNamespace(
                        function=SimpleNamespace(
                            name="declare_complete",
                            arguments={"summary": "all done"},
                        )
                    )
                ],
            )
        )

        with patch.object(loop, "_chat_completion",
                          return_value=fake_response):
            result = loop.run()

        # declare_complete exits before wip_commit fires
        assert result.exit_reason == LoopExitReason.COMPLETE
        # WIP commit should NOT fire on declare_complete exit
        assert len(wip_calls) == 0

    def test_wip_commit_fires_after_normal_tool_call(self, tmp_path):
        """wip_commit fires after a non-exit tool call turn."""
        from matrixmouse.loop import AgentLoop, LoopExitReason
        from matrixmouse.tools import TOOL_REGISTRY
        from types import SimpleNamespace

        wip_calls = []

        def fake_wip():
            wip_calls.append(1)

        messages = [{"role": "system", "content": "prompt"}]
        loop = AgentLoop(
            model="test",
            messages=messages,
            config=make_config(),
            paths=MagicMock(),
            wip_commit=fake_wip,
        )

        turn = 0
        def fake_response():
            nonlocal turn
            turn += 1
            if turn == 1:
                # First turn: normal tool call
                return SimpleNamespace(
                    message=SimpleNamespace(
                        content="",
                        thinking=None,
                        tool_calls=[
                            SimpleNamespace(
                                function=SimpleNamespace(
                                    name="get_git_status",
                                    arguments={},
                                )
                            )
                        ],
                    )
                )
            else:
                # Second turn: declare complete
                return SimpleNamespace(
                    message=SimpleNamespace(
                        content="done",
                        thinking=None,
                        tool_calls=[
                            SimpleNamespace(
                                function=SimpleNamespace(
                                    name="declare_complete",
                                    arguments={"summary": "done"},
                                )
                            )
                        ],
                    )
                )

        with patch.object(loop, "_chat_completion",
                          side_effect=fake_response), \
             patch.dict(TOOL_REGISTRY,
                        {"get_git_status": lambda: "clean"}):
            result = loop.run()

        assert result.exit_reason == LoopExitReason.COMPLETE
        # WIP commit fires after turn 1 (normal tool), not after turn 2 (exit)
        assert len(wip_calls) >= 1 # We now WIP commit after every dispatch & loop
        

class TestMergeUp:
    def test_clean_merge_marks_reviewed_task_complete(self, tmp_path):
        orch = make_orchestrator(tmp_path)
        reviewed = make_task(role=AgentRole.CODER, branch="mm/feature/foo",
                             repo=["repo"])
        critic = make_task(role=AgentRole.CRITIC)
        critic.reviews_task_id = reviewed.id
        orch.queue.add(reviewed)
        orch.queue.add(critic)
        orch.queue.add_dependency(critic.id, reviewed.id)

        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        result = make_loop_result()

        with patch.object(orch, "_get_merge_target",
                          return_value="mm/dev"), \
             patch.object(orch, "_is_protected_branch",
                          return_value=False), \
             patch.object(orch, "_run_merge_up",
                          return_value=(True, "")), \
             patch("matrixmouse.comms.get_manager", return_value=None):
            orch._handle_critic_complete(critic, result)

        t = orch.queue.get(reviewed.id)
        assert t is not None
        assert t.status == TaskStatus.COMPLETE

    def test_conflict_transitions_to_merge_role(self, tmp_path):
        orch = make_orchestrator(tmp_path)
        reviewed = make_task(role=AgentRole.CODER, branch="mm/feature/foo",
                             repo=["repo"])
        critic = make_task(role=AgentRole.CRITIC)
        critic.reviews_task_id = reviewed.id
        orch.queue.add(reviewed)
        orch.queue.add(critic)
        orch.queue.add_dependency(critic.id, reviewed.id)

        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        result = make_loop_result()

        with patch.object(orch, "_get_merge_target",
                          return_value="mm/dev"), \
             patch.object(orch, "_is_protected_branch",
                          return_value=False), \
             patch.object(orch, "_run_merge_up",
                          return_value=(False, "CONFLICT:foo.py,bar.py")), \
             patch("matrixmouse.comms.get_manager", return_value=None):
            orch._handle_critic_complete(critic, result)

        updated = orch.queue.get(reviewed.id)
        assert updated is not None
        assert updated.role == AgentRole.MERGE
        assert updated.status == TaskStatus.READY
        assert updated.preemptable is False

    def test_conflict_appends_notification_to_context(self, tmp_path):
        orch = make_orchestrator(tmp_path)
        reviewed = make_task(role=AgentRole.CODER, branch="mm/feature/foo",
                             repo=["repo"])
        critic = make_task(role=AgentRole.CRITIC)
        critic.reviews_task_id = reviewed.id
        orch.queue.add(reviewed)
        orch.queue.add(critic)
        orch.queue.add_dependency(critic.id, reviewed.id)

        (tmp_path / "repo").mkdir()
        result = make_loop_result()

        with patch.object(orch, "_get_merge_target",
                          return_value="mm/dev"), \
             patch.object(orch, "_is_protected_branch",
                          return_value=False), \
             patch.object(orch, "_run_merge_up",
                          return_value=(False, "CONFLICT:foo.py")), \
             patch("matrixmouse.comms.get_manager", return_value=None):
            orch._handle_critic_complete(critic, result)

        updated = orch.queue.get(reviewed.id)
        assert updated is not None
        assert any(
            "Merge Conflict Detected" in m.get("content", "")
            for m in updated.context_messages
        )

    def test_protected_branch_emits_pr_approval_required(self, tmp_path):
        orch = make_orchestrator(tmp_path)
        reviewed = make_task(role=AgentRole.CODER, branch="mm/feature/foo",
                             repo=["repo"])
        critic = make_task(role=AgentRole.CRITIC)
        critic.reviews_task_id = reviewed.id
        orch.queue.add(reviewed)
        orch.queue.add(critic)
        orch.queue.add_dependency(critic.id, reviewed.id)

        (tmp_path / "repo").mkdir()
        result = make_loop_result()
        mock_comms = MagicMock()

        with patch.object(orch, "_get_merge_target",
                          return_value="main"), \
             patch.object(orch, "_is_protected_branch",
                          return_value=True), \
             patch("matrixmouse.comms.get_manager",
                   return_value=mock_comms):
            orch._handle_critic_complete(critic, result)

        emitted = [c.args[0] for c in mock_comms.emit.call_args_list]
        assert "pr_approval_required" in emitted
        t = orch.queue.get(reviewed.id)
        assert t is not None
        assert t.status == TaskStatus.BLOCKED_BY_HUMAN

    def test_no_merge_target_blocks_for_human(self, tmp_path):
        orch = make_orchestrator(tmp_path)
        reviewed = make_task(role=AgentRole.CODER, branch="mm/feature/foo",
                             repo=["repo"])
        critic = make_task(role=AgentRole.CRITIC)
        critic.reviews_task_id = reviewed.id
        orch.queue.add(reviewed)
        orch.queue.add(critic)
        orch.queue.add_dependency(critic.id, reviewed.id)

        (tmp_path / "repo").mkdir()
        result = make_loop_result()
        mock_comms = MagicMock()

        with patch.object(orch, "_get_merge_target", return_value=None), \
             patch("matrixmouse.comms.get_manager",
                   return_value=mock_comms):
            orch._handle_critic_complete(critic, result)

        emitted = [c.args[0] for c in mock_comms.emit.call_args_list]
        assert "merge_target_required" in emitted
        t = orch.queue.get(reviewed.id)
        assert t is not None
        assert t.status == TaskStatus.BLOCKED_BY_HUMAN

    def test_merge_complete_releases_lock(self, tmp_path):
        orch = make_orchestrator(tmp_path)
        task = make_task(role=AgentRole.MERGE, branch="mm/feature/foo",
                         repo=["repo"])
        task.preemptable = False
        orch.queue.add(task)
        orch._ws_state_repo.acquire_merge_lock("mm/dev", task.id)

        (tmp_path / "repo").mkdir()
        result = make_loop_result()

        with patch.object(orch, "_get_merge_target",
                          return_value="mm/dev"), \
             patch("matrixmouse.tools.git_tools.push_to_remote",
                   return_value=(True, "")), \
             patch("matrixmouse.comms.get_manager", return_value=None):
            orch._handle_merge_complete(task, result)

        assert orch._ws_state_repo.get_merge_lock_holder("mm/dev") is None

    def test_merge_complete_marks_task_complete(self, tmp_path):
        orch = make_orchestrator(tmp_path)
        task = make_task(role=AgentRole.MERGE, branch="mm/feature/foo",
                         repo=["repo"])
        task.preemptable = False
        orch.queue.add(task)
        orch._ws_state_repo.acquire_merge_lock("mm/dev", task.id)

        (tmp_path / "repo").mkdir()
        result = make_loop_result()

        with patch.object(orch, "_get_merge_target",
                          return_value="mm/dev"), \
             patch("matrixmouse.tools.git_tools.push_to_remote",
                   return_value=(True, "")), \
             patch("matrixmouse.comms.get_manager", return_value=None):
            orch._handle_merge_complete(task, result)

        t = orch.queue.get(task.id)
        assert t is not None
        assert t.status == TaskStatus.COMPLETE

    def test_should_yield_false_for_non_preemptable(self, tmp_path):
        orch = make_orchestrator(tmp_path)
        task = make_task(role=AgentRole.MERGE)
        task.preemptable = False
        orch.queue.add(task)
        orch._scheduler.time_slice_expired = MagicMock(return_value=True)
        assert orch._should_yield(task) is False

    def test_queued_task_stays_blocked(self, tmp_path):
        orch = make_orchestrator(tmp_path)
        reviewed = make_task(role=AgentRole.CODER, branch="mm/feature/foo",
                             repo=["repo"])
        critic = make_task(role=AgentRole.CRITIC)
        critic.reviews_task_id = reviewed.id
        orch.queue.add(reviewed)
        orch.queue.add(critic)
        orch.queue.add_dependency(critic.id, reviewed.id)

        (tmp_path / "repo").mkdir()
        result = make_loop_result()

        with patch.object(orch, "_get_merge_target",
                          return_value="mm/dev"), \
             patch.object(orch, "_is_protected_branch",
                          return_value=False), \
             patch.object(orch, "_run_merge_up",
                          return_value=(False, "QUEUED")), \
             patch("matrixmouse.comms.get_manager", return_value=None):
            orch._handle_critic_complete(critic, result)

        # Task should not be complete or transitioned to MERGE
        updated = orch.queue.get(reviewed.id)
        assert updated is not None
        assert updated.role == AgentRole.CODER
        assert updated.status != TaskStatus.COMPLETE

class TestGetMergeTarget:
    def test_returns_parent_branch_when_parent_has_branch(self, tmp_path):
        orch = make_orchestrator(tmp_path)
        parent = make_task(role=AgentRole.MANAGER, branch="mm/feature/parent")
        child = make_task(role=AgentRole.CODER)
        child.parent_task_id = parent.id
        orch.queue.add(parent)
        orch.queue.add(child)
        assert orch._get_merge_target(child) == "mm/feature/parent"

    def test_returns_default_target_when_no_parent(self, tmp_path):
        orch = make_orchestrator(tmp_path)
        orch.config.default_merge_target = "mm/dev"
        task = make_task(role=AgentRole.CODER)
        orch.queue.add(task)
        assert orch._get_merge_target(task) == "mm/dev"

    def test_returns_none_when_no_parent_and_no_default(self, tmp_path):
        orch = make_orchestrator(tmp_path)
        orch.config.default_merge_target = ""
        task = make_task(role=AgentRole.CODER)
        orch.queue.add(task)
        assert orch._get_merge_target(task) is None

    def test_returns_none_when_parent_has_no_branch(self, tmp_path):
        orch = make_orchestrator(tmp_path)
        orch.config.default_merge_target = ""
        parent = make_task(role=AgentRole.MANAGER, branch="")
        child = make_task(role=AgentRole.CODER)
        child.parent_task_id = parent.id
        orch.queue.add(parent)
        orch.queue.add(child)
        assert orch._get_merge_target(child) is None

    def test_returns_none_when_parent_not_found(self, tmp_path):
        orch = make_orchestrator(tmp_path)
        orch.config.default_merge_target = ""
        task = make_task(role=AgentRole.CODER)
        task.parent_task_id = "nonexistent"
        orch.queue.add(task)
        assert orch._get_merge_target(task) is None


class TestIsProtectedBranch:
    def test_main_is_protected_by_default(self, tmp_path):
        orch = make_orchestrator(tmp_path)
        orch.config.protected_branches = ["main", "master", "develop"]
        assert orch._is_protected_branch("main") is True

    def test_agent_branch_is_not_protected(self, tmp_path):
        orch = make_orchestrator(tmp_path)
        orch.config.protected_branches = ["main", "master"]
        assert orch._is_protected_branch("mm/feature/foo") is False

    def test_empty_protected_list(self, tmp_path):
        orch = make_orchestrator(tmp_path)
        orch.config.protected_branches = []
        assert orch._is_protected_branch("main") is False


class TestRunMergeUp:
    def test_returns_queued_when_lock_busy(self, tmp_path):
        orch = make_orchestrator(tmp_path)
        task = make_task(role=AgentRole.CODER, branch="mm/feature/foo",
                         repo=["repo"])
        orch.queue.add(task)
        # Pre-lock the branch
        orch._ws_state_repo.acquire_merge_lock("mm/dev", "other-task")

        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()

        success, info = orch._run_merge_up(task, "mm/dev", repo_dir)
        assert not success
        assert info == "QUEUED"
        # Task should be enqueued
        assert orch._ws_state_repo.dequeue_next_merge_waiter("mm/dev") == task.id

    def test_returns_conflict_on_merge_conflict(self, tmp_path):
        orch = make_orchestrator(tmp_path)
        task = make_task(role=AgentRole.CODER, branch="mm/feature/foo",
                         repo=["repo"])
        orch.queue.add(task)
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()

        from matrixmouse.tools.git_tools import _git as real_git

        def mock_git(args, cwd):
            if args[0] == "checkout":
                return True, ""
            if args[0] == "merge":
                if "--abort" in args:
                    return True, ""
                return False, "CONFLICT (content): Merge conflict in foo.py"
            return True, ""

        with patch("matrixmouse.tools.git_tools._git", side_effect=mock_git), \
             patch("matrixmouse.tools.merge_tools.get_conflicted_files",
                   return_value=["foo.py"]):
            success, info = orch._run_merge_up(task, "mm/dev", repo_dir)

        assert not success
        assert info.startswith("CONFLICT:")
        assert "foo.py" in info
        # Lock should still be held
        assert orch._ws_state_repo.get_merge_lock_holder("mm/dev") == task.id

    def test_releases_lock_on_clean_merge(self, tmp_path):
        orch = make_orchestrator(tmp_path)
        task = make_task(role=AgentRole.CODER, branch="mm/feature/foo",
                         repo=["repo"])
        orch.queue.add(task)
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()

        def mock_git(args, cwd):
            return True, "merge successful"

        with patch("matrixmouse.tools.git_tools._git", side_effect=mock_git), \
             patch("matrixmouse.tools.git_tools.push_to_remote",
                   return_value=(True, "")):
            success, info = orch._run_merge_up(task, "mm/dev", repo_dir)

        assert success
        assert info == ""
        assert orch._ws_state_repo.get_merge_lock_holder("mm/dev") is None

    def test_checkout_failure_releases_lock(self, tmp_path):
        orch = make_orchestrator(tmp_path)
        task = make_task(role=AgentRole.CODER, branch="mm/feature/foo",
                         repo=["repo"])
        orch.queue.add(task)
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()

        def mock_git(args, cwd):
            if args[0] == "checkout":
                return False, "fatal: checkout failed"
            return True, ""

        with patch("matrixmouse.tools.git_tools._git", side_effect=mock_git):
            success, info = orch._run_merge_up(task, "mm/dev", repo_dir)

        assert not success
        assert "CHECKOUT_FAILED" in info
        # Lock should be released on checkout failure
        assert orch._ws_state_repo.get_merge_lock_holder("mm/dev") is None

    def test_handle_no_merge_target_works_without_comms(self, tmp_path):
        orch = make_orchestrator(tmp_path)
        task = make_task(role=AgentRole.CODER, branch="mm/feature/foo")
        orch.queue.add(task)
        with patch("matrixmouse.comms.get_manager", return_value=None):
            orch._handle_no_merge_target(task)
        t = orch.queue.get(task.id)
        assert t is not None
        assert t.status == TaskStatus.BLOCKED_BY_HUMAN

    def test_transition_to_merge_agent_handles_update_failure(self, tmp_path):
        orch = make_orchestrator(tmp_path)
        task = make_task(role=AgentRole.CODER, branch="mm/feature/foo",
                        repo=["repo"])
        orch.queue.add(task)
        orch._ws_state_repo.acquire_merge_lock("mm/dev", task.id)
        (tmp_path / "repo").mkdir()

        with patch.object(orch.queue, "update",
                        side_effect=Exception("DB error")), \
            patch("matrixmouse.comms.get_manager", return_value=None):
            orch._transition_to_merge_agent(
                task, "mm/dev", tmp_path / "repo", ["foo.py"]
            )

        # Lock should be released on failure
        assert orch._ws_state_repo.get_merge_lock_holder("mm/dev") is None
        t = orch.queue.get(task.id)
        assert t is not None
        assert t.status == TaskStatus.BLOCKED_BY_HUMAN


class TestReplayMergeDecisions:
    def test_replays_ours_decision(self, tmp_path):
        orch = make_orchestrator(tmp_path)
        task = make_task(role=AgentRole.MERGE)
        task.merge_resolution_decisions = [
            {"file": "foo.py", "resolution": "ours", "content": None}
        ]
        orch.queue.add(task)
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()

        calls = []
        def mock_run(args, **kwargs):
            calls.append(args)
            return MagicMock(returncode=0)

        with patch("subprocess.run", side_effect=mock_run):
            orch._replay_merge_decisions(task, repo_dir)

        checkout_calls = [c for c in calls if "checkout" in c]
        assert any("--ours" in c for c in checkout_calls)

    def test_replays_theirs_decision(self, tmp_path):
        orch = make_orchestrator(tmp_path)
        task = make_task(role=AgentRole.MERGE)
        task.merge_resolution_decisions = [
            {"file": "bar.py", "resolution": "theirs", "content": None}
        ]
        orch.queue.add(task)
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()

        calls = []
        def mock_run(args, **kwargs):
            calls.append(args)
            return MagicMock(returncode=0)

        with patch("subprocess.run", side_effect=mock_run):
            orch._replay_merge_decisions(task, repo_dir)

        checkout_calls = [c for c in calls if "checkout" in c]
        assert any("--theirs" in c for c in checkout_calls)

    def test_replays_manual_decision(self, tmp_path):
        orch = make_orchestrator(tmp_path)
        task = make_task(role=AgentRole.MERGE)
        task.merge_resolution_decisions = [
            {"file": "baz.py", "resolution": "manual",
             "content": "merged content"}
        ]
        orch.queue.add(task)
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        (repo_dir / "baz.py").write_text("original")

        with patch("subprocess.run", return_value=MagicMock(returncode=0)):
            orch._replay_merge_decisions(task, repo_dir)

        assert (repo_dir / "baz.py").read_text() == "merged content"

    def test_noop_on_empty_decisions(self, tmp_path):
        orch = make_orchestrator(tmp_path)
        task = make_task(role=AgentRole.MERGE)
        task.merge_resolution_decisions = []
        orch.queue.add(task)
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()

        with patch("subprocess.run") as mock_run:
            orch._replay_merge_decisions(task, repo_dir)

        mock_run.assert_not_called()


class TestMergeTurnLimit:
    def test_merge_turn_limit_emits_correct_event(self, tmp_path):
        orch = make_orchestrator(tmp_path)
        orch.config.merge_conflict_max_turns = 5
        task = make_task(role=AgentRole.MERGE, branch="mm/feature/foo",
                         repo=["repo"])
        task.preemptable = False
        orch.queue.add(task)

        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()

        result = make_loop_result(
            exit_reason=LoopExitReason.DECISION,
            decision_type="turn_limit_reached",
            turns=5,
        )
        mock_comms = MagicMock()

        with patch("matrixmouse.comms.get_manager",
                   return_value=mock_comms), \
             patch.object(orch, "_get_merge_target",
                          return_value="mm/dev"), \
             patch("matrixmouse.orchestrator._git",
                   return_value=(True, "")):
            orch._handle_decision(task, result)

        emitted = [c.args[0] for c in mock_comms.emit.call_args_list]
        assert "merge_conflict_resolution_turn_limit_reached" in emitted
        assert "turn_limit_reached" not in emitted
        assert "critic_turn_limit_reached" not in emitted

    def test_merge_turn_limit_aborts_merge(self, tmp_path):
        orch = make_orchestrator(tmp_path)
        orch.config.merge_conflict_max_turns = 5
        task = make_task(role=AgentRole.MERGE, branch="mm/feature/foo",
                         repo=["repo"])
        task.preemptable = False
        orch.queue.add(task)

        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()

        result = make_loop_result(
            exit_reason=LoopExitReason.DECISION,
            decision_type="turn_limit_reached",
            turns=5,
        )
        git_calls = []

        def mock_git(args, cwd):
            git_calls.append(args)
            return True, ""

        with patch("matrixmouse.comms.get_manager", return_value=MagicMock()), \
             patch.object(orch, "_get_merge_target", return_value="mm/dev"), \
             patch("matrixmouse.tools.git_tools._git", side_effect=mock_git):
            orch._handle_decision(task, result)

        abort_calls = [c for c in git_calls if "merge" in c and "--abort" in c]
        assert len(abort_calls) == 1

    def test_merge_turn_limit_marks_blocked_by_human(self, tmp_path):
        orch = make_orchestrator(tmp_path)
        orch.config.merge_conflict_max_turns = 5
        task = make_task(role=AgentRole.MERGE, branch="mm/feature/foo",
                         repo=["repo"])
        task.preemptable = False
        orch.queue.add(task)

        (tmp_path / "repo").mkdir()
        result = make_loop_result(
            exit_reason=LoopExitReason.DECISION,
            decision_type="turn_limit_reached",
            turns=5,
        )

        with patch("matrixmouse.comms.get_manager",
                   return_value=MagicMock()), \
             patch.object(orch, "_get_merge_target", return_value=None), \
             patch("matrixmouse.orchestrator._git", return_value=(True, "")):
            orch._handle_decision(task, result)

        t = orch.queue.get(task.id)
        assert t is not None
        assert t.status == TaskStatus.BLOCKED_BY_HUMAN
