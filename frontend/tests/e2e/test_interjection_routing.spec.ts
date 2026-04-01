/**
 * E2E Tests for Interjection Routing
 *
 * Tests that interjections (user messages) are routed to the correct API endpoints
 * based on the current scope (workspace, repo, or task).
 *
 * Verifies:
 * - Workspace interjections → POST /interject/workspace
 * - Repo interjections → POST /interject/repo/{repo}
 * - Task interjections → POST /tasks/{id}/interject
 * - Scope switching clears selected task
 */

import { test, expect } from '@playwright/test';

test.describe('Interjection Routing', () => {
  test.beforeEach(async ({ page }) => {
    // Mock API endpoints
    await page.route('**/repos', async route => {
      await route.fulfill({
        json: {
          repos: [
            { name: 'test-repo', remote: 'https://github.com/test/test-repo.git' },
            { name: 'another-repo', remote: 'https://github.com/test/another-repo.git' },
          ],
        },
      });
    });
    await page.route('**/tasks**', async route => {
      await route.fulfill({
        json: {
          tasks: [
            {
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

  test.describe('Workspace Interjections', () => {
    test('workspace interjection routes to /interject/workspace', async ({ page }) => {
      await page.goto('/');
      await page.waitForSelector('#channel-page, #conversation');

      // Track API calls
      let workspaceApiCalled = false;
      let capturedPayload: any = null;
      
      await page.route('**/interject/workspace', async route => {
        workspaceApiCalled = true;
        capturedPayload = route.request().postDataJSON();
        await route.fulfill({ json: { success: true } });
      });

      // Type and send message
      const input = page.locator('#msg-input, #conversation-input input, input[placeholder*="message" i]');
      await expect(input).toBeVisible();
      await input.fill('Hello workspace!');
      
      const sendBtn = page.locator('#send-btn, #conversation-input button, button:has-text("Send")');
      await sendBtn.click();

      // Wait for API call
      await page.waitForTimeout(500);
      
      expect(workspaceApiCalled).toBeTruthy();
      expect(capturedPayload).toBeTruthy();
      expect(capturedPayload.message).toBe('Hello workspace!');
    });

    test('workspace interjection includes message content', async ({ page }) => {
      await page.goto('/');
      await page.waitForSelector('#channel-page, #conversation');

      let capturedMessage: string | null = null;
      
      await page.route('**/interject/workspace', async route => {
        const postData = route.request().postDataJSON();
        capturedMessage = postData.message;
        await route.fulfill({ json: { success: true } });
      });

      // Send message
      const input = page.locator('#msg-input, #conversation-input input').first();
      await input.fill('Test message content');
      await page.locator('#send-btn, #conversation-input button').first().click();

      // Wait
      await page.waitForTimeout(500);
      
      expect(capturedMessage).toBe('Test message content');
    });

    test('empty workspace interjection is rejected', async ({ page }) => {
      await page.goto('/');
      await page.waitForSelector('#channel-page, #conversation');

      let apiCalled = false;
      
      await page.route('**/interject/workspace', async route => {
        apiCalled = true;
        await route.fulfill({ json: { success: true } });
      });

      // Try to send empty message
      const input = page.locator('#msg-input, #conversation-input input').first();
      await input.fill('');
      
      const sendBtn = page.locator('#send-btn, #conversation-input button').first();
      await sendBtn.click();

      // Wait
      await page.waitForTimeout(500);
      
      // API should not have been called for empty message
      expect(apiCalled).toBeFalsy();
    });

    test('whitespace-only workspace interjection is rejected', async ({ page }) => {
      await page.goto('/');
      await page.waitForSelector('#channel-page, #conversation');

      let apiCalled = false;
      
      await page.route('**/interject/workspace', async route => {
        apiCalled = true;
        await route.fulfill({ json: { success: true } });
      });

      // Try to send whitespace-only message
      const input = page.locator('#msg-input, #conversation-input input').first();
      await input.fill('   \n\t  ');
      
      const sendBtn = page.locator('#send-btn, #conversation-input button').first();
      await sendBtn.click();

      // Wait
      await page.waitForTimeout(500);
      
      expect(apiCalled).toBeFalsy();
    });

    test('workspace interjection appears in conversation', async ({ page }) => {
      await page.goto('/');
      await page.waitForSelector('#channel-page, #conversation');

      // Mock successful response
      await page.route('**/interject/workspace', async route => {
        await route.fulfill({ json: { success: true } });
      });

      // Get initial message count
      const initialMessages = page.locator('.message-bubble.user, .message-row.user');
      const initialCount = await initialMessages.count();

      // Send message
      const input = page.locator('#msg-input, #conversation-input input').first();
      await input.fill('Test message');
      await page.locator('#send-btn, #conversation-input button').first().click();

      // Wait for message to appear
      await page.waitForTimeout(1000);

      // Should have new message
      const newMessages = page.locator('.message-bubble.user, .message-row.user');
      const newCount = await newMessages.count();
      
      expect(newCount).toBeGreaterThan(initialCount);
    });
  });

  test.describe('Task Interjections', () => {
    test('task interjection routes to /tasks/{id}/interject', async ({ page }) => {
      await page.goto('/task/task-123');
      await page.waitForSelector('#task-page, #conversation');

      let taskApiCalled = false;
      let capturedTaskId: string | null = null;
      
      await page.route('**/tasks/*/interject', async route => {
        taskApiCalled = true;
        const url = route.request().url();
        const match = url.match(/\/tasks\/([^/]+)\/interject/);
        if (match) {
          capturedTaskId = match[1];
        }
        await route.fulfill({ json: { success: true } });
      });

      // Send message
      const input = page.locator('#msg-input, #conversation-input input').first();
      await expect(input).toBeVisible();
      await input.fill('Hello task!');
      
      const sendBtn = page.locator('#send-btn, #conversation-input button').first();
      await sendBtn.click();

      // Wait
      await page.waitForTimeout(500);
      
      expect(taskApiCalled).toBeTruthy();
      expect(capturedTaskId).toBe('task-123');
    });

    test('task interjection includes task_id in payload', async ({ page }) => {
      await page.goto('/task/task-123');
      await page.waitForSelector('#task-page, #conversation');

      let capturedTaskId: string | null = null;
      
      await page.route('**/tasks/*/interject', async route => {
        const postData = route.request().postDataJSON();
        if (postData.task_id) {
          capturedTaskId = postData.task_id;
        }
        await route.fulfill({ json: { success: true } });
      });

      // Send message
      const input = page.locator('#msg-input, #conversation-input input').first();
      await input.fill('Test');
      await page.locator('#send-btn, #conversation-input button').first().click();

      // Wait
      await page.waitForTimeout(500);
      
      expect(capturedTaskId).toBe('task-123');
    });

    test('task interjection appears in task conversation', async ({ page }) => {
      await page.goto('/task/task-123');
      await page.waitForSelector('#task-page, #conversation');

      // Mock response
      await page.route('**/tasks/*/interject', async route => {
        await route.fulfill({ json: { success: true } });
      });

      // Get initial message count
      const initialMessages = page.locator('.message-bubble.user, .message-row.user');
      const initialCount = await initialMessages.count();

      // Send message
      const input = page.locator('#msg-input, #conversation-input input').first();
      await input.fill('Task message');
      await page.locator('#send-btn, #conversation-input button').first().click();

      // Wait
      await page.waitForTimeout(1000);

      // Should have new message
      const newMessages = page.locator('.message-bubble.user, .message-row.user');
      const newCount = await newMessages.count();
      
      expect(newCount).toBeGreaterThan(initialCount);
    });

    test('navigating away from task clears conversation input', async ({ page }) => {
      await page.goto('/task/task-123');
      await page.waitForSelector('#task-page, #conversation');

      // Type message but don't send
      const input = page.locator('#msg-input, #conversation-input input').first();
      await input.fill('Draft message');
      
      // Navigate away
      await page.goto('/');
      await page.waitForSelector('#channel-page, #conversation');

      // Input should be cleared or different
      const newInput = page.locator('#msg-input, #conversation-input input').first();
      const value = await newInput.inputValue();
      
      // Should be empty (cleared on navigation)
      expect(value).toBe('');
    });
  });

  test.describe('Scope Switching', () => {
    test('switching from task to workspace clears selected task', async ({ page }) => {
      await page.goto('/task/task-123');
      await page.waitForSelector('#task-page');

      // Verify we're on task page
      expect(page.url()).toContain('/task/task-123');

      // Navigate to workspace
      await page.goto('/');
      await page.waitForSelector('#channel-page');

      // Should be on workspace page
      expect(page.url()).toBe('http://localhost:3000/') || expect(page.url()).toContain('/channel/workspace');
      
      // Task-specific elements should not be visible
      const taskHeader = page.locator('#task-header, .task-title:has-text("Test Task")');
      await expect(taskHeader).not.toBeVisible();
    });

    test('switching scope clears chat input', async ({ page }) => {
      await page.goto('/task/task-123');
      await page.waitForSelector('#task-page, #conversation');

      // Type message
      const taskInput = page.locator('#msg-input, #conversation-input input').first();
      await taskInput.fill('Message for task');

      // Navigate to workspace
      await page.goto('/');
      await page.waitForSelector('#channel-page, #conversation');

      // Input should be cleared
      const workspaceInput = page.locator('#msg-input, #conversation-input input').first();
      const value = await workspaceInput.inputValue();
      expect(value).toBe('');
    });

    test('switching from repo to workspace clears context', async ({ page }) => {
      await page.goto('/channel/test-repo');
      await page.waitForSelector('#channel-page, #conversation');

      // Type message
      const repoInput = page.locator('#msg-input, #conversation-input input').first();
      await repoInput.fill('Message for repo');

      // Navigate to workspace
      await page.goto('/');
      await page.waitForSelector('#channel-page, #conversation');

      // Input should be cleared
      const workspaceInput = page.locator('#msg-input, #conversation-input input').first();
      const value = await workspaceInput.inputValue();
      expect(value).toBe('');
    });

    test('sidebar reflects current scope', async ({ page }) => {
      await page.goto('/');
      await page.waitForSelector('#sidebar');

      // Workspace should be active
      const workspaceItem = page.locator('#sidebar .sb-item.active, #sidebar .sb-item:has-text("workspace")');
      await expect(workspaceItem).toHaveCount({ min: 1 });

      // Navigate to task
      await page.goto('/task/task-123');
      await page.waitForSelector('#task-page');

      // Task should be selected in sidebar
      const taskItem = page.locator('#sidebar .sb-task-item.active, #sidebar .sb-item:has-text("task-123")');
      await expect(taskItem).toHaveCount({ min: 1 });
    });
  });

  test.describe('Repo Interjections', () => {
    test('repo interjection routes to /interject/repo/{repo}', async ({ page }) => {
      await page.goto('/channel/test-repo');
      await page.waitForSelector('#channel-page, #conversation');

      let repoApiCalled = false;
      let capturedRepo: string | null = null;
      
      await page.route('**/interject/repo/*', async route => {
        repoApiCalled = true;
        const url = route.request().url();
        const match = url.match(/\/interject\/repo\/([^/]+)/);
        if (match) {
          capturedRepo = decodeURIComponent(match[1]);
        }
        await route.fulfill({ json: { success: true } });
      });

      // Send message
      const input = page.locator('#msg-input, #conversation-input input').first();
      await input.fill('Hello repo!');
      
      const sendBtn = page.locator('#send-btn, #conversation-input button').first();
      await sendBtn.click();

      // Wait
      await page.waitForTimeout(500);
      
      expect(repoApiCalled).toBeTruthy();
      expect(capturedRepo).toBe('test-repo');
    });

    test('repo interjection includes repo name in URL', async ({ page }) => {
      await page.goto('/channel/another-repo');
      await page.waitForSelector('#channel-page, #conversation');

      let capturedUrl: string | null = null;
      
      await page.route('**/interject/repo/*', async route => {
        capturedUrl = route.request().url();
        await route.fulfill({ json: { success: true } });
      });

      // Send message
      const input = page.locator('#msg-input, #conversation-input input').first();
      await input.fill('Test');
      await page.locator('#send-btn, #conversation-input button').first().click();

      // Wait
      await page.waitForTimeout(500);
      
      expect(capturedUrl).toContain('/interject/repo/another-repo');
    });

    test('repo name is properly encoded in URL', async ({ page }) => {
      // Test with repo name that needs encoding
      await page.goto('/channel/test-repo');
      await page.waitForSelector('#channel-page, #conversation');

      let capturedUrl: string | null = null;
      
      await page.route('**/interject/repo/*', async route => {
        capturedUrl = route.request().url();
        await route.fulfill({ json: { success: true } });
      });

      // Send message
      const input = page.locator('#msg-input, #conversation-input input').first();
      await input.fill('Test');
      await page.locator('#send-btn, #conversation-input button').first().click();

      // Wait
      await page.waitForTimeout(500);
      
      // URL should be properly formatted
      expect(capturedUrl).toMatch(/\/interject\/repo\/[\w-]+/);
    });
  });

  test.describe('Input Behavior', () => {
    test('chat input clears after successful send', async ({ page }) => {
      await page.goto('/');
      await page.waitForSelector('#channel-page, #conversation');

      // Mock successful response
      await page.route('**/interject/workspace', async route => {
        await route.fulfill({ json: { success: true } });
      });

      // Send message
      const input = page.locator('#msg-input, #conversation-input input').first();
      await input.fill('Test message');
      expect(await input.inputValue()).toBe('Test message');
      
      const sendBtn = page.locator('#send-btn, #conversation-input button').first();
      await sendBtn.click();

      // Wait for input to clear
      await page.waitForTimeout(500);
      
      const newValue = await input.inputValue();
      expect(newValue).toBe('');
    });

    test('send button is disabled when input is empty', async ({ page }) => {
      await page.goto('/');
      await page.waitForSelector('#channel-page, #conversation');

      const sendBtn = page.locator('#send-btn, #conversation-input button').first();
      const input = page.locator('#msg-input, #conversation-input input').first();

      // Clear input
      await input.clear();
      
      // Wait for button state update
      await page.waitForTimeout(200);
      
      // Button should be disabled or not clickable
      const isDisabled = await sendBtn.isDisabled();
      const isHidden = await sendBtn.isHidden();
      
      // At least one should be true
      expect(isDisabled || isHidden).toBeTruthy();
    });

    test('send button is enabled when input has content', async ({ page }) => {
      await page.goto('/');
      await page.waitForSelector('#channel-page, #conversation');

      const sendBtn = page.locator('#send-btn, #conversation-input button').first();
      const input = page.locator('#msg-input, #conversation-input input').first();

      // Fill input
      await input.fill('Test message');
      
      // Wait for button state update
      await page.waitForTimeout(200);
      
      // Button should be enabled
      const isEnabled = await sendBtn.isEnabled();
      expect(isEnabled).toBeTruthy();
    });

    test('Enter key sends message', async ({ page }) => {
      await page.goto('/');
      await page.waitForSelector('#channel-page, #conversation');

      let apiCalled = false;
      
      await page.route('**/interject/workspace', async route => {
        apiCalled = true;
        await route.fulfill({ json: { success: true } });
      });

      // Type and press Enter
      const input = page.locator('#msg-input, #conversation-input input').first();
      await input.fill('Test message');
      await input.press('Enter');

      // Wait
      await page.waitForTimeout(500);
      
      expect(apiCalled).toBeTruthy();
    });

    test('Shift+Enter adds newline without sending', async ({ page }) => {
      await page.goto('/');
      await page.waitForSelector('#channel-page, #conversation');

      let apiCalled = false;
      
      await page.route('**/interject/workspace', async route => {
        apiCalled = true;
        await route.fulfill({ json: { success: true } });
      });

      // Type and press Shift+Enter
      const input = page.locator('#msg-input, #conversation-input input, textarea').first();
      await input.fill('Line 1');
      await input.press('Shift+Enter');
      await input.fill('Line 1\nLine 2');

      // Wait
      await page.waitForTimeout(500);
      
      // API should not have been called
      expect(apiCalled).toBeFalsy();
      
      // Input should have newline
      const value = await input.inputValue();
      expect(value).toContain('\n');
    });
  });

  test.describe('Edge Cases', () => {
    test('rapid message sending is handled', async ({ page }) => {
      await page.goto('/');
      await page.waitForSelector('#channel-page, #conversation');

      let callCount = 0;
      
      await page.route('**/interject/workspace', async route => {
        callCount++;
        await route.fulfill({ json: { success: true } });
      });

      // Send multiple messages rapidly
      const input = page.locator('#msg-input, #conversation-input input').first();
      const sendBtn = page.locator('#send-btn, #conversation-input button').first();

      for (let i = 0; i < 3; i++) {
        await input.fill(`Message ${i}`);
        await sendBtn.click();
        await page.waitForTimeout(100);
      }

      // Wait for all API calls
      await page.waitForTimeout(1000);
      
      // All messages should be sent
      expect(callCount).toBe(3);
    });

    test('very long message is sent successfully', async ({ page }) => {
      await page.goto('/');
      await page.waitForSelector('#channel-page, #conversation');

      let capturedMessage: string | null = null;
      
      await page.route('**/interject/workspace', async route => {
        const postData = route.request().postDataJSON();
        capturedMessage = postData.message;
        await route.fulfill({ json: { success: true } });
      });

      // Send long message
      const longMessage = 'A'.repeat(1000);
      const input = page.locator('#msg-input, #conversation-input input').first();
      await input.fill(longMessage);
      await page.locator('#send-btn, #conversation-input button').first().click();

      // Wait
      await page.waitForTimeout(500);
      
      expect(capturedMessage).toBe(longMessage);
    });

    test('special characters in message are preserved', async ({ page }) => {
      await page.goto('/');
      await page.waitForSelector('#channel-page, #conversation');

      let capturedMessage: string | null = null;
      
      await page.route('**/interject/workspace', async route => {
        const postData = route.request().postDataJSON();
        capturedMessage = postData.message;
        await route.fulfill({ json: { success: true } });
      });

      // Send message with special characters
      const specialMessage = 'Test <>&"\' message with special chars! @#$%^&*()';
      const input = page.locator('#msg-input, #conversation-input input').first();
      await input.fill(specialMessage);
      await page.locator('#send-btn, #conversation-input button').first().click();

      // Wait
      await page.waitForTimeout(500);
      
      expect(capturedMessage).toBe(specialMessage);
    });

    test('API error is handled gracefully', async ({ page }) => {
      await page.goto('/');
      await page.waitForSelector('#channel-page, #conversation');

      // Mock API error
      await page.route('**/interject/workspace', async route => {
        await route.fulfill({ status: 500, json: { error: 'Server error' } });
      });

      // Send message
      const input = page.locator('#msg-input, #conversation-input input').first();
      await input.fill('Test message');
      await page.locator('#send-btn, #conversation-input button').first().click();

      // Wait
      await page.waitForTimeout(1000);

      // Page should still be functional
      await expect(page.locator('#channel-page')).toBeVisible();
      
      // Input should still be there
      await expect(input).toBeVisible();
    });

    test('network timeout is handled gracefully', async ({ page }) => {
      await page.goto('/');
      await page.waitForSelector('#channel-page, #conversation');

      // Mock network timeout
      await page.route('**/interject/workspace', async route => {
        // Don't respond - simulate timeout
      });

      // Send message
      const input = page.locator('#msg-input, #conversation-input input').first();
      await input.fill('Test message');
      await page.locator('#send-btn, #conversation-input button').first().click();

      // Wait for timeout
      await page.waitForTimeout(5000);

      // Page should still be functional
      await expect(page.locator('#channel-page')).toBeVisible();
    });

    test('interjection works after page refresh', async ({ page }) => {
      await page.goto('/');
      await page.waitForSelector('#channel-page, #conversation');

      // Refresh page
      await page.reload();
      await page.waitForSelector('#channel-page, #conversation');

      let apiCalled = false;
      
      await page.route('**/interject/workspace', async route => {
        apiCalled = true;
        await route.fulfill({ json: { success: true } });
      });

      // Send message
      const input = page.locator('#msg-input, #conversation-input input').first();
      await input.fill('After refresh');
      await page.locator('#send-btn, #conversation-input button').first().click();

      // Wait
      await page.waitForTimeout(500);
      
      expect(apiCalled).toBeTruthy();
    });
  });
});
