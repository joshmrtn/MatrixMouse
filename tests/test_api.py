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
from matrixmouse.task import AgentRole, Task, TaskStatus, TaskQueue


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
    configure(queue=MagicMock(), status={}, workspace_root=ws, config=MagicMock())
    return ws


@pytest.fixture
def client(workspace):
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Fixtures for task-related tests
# ---------------------------------------------------------------------------

@pytest.fixture
def queue_workspace(tmp_path):
    """Workspace with a real TaskQueue wired into the API."""
    ws = tmp_path / "workspace"
    (ws / ".matrixmouse").mkdir(parents=True)
    tasks_file = ws / ".matrixmouse" / "tasks.json"
    tasks_file.write_text("[]")
    q = TaskQueue(tasks_file)
    cfg = MagicMock()
    cfg.agent_max_turns = 50
    configure(queue=q, status={}, workspace_root=ws, config=cfg)
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
        configure(queue=MagicMock(), status={}, workspace_root=None, config=MagicMock())
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
        configure(queue=MagicMock(), status={}, workspace_root=None, config=MagicMock())
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