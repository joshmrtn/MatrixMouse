"""
tests/frontend/mock_server.py

Mock FastAPI server for testing the frontend.
Provides all MatrixMouse API endpoints plus special test control endpoints.
"""

import asyncio
import json
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from matrixmouse.repository.memory_task_repository import InMemoryTaskRepository
from matrixmouse.repository.memory_workspace_state_repository import (
    InMemoryWorkspaceStateRepository,
)
from matrixmouse.task import Task, TaskStatus, AgentRole
from matrixmouse.comms import CommsManager


# ---------------------------------------------------------------------------
# Mock Server Class
# ---------------------------------------------------------------------------

class MockMatrixMouseServer:
    """
    Mock MatrixMouse server for frontend testing.
    
    Provides:
    - All standard MatrixMouse API endpoints
    - Test control endpoints for triggering events
    - WebSocket event broadcasting
    """
    
    def __init__(self, port: int = 8765):
        self.port = port
        self.app = FastAPI(title="Mock MatrixMouse")
        
        # In-memory repositories
        self.task_repo = InMemoryTaskRepository()
        self.ws_state_repo = InMemoryWorkspaceStateRepository()
        
        # Comms manager for WebSocket events (use mock config)
        from matrixmouse.config import MatrixMouseConfig
        mock_config = MatrixMouseConfig()
        self.comms = CommsManager(mock_config)
        
        # Status dict (mimics real orchestrator status)
        self.status = {
            "idle": True,
            "stopped": False,
            "blocked": False,
            "task": None,
            "phase": None,
            "model": None,
            "turns": 0,
        }
        
        # Register routes
        self._register_routes()
        
        # Server thread
        self._server_thread: threading.Thread | None = None
        self._server_instance: Any | None = None
    
    def _register_routes(self):
        """Register all API routes."""
        
        # Standard MatrixMouse endpoints (simplified)
        @self.app.get("/health")
        async def health():
            return {"ok": True, "timestamp": datetime.now(timezone.utc).isoformat()}
        
        @self.app.get("/status")
        async def get_status():
            return dict(self.status)
        
        @self.app.get("/tasks")
        async def list_tasks(status: str | None = None, all: bool = False):
            tasks = self.task_repo.all_tasks()
            
            if not all:
                terminal = {"complete", "cancelled"}
                tasks = [t for t in tasks if t.status.value not in terminal]
            
            if status:
                tasks = [t for t in tasks if t.status.value == status]
            
            tasks.sort(key=lambda t: t.priority_score())
            
            return {
                "tasks": [t.to_dict() for t in tasks],
                "count": len(tasks),
            }
        
        @self.app.get("/tasks/{task_id}")
        async def get_task(task_id: str):
            task = self.task_repo.get(task_id)
            if task is None:
                raise HTTPException(status_code=404, detail="Task not found")
            return task.to_dict()
        
        @self.app.post("/tasks", status_code=201)
        async def create_task(body: TaskCreateRequest):
            task = Task(
                title=body.title,
                description=body.description,
                repo=body.repo or [],
                role=AgentRole(body.role.lower()) if body.role else AgentRole.CODER,
                status=TaskStatus.READY,
                importance=body.importance or 0.5,
                urgency=body.urgency or 0.5,
            )
            self.task_repo.add(task)
            
            # Emit task tree update
            self._emit_event("task_tree_update", {
                "tasks": [t.to_dict() for t in self.task_repo.all_tasks()],
            })
            
            return task.to_dict()
        
        @self.app.post("/tasks/{task_id}/interject")
        async def interject_task(task_id: str, body: MessageRequest):
            task = self.task_repo.get(task_id)
            if task is None:
                raise HTTPException(status_code=404, detail="Task not found")
            
            task.context_messages.append({
                "role": "user",
                "content": body.message,
            })
            self.task_repo.update(task)
            
            return {"ok": True, "task_id": task_id}
        
        @self.app.post("/tasks/{task_id}/answer")
        async def answer_task(task_id: str, body: MessageRequest):
            task = self.task_repo.get(task_id)
            if task is None:
                raise HTTPException(status_code=404, detail="Task not found")
            
            task.context_messages.append({"role": "user", "content": body.message})
            task.pending_question = ""
            
            if task.status == TaskStatus.BLOCKED_BY_HUMAN:
                task.status = TaskStatus.READY
            
            self.task_repo.update(task)
            
            return {"ok": True, "task_id": task_id, "unblocked": True}
        
        @self.app.post("/tasks/{task_id}/decision")
        async def task_decision(task_id: str, body: DecisionRequest):
            task = self.task_repo.get(task_id)
            if task is None:
                raise HTTPException(status_code=404, detail="Task not found")
            
            # Simplified decision handling - just unblock the task
            task.status = TaskStatus.READY
            task.context_messages.append({
                "role": "user",
                "content": f"[Decision: {body.decision_type} = {body.choice}]\n{body.note}",
            })
            self.task_repo.update(task)
            
            return {"ok": True, "action": body.choice}
        
        @self.app.get("/repos")
        async def list_repos():
            # Return mock repos
            return {"repos": []}
        
        @self.app.get("/blocked")
        async def get_blocked():
            tasks = self.task_repo.all_tasks()
            
            report = {
                "human": [],
                "dependencies": [],
                "waiting": [],
            }
            
            for task in tasks:
                if task.status == TaskStatus.BLOCKED_BY_HUMAN:
                    report["human"].append({
                        "id": task.id,
                        "title": task.title,
                        "blocking_reason": task.notes or "Awaiting human input",
                    })
                elif task.status == TaskStatus.BLOCKED_BY_TASK:
                    report["dependencies"].append({
                        "id": task.id,
                        "title": task.title,
                        "blocking_reason": "Blocked by dependencies",
                    })
                elif task.status == TaskStatus.WAITING:
                    report["waiting"].append({
                        "id": task.id,
                        "title": task.title,
                        "blocking_reason": task.wait_reason or "Waiting on conditions",
                    })
            
            return {"report": report}
        
        @self.app.get("/pending")
        async def get_pending():
            question = self.comms.get_pending_question()
            return {"pending": question}
        
        @self.app.get("/context")
        async def get_context(repo: str | None = None):
            # Return empty context for now
            return {"messages": [], "count": 0}
        
        @self.app.get("/config")
        async def get_config():
            return {
                "coder_model": "ollama:test",
                "manager_model": "ollama:test",
                "agent_max_turns": 50,
            }
        
        @self.app.post("/stop")
        async def soft_stop():
            self.status["stopped"] = True
            return {"ok": True, "message": "Stop requested"}
        
        @self.app.post("/kill")
        async def estop():
            self.status["stopped"] = True
            return {"ok": True, "message": "E-STOP engaged"}
        
        # Test control endpoints
        @self.app.post("/test/emit_event")
        async def emit_test_event(body: EmitEventRequest):
            """Emit an arbitrary WebSocket event for testing."""
            self._emit_event(body.event_type, body.data)
            return {"ok": True}
        
        @self.app.post("/test/create_task")
        async def create_test_task(body: TestTaskRequest):
            """Create a task with specific properties for testing."""
            task = Task(
                title=body.title,
                description=body.description or "",
                repo=body.repo or [],
                role=AgentRole(body.role) if body.role else AgentRole.CODER,
                status=TaskStatus(body.status) if body.status else TaskStatus.READY,
                importance=body.importance or 0.5,
                urgency=body.urgency or 0.5,
            )
            
            if body.parent_task_id:
                task.parent_task_id = body.parent_task_id
            
            if body.status == "blocked_by_human":
                task.status = TaskStatus.BLOCKED_BY_HUMAN
                if body.blocking_reason:
                    task.notes = body.blocking_reason
            
            if body.context_messages:
                task.context_messages = body.context_messages
            
            self.task_repo.add(task)
            
            self._emit_event("task_tree_update", {
                "tasks": [t.to_dict() for t in self.task_repo.all_tasks()],
            })
            
            return task.to_dict()
        
        @self.app.post("/test/set_status")
        async def set_test_status(body: dict):
            """Set the orchestrator status for testing."""
            self.status.update(body)
            self._emit_event("status_update", {"data": self.status})
            return {"ok": True}
        
        @self.app.post("/test/trigger_clarification")
        async def trigger_clarification(body: ClarificationRequest):
            """Trigger a clarification request event."""
            self.comms.ask_question(body.question)
            self._emit_event("clarification_request", {
                "question": body.question,
            })
            return {"ok": True}
        
        @self.app.post("/test/trigger_decision")
        async def trigger_decision(body: TriggerDecisionRequest):
            """Trigger a decision required event."""
            self._emit_event(body.decision_type, {
                "task_id": body.task_id,
                "message": body.message,
                "choices": body.choices,
            })
            return {"ok": True}
        
        @self.app.post("/test/reset")
        async def reset_test_state():
            """Reset all test state."""
            self.task_repo = InMemoryTaskRepository()
            self.status = {
                "idle": True,
                "stopped": False,
                "blocked": False,
                "task": None,
                "phase": None,
                "model": None,
                "turns": 0,
            }
            self.comms = CommsManager()
            return {"ok": True}
    
    def _emit_event(self, event_type: str, data: dict):
        """Emit a WebSocket event."""
        self.comms.emit(event_type, data)
    
    def start(self):
        """Start the mock server in a background thread."""
        if self._server_thread is not None:
            return
        
        def run_server():
            uvicorn.run(
                self.app,
                host="127.0.0.1",
                port=self.port,
                log_level="error",
                access_log=False,
            )
        
        self._server_thread = threading.Thread(target=run_server, daemon=True)
        self._server_thread.start()
        
        # Wait for server to start
        import time
        time.sleep(0.5)
    
    def stop(self):
        """Stop the mock server."""
        if self._server_instance:
            self._server_instance.should_exit = True
        
        if self._server_thread:
            self._server_thread.join(timeout=2)
            self._server_thread = None
    
    @contextmanager
    def run(self):
        """Context manager for running the server."""
        self.start()
        try:
            yield self
        finally:
            self.stop()


