"""
tests/test_api.py

Tests for matrixmouse.api — control endpoints added in refactor/web-server.
"""

import os
import signal
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from matrixmouse.api import (
    app, configure, clear_stop_requested, is_stop_requested, is_paused,
    _stop_requested, _orchestrator_paused,
)
from matrixmouse.task import AgentRole, Task, TaskStatus
from matrixmouse.repository.memory_task_repository import InMemoryTaskRepository
from matrixmouse.repository.workspace_state_repository import WorkspaceStateRepository


@pytest.fixture(autouse=True)
def reset_flags():
    _stop_requested.clear()
    _orchestrator_paused.clear()
    yield
    _stop_requested.clear()
    _orchestrator_paused.clear()


@pytest.fixture
def workspace(tmp_path):
    ws = tmp_path / "workspace"
    (ws / ".matrixmouse").mkdir(parents=True)
    configure(queue=MagicMock(), status={}, workspace_root=ws, config=MagicMock(), ws_state_repo=InMemoryWorkspaceStateRepository())
    return ws


@pytest.fixture
def client(workspace):
    return TestClient(app, raise_server_exceptions=False)


class InMemoryWorkspaceStateRepository(WorkspaceStateRepository):
    def __init__(self):
        self._store: dict = {}
        self._stale: dict = {}

    def get(self, key):
        return self._store.get(key)

    def set(self, key, value):
        self._store[key] = value

    def delete(self, key):
        self._store.pop(key, None)

    def get_stale_clarification_task(self, blocked_task_id):
        return self._stale.get(blocked_task_id)

    def register_stale_clarification_task(self, blocked_task_id, manager_task_id):
        self._stale[blocked_task_id] = manager_task_id

    def clear_stale_clarification_task(self, blocked_task_id):
        self._stale.pop(blocked_task_id, None)

    def all_stale_clarification_tasks(self):
        return dict(self._stale)

# ---------------------------------------------------------------------------
# Fixtures for task-related tests
# ---------------------------------------------------------------------------

@pytest.fixture
def queue_workspace(tmp_path):
    """Workspace with a real InMemoryTaskRepository wired into the API."""
    ws = tmp_path / "workspace"
    (ws / ".matrixmouse").mkdir(parents=True)
    q = InMemoryTaskRepository()
    cfg = MagicMock()
    cfg.agent_max_turns = 50
    configure(queue=q, status={}, workspace_root=ws, config=cfg, ws_state_repo=InMemoryWorkspaceStateRepository())
    return ws, q


@pytest.fixture
def queue_client(queue_workspace):
    _, q = queue_workspace
    return TestClient(app, raise_server_exceptions=False), q


class TestSoftStop:
    def test_sets_stop_flag(self, client):
        assert not is_stop_requested()
        assert client.post("/stop").json()["ok"] is True
        assert is_stop_requested()

    def test_returns_message(self, client):
        assert "message" in client.post("/stop").json()

    def test_idempotent(self, client):
        client.post("/stop"); client.post("/stop")
        assert is_stop_requested()

    def test_clear_stop_requested(self, client):
        client.post("/stop"); clear_stop_requested()
        assert not is_stop_requested()


class TestEstopStatus:
    def test_not_engaged_initially(self, client, workspace):
        data = client.get("/estop").json()
        assert data["engaged"] is False and data["message"] is None

    def test_engaged_when_lockfile_exists(self, client, workspace):
        (workspace / ".matrixmouse" / "ESTOP").write_text("E-STOP at 2026-01-01T00:00:00Z\n")
        data = client.get("/estop").json()
        assert data["engaged"] is True
        assert "2026-01-01" in data["message"]

    def test_engaged_unreadable_lockfile(self, client, workspace, monkeypatch):
        lockfile = workspace / ".matrixmouse" / "ESTOP"
        lockfile.write_text("something")
        original = Path.read_text
        def bad_read(self, *a, **kw):
            if self == lockfile: raise OSError("permission denied")
            return original(self, *a, **kw)
        monkeypatch.setattr(Path, "read_text", bad_read)
        assert client.get("/estop").json()["engaged"] is True


class TestKill:
    def test_writes_lockfile(self, client, workspace):
        lockfile = workspace / ".matrixmouse" / "ESTOP"
        with patch("os.kill"): client.post("/kill")
        assert lockfile.exists()

    def test_lockfile_content(self, client, workspace):
        with patch("os.kill"): client.post("/kill")
        content = (workspace / ".matrixmouse" / "ESTOP").read_text()
        assert "ESTOP" in content and "systemctl" in content

    def test_sends_sigterm(self, client, workspace):
        with patch("os.kill") as mock_kill: client.post("/kill")
        mock_kill.assert_called_once_with(os.getpid(), signal.SIGTERM)

    def test_engaged_after_kill(self, client, workspace):
        with patch("os.kill"): client.post("/kill")
        assert client.get("/estop").json()["engaged"] is True

    def test_503_without_workspace(self):
        configure(queue=MagicMock(), status={}, workspace_root=None, config=MagicMock(), ws_state_repo=InMemoryWorkspaceStateRepository) # type: ignore[arg-type]
        assert TestClient(app, raise_server_exceptions=False).post("/kill").status_code == 503


