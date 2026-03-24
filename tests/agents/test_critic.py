"""
tests/agents/test_critic.py

Tests for CriticAgent — prompt structure, approve/deny tool flows,
and turn limit escalation routing.

Prompt tests check structure and behavioural contracts only —
no keyword matching on prompt wording.

Coverage:
    build_system_prompt:
        - Returns non-empty string
        - Mentions approve and deny tools by name
        - Mentions critic_max_turns or a turn limit concept
        - Does not include shared constraints (Critic overrides to empty)

    approve flow (via task_tools):
        - Original task marked COMPLETE
        - Critic task marked COMPLETE
        - Critic task removed from original task blocked_by
        - Returns OK string

    deny flow (via task_tools):
        - Original task returned to READY
        - Feedback appended to original task context_messages
        - Critic task marked COMPLETE
        - Returns OK string
        - Empty feedback returns ERROR

    turn limit escalation:
        - Critic hitting turn limit emits critic_turn_limit_reached event
        - Event contains three choices: approve_task, extend_critic, block_task
        - Event contains reviewed_task_id
        - Critic task moved to BLOCKED_BY_HUMAN on turn limit
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch


from matrixmouse.agents.critic import CriticAgent
from matrixmouse.task import AgentRole, Task, TaskStatus
from matrixmouse.repository.memory_task_repository import InMemoryTaskRepository
from matrixmouse.repository.workspace_state_repository import WorkspaceStateRepository
from matrixmouse.repository.memory_workspace_state_repository import (
    InMemoryWorkspaceStateRepository,
)
from matrixmouse.tools import task_tools
from matrixmouse.loop import LoopExitReason, LoopResult


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


def make_critic_task(reviewed_id: str) -> Task:
    task = make_task(
        title=f"[Critic Review] reviewed task",
        role=AgentRole.CRITIC,
    )
    task.reviews_task_id = reviewed_id
    return task


def make_repo() -> InMemoryTaskRepository:
    return InMemoryTaskRepository()


def setup_critic_review():
    """Set up a standard Critic reviewing a Coder task."""
    reviewed = make_task(title="reviewed task", role=AgentRole.CODER)
    critic = make_critic_task(reviewed.id)

    q = make_repo()
    q.add(reviewed)
    q.add(critic)
    q.add_dependency(critic.id, reviewed.id)
    task_tools.configure(queue=q, active_task_id=critic.id, config=MagicMock())
    return q, reviewed, critic

# ---------------------------------------------------------------------------
# build_system_prompt
# ---------------------------------------------------------------------------

class TestCriticBuildSystemPrompt:
    def test_returns_non_empty_string(self):
        agent = CriticAgent()
        task = make_task(role=AgentRole.CRITIC)
        assert len(agent.build_system_prompt(task)) > 100

    def test_mentions_approve_tool(self):
        agent = CriticAgent()
        prompt = agent.build_system_prompt(make_task(role=AgentRole.CRITIC))
        assert "approve" in prompt.lower()

    def test_mentions_deny_tool(self):
        agent = CriticAgent()
        prompt = agent.build_system_prompt(make_task(role=AgentRole.CRITIC))
        assert "deny" in prompt.lower()

    def test_shared_constraints_empty(self):
        agent = CriticAgent()
        assert agent._shared_constraints() == ""

    def test_prompt_does_not_include_declare_complete(self):
        agent = CriticAgent()
        prompt = agent.build_system_prompt(make_task(role=AgentRole.CRITIC))
        # Critic must not use declare_complete — only approve/deny
        assert "declare_complete" not in prompt


# ---------------------------------------------------------------------------
# approve flow
# ---------------------------------------------------------------------------

class TestApproveFlow:
    def test_approve_marks_reviewed_task_complete(self):
        q, reviewed, critic = setup_critic_review()
        task_tools.approve()
        result = q.get(reviewed.id)
        assert result is not None
        assert result.status == TaskStatus.COMPLETE

    def test_approve_marks_critic_task_complete(self):
        q, reviewed, critic = setup_critic_review()
        task_tools.approve()
        result= q.get(critic.id)
        assert result is not None
        assert result.status == TaskStatus.COMPLETE

    def test_approve_removes_critic_from_blocked_by(self):
        q, reviewed, critic = setup_critic_review()
        task_tools.approve()
        assert not q.has_blockers(reviewed.id)

    def test_approve_returns_ok(self):
        q, reviewed, critic = setup_critic_review()
        result = task_tools.approve()
        assert "OK" in result

    def test_approve_error_when_no_active_task(self):
        q = make_repo()
        task_tools.configure(queue=q, active_task_id=None, config=MagicMock())
        assert "ERROR" in task_tools.approve()

    def test_approve_error_when_no_reviews_task_id(self):
        task = make_task(role=AgentRole.CRITIC)
        q = make_repo()
        q.add(task)
        task_tools.configure(queue=q, active_task_id=task.id, config=MagicMock())
        assert "ERROR" in task_tools.approve()


# ---------------------------------------------------------------------------
# deny flow
# ---------------------------------------------------------------------------

class TestDenyFlow:
    def test_deny_returns_reviewed_task_to_ready(self):
        q, reviewed, critic = setup_critic_review()
        task_tools.deny("Missing error handling.")
        result = q.get(reviewed.id)
        assert result is not None
        assert result.status == TaskStatus.READY

    def test_deny_appends_feedback_to_context_messages(self):
        q, reviewed, critic = setup_critic_review()
        task_tools.deny("The tests were deleted.")
        result = q.get(reviewed.id)
        assert result is not None
        messages = result.context_messages
        assert any(
            "The tests were deleted." in m.get("content", "")
            for m in messages
        )

    def test_deny_marks_critic_task_complete(self):
        q, reviewed, critic = setup_critic_review()
        task_tools.deny("Needs more work.")
        result = q.get(critic.id)
        assert result is not None
        assert result.status == TaskStatus.COMPLETE

    def test_deny_returns_ok(self):
        q, reviewed, critic = setup_critic_review()
        assert "OK" in task_tools.deny("Feedback here.")

    def test_deny_empty_feedback_returns_error(self):
        q, reviewed, critic = setup_critic_review()
        assert "ERROR" in task_tools.deny("")

    def test_deny_whitespace_feedback_returns_error(self):
        q, reviewed, critic = setup_critic_review()
        assert "ERROR" in task_tools.deny("   ")

    def test_deny_error_when_no_active_task(self):
        q = make_repo()
        task_tools.configure(queue=q, active_task_id=None, config=MagicMock())
        assert "ERROR" in task_tools.deny("feedback")


# ---------------------------------------------------------------------------
# Turn limit escalation
# ---------------------------------------------------------------------------

class TestCriticTurnLimitEscalation:
    def _make_orchestrator(self, tmp_path):
        from matrixmouse.orchestrator import Orchestrator

        cfg = MagicMock()
        cfg.manager_review_schedule = ""
        cfg.agent_max_turns = 50
        cfg.critic_max_turns = 5
        cfg.priority_aging_rate = 0.01
        cfg.priority_max_aging_bonus = 0.3
        cfg.priority_importance_weight = 0.6
        cfg.priority_urgency_weight = 0.4

        paths = MagicMock()
        paths.workspace_root = tmp_path
        paths.agent_notes = tmp_path / "AGENT_NOTES.md"

        return Orchestrator(
            config=cfg,
            paths=paths,
            queue=InMemoryTaskRepository(),
            ws_state_repo=InMemoryWorkspaceStateRepository(),
        )

    def test_critic_task_blocked_on_turn_limit(self, tmp_path):
        orch = self._make_orchestrator(tmp_path)
        reviewed = make_task(role=AgentRole.CODER)
        critic = make_critic_task(reviewed.id)
        orch.queue.add(reviewed)
        orch.queue.add(critic)

        result = LoopResult(
            exit_reason=LoopExitReason.TURN_LIMIT_REACHED,
            messages=[],
            turns_taken=5,
        )
        with patch("matrixmouse.comms.get_manager", return_value=None):
            orch._handle_turn_limit(critic, result)

        crit_result = orch.queue.get(critic.id)
        assert crit_result is not None
        assert crit_result.status == TaskStatus.BLOCKED_BY_HUMAN

    def test_critic_turn_limit_emits_critic_specific_event(self, tmp_path):
        orch = self._make_orchestrator(tmp_path)
        reviewed = make_task(role=AgentRole.CODER)
        critic = make_critic_task(reviewed.id)
        orch.queue.add(reviewed)
        orch.queue.add(critic)

        result = LoopResult(
            exit_reason=LoopExitReason.TURN_LIMIT_REACHED,
            messages=[],
            turns_taken=5,
        )
        mock_comms = MagicMock()
        with patch("matrixmouse.comms.get_manager", return_value=mock_comms):
            orch._handle_turn_limit(critic, result)

        emitted_types = [c.args[0] for c in mock_comms.emit.call_args_list]
        assert "critic_turn_limit_reached" in emitted_types
        assert "turn_limit_reached" not in emitted_types

    def test_critic_turn_limit_event_has_three_choices(self, tmp_path):
        orch = self._make_orchestrator(tmp_path)
        reviewed = make_task(role=AgentRole.CODER)
        critic = make_critic_task(reviewed.id)
        orch.queue.add(reviewed)
        orch.queue.add(critic)

        result = LoopResult(
            exit_reason=LoopExitReason.TURN_LIMIT_REACHED,
            messages=[],
            turns_taken=5,
        )
        mock_comms = MagicMock()
        with patch("matrixmouse.comms.get_manager", return_value=mock_comms):
            orch._handle_turn_limit(critic, result)

        event_data = next(
            c.args[1] for c in mock_comms.emit.call_args_list
            if c.args[0] == "critic_turn_limit_reached"
        )
        choices = event_data["choices"]
        assert len(choices) == 3
        choice_values = {c["value"] for c in choices}
        assert choice_values == {"approve_task", "extend_critic", "block_task"}

    def test_critic_turn_limit_event_contains_reviewed_task_id(self, tmp_path):
        orch = self._make_orchestrator(tmp_path)
        reviewed = make_task(role=AgentRole.CODER)
        critic = make_critic_task(reviewed.id)
        orch.queue.add(reviewed)
        orch.queue.add(critic)

        result = LoopResult(
            exit_reason=LoopExitReason.TURN_LIMIT_REACHED,
            messages=[],
            turns_taken=5,
        )
        mock_comms = MagicMock()
        with patch("matrixmouse.comms.get_manager", return_value=mock_comms):
            orch._handle_turn_limit(critic, result)

        event_data = next(
            c.args[1] for c in mock_comms.emit.call_args_list
            if c.args[0] == "critic_turn_limit_reached"
        )
        assert event_data["reviewed_task_id"] == reviewed.id

    def test_non_critic_turn_limit_emits_standard_event(self, tmp_path):
        orch = self._make_orchestrator(tmp_path)
        task = make_task(role=AgentRole.CODER)
        orch.queue.add(task)

        result = LoopResult(
            exit_reason=LoopExitReason.TURN_LIMIT_REACHED,
            messages=[],
            turns_taken=50,
        )
        mock_comms = MagicMock()
        with patch("matrixmouse.comms.get_manager", return_value=mock_comms):
            orch._handle_turn_limit(task, result)

        emitted_types = [c.args[0] for c in mock_comms.emit.call_args_list]
        assert "turn_limit_reached" in emitted_types
        assert "critic_turn_limit_reached" not in emitted_types
        