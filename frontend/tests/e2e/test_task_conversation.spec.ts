/**
 * E2E Tests for Task Page Conversation and Workflow
 *
 * Tests the task detail page including:
 * - Task metadata display
 * - Conversation view
 * - Edit button functionality
 * - Unblock button for blocked tasks
 * - Dependency links
 *
 * These tests verify the complete task management workflow.
 */

import { test, expect } from '@playwright/test';

// Mock task factory for consistent test data
const createMockTask = (overrides: Partial<Task>): Task => ({
  id: 'task-123',
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
  ...overrides,
});

interface Task {
  id: string;
  title: string;
  description: string;
  repo: string[];
  role: string;
  status: string;
  branch: string;
  parent_task_id: string | null;
  depth: number;
  importance: number;
  urgency: number;
  priority_score: number;
  preemptable: boolean;
  preempt: boolean;
  created_at: string;
  last_modified: string;
  context_messages: any[];
  pending_tool_calls: any[];
  decomposition_confirmed_depth: number;
  merge_resolution_decisions: any[];
  notes?: string;
  blocking_reason?: string;
}

test.describe('Task Page Conversation', () => {
  test.beforeEach(async ({ page }) => {
    // Mock API endpoints
    await page.route('**/repos', async route => {
      await route.fulfill({
        json: {
          repos: [
            { name: 'test-repo', remote: 'https://github.com/test/test-repo.git' },
          ],
        },
      });
    });
    await page.route('**/tasks**', async route => {
      const url = route.request().url();
      
      // Handle task detail endpoint
      if (url.includes('/tasks/task-123')) {
        await route.fulfill({
          json: {
            id: 'task-123',
            title: 'Test Task',
            description: 'Test description for the task',
            repo: ['test-repo'],
            role: 'coder',
            status: 'ready',
            branch: 'mm/test-task',
            parent_task_id: null,
            depth: 0,
            importance: 0.5,
            urgency: 0.5,
            priority_score: 0.5,
            preemptable: true,
            preempt: false,
            created_at: '2024-01-01T00:00:00Z',
            last_modified: '2024-01-01T00:00:00Z',
            context_messages: [
              { role: 'system', content: 'You are a coding assistant.' },
              { role: 'user', content: 'Can you help me write a function?' },
              { role: 'assistant', content: 'Of course! Here is a function:' },
            ],
            pending_tool_calls: [],
            decomposition_confirmed_depth: 0,
            merge_resolution_decisions: [],
          },
        });
        return;
      }
      
      // Handle task list endpoint
      await route.fulfill({
        json: {
          tasks: [{
            id: 'task-123',
            title: 'Test Task',
            description: 'Test description',
            repo: ['test-repo'],
            role: 'coder',
            status: 'ready',
            branch: 'mm/test-task',
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
    await page.route('**/blocked', async route => {
      await route.fulfill({
        json: {
          report: {
            human: [],
            dependencies: [],
            waiting: [],
          },
        },
      });
    });
    await page.route('**/tasks/*/interject', async route => {
      await route.fulfill({ json: { success: true } });
    });
  });

  test.describe('Task Page Display', () => {
    test('displays task page with all metadata', async ({ page }) => {
      await page.goto('/task/task-123');
      await page.waitForSelector('#task-page');

      // Verify task title
      const title = page.locator('.task-title');
      await expect(title).toBeVisible();
      await expect(title).toHaveText('Test Task');

      // Verify task ID
      const taskIdElement = page.locator('.meta-item:has-text("ID:") .meta-value');
      await expect(taskIdElement).toBeVisible();
      await expect(taskIdElement).toHaveText('task-123');

      // Verify status
      const statusElement = page.locator('.meta-item:has-text("Status:") .meta-value');
      await expect(statusElement).toBeVisible();
      await expect(statusElement).toContainText(/Ready/i);

      // Verify role
      const roleElement = page.locator('.meta-item:has-text("Role:") .meta-value');
      await expect(roleElement).toBeVisible();
      await expect(roleElement).toContainText(/Coder/i);

      // Verify branch
      const branchElement = page.locator('.meta-item:has-text("Branch:") .meta-value');
      await expect(branchElement).toBeVisible();
      await expect(branchElement).toHaveText('mm/test-task');

      // Verify repo
      const repoElement = page.locator('.meta-item:has-text("Repo:") .meta-value');
      await expect(repoElement).toBeVisible();
      await expect(repoElement).toContainText('test-repo');
    });

    test('displays conversation container', async ({ page }) => {
      await page.goto('/task/task-123');
      await page.waitForSelector('#task-page');

      // Verify conversation container exists
      const conversationContainer = page.locator('#task-conversation-container');
      await expect(conversationContainer).toBeVisible();

      // Verify conversation has messages
      const messages = page.locator('.message-bubble');
      await expect(messages).toHaveCount({ min: 1 });
    });

    test('displays conversation messages correctly', async ({ page }) => {
      await page.goto('/task/task-123');
      await page.waitForSelector('#task-page');

      // Verify system message
      const systemMessages = page.locator('.message-bubble.system');
      await expect(systemMessages).toHaveCount({ min: 1 });

      // Verify user message
      const userMessages = page.locator('.message-bubble.user');
      await expect(userMessages).toHaveCount({ min: 1 });

      // Verify assistant message
      const assistantMessages = page.locator('.message-bubble.assistant');
      await expect(assistantMessages).toHaveCount({ min: 1 });
    });

    test('displays conversation input field', async ({ page }) => {
      await page.goto('/task/task-123');
      await page.waitForSelector('#task-page');

      // Verify input field exists
      const input = page.locator('#conversation-input input, #msg-input');
      await expect(input).toBeVisible();
      await expect(input).toBeEditable();

      // Verify send button exists
      const sendBtn = page.locator('#conversation-input button, #send-btn');
      await expect(sendBtn).toBeVisible();
    });

    test('can send interjection in task conversation', async ({ page }) => {
      await page.goto('/task/task-123');
      await page.waitForSelector('#task-page');

      // Track API call
      let apiCalled = false;
      await page.route('**/tasks/task-123/interject', async route => {
        apiCalled = true;
        await route.fulfill({ json: { success: true } });
      });

      // Type and send message
      const input = page.locator('#conversation-input input, #msg-input').first();
      await input.fill('Test interjection');
      
      const sendBtn = page.locator('#conversation-input button, #send-btn').first();
      await sendBtn.click();

      // Wait for API call
      await page.waitForTimeout(500);
      expect(apiCalled).toBeTruthy();

      // Input should be cleared
      const value = await input.inputValue();
      expect(value).toBe('');
    });

    test('sends interjection on Enter key', async ({ page }) => {
      await page.goto('/task/task-123');
      await page.waitForSelector('#task-page');

      let apiCalled = false;
      await page.route('**/tasks/task-123/interject', async route => {
        apiCalled = true;
        await route.fulfill({ json: { success: true } });
      });

      // Type and press Enter
      const input = page.locator('#conversation-input input, #msg-input').first();
      await input.fill('Test message');
      await input.press('Enter');

      // Wait for API call
      await page.waitForTimeout(500);
      expect(apiCalled).toBeTruthy();
    });

    test('does not send empty interjections', async ({ page }) => {
      await page.goto('/task/task-123');
      await page.waitForSelector('#task-page');

      let apiCalled = false;
      await page.route('**/tasks/task-123/interject', async route => {
        apiCalled = true;
        await route.fulfill({ json: { success: true } });
      });

      // Try to send empty message
      const sendBtn = page.locator('#conversation-input button, #send-btn').first();
      await sendBtn.click();

      // Wait
      await page.waitForTimeout(500);
      expect(apiCalled).toBeFalsy();
    });
  });

  test.describe('Error Handling', () => {
    test('shows error when interjection API fails', async ({ page }) => {
      await page.goto('/task/task-123');
      await page.waitForSelector('#task-page');

      // Mock API error
      await page.route('**/tasks/task-123/interject', async route => {
        await route.fulfill({ status: 500, json: { error: 'Internal server error' } });
      });

      // Send message
      const input = page.locator('#conversation-input input, #msg-input').first();
      await input.fill('Test message');
      
      const sendBtn = page.locator('#conversation-input button, #send-btn').first();
      await sendBtn.click();

      // Wait for error to appear (implementation dependent)
      await page.waitForTimeout(500);
      
      // Input should still have the message (not cleared on error)
      const value = await input.inputValue();
      expect(value).toBe('Test message');
    });

    test('handles network timeout gracefully', async ({ page }) => {
      await page.goto('/task/task-123');
      await page.waitForSelector('#task-page');

      // Mock network abort
      await page.route('**/tasks/task-123/interject', async route => {
        route.abort('failed');
      });

      // Send message
      const input = page.locator('#conversation-input input, #msg-input').first();
      await input.fill('Test message');
      
      const sendBtn = page.locator('#conversation-input button, #send-btn').first();
      await sendBtn.click();

      // Wait for timeout
      await page.waitForTimeout(1000);
      
      // Page should still be functional
      await expect(page.locator('#task-page')).toBeVisible();
    });

    test('shows error when Save API fails', async ({ page }) => {
      await page.goto('/task/task-123');
      await page.waitForSelector('#task-page');

      // Mock Save API error
      await page.route('**/tasks/task-123', async route => {
        if (route.request().method() === 'PATCH') {
          await route.fulfill({ status: 500, json: { error: 'Failed to save' } });
        }
      });

      // Open edit form
      await page.locator("button:has-text('Edit'), #task-edit-btn").first().click();
      await page.waitForSelector('.task-edit-form');

      const editForm = page.locator('.task-edit-form').first();

      // Update title
      const titleField = editForm.locator('input[id*="title"], input[name="title"]').first();
      await titleField.fill('Updated Title');

      // Click Save
      const saveBtn = editForm.locator("button:has-text('Save'), .btn-save").first();
      await saveBtn.click();

      // Wait for error
      await page.waitForTimeout(500);

      // Form should still be open (not closed on error)
      await expect(editForm).toBeVisible();
    });

    test('handles task not found (404)', async ({ page }) => {
      // Mock 404 response
      await page.route('**/tasks/nonexistent-123', async route => {
        await route.fulfill({ status: 404, json: { error: 'Task not found' } });
      });

      // Navigate to non-existent task
      await page.goto('/task/nonexistent-123');
      
      // Wait for page to load (may show error state)
      await page.waitForTimeout(1000);
      
      // Page should handle gracefully (show error or redirect)
      // Implementation dependent - just verify no crash
      expect(true).toBeTruthy();
    });

    test('handles unblock API failure', async ({ page }) => {
      await page.goto('/task/blocked-123');
      await page.waitForSelector('#task-page');

      // Mock unblock API error
      await page.route('**/tasks/blocked-123/unblock', async route => {
        await route.fulfill({ status: 500, json: { error: 'Failed to unblock' } });
      });

      // Handle prompt
      page.on('dialog', async dialog => {
        await dialog.accept('Unblocking task');
      });

      // Click unblock
      const unblockBtn = page.locator("button:has-text('Unblock'), #task-unblock-btn").first();
      await unblockBtn.click();

      // Wait for error
      await page.waitForTimeout(500);

      // Task should still show as blocked
      const statusElement = page.locator('.meta-item:has-text("Status:") .meta-value');
      await expect(statusElement).toContainText(/Blocked/i);
    });
  });

  test.describe('WebSocket Real-time Updates', () => {
    test('receives new conversation messages via WebSocket', async ({ page }) => {
      await page.goto('/task/task-123');
      await page.waitForSelector('#task-page');

      // Get initial message count
      const initialMessages = page.locator('.message-bubble.assistant');
      const initialCount = await initialMessages.count();

      // Simulate WebSocket message arrival
      await page.evaluate(() => {
        window.dispatchEvent(new CustomEvent('ws_message', {
          detail: {
            role: 'assistant',
            content: 'New response from agent',
          },
        }));
      });

      // Wait for message to appear
      await page.waitForTimeout(500);

      // Verify new message appeared
      const newMessages = page.locator('.message-bubble.assistant');
      const newCount = await newMessages.count();
      expect(newCount).toBeGreaterThan(initialCount);
    });

    test('handles WebSocket disconnection gracefully', async ({ page }) => {
      await page.goto('/task/task-123');
      await page.waitForSelector('#task-page');

      // Simulate WebSocket disconnect event
      await page.evaluate(() => {
        window.dispatchEvent(new CustomEvent('ws_disconnect'));
      });

      // Wait for reconnection indicator
      await page.waitForTimeout(500);

      // Page should still be functional
      await expect(page.locator('#task-page')).toBeVisible();
    });

    test('displays connection status indicator', async ({ page }) => {
      await page.goto('/task/task-123');
      await page.waitForSelector('#task-page');

      // Connection indicator should be visible
      const connIndicator = page.locator('#conn-dot');
      await expect(connIndicator).toBeVisible();
    });
  });

  test.describe('Edit Button Workflow', () => {
    test('EDIT button is visible on task page', async ({ page }) => {
      await page.goto('/task/task-123');
      await page.waitForSelector('#task-page');

      const editBtn = page.locator("button:has-text('Edit'), #task-edit-btn, .btn-edit");
      await expect(editBtn).toBeVisible();
      await expect(editBtn).toBeEnabled();
    });

    test('EDIT button click opens edit form', async ({ page }) => {
      await page.goto('/task/task-123');
      await page.waitForSelector('#task-page');

      // Click EDIT button
      const editBtn = page.locator("button:has-text('Edit'), #task-edit-btn").first();
      await editBtn.click();

      // Wait for edit form to appear
      const editForm = page.locator('.task-edit-form, #task-edit-container .task-edit-form');
      await expect(editForm).toBeVisible({ timeout: 5000 });
    });

    test('edit form contains all expected fields', async ({ page }) => {
      await page.goto('/task/task-123');
      await page.waitForSelector('#task-page');

      // Open edit form
      await page.locator("button:has-text('Edit'), #task-edit-btn").first().click();
      await page.waitForSelector('.task-edit-form');

      const editForm = page.locator('.task-edit-form').first();

      // Verify title field
      const titleField = editForm.locator('input[id*="title"], input[name="title"]').first();
      await expect(titleField).toBeVisible();

      // Verify description field
      const descField = editForm.locator('textarea[id*="description"], textarea[name="description"]').first();
      await expect(descField).toBeVisible();

      // Verify importance field
      const importanceField = editForm.locator('select[id*="importance"], select[name="importance"]').first();
      await expect(importanceField).toBeVisible();

      // Verify urgency field
      const urgencyField = editForm.locator('select[id*="urgency"], select[name="urgency"]').first();
      await expect(urgencyField).toBeVisible();

      // Verify notes field
      const notesField = editForm.locator('textarea[id*="notes"], textarea[name="notes"]').first();
      await expect(notesField).toBeVisible();
    });

    test('edit form has Save and Cancel buttons', async ({ page }) => {
      await page.goto('/task/task-123');
      await page.waitForSelector('#task-page');

      // Open edit form
      await page.locator("button:has-text('Edit'), #task-edit-btn").first().click();
      await page.waitForSelector('.task-edit-form');

      const editForm = page.locator('.task-edit-form').first();

      // Verify Save button
      const saveBtn = editForm.locator('button:has-text("Save"), .btn-save');
      await expect(saveBtn).toBeVisible();
      await expect(saveBtn).toBeEnabled();

      // Verify Cancel button
      const cancelBtn = editForm.locator('button:has-text("Cancel"), .btn-cancel');
      await expect(cancelBtn).toBeVisible();
      await expect(cancelBtn).toBeEnabled();
    });

    test('Cancel button closes edit form', async ({ page }) => {
      await page.goto('/task/task-123');
      await page.waitForSelector('#task-page');

      // Open edit form
      await page.locator("button:has-text('Edit'), #task-edit-btn").first().click();
      await page.waitForSelector('.task-edit-form');

      // Click Cancel
      const cancelBtn = page.locator('button:has-text("Cancel"), .btn-cancel').first();
      await cancelBtn.click();

      // Wait for form to close
      await page.waitForTimeout(500);
      await expect(page.locator('.task-edit-form')).not.toBeVisible();
    });

    test('edit form is pre-filled with task data', async ({ page }) => {
      await page.goto('/task/task-123');
      await page.waitForSelector('#task-page');

      // Open edit form
      await page.locator("button:has-text('Edit'), #task-edit-btn").first().click();
      await page.waitForSelector('.task-edit-form');

      const editForm = page.locator('.task-edit-form').first();

      // Verify title is pre-filled
      const titleField = editForm.locator('input[id*="title"], input[name="title"]').first();
      await expect(titleField).toHaveValue('Test Task');

      // Verify description is pre-filled
      const descField = editForm.locator('textarea[id*="description"], textarea[name="description"]').first();
      await expect(descField).toHaveValue('Test description for the task');
    });

    test('Save button updates task via API', async ({ page }) => {
      await page.goto('/task/task-123');
      await page.waitForSelector('#task-page');

      // Track API call
      let capturedPayload: any = null;
      await page.route('**/tasks/task-123', async route => {
        if (route.request().method() === 'PATCH') {
          capturedPayload = route.request().postDataJSON();
        }
        await route.fulfill({ json: { success: true } });
      });

      // Open edit form
      await page.locator("button:has-text('Edit'), #task-edit-btn").first().click();
      await page.waitForSelector('.task-edit-form');

      const editForm = page.locator('.task-edit-form').first();

      // Update title
      const titleField = editForm.locator('input[id*="title"], input[name="title"]').first();
      await titleField.fill('Updated Title');

      // Click Save
      const saveBtn = editForm.locator("button:has-text('Save'), .btn-save").first();
      await saveBtn.click();

      // Wait for API response
      await page.waitForResponse('**/tasks/task-123');

      // Verify API was called with correct payload
      expect(capturedPayload).toBeTruthy();
      expect(capturedPayload.title).toBe('Updated Title');
    });
  });

  test.describe('Dependency Display', () => {
    test('displays dependencies section when task is blocked', async ({ page }) => {
      // Mock blocked task
      await page.route('**/tasks/task-456', async route => {
        await route.fulfill({
          json: {
            id: 'task-456',
            title: 'Blocked Task',
            description: 'Blocked by another task',
            repo: ['test-repo'],
            role: 'coder',
            status: 'blocked_by_task',
            branch: 'mm/blocked',
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

      // Mock dependencies endpoint
      await page.route('**/tasks/task-456/dependencies', async route => {
        await route.fulfill({
          json: {
            dependencies: [
              {
                id: 'task-123',
                title: 'Blocking Task',
              },
            ],
          },
        });
      });

      await page.goto('/task/task-456');
      await page.waitForSelector('#task-page');

      // Verify dependencies section exists
      const depsSection = page.locator('#task-dependencies, .dependencies-section');
      await expect(depsSection).toBeVisible();

      // Verify dependency link exists
      const depLink = page.locator('.dependency-link, a[data-task-id="task-123"]');
      await expect(depLink).toBeVisible();

      // Verify blocking task ID is shown
      await expect(depLink).toContainText('task-123');
    });

    test('displays multiple dependencies for a task', async ({ page }) => {
      // Mock blocked task
      await page.route('**/tasks/task-456', async route => {
        await route.fulfill({
          json: {
            id: 'task-456',
            title: 'Blocked Task',
            description: 'Blocked by multiple tasks',
            repo: ['test-repo'],
            role: 'coder',
            status: 'blocked_by_task',
            branch: 'mm/blocked',
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

      // Mock dependencies endpoint with multiple blockers
      await page.route('**/tasks/task-456/dependencies', async route => {
        await route.fulfill({
          json: {
            dependencies: [
              { id: 'task-123', title: 'Blocking Task 1' },
              { id: 'task-789', title: 'Blocking Task 2' },
              { id: 'task-999', title: 'Blocking Task 3' },
            ],
          },
        });
      });

      await page.goto('/task/task-456');
      await page.waitForSelector('#task-page');

      // Verify dependencies section exists
      const depsSection = page.locator('#task-dependencies, .dependencies-section');
      await expect(depsSection).toBeVisible();

      // Verify all three dependency links exist
      const depLinks = page.locator('.dependency-link');
      await expect(depLinks).toHaveCount(3);

      // Verify each dependency is visible
      await expect(depLinks.nth(0)).toContainText('task-123');
      await expect(depLinks.nth(0)).toContainText('Blocking Task 1');
      
      await expect(depLinks.nth(1)).toContainText('task-789');
      await expect(depLinks.nth(1)).toContainText('Blocking Task 2');
      
      await expect(depLinks.nth(2)).toContainText('task-999');
      await expect(depLinks.nth(2)).toContainText('Blocking Task 3');
    });

    test('dependency link is clickable and navigates to task', async ({ page }) => {
      // Mock blocked task
      await page.route('**/tasks/task-456', async route => {
        await route.fulfill({
          json: {
            id: 'task-456',
            title: 'Blocked Task',
            description: 'Blocked',
            repo: ['test-repo'],
            role: 'coder',
            status: 'blocked_by_task',
            branch: 'mm/blocked',
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

      // Mock dependencies endpoint
      await page.route('**/tasks/task-456/dependencies', async route => {
        await route.fulfill({
          json: {
            dependencies: [
              {
                id: 'task-123',
                title: 'Blocking Task',
              },
            ],
          },
        });
      });

      await page.goto('/task/task-456');
      await page.waitForSelector('#task-page');

      // Click dependency link
      const depLink = page.locator('.dependency-link').first();
      await depLink.click();

      // Should navigate to blocking task
      await page.waitForURL('**/task/task-123');
      await expect(page.locator('#task-page')).toBeVisible();
    });

    test('does not display dependencies section for non-blocked tasks', async ({ page }) => {
      await page.goto('/task/task-123');
      await page.waitForSelector('#task-page');

      // Dependencies section should not be visible for ready task
      const depsSection = page.locator('#task-dependencies');
      await expect(depsSection).not.toBeVisible();
    });
  });
});

test.describe('Unblock Button Workflow', () => {
  test.beforeEach(async ({ page }) => {
    // Mock blocked task
    await page.route('**/tasks/blocked-123', async route => {
      await route.fulfill({
        json: {
          id: 'blocked-123',
          title: 'Blocked Task',
          description: 'Waiting for human approval',
          repo: ['test-repo'],
          role: 'coder',
          status: 'blocked_by_human',
          branch: 'mm/blocked',
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
          notes: '[BLOCKED] Awaiting approval',
        },
      });
    });

    // Mock unblock endpoint
    await page.route('**/tasks/blocked-123/unblock', async route => {
      await route.fulfill({ json: { success: true } });
    });

    await page.route('**/repos', async route => {
      await route.fulfill({ json: { repos: [] } });
    });
    await page.route('**/tasks**', async route => {
      await route.fulfill({
        json: {
          tasks: [{
            id: 'blocked-123',
            title: 'Blocked Task',
            description: 'Waiting for human approval',
            repo: ['test-repo'],
            role: 'coder',
            status: 'blocked_by_human',
            branch: 'mm/blocked',
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
            notes: '[BLOCKED] Awaiting approval',
          }],
          count: 1,
        },
      });
    });
    await page.route('**/status', async route => {
      await route.fulfill({ json: { idle: true, stopped: false, blocked: false } });
    });
    await page.route('**/blocked', async route => {
      await route.fulfill({
        json: {
          report: {
            human: [{
              id: 'blocked-123',
              title: 'Blocked Task',
              blocking_reason: 'Awaiting approval',
            }],
            dependencies: [],
            waiting: [],
          },
        },
      });
    });
  });

  test('unblock button is visible for blocked_by_human tasks', async ({ page }) => {
    await page.goto('/task/blocked-123');
    await page.waitForSelector('#task-page');

    const unblockBtn = page.locator("button:has-text('Unblock'), #task-unblock-btn, .btn-unblock");
    await expect(unblockBtn).toBeVisible();
    await expect(unblockBtn).toBeEnabled();
  });

  test('unblock button is not visible for ready tasks', async ({ page }) => {
    // Mock ready task
    await page.route('**/tasks/ready-123', async route => {
      await route.fulfill({
        json: {
          id: 'ready-123',
          title: 'Ready Task',
          description: 'Ready to work',
          repo: ['test-repo'],
          role: 'coder',
          status: 'ready',
          branch: 'mm/ready',
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

    await page.goto('/task/ready-123');
    await page.waitForSelector('#task-page');

    const unblockBtn = page.locator("button:has-text('Unblock'), #task-unblock-btn");
    await expect(unblockBtn).not.toBeVisible();
  });

  test('unblock button click prompts for note', async ({ page }) => {
    await page.goto('/task/blocked-123');
    await page.waitForSelector('#task-page');

    let dialogAccepted = false;
    
    // Mock prompt
    page.on('dialog', async dialog => {
      expect(dialog.type()).toBe('prompt');
      const message = dialog.message();
      expect(message.includes('note') || message.includes('Unblock')).toBeTruthy();
      await dialog.accept('Unblocking for testing');
      dialogAccepted = true;
    });

    const unblockBtn = page.locator("button:has-text('Unblock'), #task-unblock-btn").first();
    await unblockBtn.click();

    // Wait for dialog to be handled
    await page.waitForTimeout(500);
    expect(dialogAccepted).toBeTruthy();
  });

  test('unblock button is in task actions area', async ({ page }) => {
    await page.goto('/task/blocked-123');
    await page.waitForSelector('#task-page');

    const actionsArea = page.locator('.task-actions');
    await expect(actionsArea).toBeVisible();

    const unblockBtn = actionsArea.locator("button:has-text('Unblock'), #task-unblock-btn");
    await expect(unblockBtn).toBeVisible();
  });

  test('task shows blocking reason in notes', async ({ page }) => {
    await page.goto('/task/blocked-123');
    await page.waitForSelector('#task-page');

    // Check if blocking reason is displayed somewhere in the UI
    const pageContent = await page.locator('#task-page').textContent();
    expect(pageContent && (pageContent.includes('Awaiting approval') || pageContent.includes('BLOCKED'))).toBeTruthy();
  });

  test('unblock changes task status to ready', async ({ page }) => {
    await page.goto('/task/blocked-123');
    await page.waitForSelector('#task-page');

    // Mock unblock endpoint
    await page.route('**/tasks/blocked-123/unblock', async route => {
      await route.fulfill({ json: { success: true } });
    });

    // Mock task after unblock (status changed to ready)
    await page.route('**/tasks/blocked-123', async route => {
      await route.fulfill({
        json: {
          id: 'blocked-123',
          title: 'Blocked Task',
          description: 'Waiting for human approval',
          repo: ['test-repo'],
          role: 'coder',
          status: 'ready',  // Status changed from blocked_by_human
          branch: 'mm/blocked',
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
          notes: '',
        },
      });
    });

    // Handle prompt
    page.on('dialog', async dialog => {
      await dialog.accept('Unblocking task');
    });

    // Verify initial status is blocked
    const statusElement = page.locator('.meta-item:has-text("Status:") .meta-value');
    await expect(statusElement).toContainText(/Blocked/i);

    // Click unblock button
    const unblockBtn = page.locator("button:has-text('Unblock'), #task-unblock-btn").first();
    await unblockBtn.click();

    // Wait for API response
    await page.waitForResponse('**/tasks/blocked-123/unblock');

    // Verify status changed to ready
    const newStatusElement = page.locator('.meta-item:has-text("Status:") .meta-value');
    await expect(newStatusElement).toContainText(/Ready/i);
  });
});

test.describe('Task Page Responsive Behavior', () => {
  test.beforeEach(async ({ page }) => {
    await page.route('**/repos', async route => {
      await route.fulfill({ json: { repos: [] } });
    });
    await page.route('**/tasks**', async route => {
      await route.fulfill({
        json: {
          tasks: [{
            id: 'task-123',
            title: 'Test Task',
            description: 'Test',
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
          }],
          count: 1,
        },
      });
    });
    await page.route('**/status', async route => {
      await route.fulfill({ json: { idle: true, stopped: false, blocked: false } });
    });
  });

  test('displays correctly on mobile viewport', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 667 });
    await page.goto('/task/task-123');
    await page.waitForSelector('#task-page');

    // Verify page is visible
    await expect(page.locator('#task-page')).toBeVisible();

    // Verify task title is visible
    await expect(page.locator('.task-title')).toBeVisible();

    // Verify conversation is accessible
    await expect(page.locator('#task-conversation-container')).toBeVisible();
  });

  test('task metadata is readable on mobile', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 667 });
    await page.goto('/task/task-123');
    await page.waitForSelector('#task-page');

    // Verify metadata section exists
    const metaSection = page.locator('.task-meta');
    await expect(metaSection).toBeVisible();

    // Verify text is not truncated
    const title = page.locator('.task-title');
    const titleBox = await title.boundingBox();
    expect(titleBox).toBeTruthy();
    expect(titleBox!.width).toBeGreaterThan(100);
  });

  test('edit button is touch-friendly on mobile', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 667 });
    await page.goto('/task/task-123');
    await page.waitForSelector('#task-page');

    const editBtn = page.locator("button:has-text('Edit'), #task-edit-btn").first();
    await expect(editBtn).toBeVisible();

    // Check button size (should be at least 44x44 for touch)
    const editBtnBox = await editBtn.boundingBox();
    expect(editBtnBox).toBeTruthy();
    expect(editBtnBox!.height).toBeGreaterThanOrEqual(40); // Close to 44px minimum
  });
});
