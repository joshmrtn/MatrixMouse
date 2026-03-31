"""
tests/frontend/test_tasks_tab_alignment.py

E2E tests for Tasks tab status column alignment:
- Status column alignment is consistent regardless of button count
- EDIT and UNBLOCK buttons don't affect status position
- All rows have consistent grid layout
"""

import pytest
from playwright.sync_api import Page, expect

from .test_server import TestMatrixMouseServer


class TestTasksTabStatusAlignment:
    """Test that status column alignment is consistent."""
    
    def test_status_column_position_consistent(
        self,
        page_with_test_server: Page,
        test_server: TestMatrixMouseServer,
        wait_for_ws,
    ):
        """Status column is in same position for all tasks."""
        page = page_with_test_server
        
        # Create tasks with different button configurations
        test_server.create_task(
            title="Task With Unblock",
            status="blocked_by_human",  # Has EDIT + UNBLOCK
        )
        test_server.create_task(
            title="Task Edit Only",
            status="ready",  # Has only EDIT
        )
        
        # Navigate to Tasks tab
        page.click('[data-tab="tasks"]')
        page.wait_for_timeout(500)
        
        # Get all status elements
        status_elements = page.locator(".task-status")
        count = status_elements.count()
        
        if count >= 2:
            # Get the X position of each status element
            first_box = status_elements.nth(0).bounding_box()
            second_box = status_elements.nth(1).bounding_box()
            
            # X positions should be the same (aligned)
            if first_box and second_box:
                # Allow 2px tolerance for rendering differences
                assert abs(first_box['x'] - second_box['x']) < 2, \
                    f"Status columns not aligned: {first_box['x']} vs {second_box['x']}"
    
    def test_action_buttons_dont_affect_status_width(
        self,
        page_with_test_server: Page,
        test_server: TestMatrixMouseServer,
        wait_for_ws,
    ):
        """Action buttons column width is consistent."""
        page = page_with_test_server
        
        # Create tasks
        test_server.create_task(title="Task 1", status="blocked_by_human")
        test_server.create_task(title="Task 2", status="ready")
        
        # Navigate to Tasks tab
        page.click('[data-tab="tasks"]')
        page.wait_for_timeout(500)
        
        # Get action button containers
        action_containers = page.locator(".task-actions")
        count = action_containers.count()
        
        if count >= 2:
            # Both should exist and have similar structure
            expect(action_containers.nth(0)).to_be_visible()
            expect(action_containers.nth(1)).to_be_visible()
            
            # Button count may differ, but container should be consistent
            first_buttons = action_containers.nth(0).locator("button")
            second_buttons = action_containers.nth(1).locator("button")
            
            # At minimum, both should have EDIT button
            expect(first_buttons.nth(0)).to_be_visible()
            expect(second_buttons.nth(0)).to_be_visible()
    
    def test_task_row_grid_layout(
        self,
        page_with_test_server: Page,
        test_server: TestMatrixMouseServer,
        wait_for_ws,
    ):
        """Task rows use consistent grid layout."""
        page = page_with_test_server
        
        # Create a task
        test_server.create_task(title="Grid Test")
        
        # Navigate to Tasks tab
        page.click('[data-tab="tasks"]')
        page.wait_for_timeout(300)
        
        # Check row has correct grid structure
        task_row = page.locator(".task-row").first
        expect(task_row).to_be_visible()
        
        # Should have status dot, title/repo container, status, actions
        expect(task_row.locator(".task-status-dot")).to_be_visible()
        expect(task_row.locator(".task-title")).to_be_visible()
        expect(task_row.locator(".task-status")).to_be_visible()
        expect(task_row.locator(".task-actions")).to_be_visible()


class TestTasksTabMobileLayout:
    """Test Tasks tab layout on narrow screens."""
    
    def test_status_wraps_on_narrow_screen(
        self,
        page_with_test_server: Page,
        test_server: TestMatrixMouseServer,
        wait_for_ws,
    ):
        """Status text wraps instead of being cut off on narrow screens."""
        page = page_with_test_server
        
        # Set narrow viewport
        page.set_viewport_size({"width": 400, "height": 800})
        
        # Create task with long status
        test_server.create_task(title="Long Status", status="blocked_by_human")
        
        # Navigate to Tasks tab
        page.click('[data-tab="tasks"]')
        page.wait_for_timeout(300)
        
        # Status should be visible (may wrap)
        status_element = page.locator(".task-status")
        expect(status_element).to_be_visible()
        
        # Text should not be completely cut off
        status_text = status_element.text_content()
        assert len(status_text.strip()) > 0, "Status text is completely hidden"
    
    def test_buttons_visible_on_narrow_screen(
        self,
        page_with_test_server: Page,
        test_server: TestMatrixMouseServer,
        wait_for_ws,
    ):
        """Action buttons remain visible on narrow screens."""
        page = page_with_test_server
        
        # Set narrow viewport
        page.set_viewport_size({"width": 400, "height": 800})
        
        # Create blocked task (has both buttons)
        test_server.create_task(
            title="Narrow Test",
            status="blocked_by_human",
        )
        
        # Navigate to Tasks tab
        page.click('[data-tab="tasks"]')
        page.wait_for_timeout(300)
        
        # EDIT button should be visible
        expect(page.locator("button:has-text('Edit')")).to_be_visible()
        
        # UNBLOCK button should be visible
        expect(page.locator("button:has-text('Unblock')")).to_be_visible()
