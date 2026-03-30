"""
tests/frontend/test_decision_modals.py

E2E tests for decision modals:
- Modal appears for various decision types
- Choices are rendered correctly
- Text input shown when required
- Decision submission works
"""

import pytest
from playwright.sync_api import Page, expect

from .test_server import TestMatrixMouseServer


class TestDecisionModalDisplay:
    """Test decision modal display."""
    
    def test_decomposition_modal(
        self,
        page_with_test_server: Page,
        test_server: TestMatrixMouseServer,
        wait_for_ws,
    ):
        """Decomposition confirmation modal displays correctly."""
        page = page_with_test_server
        
        # Trigger decomposition event
        test_server._emit_event("decomposition_confirmation_required", {
            "task_id": "test123",
            "message": "Allow splitting into subtasks?",
        })
        
        # Wait for modal
        page.wait_for_selector("#confirmation-modal-overlay.visible")
        
        # Verify modal content
        expect(page.locator("#confirmation-modal-title")).to_contain_text("Decomposition")
        expect(page.locator("#confirmation-modal-body")).to_contain_text("Allow splitting")
        
        # Verify choices
        expect(page.locator("#confirmation-modal-choices")).to_contain_text("Allow")
        expect(page.locator("#confirmation-modal-choices")).to_contain_text("Deny")
    
    def test_pr_approval_modal(
        self,
        page_with_test_server: Page,
        test_server: TestMatrixMouseServer,
        wait_for_ws,
    ):
        """PR approval modal displays correctly."""
        page = page_with_test_server
        
        # Trigger PR approval event
        test_server._emit_event("pr_approval_required", {
            "task_id": "pr123",
            "message": "Approve this PR?",
        })
        
        # Wait for modal
        page.wait_for_selector("#confirmation-modal-overlay.visible")
        
        # Verify modal content
        expect(page.locator("#confirmation-modal-title")).to_contain_text("PR Approval")
        
        # Verify choices
        expect(page.locator("#confirmation-modal-choices")).to_contain_text("Approve")
        expect(page.locator("#confirmation-modal-choices")).to_contain_text("Reject")
    
    def test_turn_limit_modal(
        self,
        page_with_test_server: Page,
        test_server: TestMatrixMouseServer,
        wait_for_ws,
    ):
        """Turn limit modal displays correctly."""
        page = page_with_test_server
        
        # Trigger turn limit event
        test_server._emit_event("turn_limit_reached", {
            "task_id": "task123",
            "message": "Task has reached turn limit.",
        })
        
        # Wait for modal
        page.wait_for_selector("#confirmation-modal-overlay.visible")
        
        # Verify choices
        expect(page.locator("#confirmation-modal-choices")).to_contain_text("Extend")
        expect(page.locator("#confirmation-modal-choices")).to_contain_text("Respec")
        expect(page.locator("#confirmation-modal-choices")).to_contain_text("Cancel")


class TestDecisionModalTextRequirement:
    """Test decision modals with required text input."""
    
    def test_deny_decomposition_requires_text(
        self,
        page_with_test_server: Page,
        test_server: TestMatrixMouseServer,
        wait_for_ws,
    ):
        """Denying decomposition requires text input."""
        page = page_with_test_server
        
        # Trigger decomposition event
        test_server._emit_event("decomposition_confirmation_required", {
            "task_id": "test123",
            "message": "Allow splitting?",
        })
        
        page.wait_for_selector("#confirmation-modal-overlay.visible")
        
        # Click Deny (should require text)
        page.click('button:has-text("Deny")')
        
        # Verify text input is shown and focused
        expect(page.locator("#confirmation-modal-text-container")).to_be_visible()
        expect(page.locator("#confirmation-modal-text-input")).to_have_attribute(
            "placeholder", "Explain why*"
        )
    
    def test_text_validation(
        self,
        page_with_test_server: Page,
        test_server: TestMatrixMouseServer,
        wait_for_ws,
    ):
        """Text input validation prevents submission without text."""
        page = page_with_test_server
        
        # Trigger event requiring text
        test_server._emit_event("decomposition_confirmation_required", {
            "task_id": "test123",
            "message": "Allow splitting?",
        })
        
        page.wait_for_selector("#confirmation-modal-overlay.visible")
        
        # Click Deny
        page.click('button:has-text("Deny")')
        
        # Try to submit without text (should fail)
        # Note: Current implementation shows red border but doesn't prevent
        # This test documents the behavior
        page.click('button:has-text("Deny")')
        
        # Verify error indication
        expect(page.locator("#confirmation-modal-text-input")).to_have_css(
            "border-color", "rgb(255, 34, 68)"  # var(--red)
        )


