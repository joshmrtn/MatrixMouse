/**
 * E2E Tests for Channel Page
 * 
 * Tests workspace/repo conversation view with interjections and clarification.
 */

import { test, expect } from '@playwright/test';

const mockContextMessages = [
  { role: 'system', content: 'You are MatrixMouse assistant.' },
  { role: 'user', content: 'Hello, can you help me with the project?' },
  { role: 'assistant', content: 'Of course! I\'d be happy to help. What would you like to work on?' },
];

const mockRepos = [
  { name: 'main-repo', remote: 'https://github.com/test/main.git', local_path: '/test/main', added: '2024-01-01' },
  { name: 'test-repo', remote: 'https://github.com/test/test.git', local_path: '/test/test', added: '2024-01-01' },
];

test.describe('Channel Page', () => {
  test.beforeEach(async ({ page }) => {
    // Setup mock API responses
    await page.route('**/context**', async route => {
      await route.fulfill({
        status: 200,
        json: {
          messages: mockContextMessages,
          count: mockContextMessages.length,
          estimated_tokens: 150,
        },
      });
    });

    await page.route('**/interject/**', async route => {
      if (route.request().method() === 'POST') {
        await route.fulfill({
          status: 200,
          json: { ok: true },
        });
      }
    });

    await page.route('**/repos', async route => {
      await route.fulfill({
        status: 200,
        json: { repos: mockRepos },
      });
    });

    await page.route('**/health', async route => {
      await route.fulfill({ status: 200, json: { status: 'ok' } });
    });
  });

  test('loads channel page successfully', async ({ page }) => {
    await page.goto('/channel/workspace');
    
    // Check page structure
    await expect(page.locator('#channel-page')).toBeVisible();
    await expect(page.locator('#channel-header')).toBeVisible();
  });

  test('displays channel name in header', async ({ page }) => {
    await page.goto('/channel/workspace');
    
    const header = page.locator('#channel-header');
    await expect(header).toContainText('Channel');
  });

  test('displays conversation messages', async ({ page }) => {
    await page.goto('/channel/workspace');
    
    // Wait for conversation to load
    await page.waitForSelector('.message-bubble');
    
    // Should show messages
    const messages = page.locator('.message-bubble');
    await expect(messages).toHaveCount(2); // user + assistant (not system)
  });

  test('displays user messages with correct styling', async ({ page }) => {
    await page.goto('/channel/workspace');
    
    const userMessage = page.locator('.message-bubble.user');
    await expect(userMessage).toBeVisible();
    await expect(userMessage).toContainText('Hello');
  });

  test('displays assistant messages with correct styling', async ({ page }) => {
    await page.goto('/channel/workspace');
    
    const assistantMessage = page.locator('.message-bubble.assistant');
    await expect(assistantMessage).toBeVisible();
    await expect(assistantMessage).toContainText('happy to help');
  });

  test('displays input field for interjections', async ({ page }) => {
    await page.goto('/channel/workspace');
    
    const input = page.locator('#channel-input input');
    await expect(input).toBeVisible();
    await expect(input).toHaveAttribute('placeholder', /message/i);
  });

  test('displays send button', async ({ page }) => {
    await page.goto('/channel/workspace');
    
    const sendButton = page.locator('#channel-input button');
    await expect(sendButton).toBeVisible();
    await expect(sendButton).toContainText(/send/i);
  });

  test('sends interjection when typing and pressing Enter', async ({ page }) => {
    await page.goto('/channel/workspace');
    
    const input = page.locator('#channel-input input');
    await input.fill('Test message');
    await input.press('Enter');
    
    // Should show message in conversation
    await expect(page.locator('.message-bubble.user')).toHaveCount(2);
  });

  test('sends interjection when clicking send button', async ({ page }) => {
    await page.goto('/channel/workspace');
    
    const input = page.locator('#channel-input input');
    await input.fill('Another test');
    
    const sendButton = page.locator('#channel-input button');
    await sendButton.click();
    
    // Should show message in conversation
    await expect(page.locator('.message-bubble.user')).toHaveCount(2);
  });

  test('clears input after sending message', async ({ page }) => {
    await page.goto('/channel/workspace');
    
    const input = page.locator('#channel-input input');
    await input.fill('Test message');
    await input.press('Enter');
    
    // Input should be cleared
    await expect(input).toHaveValue('');
  });

  test('does not send empty messages', async ({ page }) => {
    await page.goto('/channel/workspace');
    
    const input = page.locator('#channel-input input');
    await input.press('Enter');
    
    // Should still have only original messages
    const messages = page.locator('.message-bubble.user');
    await expect(messages).toHaveCount(1);
  });

  test('navigates to repo channel when clicking repo in sidebar', async ({ page }) => {
    await page.goto('/channel/workspace');
    
    // Click on repo in sidebar
    const repoItem = page.locator('[data-repo="main-repo"]');
    await repoItem.click();
    
    // Should navigate to repo channel
    await expect(page).toHaveURL('/channel/main-repo');
  });

  test('displays repo channel when navigating directly', async ({ page }) => {
    await page.goto('/channel/main-repo');
    
    const header = page.locator('#channel-header');
    await expect(header).toBeVisible();
  });
});