class TestEstopReset:
    def test_removes_lockfile(self, client, workspace):
        lockfile = workspace / ".matrixmouse" / "ESTOP"
        lockfile.write_text("engaged")
        r = client.post("/estop/reset")
        assert r.json()["ok"] is True and not lockfile.exists()

    def test_idempotent_when_not_engaged(self, client, workspace):
        assert client.post("/estop/reset").json()["ok"] is True

    def test_not_engaged_after_reset(self, client, workspace):
        (workspace / ".matrixmouse" / "ESTOP").write_text("engaged")
        client.post("/estop/reset")
        assert client.get("/estop").json()["engaged"] is False

    def test_503_without_workspace(self):
        configure(queue=MagicMock(), status={}, workspace_root=None, config=MagicMock(), ws_state_repo=InMemoryWorkspaceStateRepository()) # type: ignore[arg-type]
        assert TestClient(app, raise_server_exceptions=False).post("/estop/reset").status_code == 503


class TestEstopCycle:
    def test_kill_reset_cycle(self, workspace):
        c = TestClient(app, raise_server_exceptions=False)
        lockfile = workspace / ".matrixmouse" / "ESTOP"
        with patch("os.kill"): c.post("/kill")
        assert lockfile.exists() and c.get("/estop").json()["engaged"] is True
        c.post("/estop/reset")
        assert not lockfile.exists() and c.get("/estop").json()["engaged"] is False


class TestOrchestratorPause:
    def test_pause_sets_flag(self, client):
        r = client.post("/orchestrator/pause")
        assert r.json()["ok"] is True and r.json()["paused"] is True and is_paused()

    def test_resume_clears_flag(self, client):
        _orchestrator_paused.set()
        r = client.post("/orchestrator/resume")
        assert r.json()["paused"] is False and not is_paused()

    def test_pause_idempotent(self, client):
        client.post("/orchestrator/pause"); client.post("/orchestrator/pause")
        assert is_paused()

    def test_resume_when_not_paused(self, client):
        r = client.post("/orchestrator/resume")
        assert r.status_code == 200 and not is_paused()

    def test_pause_resume_cycle(self, client):
        client.post("/orchestrator/pause"); assert is_paused()
        client.post("/orchestrator/resume"); assert not is_paused()


class TestOrchestratorStatus:
    def test_not_paused_initially(self, client):
        data = client.get("/orchestrator/status").json()
        assert data["paused"] is False and "status" in data

    def test_reflects_pause(self, client):
        client.post("/orchestrator/pause")
        assert client.get("/orchestrator/status").json()["paused"] is True

    def test_reflects_stop(self, client):
        client.post("/stop")
        assert client.get("/orchestrator/status").json()["stopped"] is True


class TestContext:
    def test_empty_when_no_active_task(self, client):
        data = client.get("/context").json()
        assert data["messages"] == [] and data["count"] == 0

    def test_returns_messages_from_status(self, client, workspace):
        from matrixmouse import api as api_module
        messages = [
            {"role": "system",    "content": "You are a coding agent."},
            {"role": "user",      "content": "Fix the bug"},
            {"role": "assistant", "content": "Looking at the file."},
        ]
        api_module._status["context_messages"] = messages
        data = client.get("/context").json()
        assert data["count"] == 3
        assert data["messages"][0]["role"] == "system"
        api_module._status.pop("context_messages", None)

    def test_handles_ollama_message_objects(self, client, workspace):
        class FakeMsg:
            def __init__(self, role, content): self.role = role; self.content = content
        from matrixmouse import api as api_module
        api_module._status["context_messages"] = [FakeMsg("system", "prompt"), FakeMsg("user", "msg")]
        data = client.get("/context").json()
        assert data["count"] == 2
        assert all(isinstance(m["role"], str) for m in data["messages"])
        api_module._status.pop("context_messages", None)

    def test_estimated_tokens(self, client, workspace):
        from matrixmouse import api as api_module
        api_module._status["context_messages"] = [{"role": "user", "content": "x" * 400}]
        assert client.get("/context").json()["estimated_tokens"] == 100
        api_module._status.pop("context_messages", None)

    def test_repo_param_accepted(self, client):
        r = client.get("/context?repo=myrepo")
        assert r.status_code == 200 and r.json()["repo"] == "myrepo"


# ---------------------------------------------------------------------------
# Task creation
# ---------------------------------------------------------------------------

