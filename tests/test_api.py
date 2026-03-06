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
