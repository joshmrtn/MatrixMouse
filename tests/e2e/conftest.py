"""tests/e2e/conftest.py

Pytest fixtures for E2E tests.

Integrates the Python MatrixMouseTestServer with Playwright tests.
The test server serves both the API AND the frontend build.
"""

import pytest
import time
from pathlib import Path
from typing import Generator

from matrixmouse.test_server import MatrixMouseTestServer, MatrixMouseTestServerConfig


@pytest.fixture(scope="session")
def e2e_test_server() -> Generator[MatrixMouseTestServer, None, None]:
    """
    Start a MatrixMouseTestServer for E2E testing.
    
    This server:
    - Uses in-memory repositories (no disk I/O)
    - Uses FakeBackend for LLM (no Ollama required)
    - Serves the frontend build from dist/
    - Provides real API endpoints
    
    Yields:
        MatrixMouseTestServer instance
    """
    # Find the frontend dist directory
    frontend_root = Path(__file__).parent.parent.parent / "frontend"
    dist_dir = frontend_root / "dist"
    
    if not dist_dir.exists():
        pytest.fail(
            f"Frontend build not found at {dist_dir}. "
            "Run 'cd frontend && npm run build' first."
        )
    
    # Create test server on a specific port
    config = MatrixMouseTestServerConfig(
        port=8765,  # Use a specific port for E2E tests
        host="127.0.0.1",
        llm_mode="echo",  # Echo mode for predictable behavior
    )
    
    server = MatrixMouseTestServer(config)
    
    try:
        server.start()
        
        # Wait for server to be ready
        time.sleep(2)
        
        yield server
    finally:
        server.stop()


@pytest.fixture
def e2e_base_url(e2e_test_server: MatrixMouseTestServer) -> str:
    """Get the base URL for the E2E test server."""
    return f"http://{e2e_test_server.config.host}:{e2e_test_server.config.port}"


@pytest.fixture
def setup_test_data(e2e_test_server: MatrixMouseTestServer):
    """
    Set up test data in the test server.
    
    Usage:
        def test_something(setup_test_data):
            # Test data is already populated
            pass
    """
    from matrixmouse.task import TaskStatus, AgentRole
    
    # Add test repos
    e2e_test_server.add_repo(
        name="main-repo",
        remote="https://github.com/test/main.git",
    )
    e2e_test_server.add_repo(
        name="test-repo",
        remote="https://github.com/test/test.git",
    )
    
    # Add test tasks
    e2e_test_server.add_task(
        title="High Priority Task",
        description="This is urgent",
        repo=["main-repo"],
        role=AgentRole.CODER,
        status=TaskStatus.READY,
        importance=0.9,
        urgency=0.9,
    )
    
    e2e_test_server.add_task(
        title="Running Task",
        description="Currently executing",
        repo=["main-repo"],
        role=AgentRole.CODER,
        status=TaskStatus.RUNNING,
    )
    
    e2e_test_server.add_task(
        title="Blocked by Human",
        description="Waiting for review",
        repo=["test-repo"],
        role=AgentRole.CRITIC,
        status=TaskStatus.BLOCKED_BY_HUMAN,
        notes="[BLOCKED] Awaiting review",
    )
    
    e2e_test_server.add_task(
        title="Completed Task",
        description="Already done",
        repo=["main-repo"],
        role=AgentRole.MANAGER,
        status=TaskStatus.COMPLETE,
    )
    
    e2e_test_server.add_task(
        title="Workspace Task",
        description="No repo assigned",
        repo=[],
        role=AgentRole.WRITER,
        status=TaskStatus.READY,
    )
    
    yield
    
    # Cleanup happens automatically when server stops


@pytest.fixture
def setup_blocked_tasks(e2e_test_server: MatrixMouseTestServer, setup_test_data):
    """
    Set up test data with blocked tasks for status dashboard tests.
    
    This extends setup_test_data with additional blocked/waiting tasks.
    """
    from matrixmouse.task import TaskStatus, AgentRole
    
    # Add dependency relationship
    tasks = e2e_test_server.get_all_tasks()
    running_task = next(t for t in tasks if t.status == TaskStatus.RUNNING)
    blocked_task = next(t for t in tasks if t.status == TaskStatus.BLOCKED_BY_HUMAN)
    
    # Create a task blocked by dependency
    e2e_test_server.add_task(
        title="Waiting on Dependency",
        description="Blocked by another task",
        repo=["main-repo"],
        role=AgentRole.CODER,
        status=TaskStatus.READY,
    )
    
    # Add dependency (running_task blocks the new task)
    new_tasks = e2e_test_server.get_all_tasks()
    new_task = next(t for t in new_tasks if t.title == "Waiting on Dependency")
    e2e_test_server.add_dependency(running_task.id, new_task.id)
    
    # Add waiting task
    e2e_test_server.add_task(
        title="Rate Limited",
        description="Waiting for rate limit reset",
        repo=["test-repo"],
        role=AgentRole.CODER,
        status=TaskStatus.WAITING,
        wait_reason="budget:api_limit",
        wait_until="2099-01-01T00:00:00Z",
    )
    
    yield


@pytest.fixture
def setup_settings_data(e2e_test_server: MatrixMouseTestServer):
    """
    Set up test data for settings page tests.
    
    Configures the server with specific settings that can be modified.
    """
    # Initial state is set via server config
    # Settings tests will modify via API
    yield


@pytest.fixture
def setup_channel_data(e2e_test_server: MatrixMouseTestServer, setup_test_data):
    """
    Set up test data for channel/conversation tests.
    
    Creates tasks with context messages for conversation testing.
    """
    from matrixmouse.task import Task, AgentRole, TaskStatus
    
    # Add a task with conversation context
    task = Task(
        title="Conversation Test Task",
        description="Test conversation features",
        repo=["main-repo"],
        role=AgentRole.CODER,
        status=TaskStatus.RUNNING,
        context_messages=[
            {"role": "system", "content": "You are MatrixMouse assistant."},
            {"role": "user", "content": "Hello, can you help me?"},
            {"role": "assistant", "content": "Of course! I'd be happy to help."},
        ],
    )
    e2e_test_server.task_repo.add(task)
    
    yield
