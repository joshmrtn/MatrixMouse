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

from datetime import datetime, timezone, timedelta
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from matrixmouse.orchestrator import Orchestrator
from matrixmouse.task import AgentRole, Task, TaskStatus
from matrixmouse.loop import LoopResult, LoopExitReason
from matrixmouse.repository.memory_task_repository import InMemoryTaskRepository
from matrixmouse.repository.workspace_state_repository import WorkspaceStateRepository
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
    cfg.merge_conflict_max_turns      = kwargs.get("merge_conflict_max_turns", 5)
    cfg.default_merge_target          = kwargs.get("default_merge_target",     "")
    cfg.protected_branches            = kwargs.get("protected_branches",
                                                   ["main", "master", "develop", "release"])
    cfg.branch_protection_cache_ttl_minutes = kwargs.get(
        "branch_protection_cache_ttl_minutes", 60
    )
    cfg.pr_poll_interval_minutes      = kwargs.get("pr_poll_interval_minutes", 10)
    return cfg


def make_orchestrator(tmp_path: Path, **config_kwargs) -> Orchestrator:
    """Construct an Orchestrator with minimal real dependencies.

    The Router is patched out entirely — test_router.py covers routing logic.
    All other orchestrator logic runs against real in-memory repositories.
    """
    config        = make_config(**config_kwargs)
    paths         = MagicMock()
    paths.workspace_root = tmp_path
    paths.agent_notes    = tmp_path / "AGENT_NOTES.md"
    queue         = InMemoryTaskRepository()
    ws_state_repo = InMemoryWorkspaceStateRepository()

    mock_router = MagicMock()
    mock_router.model_for_role.return_value        = "ollama:test-model"
    mock_router.parsed_model_for_role.return_value = MagicMock(model="test-model")
    mock_router.backend_for_role.return_value      = MagicMock()
    mock_router.get_backend.return_value           = MagicMock()
    mock_router.cascade_for_role.return_value      = ["ollama:test-model"]
    mock_router.get_backend_for_model.return_value = MagicMock()
    mock_router.stream_for_role.return_value       = False
    mock_router.think_for_role.return_value        = False

    def _fake_parse(model_str):
        pm = MagicMock()
        pm.backend = "ollama"
        pm.model = "test-model"
        pm.is_remote = False
        return pm
    mock_router.parse_model_string = _fake_parse

    with patch("matrixmouse.orchestrator.Router", return_value=mock_router):
        orch = Orchestrator(
            config=config,
            paths=paths,
            queue=queue,
            ws_state_repo=ws_state_repo,
        )
    # Replace the router with our mock after construction too, in case
    # Orchestrator stores it as self._router
    orch._router = mock_router
    return orch


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