class TestCreateTask:
    def test_creates_task_with_ready_status(self, queue_client):
        client, q = queue_client
        r = client.post("/tasks", json={
            "title": "My task",
            "description": "Do the thing",
            "repo": ["my-repo"],
        })
        assert r.status_code == 201
        assert r.json()["status"] == "ready"

    def test_default_role_is_coder(self, queue_client):
        client, q = queue_client
        r = client.post("/tasks", json={
            "title": "task", "description": "desc", "repo": ["r"]
        })
        assert r.json()["role"] == "coder"

    def test_explicit_writer_role_accepted(self, queue_client):
        client, q = queue_client
        r = client.post("/tasks", json={
            "title": "t", "description": "d",
            "repo": ["r"], "role": "writer",
        })
        assert r.status_code == 201
        assert r.json()["role"] == "writer"

    def test_rejects_manager_role(self, queue_client):
        client, q = queue_client
        r = client.post("/tasks", json={
            "title": "t", "description": "d",
            "repo": ["r"], "role": "manager",
        })
        assert r.status_code == 400

    def test_rejects_critic_role(self, queue_client):
        client, q = queue_client
        r = client.post("/tasks", json={
            "title": "t", "description": "d",
            "repo": ["r"], "role": "critic",
        })
        assert r.status_code == 400

    def test_rejects_empty_title(self, queue_client):
        client, q = queue_client
        r = client.post("/tasks", json={
            "title": "  ", "description": "d", "repo": ["r"]
        })
        assert r.status_code == 400

    def test_rejects_invalid_role(self, queue_client):
        client, q = queue_client
        r = client.post("/tasks", json={
            "title": "t", "description": "d",
            "repo": ["r"], "role": "overlord",
        })
        assert r.status_code == 400

    def test_task_added_to_queue(self, queue_client):
        client, q = queue_client
        client.post("/tasks", json={
            "title": "queued task",
            "description": "desc",
            "repo": ["r"],
        })
        assert len(q.all_tasks()) == 1
        assert q.all_tasks()[0].title == "queued task"

    def test_task_list_sorted_ascending_priority(self, queue_client):
        client, q = queue_client
        client.post("/tasks", json={
            "title": "low", "description": "d",
            "repo": ["r"], "importance": 0.0, "urgency": 0.0,
        })
        client.post("/tasks", json={
            "title": "high", "description": "d",
            "repo": ["r"], "importance": 1.0, "urgency": 1.0,
        })
        r = client.get("/tasks")
        titles = [t["title"] for t in r.json()["tasks"]]
        assert titles[0] == "high"


# ---------------------------------------------------------------------------
# Task cancellation
# ---------------------------------------------------------------------------

class TestCancelTask:
    def test_cancel_sets_cancelled_status(self, queue_client):
        client, q = queue_client
        task = Task(title="t", description="d",
                    role=AgentRole.CODER, repo=["r"])
        q.add(task)
        r = client.delete(f"/tasks/{task.id}")
        assert r.status_code == 200
        assert q.get(task.id).status == TaskStatus.CANCELLED

    def test_cancel_idempotent_on_terminal_task(self, queue_client):
        client, q = queue_client
        task = Task(title="t", description="d",
                    role=AgentRole.CODER, repo=["r"],
                    status=TaskStatus.COMPLETE)
        q.add(task)
        r = client.delete(f"/tasks/{task.id}")
        assert r.status_code == 200
        assert "already" in r.json()["message"]

    def test_cancel_404_on_missing_task(self, queue_client):
        client, q = queue_client
        assert client.delete("/tasks/nonexistent").status_code == 404


# ---------------------------------------------------------------------------
# Turn limit response endpoint
# ---------------------------------------------------------------------------