# ---------------------------------------------------------------------------
# Request Models
# ---------------------------------------------------------------------------

class TaskCreateRequest(BaseModel):
    title: str
    description: str = ""
    repo: list[str] = []
    role: str = "coder"
    importance: float = 0.5
    urgency: float = 0.5

class MessageRequest(BaseModel):
    message: str

class DecisionRequest(BaseModel):
    decision_type: str
    choice: str
    note: str = ""

class EmitEventRequest(BaseModel):
    event_type: str
    data: dict

class TestTaskRequest(BaseModel):
    title: str
    description: str = ""
    repo: list[str] = []
    role: str = "coder"
    status: str = "ready"
    importance: float = 0.5
    urgency: float = 0.5
    parent_task_id: str | None = None
    blocking_reason: str | None = None
    context_messages: list[dict] = []

class ClarificationRequest(BaseModel):
    question: str

class TriggerDecisionRequest(BaseModel):
    task_id: str
    decision_type: str
    message: str
    choices: list[dict] = []


# ---------------------------------------------------------------------------
# Fixtures for Pytest
# ---------------------------------------------------------------------------

import pytest

@pytest.fixture
def mock_server():
    """Create and start a mock server for testing."""
    server = MockMatrixMouseServer(port=8765)
    server.start()
    yield server
    server.stop()

@pytest.fixture
def mock_server_url(mock_server):
    """Return the base URL for the mock server."""
    return f"http://127.0.0.1:{mock_server.port}"
