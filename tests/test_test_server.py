"""tests/test_test_server.py

Tests for the MatrixMouse test server infrastructure.
"""

import pytest
import requests
import time
from matrixmouse.test_server import MatrixMouseTestServer, MatrixMouseTestServerConfig, create_test_scenario
from matrixmouse.task import Task, AgentRole, TaskStatus
from matrixmouse.inference.fake import fake_text_response


class TestMatrixMouseTestServer:
    """Tests for MatrixMouseTestServer class."""
    
    def test_server_starts_and_stops(self):
        """Test server starts and stops cleanly."""
        config = MatrixMouseTestServerConfig(port=8081)  # Use specific port to avoid conflicts
        server = MatrixMouseTestServer(config)
        
        try:
            server.start()
            # Server should be running - use session to disable redirects
            session = requests.Session()
            session.max_redirects = 0
            resp = session.get(f"http://{server.config.host}:{server.config.port}/health", timeout=5, allow_redirects=False)
            assert resp.status_code == 200
        finally:
            server.stop()
    
    def test_server_context_manager(self):
        """Test server context manager."""
        with MatrixMouseTestServer(MatrixMouseTestServerConfig(port=8082)) as server:
            # Server should be running
            resp = requests.get(f"http://{server.config.host}:{server.config.port}/health", timeout=5, allow_redirects=False)
            assert resp.status_code == 200
        
        # Server should be stopped after context exit
    
    def test_server_base_url(self):
        """Test server base URL is correct."""
        with MatrixMouseTestServer(MatrixMouseTestServerConfig(port=8083)) as server:
            assert server.base_url.startswith("http://")
            assert "/health" not in server.base_url
    
    def test_server_ws_url(self):
        """Test server WebSocket URL is correct."""
        with MatrixMouseTestServer(MatrixMouseTestServerConfig(port=8084)) as server:
            assert server.ws_url.startswith("ws://")
            assert server.ws_url.endswith("/ws")


class TestMatrixMouseTestServerTasks:
    """Tests for task management in test server."""
    
    def test_add_task(self):
        """Test adding a task."""
        with MatrixMouseTestServer(MatrixMouseTestServerConfig(port=8091)) as server:
            task = server.add_task(
                title="Test Task",
                description="Test description",
                importance=0.8,
                urgency=0.9,
            )
            
            assert task.title == "Test Task"
            assert task.description == "Test description"
            assert task.importance == 0.8
            assert task.urgency == 0.9
            assert task.status == TaskStatus.READY
    
    def test_add_task_with_repo(self):
        """Test adding a task scoped to a repo."""
        with MatrixMouseTestServer(MatrixMouseTestServerConfig(port=8092)) as server:
            task = server.add_task(
                title="Repo Task",
                repo=["test-repo"],
                role=AgentRole.MANAGER,
            )
            
            assert task.repo == ["test-repo"]
            assert task.role == AgentRole.MANAGER
    
    def test_get_task(self):
        """Test getting a task by ID."""
        with MatrixMouseTestServer(MatrixMouseTestServerConfig(port=8093)) as server:
            added = server.add_task(title="Get Test")
            
            retrieved = server.get_task(added.id)
            assert retrieved is not None
            assert retrieved.id == added.id
            assert retrieved.title == "Get Test"
    
    def test_get_all_tasks(self):
        """Test getting all tasks."""
        with MatrixMouseTestServer(MatrixMouseTestServerConfig(port=8094)) as server:
            server.add_task(title="Task 1")
            server.add_task(title="Task 2")
            server.add_task(title="Task 3")
            
            tasks = server.get_all_tasks()
            assert len(tasks) == 3
            
            titles = {t.title for t in tasks}
            assert titles == {"Task 1", "Task 2", "Task 3"}
    
    def test_update_task(self):
        """Test updating a task."""
        with MatrixMouseTestServer(MatrixMouseTestServerConfig(port=8095)) as server:
            task = server.add_task(title="Update Test")
            
            task.title = "Updated Title"
            task.importance = 0.9
            server.update_task(task)
            
            retrieved = server.get_task(task.id)
            assert retrieved.title == "Updated Title"
            assert retrieved.importance == 0.9
    
    def test_delete_task(self):
        """Test deleting a task."""
        with MatrixMouseTestServer(MatrixMouseTestServerConfig(port=8096)) as server:
            task = server.add_task(title="Delete Test")
            
            server.delete_task(task.id)
            
            retrieved = server.get_task(task.id)
            assert retrieved is None
    
    def test_add_dependency(self):
        """Test adding task dependency."""
        with MatrixMouseTestServer(MatrixMouseTestServerConfig(port=8097)) as server:
            task1 = server.add_task(title="Blocking Task", status=TaskStatus.RUNNING)
            task2 = server.add_task(title="Blocked Task", status=TaskStatus.READY)
            
            server.add_dependency(task1.id, task2.id)
            
            # task2 should now be blocked
            blocked_task = server.get_task(task2.id)
            assert blocked_task.status == TaskStatus.BLOCKED_BY_TASK
            
            # Check blockers
            blockers = server.task_repo.get_blocked_by(task2.id)
            assert len(blockers) == 1
            assert blockers[0].id == task1.id
    
    def test_task_status_filtering(self):
        """Test filtering tasks by status."""
        with MatrixMouseTestServer(MatrixMouseTestServerConfig(port=8098)) as server:
            server.add_task(title="Ready Task", status=TaskStatus.READY)
            server.add_task(title="Running Task", status=TaskStatus.RUNNING)
            server.add_task(title="Blocked Task", status=TaskStatus.BLOCKED_BY_HUMAN)
            server.add_task(title="Complete Task", status=TaskStatus.COMPLETE)

            # Filter tasks by status manually since repository doesn't have get_tasks_by_status
            all_tasks = server.task_repo.all_tasks()
            ready = [t for t in all_tasks if t.status == TaskStatus.READY]
            assert len(ready) == 1
            assert ready[0].title == "Ready Task"

            blocked = [t for t in all_tasks if t.status == TaskStatus.BLOCKED_BY_HUMAN]
            assert len(blocked) == 1
            assert blocked[0].title == "Blocked Task"