class TestTurnLimitResponse:
    def _blocked_task(self, q) -> Task:
        task = Task(
            title="stuck task", description="desc",
            role=AgentRole.CODER, repo=["r"],
            status=TaskStatus.BLOCKED_BY_HUMAN,
        )
        task.notes = "[BLOCKED] Turn limit reached (50 turns)."
        q.add(task)
        return task

    def test_extend_returns_task_to_ready(self, queue_client):
        client, q = queue_client
        task = self._blocked_task(q)
        r = client.post(f"/tasks/{task.id}/turn-limit-response",
                        json={"action": "extend"})
        assert r.status_code == 200
        assert q.get(task.id).status == TaskStatus.READY

    def test_extend_increases_turn_limit(self, queue_client):
        client, q = queue_client
        task = self._blocked_task(q)
        r = client.post(f"/tasks/{task.id}/turn-limit-response",
                        json={"action": "extend", "extend_by": 25})
        assert r.json()["new_turn_limit"] == 25

    def test_extend_uses_config_default_when_extend_by_zero(self, queue_client):
        client, q = queue_client
        task = self._blocked_task(q)
        r = client.post(f"/tasks/{task.id}/turn-limit-response",
                        json={"action": "extend", "extend_by": 0})
        assert r.json()["new_turn_limit"] == 50  # matches cfg.agent_max_turns

    def test_extend_appends_note_to_context(self, queue_client):
        client, q = queue_client
        task = self._blocked_task(q)
        client.post(f"/tasks/{task.id}/turn-limit-response",
                    json={"action": "extend", "note": "Try a different approach."})
        messages = q.get(task.id).context_messages
        assert any("Try a different approach." in m.get("content", "")
                   for m in messages)

    def test_respec_returns_task_to_ready(self, queue_client):
        client, q = queue_client
        task = self._blocked_task(q)
        r = client.post(f"/tasks/{task.id}/turn-limit-response",
                        json={"action": "respec",
                              "note": "Focus only on the parse function."})
        assert r.status_code == 200
        assert q.get(task.id).status == TaskStatus.READY

    def test_respec_appends_note_to_context(self, queue_client):
        client, q = queue_client
        task = self._blocked_task(q)
        client.post(f"/tasks/{task.id}/turn-limit-response",
                    json={"action": "respec",
                          "note": "Focus only on the parse function."})
        messages = q.get(task.id).context_messages
        assert any("Focus only on the parse function." in m.get("content", "")
                   for m in messages)

    def test_respec_resets_turn_limit(self, queue_client):
        client, q = queue_client
        task = self._blocked_task(q)
        task.turn_limit = 75
        q.update(task)
        client.post(f"/tasks/{task.id}/turn-limit-response",
                    json={"action": "respec", "note": "Start fresh."})
        assert q.get(task.id).turn_limit == 0

    def test_respec_requires_note(self, queue_client):
        client, q = queue_client
        task = self._blocked_task(q)
        r = client.post(f"/tasks/{task.id}/turn-limit-response",
                        json={"action": "respec", "note": ""})
        assert r.status_code == 400

    def test_cancel_marks_task_cancelled(self, queue_client):
        client, q = queue_client
        task = self._blocked_task(q)
        r = client.post(f"/tasks/{task.id}/turn-limit-response",
                        json={"action": "cancel"})
        assert r.status_code == 200
        assert q.get(task.id).status == TaskStatus.CANCELLED

    def test_cancel_appends_note_when_given(self, queue_client):
        client, q = queue_client
        task = self._blocked_task(q)
        client.post(f"/tasks/{task.id}/turn-limit-response",
                    json={"action": "cancel", "note": "No longer needed."})
        assert "No longer needed." in q.get(task.id).notes

    def test_invalid_action_returns_400(self, queue_client):
        client, q = queue_client
        task = self._blocked_task(q)
        r = client.post(f"/tasks/{task.id}/turn-limit-response",
                        json={"action": "dance"})
        assert r.status_code == 400

    def test_requires_blocked_by_human_status(self, queue_client):
        client, q = queue_client
        task = Task(title="t", description="d",
                    role=AgentRole.CODER, repo=["r"],
                    status=TaskStatus.READY)
        q.add(task)
        r = client.post(f"/tasks/{task.id}/turn-limit-response",
                        json={"action": "extend"})
        assert r.status_code == 400

    def test_404_for_unknown_task(self, queue_client):
        client, q = queue_client
        r = client.post("/tasks/nonexistent/turn-limit-response",
                        json={"action": "extend"})
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Decomposition confirm endpoint
# ---------------------------------------------------------------------------

class TestDecompositionConfirm:
    def _manager_task(self, q) -> Task:
        task = Task(
            title="[Manager Review] planning",
            description="plan the work",
            role=AgentRole.MANAGER,
            repo=["r"],
        )
        task.started_at = "2026-01-01T00:00:00+00:00"
        q.add(task)
        return task

    def _parent_task(self, q, depth=3) -> Task:
        task = Task(
            title="parent task", description="desc",
            role=AgentRole.CODER, repo=["r"],
            depth=depth,
        )
        q.add(task)
        return task

    def test_confirm_increments_confirmed_depth(self, queue_client):
        client, q = queue_client
        parent = self._parent_task(q)
        mgr = self._manager_task(q)
        r = client.post(f"/tasks/{parent.id}/decomposition-confirm",
                        json={
                            "confirmation_id": "abc123",
                            "confirmed": True,
                            "reason": "",
                        })
        assert r.status_code == 200
        assert q.get(parent.id).decomposition_confirmed_depth == 1

    def test_confirm_returns_new_confirmed_depth(self, queue_client):
        client, q = queue_client
        parent = self._parent_task(q)
        self._manager_task(q)
        r = client.post(f"/tasks/{parent.id}/decomposition-confirm",
                        json={"confirmation_id": "x", "confirmed": True})
        assert r.json()["decomposition_confirmed_depth"] == 1

    def test_deny_requires_reason(self, queue_client):
        client, q = queue_client
        parent = self._parent_task(q)
        r = client.post(f"/tasks/{parent.id}/decomposition-confirm",
                        json={
                            "confirmation_id": "x",
                            "confirmed": False,
                            "reason": "",
                        })
        assert r.status_code == 400

    def test_deny_injects_message_into_manager_context(self, queue_client):
        client, q = queue_client
        parent = self._parent_task(q)
        mgr = self._manager_task(q)
        client.post(f"/tasks/{parent.id}/decomposition-confirm",
                    json={
                        "confirmation_id": "abc123",
                        "confirmed": False,
                        "reason": "Tasks are already small enough.",
                    })
        messages = q.get(mgr.id).context_messages
        assert any(
            "Tasks are already small enough." in m.get("content", "")
            for m in messages
        )

    def test_confirm_injects_approval_into_manager_context(self, queue_client):
        client, q = queue_client
        parent = self._parent_task(q)
        mgr = self._manager_task(q)
        client.post(f"/tasks/{parent.id}/decomposition-confirm",
                    json={"confirmation_id": "abc123", "confirmed": True})
        messages = q.get(mgr.id).context_messages
        assert any(
            "confirmed" in m.get("content", "").lower()
            for m in messages
        )

    def test_404_for_unknown_task(self, queue_client):
        client, q = queue_client
        r = client.post("/tasks/nonexistent/decomposition-confirm",
                        json={"confirmation_id": "x", "confirmed": True})
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Fixtures for interjection/answer tests
# ---------------------------------------------------------------------------

