"""
tests/test_api.py

Tests for matrixmouse.api — focused on the new control endpoints added
in the refactor/web-server branch:

    POST /stop          Soft stop flag
    POST /kill          E-STOP lockfile + SIGTERM
    GET  /estop         E-STOP status
    POST /estop/reset   Remove lockfile

Existing api tests in this file (if any) are unaffected — all new tests
use isolated temp directories and mock the signal so no real SIGTERM is sent.
"""

import json
import os
import signal
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from matrixmouse.api import (
    app,
    configure,
    clear_stop_requested,
    is_stop_requested,
    _stop_requested,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_stop_flag():
    """Ensure the stop flag is clear before and after every test."""
    _stop_requested.clear()
    yield
    _stop_requested.clear()


@pytest.fixture
def workspace(tmp_path):
    """Provide a temporary workspace with .matrixmouse/ dir and configure api."""
    ws = tmp_path / "workspace"
    (ws / ".matrixmouse").mkdir(parents=True)

    # Minimal config mock
    config_mock = MagicMock()
    configure(
        queue=MagicMock(),
        status={},
        workspace_root=ws,
        config=config_mock,
    )
    return ws


@pytest.fixture
def client(workspace):
    """TestClient with workspace configured."""
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# POST /stop — soft stop
# ---------------------------------------------------------------------------

class TestSoftStop:
    def test_sets_stop_flag(self, client):
        assert not is_stop_requested()
        r = client.post("/stop")
        assert r.status_code == 200
        assert r.json()["ok"] is True
        assert is_stop_requested()

    def test_returns_message(self, client):
        r = client.post("/stop")
        assert "message" in r.json()

    def test_idempotent(self, client):
        """Calling /stop twice is fine — flag stays set."""
        client.post("/stop")
        r = client.post("/stop")
        assert r.status_code == 200
        assert is_stop_requested()

    def test_clear_stop_requested(self, client):
        client.post("/stop")
        assert is_stop_requested()
        clear_stop_requested()
        assert not is_stop_requested()


# ---------------------------------------------------------------------------
# GET /estop — status check
# ---------------------------------------------------------------------------

class TestEstopStatus:
    def test_not_engaged_initially(self, client, workspace):
        r = client.get("/estop")
        assert r.status_code == 200
        data = r.json()
        assert data["engaged"] is False
        assert data["message"] is None

    def test_engaged_when_lockfile_exists(self, client, workspace):
        lockfile = workspace / ".matrixmouse" / "ESTOP"
        lockfile.write_text("E-STOP engaged at 2026-01-01T00:00:00Z\n")
        r = client.get("/estop")
        data = r.json()
        assert data["engaged"] is True
        assert "2026-01-01" in data["message"]

    def test_engaged_lockfile_unreadable(self, client, workspace, monkeypatch):
        """If lockfile exists but can't be read, still reports engaged."""
        lockfile = workspace / ".matrixmouse" / "ESTOP"
        lockfile.write_text("something")
        # Patch Path.read_text to raise
        original_read = Path.read_text
        def bad_read(self, *a, **kw):
            if self == lockfile:
                raise OSError("permission denied")
            return original_read(self, *a, **kw)
        monkeypatch.setattr(Path, "read_text", bad_read)
        r = client.get("/estop")
        assert r.json()["engaged"] is True


# ---------------------------------------------------------------------------
# POST /kill — E-STOP engagement
# ---------------------------------------------------------------------------

class TestKill:
    def test_writes_lockfile(self, client, workspace):
        lockfile = workspace / ".matrixmouse" / "ESTOP"
        assert not lockfile.exists()

        with patch("os.kill") as mock_kill:
            r = client.post("/kill")

        assert lockfile.exists()
        content = lockfile.read_text()
        assert "ESTOP" in content
        assert "systemctl" in content

    def test_sends_sigterm_to_self(self, client, workspace):
        with patch("os.kill") as mock_kill:
            client.post("/kill")
        mock_kill.assert_called_once_with(os.getpid(), signal.SIGTERM)

    def test_lockfile_contains_timestamp(self, client, workspace):
        with patch("os.kill"):
            client.post("/kill")
        lockfile = workspace / ".matrixmouse" / "ESTOP"
        content = lockfile.read_text()
        # ISO timestamp format check
        assert "T" in content  # e.g. 2026-03-05T04:00:00+00:00

    def test_estop_status_engaged_after_kill(self, client, workspace):
        with patch("os.kill"):
            client.post("/kill")
        r = client.get("/estop")
        assert r.json()["engaged"] is True

    def test_returns_503_without_workspace(self):
        """If workspace is not configured, /kill returns 503."""
        configure(queue=MagicMock(), status={}, workspace_root=None, config=MagicMock())
        c = TestClient(app, raise_server_exceptions=False)
        r = c.post("/kill")
        assert r.status_code == 503
        # Restore for other tests
        configure(queue=MagicMock(), status={}, workspace_root=None, config=MagicMock())


# ---------------------------------------------------------------------------
# POST /estop/reset — remove lockfile
# ---------------------------------------------------------------------------

class TestEstopReset:
    def test_removes_lockfile(self, client, workspace):
        lockfile = workspace / ".matrixmouse" / "ESTOP"
        lockfile.write_text("engaged")
        r = client.post("/estop/reset")
        assert r.status_code == 200
        assert r.json()["ok"] is True
        assert not lockfile.exists()

    def test_idempotent_when_not_engaged(self, client, workspace):
        """Reset when not engaged returns ok, does not error."""
        r = client.post("/estop/reset")
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_estop_not_engaged_after_reset(self, client, workspace):
        lockfile = workspace / ".matrixmouse" / "ESTOP"
        lockfile.write_text("engaged")
        client.post("/estop/reset")
        r = client.get("/estop")
        assert r.json()["engaged"] is False

    def test_returns_503_without_workspace(self):
        configure(queue=MagicMock(), status={}, workspace_root=None, config=MagicMock())
        c = TestClient(app, raise_server_exceptions=False)
        r = c.post("/estop/reset")
        assert r.status_code == 503


# ---------------------------------------------------------------------------
# ESTOP lockfile survival — simulates what _service.py checks at startup
# ---------------------------------------------------------------------------

class TestEstopLockfileSurvival:
    def test_lockfile_persists_across_reset_and_kill_sequence(self, workspace):
        """
        Full cycle: kill → lockfile exists → reset → lockfile gone.
        This mirrors the operator workflow after an E-STOP event.
        """
        lockfile = workspace / ".matrixmouse" / "ESTOP"

        client = TestClient(app, raise_server_exceptions=False)

        # Engage E-STOP
        with patch("os.kill"):
            r = client.post("/kill")
        assert r.status_code == 200
        assert lockfile.exists()

        # Status shows engaged
        assert client.get("/estop").json()["engaged"] is True

        # Reset
        r = client.post("/estop/reset")
        assert r.status_code == 200
        assert not lockfile.exists()

        # Status shows clear
        assert client.get("/estop").json()["engaged"] is False