class TestMatrixMouseTestServerRepos:
    """Tests for repository management in test server."""
    
    def test_add_repo(self):
        """Test adding a repository."""
        with MatrixMouseTestServer(MatrixMouseTestServerConfig(port=8101)) as server:
            repo = server.add_repo(
                name="test-repo",
                remote="https://github.com/test/test-repo.git",
            )
            
            assert repo["name"] == "test-repo"
            assert repo["remote"] == "https://github.com/test/test-repo.git"
    
    def test_get_all_repos(self):
        """Test getting all repositories."""
        with MatrixMouseTestServer(MatrixMouseTestServerConfig(port=8102)) as server:
            server.add_repo(name="repo1", remote="https://.../repo1.git")
            server.add_repo(name="repo2", remote="https://.../repo2.git")
            
            repos = server.get_all_repos()
            assert len(repos) == 2
            
            names = {r["name"] for r in repos}
            assert names == {"repo1", "repo2"}


class TestMatrixMouseTestServerLLM:
    """Tests for LLM control in test server."""
    
    def test_set_llm_mode(self):
        """Test setting LLM mode."""
        with MatrixMouseTestServer(MatrixMouseTestServerConfig(port=8103)) as server:
            server.set_llm_mode("echo")
            assert server.llm_backend._mode == "echo"
            
            server.set_llm_mode("tool_call")
            assert server.llm_backend._mode == "tool_call"
    
    def test_add_scripted_response(self):
        """Test adding scripted responses."""
        with MatrixMouseTestServer(MatrixMouseTestServerConfig(port=8104)) as server:
            response = fake_text_response("Scripted response")
            server.add_scripted_response(response)
            
            assert len(server.llm_backend._scripted_responses) == 1
    
    def test_reset_llm(self):
        """Test resetting LLM state."""
        with MatrixMouseTestServer(MatrixMouseTestServerConfig(port=8105)) as server:
            server.add_scripted_response(fake_text_response("Response 1"))
            server.add_scripted_response(fake_text_response("Response 2"))
            
            # Consume first response
            server.llm_backend.chat(model="fake", messages=[], tools=[])
            
            # Reset
            server.reset_llm()
            
            # Should be back to first response
            assert server.llm_backend._response_index == 0