@pytest.fixture
def queue_workspace_with_state(tmp_path):
    """Workspace with InMemoryTaskRepository and workspace state wired in."""
    ws = tmp_path / "workspace"
    (ws / ".matrixmouse").mkdir(parents=True)
    q = InMemoryTaskRepository()
    ws_state_repo = InMemoryWorkspaceStateRepository()
    cfg = MagicMock()
    cfg.agent_max_turns = 50
    cfg.critic_max_turns = 5
    configure(
        queue=q, status={}, workspace_root=ws,
        config=cfg, ws_state_repo=ws_state_repo
    )
    return ws, q, ws_state_repo


@pytest.fixture
def state_client(queue_workspace_with_state):
    ws, q, ws_state_repo = queue_workspace_with_state
    return TestClient(app, raise_server_exceptions=False), q, ws, ws_state_repo


# ---------------------------------------------------------------------------
# POST /interject/workspace
# ---------------------------------------------------------------------------

class TestInterjectionWorkspace:
    def test_creates_manager_task(self, state_client):
        client, q, ws, ws_state_repo = state_client
        r = client.post("/interject/workspace",
                        json={"message": "Please review the architecture."})
        assert r.status_code == 201
        manager_tasks = [t for t in q.all_tasks()
                         if t.role == AgentRole.MANAGER]
        assert len(manager_tasks) == 1

    def test_returns_manager_task_id(self, state_client):
        client, q, ws, ws_state_repo = state_client
        r = client.post("/interject/workspace",
                        json={"message": "Rethink the approach."})
        assert r.json()["ok"] is True
        task_id = r.json()["manager_task_id"]
        assert q.get(task_id) is not None

    def test_created_task_has_preempt_true(self, state_client):
        client, q, ws, ws_state_repo = state_client
        r = client.post("/interject/workspace",
                        json={"message": "Urgent direction change."})
        task_id = r.json()["manager_task_id"]
        task = q.get(task_id)
        assert task is not None
        assert task.preempt is True

    def test_created_task_contains_message(self, state_client):
        client, q, ws, ws_state_repo = state_client
        r = client.post("/interject/workspace",
                        json={"message": "Switch to a different database."})
        task_id = r.json()["manager_task_id"]
        task = q.get(task_id)
        assert task is not None
        assert "Switch to a different database." in task.description

    def test_empty_message_returns_400(self, state_client):
        client, q, ws, ws_state_repo = state_client
        r = client.post("/interject/workspace", json={"message": ""})
        assert r.status_code == 400

    def test_task_has_no_repo_scope(self, state_client):
        client, q, ws, ws_state_repo = state_client
        r = client.post("/interject/workspace",
                        json={"message": "Global direction."})
        task_id = r.json()["manager_task_id"]
        task = q.get(task_id)
        assert task is not None
        assert task.repo == []


# ---------------------------------------------------------------------------
# POST /interject/repo/{repo_name}
# ---------------------------------------------------------------------------

class TestInterjectionRepo:
    def test_creates_manager_task_scoped_to_repo(self, state_client):
        client, q, ws, ws_state_repo = state_client
        r = client.post("/interject/repo/my-repo",
                        json={"message": "Refactor the parser."})
        assert r.status_code == 201
        task_id = r.json()["manager_task_id"]
        task = q.get(task_id)
        assert task is not None
        assert "my-repo" in task.repo

    def test_returns_repo_in_response(self, state_client):
        client, q, ws, ws_state_repo = state_client
        r = client.post("/interject/repo/special-repo",
                        json={"message": "Fix the login flow."})
        assert r.json()["repo"] == "special-repo"

    def test_created_task_has_preempt_true(self, state_client):
        client, q, ws, ws_state_repo = state_client
        r = client.post("/interject/repo/my-repo",
                        json={"message": "Urgent fix needed."})
        task_id = r.json()["manager_task_id"]
        task = q.get(task_id)
        assert task is not None
        assert task.preempt is True

    def test_created_task_contains_message(self, state_client):
        client, q, ws, ws_state_repo = state_client
        r = client.post("/interject/repo/my-repo",
                        json={"message": "Use async handlers everywhere."})
        task_id = r.json()["manager_task_id"]
        task = q.get(task_id)
        assert task is not None
        assert "Use async handlers everywhere." in task.description

    def test_empty_message_returns_400(self, state_client):
        client, q, ws, ws_state_repo = state_client
        r = client.post("/interject/repo/my-repo", json={"message": ""})
        assert r.status_code == 400

    def test_task_role_is_manager(self, state_client):
        client, q, ws, ws_state_repo = state_client
        r = client.post("/interject/repo/my-repo",
                        json={"message": "Add rate limiting."})
        task_id = r.json()["manager_task_id"]
        task = q.get(task_id)
        assert task is not None
        assert task.role == AgentRole.MANAGER


