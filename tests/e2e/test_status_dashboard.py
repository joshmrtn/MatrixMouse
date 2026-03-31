"""tests/e2e/test_status_dashboard.py

Playwright E2E tests for the Status Dashboard page.

These tests use a mock API server for fast, deterministic testing.
"""

import pytest
from playwright.sync_api import Page, expect

from .conftest import _MockAPIServer as MockAPIServer, with_blocked_tasks


class TestStatusDashboard:
    """E2E tests for Status Dashboard page."""
    
    def test_status_page_loads(self, page: Page, mock_api_server):
        """Test that status page loads successfully."""
        page.goto(f"http://127.0.0.1:{mock_api_server.port}/status")
        
        # Check page title
        expect(page).to_have_title("MatrixMouse")
        expect(page.locator("h1")).to_contain_text("Status Dashboard")
    
    def test_blocked_by_human_section_shows_tasks(
        self, page: Page, mock_api_server, with_blocked_tasks
    ):
        """Test that blocked by human section displays tasks."""
        page.goto(f"http://127.0.0.1:{mock_api_server.port}/status")
        
        # Find the blocked by human section
        human_section = page.locator("#status-blocked-human")
        expect(human_section).to_be_visible()
        
        # Check section header
        expect(human_section.locator(".status-section-title")).to_contain_text(
            "Blocked by Human"
        )
        
        # Check task is displayed
        task_link = human_section.locator(".task-link").first
        expect(task_link).to_be_visible()
        expect(task_link).to_contain_text("Awaiting Review")
    
    def test_blocked_by_dependencies_section_shows_tasks(
        self, page: Page, mock_api_server, with_blocked_tasks
    ):
        """Test that blocked by dependencies section displays tasks."""
        page.goto(f"http://127.0.0.1:{mock_api_server.port}/status")
        
        # Find the blocked by dependencies section
        deps_section = page.locator("#status-blocked-deps")
        expect(deps_section).to_be_visible()
        
        # Check section header
        expect(deps_section.locator(".status-section-title")).to_contain_text(
            "Blocked by Dependencies"
        )
        
        # Check task is displayed
        task_link = deps_section.locator(".task-link").first
        expect(task_link).to_be_visible()
        expect(task_link).to_contain_text("Waiting on Dependency")
    
    def test_waiting_section_shows_tasks(
        self, page: Page, mock_api_server, with_blocked_tasks
    ):
        """Test that waiting section displays tasks."""
        page.goto(f"http://127.0.0.1:{mock_api_server.port}/status")
        
        # Find the waiting section
        waiting_section = page.locator("#status-waiting")
        expect(waiting_section).to_be_visible()
        
        # Check section header
        expect(waiting_section.locator(".status-section-title")).to_contain_text(
            "Waiting"
        )
        
        # Check task is displayed
        task_link = waiting_section.locator(".task-link").first
        expect(task_link).to_be_visible()
        expect(task_link).to_contain_text("Rate Limited")
    
    def test_task_links_are_clickable(
        self, page: Page, mock_api_server, with_blocked_tasks
    ):
        """Test that task links are clickable."""
        page.goto(f"http://127.0.0.1:{mock_api_server.port}/status")
        
        # Click task link
        task_link = page.locator("#status-blocked-human .task-link").first
        task_link.click()
        
        # Should navigate to task page (mock will 404 but URL should change)
        expect(page).to_have_url(f"http://127.0.0.1:{mock_api_server.port}/task/task001")
    
    def test_empty_state_when_no_blocked_tasks(self, page: Page, mock_api_server):
        """Test empty state message when no blocked tasks."""
        MockAPIServer.set_blocked_report({
            "human": [],
            "dependencies": [],
            "waiting": [],
        })
        
        page.goto(f"http://127.0.0.1:{mock_api_server.port}/status")
        
        # Check empty message in blocked by human section
        human_section = page.locator("#status-blocked-human")
        expect(human_section.locator(".empty-message")).to_contain_text(
            "No tasks blocked by human input"
        )
    
    def test_task_id_and_title_displayed(
        self, page: Page, mock_api_server, with_blocked_tasks
    ):
        """Test that both task ID and title are displayed."""
        page.goto(f"http://127.0.0.1:{mock_api_server.port}/status")
        
        task_item = page.locator("#status-blocked-human .status-task-item").first
        
        # Should have task ID (mono font)
        task_id = task_item.locator(".task-id")
        expect(task_id).to_be_visible()
        
        # Should have task title
        task_title = task_item.locator(".task-title")
        expect(task_title).to_be_visible()
        expect(task_title).not_to_be_empty()
    
    def test_blocking_reason_displayed(
        self, page: Page, mock_api_server, with_blocked_tasks
    ):
        """Test that blocking reason is displayed."""
        page.goto(f"http://127.0.0.1:{mock_api_server.port}/status")
        
        task_item = page.locator("#status-blocked-human .status-task-item").first
        
        # Should have reason
        reason = task_item.locator(".task-reason")
        expect(reason).to_be_visible()
        expect(reason).to_contain_text("Awaiting security review")
    
    def test_unicode_icons_displayed(
        self, page: Page, mock_api_server, with_blocked_tasks
    ):
        """Test that unicode icons are displayed for each section."""
        page.goto(f"http://127.0.0.1:{mock_api_server.port}/status")
        
        # Check icons
        human_icon = page.locator("#status-blocked-human .status-section-icon")
        expect(human_icon).to_contain_text("⦸")
        
        deps_icon = page.locator("#status-blocked-deps .status-section-icon")
        expect(deps_icon).to_contain_text("⊞")
        
        waiting_icon = page.locator("#status-waiting .status-section-icon")
        expect(waiting_icon).to_contain_text("⋯")
