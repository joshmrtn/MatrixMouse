"""
tests/test_pr_flow.py

Tests for issue #29 — PR flow, decision endpoint, and PR polling.

Covers:
    - _parse_owner_repo helper (orchestrator + api)
    - _get_provider (orchestrator)
    - _is_protected_branch cache-aware version (orchestrator)
    - _handle_critic_complete now emits pr_approval_required (orchestrator)
    - _poll_pr_tasks — merged, closed, still open, error handling (orchestrator)
    - _handle_pr_merged (orchestrator)
    - _handle_pr_closed — feedback injection, pr_rejection event (orchestrator)
    - _push_branch_and_create_pr (orchestrator)
    - POST /tasks/{task_id}/decision — all decision_types (api)

All tests mock the GitRemoteProvider — no real API calls are made.
All tests mock git operations — no real git calls are made.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from matrixmouse.git.git_remote_provider import AuthenticationError, ProviderAPIError
from matrixmouse.repository.memory_workspace_state_repository import (
    InMemoryWorkspaceStateRepository,
)
from matrixmouse.repository.memory_task_repository import InMemoryTaskRepository
from matrixmouse.task import AgentRole, PRState, Task, TaskStatus


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_config(**overrides):
    cfg = MagicMock()
    cfg.protected_branches = ["main", "master"]
    cfg.pr_poll_interval_minutes = 10
    cfg.branch_protection_cache_ttl_minutes = 60
    cfg.default_merge_target = ""
    cfg.critic_max_turns = 5
    cfg.merge_conflict_max_turns = 5
    cfg.manager_planning_max_turns = 10
    cfg.agent_max_turns = 50
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


def _make_paths(tmp_path):
    paths = MagicMock()
    paths.workspace_root = tmp_path
    return paths


def _make_orchestrator(tmp_path, **config_kwargs):
    from matrixmouse.orchestrator import Orchestrator
    return Orchestrator(
        config=_make_config(**config_kwargs),
        paths=_make_paths(tmp_path),
        queue=InMemoryTaskRepository(),
        ws_state_repo=InMemoryWorkspaceStateRepository(),
    )


def _ready_task(
    title: str = "Test task",
    description: str = "Do the thing carefully.",
    role: AgentRole = AgentRole.CODER,
    status: TaskStatus = TaskStatus.READY,
    repo: list[str] | None = ["MatrixMouse"],
    branch: str = "mm/test-task",
    importance=0.5,
    urgency=0.5,
    **kwargs,
) -> Task:
    return Task(
        title=title,
        description=description,
        role=role,
        status=status,
        repo=repo if repo is not None else ["repo"],
        branch=branch,
        importance=importance,
        urgency=urgency,
        **kwargs,
    )

def _blocked_task(**kwargs) -> Task:
    t = _ready_task(**kwargs)
    t.status = TaskStatus.BLOCKED_BY_HUMAN
    return t


def _provider_mock(state="open", pr_url="https://github.com/o/r/pull/1", feedback=""):
    p = MagicMock()
    p.is_branch_protected.return_value = False
    p.create_pull_request.return_value = pr_url
    p.get_pr_state.return_value = state
    p.get_pr_feedback.return_value = feedback
    return p


# ---------------------------------------------------------------------------
# _parse_owner_repo
# ---------------------------------------------------------------------------

class TestParseOwnerRepo:
    def test_https_url(self, tmp_path):
        from matrixmouse.orchestrator import _parse_owner_repo
        assert _parse_owner_repo("https://github.com/joshmrtn/MatrixMouse") == "joshmrtn/MatrixMouse"

    def test_https_url_with_git_suffix(self, tmp_path):
        from matrixmouse.orchestrator import _parse_owner_repo
        assert _parse_owner_repo("https://github.com/joshmrtn/MatrixMouse.git") == "joshmrtn/MatrixMouse"

    def test_ssh_url(self, tmp_path):
        from matrixmouse.orchestrator import _parse_owner_repo
        assert _parse_owner_repo("git@github.com:joshmrtn/MatrixMouse.git") == "joshmrtn/MatrixMouse"

    def test_ssh_url_no_git_suffix(self, tmp_path):
        from matrixmouse.orchestrator import _parse_owner_repo
        assert _parse_owner_repo("git@github.com:joshmrtn/MatrixMouse") == "joshmrtn/MatrixMouse"

    def test_trailing_slash_stripped(self, tmp_path):
        from matrixmouse.orchestrator import _parse_owner_repo
        assert _parse_owner_repo("https://github.com/joshmrtn/MatrixMouse/") == "joshmrtn/MatrixMouse"

    def test_empty_string_returns_empty(self, tmp_path):
        from matrixmouse.orchestrator import _parse_owner_repo
        assert _parse_owner_repo("") == ""


# ---------------------------------------------------------------------------
# _get_provider
# ---------------------------------------------------------------------------

class TestGetProvider:
    def test_returns_none_when_no_metadata(self, tmp_path):
        orch = _make_orchestrator(tmp_path)
        result = orch._get_provider("UnknownRepo")
        assert result is None

    def test_returns_none_when_provider_is_empty(self, tmp_path):
        orch = _make_orchestrator(tmp_path)
        orch._ws_state_repo.set_repo_metadata(
            "MatrixMouse", provider="", remote_url="https://github.com/o/r.git"
        )
        result = orch._get_provider("MatrixMouse")
        assert result is None

    def test_returns_none_when_token_missing(self, tmp_path, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        orch = _make_orchestrator(tmp_path)
        orch._ws_state_repo.set_repo_metadata(
            "MatrixMouse", provider="github", remote_url="https://github.com/o/r.git"
        )
        result = orch._get_provider("MatrixMouse")
        assert result is None

    def test_returns_github_provider_when_configured(self, tmp_path, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "test-token")
        from matrixmouse.git.github_provider import GitHubProvider
        orch = _make_orchestrator(tmp_path)
        orch._ws_state_repo.set_repo_metadata(
            "MatrixMouse", provider="github", remote_url="https://github.com/o/r.git"
        )
        result = orch._get_provider("MatrixMouse")
        assert isinstance(result, GitHubProvider)


# ---------------------------------------------------------------------------
# _is_protected_branch — cache-aware
# ---------------------------------------------------------------------------

class TestIsProtectedBranchCacheAware:
    def test_config_list_checked_first(self, tmp_path):
        orch = _make_orchestrator(tmp_path)
        # "main" is in the default config list — should return True
        # without touching cache or provider
        assert orch._is_protected_branch("main", "MatrixMouse") is True

    def test_returns_false_for_unknown_branch_no_repo_name(self, tmp_path):
        orch = _make_orchestrator(tmp_path)
        assert orch._is_protected_branch("mm/feature", "") is False

    def test_cache_hit_avoids_api_call(self, tmp_path, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "tok")
        orch = _make_orchestrator(tmp_path)
        orch._ws_state_repo.set_repo_metadata(
            "Repo", provider="github", remote_url="https://github.com/o/r.git"
        )
        # Populate the cache — set_protected_branches_cached stamps now as timestamp
        orch._ws_state_repo.set_protected_branches_cached("Repo", ["develop"])
        mock_provider = _provider_mock()
        # Provider should not be called when cache is fresh
        with patch.object(orch, "_get_provider", return_value=mock_provider):
            result = orch._is_protected_branch("develop", "Repo")
        assert result is True
        mock_provider.is_branch_protected.assert_not_called()

    def test_cache_miss_calls_provider(self, tmp_path, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "tok")
        orch = _make_orchestrator(tmp_path)
        orch._ws_state_repo.set_repo_metadata(
            "Repo", provider="github", remote_url="https://github.com/o/r.git"
        )
        # No cache set
        mock_provider = _provider_mock()
        mock_provider.is_branch_protected.return_value = True
        with patch.object(orch, "_get_provider", return_value=mock_provider):
            with patch.object(mock_provider, "_get", return_value=[]):
                result = orch._is_protected_branch("release", "Repo")
        assert result is True
        mock_provider.is_branch_protected.assert_called_once()

    def test_provider_error_falls_back_to_false(self, tmp_path, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "tok")
        orch = _make_orchestrator(tmp_path)
        orch._ws_state_repo.set_repo_metadata(
            "Repo", provider="github", remote_url="https://github.com/o/r.git"
        )
        mock_provider = _provider_mock()
        mock_provider.is_branch_protected.side_effect = ProviderAPIError("oops")
        with patch.object(orch, "_get_provider", return_value=mock_provider):
            result = orch._is_protected_branch("release", "Repo")
        assert result is False


# ---------------------------------------------------------------------------
# _handle_critic_complete — pr_approval_required event
# ---------------------------------------------------------------------------

class TestHandleCriticCompleteEmitsPrApprovalRequired:
    def _setup(self, tmp_path):
        orch = _make_orchestrator(tmp_path)

        reviewed = _ready_task(repo=["MatrixMouse"], branch="mm/work")
        orch.queue.add(reviewed)

        critic = Task(
            title="[Critic Review] Test",
            role=AgentRole.CRITIC,
            status=TaskStatus.RUNNING,
            repo=["MatrixMouse"],
            reviews_task_id=reviewed.id,
        )
        orch.queue.add(critic)
        return orch, reviewed, critic

    def test_emits_pr_approval_required_for_protected_branch(self, tmp_path):
        orch, reviewed, critic = self._setup(tmp_path)

        emitted = []
        mock_m = MagicMock()
        mock_m.emit.side_effect = lambda t, d: emitted.append((t, d))

        with patch.object(orch, "_get_merge_target", return_value="main"):
            with patch.object(orch, "_is_protected_branch", return_value=True):
                with patch("matrixmouse.comms.get_manager", return_value=mock_m):
                    from matrixmouse.loop import LoopResult, LoopExitReason
                    orch._handle_critic_complete(
                        critic,
                        LoopResult(
                            exit_reason=LoopExitReason.COMPLETE,
                            messages=[],
                            turns_taken=1,
                        ),
                    )

        event_types = [e[0] for e in emitted]
        assert "pr_approval_required" in event_types

    def test_pr_approval_event_contains_choices(self, tmp_path):
        orch, reviewed, critic = self._setup(tmp_path)

        emitted = {}
        mock_m = MagicMock()
        mock_m.emit.side_effect = lambda t, d: emitted.update({t: d})

        with patch.object(orch, "_get_merge_target", return_value="main"):
            with patch.object(orch, "_is_protected_branch", return_value=True):
                with patch("matrixmouse.comms.get_manager", return_value=mock_m):
                    from matrixmouse.loop import LoopResult, LoopExitReason
                    orch._handle_critic_complete(
                        critic,
                        LoopResult(
                            exit_reason=LoopExitReason.COMPLETE,
                            messages=[],
                            turns_taken=1,
                        ),
                    )

        data = emitted.get("pr_approval_required", {})
        choices = [c["value"] for c in data.get("choices", [])]
        assert "approve" in choices
        assert "reject" in choices

    def test_task_stays_blocked_by_human(self, tmp_path):
        orch, reviewed, critic = self._setup(tmp_path)

        with patch.object(orch, "_get_merge_target", return_value="main"):
            with patch.object(orch, "_is_protected_branch", return_value=True):
                with patch("matrixmouse.comms.get_manager", return_value=None):
                    from matrixmouse.loop import LoopResult, LoopExitReason
                    orch._handle_critic_complete(
                        critic,
                        LoopResult(
                            exit_reason=LoopExitReason.COMPLETE,
                            messages=[],
                            turns_taken=1,
                        ),
                    )

        refreshed = orch.queue.get(reviewed.id)
        assert refreshed is not None
        assert refreshed.status == TaskStatus.BLOCKED_BY_HUMAN


# ---------------------------------------------------------------------------
# _poll_pr_tasks
# ---------------------------------------------------------------------------

class TestPollPrTasks:
    def _task_with_open_pr(self, orch, poll_next_at="") -> Task:
        task = _blocked_task(pr_url="https://github.com/o/r/pull/1")
        task.pr_state = PRState.OPEN
        task.pr_poll_next_at = poll_next_at
        orch.queue.add(task)
        return task

    def test_skips_tasks_with_no_pr_url(self, tmp_path):
        orch = _make_orchestrator(tmp_path)
        task = _blocked_task()
        task.pr_state = PRState.OPEN
        task.pr_poll_next_at = ""
        orch.queue.add(task)

        mock_provider = _provider_mock()
        with patch.object(orch, "_get_provider", return_value=mock_provider):
            orch._poll_pr_tasks()

        mock_provider.get_pr_state.assert_not_called()

    def test_skips_tasks_not_yet_due(self, tmp_path):
        orch = _make_orchestrator(tmp_path)
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        task = self._task_with_open_pr(orch, poll_next_at=future)

        mock_provider = _provider_mock()
        with patch.object(orch, "_get_provider", return_value=mock_provider):
            orch._poll_pr_tasks()

        mock_provider.get_pr_state.assert_not_called()

    def test_skips_when_no_provider(self, tmp_path):
        orch = _make_orchestrator(tmp_path)
        task = self._task_with_open_pr(orch)

        with patch.object(orch, "_get_provider", return_value=None):
            orch._poll_pr_tasks()  # should not raise

    def test_merged_pr_marks_task_complete(self, tmp_path):
        orch = _make_orchestrator(tmp_path)
        task = self._task_with_open_pr(orch)
        orch._ws_state_repo.set_repo_metadata(
            "MatrixMouse", provider="github",
            remote_url="https://github.com/o/MatrixMouse.git"
        )

        mock_provider = _provider_mock(state="merged")
        with patch.object(orch, "_get_provider", return_value=mock_provider):
            orch._poll_pr_tasks()

        refreshed = orch.queue.get(task.id)
        assert refreshed is not None
        assert refreshed.status == TaskStatus.COMPLETE

    def test_merged_pr_sets_pr_state_merged(self, tmp_path):
        orch = _make_orchestrator(tmp_path)
        task = self._task_with_open_pr(orch)
        orch._ws_state_repo.set_repo_metadata(
            "MatrixMouse", provider="github",
            remote_url="https://github.com/o/MatrixMouse.git"
        )

        mock_provider = _provider_mock(state="merged")
        with patch.object(orch, "_get_provider", return_value=mock_provider):
            orch._poll_pr_tasks()

        refreshed = orch.queue.get(task.id)
        assert refreshed is not None
        assert refreshed.pr_state == PRState.MERGED

    def test_closed_pr_injects_feedback_into_context(self, tmp_path):
        orch = _make_orchestrator(tmp_path)
        task = self._task_with_open_pr(orch)
        orch._ws_state_repo.set_repo_metadata(
            "MatrixMouse", provider="github",
            remote_url="https://github.com/o/MatrixMouse.git"
        )

        mock_provider = _provider_mock(state="closed", feedback="Please fix encoding.")
        with patch.object(orch, "_get_provider", return_value=mock_provider):
            with patch("matrixmouse.comms.get_manager", return_value=None):
                orch._poll_pr_tasks()

        refreshed = orch.queue.get(task.id)
        assert refreshed is not None
        messages = refreshed.context_messages
        assert any("Please fix encoding." in str(m.get("content", "")) for m in messages)

    def test_closed_pr_emits_pr_rejection_event(self, tmp_path):
        orch = _make_orchestrator(tmp_path)
        task = self._task_with_open_pr(orch)
        orch._ws_state_repo.set_repo_metadata(
            "MatrixMouse", provider="github",
            remote_url="https://github.com/o/MatrixMouse.git"
        )

        mock_provider = _provider_mock(state="closed", feedback="Fix it.")
        emitted = []
        mock_m = MagicMock()
        mock_m.emit.side_effect = lambda t, d: emitted.append(t)

        with patch.object(orch, "_get_provider", return_value=mock_provider):
            with patch("matrixmouse.comms.get_manager", return_value=mock_m):
                orch._poll_pr_tasks()

        assert "pr_rejection" in emitted

    def test_closed_pr_sets_pr_state_closed(self, tmp_path):
        orch = _make_orchestrator(tmp_path)
        task = self._task_with_open_pr(orch)
        orch._ws_state_repo.set_repo_metadata(
            "MatrixMouse", provider="github",
            remote_url="https://github.com/o/MatrixMouse.git"
        )

        mock_provider = _provider_mock(state="closed")
        with patch.object(orch, "_get_provider", return_value=mock_provider):
            with patch("matrixmouse.comms.get_manager", return_value=None):
                orch._poll_pr_tasks()

        refreshed = orch.queue.get(task.id)
        assert refreshed is not None
        assert refreshed.pr_state == PRState.CLOSED

    def test_open_pr_updates_next_poll_time(self, tmp_path):
        orch = _make_orchestrator(tmp_path)
        task = self._task_with_open_pr(orch)
        orch._ws_state_repo.set_repo_metadata(
            "MatrixMouse", provider="github",
            remote_url="https://github.com/o/MatrixMouse.git"
        )

        mock_provider = _provider_mock(state="open")
        with patch.object(orch, "_get_provider", return_value=mock_provider):
            orch._poll_pr_tasks()

        refreshed = orch.queue.get(task.id)
        assert refreshed is not None
        assert refreshed.pr_poll_next_at != ""
        assert refreshed.pr_poll_next_at > datetime.now(timezone.utc).isoformat()

    def test_provider_error_does_not_raise(self, tmp_path):
        orch = _make_orchestrator(tmp_path)
        task = self._task_with_open_pr(orch)
        orch._ws_state_repo.set_repo_metadata(
            "MatrixMouse", provider="github",
            remote_url="https://github.com/o/MatrixMouse.git"
        )

        mock_provider = _provider_mock()
        mock_provider.get_pr_state.side_effect = ProviderAPIError("API down")
        with patch.object(orch, "_get_provider", return_value=mock_provider):
            orch._poll_pr_tasks()  # must not raise

    def test_provider_error_leaves_task_open(self, tmp_path):
        orch = _make_orchestrator(tmp_path)
        task = self._task_with_open_pr(orch)
        orch._ws_state_repo.set_repo_metadata(
            "MatrixMouse", provider="github",
            remote_url="https://github.com/o/MatrixMouse.git"
        )

        mock_provider = _provider_mock()
        mock_provider.get_pr_state.side_effect = ProviderAPIError("API down")
        with patch.object(orch, "_get_provider", return_value=mock_provider):
            orch._poll_pr_tasks()

        refreshed = orch.queue.get(task.id)
        assert refreshed is not None
        assert refreshed.pr_state == PRState.OPEN


# ---------------------------------------------------------------------------
# POST /tasks/{task_id}/decision
# ---------------------------------------------------------------------------

@pytest.fixture
def api_client(tmp_path):
    """TestClient with queue and ws_state_repo configured."""
    import matrixmouse.api as api_module
    from matrixmouse.repository.memory_task_repository import InMemoryTaskRepository
    from matrixmouse.repository.memory_workspace_state_repository import (
        InMemoryWorkspaceStateRepository,
    )

    queue = InMemoryTaskRepository()
    ws_state_repo = InMemoryWorkspaceStateRepository()
    api_module.configure(
        queue=queue,
        status={},
        workspace_root=tmp_path,
        config=_make_config(),
        ws_state_repo=ws_state_repo,
    )
    yield TestClient(api_module.app), queue, ws_state_repo


class TestDecisionEndpointUnknownType:
    def test_unknown_decision_type_returns_400(self, api_client):
        client, queue, _ = api_client
        task = _blocked_task()
        queue.add(task)

        resp = client.post(f"/tasks/{task.id}/decision", json={
            "decision_type": "totally_unknown_event",
            "choice": "yes",
        })
        assert resp.status_code == 400

    def test_missing_task_returns_404(self, api_client):
        client, _, _ = api_client
        resp = client.post("/tasks/doesnotexist/decision", json={
            "decision_type": "pr_approval_required",
            "choice": "approve",
        })
        assert resp.status_code == 404


class TestDecisionEndpointPrApproval:
    def test_reject_keeps_task_blocked(self, api_client):
        client, queue, _ = api_client
        task = _blocked_task()
        queue.add(task)

        resp = client.post(f"/tasks/{task.id}/decision", json={
            "decision_type": "pr_approval_required",
            "choice": "reject",
        })
        assert resp.status_code == 200
        refreshed = queue.get(task.id)
        assert refreshed.status == TaskStatus.BLOCKED_BY_HUMAN

    def test_reject_with_note_appends_to_context(self, api_client):
        client, queue, _ = api_client
        task = _blocked_task()
        queue.add(task)

        resp = client.post(f"/tasks/{task.id}/decision", json={
            "decision_type": "pr_approval_required",
            "choice": "reject",
            "note": "Not ready yet.",
        })
        assert resp.status_code == 200
        refreshed = queue.get(task.id)
        assert any("Not ready yet." in str(m.get("content", ""))
                   for m in refreshed.context_messages)

    def test_approve_requires_blocked_by_human(self, api_client):
        client, queue, _ = api_client
        task = _ready_task()  # READY, not BLOCKED
        queue.add(task)

        resp = client.post(f"/tasks/{task.id}/decision", json={
            "decision_type": "pr_approval_required",
            "choice": "approve",
        })
        assert resp.status_code == 400

    def test_invalid_choice_returns_400(self, api_client):
        client, queue, _ = api_client
        task = _blocked_task()
        queue.add(task)

        resp = client.post(f"/tasks/{task.id}/decision", json={
            "decision_type": "pr_approval_required",
            "choice": "maybe",
        })
        assert resp.status_code == 400


class TestDecisionEndpointPrRejection:
    def test_rework_unblocks_task(self, api_client):
        client, queue, _ = api_client
        task = _blocked_task(pr_state=PRState.CLOSED, pr_url="https://github.com/o/r/pull/1")
        queue.add(task)

        resp = client.post(f"/tasks/{task.id}/decision", json={
            "decision_type": "pr_rejection",
            "choice": "rework",
        })
        assert resp.status_code == 200
        refreshed = queue.get(task.id)
        assert refreshed.status == TaskStatus.READY

    def test_rework_clears_pr_fields(self, api_client):
        client, queue, _ = api_client
        task = _blocked_task(
            pr_state=PRState.CLOSED,
            pr_url="https://github.com/o/r/pull/1",
            pr_poll_next_at="2099-01-01T00:00:00+00:00",
        )
        queue.add(task)

        client.post(f"/tasks/{task.id}/decision", json={
            "decision_type": "pr_rejection",
            "choice": "rework",
        })
        refreshed = queue.get(task.id)
        assert refreshed.pr_state == PRState.NONE
        assert refreshed.pr_url == ""
        assert refreshed.pr_poll_next_at == ""

    def test_rework_with_note_appends_to_context(self, api_client):
        client, queue, _ = api_client
        task = _blocked_task(pr_state=PRState.CLOSED)
        queue.add(task)

        client.post(f"/tasks/{task.id}/decision", json={
            "decision_type": "pr_rejection",
            "choice": "rework",
            "note": "Focus on the encoding issue.",
        })
        refreshed = queue.get(task.id)
        assert any("Focus on the encoding issue." in str(m.get("content", ""))
                   for m in refreshed.context_messages)

    def test_manual_keeps_task_blocked(self, api_client):
        client, queue, _ = api_client
        task = _blocked_task(pr_state=PRState.CLOSED)
        queue.add(task)

        resp = client.post(f"/tasks/{task.id}/decision", json={
            "decision_type": "pr_rejection",
            "choice": "manual",
        })
        assert resp.status_code == 200
        refreshed = queue.get(task.id)
        assert refreshed.status == TaskStatus.BLOCKED_BY_HUMAN

    def test_manual_with_note_appended_to_notes(self, api_client):
        client, queue, _ = api_client
        task = _blocked_task(pr_state=PRState.CLOSED)
        queue.add(task)

        client.post(f"/tasks/{task.id}/decision", json={
            "decision_type": "pr_rejection",
            "choice": "manual",
            "note": "Will fix in next sprint.",
        })
        refreshed = queue.get(task.id)
        assert "Will fix in next sprint." in refreshed.notes

    def test_invalid_choice_returns_400(self, api_client):
        client, queue, _ = api_client
        task = _blocked_task(pr_state=PRState.CLOSED)
        queue.add(task)

        resp = client.post(f"/tasks/{task.id}/decision", json={
            "decision_type": "pr_rejection",
            "choice": "delete_it",
        })
        assert resp.status_code == 400


class TestDecisionEndpointTurnLimit:
    """Verify /decision delegates correctly to the turn limit handler."""

    def test_extend_via_decision_endpoint(self, api_client):
        client, queue, _ = api_client
        task = _blocked_task()
        task.turn_limit = 10
        queue.add(task)

        resp = client.post(f"/tasks/{task.id}/decision", json={
            "decision_type": "turn_limit_reached",
            "choice": "extend",
        })
        assert resp.status_code == 200
        refreshed = queue.get(task.id)
        assert refreshed.status == TaskStatus.READY
        assert refreshed.turn_limit > 10

    def test_cancel_via_decision_endpoint(self, api_client):
        client, queue, _ = api_client
        task = _blocked_task()
        queue.add(task)

        resp = client.post(f"/tasks/{task.id}/decision", json={
            "decision_type": "turn_limit_reached",
            "choice": "cancel",
        })
        assert resp.status_code == 200
        refreshed = queue.get(task.id)
        assert refreshed.status == TaskStatus.CANCELLED


class TestDecisionEndpointMergeTurnLimit:
    def test_extend_returns_task_to_ready(self, api_client):
        client, queue, _ = api_client
        task = _blocked_task(role=AgentRole.MERGE)
        task.turn_limit = 5
        queue.add(task)

        resp = client.post(f"/tasks/{task.id}/decision", json={
            "decision_type": "merge_conflict_resolution_turn_limit_reached",
            "choice": "extend",
        })
        assert resp.status_code == 200
        refreshed = queue.get(task.id)
        assert refreshed.status == TaskStatus.READY

    def test_abort_cancels_task(self, api_client):
        client, queue, _ = api_client
        task = _blocked_task(role=AgentRole.MERGE)
        queue.add(task)

        resp = client.post(f"/tasks/{task.id}/decision", json={
            "decision_type": "merge_conflict_resolution_turn_limit_reached",
            "choice": "abort",
        })
        assert resp.status_code == 200
        refreshed = queue.get(task.id)
        assert refreshed.status == TaskStatus.CANCELLED

    def test_invalid_choice_returns_400(self, api_client):
        client, queue, _ = api_client
        task = _blocked_task(role=AgentRole.MERGE)
        queue.add(task)

        resp = client.post(f"/tasks/{task.id}/decision", json={
            "decision_type": "merge_conflict_resolution_turn_limit_reached",
            "choice": "explode",
        })
        assert resp.status_code == 400


class TestDecisionEndpointPlanningTurnLimit:
    def test_commit_marks_task_complete(self, api_client):
        client, queue, ws = api_client
        task = _blocked_task(role=AgentRole.MANAGER)
        queue.add(task)

        resp = client.post(f"/tasks/{task.id}/decision", json={
            "decision_type": "planning_turn_limit_reached",
            "choice": "commit",
        })
        assert resp.status_code == 200
        refreshed = queue.get(task.id)
        assert refreshed.status == TaskStatus.COMPLETE

    def test_cancel_cancels_task(self, api_client):
        client, queue, _ = api_client
        task = _blocked_task(role=AgentRole.MANAGER)
        queue.add(task)

        resp = client.post(f"/tasks/{task.id}/decision", json={
            "decision_type": "planning_turn_limit_reached",
            "choice": "cancel",
        })
        assert resp.status_code == 200
        refreshed = queue.get(task.id)
        assert refreshed.status == TaskStatus.CANCELLED

    def test_extend_returns_task_to_ready(self, api_client):
        client, queue, _ = api_client
        task = _blocked_task(role=AgentRole.MANAGER)
        task.turn_limit = 10
        queue.add(task)

        resp = client.post(f"/tasks/{task.id}/decision", json={
            "decision_type": "planning_turn_limit_reached",
            "choice": "extend",
        })
        assert resp.status_code == 200
        refreshed = queue.get(task.id)
        assert refreshed.status == TaskStatus.READY
        assert refreshed.turn_limit > 10
