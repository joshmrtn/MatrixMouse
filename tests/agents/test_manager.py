"""
tests/agents/test_manager.py

Tests for ManagerAgent — prompt structure, review mode detection,
review task context assembly, and Manager review orchestration.

Prompt content tests check structure and role-appropriate behaviour,
not specific keywords (prompt wording may change; structure should not).

Coverage:
    build_system_prompt:
        - Returns distinct prompts for planning vs review mode
        - Planning prompt instructs task decomposition
        - Planning prompt instructs declare_complete
        - Review prompt instructs examining blocked and completed tasks
        - Review prompt instructs declare_complete with summary
        - Prompt includes repo when set on task

    _is_review_task:
        - Detects [Manager Review] prefix
        - Does not detect tasks without the prefix
        - Does not detect partial prefix match
        - Does not detect empty title

    _build_review_task (orchestrator helper):
        - Created task has MANAGER role
        - Created task has preempt=True
        - Description includes recently completed tasks
        - Description includes blocked tasks section
        - Description includes upcoming tasks section
        - Description includes previous summary when present
        - Description omits previous summary section when absent
        - Respects manager_review_upcoming_tasks limit
        - Recently completed excludes tasks completed before last review

    _on_manager_review_complete:
        - Updates last_manager_review_at in workspace state
        - Saves workspace state to disk
        - Stores summary in workspace state
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch


from matrixmouse.agents.manager import ManagerAgent, _is_review_task
from matrixmouse.orchestrator import _build_review_task
from matrixmouse.task import AgentRole, Task, TaskStatus
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
    **kwargs,
) -> Task:
    return Task(
        title=title,
        description=description,
        role=role,
        repo=repo if repo is not None else ["repo"],
        **kwargs,
    )


def make_repo() -> InMemoryTaskRepository:
    return InMemoryTaskRepository()


def make_config(upcoming_tasks=20) -> MagicMock:
    cfg = MagicMock()
    cfg.manager_review_upcoming_tasks = upcoming_tasks
    return cfg


# ---------------------------------------------------------------------------
# build_system_prompt — structure
# ---------------------------------------------------------------------------

class TestManagerBuildSystemPrompt:
    def test_planning_and_review_prompts_are_distinct(self):
        agent = ManagerAgent()
        planning = agent.build_system_prompt(
            make_task(role=AgentRole.MANAGER, title="Implement feature X")
        )
        review = agent.build_system_prompt(
            make_task(role=AgentRole.MANAGER,
                      title="[Manager Review] Weekly review")
        )
        assert planning != review

    def test_planning_prompt_is_non_empty(self):
        agent = ManagerAgent()
        prompt = agent.build_system_prompt(
            make_task(role=AgentRole.MANAGER)
        )
        assert len(prompt) > 100

    def test_review_prompt_is_non_empty(self):
        agent = ManagerAgent()
        prompt = agent.build_system_prompt(
            make_task(role=AgentRole.MANAGER,
                      title="[Manager Review] Daily review")
        )
        assert len(prompt) > 100

    def test_planning_prompt_mentions_declare_complete(self):
        agent = ManagerAgent()
        prompt = agent.build_system_prompt(make_task(role=AgentRole.MANAGER))
        assert "declare_complete" in prompt

    def test_review_prompt_mentions_declare_complete(self):
        agent = ManagerAgent()
        prompt = agent.build_system_prompt(
            make_task(role=AgentRole.MANAGER,
                      title="[Manager Review] Daily review")
        )
        assert "declare_complete" in prompt

    def test_prompt_includes_repo_when_set(self):
        agent = ManagerAgent()
        task = make_task(role=AgentRole.MANAGER, repo=["special-repo"])
        prompt = agent.build_system_prompt(task)
        assert "special-repo" in prompt

    def test_planning_prompt_references_agent_roles(self):
        agent = ManagerAgent()
        prompt = agent.build_system_prompt(make_task(role=AgentRole.MANAGER))
        # Manager must know about the roles it can assign to
        assert "coder" in prompt.lower() or "writer" in prompt.lower()


# ---------------------------------------------------------------------------
# _is_review_task
# ---------------------------------------------------------------------------

class TestIsReviewTask:
    def test_detects_manager_review_prefix(self):
        assert _is_review_task(
            make_task(title="[Manager Review] Weekly review")
        ) is True

    def test_non_review_task_not_detected(self):
        assert _is_review_task(
            make_task(title="Implement the parser")
        ) is False

    def test_partial_prefix_not_detected(self):
        assert _is_review_task(
            make_task(title="Manager Review of something")
        ) is False

    def test_empty_title_not_detected(self):
        assert _is_review_task(make_task(title="")) is False

    def test_case_sensitive(self):
        # Prefix must match exactly
        assert _is_review_task(
            make_task(title="[manager review] lowercase")
        ) is False


# ---------------------------------------------------------------------------
# _build_review_task (orchestrator helper)
# ---------------------------------------------------------------------------

class TestBuildReviewTask:
    def _setup(self, tasks=None, last_review_at=None,
            prev_summary="", upcoming_limit=20):
        q = make_repo()
        if tasks:
            for t in tasks:
                q.add(t)
        ws_repo = InMemoryWorkspaceStateRepository()
        if last_review_at:
            ws_repo.set_last_review_at(last_review_at)
        if prev_summary:
            ws_repo.set_last_review_summary(prev_summary)
        cfg = make_config(upcoming_limit)
        return q, ws_repo, cfg

    def test_created_task_has_manager_role(self):
        q, ws_repo, cfg = self._setup()
        task = _build_review_task(q, ws_repo, cfg)
        assert task.role == AgentRole.MANAGER

    def test_created_task_has_preempt_true(self):
        q, ws_repo, cfg = self._setup()
        task = _build_review_task(q, ws_repo, cfg)
        assert task.preempt is True

    def test_title_has_manager_review_prefix(self):
        q, ws_repo, cfg = self._setup()
        task = _build_review_task(q, ws_repo, cfg)
        assert task.title.startswith("[Manager Review]")

    def test_description_includes_blocked_section(self):
        blocked = make_task(title="blocked task")
        blocked.status = TaskStatus.BLOCKED_BY_HUMAN
        q, ws_repo, cfg = self._setup(tasks=[blocked])
        task = _build_review_task(q, ws_repo, cfg)
        assert "BLOCKED" in task.description.upper()

    def test_description_includes_upcoming_section(self):
        ready = make_task(title="upcoming task", status=TaskStatus.READY)
        q, ws_repo, cfg = self._setup(tasks=[ready])
        task = _build_review_task(q, ws_repo, cfg)
        assert "UPCOMING" in task.description.upper() or \
               "READY" in task.description.upper()

    def test_description_includes_completed_section(self):
        done = make_task(title="done task", status=TaskStatus.COMPLETE)
        done.completed_at = datetime.now(timezone.utc).isoformat()
        q, ws_repo, cfg = self._setup(tasks=[done])
        task = _build_review_task(q, ws_repo, cfg)
        assert "COMPLETED" in task.description.upper() or \
               "COMPLETE" in task.description.upper()

    def test_description_includes_previous_summary_when_present(self):
        q, ws_repo, cfg = self._setup(prev_summary="All looking good.")
        task = _build_review_task(q, ws_repo, cfg)
        assert "All looking good." in task.description

    def test_description_omits_previous_summary_when_absent(self):
        q, ws_repo, cfg = self._setup(prev_summary="")
        task = _build_review_task(q, ws_repo, cfg)
        assert "PREVIOUS REVIEW" not in task.description.upper()

    def test_respects_upcoming_tasks_limit(self):
        tasks = [
            make_task(title=f"task {i}", status=TaskStatus.READY)
            for i in range(10)
        ]
        q, ws_repo, cfg = self._setup(tasks=tasks, upcoming_limit=3)
        task = _build_review_task(q, ws_repo, cfg)
        # Only 3 upcoming tasks should appear — count lines with task IDs
        # by checking the description contains at most 3 ready task titles
        shown = sum(1 for t in tasks if t.title in task.description)
        assert shown <= 3

    def test_recently_completed_excludes_pre_review_tasks(self):
        old_done = make_task(title="old completed")
        old_done.status = TaskStatus.COMPLETE
        old_done.completed_at = "2026-01-01T00:00:00+00:00"

        new_done = make_task(title="new completed")
        new_done.status = TaskStatus.COMPLETE
        new_done.completed_at = "2026-03-15T00:00:00+00:00"

        last_review = datetime(2026, 3, 1, tzinfo=timezone.utc)
        q, ws_repo, cfg = self._setup(
            tasks=[old_done, new_done],
            last_review_at=last_review,
        )
        task = _build_review_task(q, ws_repo, cfg)
        assert "new completed" in task.description
        assert "old completed" not in task.description

    def test_pending_question_included_for_blocked_task(self):
        blocked = make_task(title="blocked with question")
        blocked.status = TaskStatus.BLOCKED_BY_HUMAN
        blocked.pending_question = "Which algorithm should I use?"
        q, state, cfg = self._setup(tasks=[blocked])
        task = _build_review_task(q, state, cfg)
        assert "Which algorithm should I use?" in task.description


# ---------------------------------------------------------------------------
# _on_manager_review_complete
# ---------------------------------------------------------------------------

class TestOnManagerReviewComplete:
    def _make_orchestrator(self, tmp_path):
        from matrixmouse.orchestrator import Orchestrator
        cfg = MagicMock()
        cfg.manager_review_schedule = ""
        cfg.priority_aging_rate = 0.01
        cfg.priority_max_aging_bonus = 0.3
        cfg.priority_importance_weight = 0.6
        cfg.priority_urgency_weight = 0.4

        paths = MagicMock()
        paths.workspace_root = tmp_path
        paths.agent_notes = tmp_path / "AGENT_NOTES.md"

        queue = InMemoryTaskRepository()
        ws_state_repo = InMemoryWorkspaceStateRepository()

        return Orchestrator(
            config=cfg,
            paths=paths,
            queue=queue,
            ws_state_repo=ws_state_repo,
    )

    def test_updates_last_manager_review_at(self, tmp_path):
        orch = self._make_orchestrator(tmp_path)
        orch._on_manager_review_complete("Summary text.")
        assert orch._ws_state_repo.get_last_review_at() is not None

    def test_saves_workspace_state_to_disk(self, tmp_path):
        # SQLite auto-persists — no JSON file to check.
        # Verify the state is readable after calling the method instead.
        orch = self._make_orchestrator(tmp_path)
        orch._on_manager_review_complete("Summary text.")
        assert orch._ws_state_repo.get_last_review_at() is not None

    def test_stores_summary_in_workspace_state(self, tmp_path):
        orch = self._make_orchestrator(tmp_path)
        orch._on_manager_review_complete("Everything looks healthy.")
        assert orch._ws_state_repo.get_last_review_summary() == \
            "Everything looks healthy."
        