test.describe('Channel Page - Clarification', () => {
  const mockClarificationContext = [
    ...mockContextMessages,
    { role: 'assistant', content: 'I need clarification.' },
  ];

  test.beforeEach(async ({ page }) => {
    await page.route('**/context**', async route => {
      await route.fulfill({
        status: 200,
        json: {
          messages: mockClarificationContext,
          count: mockClarificationContext.length,
          estimated_tokens: 200,
        },
      });
    });

    await page.route('**/pending', async route => {
      await route.fulfill({
        status: 200,
        json: { pending: 'What would you like me to do?' },
      });
    });

    await page.route('**/interject**', async route => {
      await route.fulfill({ status: 200, json: { ok: true } });
    });

    await page.route('**/repos', async route => {
      await route.fulfill({ status: 200, json: { repos: mockRepos } });
    });
  });

  test('displays clarification banner when question pending', async ({ page }) => {
    await page.goto('/channel/workspace');
    
    // Should show clarification banner
    const banner = page.locator('#clarification-banner');
    await expect(banner).toBeVisible();
  });

  test('displays clarification question', async ({ page }) => {
    await page.goto('/channel/workspace');
    
    const question = page.locator('.clar-q');
    await expect(question).toContainText('What would you like me to do?');
  });

  test('has input field for clarification answer', async ({ page }) => {
    await page.goto('/channel/workspace');
    
    const input = page.locator('#clar-input');
    await expect(input).toBeVisible();
    await expect(input).toHaveAttribute('placeholder', /type your answer/i);
  });

  test('has answer button for clarification', async ({ page }) => {
    await page.goto('/channel/workspace');
    
    const button = page.locator('#clar-answer-btn');
    await expect(button).toBeVisible();
    await expect(button).toContainText('Answer');
  });

  test('sends clarification answer when pressing Enter', async ({ page }) => {
    await page.goto('/channel/workspace');
    
    const input = page.locator('#clar-input');
    await input.fill('Please continue');
    await input.press('Enter');
    
    // Banner should hide after sending
    const banner = page.locator('#clarification-banner');
    await expect(banner).not.toBeVisible();
  });

  test('sends clarification answer when clicking Answer button', async ({ page }) => {
    await page.goto('/channel/workspace');
    
    const input = page.locator('#clar-input');
    await input.fill('My answer');
    
    const button = page.locator('#clar-answer-btn');
    await button.click();
    
    // Banner should hide
    const banner = page.locator('#clarification-banner');
    await expect(banner).not.toBeVisible();
  });

  test('clears clarification input after sending', async ({ page }) => {
    await page.goto('/channel/workspace');
    
    const input = page.locator('#clar-input');
    await input.fill('Test answer');
    await input.press('Enter');
    
    await expect(input).toHaveValue('');
  });
});

test.describe('Channel Page - Mobile', () => {
  test.beforeEach(async ({ page }) => {
    await page.route('**/context**', async route => {
      await route.fulfill({
        status: 200,
        json: { messages: mockContextMessages, count: 3, estimated_tokens: 150 },
      });
    });

    await page.route('**/repos', async route => {
      await route.fulfill({ status: 200, json: { repos: mockRepos } });
    });
  });

  test('displays correctly on mobile viewport', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 667 });
    await page.goto('/channel/workspace');
    
    // Check conversation is visible
    await expect(page.locator('#conversation')).toBeVisible();
    
    // Check input is accessible
    await expect(page.locator('#channel-input input')).toBeVisible();
    
    // No horizontal scroll
    const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
    const clientWidth = await page.evaluate(() => document.documentElement.clientWidth);
    expect(scrollWidth).toBeLessThanOrEqual(clientWidth);
  });

  test('hamburger menu toggles sidebar on mobile', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 667 });
    await page.goto('/channel/workspace');
    
    // Click hamburger
    const hamburger = page.locator('#hamburger-menu');
    await hamburger.click();
    
    // Sidebar should open
    const sidebar = page.locator('#sidebar');
    await expect(sidebar).toHaveClass(/open/);
    
    // Click hamburger again to close
    await hamburger.click();
    await expect(sidebar).not.toHaveClass(/open/);
  });

  test('backdrop closes sidebar on mobile', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 667 });
    await page.goto('/channel/workspace');
    
    // Open sidebar
    const hamburger = page.locator('#hamburger-menu');
    await hamburger.click();
    
    // Click backdrop
    const backdrop = page.locator('#sidebar-backdrop');
    await backdrop.click();
    
    // Sidebar should close
    const sidebar = page.locator('#sidebar');
    await expect(sidebar).not.toHaveClass(/open/);
  });

  test('input fields are touch-friendly on mobile', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 667 });
    await page.goto('/channel/workspace');
    
    const input = page.locator('#channel-input input');
    const boundingBox = await input.boundingBox();
    
    expect(boundingBox).toBeTruthy();
    expect(boundingBox!.height).toBeGreaterThanOrEqual(40);
  });
});
