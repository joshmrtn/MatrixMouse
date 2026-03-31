"""tests/e2e/test_tasks_page.py

Playwright E2E tests for the Tasks List page.
"""

import pytest
from playwright.sync_api import Page, expect

from matrixmouse.test_server import create_test_scenario
from matrixmouse.task import TaskStatus


class TestTasksPage:
    """E2E tests for Tasks List page."""
    
    @pytest.fixture
    def server_with_tasks(self):
        """Create test server with various tasks."""
        return create_test_scenario(
            repos=[
                {"name": "main-repo", "remote": "https://github.com/test/main.git"},
                {"name": "test-repo", "remote": "https://github.com/test/test.git"},
            ],
            tasks=[
                {
                    "title": "High Priority Task",
                    "status": TaskStatus.READY,
                    "importance": 0.9,
                    "urgency": 0.9,
                    "repo": ["main-repo"],
                },
                {
                    "title": "Running Task",
                    "status": TaskStatus.RUNNING,
                    "repo": ["main-repo"],
                },
                {
                    "title": "Blocked by Human",
                    "status": TaskStatus.BLOCKED_BY_HUMAN,
                    "repo": ["test-repo"],
                },
                {
                    "title": "Completed Task",
                    "status": TaskStatus.COMPLETE,
                    "repo": ["main-repo"],
                },
                {
                    "title": "Workspace Task",
                    "status": TaskStatus.READY,
                    "repo": [],  # Workspace-level task
                },
            ],
        )
    
    def test_tasks_page_loads(self, page: Page, server_with_tasks):
        """Test that tasks page loads successfully."""
        server = server_with_tasks
        
        try:
            page.goto(f"{server.base_url}/tasks")
            
            # Check page title
            expect(page.locator("h1")).to_contain_text("Tasks")
        finally:
            server.stop()
    
    def test_tasks_list_displays_all_tasks(self, page: Page, server_with_tasks):
        """Test that all tasks are displayed in the list."""
        server = server_with_tasks
        
        try:
            page.goto(f"{server.base_url}/tasks")
            
            task_items = page.locator(".task-item")
            expect(task_items).to_have_count(5)
        finally:
            server.stop()
    
    def test_task_displays_title_and_id(self, page: Page, server_with_tasks):
        """Test that task displays title and ID."""
        server = server_with_tasks
        
        try:
            page.goto(f"{server.base_url}/tasks")
            
            task_item = page.locator(".task-item").first
            
            # Should have task title
            expect(task_item.locator(".task-title")).to_be_visible()
            
            # Should have task ID
            expect(task_item.locator(".task-id")).to_be_visible()
        finally:
            server.stop()
    
    def test_task_displays_status(self, page: Page, server_with_tasks):
        """Test that task displays status with correct styling."""
        server = server_with_tasks
        
        try:
            page.goto(f"{server.base_url}/tasks")
            
            # Find running task
            running_task = page.locator(".task-item:has-text('Running Task')")
            expect(running_task.locator(".task-status")).to_contain_text("Running")
            expect(running_task.locator(".task-status")).to_have_class(
                "task-status status-running"
            )
        finally:
            server.stop()
    
    def test_task_displays_repo(self, page: Page, server_with_tasks):
        """Test that task displays repo information."""
        server = server_with_tasks
        
        try:
            page.goto(f"{server.base_url}/tasks")
            
            # Task with repo
            main_repo_task = page.locator(".task-item:has-text('High Priority Task')")
            expect(main_repo_task.locator(".task-repo")).to_contain_text("main-repo")
            
            # Workspace task (no repo)
            workspace_task = page.locator(".task-item:has-text('Workspace Task')")
            expect(workspace_task.locator(".task-repo")).to_contain_text("Workspace")
        finally:
            server.stop()
    
    def test_clicking_task_navigates_to_task_page(
        self, page: Page, server_with_tasks
    ):
        """Test that clicking a task navigates to task page."""
        server = server_with_tasks
        
        try:
            page.goto(f"{server.base_url}/tasks")
            
            # Get task ID
            tasks = server.get_all_tasks()
            target_task = next(t for t in tasks if t.title == "High Priority Task")
            
            # Click task
            task_link = page.locator(".task-item:has-text('High Priority Task') a")
            task_link.click()
            
            # Should navigate to task page
            expect(page).to_have_url(f"{server.base_url}/task/{target_task.id}")
        finally:
            server.stop()
    
    def test_filter_by_status(self, page: Page, server_with_tasks):
        """Test filtering tasks by status."""
        server = server_with_tasks
        
        try:
            page.goto(f"{server.base_url}/tasks")
            
            # Initially all tasks shown
            expect(page.locator(".task-item")).to_have_count(5)
            
            # Filter by "running"
            status_filter = page.locator("#filter-status")
            status_filter.select_option("running")
            
            # Should only show running task
            expect(page.locator(".task-item")).to_have_count(1)
            expect(page.locator(".task-item")).to_contain_text("Running Task")
        finally:
            server.stop()
    
    def test_filter_by_repo(self, page: Page, server_with_tasks):
        """Test filtering tasks by repo."""
        server = server_with_tasks
        
        try:
            page.goto(f"{server.base_url}/tasks")
            
            # Filter by main-repo
            repo_filter = page.locator("#filter-repo")
            repo_filter.select_option("main-repo")
            
            # Should show tasks in main-repo only
            task_items = page.locator(".task-item")
            expect(task_items).to_have_count(3)  # High Priority, Running, Complete
            
            # Verify all shown tasks are from main-repo
            for item in task_items.all():
                expect(item.locator(".task-repo")).to_contain_text("main-repo")
        finally:
            server.stop()
    
    def test_clear_filters(self, page: Page, server_with_tasks):
        """Test clearing filters."""
        server = server_with_tasks
        
        try:
            page.goto(f"{server.base_url}/tasks")
            
            # Apply filter
            status_filter = page.locator("#filter-status")
            status_filter.select_option("complete")
            expect(page.locator(".task-item")).to_have_count(1)
            
            # Clear filter
            status_filter.select_option("all")
            
            # Should show all tasks again
            expect(page.locator(".task-item")).to_have_count(5)
        finally:
            server.stop()
    
    def test_tasks_sorted_by_priority(self, page: Page, server_with_tasks):
        """Test that tasks are sorted by priority (lower score = higher priority)."""
        server = server_with_tasks
        
        try:
            page.goto(f"{server.base_url}/tasks")
            
            # High priority task should appear first
            first_task = page.locator(".task-item").first
            expect(first_task.locator(".task-title")).to_contain_text("High Priority Task")
        finally:
            server.stop()
    
    def test_add_new_task_button(self, page: Page, server_with_tasks):
        """Test that add new task button navigates to create form."""
        server = server_with_tasks
        
        try:
            page.goto(f"{server.base_url}/tasks")
            
            # Click add button
            add_button = page.locator("#add-task-btn")
            add_button.click()
            
            # Should navigate to new task page
            expect(page).to_have_url(f"{server.base_url}/tasks/new")
        finally:
            server.stop()
    
    def test_empty_state_when_no_tasks(self, page: Page):
        """Test empty state message when no tasks."""
        server = create_test_scenario(tasks=[])
        
        try:
            page.goto(f"{server.base_url}/tasks")
            
            # Should show empty message
            expect(page.locator(".empty-message")).to_contain_text("No tasks found")
        finally:
            server.stop()
    
    def test_status_filter_has_all_options(self, page: Page, server_with_tasks):
        """Test that status filter has all status options."""
        server = server_with_tasks
        
        try:
            page.goto(f"{server.base_url}/tasks")
            
            status_filter = page.locator("#filter-status")
            
            # Check all options exist
            options = status_filter.locator("option")
            expect(options).to_have_count(9)  # All + 8 statuses
            
            option_texts = [opt.inner_text() for opt in options.all()]
            assert "All" in option_texts
            assert "Pending" in option_texts
            assert "Ready" in option_texts
            assert "Running" in option_texts
            assert "Blocked by Human" in option_texts
            assert "Blocked by Dependencies" in option_texts
            assert "Waiting" in option_texts
            assert "Complete" in option_texts
            assert "Cancelled" in option_texts
        finally:
            server.stop()
    
    def test_repo_filter_populated_from_repos(self, page: Page, server_with_tasks):
        """Test that repo filter is populated from repos."""
        server = server_with_tasks
        
        try:
            page.goto(f"{server.base_url}/tasks")
            
            repo_filter = page.locator("#filter-repo")
            
            # Check options
            options = repo_filter.locator("option")
            option_texts = [opt.inner_text() for opt in options.all()]
            
            assert "All" in option_texts
            assert "main-repo" in option_texts
            assert "test-repo" in option_texts
        finally:
            server.stop()