# ---------------------------------------------------------------------------
# POST /tasks/{task_id}/interject
# ---------------------------------------------------------------------------

class TestTaskInterject:
    def test_appends_message_to_context(self, state_client):
        client, q, ws, ws_state_repo = state_client
        task = Task(title="t", description="d",
                    role=AgentRole.CODER, repo=["r"])
        q.add(task)
        r = client.post(f"/tasks/{task.id}/interject",
                        json={"message": "Use the second approach."})
        assert r.status_code == 200
        updated = q.get(task.id)
        assert updated is not None
        assert any("Use the second approach." in m.get("content", "")
                   for m in updated.context_messages)

    def test_message_has_operator_prefix(self, state_client):
        client, q, ws, ws_state_repo = state_client
        task = Task(title="t", description="d",
                    role=AgentRole.CODER, repo=["r"])
        q.add(task)
        client.post(f"/tasks/{task.id}/interject",
                    json={"message": "Change the approach."})
        updated = q.get(task.id)
        assert updated is not None
        msg = next(m for m in updated.context_messages
                   if "Change the approach." in m.get("content", ""))
        assert "operator" in msg["content"].lower() or \
               "Human" in msg["content"]

    def test_message_role_is_user(self, state_client):
        client, q, ws, ws_state_repo = state_client
        task = Task(title="t", description="d",
                    role=AgentRole.CODER, repo=["r"])
        q.add(task)
        client.post(f"/tasks/{task.id}/interject",
                    json={"message": "Note this."})
        updated = q.get(task.id)
        assert updated is not None
        assert any(m.get("role") == "user"
                   for m in updated.context_messages)

    def test_does_not_change_task_status(self, state_client):
        client, q, ws, ws_state_repo = state_client
        task = Task(title="t", description="d",
                    role=AgentRole.CODER, repo=["r"],
                    status=TaskStatus.RUNNING)
        q.add(task)
        client.post(f"/tasks/{task.id}/interject",
                    json={"message": "Keep going."})
        updated = q.get(task.id)
        assert updated is not None
        assert updated.status == TaskStatus.RUNNING

    def test_empty_message_returns_400(self, state_client):
        client, q, ws, ws_state_repo = state_client
        task = Task(title="t", description="d",
                    role=AgentRole.CODER, repo=["r"])
        q.add(task)
        r = client.post(f"/tasks/{task.id}/interject",
                        json={"message": ""})
        assert r.status_code == 400

    def test_terminal_task_returns_400(self, state_client):
        client, q, ws, ws_state_repo = state_client
        task = Task(title="t", description="d",
                    role=AgentRole.CODER, repo=["r"],
                    status=TaskStatus.COMPLETE)
        q.add(task)
        r = client.post(f"/tasks/{task.id}/interject",
                        json={"message": "Too late."})
        assert r.status_code == 400

    def test_404_for_unknown_task(self, state_client):
        client, q, ws, ws_state_repo = state_client
        r = client.post("/tasks/nonexistent/interject",
                        json={"message": "Hello."})
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# POST /tasks/{task_id}/answer
# ---------------------------------------------------------------------------