def make_run_result(
    exit_reason=LoopExitReason.COMPLETE,
    decision_type="",
    turns=5,
    summary="done",
    messages=None,
) -> "RunResult":
    """Create a RunResult for mocking _run_agent return value."""
    from matrixmouse.orchestrator import RunResult
    return RunResult(
        loop_result=make_loop_result(
            exit_reason=exit_reason,
            decision_type=decision_type,
            turns=turns,
            summary=summary,
            messages=messages,
        ),
        detector=MagicMock(),
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
        assert updated_task.last_review_summary == "All tasks look healthy."

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
        orch._maybe_inject_manager_review()
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
    def test_branch_setup_context_set_for_branchless_manager(self, tmp_path):
        from matrixmouse.repository.workspace_state_repository import SessionMode
        orch = make_orchestrator(tmp_path)
        task = make_task(role=AgentRole.MANAGER, branch="")
        orch.queue.add(task)

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
        orch = make_orchestrator(tmp_path)
        task = make_task(role=AgentRole.MANAGER, branch="mm/feature/foo")
        orch.queue.add(task)
        assert orch._ws_state_repo.get_session_context(task.id) is None

    def test_planning_context_cleared_on_complete(self, tmp_path):
        from matrixmouse.repository.workspace_state_repository import (
            SessionContext, SessionMode, PLANNING_TOOLS
        )
        orch = make_orchestrator(tmp_path)
        task = make_task(role=AgentRole.MANAGER, branch="mm/feature/foo")
        orch.queue.add(task)

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
        from matrixmouse.repository.workspace_state_repository import (
            SessionContext, SessionMode, PLANNING_TOOLS
        )
        orch = make_orchestrator(tmp_path)
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

        result = make_loop_result(summary="plan done")
        with patch("matrixmouse.comms.get_manager", return_value=None):
            orch._handle_complete(task, result)

        t = orch.queue.get(subtask.id)
        assert t is not None
        assert t.status == TaskStatus.READY

    def test_branch_setup_context_cleared_on_complete(self, tmp_path):
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

        t = orch.queue.get(subtask.id)
        assert t is not None
        assert t.status == TaskStatus.READY
        assert orch._ws_state_repo.get_session_context(task.id) is None
        emitted = [c.args[0] for c in mock_comms.emit.call_args_list]
        assert "planning_turn_limit_reached" in emitted
        assert "turn_limit_reached" not in emitted

    def test_coder_task_not_given_branch_setup_context(self, tmp_path):
        orch = make_orchestrator(tmp_path)
        task = make_task(role=AgentRole.CODER, branch="")
        orch.queue.add(task)
        assert orch._ws_state_repo.get_session_context(task.id) is None

    def test_branch_missing_triggers_human_intervention(self, tmp_path):
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
        orch = make_orchestrator(tmp_path)
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


# ---------------------------------------------------------------------------
# WIP commit wiring
# ---------------------------------------------------------------------------

class TestWipCommitWiring:
    def test_wip_commit_callable_called_after_dispatch(self, tmp_path):
        """wip_commit is called once per turn after tool dispatch."""
        from matrixmouse.loop import AgentLoop, LoopExitReason
        from matrixmouse.inference.base import LLMResponse, TextBlock, ToolUseBlock

        wip_calls = []

        def fake_wip():
            wip_calls.append(1)

        messages = [{"role": "system", "content": "prompt"}]
        backend = MagicMock()
        loop = AgentLoop(
            backend=backend,
            model="test",
            messages=messages,
            config=make_config(),
            paths=MagicMock(),
            wip_commit=fake_wip,
        )

        declare_block = ToolUseBlock(
            id="call_dc",
            name="declare_complete",
            input={"summary": "all done"},
        )
        fake_response = LLMResponse(
            content=[declare_block],
            input_tokens=10,
            output_tokens=5,
            model="test",
            stop_reason="tool_use",
        )
        backend.chat.return_value = fake_response

        result = loop.run()

        assert result.exit_reason == LoopExitReason.COMPLETE
        # WIP commit should NOT fire on declare_complete exit
        assert len(wip_calls) == 0

    def test_wip_commit_fires_after_normal_tool_call(self, tmp_path):
        """wip_commit fires after a non-exit tool call turn."""
        from matrixmouse.loop import AgentLoop, LoopExitReason
        from matrixmouse.inference.base import LLMResponse, TextBlock, ToolUseBlock
        from matrixmouse.inference.base import Tool
        from matrixmouse.tools import TOOL_REGISTRY

        wip_calls = []

        def fake_wip():
            wip_calls.append(1)

        messages = [{"role": "system", "content": "prompt"}]
        backend = MagicMock()
        loop = AgentLoop(
            backend=backend,
            model="test",
            messages=messages,
            config=make_config(),
            paths=MagicMock(),
            wip_commit=fake_wip,
        )

        status_block = ToolUseBlock(
            id="call_status",
            name="get_git_status",
            input={},
        )
        declare_block = ToolUseBlock(
            id="call_dc",
            name="declare_complete",
            input={"summary": "done"},
        )
        response1 = LLMResponse(
            content=[status_block],
            input_tokens=10, output_tokens=5,
            model="test", stop_reason="tool_use",
        )
        response2 = LLMResponse(
            content=[declare_block],
            input_tokens=10, output_tokens=5,
            model="test", stop_reason="tool_use",
        )
        backend.chat.side_effect = [response1, response2]

        fake_tool = Tool(
            fn=lambda: "clean",
            schema={"name": "get_git_status", "input_schema": {}},
        )
        with patch.dict(TOOL_REGISTRY, {"get_git_status": fake_tool}):
            result = loop.run()

        assert result.exit_reason == LoopExitReason.COMPLETE
        assert len(wip_calls) >= 1


# ---------------------------------------------------------------------------
# Merge-up tests
# ---------------------------------------------------------------------------

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
        orch._ws_state_repo.acquire_merge_lock("mm/dev", "other-task")

        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()

        success, info = orch._run_merge_up(task, "mm/dev", repo_dir)
        assert not success
        assert info == "QUEUED"
        assert orch._ws_state_repo.dequeue_next_merge_waiter("mm/dev") == task.id

    def test_returns_conflict_on_merge_conflict(self, tmp_path):
        orch = make_orchestrator(tmp_path)
        task = make_task(role=AgentRole.CODER, branch="mm/feature/foo",
                         repo=["repo"])
        orch.queue.add(task)
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()

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

        (tmp_path / "repo").mkdir()

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

        (tmp_path / "repo").mkdir()

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


# ---------------------------------------------------------------------------
# _maybe_promote_waiting_tasks
# ---------------------------------------------------------------------------

class TestMaybePromoteWaitingTasks:
    """Tests for Orchestrator._maybe_promote_waiting_tasks method."""

    def test_promotes_task_when_wait_until_passed(self, tmp_path):
        """_maybe_promote_waiting_tasks promotes task when wait_until passed."""
        orch = make_orchestrator(tmp_path)
        task = make_task(status=TaskStatus.WAITING)
        # Set wait_until in the past
        task.wait_until = (
            datetime.now(timezone.utc) - timedelta(minutes=5)
        ).isoformat()
        task.wait_reason = "budget:anthropic"
        orch.queue.add(task)
        
        promoted = orch._maybe_promote_waiting_tasks()
        
        assert promoted == 1
        updated = orch.queue.get(task.id)
        assert updated is not None
        assert updated.status == TaskStatus.READY
        assert updated.wait_until is None
        assert updated.wait_reason == ""

    def test_does_not_promote_when_wait_until_in_future(self, tmp_path):
        """_maybe_promote_waiting_tasks does not promote when wait_until in future."""
        orch = make_orchestrator(tmp_path)
        task = make_task(status=TaskStatus.WAITING)
        # Set wait_until in the future
        task.wait_until = (
            datetime.now(timezone.utc) + timedelta(minutes=30)
        ).isoformat()
        task.wait_reason = "budget:anthropic"
        orch.queue.add(task)
        
        promoted = orch._maybe_promote_waiting_tasks()
        
        assert promoted == 0
        updated = orch.queue.get(task.id)
        assert updated is not None
        assert updated.status == TaskStatus.WAITING
        assert updated.wait_until is not None
        assert updated.wait_reason == "budget:anthropic"

    def test_clears_wait_until_and_wait_reason_on_promotion(self, tmp_path):
        """_maybe_promote_waiting_tasks clears wait_until and wait_reason on promotion."""
        orch = make_orchestrator(tmp_path)
        task = make_task(status=TaskStatus.WAITING)
        task.wait_until = (
            datetime.now(timezone.utc) - timedelta(minutes=5)
        ).isoformat()
        task.wait_reason = "budget:anthropic"
        orch.queue.add(task)
        
        orch._maybe_promote_waiting_tasks()
        
        updated = orch.queue.get(task.id)
        assert updated is not None
        assert updated.wait_until is None
        assert updated.wait_reason == ""

    def test_promotes_task_with_none_wait_until_immediately(self, tmp_path):
        """_maybe_promote_waiting_tasks promotes task with None wait_until immediately."""
        orch = make_orchestrator(tmp_path)
        task = make_task(status=TaskStatus.WAITING)
        task.wait_until = None
        task.wait_reason = "budget:anthropic"
        orch.queue.add(task)
        
        promoted = orch._maybe_promote_waiting_tasks()
        
        assert promoted == 1
        updated = orch.queue.get(task.id)
        assert updated is not None
        assert updated.status == TaskStatus.READY
        assert updated.wait_until is None

    def test_handles_unparseable_wait_until_gracefully(self, tmp_path):
        """_maybe_promote_waiting_tasks handles unparseable wait_until gracefully."""
        orch = make_orchestrator(tmp_path)
        task = make_task(status=TaskStatus.WAITING)
        task.wait_until = "not-a-valid-iso-date"
        task.wait_reason = "budget:anthropic"
        orch.queue.add(task)
        
        promoted = orch._maybe_promote_waiting_tasks()
        
        assert promoted == 1
        updated = orch.queue.get(task.id)
        assert updated is not None
        assert updated.status == TaskStatus.READY
        assert updated.wait_until is None


# ---------------------------------------------------------------------------
# _handle_budget_exhausted
# ---------------------------------------------------------------------------

class TestHandleBudgetExhausted:
    """Tests for Orchestrator._handle_budget_exhausted method."""

    def test_sets_task_status_to_waiting(self, tmp_path):
        """_handle_budget_exhausted sets task status to WAITING."""
        from matrixmouse.inference.base import TokenBudgetExceededError
        
        orch = make_orchestrator(tmp_path)
        task = make_task()
        orch.queue.add(task)
        
        exc = TokenBudgetExceededError(
            provider="anthropic",
            period="hour",
            limit=100000,
            used=150000,
            retry_after=datetime.now(timezone.utc) + timedelta(minutes=30),
        )
        orch._handle_budget_exhausted(task, exc)
        
        updated = orch.queue.get(task.id)
        assert updated is not None
        assert updated.status == TaskStatus.WAITING

    def test_sets_wait_reason_to_budget_provider(self, tmp_path):
        """_handle_budget_exhausted sets wait_reason to "budget:<provider>"."""
        from matrixmouse.inference.base import TokenBudgetExceededError
        
        orch = make_orchestrator(tmp_path)
        task = make_task()
        orch.queue.add(task)
        
        exc = TokenBudgetExceededError(
            provider="anthropic",
            period="hour",
            limit=100000,
            used=150000,
            retry_after=datetime.now(timezone.utc) + timedelta(minutes=30),
        )
        orch._handle_budget_exhausted(task, exc)
        
        updated = orch.queue.get(task.id)
        assert updated is not None
        assert updated.wait_reason == "budget:anthropic"

    def test_sets_wait_until_from_exc_retry_after(self, tmp_path):
        """_handle_budget_exhausted sets wait_until from exc.retry_after."""
        from matrixmouse.inference.base import TokenBudgetExceededError
        
        orch = make_orchestrator(tmp_path)
        task = make_task()
        orch.queue.add(task)
        
        retry_dt = datetime.now(timezone.utc) + timedelta(minutes=30)
        exc = TokenBudgetExceededError(
            provider="anthropic",
            period="hour",
            limit=100000,
            used=150000,
            retry_after=retry_dt,
        )
        orch._handle_budget_exhausted(task, exc)
        
        updated = orch.queue.get(task.id)
        assert updated is not None
        assert updated.wait_until is not None
        # Should be the ISO format of the retry_after datetime
        assert updated.wait_until == retry_dt.isoformat()


# ---------------------------------------------------------------------------
# _mark_backend_exhausted / _get_and_clear_exhausted_backends
# ---------------------------------------------------------------------------

class TestBackendExhausted:
    """Tests for Orchestrator backend exhaustion tracking."""

    def test_mark_backend_exhausted_adds_to_set(self, tmp_path):
        """_mark_backend_exhausted adds to set."""
        orch = make_orchestrator(tmp_path)
        orch._mark_backend_exhausted("anthropic")
        
        with orch._exhausted_backends_lock:
            assert "anthropic" in orch._exhausted_backends

    def test_get_and_clear_exhausted_backends_returns_snapshot(self, tmp_path):
        """_get_and_clear_exhausted_backends returns snapshot and clears set."""
        orch = make_orchestrator(tmp_path)
        orch._mark_backend_exhausted("anthropic")
        orch._mark_backend_exhausted("openai")
        
        result = orch._get_and_clear_exhausted_backends()
        
        assert result == {"anthropic", "openai"}
        with orch._exhausted_backends_lock:
            assert len(orch._exhausted_backends) == 0

    def test_concurrent_mark_backend_exhausted_calls_are_safe(self, tmp_path):
        """Concurrent _mark_backend_exhausted calls are safe (no data loss)."""
        import threading
        orch = make_orchestrator(tmp_path)
        
        def mark_backend(backend: str):
            orch._mark_backend_exhausted(backend)
        
        threads = []
        backends = ["anthropic", "openai", "google", "azure"]
        for backend in backends:
            t = threading.Thread(target=mark_backend, args=(backend,))
            threads.append(t)
            t.start()
        
        for t in threads:
            t.join()
        
        result = orch._get_and_clear_exhausted_backends()
        # All backends should be recorded
        assert result == set(backends)


# ---------------------------------------------------------------------------
# TaskRunContext tests (Phase 3 — #18 TreeSitter Integration)
# ---------------------------------------------------------------------------


class TestTaskRunContext:
    """Tests for TaskRunContext dataclass and per-task graph construction."""

    @pytest.fixture(autouse=True)
    def ensure_python_extractor_registered(self) -> None:
        """Ensure PythonExtractor is registered for these tests."""
        from matrixmouse.codemap._registry import register_extractor, _registry
        from matrixmouse.codemap.extractors.python import PythonExtractor
        
        # Register PythonExtractor if not already registered
        if ".py" not in _registry:
            register_extractor(PythonExtractor())

    def test_task_run_context_has_graph_field(self, tmp_path: Path) -> None:
        """TaskRunContext has task and graph fields."""
        from matrixmouse.orchestrator import TaskRunContext
        from matrixmouse.codemap import ProjectAnalyzer
        from matrixmouse.task import Task, AgentRole

        task = Task(
            title="Test task",
            description="Test description",
            role=AgentRole.CODER,
        )
        graph = ProjectAnalyzer()
        ctx = TaskRunContext(task=task, graph=graph)

        assert ctx.task is task
        assert ctx.graph is graph
        assert isinstance(ctx.graph, ProjectAnalyzer)

    def test_run_task_creates_task_run_context_with_graph(
        self, tmp_path: Path
    ) -> None:
        """
        _run_task() constructs a TaskRunContext with a non-None graph field
        when repo exists.
        """
        from matrixmouse.orchestrator import TaskRunContext
        from matrixmouse.task import Task, AgentRole, TaskStatus
        from matrixmouse.codemap import ProjectAnalyzer

        # Create a minimal repo structure
        repo_root = tmp_path / "test-repo"
        repo_root.mkdir()
        (repo_root / "test.py").write_text("def foo(): pass\n")

        orch = make_orchestrator(tmp_path)
        orch.paths.workspace_root = tmp_path

        task = Task(
            title="Test",
            description="Test",
            role=AgentRole.CODER,
            repo=["test-repo"],
            branch="main",
        )
        orch.queue.add(task)

        # Mock _run_agent to capture the ctx
        captured_ctx = None

        def mock_run_agent(ctx, agent, messages, model=None):
            nonlocal captured_ctx
            captured_ctx = ctx
            return make_run_result(LoopExitReason.COMPLETE, summary="done")

        with patch.object(orch, "_run_agent", side_effect=mock_run_agent):
            with patch("matrixmouse.orchestrator.agent_for_role"):
                with patch("matrixmouse.orchestrator.ensure_branch_from_mirror", return_value=(True, "")):
                    with patch("matrixmouse.orchestrator._git", return_value=(True, "")):
                        orch._run_task(task)

        assert captured_ctx is not None
        assert isinstance(captured_ctx, TaskRunContext)
        assert captured_ctx.task is task
        assert captured_ctx.graph is not None
        assert isinstance(captured_ctx.graph, ProjectAnalyzer)

    def test_sequential_task_runs_produce_independent_graphs(
        self, tmp_path: Path
    ) -> None:
        """
        Two sequential task runs produce independent ProjectAnalyzer instances
        (not the same object).
        """
        from matrixmouse.orchestrator import TaskRunContext
        from matrixmouse.task import Task, AgentRole, TaskStatus
        from matrixmouse.codemap import ProjectAnalyzer

        # Create two separate repo structures
        repo1 = tmp_path / "repo1"
        repo1.mkdir()
        (repo1 / "file1.py").write_text("def func1(): pass\n")

        repo2 = tmp_path / "repo2"
        repo2.mkdir()
        (repo2 / "file2.py").write_text("def func2(): pass\n")

        orch = make_orchestrator(tmp_path)
        orch.paths.workspace_root = tmp_path

        task1 = Task(
            title="Task 1",
            description="Test 1",
            role=AgentRole.CODER,
            repo=["repo1"],
            branch="main",
        )
        task2 = Task(
            title="Task 2",
            description="Test 2",
            role=AgentRole.CODER,
            repo=["repo2"],
            branch="main",
        )
        orch.queue.add(task1)
        orch.queue.add(task2)

        captured_graphs = []

        def mock_run_agent(ctx, agent, messages, model=None):
            captured_graphs.append(ctx.graph)
            return make_run_result(LoopExitReason.COMPLETE, summary="done")

        with patch.object(orch, "_run_agent", side_effect=mock_run_agent):
            with patch("matrixmouse.orchestrator.agent_for_role"):
                with patch("matrixmouse.orchestrator.ensure_branch_from_mirror", return_value=(True, "")):
                    with patch("matrixmouse.orchestrator._git", return_value=(True, "")):
                        orch._run_task(task1)
                        orch._run_task(task2)

        assert len(captured_graphs) == 2
        assert captured_graphs[0] is not captured_graphs[1]
        assert isinstance(captured_graphs[0], ProjectAnalyzer)
        assert isinstance(captured_graphs[1], ProjectAnalyzer)

        # Each graph should have different functions
        assert "func1" in captured_graphs[0].functions
        assert "func2" not in captured_graphs[0].functions
        assert "func2" in captured_graphs[1].functions
        assert "func1" not in captured_graphs[1].functions

    def test_run_task_handles_missing_repo_gracefully(
        self, tmp_path: Path
    ) -> None:
        """
        _run_task() creates TaskRunContext with None graph when repo doesn't exist.
        """
        from matrixmouse.orchestrator import TaskRunContext
        from matrixmouse.task import Task, AgentRole

        orch = make_orchestrator(tmp_path)
        orch.paths.workspace_root = tmp_path

        task = Task(
            title="Test",
            description="Test",
            role=AgentRole.CODER,
            repo=["nonexistent-repo"],
            branch="main",
        )
        orch.queue.add(task)

        captured_ctx = None

        def mock_run_agent(ctx, agent, messages, model=None):
            nonlocal captured_ctx
            captured_ctx = ctx
            return make_run_result(LoopExitReason.COMPLETE, summary="done")

        with patch.object(orch, "_run_agent", side_effect=mock_run_agent):
            with patch("matrixmouse.orchestrator.agent_for_role"):
                # No branch checkout needed for nonexistent repo
                orch._run_task(task)

        assert captured_ctx is not None
        assert isinstance(captured_ctx, TaskRunContext)
        assert captured_ctx.graph is None


# ---------------------------------------------------------------------------
# Phase 3B — Cascade resolution (Issue #32)
# ---------------------------------------------------------------------------

class TestResolveModelForTask:
    """Tests for Orchestrator._resolve_model_for_task()."""

    def _make_orch_for_resolve(self, tmp_path):
        """Create orchestrator with real-ish cascade resolution."""
        from matrixmouse.repository.memory_workspace_state_repository import (
            InMemoryWorkspaceStateRepository,
        )
        from matrixmouse.inference.availability import BackendAvailabilityCache

        config = make_config()
        config.coder_cascade = ["ollama:coder1", "ollama:coder2"]
        config.manager_cascade = ["ollama:manager1"]
        config.writer_cascade = ["ollama:writer1"]
        config.critic_cascade = ["ollama:critic1"]
        config.merge_resolution_cascade = ["ollama:merge1"]
        config.summarizer_cascade = ["ollama:summarizer1"]

        paths = MagicMock()
        paths.workspace_root = tmp_path

        queue = InMemoryTaskRepository()
        ws_state_repo = InMemoryWorkspaceStateRepository()

        mock_router = MagicMock()
        mock_router.cascade_for_role.return_value = ["ollama:coder1", "ollama:coder2"]

        mock_router.stream_for_role.return_value = False
        mock_router.think_for_role.return_value = False

        # parse_model_string mock
        def fake_parse(model_str):
            pm = MagicMock()
            pm.backend = model_str.split(":")[0] if ":" in model_str else "ollama"
            pm.model = model_str.split(":")[-1]
            pm.is_remote = pm.backend in ("anthropic", "openai")
            return pm

        mock_router.get_backend_for_model.return_value = MagicMock()

        with patch("matrixmouse.orchestrator.Router", return_value=mock_router):
            orch = Orchestrator(
                config=config,
                paths=paths,
                queue=queue,
                ws_state_repo=ws_state_repo,
            )
        orch._router = mock_router
        orch._router.parse_model_string = fake_parse
        return orch, mock_router

    def test_resolve_model_picks_first_available(self):
        """Cascade [A, B, C], all pass → A."""
        tmp = Path("/tmp/test_orch_3b_1")
        tmp.mkdir(exist_ok=True)
        orch, mock_router = self._make_orch_for_resolve(tmp)

        def fake_parse(model_str):
            pm = MagicMock()
            pm.backend = "ollama"
            pm.model = model_str.split(":")[-1]
            pm.is_remote = False
            return pm

        mock_router.parse_model_string = fake_parse

        result = orch._resolve_model_for_task(
            make_task(role=AgentRole.CODER, repo=["repo"])
        )
        assert result == "ollama:coder1"

    def test_resolve_model_skips_budget_exhausted_remote(self):
        """A raises TokenBudgetExceededError in check_budget → B."""
        tmp = Path("/tmp/test_orch_3b_2")
        tmp.mkdir(exist_ok=True)
        orch, mock_router = self._make_orch_for_resolve(tmp)

        from matrixmouse.inference.base import TokenBudgetExceededError
        from matrixmouse.inference.token_budget import TokenBudgetTracker

        # Set up a budget tracker that blocks the first model
        mock_tracker = MagicMock()
        def check_budget_fn(provider, model):
            if provider == "anthropic" and model == "claude-1":
                raise TokenBudgetExceededError(
                    provider="anthropic", period="hour",
                    limit=100, used=101,
                )
        mock_tracker.check_budget.side_effect = check_budget_fn
        orch._budget_tracker = mock_tracker

        mock_router.cascade_for_role.return_value = [
            "anthropic:claude-1", "anthropic:claude-2"
        ]

        def fake_parse(model_str):
            pm = MagicMock()
            pm.backend = "anthropic"
            pm.model = model_str.split(":")[-1]
            pm.is_remote = True
            return pm

        mock_router.parse_model_string = fake_parse

        result = orch._resolve_model_for_task(
            make_task(role=AgentRole.CODER, repo=["repo"])
        )
        assert result == "anthropic:claude-2"

    def test_resolve_model_skips_cooldown_backend(self):
        """A's backend in cooldown → B (different backend)."""
        tmp = Path("/tmp/test_orch_3b_3")
        tmp.mkdir(exist_ok=True)
        from matrixmouse.repository.memory_workspace_state_repository import (
            InMemoryWorkspaceStateRepository,
        )
        from matrixmouse.inference.availability import BackendAvailabilityCache

        orch, mock_router = self._make_orch_for_resolve(tmp)

        ws_state_repo = InMemoryWorkspaceStateRepository()
        cache = BackendAvailabilityCache(ws_state_repo)
        cache.record_failure("anthropic")
        orch._availability_cache = cache

        mock_router.cascade_for_role.return_value = [
            "anthropic:claude-1", "openai:gpt-4o"
        ]

        def fake_parse(model_str):
            pm = MagicMock()
            parts = model_str.split(":")
            pm.backend = parts[0]
            pm.model = parts[-1]
            pm.is_remote = True
            return pm

        mock_router.parse_model_string = fake_parse
        # No budget tracker → budget check skipped
        orch._budget_tracker = None

        result = orch._resolve_model_for_task(
            make_task(role=AgentRole.CODER, repo=["repo"])
        )
        assert result == "openai:gpt-4o"

    def test_resolve_model_local_backend_skips_budget_check(self):
        """Local backend is not passed to check_budget even when
        budget_tracker is set; confirm via mock."""
        tmp = Path("/tmp/test_orch_3b_4")
        tmp.mkdir(exist_ok=True)
        orch, mock_router = self._make_orch_for_resolve(tmp)

        mock_tracker = MagicMock()
        orch._budget_tracker = mock_tracker

        mock_router.cascade_for_role.return_value = ["ollama:coder1"]

        def fake_parse(model_str):
            pm = MagicMock()
            pm.backend = "ollama"
            pm.model = model_str.split(":")[-1]
            pm.is_remote = False
            return pm

        mock_router.parse_model_string = fake_parse

        orch._resolve_model_for_task(
            make_task(role=AgentRole.CODER, repo=["repo"])
        )

        # Budget tracker should NOT be called for local backends
        mock_tracker.check_budget.assert_not_called()

    def test_resolve_model_all_exhausted_returns_none(self):
        """All fail → None."""
        tmp = Path("/tmp/test_orch_3b_5")
        tmp.mkdir(exist_ok=True)
        from matrixmouse.repository.memory_workspace_state_repository import (
            InMemoryWorkspaceStateRepository,
        )
        from matrixmouse.inference.availability import BackendAvailabilityCache

        orch, mock_router = self._make_orch_for_resolve(tmp)

        ws_state_repo = InMemoryWorkspaceStateRepository()
        cache = BackendAvailabilityCache(ws_state_repo)
        cache.record_failure("anthropic")
        orch._availability_cache = cache
        orch._budget_tracker = None

        mock_router.cascade_for_role.return_value = ["anthropic:claude-1"]

        def fake_parse(model_str):
            pm = MagicMock()
            pm.backend = "anthropic"
            pm.model = model_str.split(":")[-1]
            pm.is_remote = True
            return pm

        mock_router.parse_model_string = fake_parse

        result = orch._resolve_model_for_task(
            make_task(role=AgentRole.CODER, repo=["repo"])
        )
        assert result is None

    def test_resolve_model_single_entry_cascade_passes(self):
        """Single entry cascade, available → returns it."""
        tmp = Path("/tmp/test_orch_3b_6")
        tmp.mkdir(exist_ok=True)
        orch, mock_router = self._make_orch_for_resolve(tmp)

        mock_router.cascade_for_role.return_value = ["ollama:only-model"]
        orch._budget_tracker = None
        orch._availability_cache = None

        def fake_parse(model_str):
            pm = MagicMock()
            pm.backend = "ollama"
            pm.model = model_str.split(":")[-1]
            pm.is_remote = False
            return pm

        mock_router.parse_model_string = fake_parse

        result = orch._resolve_model_for_task(
            make_task(role=AgentRole.CODER, repo=["repo"])
        )
        assert result == "ollama:only-model"

    def test_resolve_model_single_entry_cascade_fails_returns_none(self):
        """Single entry cascade, backend in cooldown → None."""
        tmp = Path("/tmp/test_orch_3b_7")
        tmp.mkdir(exist_ok=True)
        from matrixmouse.repository.memory_workspace_state_repository import (
            InMemoryWorkspaceStateRepository,
        )
        from matrixmouse.inference.availability import BackendAvailabilityCache

        orch, mock_router = self._make_orch_for_resolve(tmp)

        ws_state_repo = InMemoryWorkspaceStateRepository()
        cache = BackendAvailabilityCache(ws_state_repo)
        cache.record_failure("ollama")
        orch._availability_cache = cache
        orch._budget_tracker = None

        mock_router.cascade_for_role.return_value = ["ollama:only-model"]

        def fake_parse(model_str):
            pm = MagicMock()
            pm.backend = "ollama"
            pm.model = model_str.split(":")[-1]
            pm.is_remote = False
            return pm

        mock_router.parse_model_string = fake_parse

        result = orch._resolve_model_for_task(
            make_task(role=AgentRole.CODER, repo=["repo"])
        )
        assert result is None
        