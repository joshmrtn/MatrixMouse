"""
tests/frontend/test_server.py

Test server fixture that runs the real MatrixMouse API with mocked backend components.
"""

import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator

import uvicorn

from matrixmouse.api import app, configure, notify_task_available
from matrixmouse.config import MatrixMouseConfig, MatrixMousePaths
from matrixmouse.inference.token_budget import TokenBudgetTracker
from matrixmouse.repository.memory_task_repository import InMemoryTaskRepository
from matrixmouse.repository.memory_workspace_state_repository import (
    InMemoryWorkspaceStateRepository,
)
from matrixmouse.scheduling import Scheduler

from .mock_llm import FakeLLMBackend


class TestMatrixMouseServer:
    """
    Real MatrixMouse server with mocked backend components for testing.
    
    Provides:
    - Real FastAPI app with all endpoints
    - Real WebSocket event streaming
    - Mocked LLM backend (deterministic responses)
    - In-memory repositories (isolated per test)
    - Test control methods for manipulating state
    """
    
    def __init__(self, port: int = 8765, llm_responses: list[str] | None = None):
        self.port = port
        self.config = MatrixMouseConfig(local_only=True)
        self.paths = MatrixMousePaths(workspace_root=Path("/tmp/test-workspace"))
        
        # Create workspace dir
        self.paths.workspace_root.mkdir(parents=True, exist_ok=True)
        
        # In-memory repositories (isolated per test)
        self.task_repo = InMemoryTaskRepository()
        self.ws_state_repo = InMemoryWorkspaceStateRepository()
        
        # Mocked LLM backend
        self.fake_llm = FakeLLMBackend(llm_responses or [])
        
        # Scheduler (lightweight - doesn't hold repos)
        self.scheduler = Scheduler(
            config=self.config,
            stale_clarification_callback=None,
        )
        
        # Status dict
        self.status = {
            "idle": True,
            "stopped": False,
            "blocked": False,
            "task": None,
            "phase": None,
            "model": None,
            "turns": 0,
        }
        
        # Budget tracker (uses in-memory repo)
        self.budget_tracker = TokenBudgetTracker(ws_state_repo=self.ws_state_repo)
        
        # Server instance
        self._server_thread: threading.Thread | None = None
        
        # Configure the API app
        self._configure_api()
    
    def _configure_api(self):
        """Configure the FastAPI app with our mocked components."""
        from matrixmouse import comms as comms_module
        from matrixmouse.server import _register_routes
        
        configure(
            queue=self.task_repo,
            scheduler=self.scheduler,
            status=self.status,
            workspace_root=self.paths.workspace_root,
            config=self.config,
            ws_state_repo=self.ws_state_repo,
            budget_tracker=self.budget_tracker,
        )
        
        # Register the index and WebSocket routes
        _register_routes(app, comms_module)
    
    def start(self):
        """Start the server in a background thread."""
        if self._server_thread is not None:
            return
        
        def run_server():
            uvicorn.run(
                app,
                host="127.0.0.1",
                port=self.port,
                log_level="error",
                access_log=False,
            )
        
        self._server_thread = threading.Thread(target=run_server, daemon=True)
        self._server_thread.start()
        
        # Wait for server to start
        time.sleep(1)
    
    def stop(self):
        """Stop the server."""
        # Note: uvicorn doesn't have a clean shutdown from outside
        # The thread will die when the process exits (daemon=True)
        self._server_thread = None
    
    def reset(self):
        """Reset all state for a clean test."""
        self.task_repo = InMemoryTaskRepository()
        self.ws_state_repo = InMemoryWorkspaceStateRepository()
        self.fake_llm.reset()
        self.status = {
            "idle": True,
            "stopped": False,
            "blocked": False,
            "task": None,
            "phase": None,
            "model": None,
            "turns": 0,
        }
        self._configure_api()
    
    def set_llm_responses(self, responses: list[str]):
        """Set LLM responses for the next test."""
        self.fake_llm.reset(responses)
    
    def create_task(self, **kwargs) -> dict:
        """Create a task and return its dict representation."""
        from matrixmouse.task import Task, TaskStatus, AgentRole
        
        task = Task(
            title=kwargs.get("title", "Test Task"),
            description=kwargs.get("description", ""),
            repo=kwargs.get("repo", []),
            role=kwargs.get("role", AgentRole.CODER),
            status=kwargs.get("status", TaskStatus.READY),
            importance=kwargs.get("importance", 0.5),
            urgency=kwargs.get("urgency", 0.5),
        )
        
        if kwargs.get("parent_task_id"):
            task.parent_task_id = kwargs["parent_task_id"]
        
        if kwargs.get("status") == "blocked_by_human":
            task.status = TaskStatus.BLOCKED_BY_HUMAN
            if kwargs.get("blocking_reason"):
                task.notes = kwargs["blocking_reason"]
        
        if kwargs.get("context_messages"):
            task.context_messages = kwargs["context_messages"]
        
        self.task_repo.add(task)
        notify_task_available()
        
        return task.to_dict()
    
    def emit_event(self, event_type: str, data: dict):
        """Emit a WebSocket event."""
        from matrixmouse import comms as comms_module
        
        manager = comms_module.get_manager()
        if manager:
            manager.emit(event_type, data)
    
    @contextmanager
    def run(self) -> Generator["TestMatrixMouseServer", None, None]:
        """Context manager for running the server."""
        self.start()
        try:
            yield self
        finally:
            self.stop()
