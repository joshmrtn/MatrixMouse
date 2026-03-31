"""
tests/frontend/test_tasks_enhancements.py

E2E tests for Tasks tab enhancements:
- Task conversation header with edit/unblock buttons
- Human-readable status display
- Enhanced filtering (Blocked Human/Task)
- Status column width and alignment
"""

import pytest
from playwright.sync_api import Page, expect

from .test_server import TestMatrixMouseServer


class TestTaskConversationHeader:
    """Test task conversation view improvements."""
    
    def test_conversation_header_has_edit_button(
        self,
        page_with_test_server: Page,
        test_server: TestMatrixMouseServer,
        wait_for_ws,
    ):
        """Task conversation shows Edit button."""
        page = page_with_test_server
        
        # Create a task
        test_server.create_task(title="Edit Me")
        
        # Navigate to task conversation
        page.click('[data-tab="tasks"]')
        page.wait_for_timeout(300)
        page.click('.task-title:has-text("Edit Me")')
        page.wait_for_timeout(300)
        
        # Verify Edit button is visible
        expect(page.locator("button:has-text('Edit')")).to_be_visible()
    
    def test_conversation_header_has_unblock_button_for_blocked(
        self,
        page_with_test_server: Page,
        test_server: TestMatrixMouseServer,
        wait_for_ws,
    ):
        """Task conversation shows Unblock button for blocked tasks."""
        page = page_with_test_server
        
        # Create a blocked task
        test_server.create_task(
            title="Blocked Task",
            status="blocked_by_human",
        )
        
        # Navigate to task conversation
        page.click('[data-tab="tasks"]')
        page.wait_for_timeout(300)
        page.click('.task-title:has-text("Blocked Task")')
        page.wait_for_timeout(300)
        
        # Verify Unblock button is visible
        expect(page.locator("button:has-text('Unblock')")).to_be_visible()
    
    def test_conversation_header_status_human_readable(
        self,
        page_with_test_server: Page,
        test_server: TestMatrixMouseServer,
        wait_for_ws,
    ):
        """Status displayed in human-readable format."""
        page = page_with_test_server
        
        # Create task with snake_case status
        test_server.create_task(
            title="Status Test",
            status="blocked_by_human",
        )
        
        # Navigate to task conversation
        page.click('[data-tab="tasks"]')
        page.wait_for_timeout(300)
        page.click('.task-title:has-text("Status Test")')
        page.wait_for_timeout(300)
        
        # Status should be formatted (no underscores, title case)
        expect(page.locator("text=Status:")).to_contain_text("Blocked By Human")
    
    def test_conversation_header_role_capitalized(
        self,
        page_with_test_server: Page,
        test_server: TestMatrixMouseServer,
        wait_for_ws,
    ):
        """Role displayed with capital first letter."""
        page = page_with_test_server
        
        # Create task with lowercase role
        test_server.create_task(
            title="Role Test",
            role="manager",
        )
        
        # Navigate to task conversation
        page.click('[data-tab="tasks"]')
        page.wait_for_timeout(300)
        page.click('.task-title:has-text("Role Test")')
        page.wait_for_timeout(300)
        
        # Role should be capitalized
        expect(page.locator("text=Role:")).to_contain_text("Manager")