class TestTaskAnswer:
    def test_appends_answer_to_context(self, state_client):
        client, q, ws, ws_state_repo = state_client
        task = Task(title="t", description="d",
                    role=AgentRole.CODER, repo=["r"],
                    status=TaskStatus.BLOCKED_BY_HUMAN)
        task.pending_question = "Which approach?"
        q.add(task)
        client.post(f"/tasks/{task.id}/answer",
                    json={"message": "Use the iterative approach."})
        updated = q.get(task.id)
        assert updated is not None
        assert any("Use the iterative approach." in m.get("content", "")
                   for m in updated.context_messages)

    def test_unblocks_blocked_by_human_task(self, state_client):
        client, q, ws, ws_state_repo = state_client
        task = Task(title="t", description="d",
                    role=AgentRole.CODER, repo=["r"],
                    status=TaskStatus.BLOCKED_BY_HUMAN)
        task.pending_question = "Which approach?"
        q.add(task)
        r = client.post(f"/tasks/{task.id}/answer",
                        json={"message": "Use approach B."})
        assert r.json()["unblocked"] is True
        updated = q.get(task.id)
        assert updated is not None
        assert updated.status == TaskStatus.READY

    def test_clears_pending_question(self, state_client):
        client, q, ws, ws_state_repo = state_client
        task = Task(title="t", description="d",
                    role=AgentRole.CODER, repo=["r"],
                    status=TaskStatus.BLOCKED_BY_HUMAN)
        task.pending_question = "What format?"
        q.add(task)
        client.post(f"/tasks/{task.id}/answer",
                    json={"message": "Use JSON."})
        updated = q.get(task.id)
        assert updated is not None
        assert updated.pending_question == ""

    def test_does_not_unblock_running_task(self, state_client):
        client, q, ws, ws_state_repo = state_client
        task = Task(title="t", description="d",
                    role=AgentRole.CODER, repo=["r"],
                    status=TaskStatus.RUNNING)
        q.add(task)
        r = client.post(f"/tasks/{task.id}/answer",
                        json={"message": "Additional context."})
        assert r.json()["unblocked"] is False
        updated = q.get(task.id)
        assert updated is not None
        assert updated.status == TaskStatus.RUNNING

    def test_cancels_stale_clarification_manager_task(self, state_client):
        client, q, ws, ws_state_repo = state_client

        task = Task(title="blocked", description="d",
                    role=AgentRole.CODER, repo=["r"],
                    status=TaskStatus.BLOCKED_BY_HUMAN)
        task.pending_question = "Which approach?"
        q.add(task)

        mgr_task = Task(title="[Stale Clarification] ...",
                        description="d", role=AgentRole.MANAGER, repo=["r"])
        q.add(mgr_task)

        ws_state_repo.register_stale_clarification_task(task.id, mgr_task.id)

        client.post(f"/tasks/{task.id}/answer",
                    json={"message": "Use approach B."})

        updated_mgr = q.get(mgr_task.id)
        assert updated_mgr is not None
        assert updated_mgr.status == TaskStatus.CANCELLED

    def test_empty_message_returns_400(self, state_client):
        client, q, ws, ws_state_repo = state_client
        task = Task(title="t", description="d",
                    role=AgentRole.CODER, repo=["r"])
        q.add(task)
        r = client.post(f"/tasks/{task.id}/answer",
                        json={"message": ""})
        assert r.status_code == 400

    def test_404_for_unknown_task(self, state_client):
        client, q, ws, ws_state_repo = state_client
        r = client.post("/tasks/nonexistent/answer",
                        json={"message": "Hello."})
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# POST /tasks/{task_id}/critic-review-response
# ---------------------------------------------------------------------------

