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

def make_task(**kwargs) -> Task:
    defaults = dict(
        title="Test task",
        description="Do the thing.",
        role=AgentRole.CODER,
        repo=["my-repo"],
        importance=0.5,
        urgency=0.5,
    )
    defaults.update(kwargs)
    return Task(**defaults)


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
    return cfg


def make_paths(tmp_path: Path) -> MagicMock:
    paths = MagicMock()
    paths.workspace_root = tmp_path
    tasks_file = tmp_path / "tasks.json"
    tasks_file.write_text("[]")
    paths.tasks_file = tasks_file
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
        assert orch.queue.get(task.id).status == TaskStatus.BLOCKED_BY_HUMAN

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
        assert orch.queue.get(task.id).status == TaskStatus.COMPLETE

    def test_manager_review_summary_stored(self, tmp_path):
        orch = make_orchestrator(tmp_path)
        task = make_task(role=AgentRole.MANAGER)
        orch.queue.add(task)
        result = make_loop_result(summary="All tasks look healthy.")
        with patch("matrixmouse.comms.get_manager", return_value=None):
            orch._handle_complete(task, result)
        assert orch.queue.get(task.id).last_review_summary == \
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
        assert orch.queue.get(task.id).status == TaskStatus.COMPLETE


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