/**
 * E2E Tests for Channel Page
 *
 * Tests the channel/conversation page using Playwright.
 * Verifies workspace and repo interjections, conversation display,
 * and clarification question handling.
 */

import { test, expect } from '@playwright/test';

test.describe('Channel Page', () => {
  // Common mock data
  const mockContextResponse = {
    messages: [
      { role: 'user', content: 'Hello, can you help me?' },
      { role: 'assistant', content: 'Sure, I\'d be happy to help!' },
    ],
    count: 2,
    estimated_tokens: 20,
  };

  const mockEmptyContext = {
    messages: [],
    count: 0,
    estimated_tokens: 0,
  };

  test.beforeEach(async ({ page }) => {
    // Mock common API endpoints
    await page.route('**/repos', async route => {
      await route.fulfill({
        json: { repos: [{ name: 'test-repo', remote: 'https://github.com/test/test.git', local_path: '/test', added: '2024-01-01' }] },
      });
    });
    await page.route('**/tasks**', async route => {
      await route.fulfill({
        json: { tasks: [], count: 0 },
      });
    });
    await page.route('**/status', async route => {
      await route.fulfill({
        json: { idle: true, stopped: false, blocked: false },
      });
    });
    await page.route('**/blocked', async route => {
      await route.fulfill({
        json: { report: { human: [], dependencies: [], waiting: [] } },
      });
    });
    await page.route('**/pending', async route => {
      await route.fulfill({
        json: { pending: null },
      });
    });
  });

  test.describe('Navigation', () => {
    test('navigates to channel from sidebar', async ({ page }) => {
      await page.route('**/context', async route => {
        await route.fulfill({ json: mockContextResponse });
      });

      await page.goto('/');
      await page.waitForSelector('#channel-page');

      await expect(page.locator('#channel-page')).toBeVisible();
      expect(page.url()).toBe(`${page.url().split('/').slice(0, 3).join('/')}/`);
    });

    test('direct navigation to workspace channel works', async ({ page }) => {
      await page.route('**/context', async route => {
        await route.fulfill({ json: mockContextResponse });
      });

      await page.goto('/');
      await page.waitForSelector('#channel-page');

      await expect(page.locator('#channel-header')).toContainText('Channel: workspace');
    });

    test('direct navigation to repo channel works', async ({ page }) => {
      await page.route('**/context?repo=test-repo', async route => {
        await route.fulfill({ json: mockContextResponse });
      });

      await page.goto('/channel/test-repo');
      await page.waitForSelector('#channel-page');

      await expect(page.locator('#channel-header')).toContainText('Channel: test-repo');
    });

    test('sidebar highlights channel when active', async ({ page }) => {
      await page.route('**/context', async route => {
        await route.fulfill({ json: mockContextResponse });
      });

      await page.goto('/');
      await page.waitForSelector('#sidebar');

      const workspaceItem = page.locator('.sb-item').filter({ hasText: /workspace/i });
      await expect(workspaceItem).toHaveClass(/active/);
    });
  });

  test.describe('Conversation Display', () => {
    test('displays conversation header', async ({ page }) => {
      await page.route('**/context', async route => {
        await route.fulfill({ json: mockContextResponse });
      });

      await page.goto('/');
      await page.waitForSelector('#channel-header');

      await expect(page.locator('#channel-header')).toBeVisible();
      await expect(page.locator('#channel-header')).toContainText('Channel: workspace');
    });

    test('displays user messages', async ({ page }) => {
      await page.route('**/context', async route => {
        await route.fulfill({ json: mockContextResponse });
      });

      await page.goto('/');
      await page.waitForSelector('#conversation-log');

      const userMsg = page.locator('.message-bubble.user');
      await expect(userMsg).toBeVisible();
      await expect(userMsg).toContainText('Hello, can you help me?');
    });

    test('displays assistant messages', async ({ page }) => {
      await page.route('**/context', async route => {
        await route.fulfill({ json: mockContextResponse });
      });

      await page.goto('/');
      await page.waitForSelector('#conversation-log');

      const assistantMsg = page.locator('.message-bubble.assistant');
      await expect(assistantMsg).toBeVisible();
      await expect(assistantMsg).toContainText('Sure, I\'d be happy to help!');
    });

    test('displays message role labels', async ({ page }) => {
      await page.route('**/context', async route => {
        await route.fulfill({ json: mockContextResponse });
      });

      await page.goto('/');
      await page.waitForSelector('#conversation-log');

      const roleLabels = page.locator('.message-role');
      await expect(roleLabels.nth(0)).toHaveText('user');
      await expect(roleLabels.nth(1)).toHaveText('assistant');
    });

    test('shows empty state when no messages', async ({ page }) => {
      await page.route('**/context', async route => {
        await route.fulfill({ json: mockEmptyContext });
      });

      await page.goto('/');
      await page.waitForSelector('#conversation-log');

      await expect(page.locator('.empty-message')).toBeVisible();
      await expect(page.locator('.empty-message')).toContainText('No conversation yet');
    });

    test('displays loading state initially', async ({ page }) => {
      // Delay the response to test loading state
      await page.route('**/context', async route => {
        await new Promise(resolve => setTimeout(resolve, 500));
        await route.fulfill({ json: mockContextResponse });
      });

      await page.goto('/');
      
      // Should see loading state briefly
      await page.waitForTimeout(100);
      const loadingState = page.locator('.loading-state');
      await expect(loadingState).toBeVisible();
      
      // Wait for actual content
      await page.waitForSelector('.message-bubble');
    });

    test('displays error state on API failure', async ({ page }) => {
      await page.route('**/context', async route => {
        await route.abort('failed');
      });

      await page.goto('/');
      await page.waitForSelector('#conversation-log');

      await expect(page.locator('.error-message')).toBeVisible();
      await expect(page.locator('.error-message')).toContainText('Failed to load conversation');
    });

    test('retry button reloads conversation', async ({ page }) => {
      let failCount = 0;
      
      await page.route('**/context', async route => {
        if (failCount < 1) {
          failCount++;
          await route.abort('failed');
        } else {
          await route.fulfill({ json: mockContextResponse });
        }
      });

      await page.goto('/');
      await page.waitForSelector('.error-message');

      // Click retry
      await page.click('#retry-load');
      await page.waitForSelector('.message-bubble');

      const userMsg = page.locator('.message-bubble.user');
      await expect(userMsg).toBeVisible();
    });

    test('displays tool_call messages with preformatted text', async ({ page }) => {
      await page.route('**/context', async route => {
        await route.fulfill({
          json: {
            messages: [{ role: 'tool_call', content: 'read_file(path="test.py")' }],
            count: 1,
            estimated_tokens: 5,
          },
        });
      });

      await page.goto('/');
      await page.waitForSelector('#conversation-log');

      const toolMsg = page.locator('.message-bubble.tool');
      await expect(toolMsg).toBeVisible();
      await expect(toolMsg.locator('pre')).toBeVisible();
      await expect(toolMsg).toContainText('read_file(path="test.py")');
    });

    test('displays tool_result messages with preformatted text', async ({ page }) => {
      await page.route('**/context', async route => {
        await route.fulfill({
          json: {
            messages: [{ role: 'tool_result', content: 'File contents: print("hello")' }],
            count: 1,
            estimated_tokens: 5,
          },
        });
      });

      await page.goto('/');
      await page.waitForSelector('#conversation-log');

      const toolMsg = page.locator('.message-bubble.tool');
      await expect(toolMsg).toBeVisible();
      await expect(toolMsg).toContainText('File contents: print("hello")');
    });

    test('renders markdown in assistant messages', async ({ page }) => {
      await page.route('**/context', async route => {
        await route.fulfill({
          json: {
            messages: [
              { role: 'assistant', content: 'Here is the code:\n\n```python\nprint("hello")\n```' },
            ],
            count: 1,
            estimated_tokens: 15,
          },
        });
      });

      await page.goto('/');
      await page.waitForSelector('#conversation-log');

      const assistantMsg = page.locator('.message-bubble.assistant');
      await expect(assistantMsg).toBeVisible();
      await expect(assistantMsg.locator('pre')).toBeVisible();
      await expect(assistantMsg.locator('code')).toBeVisible();
    });

    test('escapes HTML in user messages for security', async ({ page }) => {
      await page.route('**/context', async route => {
        await route.fulfill({
          json: {
            messages: [{ role: 'user', content: '<script>alert("xss")</script>' }],
            count: 1,
            estimated_tokens: 5,
          },
        });
      });

      await page.goto('/');
      await page.waitForSelector('#conversation-log');

      const userMsg = page.locator('.message-bubble.user');
      await expect(userMsg).toBeVisible();
      // Should not contain actual script tags
      expect(await userMsg.innerHTML()).not.toContain('<script>');
    });
  });

  test.describe('Workspace Interjections', () => {
    test('displays input field and send button', async ({ page }) => {
      await page.route('**/context', async route => {
        await route.fulfill({ json: mockContextResponse });
      });

      await page.goto('/');
      await page.waitForSelector('#channel-input');

      await expect(page.locator('#channel-input input')).toBeVisible();
      await expect(page.locator('#channel-input button')).toBeVisible();
      await expect(page.locator('#channel-input button')).toHaveText('Send');
    });

    test('input placeholder shows workspace', async ({ page }) => {
      await page.route('**/context', async route => {
        await route.fulfill({ json: mockContextResponse });
      });

      await page.goto('/');
      await page.waitForSelector('#channel-input input');

      await expect(page.locator('#channel-input input')).toHaveAttribute('placeholder', 'Message workspace...');
    });

    test('sends interjection on button click', async ({ page }) => {
      let interjectionReceived = false;
      let interjectionMessage = '';

      await page.route('**/context', async route => {
        await route.fulfill({ json: mockContextResponse });
      });
      await page.route('**/interject/workspace', async route => {
        interjectionReceived = true;
        interjectionMessage = route.request().postDataJSON()?.message || '';
        await route.fulfill({ json: { ok: true, manager_task_id: 'task123' } });
      });

      await page.goto('/');
      await page.waitForSelector('#channel-input input');

      // Type message and click send
      await page.fill('#channel-input input', 'Test workspace message');
      await page.click('#channel-input button');
      await page.waitForTimeout(200);

      expect(interjectionReceived).toBe(true);
      expect(interjectionMessage).toBe('Test workspace message');
    });

    test('sends interjection on Enter key', async ({ page }) => {
      let interjectionReceived = false;

      await page.route('**/context', async route => {
        await route.fulfill({ json: mockContextResponse });
      });
      await page.route('**/interject/workspace', async route => {
        interjectionReceived = true;
        await route.fulfill({ json: { ok: true, manager_task_id: 'task123' } });
      });

      await page.goto('/');
      await page.waitForSelector('#channel-input input');

      // Type message and press Enter
      await page.fill('#channel-input input', 'Test Enter key');
      await page.press('#channel-input input', 'Enter');
      await page.waitForTimeout(200);

      expect(interjectionReceived).toBe(true);
    });

    test('clears input after sending message', async ({ page }) => {
      await page.route('**/context', async route => {
        await route.fulfill({ json: mockContextResponse });
      });
      await page.route('**/interject/workspace', async route => {
        await route.fulfill({ json: { ok: true, manager_task_id: 'task123' } });
      });

      await page.goto('/');
      await page.waitForSelector('#channel-input input');

      await page.fill('#channel-input input', 'Test message');
      await page.click('#channel-input button');
      await page.waitForTimeout(200);

      await expect(page.locator('#channel-input input')).toHaveValue('');
    });

    test('does not send empty message', async ({ page }) => {
      let interjectionReceived = false;

      await page.route('**/context', async route => {
        await route.fulfill({ json: mockContextResponse });
      });
      await page.route('**/interject/workspace', async route => {
        interjectionReceived = true;
        await route.fulfill({ json: { ok: true, manager_task_id: 'task123' } });
      });

      await page.goto('/');
      await page.waitForSelector('#channel-input input');

      // Try to send empty message
      await page.fill('#channel-input input', '   ');
      await page.click('#channel-input button');
      await page.waitForTimeout(200);

      expect(interjectionReceived).toBe(false);
    });

    test('adds user message optimistically', async ({ page }) => {
      await page.route('**/context', async route => {
        await route.fulfill({ json: { messages: [], count: 0, estimated_tokens: 0 } });
      });
      await page.route('**/interject/workspace', async route => {
        await new Promise(resolve => setTimeout(resolve, 500));
        await route.fulfill({ json: { ok: true, manager_task_id: 'task123' } });
      });

      await page.goto('/');
      await page.waitForSelector('#channel-input input');

      await page.fill('#channel-input input', 'Optimistic message');
      await page.click('#channel-input button');

      // Should see user message immediately (before API responds)
      await page.waitForTimeout(100);
      const userMsg = page.locator('.message-bubble.user');
      await expect(userMsg).toBeVisible();
      await expect(userMsg).toContainText('Optimistic message');
    });

    test('shows error message when interjection fails', async ({ page }) => {
      await page.route('**/context', async route => {
        await route.fulfill({ json: mockContextResponse });
      });
      await page.route('**/interject/workspace', async route => {
        await route.fulfill({ status: 500, json: { detail: 'API error' } });
      });

      await page.goto('/');
      await page.waitForSelector('#channel-input input');

      await page.fill('#channel-input input', 'Test message');
      await page.click('#channel-input button');
      await page.waitForTimeout(300);

      // Should show error message
      const errorMsg = page.locator('.message-bubble.system');
      await expect(errorMsg).toBeVisible();
      await expect(errorMsg).toContainText('Error');
    });
  });

  test.describe('Repo Interjections', () => {
    test('input placeholder shows repo name', async ({ page }) => {
      await page.route('**/context?repo=test-repo', async route => {
        await route.fulfill({ json: mockContextResponse });
      });

      await page.goto('/channel/test-repo');
      await page.waitForSelector('#channel-input input');

      await expect(page.locator('#channel-input input')).toHaveAttribute('placeholder', 'Message test-repo...');
    });

    test('sends to repo interjection endpoint', async ({ page }) => {
      let interjectionReceived = false;
      let interjectionRepo = '';
      let interjectionMessage = '';

      await page.route('**/context?repo=test-repo', async route => {
        await route.fulfill({ json: mockContextResponse });
      });
      await page.route('**/interject/repo/test-repo', async route => {
        interjectionReceived = true;
        interjectionRepo = route.request().url().split('/').pop() || '';
        interjectionMessage = route.request().postDataJSON()?.message || '';
        await route.fulfill({ json: { ok: true, manager_task_id: 'task456', repo: 'test-repo' } });
      });

      await page.goto('/channel/test-repo');
      await page.waitForSelector('#channel-input input');

      await page.fill('#channel-input input', 'Test repo message');
      await page.click('#channel-input button');
      await page.waitForTimeout(200);

      expect(interjectionReceived).toBe(true);
      expect(interjectionMessage).toBe('Test repo message');
    });

    test('encodes special characters in repo name', async ({ page }) => {
      await page.route('**/context?repo=my-special_repo', async route => {
        await route.fulfill({ json: mockContextResponse });
      });
      await page.route('**/interject/repo/my-special_repo', async route => {
        await route.fulfill({ json: { ok: true, manager_task_id: 'task789', repo: 'my-special_repo' } });
      });

      await page.goto('/channel/my-special_repo');
      await page.waitForSelector('#channel-input input');

      await page.fill('#channel-input input', 'Message');
      await page.click('#channel-input button');
      await page.waitForTimeout(200);

      // Should not error - URL encoding should work
      await expect(page.locator('#channel-input input')).toHaveValue('');
    });
  });

  test.describe('Clarification Questions', () => {
    test('shows clarification banner when question is pending', async ({ page }) => {
      await page.route('**/context', async route => {
        await route.fulfill({ json: mockContextResponse });
      });
      await page.route('**/pending', async route => {
        await route.fulfill({ json: { pending: 'What is the expected behavior?' } });
      });

      await page.goto('/');
      await page.waitForSelector('#clarification-banner');

      await expect(page.locator('#clarification-banner')).toBeVisible();
      await expect(page.locator('.clar-q')).toContainText('What is the expected behavior?');
    });

    test('hides clarification banner when no pending question', async ({ page }) => {
      await page.route('**/context', async route => {
        await route.fulfill({ json: mockContextResponse });
      });
      await page.route('**/pending', async route => {
        await route.fulfill({ json: { pending: null } });
      });

      await page.goto('/');
      await page.waitForSelector('#channel-page');

      const banner = page.locator('#clarification-banner');
      await expect(banner).not.toBeVisible();
    });

    test('clarification input is focused when banner appears', async ({ page }) => {
      await page.route('**/context', async route => {
        await route.fulfill({ json: mockContextResponse });
      });
      await page.route('**/pending', async route => {
        await route.fulfill({ json: { pending: 'Please clarify' } });
      });

      await page.goto('/');
      await page.waitForSelector('#clarification-banner');

      const clarInput = page.locator('#clar-input');
      await expect(clarInput).toBeFocused();
    });

    test('sends answer on clarification button click', async ({ page }) => {
      let answerSent = false;
      let answerMessage = '';

      await page.route('**/context', async route => {
        await route.fulfill({ json: mockContextResponse });
      });
      await page.route('**/pending', async route => {
        await route.fulfill({ json: { pending: 'What do you want?' } });
      });
      await page.route('**/interject/workspace', async route => {
        answerSent = true;
        answerMessage = route.request().postDataJSON()?.message || '';
        await route.fulfill({ json: { ok: true, manager_task_id: 'task123' } });
      });

      await page.goto('/');
      await page.waitForSelector('#clarification-banner');

      await page.fill('#clar-input', 'My answer');
      await page.click('#clar-answer-btn');
      await page.waitForTimeout(200);

      expect(answerSent).toBe(true);
      expect(answerMessage).toBe('My answer');
    });

    test('sends answer on Enter key', async ({ page }) => {
      let answerSent = false;

      await page.route('**/context', async route => {
        await route.fulfill({ json: mockContextResponse });
      });
      await page.route('**/pending', async route => {
        await route.fulfill({ json: { pending: 'What do you want?' } });
      });
      await page.route('**/interject/workspace', async route => {
        answerSent = true;
        await route.fulfill({ json: { ok: true, manager_task_id: 'task123' } });
      });

      await page.goto('/');
      await page.waitForSelector('#clarification-banner');

      await page.fill('#clar-input', 'My Enter answer');
      await page.press('#clar-input', 'Enter');
      await page.waitForTimeout(200);

      expect(answerSent).toBe(true);
    });

    test('hides banner after answering', async ({ page }) => {
      await page.route('**/context', async route => {
        await route.fulfill({ json: mockContextResponse });
      });
      await page.route('**/pending', async route => {
        await route.fulfill({ json: { pending: 'Question' } });
      });
      await page.route('**/interject/workspace', async route => {
        await route.fulfill({ json: { ok: true, manager_task_id: 'task123' } });
      });

      await page.goto('/');
      await page.waitForSelector('#clarification-banner');

      await page.fill('#clar-input', 'Answer');
      await page.click('#clar-answer-btn');
      await page.waitForTimeout(200);

      await expect(page.locator('#clarification-banner')).not.toBeVisible();
    });

    test('does not send empty clarification answer', async ({ page }) => {
      let answerSent = false;

      await page.route('**/context', async route => {
        await route.fulfill({ json: mockContextResponse });
      });
      await page.route('**/pending', async route => {
        await route.fulfill({ json: { pending: 'Question' } });
      });
      await page.route('**/interject/workspace', async route => {
        answerSent = true;
        await route.fulfill({ json: { ok: true, manager_task_id: 'task123' } });
      });

      await page.goto('/');
      await page.waitForSelector('#clarification-banner');

      await page.fill('#clar-input', '   ');
      await page.click('#clar-answer-btn');
      await page.waitForTimeout(200);

      expect(answerSent).toBe(false);
    });

    test('adds answer as user message', async ({ page }) => {
      await page.route('**/context', async route => {
        await route.fulfill({ json: { messages: [], count: 0, estimated_tokens: 0 } });
      });
      await page.route('**/pending', async route => {
        await route.fulfill({ json: { pending: 'Question' } });
      });
      await page.route('**/interject/workspace', async route => {
        await route.fulfill({ json: { ok: true, manager_task_id: 'task123' } });
      });

      await page.goto('/');
      await page.waitForSelector('#clarification-banner');

      await page.fill('#clar-input', 'My clarification answer');
      await page.click('#clar-answer-btn');
      await page.waitForTimeout(200);

      const userMsg = page.locator('.message-bubble.user');
      await expect(userMsg).toBeVisible();
      await expect(userMsg).toContainText('My clarification answer');
    });
  });

  test.describe('Responsive Behavior', () => {
    test('works on mobile viewport', async ({ page }) => {
      await page.route('**/context', async route => {
        await route.fulfill({ json: mockContextResponse });
      });

      await page.setViewportSize({ width: 375, height: 667 });
      await page.goto('/');
      await page.waitForSelector('#channel-page');

      await expect(page.locator('#channel-page')).toBeVisible();
      await expect(page.locator('#channel-input input')).toBeVisible();
      await expect(page.locator('#channel-input button')).toBeVisible();
    });

    test('input is touch-friendly on mobile', async ({ page }) => {
      await page.route('**/context', async route => {
        await route.fulfill({ json: mockContextResponse });
      });

      await page.setViewportSize({ width: 375, height: 667 });
      await page.goto('/');
      await page.waitForSelector('#channel-input input');

      const input = page.locator('#channel-input input');
      const box = await input.boundingBox();
      expect(box).toBeTruthy();
      expect(box!.height).toBeGreaterThanOrEqual(44); // Touch-friendly height
    });
  });
});