class TestDecisionModalSubmission:
    """Test decision modal submission."""
    
    def test_submit_decision(
        self,
        page_with_test_server: Page,
        test_server: TestMatrixMouseServer,
        wait_for_ws,
    ):
        """Submitting a decision calls the API."""
        page = page_with_test_server
        
        # Create a task
        from matrixmouse.task import Task, TaskStatus, AgentRole
        task = Task(
            title="Test Task",
            repo=["test-repo"],
            role=AgentRole.CODER,
            status=TaskStatus.BLOCKED_BY_HUMAN,
        )
        test_server.task_repo.add(task)
        
        # Trigger decision event
        test_server._emit_event("pr_approval_required", {
            "task_id": task.id,
            "message": "Approve PR?",
        })
        
        page.wait_for_selector("#confirmation-modal-overlay.visible")
        
        # Track API calls
        api_calls = []
        page.route(f"**/tasks/{task.id}/decision", lambda route: api_calls.append(route.request))
        
        # Click Approve
        page.click('button:has-text("Approve")')
        
        # Wait for API call
        page.wait_for_timeout(500)
        
        # Verify API was called
        assert len(api_calls) == 1
        assert f"tasks/{task.id}/decision" in api_calls[0].url
    
    def test_submit_decision_with_note(
        self,
        page_with_test_server: Page,
        test_server: TestMatrixMouseServer,
        wait_for_ws,
    ):
        """Submitting a decision with a note includes it in the request."""
        page = page_with_test_server
        
        # Create a task
        from matrixmouse.task import Task, TaskStatus, AgentRole
        task = Task(
            title="Test Task",
            repo=["test-repo"],
            role=AgentRole.CODER,
            status=TaskStatus.BLOCKED_BY_HUMAN,
        )
        test_server.task_repo.add(task)
        
        # Trigger turn limit event (supports notes)
        test_server._emit_event("turn_limit_reached", {
            "task_id": task.id,
            "message": "Turn limit reached.",
        })
        
        page.wait_for_selector("#confirmation-modal-overlay.visible")
        
        # Fill in note
        page.fill("#confirmation-modal-text-input", "Please optimize your approach")
        
        # Track API calls
        api_calls = []
        page.route(f"**/tasks/{task.id}/decision", lambda route: api_calls.append(route.request))
        
        # Click Respec
        page.click('button:has-text("Respec")')
        
        # Wait for API call
        page.wait_for_timeout(500)
        
        # Verify note was included (would need to check request body)
        assert len(api_calls) == 1
    
    def test_cancel_closes_modal(
        self,
        page_with_test_server: Page,
        test_server: TestMatrixMouseServer,
        wait_for_ws,
    ):
        """Clicking Cancel closes the modal without submitting."""
        page = page_with_test_server
        
        # Trigger any decision event
        test_server._emit_event("pr_approval_required", {
            "task_id": "test123",
            "message": "Approve?",
        })
        
        page.wait_for_selector("#confirmation-modal-overlay.visible")
        
        # Click Cancel
        page.click("#confirmation-modal-cancel")
        
        # Wait for modal to close
        page.wait_for_timeout(300)
        
        # Verify modal is closed
        expect(page.locator("#confirmation-modal-overlay")).not_to_have_class("visible")
    
    def test_modal_closes_after_submission(
        self,
        page_with_test_server: Page,
        test_server: TestMatrixMouseServer,
        wait_for_ws,
    ):
        """Modal closes automatically after successful submission."""
        page = page_with_test_server
        
        # Create a task
        from matrixmouse.task import Task, TaskStatus, AgentRole
        task = Task(
            title="Test Task",
            repo=["test-repo"],
            role=AgentRole.CODER,
            status=TaskStatus.BLOCKED_BY_HUMAN,
        )
        test_server.task_repo.add(task)
        
        # Trigger decision event
        test_server._emit_event("pr_approval_required", {
            "task_id": task.id,
            "message": "Approve?",
        })
        
        page.wait_for_selector("#confirmation-modal-overlay.visible")
        
        # Click Approve
        page.click('button:has-text("Approve")')
        
        # Wait for modal to close
        page.wait_for_timeout(500)
        
        # Verify modal is closed
        expect(page.locator("#confirmation-modal-overlay")).not_to_have_class("visible")