class TestEnhancedFiltering:
    """Test enhanced task filtering."""
    
    def test_blocked_human_filter(
        self,
        page_with_test_server: Page,
        test_server: TestMatrixMouseServer,
        wait_for_ws,
    ):
        """Blocked (Human) filter shows only human-blocked tasks."""
        page = page_with_test_server
        
        # Create various blocked tasks
        test_server.create_task(title="Human Blocked", status="blocked_by_human")
        test_server.create_task(title="Task Blocked", status="blocked_by_task")
        test_server.create_task(title="Ready Task", status="ready")
        
        # Navigate to Tasks tab
        page.click('[data-tab="tasks"]')
        page.wait_for_timeout(300)
        
        # Select Blocked (Human) filter
        page.select_option("#task-filter-status", "blocked_human")
        page.wait_for_timeout(300)
        
        # Should show only human-blocked task
        expect(page.locator(".task-title").filter(has_text="Human Blocked")).to_be_visible()
        expect(page.locator(".task-title").filter(has_text="Task Blocked")).not_to_be_visible()
        expect(page.locator(".task-title").filter(has_text="Ready Task")).not_to_be_visible()
    
    def test_blocked_task_filter(
        self,
        page_with_test_server: Page,
        test_server: TestMatrixMouseServer,
        wait_for_ws,
    ):
        """Blocked (Task) filter shows only dependency-blocked tasks."""
        page = page_with_test_server
        
        # Create various blocked tasks
        test_server.create_task(title="Human Blocked", status="blocked_by_human")
        test_server.create_task(title="Task Blocked", status="blocked_by_task")
        test_server.create_task(title="Ready Task", status="ready")
        
        # Navigate to Tasks tab
        page.click('[data-tab="tasks"]')
        page.wait_for_timeout(300)
        
        # Select Blocked (Task) filter
        page.select_option("#task-filter-status", "blocked_task")
        page.wait_for_timeout(300)
        
        # Should show only task-blocked task
        expect(page.locator(".task-title").filter(has_text="Task Blocked")).to_be_visible()
        expect(page.locator(".task-title").filter(has_text="Human Blocked")).not_to_be_visible()
        expect(page.locator(".task-title").filter(has_text="Ready Task")).not_to_be_visible()


class TestStatusColumnDisplay:
    """Test status column width and alignment."""
    
    def test_status_column_left_aligned(
        self,
        page_with_test_server: Page,
        test_server: TestMatrixMouseServer,
        wait_for_ws,
    ):
        """Status column is left-aligned."""
        page = page_with_test_server
        
        # Create tasks with various statuses
        test_server.create_task(title="Task 1", status="running")
        test_server.create_task(title="Task 2", status="blocked_by_human")
        
        # Navigate to Tasks tab
        page.click('[data-tab="tasks"]')
        page.wait_for_timeout(300)
        
        # Status should be left-aligned (check CSS)
        status_element = page.locator(".task-status").first
        text_align = status_element.evaluate("el => window.getComputedStyle(el).textAlign")
        assert text_align == "left"
    
    def test_status_column_accommodates_long_status(
        self,
        page_with_test_server: Page,
        test_server: TestMatrixMouseServer,
        wait_for_ws,
    ):
        """Status column width accommodates 'Blocked By Human'."""
        page = page_with_test_server
        
        # Create task with longest status
        test_server.create_task(title="Long Status", status="blocked_by_human")
        
        # Navigate to Tasks tab
        page.click('[data-tab="tasks"]')
        page.wait_for_timeout(300)
        
        # Status should be fully visible (not truncated)
        status_element = page.locator(".task-status").filter(has_text="Blocked By Human")
        expect(status_element).to_be_visible()
        # Verify it contains the full text
        expect(status_element).to_contain_text("Blocked By Human")


class TestConversationActions:
    """Test edit/unblock actions from conversation view."""
    
    def test_edit_button_navigates_to_tasks_tab(
        self,
        page_with_test_server: Page,
        test_server: TestMatrixMouseServer,
        wait_for_ws,
    ):
        """Edit button navigates to Tasks tab with edit form."""
        page = page_with_test_server
        
        # Create a task
        test_server.create_task(title="Edit This")
        
        # Navigate to task conversation
        page.click('[data-tab="tasks"]')
        page.wait_for_timeout(300)
        page.click('.task-title:has-text("Edit This")')
        page.wait_for_timeout(300)
        
        # Click Edit button
        page.click("button:has-text('Edit')")
        page.wait_for_timeout(300)
        
        # Should be on Tasks tab with edit form open
        expect(page.locator("#tasks-panel")).to_be_visible()
        expect(page.locator(".task-edit-form.open")).to_be_visible()
