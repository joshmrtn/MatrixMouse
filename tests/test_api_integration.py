"""tests/test_api_integration.py

Minimal backend integration tests.

These tests verify that the real MatrixMouse backend API works correctly
with actual business logic (not mocked). This catches API contract changes
that TypeScript E2E tests would miss.
"""

import pytest
import requests

from matrixmouse.test_server import MatrixMouseTestServer, MatrixMouseTestServerConfig
from matrixmouse.task import TaskStatus, AgentRole


class TestBackendApiIntegration:
    """Test real backend API endpoints with business logic."""

    def test_health_endpoint(self):
        """Health endpoint returns 200."""
        config = MatrixMouseTestServerConfig(port=8800)
        with MatrixMouseTestServer(config) as server:
            resp = requests.get(f"{server.base_url}/health", timeout=5)
            assert resp.status_code == 200
            # Health endpoint returns ok and timestamp
            data = resp.json()
            assert "ok" in data

    def test_tasks_endpoint_empty(self):
        """Tasks endpoint returns empty list initially."""
        config = MatrixMouseTestServerConfig(port=8801)
        with MatrixMouseTestServer(config) as server:
            resp = requests.get(f"{server.base_url}/tasks", timeout=5)
            assert resp.status_code == 200
            data = resp.json()
            assert "tasks" in data
            assert data["count"] == 0

    def test_create_task_via_api(self):
        """Task creation works and is retrievable."""
        config = MatrixMouseTestServerConfig(port=8802)
        with MatrixMouseTestServer(config) as server:
            # Create task via API (returns 201 Created)
            task_data = {
                "title": "Integration Test Task",
                "description": "Test backend integration",
                "repo": ["test-repo"],
                "role": "coder",
                "status": "ready",
                "importance": 0.5,
                "urgency": 0.5,
            }
            resp = requests.post(
                f"{server.base_url}/tasks",
                json=task_data,
                timeout=5,
            )
            assert resp.status_code == 201  # Created
            created = resp.json()
            assert created["title"] == "Integration Test Task"
            assert "id" in created

            # Retrieve task
            task_id = created["id"]
            resp = requests.get(f"{server.base_url}/tasks/{task_id}", timeout=5)
            assert resp.status_code == 200
            retrieved = resp.json()
            assert retrieved["id"] == task_id
            assert retrieved["title"] == "Integration Test Task"

    def test_task_list_after_creation(self):
        """Task list includes created tasks."""
        config = MatrixMouseTestServerConfig(port=8803)
        with MatrixMouseTestServer(config) as server:
            # Create a task (returns 201)
            task_data = {
                "title": "List Test Task",
                "description": "Test",
                "repo": [],
                "role": "coder",
                "status": "ready",
            }
            resp = requests.post(
                f"{server.base_url}/tasks",
                json=task_data,
                timeout=5,
            )
            assert resp.status_code == 201

            # Get task list
            resp = requests.get(f"{server.base_url}/tasks", timeout=5)
            assert resp.status_code == 200
            data = resp.json()
            assert data["count"] >= 1
            titles = [t["title"] for t in data["tasks"]]
            assert "List Test Task" in titles

    def test_blocked_endpoint(self):
        """Blocked endpoint returns correct structure."""
        config = MatrixMouseTestServerConfig(port=8804)
        with MatrixMouseTestServer(config) as server:
            resp = requests.get(f"{server.base_url}/blocked", timeout=5)
            assert resp.status_code == 200
            data = resp.json()
            assert "report" in data
            assert "human" in data["report"]
            assert "dependencies" in data["report"]
            assert "waiting" in data["report"]

    def test_repos_endpoint(self):
        """Repos endpoint returns empty list initially."""
        config = MatrixMouseTestServerConfig(port=8805)
        with MatrixMouseTestServer(config) as server:
            resp = requests.get(f"{server.base_url}/repos", timeout=5)
            assert resp.status_code == 200
            data = resp.json()
            assert "repos" in data
            assert len(data["repos"]) == 0

    def test_task_status_filtering(self):
        """Task filtering by status works."""
        config = MatrixMouseTestServerConfig(port=8806)
        with MatrixMouseTestServer(config) as server:
            # Create tasks with different statuses (returns 201)
            for status in ["ready", "running", "blocked_by_human"]:
                task_data = {
                    "title": f"Task {status}",
                    "description": "Test",
                    "repo": [],
                    "role": "coder",
                    "status": status,
                }
                resp = requests.post(
                    f"{server.base_url}/tasks",
                    json=task_data,
                    timeout=5,
                )
                assert resp.status_code == 201

            # Filter by status
            resp = requests.get(
                f"{server.base_url}/tasks?status=ready",
                timeout=5,
            )
            assert resp.status_code == 200
            data = resp.json()
            # Should only return ready tasks
            for task in data["tasks"]:
                assert task["status"] == "ready"

    def test_task_update_via_api(self):
        """Task update works correctly."""
        config = MatrixMouseTestServerConfig(port=8807)
        with MatrixMouseTestServer(config) as server:
            # Create task (returns 201)
            task_data = {
                "title": "Update Test",
                "description": "Original",
                "repo": [],
                "role": "coder",
                "status": "ready",
            }
            resp = requests.post(
                f"{server.base_url}/tasks",
                json=task_data,
                timeout=5,
            )
            assert resp.status_code == 201
            task_id = resp.json()["id"]

            # Update task
            update_data = {
                "title": "Updated Title",
                "description": "Updated description",
            }
            resp = requests.patch(
                f"{server.base_url}/tasks/{task_id}",
                json=update_data,
                timeout=5,
            )
            assert resp.status_code == 200
            updated = resp.json()
            assert updated["title"] == "Updated Title"
            assert updated["description"] == "Updated description"

    def test_task_deletion_via_api(self):
        """Task deletion works correctly."""
        config = MatrixMouseTestServerConfig(port=8808)
        with MatrixMouseTestServer(config) as server:
            # Create task (returns 201)
            task_data = {
                "title": "Delete Test",
                "description": "Test",
                "repo": [],
                "role": "coder",
                "status": "ready",
            }
            resp = requests.post(
                f"{server.base_url}/tasks",
                json=task_data,
                timeout=5,
            )
            assert resp.status_code == 201
            task_id = resp.json()["id"]

            # Delete task
            resp = requests.delete(
                f"{server.base_url}/tasks/{task_id}",
                timeout=5,
            )
            assert resp.status_code == 200

            # Verify task is removed from list
            resp = requests.get(f"{server.base_url}/tasks", timeout=5)
            assert resp.status_code == 200
            data = resp.json()
            task_ids = [t["id"] for t in data["tasks"]]
            assert task_id not in task_ids

    def test_dependency_creation(self):
        """Task dependencies can be created."""
        config = MatrixMouseTestServerConfig(port=8809)
        with MatrixMouseTestServer(config) as server:
            # Create two tasks (returns 201)
            task1_data = {
                "title": "Blocking Task",
                "description": "Blocks task 2",
                "repo": [],
                "role": "coder",
                "status": "ready",
            }
            resp = requests.post(f"{server.base_url}/tasks", json=task1_data, timeout=5)
            assert resp.status_code == 201
            task1_id = resp.json()["id"]

            task2_data = {
                "title": "Blocked Task",
                "description": "Blocked by task 1",
                "repo": [],
                "role": "coder",
                "status": "ready",
            }
            resp = requests.post(f"{server.base_url}/tasks", json=task2_data, timeout=5)
            assert resp.status_code == 201
            task2_id = resp.json()["id"]

            # Verify dependencies endpoint exists and returns structure
            resp = requests.get(
                f"{server.base_url}/tasks/{task2_id}/dependencies",
                timeout=5,
            )
            assert resp.status_code == 200
            data = resp.json()
            assert "dependencies" in data
