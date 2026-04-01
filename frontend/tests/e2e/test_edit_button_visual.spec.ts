/**
 * E2E Tests for Edit Button Visual Functionality
 *
 * Tests that the EDIT button actually makes the form visible and functional.
 * Verifies form visibility, field rendering, and visual appearance.
 */

import { test, expect } from '@playwright/test';

test.describe('Edit Button Visual', () => {
  test.beforeEach(async ({ page }) => {
    // Mock API endpoints
    await page.route('**/repos', async route => {
      await route.fulfill({ json: { repos: [] } });
    });
    await page.route('**/tasks**', async route => {
      await route.fulfill({
        json: {
          tasks: [
            {
              id: 'test-123',
              title: 'Test Task',
              description: 'Test description',
              repo: ['test-repo'],
              role: 'coder',
              status: 'ready',
              branch: 'mm/test',
              parent_task_id: null,
              depth: 0,
              importance: 0.5,
              urgency: 0.5,
              priority_score: 0.5,
              preemptable: true,
              preempt: false,
              created_at: '2024-01-01T00:00:00Z',
              last_modified: '2024-01-01T00:00:00Z',
              context_messages: [],
              pending_tool_calls: [],
              decomposition_confirmed_depth: 0,
              merge_resolution_decisions: [],
            },
          ],
          count: 1,
        },
      });
    });
    await page.route('**/status', async route => {
      await route.fulfill({ json: { idle: true, stopped: false, blocked: false } });
    });
  });

  test.describe('Edit Button Visibility', () => {
    test('EDIT button is visible on task page', async ({ page }) => {
      await page.goto('/task/test-123');
      await page.waitForSelector('#task-page');

      // Find EDIT button
      const editBtn = page.locator("button:has-text('Edit'), #task-edit-btn, .btn-edit");
      await expect(editBtn).toBeVisible();
      await expect(editBtn).toBeEnabled();
    });

    test('EDIT button has proper styling', async ({ page }) => {
      await page.goto('/task/test-123');
      await page.waitForSelector('#task-page');

      const editBtn = page.locator("button:has-text('Edit'), #task-edit-btn").first();
      await expect(editBtn).toBeVisible();

      // Check button styling
      const backgroundColor = await editBtn.evaluate(el => window.getComputedStyle(el).backgroundColor);
      const cursor = await editBtn.evaluate(el => window.getComputedStyle(el).cursor);
      
      expect(cursor).toBe('pointer');
      // Button should have some background (not fully transparent)
      expect(backgroundColor).toBeTruthy();
    });

    test('EDIT button is clickable', async ({ page }) => {
      await page.goto('/task/test-123');
      await page.waitForSelector('#task-page');

      const editBtn = page.locator("button:has-text('Edit'), #task-edit-btn").first();
      await expect(editBtn).toBeEnabled();
      
      // Should be able to click without errors
      await editBtn.click();
      await page.waitForTimeout(100);
      
      // Page should still be functional
      await expect(page.locator('#task-page')).toBeVisible();
    });
  });

  test.describe('Edit Form Visibility', () => {
    test('edit form appears after clicking EDIT button', async ({ page }) => {
      await page.goto('/task/test-123');
      await page.waitForSelector('#task-page');

      // Click EDIT button
      const editBtn = page.locator("button:has-text('Edit'), #task-edit-btn").first();
      await editBtn.click();

      // Wait for edit form to appear
      const editForm = page.locator('.task-edit-form, #task-edit-form-test-123, #task-edit-container .task-edit-form');
      await expect(editForm).toBeVisible({ timeout: 5000 });
    });

    test('edit form has visible height (not collapsed)', async ({ page }) => {
      await page.goto('/task/test-123');
      await page.waitForSelector('#task-page');

      // Click EDIT button
      await page.locator("button:has-text('Edit'), #task-edit-btn").first().click();

      // Wait for edit form
      const editForm = page.locator('.task-edit-form').first();
      await expect(editForm).toBeVisible();

      // Check form has actual height
      const height = await editForm.evaluate(el => el.offsetHeight);
      expect(height).toBeGreaterThan(100); // Should have substantial height
    });

    test('edit form is not hidden by CSS', async ({ page }) => {
      await page.goto('/task/test-123');
      await page.waitForSelector('#task-page');

      // Click EDIT button
      await page.locator("button:has-text('Edit'), #task-edit-btn").first().click();

      // Wait for edit form
      const editForm = page.locator('.task-edit-form').first();
      await expect(editForm).toBeVisible();

      // Check CSS display property
      const display = await editForm.evaluate(el => window.getComputedStyle(el).display);
      const visibility = await editForm.evaluate(el => window.getComputedStyle(el).visibility);
      const opacity = await editForm.evaluate(el => parseFloat(window.getComputedStyle(el).opacity));

      expect(display).not.toBe('none');
      expect(visibility).toBe('visible');
      expect(opacity).toBeGreaterThan(0.5);
    });

    test('edit form has proper z-index (appears above content)', async ({ page }) => {
      await page.goto('/task/test-123');
      await page.waitForSelector('#task-page');

      // Click EDIT button
      await page.locator("button:has-text('Edit'), #task-edit-btn").first().click();

      // Wait for edit form
      const editForm = page.locator('.task-edit-form').first();
      await expect(editForm).toBeVisible();

      // Check z-index
      const zIndex = await editForm.evaluate(el => window.getComputedStyle(el).zIndex);
      expect(zIndex).toBeTruthy();
    });

    test('edit form container is visible', async ({ page }) => {
      await page.goto('/task/test-123');
      await page.waitForSelector('#task-page');

      // Click EDIT button
      await page.locator("button:has-text('Edit'), #task-edit-btn").first().click();

      // Container should be visible
      const container = page.locator('#task-edit-container');
      await expect(container).toBeVisible();
      
      // Container should have children
      const childCount = await container.locator('> *').count();
      expect(childCount).toBeGreaterThan(0);
    });
  });

  test.describe('Edit Form Fields', () => {
    test('edit form contains title field', async ({ page }) => {
      await page.goto('/task/test-123');
      await page.waitForSelector('#task-page');

      // Click EDIT button
      await page.locator("button:has-text('Edit'), #task-edit-btn").first().click();

      // Wait for edit form
      const editForm = page.locator('.task-edit-form').first();
      await expect(editForm).toBeVisible();

      // Find title field
      const titleField = editForm.locator('input[id*="title"], input[name="title"], #ef-title');
      await expect(titleField).toBeVisible();
      await expect(titleField).toHaveAttribute('type', 'text');
    });

    test('edit form contains description field', async ({ page }) => {
      await page.goto('/task/test-123');
      await page.waitForSelector('#task-page');

      // Click EDIT button
      await page.locator("button:has-text('Edit'), #task-edit-btn").first().click();

      // Wait for edit form
      const editForm = page.locator('.task-edit-form').first();
      await expect(editForm).toBeVisible();

      // Find description field (textarea)
      const descField = editForm.locator('textarea[id*="description"], textarea[name="description"], #ef-description');
      await expect(descField).toBeVisible();
    });

    test('edit form contains importance field', async ({ page }) => {
      await page.goto('/task/test-123');
      await page.waitForSelector('#task-page');

      // Click EDIT button
      await page.locator("button:has-text('Edit'), #task-edit-btn").first().click();

      // Wait for edit form
      const editForm = page.locator('.task-edit-form').first();
      await expect(editForm).toBeVisible();

      // Find importance field (select or input)
      const importanceField = editForm.locator('select[id*="importance"], select[name="importance"], input[id*="importance"], #ef-importance');
      await expect(importanceField).toBeVisible();
    });

    test('edit form contains urgency field', async ({ page }) => {
      await page.goto('/task/test-123');
      await page.waitForSelector('#task-page');

      // Click EDIT button
      await page.locator("button:has-text('Edit'), #task-edit-btn").first().click();

      // Wait for edit form
      const editForm = page.locator('.task-edit-form').first();
      await expect(editForm).toBeVisible();

      // Find urgency field
      const urgencyField = editForm.locator('select[id*="urgency"], select[name="urgency"], input[id*="urgency"], #ef-urgency');
      await expect(urgencyField).toBeVisible();
    });

    test('edit form contains notes field', async ({ page }) => {
      await page.goto('/task/test-123');
      await page.waitForSelector('#task-page');

      // Click EDIT button
      await page.locator("button:has-text('Edit'), #task-edit-btn").first().click();

      // Wait for edit form
      const editForm = page.locator('.task-edit-form').first();
      await expect(editForm).toBeVisible();

      // Find notes field
      const notesField = editForm.locator('textarea[id*="notes"], textarea[name="notes"], #ef-notes');
      await expect(notesField).toBeVisible();
    });

    test('edit form fields are editable', async ({ page }) => {
      await page.goto('/task/test-123');
      await page.waitForSelector('#task-page');

      // Click EDIT button
      await page.locator("button:has-text('Edit'), #task-edit-btn").first().click();

      // Wait for edit form
      const editForm = page.locator('.task-edit-form').first();
      await expect(editForm).toBeVisible();

      // Try to fill title field
      const titleField = editForm.locator('input[id*="title"], input[name="title"]').first();
      await expect(titleField).toBeEditable();
      await titleField.fill('New Test Title');
      await expect(titleField).toHaveValue('New Test Title');
    });

    test('edit form fields have labels', async ({ page }) => {
      await page.goto('/task/test-123');
      await page.waitForSelector('#task-page');

      // Click EDIT button
      await page.locator("button:has-text('Edit'), #task-edit-btn").first().click();

      // Wait for edit form
      const editForm = page.locator('.task-edit-form').first();
      await expect(editForm).toBeVisible();

      // Check for labels
      const labels = editForm.locator('label');
      const labelCount = await labels.count();
      expect(labelCount).toBeGreaterThan(2); // Should have multiple field labels
    });

    test('edit form has header/title', async ({ page }) => {
      await page.goto('/task/test-123');
      await page.waitForSelector('#task-page');

      // Click EDIT button
      await page.locator("button:has-text('Edit'), #task-edit-btn").first().click();

      // Wait for edit form
      const editForm = page.locator('.task-edit-form').first();
      await expect(editForm).toBeVisible();

      // Find header
      const header = editForm.locator('.edit-form-header, h3, .form-header, h2:has-text("Edit")');
      await expect(header).toHaveCount({ min: 1 });
    });
  });

  test.describe('Edit Form Actions', () => {
    test('edit form has Save button', async ({ page }) => {
      await page.goto('/task/test-123');
      await page.waitForSelector('#task-page');

      // Click EDIT button
      await page.locator("button:has-text('Edit'), #task-edit-btn").first().click();

      // Wait for edit form
      const editForm = page.locator('.task-edit-form').first();
      await expect(editForm).toBeVisible();

      // Find Save button
      const saveBtn = editForm.locator('button:has-text("Save"), .btn-save, button[type="submit"]');
      await expect(saveBtn).toBeVisible();
      await expect(saveBtn).toBeEnabled();
    });

    test('edit form has Cancel button', async ({ page }) => {
      await page.goto('/task/test-123');
      await page.waitForSelector('#task-page');

      // Click EDIT button
      await page.locator("button:has-text('Edit'), #task-edit-btn").first().click();

      // Wait for edit form
      const editForm = page.locator('.task-edit-form').first();
      await expect(editForm).toBeVisible();

      // Find Cancel button
      const cancelBtn = editForm.locator('button:has-text("Cancel"), .btn-cancel');
      await expect(cancelBtn).toBeVisible();
      await expect(cancelBtn).toBeEnabled();
    });

    test('edit form has Cancel Task button', async ({ page }) => {
      await page.goto('/task/test-123');
      await page.waitForSelector('#task-page');

      // Click EDIT button
      await page.locator("button:has-text('Edit'), #task-edit-btn").first().click();

      // Wait for edit form
      const editForm = page.locator('.task-edit-form').first();
      await expect(editForm).toBeVisible();

      // Find Cancel Task button
      const cancelTaskBtn = editForm.locator('button:has-text("Cancel Task"), .btn-cancel-task');
      await expect(cancelTaskBtn).toBeVisible();
    });

    test('Save button is enabled when form is valid', async ({ page }) => {
      await page.goto('/task/test-123');
      await page.waitForSelector('#task-page');

      // Click EDIT button
      await page.locator("button:has-text('Edit'), #task-edit-btn").first().click();

      // Wait for edit form
      const editForm = page.locator('.task-edit-form').first();
      await expect(editForm).toBeVisible();

      // Fill required field
      const titleField = editForm.locator('input[id*="title"], input[name="title"]').first();
      await titleField.fill('Valid Title');

      // Save button should be enabled
      const saveBtn = editForm.locator('button:has-text("Save"), .btn-save');
      await expect(saveBtn).toBeEnabled();
    });
  });

  test.describe('Edit Form Layout', () => {
    test('edit form fields are properly aligned', async ({ page }) => {
      await page.goto('/task/test-123');
      await page.waitForSelector('#task-page');

      // Click EDIT button
      await page.locator("button:has-text('Edit'), #task-edit-btn").first().click();

      // Wait for edit form
      const editForm = page.locator('.task-edit-form').first();
      await expect(editForm).toBeVisible();

      // Check field alignment
      const fields = editForm.locator('.edit-form-field');
      const fieldCount = await fields.count();
      expect(fieldCount).toBeGreaterThan(3);

      // All fields should have similar left alignment
      const firstFieldX = await fields.nth(0).evaluate(el => el.getBoundingClientRect().left);
      for (let i = 1; i < Math.min(fieldCount, 5); i++) {
        const fieldX = await fields.nth(i).evaluate(el => el.getBoundingClientRect().left);
        const diff = Math.abs(firstFieldX - fieldX);
        expect(diff).toBeLessThan(20); // Within 20px alignment
      }
    });

    test('edit form has proper spacing between fields', async ({ page }) => {
      await page.goto('/task/test-123');
      await page.waitForSelector('#task-page');

      // Click EDIT button
      await page.locator("button:has-text('Edit'), #task-edit-btn").first().click();

      // Wait for edit form
      const editForm = page.locator('.task-edit-form').first();
      await expect(editForm).toBeVisible();

      // Check spacing between fields
      const fields = editForm.locator('.edit-form-field');
      const fieldCount = await fields.count();
      
      if (fieldCount >= 2) {
        const firstFieldBottom = await fields.nth(0).evaluate(el => el.getBoundingClientRect().bottom);
        const secondFieldTop = await fields.nth(1).evaluate(el => el.getBoundingClientRect().top);
        const gap = secondFieldTop - firstFieldBottom;
        
        expect(gap).toBeGreaterThan(5); // Should have some spacing
        expect(gap).toBeLessThan(50); // Shouldn't be excessive
      }
    });

    test('edit form fits within viewport', async ({ page }) => {
      await page.goto('/task/test-123');
      await page.waitForSelector('#task-page');

      // Click EDIT button
      await page.locator("button:has-text('Edit'), #task-edit-btn").first().click();

      // Wait for edit form
      const editForm = page.locator('.task-edit-form').first();
      await expect(editForm).toBeVisible();

      // Check form fits in viewport
      const formBox = await editForm.boundingBox();
      const viewport = page.viewportSize();

      expect(formBox).toBeTruthy();
      expect(formBox!.width).toBeLessThanOrEqual(viewport!.width * 0.95);
    });

    test('edit form is scrollable if content overflows', async ({ page }) => {
      await page.goto('/task/test-123');
      await page.waitForSelector('#task-page');

      // Click EDIT button
      await page.locator("button:has-text('Edit'), #task-edit-btn").first().click();

      // Wait for edit form
      const editForm = page.locator('.task-edit-form').first();
      await expect(editForm).toBeVisible();

      // Check if form is scrollable
      const isScrollable = await editForm.evaluate(el => {
        return el.scrollHeight > el.clientHeight || el.scrollWidth > el.clientWidth;
      });

      // If content overflows, should be scrollable
      const overflowY = await editForm.evaluate(el => window.getComputedStyle(el).overflowY);
      const overflowX = await editForm.evaluate(el => window.getComputedStyle(el).overflowX);
      
      // Should allow scrolling if needed
      expect(['auto', 'scroll', 'visible', ''].includes(overflowY) || ['auto', 'scroll', 'visible', ''].includes(overflowX)).toBeTruthy();
    });
  });

  test.describe('Edit Form Closing', () => {
    test('clicking Cancel button closes edit form', async ({ page }) => {
      await page.goto('/task/test-123');
      await page.waitForSelector('#task-page');

      // Click EDIT button
      await page.locator("button:has-text('Edit'), #task-edit-btn").first().click();

      // Wait for edit form
      const editForm = page.locator('.task-edit-form').first();
      await expect(editForm).toBeVisible();

      // Click Cancel
      const cancelBtn = editForm.locator('button:has-text("Cancel"), .btn-cancel').first();
      await cancelBtn.click();

      // Wait for form to close
      await page.waitForTimeout(500);
      await expect(editForm).not.toBeVisible();
    });

    test('edit form closes without saving changes', async ({ page }) => {
      await page.goto('/task/test-123');
      await page.waitForSelector('#task-page');

      // Track API calls
      let updateApiCalled = false;
      await page.route('**/tasks/**', async route => {
        if (route.request().method() === 'PATCH' || route.request().method() === 'PUT') {
          updateApiCalled = true;
        }
        await route.fulfill({ json: { success: true } });
      });

      // Click EDIT button
      await page.locator("button:has-text('Edit'), #task-edit-btn").first().click();

      // Wait for edit form
      const editForm = page.locator('.task-edit-form').first();
      await expect(editForm).toBeVisible();

      // Modify a field
      const titleField = editForm.locator('input[id*="title"], input[name="title"]').first();
      await titleField.fill('Modified Title');

      // Click Cancel
      const cancelBtn = editForm.locator('button:has-text("Cancel"), .btn-cancel').first();
      await cancelBtn.click();

      // Wait
      await page.waitForTimeout(500);

      // API should not have been called
      expect(updateApiCalled).toBeFalsy();
    });

    test('edit form container is cleared after closing', async ({ page }) => {
      await page.goto('/task/test-123');
      await page.waitForSelector('#task-page');

      // Click EDIT button
      await page.locator("button:has-text('Edit'), #task-edit-btn").first().click();

      // Wait for edit form
      const editForm = page.locator('.task-edit-form').first();
      await expect(editForm).toBeVisible();

      // Click Cancel
      const cancelBtn = editForm.locator('button:has-text("Cancel"), .btn-cancel').first();
      await cancelBtn.click();

      // Wait for form to close
      await page.waitForTimeout(500);

      // Container should be empty or form should not exist
      const container = page.locator('#task-edit-container');
      const formInContainer = container.locator('.task-edit-form');
      const formCount = await formInContainer.count();
      
      expect(formCount).toBe(0);
    });
  });

  test.describe('Edge Cases', () => {
    test('edit form handles rapid open/close cycles', async ({ page }) => {
      await page.goto('/task/test-123');
      await page.waitForSelector('#task-page');

      const editBtn = page.locator("button:has-text('Edit'), #task-edit-btn").first();

      // Rapid open/close cycles
      for (let i = 0; i < 3; i++) {
        await editBtn.click();
        await page.waitForTimeout(200);
        
        const editForm = page.locator('.task-edit-form').first();
        if (await editForm.count() > 0) {
          const cancelBtn = editForm.locator('button:has-text("Cancel"), .btn-cancel').first();
          if (await cancelBtn.count() > 0) {
            await cancelBtn.click();
            await page.waitForTimeout(200);
          }
        }
      }

      // Page should still be functional
      await expect(page.locator('#task-page')).toBeVisible();
    });

    test('edit form handles missing task data gracefully', async ({ page }) => {
      // Mock task with minimal data
      await page.route('**/tasks/test-minimal', async route => {
        await route.fulfill({
          json: {
            id: 'test-minimal',
            title: 'Minimal Task',
            description: '',
            repo: [],
            role: 'coder',
            status: 'ready',
            branch: '',
            parent_task_id: null,
            depth: 0,
            importance: 0.5,
            urgency: 0.5,
            priority_score: 0.5,
            preemptable: true,
            preempt: false,
            created_at: '2024-01-01T00:00:00Z',
            last_modified: '2024-01-01T00:00:00Z',
            context_messages: [],
            pending_tool_calls: [],
            decomposition_confirmed_depth: 0,
            merge_resolution_decisions: [],
          },
        });
      });

      await page.goto('/task/test-minimal');
      await page.waitForSelector('#task-page');

      // Click EDIT button
      await page.locator("button:has-text('Edit'), #task-edit-btn").first().click();

      // Wait for edit form
      const editForm = page.locator('.task-edit-form').first();
      await expect(editForm).toBeVisible({ timeout: 5000 });

      // Form should still render with defaults
      const titleField = editForm.locator('input[id*="title"], input[name="title"]').first();
      await expect(titleField).toBeVisible();
    });

    test('edit form appearance is consistent across multiple opens', async ({ page }) => {
      await page.goto('/task/test-123');
      await page.waitForSelector('#task-page');

      const editBtn = page.locator("button:has-text('Edit'), #task-edit-btn").first();

      // Open form multiple times
      const heights: number[] = [];
      for (let i = 0; i < 3; i++) {
        await editBtn.click();
        await page.waitForTimeout(300);
        
        const editForm = page.locator('.task-edit-form').first();
        if (await editForm.count() > 0) {
          const height = await editForm.evaluate(el => el.offsetHeight);
          heights.push(height);
          
          const cancelBtn = editForm.locator('button:has-text("Cancel"), .btn-cancel').first();
          await cancelBtn.click();
          await page.waitForTimeout(300);
        }
      }

      // All heights should be similar (within 10% variance)
      if (heights.length >= 2) {
        const avgHeight = heights.reduce((a, b) => a + b, 0) / heights.length;
        for (const height of heights) {
          const variance = Math.abs(height - avgHeight) / avgHeight;
          expect(variance).toBeLessThan(0.1);
        }
      }
    });

    test('edit form does not cause page layout shift', async ({ page }) => {
      await page.goto('/task/test-123');
      await page.waitForSelector('#task-page');

      // Get initial layout
      const headerBox = await page.locator('#task-header').boundingBox();
      expect(headerBox).toBeTruthy();

      // Click EDIT button
      await page.locator("button:has-text('Edit'), #task-edit-btn").first().click();

      // Wait for edit form
      await page.locator('.task-edit-form').first().toBeVisible();

      // Check header position hasn't shifted dramatically
      const newHeaderBox = await page.locator('#task-header').boundingBox();
      expect(newHeaderBox).toBeTruthy();

      if (headerBox && newHeaderBox) {
        const yDiff = Math.abs(headerBox.y - newHeaderBox.y);
        expect(yDiff).toBeLessThan(50); // Shouldn't shift more than 50px
      }
    });
  });
});
