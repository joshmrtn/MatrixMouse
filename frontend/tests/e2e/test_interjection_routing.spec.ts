/**
 * E2E Tests for Interjection Routing
 *
 * Tests that interjections are routed to the correct API endpoints
 * based on scope. The ChannelPage E2E tests cover workspace/repo interjections
 * in detail; this file focuses on task-level interjections and edge cases.
 *
 * Verifies:
 * - Task interjections → POST /tasks/{id}/interject
 * - Very long messages
 * - Special characters
 * - API error handling
 */

import { test, expect } from '@playwright/test';

test.describe('Interjection Routing', () => {
  test.beforeEach(async ({ page }) => {
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
    await page.route('**/tasks/task-123', async route => {
      await route.fulfill({
        json: {
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
      });
    });
    await page.route('**/status', async route => {
      await route.fulfill({ json: { idle: true, stopped: false, blocked: false } });
    });
  });

  test.describe('Task Interjections', () => {
    test('task interjection routes to /tasks/{id}/interject', async ({ page }) => {
      await page.goto('/task/task-123');
      await page.waitForSelector('#task-page');

      let taskApiCalled = false;
      let capturedTaskId: string | null = null;

      await page.route('**/tasks/*/interject', async route => {
        taskApiCalled = true;
        const url = route.request().url();
        const match = url.match(/\/tasks\/([^/]+)\/interject/);
        if (match) capturedTaskId = match[1];
        await route.fulfill({ json: { ok: true } });
      });

      // The Conversation component has the input inside TaskPage
      const input = page.locator('#conversation-input input, #conversation-input textarea');
      await expect(input).toBeVisible();
      await input.fill('Hello task!');

      const sendBtn = page.locator('#conversation-input button');
      await sendBtn.click();

      await page.waitForTimeout(500);

      expect(taskApiCalled).toBeTruthy();
      expect(capturedTaskId).toBe('task-123');
    });

    test('task interjection includes message content', async ({ page }) => {
      await page.goto('/task/task-123');
      await page.waitForSelector('#task-page');

      let capturedMessage: string | null = null;

      await page.route('**/tasks/*/interject', async route => {
        const postData = route.request().postDataJSON();
        capturedMessage = postData.message;
        await route.fulfill({ json: { ok: true } });
      });

      const input = page.locator('#conversation-input input, #conversation-input textarea');
      await input.fill('Test message content');
      await page.locator('#conversation-input button').click();

      await page.waitForTimeout(500);

      expect(capturedMessage).toBe('Test message content');
    });

    test('empty task interjection is rejected', async ({ page }) => {
      await page.goto('/task/task-123');
      await page.waitForSelector('#task-page');

      let apiCalled = false;
      await page.route('**/tasks/*/interject', async route => {
        apiCalled = true;
        await route.fulfill({ json: { ok: true } });
      });

      const input = page.locator('#conversation-input input, #conversation-input textarea');
      await input.fill('');
      await page.locator('#conversation-input button').click();

      await page.waitForTimeout(500);
      expect(apiCalled).toBeFalsy();
    });
  });

  test.describe('Edge Cases', () => {
    test('very long message is sent successfully', async ({ page }) => {
      await page.goto('/');
      await page.waitForSelector('#channel-page');

      let capturedMessage: string | null = null;
      await page.route('**/interject/workspace', async route => {
        capturedMessage = route.request().postDataJSON().message;
        await route.fulfill({ json: { ok: true, manager_task_id: 'task001' } });
      });

      const longMessage = 'A'.repeat(1000);
      const input = page.locator('#channel-input textarea');
      await input.fill(longMessage);
      await page.locator('#channel-input button').click();

      await page.waitForTimeout(500);
      expect(capturedMessage).toBe(longMessage);
    });

    test('special characters in message are preserved', async ({ page }) => {
      await page.goto('/');
      await page.waitForSelector('#channel-page');

      let capturedMessage: string | null = null;
      await page.route('**/interject/workspace', async route => {
        capturedMessage = route.request().postDataJSON().message;
        await route.fulfill({ json: { ok: true, manager_task_id: 'task001' } });
      });

      const specialMessage = 'Test <>&"\' message with special chars! @#$%^&*()';
      const input = page.locator('#channel-input textarea');
      await input.fill(specialMessage);
      await page.locator('#channel-input button').click();

      await page.waitForTimeout(500);
      expect(capturedMessage).toBe(specialMessage);
    });

    test('API error is handled gracefully', async ({ page }) => {
      await page.goto('/');
      await page.waitForSelector('#channel-page');

      await page.route('**/interject/workspace', async route => {
        await route.fulfill({ status: 500, json: { detail: 'Server error' } });
      });

      const input = page.locator('#channel-input textarea');
      await input.fill('Test message');
      await page.locator('#channel-input button').click();

      await page.waitForTimeout(500);

      // Page should still be functional
      await expect(page.locator('#channel-page')).toBeVisible();
      await expect(input).toBeVisible();
    });

    test('interjection works after page refresh', async ({ page }) => {
      await page.goto('/');
      await page.waitForSelector('#channel-page');

      await page.reload();
      await page.waitForSelector('#channel-page');

      let apiCalled = false;
      await page.route('**/interject/workspace', async route => {
        apiCalled = true;
        await route.fulfill({ json: { ok: true, manager_task_id: 'task001' } });
      });

      const input = page.locator('#channel-input textarea');
      await input.fill('After refresh');
      await page.locator('#channel-input button').click();

      await page.waitForTimeout(500);
      expect(apiCalled).toBeTruthy();
    });
  });
});
