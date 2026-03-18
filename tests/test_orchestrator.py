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
        - Original task blocked_by includes critic task id
        - Falls back to direct complete if critic task creation fails

    _load_or_build_messages:
        - Returns persisted messages when context_messages present
        - Calls agent.build_initial_messages for fresh task

    _scoring_kwargs:
        - Returns dict with config-backed values
        - Falls back to hardcoded defaults when config keys absent
"""

import time
from pathlib import Path
from unittest.mock import MagicMock, patch, call as mock_call

import pytest

from matrixmouse.orchestrator import Orchestrator
from matrixmouse.task import AgentRole, Task, TaskQueue, TaskStatus
from matrixmouse.loop import LoopResult, LoopExitReason


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
        **kwargs,
    )


def make_queue(tmp_path: Path) -> TaskQueue:
    tasks_file = tmp_path / "tasks.json"
    tasks_file.write_text("[]")
    return TaskQueue(tasks_file)


def make_config(**kwargs) -> MagicMock:
    cfg = MagicMock()
    cfg.priority_aging_rate        = kwargs.get("aging_rate",        0.01)
    cfg.priority_max_aging_bonus   = kwargs.get("max_aging_bonus",   0.3)
    cfg.priority_importance_weight = kwargs.get("importance_weight", 0.6)
    cfg.priority_urgency_weight    = kwargs.get("urgency_weight",    0.4)
    cfg.agent_max_turns            = kwargs.get("agent_max_turns",   50)
    cfg.manager_review_schedule    = kwargs.get("schedule",          "")
    cfg.clarification_timeout_minutes = kwargs.get("timeout_minutes", 60)
    return cfg


def make_paths(tmp_path: Path) -> MagicMock:
    paths = MagicMock()
    paths.workspace_root = tmp_path
    tasks_file = tmp_path / "tasks.json"
    tasks_file.write_text("[]")
    paths.tasks_file = tasks_file
    paths.workspace_state_file = tmp_path / "workspace_state.json"
    paths.agent_notes = tmp_path / "AGENT_NOTES.md"
    return paths


def make_orchestrator(tmp_path: Path, **config_kwargs) -> Orchestrator:
    config = make_config(**config_kwargs)
    paths  = make_paths(tmp_path)
    return Orchestrator(config=config, paths=paths)


def make_loop_result(
    exit_reason=LoopExitReason.COMPLETE,
    turns=5,
    summary="done",
    messages=None,
) -> LoopResult:
    return LoopResult(
        exit_reason=exit_reason,
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
        # Task's own preempt flag should not cause it to yield to itself
        assert orch._should_yield(task) is False

    def test_does_not_yield_when_preempting_task_not_ready(self, tmp_path):
        orch = make_orchestrator(tmp_path)
        running = make_task(title="running", status=TaskStatus.RUNNING)
        preempting = make_task(title="preempt",
                               status=TaskStatus.BLOCKED_BY_HUMAN)
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
            exit_reason=LoopExitReason.TURN_LIMIT_REACHED, turns=50
        )
        with patch("matrixmouse.comms.get_manager", return_value=None):
            orch._handle_turn_limit(task, result)
        updated_task = orch.queue.get(task.id)
        assert updated_task is not None
        assert updated_task.status == TaskStatus.BLOCKED_BY_HUMAN

    def test_emits_turn_limit_reached_event(self, tmp_path):
        orch = make_orchestrator(tmp_path)
        task = make_task()
        orch.queue.add(task)
        result = make_loop_result(
            exit_reason=LoopExitReason.TURN_LIMIT_REACHED, turns=50
        )
        mock_comms = MagicMock()
        with patch("matrixmouse.comms.get_manager", return_value=mock_comms):
            orch._handle_turn_limit(task, result)
        emitted_types = [c.args[0] for c in mock_comms.emit.call_args_list]
        assert "turn_limit_reached" in emitted_types

    def test_sends_ntfy_notification(self, tmp_path):
        orch = make_orchestrator(tmp_path)
        task = make_task(title="My stuck task")
        orch.queue.add(task)
        result = make_loop_result(
            exit_reason=LoopExitReason.TURN_LIMIT_REACHED, turns=50
        )
        mock_comms = MagicMock()
        with patch("matrixmouse.comms.get_manager", return_value=mock_comms):
            orch._handle_turn_limit(task, result)
        mock_comms.notify_blocked.assert_called_once()
        call_args = mock_comms.notify_blocked.call_args[0][0]
        assert "My stuck task" in call_args or task.id in call_args

    def test_event_contains_task_details(self, tmp_path):
        orch = make_orchestrator(tmp_path)
        task = make_task(role=AgentRole.CODER)
        orch.queue.add(task)
        result = make_loop_result(
            exit_reason=LoopExitReason.TURN_LIMIT_REACHED, turns=42
        )
        mock_comms = MagicMock()
        with patch("matrixmouse.comms.get_manager", return_value=mock_comms):
            orch._handle_turn_limit(task, result)
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
        # Should not raise, should not change task status
        # (approve/deny in task_tools already handled it)
        orch._handle_complete(task, result)
        # Status unchanged from READY — Critic task_tools marked it COMPLETE
        # already; orchestrator just logs
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
        all_tasks = orch.queue.all_tasks()
        critic_tasks = [t for t in all_tasks if t.role == AgentRole.CRITIC]
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
        assert len(updated.blocked_by) == 1


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
        updated = orch.queue.get(task.id)
        assert updated is not None
        assert critic.id in updated.blocked_by

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

    def test_falls_back_to_hardcoded_defaults(self, tmp_path):
        orch = make_orchestrator(tmp_path)
        # Remove the attributes from the mock so getattr fallback is used
        del orch.config.priority_aging_rate
        del orch.config.priority_max_aging_bonus
        del orch.config.priority_importance_weight
        del orch.config.priority_urgency_weight
        kwargs = orch._scoring_kwargs()
        assert kwargs["aging_rate"]        == 0.01
        assert kwargs["max_aging_bonus"]   == 0.3
        assert kwargs["importance_weight"] == 0.6
        assert kwargs["urgency_weight"]    == 0.4

# ---------------------------------------------------------------------------
# _maybe_inject_manager_review
# ---------------------------------------------------------------------------

class TestMaybeInjectManagerReview:
    def _make_orchestrator(self, tmp_path, schedule="0 9 * * *"):
        orch = make_orchestrator(tmp_path)
        orch.config.manager_review_schedule = schedule
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
        task = orch.queue.all_tasks()[0]
        assert task.preempt is True

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
        from datetime import datetime, timezone
        orch = self._make_orchestrator(tmp_path, schedule="0 9 * * *")
        # Set last review to now — next one not due for ~24 hours
        from matrixmouse import workspace_state as ws
        ws.set_last_review_at(orch._ws_state)
        orch._maybe_inject_manager_review()
        assert len(orch.queue.all_tasks()) == 0

    def test_injects_when_review_overdue(self, tmp_path):
        from datetime import datetime, timezone, timedelta
        orch = self._make_orchestrator(tmp_path, schedule="0 9 * * *")
        from matrixmouse import workspace_state as ws
        # Last review was 25 hours ago — definitely overdue
        old_dt = datetime.now(timezone.utc) - timedelta(hours=25)
        ws.set_last_review_at(orch._ws_state, old_dt)
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
            blocked.id,
            "Which algorithm should I use?",
            "2026-01-01T00:00:00+00:00",
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
        from matrixmouse import workspace_state as ws
        orch = self._make_orchestrator(tmp_path)
        blocked = make_task()
        blocked.status = TaskStatus.BLOCKED_BY_HUMAN
        orch.queue.add(blocked)

        orch._handle_stale_clarification(
            blocked.id, "Question?", "2026-01-01T00:00:00+00:00"
        )

        manager_task_id = ws.get_stale_clarification_task(
            orch._ws_state, blocked.id
        )
        assert manager_task_id is not None

    def test_no_duplicate_when_existing_manager_task_active(self, tmp_path):
        from matrixmouse import workspace_state as ws
        orch = self._make_orchestrator(tmp_path)
        blocked = make_task()
        blocked.status = TaskStatus.BLOCKED_BY_HUMAN
        orch.queue.add(blocked)

        # First call — creates Manager task
        orch._handle_stale_clarification(
            blocked.id, "Question?", "2026-01-01T00:00:00+00:00"
        )
        count_after_first = len([
            t for t in orch.queue.all_tasks()
            if t.role == AgentRole.MANAGER
        ])

        # Second call — should not create another
        orch._handle_stale_clarification(
            blocked.id, "Question?", "2026-01-01T00:00:00+00:00"
        )
        count_after_second = len([
            t for t in orch.queue.all_tasks()
            if t.role == AgentRole.MANAGER
        ])

        assert count_after_first == 1
        assert count_after_second == 1

    def test_creates_new_task_after_previous_completed(self, tmp_path):
        from matrixmouse import workspace_state as ws
        orch = self._make_orchestrator(tmp_path)
        blocked = make_task()
        blocked.status = TaskStatus.BLOCKED_BY_HUMAN
        orch.queue.add(blocked)

        # First call
        orch._handle_stale_clarification(
            blocked.id, "Question?", "2026-01-01T00:00:00+00:00"
        )

        # Mark the Manager task complete
        manager_task = next(
            t for t in orch.queue.all_tasks()
            if t.role == AgentRole.MANAGER
        )
        orch.queue.mark_complete(manager_task.id)

        # Second call — previous is terminal, should create a new one
        orch._handle_stale_clarification(
            blocked.id, "Question?", "2026-01-01T00:00:00+00:00"
        )

        manager_tasks = [
            t for t in orch.queue.all_tasks()
            if t.role == AgentRole.MANAGER
        ]
        assert len(manager_tasks) == 2

    def test_no_task_created_for_unknown_blocked_task(self, tmp_path):
        orch = self._make_orchestrator(tmp_path)
        orch._handle_stale_clarification(
            "nonexistent-task-id", "Question?", "2026-01-01T00:00:00+00:00"
        )
        assert len(orch.queue.all_tasks()) == 0

    def test_workspace_state_saved_to_disk(self, tmp_path):
        orch = self._make_orchestrator(tmp_path)
        blocked = make_task()
        blocked.status = TaskStatus.BLOCKED_BY_HUMAN
        orch.queue.add(blocked)

        state_file = tmp_path / "workspace_state.json"
        assert not state_file.exists()

        orch._handle_stale_clarification(
            blocked.id, "Question?", "2026-01-01T00:00:00+00:00"
        )

        assert state_file.exists()


# ---------------------------------------------------------------------------
# _on_manager_review_complete (additional coverage)
# ---------------------------------------------------------------------------

class TestOnManagerReviewCompleteOrchestrator:
    def test_last_review_at_set_in_memory(self, tmp_path):
        from matrixmouse import workspace_state as ws
        orch = make_orchestrator(tmp_path)
        task = make_task(role=AgentRole.MANAGER)
        orch._on_manager_review_complete(task, "Summary.")
        assert ws.get_last_review_at(orch._ws_state) is not None

    def test_summary_stored_in_ws_state(self, tmp_path):
        orch = make_orchestrator(tmp_path)
        task = make_task(role=AgentRole.MANAGER)
        orch._on_manager_review_complete(task, "Tasks are healthy.")
        assert orch._ws_state.get("last_review_summary") == "Tasks are healthy."

    def test_handles_empty_summary_gracefully(self, tmp_path):
        orch = make_orchestrator(tmp_path)
        task = make_task(role=AgentRole.MANAGER)
        orch._on_manager_review_complete(task, "")
        assert orch._ws_state.get("last_review_summary") == ""

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

        mock_review.assert_called_once_with(task, "Review done.")

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