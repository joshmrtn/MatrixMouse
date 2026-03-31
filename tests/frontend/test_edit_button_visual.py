"""
tests/frontend/test_edit_button_visual.py

Visual tests that verify EDIT button actually opens the form.
Uses screenshots and computed styles to verify visibility.
"""

import pytest
from playwright.sync_api import Page, expect

from .test_server import TestMatrixMouseServer


class TestEditButtonVisual:
    """Test that EDIT button actually makes form visible."""
    
    def test_edit_form_visible_after_click(
        self,
        page_with_test_server: Page,
        test_server: TestMatrixMouseServer,
        wait_for_ws,
    ):
        """EDIT button click makes form VISIBLE (not just adds class)."""
        page = page_with_test_server
        
        # Create a task
        test_server.create_task(title="Visual Test Task", description="Test desc")
        
        # Navigate to Tasks tab
        page.click('[data-tab="tasks"]')
        page.wait_for_timeout(500)
        
        # Click the task to open conversation
        page.click('.task-title:has-text("Visual Test Task")')
        page.wait_for_timeout(500)
        
        # Click EDIT button
        page.click("button:has-text('Edit')")
        
        # Wait for the edit form to have inputs (not just the 'open' class)
        page.wait_for_selector(".task-edit-form.open input[id^='ef-title']", state='visible', timeout=5000)
        
        # Debug: Check what's on the page
        all_forms = page.locator(".task-edit-form")
        print(f"Total edit forms: {all_forms.count()}")
        for i in range(all_forms.count()):
            form = all_forms.nth(i)
            form_id = form.get_attribute('id')
            form_class = form.get_attribute('class')
            form_display = form.evaluate("el => window.getComputedStyle(el).display")
            form_height = form.evaluate("el => el.offsetHeight")
            form_children = form.evaluate("el => el.children.length")
            print(f"  Form {i}: id={form_id}, class={form_class}, display={form_display}, height={form_height}, children={form_children}")
            
            # Check children heights
            for j in range(min(3, form_children)):
                child = form.evaluate(f"el => el.children[{j}]")
                child_height = form.evaluate(f"el => el.children[{j}].offsetHeight")
                child_display = form.evaluate(f"el => window.getComputedStyle(el.children[{j}]).display")
                child_tag = form.evaluate(f"el => el.children[{j}].tagName")
                print(f"    Child {j}: tag={child_tag}, display={child_display}, height={child_height}")
                
                # If child is a div, check ITS children (the inputs)
                if child_tag == 'DIV':
                    grandchild_count = form.evaluate(f"el => el.children[{j}].children.length")
                    for k in range(min(2, grandchild_count)):
                        gc_height = form.evaluate(f"el => el.children[{j}].children[{k}].offsetHeight")
                        gc_tag = form.evaluate(f"el => el.children[{j}].children[{k}].tagName")
                        print(f"      Grandchild {k}: tag={gc_tag}, height={gc_height}")
        
        # Find the edit form
        edit_form = page.locator(".task-edit-form.open").first
        
        # Check computed style FIRST
        display = edit_form.evaluate("el => window.getComputedStyle(el).display")
        height = edit_form.evaluate("el => el.offsetHeight")
        print(f"Edit form display: {display}, height: {height}")
        
        # Check it exists
        try:
            edit_form.wait_for(state='visible', timeout=1000)
        except:
            print("Edit form with 'open' class not visible!")
            raise
        
        # Check computed style to ensure display is not 'none'
        display = edit_form.evaluate("el => window.getComputedStyle(el).display")
        assert display != "none", f"Edit form has display: {display}"
        assert display == "flex", f"Edit form should have display: flex, got: {display}"
        
        # Check it contains form elements
        expect(edit_form.locator("input[id^='ef-title']")).to_be_visible()
        expect(edit_form.locator("textarea[id^='ef-desc']")).to_be_visible()
    
    def test_edit_form_contains_all_fields(
        self,
        page_with_test_server: Page,
        test_server: TestMatrixMouseServer,
        wait_for_ws,
    ):
        """Edit form contains all expected fields."""
        page = page_with_test_server
        
        # Create a task
        test_server.create_task(
            title="Field Test",
            description="Test description",
            notes="Test notes",
            branch="mm/test",
            role="coder",
        )
        
        # Navigate and open edit form
        page.click('[data-tab="tasks"]')
        page.wait_for_timeout(300)
        page.click('.task-title:has-text("Field Test")')
        page.wait_for_timeout(300)
        page.click("button:has-text('Edit')")
        page.wait_for_timeout(200)
        
        edit_form = page.locator(".task-edit-form.open").first
        
        # Check all fields are visible
        expect(edit_form.locator("input[id^='ef-title']")).to_be_visible()
        expect(edit_form.locator("textarea[id^='ef-desc']")).to_be_visible()
        expect(edit_form.locator("textarea[id^='ef-notes']")).to_be_visible()
        expect(edit_form.locator("input[id^='ef-branch']")).to_be_visible()
        expect(edit_form.locator("select[id^='ef-role']")).to_be_visible()
        expect(edit_form.locator("input[id^='ef-imp']")).to_be_visible()
        expect(edit_form.locator("input[id^='ef-urg']")).to_be_visible()
        expect(edit_form.locator("input[id^='ef-turns']")).to_be_visible()
        
        # Check save/cancel buttons
        expect(edit_form.locator("button.save-btn")).to_be_visible()
        expect(edit_form.locator("button.cancel-btn")).to_be_visible()