class TestCreateTestScenario:
    """Tests for create_test_scenario helper."""
    
    def test_create_scenario_with_tasks(self):
        """Test creating scenario with pre-configured tasks."""
        server = create_test_scenario(
            tasks=[
                {"title": "Task 1", "status": "ready"},
                {"title": "Task 2", "status": "blocked_by_human"},
                {"title": "Task 3", "status": "running"},
            ],
            port=8111,
        )
        
        try:
            tasks = server.get_all_tasks()
            assert len(tasks) == 3
            
            titles = {t.title for t in tasks}
            assert titles == {"Task 1", "Task 2", "Task 3"}
        finally:
            server.stop()
    
    def test_create_scenario_with_repos(self):
        """Test creating scenario with pre-configured repos."""
        server = create_test_scenario(
            repos=[
                {"name": "main-repo", "remote": "https://.../main.git"},
                {"name": "test-repo", "remote": "https://.../test.git"},
            ],
            port=8112,
        )
        
        try:
            repos = server.get_all_repos()
            assert len(repos) == 2
        finally:
            server.stop()
    
    def test_create_scenario_with_dependencies(self):
        """Test creating scenario with pre-configured dependencies."""
        server = create_test_scenario(
            tasks=[
                {"title": "Blocking", "id": "block123"},
                {"title": "Blocked", "id": "block456"},
            ],
            dependencies=[("block123", "block456")],
            port=8113,
        )
        
        try:
            tasks = server.get_all_tasks()
            blocked = [t for t in tasks if t.status == TaskStatus.BLOCKED_BY_TASK]
            assert len(blocked) == 1
            assert blocked[0].title == "Blocked"
        finally:
            server.stop()
    
    def test_create_scenario_combined(self):
        """Test creating scenario with tasks, repos, and dependencies."""
        server = create_test_scenario(
            repos=[{"name": "test-repo", "remote": "https://..."}],
            tasks=[
                {"title": "Setup", "repo": ["test-repo"], "status": "complete"},
                {"title": "Implement", "repo": ["test-repo"], "status": "ready"},
                {"title": "Review", "repo": ["test-repo"], "status": "blocked_by_task"},
            ],
            dependencies=[],
            port=8114,
        )
        
        try:
            tasks = server.get_all_tasks()
            assert len(tasks) == 3
            
            repos = server.get_all_repos()
            assert len(repos) == 1
        finally:
            server.stop()


class TestMatrixMouseTestServerAPIEndpoints:
    """Tests for API endpoint access through test server."""
    
    def test_health_endpoint(self):
        """Test /health endpoint."""
        with MatrixMouseTestServer(MatrixMouseTestServerConfig(port=8121)) as server:
            resp = requests.get(f"http://{server.config.host}:{server.config.port}/health", timeout=5, allow_redirects=False)
            assert resp.status_code == 200
    
    def test_tasks_endpoint(self):
        """Test /tasks endpoint."""
        with MatrixMouseTestServer(MatrixMouseTestServerConfig(port=8122)) as server:
            server.add_task(title="API Test 1")
            server.add_task(title="API Test 2")
            
            resp = requests.get(f"http://{server.config.host}:{server.config.port}/tasks", timeout=5, allow_redirects=False)
            assert resp.status_code == 200
            
            data = resp.json()
            assert len(data["tasks"]) == 2
    
    def test_repos_endpoint(self):
        """Test /repos endpoint."""
        with MatrixMouseTestServer(MatrixMouseTestServerConfig(port=8123)) as server:
            server.add_repo(name="api-repo", remote="https://...")
            
            resp = requests.get(f"http://{server.config.host}:{server.config.port}/repos", timeout=5, allow_redirects=False)
            assert resp.status_code == 200
            
            data = resp.json()
            assert len(data["repos"]) == 1
    
    def test_blocked_endpoint(self):
        """Test /blocked endpoint."""
        with MatrixMouseTestServer(MatrixMouseTestServerConfig(port=8124)) as server:
            server.add_task(title="Blocked Task", status=TaskStatus.BLOCKED_BY_HUMAN)
            
            resp = requests.get(f"http://{server.config.host}:{server.config.port}/blocked", timeout=5, allow_redirects=False)
            assert resp.status_code == 200
            
            data = resp.json()
            assert len(data["report"]["human"]) == 1
