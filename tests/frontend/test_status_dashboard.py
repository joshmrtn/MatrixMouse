"""
tests/frontend/test_status_dashboard.py

E2E tests for the Status dashboard using real API with mocked backend.
"""

import pytest
from playwright.sync_api import Page, expect

from .test_server import TestMatrixMouseServer


class TestStatusDashboard:
    """Test Status dashboard functionality."""
    
    def test_status_dashboard_loads(
        self,
        page_with_test_server: Page,
        test_server: TestMatrixMouseServer,
        wait_for_ws,
    ):
        """Status dashboard panel loads when Status tab is clicked."""
        page = page_with_test_server
        
        # Click Status tab in sidebar
        page.click('[data-tab="status"]')
        
        # Verify status panel is visible
        expect(page.locator("#status-panel")).to_be_visible()
        expect(page.locator("#status-toolbar")).to_contain_text("Status Dashboard")
    
    def test_blocked_by_human_section(
        self,
        page_with_test_server: Page,
        test_server: TestMatrixMouseServer,
        wait_for_ws,
    ):
        """Blocked by human section shows tasks."""
        page = page_with_test_server
        
        # Create a blocked task via the real API
        test_server.create_task(
            title="Needs Approval",
            description="Waiting for human",
            repo=["test-repo"],
            status="blocked_by_human",
            blocking_reason="Needs decision on approach",
        )
        
        # Navigate to Status tab
        page.click('[data-tab="status"]')
        
        # Wait for data to load
        page.wait_for_timeout(500)
        
        # Verify task appears in blocked by human section
        expect(page.locator("#status-list-human")).to_contain_text("Needs Approval")
        expect(page.locator("#status-list-human")).to_contain_text("Needs decision on approach")
    
    def test_blocked_by_dependencies_section(
        self,
        page_with_test_server: Page,
        test_server: TestMatrixMouseServer,
        wait_for_ws,
    ):
        """Blocked by dependencies section shows tasks."""
        page = page_with_test_server
        
        # Create a blocked task
        from matrixmouse.task import Task, TaskStatus, AgentRole
        task = Task(
            title="Waiting on Dependency",
            repo=["test-repo"],
            role=AgentRole.CODER,
            status=TaskStatus.BLOCKED_BY_TASK,
        )
        test_server.task_repo.add(task)
        
        # Navigate to Status tab
        page.click('[data-tab="status"]')
        page.wait_for_timeout(500)
        
        # Verify task appears
        expect(page.locator("#status-list-deps")).to_contain_text("Waiting on Dependency")
    
    def test_waiting_section(
        self,
        page_with_test_server: Page,
        test_server: TestMatrixMouseServer,
        wait_for_ws,
    ):
        """Waiting section shows tasks."""
        page = page_with_test_server
        
        # Create a waiting task
        from matrixmouse.task import Task, TaskStatus, AgentRole
        task = Task(
            title="Waiting on Budget",
            repo=["test-repo"],
            role=AgentRole.CODER,
            status=TaskStatus.WAITING,
            wait_reason="budget:anthropic",
            wait_until="2099-12-31T23:59:59Z",
        )
        test_server.task_repo.add(task)
        
        # Navigate to Status tab
        page.click('[data-tab="status"]')
        page.wait_for_timeout(500)
        
        # Verify task appears
        expect(page.locator("#status-list-waiting")).to_contain_text("Waiting on Budget")
    
    def test_click_task_navigates_to_task(
        self,
        page_with_test_server: Page,
        test_server: TestMatrixMouseServer,
        wait_for_ws,
    ):
        """Clicking a task in Status dashboard navigates to task view."""
        page = page_with_test_server
        
        # Create a blocked task
        from matrixmouse.task import Task, TaskStatus, AgentRole
        task = Task(
            title="Click Me",
            repo=["test-repo"],
            role=AgentRole.CODER,
            status=TaskStatus.BLOCKED_BY_HUMAN,
        )
        test_server.task_repo.add(task)
        
        # Navigate to Status tab
        page.click('[data-tab="status"]')
        page.wait_for_timeout(500)
        
        # Click the task
        page.click(f'[data-task-id="{task.id}"]')
        
        # Verify we're now in chat panel with task selected
        expect(page.locator("#chat-panel")).to_be_visible()
        expect(page.locator("#chat-scope-label")).to_contain_text("Click Me")
    
    def test_empty_state_message(
        self,
        page_with_test_server: Page,
        test_server: TestMatrixMouseServer,
        wait_for_ws,
    ):
        """Empty state shows 'No tasks' message."""
        page = page_with_test_server
        
        # Navigate to Status tab (no tasks created)
        page.click('[data-tab="status"]')
        page.wait_for_timeout(500)
        
        # Verify empty state messages
        expect(page.locator("#status-list-human")).to_contain_text("No tasks")
        expect(page.locator("#status-list-deps")).to_contain_text("No tasks")
        expect(page.locator("#status-list-waiting")).to_contain_text("No tasks")


class TestStatusTabHighlight:
    """Test Status tab highlighting."""
    
    def test_status_tab_active_when_selected(
        self,
        page_with_test_server: Page,
        test_server: TestMatrixMouseServer,
        wait_for_ws,
    ):
        """Status tab is highlighted when selected."""
        page = page_with_test_server
        
        # Click Status tab
        page.click('[data-tab="status"]')
        
        # Verify tab is active
        expect(page.locator('[data-tab="status"]')).to_have_class("active")
    
    def test_status_panel_visible_when_tab_selected(
        self,
        page_with_test_server: Page,
        test_server: TestMatrixMouseServer,
        wait_for_ws,
    ):
        """Status panel is visible when tab is selected."""
        page = page_with_test_server
        
        # Click Status tab
        page.click('[data-tab="status"]')
        
        # Verify panel is visible
        expect(page.locator("#status-panel")).to_have_class("tab-panel active")
