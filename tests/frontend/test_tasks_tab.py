"""
tests/frontend/test_tasks_tab.py

E2E tests for the Tasks tab enhancements.
"""

import pytest
from playwright.sync_api import Page, expect

from .test_server import TestMatrixMouseServer


class TestTaskEditModal:
    """Test enhanced task edit modal."""
    
    def test_edit_modal_has_all_fields(
        self,
        page_with_test_server: Page,
        test_server: TestMatrixMouseServer,
        wait_for_ws,
    ):
        """Edit modal shows all task fields."""
        page = page_with_test_server
        
        # Create a task
        test_server.create_task(
            title="Test Task",
            description="Test description",
            notes="Test notes",
            branch="mm/test",
            role="coder",
        )
        
        # Navigate to Tasks tab
        page.click('[data-tab="tasks"]')
        page.wait_for_timeout(500)
        
        # Click edit button
        page.click('button[title="Edit task"]')
        
        # Verify all fields are present
        expect(page.locator("input[id^='ef-title']")).to_be_visible()
        expect(page.locator("textarea[id^='ef-desc']")).to_be_visible()
        expect(page.locator("textarea[id^='ef-notes']")).to_be_visible()
        expect(page.locator("input[id^='ef-branch']")).to_be_visible()
        expect(page.locator("select[id^='ef-role']")).to_be_visible()


class TestTaskNavigation:
    """Test clicking task navigates to conversation."""
    
    def test_click_task_navigates_to_conversation(
        self,
        page_with_test_server: Page,
        test_server: TestMatrixMouseServer,
        wait_for_ws,
    ):
        """Clicking a task row navigates to conversation view."""
        page = page_with_test_server
        
        # Create a task
        test_server.create_task(title="Navigate Me")
        
        # Navigate to Tasks tab
        page.click('[data-tab="tasks"]')
        page.wait_for_timeout(500)
        
        # Click the task row
        page.click('.task-title:has-text("Navigate Me")')
        page.wait_for_timeout(500)
        
        # Should navigate to chat panel
        expect(page.locator("#chat-panel")).to_be_visible()


class TestUnblockButton:
    """Test unblock button for blocked tasks."""
    
    def test_unblock_button_shows_for_blocked_tasks(
        self,
        page_with_test_server: Page,
        test_server: TestMatrixMouseServer,
        wait_for_ws,
    ):
        """Unblock button appears for BLOCKED_BY_HUMAN tasks."""
        page = page_with_test_server
        
        # Create a blocked task
        test_server.create_task(
            title="Blocked Task",
            status="blocked_by_human",
        )
        
        # Navigate to Tasks tab
        page.click('[data-tab="tasks"]')
        page.wait_for_timeout(500)
        
        # Verify unblock button is visible
        expect(page.locator('button[title="Unblock task"]')).to_be_visible()


class TestStatusFilter:
    """Test task status filtering."""
    
    def test_blocked_filter_shows_blocked_tasks(
        self,
        page_with_test_server: Page,
        test_server: TestMatrixMouseServer,
        wait_for_ws,
    ):
        """Blocked filter shows blocked tasks."""
        page = page_with_test_server
        
        # Create blocked tasks
        test_server.create_task(title="Blocked Human", status="blocked_by_human")
        test_server.create_task(title="Ready Task", status="ready")
        
        # Navigate to Tasks tab
        page.click('[data-tab="tasks"]')
        page.wait_for_timeout(500)
        
        # Select Blocked filter
        page.select_option("#task-filter-status", "blocked")
        page.wait_for_timeout(500)
        
        # Should show blocked task
        expect(page.locator(".task-title").filter(has_text="Blocked Human")).to_be_visible()


class TestTaskDisplay:
    """Test task display improvements."""
    
    def test_status_display_human_readable(
        self,
        page_with_test_server: Page,
        test_server: TestMatrixMouseServer,
        wait_for_ws,
    ):
        """Status is displayed in human-readable format."""
        page = page_with_test_server
        
        # Create task
        test_server.create_task(title="Task 1", status="blocked_by_task")
        
        # Navigate to Tasks tab
        page.click('[data-tab="tasks"]')
        page.wait_for_timeout(500)
        
        # Status should be formatted (no underscores)
        expect(page.locator(".task-status")).to_contain_text("Blocked")


class TestCreateTaskForm:
    """Test enhanced task creation form."""
    
    def test_create_form_has_all_fields(
        self,
        page_with_test_server: Page,
        test_server: TestMatrixMouseServer,
        wait_for_ws,
    ):
        """Create task form has all new fields."""
        page = page_with_test_server
        
        # Navigate to Tasks tab
        page.click('[data-tab="tasks"]')
        
        # Click + New button
        page.click("#btn-add-task")
        
        # Verify fields are present
        expect(page.locator("#atf-title")).to_be_visible()
        expect(page.locator("#atf-desc")).to_be_visible()
        expect(page.locator("#atf-notes")).to_be_visible()
        expect(page.locator("#atf-branch")).to_be_visible()
        expect(page.locator("#atf-role")).to_be_visible()
