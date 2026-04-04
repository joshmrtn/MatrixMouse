/**
 * E2E Tests for Decision Modals
 *
 * Tests decision/moderation modal display and functionality.
 * These modals appear for:
 * - Decomposition confirmation
 * - PR approval
 * - Turn limit reached
 *
 * Tests verify modal rendering, choices, text validation, and submission.
 *
 * NOTE: These tests mock WebSocket events since we don't have a running backend.
 * In production, these events would come from the WebSocket connection.
 * 
 * ⚠️ STATUS (April 3, 2026): Tests are SKIPPED - the DecisionModal component
 * has not been implemented yet. These tests define the expected behavior for
 * future implementation. See PROJECT_HANDOFF.md "Decision Modals - Implementation Needed"
 */

import { test, expect } from '@playwright/test';

// SKIP: Component not implemented yet - tests define expected behavior
test.describe.skip('Decision Modals', () => {
  test.beforeEach(async ({ page }) => {
    // Mock API endpoints
    await page.route('**/repos', async route => {
      await route.fulfill({ json: { repos: [] } });
    });
    await page.route('**/tasks**', async route => {
      await route.fulfill({
        json: {
          tasks: [{
            id: 'test-123',
            title: 'Test Task',
            description: 'Test',
            repo: ['test-repo'],
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
          }],
          count: 1,
        },
      });
    });
    await page.route('**/status', async route => {
      await route.fulfill({ json: { idle: true, stopped: false, blocked: false } });
    });
    await page.route('**/tasks/*/decision', async route => {
      await route.fulfill({ json: { success: true } });
    });
  });

  test.describe('Modal Display', () => {
    test('decomposition modal displays with correct title and message', async ({ page }) => {
      await page.goto('/task/test-123');
      await page.waitForSelector('#task-page');

      // Trigger decomposition event via WebSocket simulation
      await page.evaluate(() => {
        const event = new CustomEvent('decomposition_confirmation_required', {
          detail: {
            task_id: 'test-123',
            message: 'Allow splitting task into subtasks?',
          },
        });
        window.dispatchEvent(event);
      });

      // Wait for modal to appear
      const modal = page.locator('#confirmation-modal-overlay');
      await expect(modal).toBeVisible({ timeout: 5000 });

      // Verify modal title
      const title = page.locator('#confirmation-modal-title');
      await expect(title).toBeVisible();
      await expect(title).toContainText(/decomposition|subtask/i);

      // Verify modal body contains message
      const body = page.locator('#confirmation-modal-body');
      await expect(body).toBeVisible();
      await expect(body).toContainText(/split|subtask/i);
    });

    test('decomposition modal shows Allow and Deny choices', async ({ page }) => {
      await page.goto('/task/test-123');
      await page.waitForSelector('#task-page');

      // Trigger decomposition event
      await page.evaluate(() => {
        window.dispatchEvent(new CustomEvent('decomposition_confirmation_required', {
          detail: { task_id: 'test-123', message: 'Allow splitting?' },
        }));
      });

      // Wait for modal
      await page.locator('#confirmation-modal-overlay').toBeVisible();

      // Verify Allow button
      const allowBtn = page.locator('button:has-text("Allow"), button:has-text("Confirm")');
      await expect(allowBtn).toBeVisible();
      await expect(allowBtn).toBeEnabled();

      // Verify Deny button
      const denyBtn = page.locator('button:has-text("Deny"), button:has-text("Cancel")');
      await expect(denyBtn).toBeVisible();
      await expect(denyBtn).toBeEnabled();
    });

    test('PR approval modal displays with correct title', async ({ page }) => {
      await page.goto('/task/pr-123');
      await page.waitForSelector('#task-page');

      // Trigger PR approval event
      await page.evaluate(() => {
        window.dispatchEvent(new CustomEvent('pr_approval_required', {
          detail: {
            task_id: 'pr-123',
            message: 'Approve this pull request?',
            pr_url: 'https://github.com/test/repo/pull/123',
          },
        }));
      });

      // Wait for modal
      const modal = page.locator('#confirmation-modal-overlay');
      await expect(modal).toBeVisible({ timeout: 5000 });

      // Verify title mentions PR/approval
      const title = page.locator('#confirmation-modal-title');
      await expect(title).toContainText(/PR|pull.*request|approval/i);
    });

    test('PR approval modal shows Approve and Reject choices', async ({ page }) => {
      await page.goto('/task/pr-123');
      await page.waitForSelector('#task-page');

      // Trigger PR approval event
      await page.evaluate(() => {
        window.dispatchEvent(new CustomEvent('pr_approval_required', {
          detail: { task_id: 'pr-123', message: 'Approve PR?' },
        }));
      });

      // Wait for modal
      await page.locator('#confirmation-modal-overlay').toBeVisible();

      // Verify Approve button
      const approveBtn = page.locator('button:has-text("Approve"), button:has-text("Allow")');
      await expect(approveBtn).toBeVisible();
      await expect(approveBtn).toBeEnabled();

      // Verify Reject button
      const rejectBtn = page.locator('button:has-text("Reject"), button:has-text("Deny")');
      await expect(rejectBtn).toBeVisible();
      await expect(rejectBtn).toBeEnabled();
    });

    test('turn limit modal displays with correct choices', async ({ page }) => {
      await page.goto('/task/limit-123');
      await page.waitForSelector('#task-page');

      // Trigger turn limit event
      await page.evaluate(() => {
        window.dispatchEvent(new CustomEvent('turn_limit_reached', {
          detail: {
            task_id: 'limit-123',
            message: 'Task has reached turn limit',
            turns_taken: 10,
            turn_limit: 10,
          },
        }));
      });

      // Wait for modal
      const modal = page.locator('#confirmation-modal-overlay');
      await expect(modal).toBeVisible({ timeout: 5000 });

      // Verify modal mentions turn limit
      const title = page.locator('#confirmation-modal-title');
      await expect(title).toContainText(/turn.*limit|maximum/i);
    });

    test('turn limit modal shows Extend, Respect, and Cancel choices', async ({ page }) => {
      await page.goto('/task/limit-123');
      await page.waitForSelector('#task-page');

      // Trigger turn limit event
      await page.evaluate(() => {
        window.dispatchEvent(new CustomEvent('turn_limit_reached', {
          detail: { task_id: 'limit-123', message: 'Turn limit reached' },
        }));
      });

      // Wait for modal
      await page.locator('#confirmation-modal-overlay').toBeVisible();

      // Should have at least 2-3 choice buttons
      const choiceButtons = page.locator('#confirmation-modal-choices button, button:has-text("Extend"), button:has-text("Respect"), button:has-text("Cancel"), button:has-text("Allow"), button:has-text("Deny")');
      await expect(choiceButtons).toHaveCount({ min: 2 });
    });
  });

  test.describe('Modal Visibility and Structure', () => {
    test('modal overlay covers entire viewport', async ({ page }) => {
      await page.goto('/task/test-123');
      await page.waitForSelector('#task-page');

      // Trigger modal
      await page.evaluate(() => {
        window.dispatchEvent(new CustomEvent('decomposition_confirmation_required', {
          detail: { task_id: 'test-123', message: 'Test' },
        }));
      });

      // Wait for overlay
      const overlay = page.locator('#confirmation-modal-overlay');
      await expect(overlay).toBeVisible();

      // Verify overlay dimensions
      const overlayBox = await overlay.boundingBox();
      const viewport = page.viewportSize();

      expect(overlayBox).toBeTruthy();
      expect(overlayBox!.width).toBeGreaterThanOrEqual(viewport!.width * 0.9);
      expect(overlayBox!.height).toBeGreaterThanOrEqual(viewport!.height * 0.9);
    });

    test('modal has proper z-index (appears above all content)', async ({ page }) => {
      await page.goto('/task/test-123');
      await page.waitForSelector('#task-page');

      // Trigger modal
      await page.evaluate(() => {
        window.dispatchEvent(new CustomEvent('decomposition_confirmation_required', {
          detail: { task_id: 'test-123', message: 'Test' },
        }));
      });

      // Wait for overlay
      const overlay = page.locator('#confirmation-modal-overlay');
      await expect(overlay).toBeVisible();

      // Verify overlay is on top by checking z-index
      const zIndex = await overlay.evaluate(el => window.getComputedStyle(el).zIndex);
      expect(zIndex).toMatch(/\d+/);
      expect(parseInt(zIndex)).toBeGreaterThan(100);
    });

    test('modal content is centered', async ({ page }) => {
      await page.goto('/task/test-123');
      await page.waitForSelector('#task-page');

      // Trigger modal
      await page.evaluate(() => {
        window.dispatchEvent(new CustomEvent('decomposition_confirmation_required', {
          detail: { task_id: 'test-123', message: 'Test' },
        }));
      });

      // Wait for modal content
      const modalContent = page.locator('#confirmation-modal-content, #confirmation-modal-overlay > div').first();
      await expect(modalContent).toBeVisible();

      // Verify content is centered (check margin/padding)
      const marginLeft = await modalContent.evaluate(el => window.getComputedStyle(el).marginLeft);
      const marginRight = await modalContent.evaluate(el => window.getComputedStyle(el).marginRight);
      
      // Should have auto margins or equal margins
      expect(marginLeft === 'auto' || marginRight === 'auto' || marginLeft === marginRight).toBeTruthy();
    });

    test('modal cannot be interacted with background content', async ({ page }) => {
      await page.goto('/task/test-123');
      await page.waitForSelector('#task-page');

      // Get a background element
      const backgroundElement = page.locator('#task-header, .task-title').first();
      await expect(backgroundElement).toBeVisible();

      // Trigger modal
      await page.evaluate(() => {
        window.dispatchEvent(new CustomEvent('decomposition_confirmation_required', {
          detail: { task_id: 'test-123', message: 'Test' },
        }));
      });

      // Wait for overlay
      await page.locator('#confirmation-modal-overlay').toBeVisible();

      // Try to click background element (should be blocked by overlay)
      // The click should not navigate or trigger any action
      await backgroundElement.click({ force: true, timeout: 1000 }).catch(() => {});

      // Modal should still be visible
      await expect(page.locator('#confirmation-modal-overlay')).toBeVisible();
    });
  });

  test.describe('Text Input Validation', () => {
    test('deny decomposition requires text input', async ({ page }) => {
      await page.goto('/task/test-123');
      await page.waitForSelector('#task-page');

      // Trigger decomposition event
      await page.evaluate(() => {
        window.dispatchEvent(new CustomEvent('decomposition_confirmation_required', {
          detail: { task_id: 'test-123', message: 'Allow splitting?', require_text_for_deny: true },
        }));
      });

      // Wait for modal
      await page.locator('#confirmation-modal-overlay').toBeVisible();

      // Click Deny button
      const denyBtn = page.locator('button:has-text("Deny"), button:has-text("Cancel")').first();
      await denyBtn.click();

      // Should show error or require text input
      // Either a text area appears or an error message
      const textInput = page.locator('textarea, input[type="text"], #confirmation-modal-note');
      const errorMsg = page.locator('text=/required/i, text=/provide.*reason/i, .error-message');

      // At least one should be visible
      const hasTextInput = await textInput.count() > 0;
      const hasError = await errorMsg.count() > 0;
      
      expect(hasTextInput || hasError).toBeTruthy();
    });

    test('empty text input is rejected', async ({ page }) => {
      await page.goto('/task/test-123');
      await page.waitForSelector('#task-page');

      // Trigger decomposition event with text requirement
      await page.evaluate(() => {
        window.dispatchEvent(new CustomEvent('decomposition_confirmation_required', {
          detail: { task_id: 'test-123', message: 'Allow splitting?', require_text_for_deny: true },
        }));
      });

      // Wait for modal
      await page.locator('#confirmation-modal-overlay').toBeVisible();

      // Find text input if it exists
      const textInput = page.locator('textarea, input[type="text"], #confirmation-modal-note').first();
      const textInputVisible = await textInput.count() > 0;

      if (textInputVisible) {
        // Try to submit with empty text
        const submitBtn = page.locator('button:has-text("Submit"), button:has-text("Confirm"), button:has-text("Deny")').last();
        await textInput.fill('');
        await submitBtn.click();

        // Should show error
        const errorMsg = page.locator('.error-message, text=/required/i, text=/cannot.*empty/i');
        await expect(errorMsg).toBeVisible({ timeout: 3000 });
      }
    });

    test('whitespace-only text input is rejected', async ({ page }) => {
      await page.goto('/task/test-123');
      await page.waitForSelector('#task-page');

      // Trigger event with text requirement
      await page.evaluate(() => {
        window.dispatchEvent(new CustomEvent('decomposition_confirmation_required', {
          detail: { task_id: 'test-123', message: 'Test', require_text_for_deny: true },
        }));
      });

      // Wait for modal
      await page.locator('#confirmation-modal-overlay').toBeVisible();

      // Find text input
      const textInput = page.locator('textarea, input[type="text"], #confirmation-modal-note').first();
      const textInputVisible = await textInput.count() > 0;

      if (textInputVisible) {
        // Try to submit with whitespace only
        const submitBtn = page.locator('button:has-text("Submit"), button:has-text("Confirm"), button:has-text("Deny")').last();
        await textInput.fill('   \n\t  ');
        await submitBtn.click();

        // Should show error
        const errorMsg = page.locator('.error-message, text=/required/i, text=/whitespace/i');
        await expect(errorMsg).toBeVisible({ timeout: 3000 });
      }
    });

    test('valid text input is accepted', async ({ page }) => {
      await page.goto('/task/test-123');
      await page.waitForSelector('#task-page');

      // Track API calls
      let apiCallMade = false;
      await page.route('**/tasks/*/decision', async route => {
        apiCallMade = true;
        await route.fulfill({ json: { success: true } });
      });

      // Trigger event with text requirement
      await page.evaluate(() => {
        window.dispatchEvent(new CustomEvent('decomposition_confirmation_required', {
          detail: { task_id: 'test-123', message: 'Test', require_text_for_deny: true },
        }));
      });

      // Wait for modal
      await page.locator('#confirmation-modal-overlay').toBeVisible();

      // Find text input
      const textInput = page.locator('textarea, input[type="text"], #confirmation-modal-note').first();
      const textInputVisible = await textInput.count() > 0;

      if (textInputVisible) {
        // Fill with valid text
        await textInput.fill('This is a valid reason for denial');
        
        // Submit
        const submitBtn = page.locator('button:has-text("Submit"), button:has-text("Confirm"), button:has-text("Deny")').last();
        await submitBtn.click();

        // Wait for API call
        await page.waitForTimeout(500);
        expect(apiCallMade).toBeTruthy();
      }
    });
  });

  test.describe('Modal Submission', () => {
    test('submit decision triggers API call', async ({ page }) => {
      await page.goto('/task/test-123');
      await page.waitForSelector('#task-page');

      // Track API calls
      let decisionApiCalled = false;
      await page.route('**/tasks/*/decision', async route => {
        decisionApiCalled = true;
        const postData = route.request().postDataJSON();
        
        // Verify request structure
        expect(postData).toHaveProperty('choice');
        expect(postData).toHaveProperty('task_id');
        
        await route.fulfill({ json: { success: true } });
      });

      // Trigger modal
      await page.evaluate(() => {
        window.dispatchEvent(new CustomEvent('decomposition_confirmation_required', {
          detail: { task_id: 'test-123', message: 'Test' },
        }));
      });

      // Wait for modal
      await page.locator('#confirmation-modal-overlay').toBeVisible();

      // Click Allow/Confirm button
      const allowBtn = page.locator('button:has-text("Allow"), button:has-text("Confirm"), button:has-text("Yes")').first();
      await allowBtn.click();

      // Wait for API call
      await page.waitForTimeout(500);
      expect(decisionApiCalled).toBeTruthy();
    });

    test('submit decision includes correct task_id', async ({ page }) => {
      await page.goto('/task/abc-123');
      await page.waitForSelector('#task-page');

      // Track API calls
      let capturedTaskId: string | null = null;
      await page.route('**/tasks/*/decision', async route => {
        const url = route.request().url();
        const match = url.match(/\/tasks\/([^/]+)\/decision/);
        if (match) {
          capturedTaskId = match[1];
        }
        await route.fulfill({ json: { success: true } });
      });

      // Trigger modal
      await page.evaluate(() => {
        window.dispatchEvent(new CustomEvent('decomposition_confirmation_required', {
          detail: { task_id: 'abc-123', message: 'Test' },
        }));
      });

      // Wait for modal
      await page.locator('#confirmation-modal-overlay').toBeVisible();

      // Click button
      const allowBtn = page.locator('button:has-text("Allow"), button:has-text("Confirm")').first();
      await allowBtn.click();

      // Wait for API call
      await page.waitForTimeout(500);
      expect(capturedTaskId).toBe('abc-123');
    });

    test('submit decision includes correct choice', async ({ page }) => {
      await page.goto('/task/test-123');
      await page.waitForSelector('#task-page');

      // Track API calls with choice verification
      let capturedChoice: string | null = null;
      await page.route('**/tasks/*/decision', async route => {
        const postData = route.request().postDataJSON();
        capturedChoice = postData.choice;
        await route.fulfill({ json: { success: true } });
      });

      // Trigger modal
      await page.evaluate(() => {
        window.dispatchEvent(new CustomEvent('decomposition_confirmation_required', {
          detail: { task_id: 'test-123', message: 'Test' },
        }));
      });

      // Wait for modal
      await page.locator('#confirmation-modal-overlay').toBeVisible();

      // Click Deny button
      const denyBtn = page.locator('button:has-text("Deny"), button:has-text("Cancel"), button:has-text("No")').first();
      await denyBtn.click();

      // Wait for API call
      await page.waitForTimeout(500);
      expect(capturedChoice).toBeTruthy();
      expect(capturedChoice!.toLowerCase()).toMatch(/deny|cancel|no|reject/);
    });

    test('submit decision with note includes metadata', async ({ page }) => {
      await page.goto('/task/test-123');
      await page.waitForSelector('#task-page');

      // Track API calls
      let capturedNote: string | null = null;
      await page.route('**/tasks/*/decision', async route => {
        const postData = route.request().postDataJSON();
        if (postData.note) {
          capturedNote = postData.note;
        }
        await route.fulfill({ json: { success: true } });
      });

      // Trigger modal with note field
      await page.evaluate(() => {
        window.dispatchEvent(new CustomEvent('decomposition_confirmation_required', {
          detail: { task_id: 'test-123', message: 'Test', show_note_field: true },
        }));
      });

      // Wait for modal
      await page.locator('#confirmation-modal-overlay').toBeVisible();

      // Fill note if field exists
      const noteField = page.locator('textarea, #confirmation-modal-note, input[name="note"]').first();
      const noteFieldVisible = await noteField.count() > 0;

      if (noteFieldVisible) {
        await noteField.fill('Test note for decision');
      }

      // Submit
      const submitBtn = page.locator('button:has-text("Submit"), button:has-text("Confirm"), button:has-text("Deny")').last();
      await submitBtn.click();

      // Wait for API call
      await page.waitForTimeout(500);
      
      // Note should be captured if field existed
      if (noteFieldVisible) {
        expect(capturedNote).toBe('Test note for decision');
      }
    });

    test('modal closes after successful submission', async ({ page }) => {
      await page.goto('/task/test-123');
      await page.waitForSelector('#task-page');

      // Mock successful API response
      await page.route('**/tasks/*/decision', async route => {
        await route.fulfill({ json: { success: true } });
      });

      // Trigger modal
      await page.evaluate(() => {
        window.dispatchEvent(new CustomEvent('decomposition_confirmation_required', {
          detail: { task_id: 'test-123', message: 'Test' },
        }));
      });

      // Wait for modal
      await page.locator('#confirmation-modal-overlay').toBeVisible();

      // Submit
      const allowBtn = page.locator('button:has-text("Allow"), button:has-text("Confirm")').first();
      await allowBtn.click();

      // Wait for modal to close
      await page.waitForTimeout(1000);
      await expect(page.locator('#confirmation-modal-overlay')).not.toBeVisible();
    });

    test('cancel button closes modal without API call', async ({ page }) => {
      await page.goto('/task/test-123');
      await page.waitForSelector('#task-page');

      // Track API calls
      let apiCallMade = false;
      await page.route('**/tasks/*/decision', async route => {
        apiCallMade = true;
        await route.fulfill({ json: { success: true } });
      });

      // Trigger modal
      await page.evaluate(() => {
        window.dispatchEvent(new CustomEvent('decomposition_confirmation_required', {
          detail: { task_id: 'test-123', message: 'Test' },
        }));
      });

      // Wait for modal
      await page.locator('#confirmation-modal-overlay').toBeVisible();

      // Click cancel/close button
      const cancelBtn = page.locator('button:has-text("Cancel"), button:has-text("Close"), #confirmation-modal-close');
      if (await cancelBtn.count() > 0) {
        await cancelBtn.first().click();
        
        // Wait for modal to close
        await page.waitForTimeout(500);
        await expect(page.locator('#confirmation-modal-overlay')).not.toBeVisible();
        
        // API should not have been called
        expect(apiCallMade).toBeFalsy();
      }
    });

    test('clicking overlay closes modal', async ({ page }) => {
      await page.goto('/task/test-123');
      await page.waitForSelector('#task-page');

      // Trigger modal
      await page.evaluate(() => {
        window.dispatchEvent(new CustomEvent('decomposition_confirmation_required', {
          detail: { task_id: 'test-123', message: 'Test' },
        }));
      });

      // Wait for modal
      await page.locator('#confirmation-modal-overlay').toBeVisible();

      // Click on overlay (not modal content)
      await page.locator('#confirmation-modal-overlay').click({ position: { x: 10, y: 10 } });

      // Wait for modal to close
      await page.waitForTimeout(500);
      await expect(page.locator('#confirmation-modal-overlay')).not.toBeVisible();
    });

    test('Escape key closes modal', async ({ page }) => {
      await page.goto('/task/test-123');
      await page.waitForSelector('#task-page');

      // Trigger modal
      await page.evaluate(() => {
        window.dispatchEvent(new CustomEvent('decomposition_confirmation_required', {
          detail: { task_id: 'test-123', message: 'Test' },
        }));
      });

      // Wait for modal
      await page.locator('#confirmation-modal-overlay').toBeVisible();

      // Press Escape
      await page.keyboard.press('Escape');

      // Wait for modal to close
      await page.waitForTimeout(500);
      await expect(page.locator('#confirmation-modal-overlay')).not.toBeVisible();
    });
  });

  test.describe('Edge Cases', () => {
    test('modal handles rapid event triggering', async ({ page }) => {
      await page.goto('/task/test-123');
      await page.waitForSelector('#task-page');

      // Trigger multiple events rapidly
      await page.evaluate(() => {
        for (let i = 0; i < 5; i++) {
          window.dispatchEvent(new CustomEvent('decomposition_confirmation_required', {
            detail: { task_id: `test-${i}`, message: `Event ${i}` },
          }));
        }
      });

      // Should only show one modal (or handle gracefully)
      const modals = page.locator('#confirmation-modal-overlay');
      const count = await modals.count();
      
      // Should have at most 1 modal visible
      expect(count).toBeLessThanOrEqual(1);
    });

    test('modal handles missing event data gracefully', async ({ page }) => {
      await page.goto('/task/test-123');
      await page.waitForSelector('#task-page');

      // Trigger event with minimal/missing data
      await page.evaluate(() => {
        window.dispatchEvent(new CustomEvent('decomposition_confirmation_required', {
          detail: {},
        }));
      });

      // Should either show modal with defaults or not crash
      await page.waitForTimeout(1000);
      
      // Page should still be functional
      await expect(page.locator('#task-page')).toBeVisible();
    });

    test('modal handles unknown event type', async ({ page }) => {
      await page.goto('/task/test-123');
      await page.waitForSelector('#task-page');

      // Trigger unknown event type
      await page.evaluate(() => {
        window.dispatchEvent(new CustomEvent('unknown_event_type', {
          detail: { task_id: 'test-123' },
        }));
      });

      // Should not crash
      await page.waitForTimeout(500);
      await expect(page.locator('#task-page')).toBeVisible();
    });

    test('modal appearance does not break page layout', async ({ page }) => {
      await page.goto('/task/test-123');
      await page.waitForSelector('#task-page');

      // Get initial layout
      const initialLayout = await page.locator('#task-page').boundingBox();

      // Trigger modal
      await page.evaluate(() => {
        window.dispatchEvent(new CustomEvent('decomposition_confirmation_required', {
          detail: { task_id: 'test-123', message: 'Test' },
        }));
      });

      // Wait for modal
      await page.locator('#confirmation-modal-overlay').toBeVisible();

      // Page layout should not shift dramatically
      const modalLayout = await page.locator('#task-page').boundingBox();

      expect(initialLayout).toBeTruthy();
      expect(modalLayout).toBeTruthy();

      // Layout should be similar (within 10% tolerance)
      if (initialLayout && modalLayout) {
        const widthDiff = Math.abs(initialLayout.width - modalLayout.width) / initialLayout.width;
        expect(widthDiff).toBeLessThan(0.1);
      }
    });
  });

  test.describe('Error Handling', () => {
    test('handles API error on decision submission', async ({ page }) => {
      await page.goto('/task/test-123');
      await page.waitForSelector('#task-page');

      // Mock API error
      await page.route('**/tasks/*/decision', async route => {
        await route.fulfill({ status: 500, json: { error: 'Failed to submit decision' } });
      });

      // Trigger modal
      await page.evaluate(() => {
        window.dispatchEvent(new CustomEvent('decomposition_confirmation_required', {
          detail: { task_id: 'test-123', message: 'Test' },
        }));
      });

      // Wait for modal
      await page.locator('#confirmation-modal-overlay').toBeVisible();

      // Click Allow button
      const allowBtn = page.locator('button:has-text("Allow"), button:has-text("Confirm")').first();
      await allowBtn.click();

      // Wait for API response
      await page.waitForTimeout(500);

      // Modal should still be open (not closed on error)
      await expect(page.locator('#confirmation-modal-overlay')).toBeVisible();
    });

    test('handles network timeout on decision submission', async ({ page }) => {
      await page.goto('/task/test-123');
      await page.waitForSelector('#task-page');

      // Mock network abort
      await page.route('**/tasks/*/decision', async route => {
        route.abort('failed');
      });

      // Trigger modal
      await page.evaluate(() => {
        window.dispatchEvent(new CustomEvent('decomposition_confirmation_required', {
          detail: { task_id: 'test-123', message: 'Test' },
        }));
      });

      // Wait for modal
      await page.locator('#confirmation-modal-overlay').toBeVisible();

      // Click Allow button
      const allowBtn = page.locator('button:has-text("Allow"), button:has-text("Confirm")').first();
      await allowBtn.click();

      // Wait for timeout
      await page.waitForTimeout(1000);

      // Page should still be functional
      await expect(page.locator('#task-page')).toBeVisible();
    });

    test('handles malformed API response', async ({ page }) => {
      await page.goto('/task/test-123');
      await page.waitForSelector('#task-page');

      // Mock malformed response
      await page.route('**/tasks/*/decision', async route => {
        await route.fulfill({ status: 200, body: 'Invalid JSON' });
      });

      // Trigger modal
      await page.evaluate(() => {
        window.dispatchEvent(new CustomEvent('decomposition_confirmation_required', {
          detail: { task_id: 'test-123', message: 'Test' },
        }));
      });

      // Wait for modal
      await page.locator('#confirmation-modal-overlay').toBeVisible();

      // Click Allow button
      const allowBtn = page.locator('button:has-text("Allow"), button:has-text("Confirm")').first();
      await allowBtn.click();

      // Wait for response
      await page.waitForTimeout(500);

      // Page should handle gracefully
      await expect(page.locator('#task-page')).toBeVisible();
    });
  });
});