class TestCriticReviewResponse:
    def _setup_critic_review(self, q):
        reviewed = Task(title="reviewed", description="d",
                        role=AgentRole.CODER, repo=["r"])
        critic = Task(title="[Critic Review] reviewed",
                    description="d", role=AgentRole.CRITIC, repo=["r"],
                    status=TaskStatus.BLOCKED_BY_HUMAN)
        critic.reviews_task_id = reviewed.id
        q.add(reviewed)
        q.add(critic)
        q.add_dependency(critic.id, reviewed.id)
        return reviewed, critic

    def test_approve_task_marks_reviewed_complete(self, state_client):
        client, q, ws, ws_state_repo = state_client
        reviewed, critic = self._setup_critic_review(q)
        r = client.post(f"/tasks/{critic.id}/critic-review-response",
                        json={"action": "approve_task"})
        assert r.status_code == 200
        updated = q.get(reviewed.id)
        assert updated is not None
        assert updated.status == TaskStatus.COMPLETE

    def test_approve_task_cancels_critic(self, state_client):
        client, q, ws, ws_state_repo = state_client
        reviewed, critic = self._setup_critic_review(q)
        client.post(f"/tasks/{critic.id}/critic-review-response",
                    json={"action": "approve_task"})
        updated_critic = q.get(critic.id)
        assert updated_critic is not None
        assert updated_critic.status == TaskStatus.CANCELLED

    def test_approve_task_appends_feedback_when_provided(self, state_client):
        client, q, ws, ws_state_repo = state_client
        reviewed, critic = self._setup_critic_review(q)
        client.post(f"/tasks/{critic.id}/critic-review-response",
                    json={"action": "approve_task",
                          "feedback": "Great work, minor style issues noted."})
        updated = q.get(reviewed.id)
        assert updated is not None
        assert any("Great work, minor style issues noted." in
                   m.get("content", "")
                   for m in updated.context_messages)

    def test_extend_critic_returns_critic_to_ready(self, state_client):
        client, q, ws, ws_state_repo = state_client
        reviewed, critic = self._setup_critic_review(q)
        r = client.post(f"/tasks/{critic.id}/critic-review-response",
                        json={"action": "extend_critic"})
        assert r.status_code == 200
        updated_critic = q.get(critic.id)
        assert updated_critic is not None
        assert updated_critic.status == TaskStatus.READY

    def test_extend_critic_increases_turn_limit(self, state_client):
        client, q, ws, ws_state_repo = state_client
        reviewed, critic = self._setup_critic_review(q)
        r = client.post(f"/tasks/{critic.id}/critic-review-response",
                        json={"action": "extend_critic"})
        updated_critic = q.get(critic.id)
        assert updated_critic is not None
        assert updated_critic.turn_limit > 0

    def test_extend_critic_appends_feedback_when_provided(self, state_client):
        client, q, ws, ws_state_repo = state_client
        reviewed, critic = self._setup_critic_review(q)
        client.post(f"/tasks/{critic.id}/critic-review-response",
                    json={"action": "extend_critic",
                          "feedback": "Focus on error handling."})
        updated_critic = q.get(critic.id)
        assert updated_critic is not None
        assert any("Focus on error handling." in m.get("content", "")
                   for m in updated_critic.context_messages)

    def test_block_task_cancels_critic(self, state_client):
        client, q, ws, ws_state_repo = state_client
        reviewed, critic = self._setup_critic_review(q)
        r = client.post(f"/tasks/{critic.id}/critic-review-response",
                        json={"action": "block_task"})
        assert r.status_code == 200
        updated_critic = q.get(critic.id)
        assert updated_critic is not None
        assert updated_critic.status == TaskStatus.CANCELLED

    def test_block_task_moves_reviewed_to_blocked_by_human(self, state_client):
        client, q, ws, ws_state_repo = state_client
        reviewed, critic = self._setup_critic_review(q)
        client.post(f"/tasks/{critic.id}/critic-review-response",
                    json={"action": "block_task"})
        updated = q.get(reviewed.id)
        assert updated is not None
        assert updated.status == TaskStatus.BLOCKED_BY_HUMAN

    def test_block_task_appends_feedback_to_notes(self, state_client):
        client, q, ws, ws_state_repo = state_client
        reviewed, critic = self._setup_critic_review(q)
        client.post(f"/tasks/{critic.id}/critic-review-response",
                    json={"action": "block_task",
                          "feedback": "Needs complete rewrite."})
        updated = q.get(reviewed.id)
        assert updated is not None
        assert "Needs complete rewrite." in updated.notes

    def test_invalid_action_returns_400(self, state_client):
        client, q, ws, ws_state_repo = state_client
        reviewed, critic = self._setup_critic_review(q)
        r = client.post(f"/tasks/{critic.id}/critic-review-response",
                        json={"action": "invalid"})
        assert r.status_code == 400

    def test_requires_blocked_by_human_status(self, state_client):
        client, q, ws, ws_state_repo = state_client
        reviewed, critic = self._setup_critic_review(q)
        critic.status = TaskStatus.READY
        q.update(critic)
        r = client.post(f"/tasks/{critic.id}/critic-review-response",
                        json={"action": "approve_task"})
        assert r.status_code == 400

    def test_requires_reviews_task_id(self, state_client):
        client, q, ws, ws_state_repo = state_client
        task = Task(title="t", description="d",
                    role=AgentRole.CRITIC, repo=["r"],
                    status=TaskStatus.BLOCKED_BY_HUMAN)
        q.add(task)
        r = client.post(f"/tasks/{task.id}/critic-review-response",
                        json={"action": "approve_task"})
        assert r.status_code == 400

    def test_404_for_unknown_task(self, state_client):
        client, q, ws, ws_state_repo = state_client
        r = client.post("/tasks/nonexistent/critic-review-response",
                        json={"action": "approve_task"})
        assert r.status_code == 404

    def test_404_when_reviewed_task_missing(self, state_client):
        client, q, ws, ws_state_repo = state_client
        critic = Task(title="critic", description="d",
                      role=AgentRole.CRITIC, repo=["r"],
                      status=TaskStatus.BLOCKED_BY_HUMAN)
        critic.reviews_task_id = "nonexistent-reviewed-task"
        q.add(critic)
        r = client.post(f"/tasks/{critic.id}/critic-review-response",
                        json={"action": "approve_task"})
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Deprecated POST /interject
# TODO: Remove these when we remove POST /interject soon
# ---------------------------------------------------------------------------

class TestDeprecatedInterject:
    def test_still_returns_200(self, client):
        from matrixmouse import comms as comms_module
        mock_manager = MagicMock()
        with patch.object(comms_module, "get_manager",
                          return_value=mock_manager):
            r = client.post("/interject",
                            json={"message": "Hello."})
        assert r.status_code == 200

    def test_empty_message_returns_400(self, client):
        from matrixmouse import comms as comms_module
        mock_manager = MagicMock()
        with patch.object(comms_module, "get_manager",
                          return_value=mock_manager):
            r = client.post("/interject", json={"message": ""})
        assert r.status_code == 400