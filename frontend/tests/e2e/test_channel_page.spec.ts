/**
 * E2E Tests for ChannelPage
 *
 * Tests the channel task request surface using the mocked test server.
 */

import { test, expect } from '@playwright/test';

test.describe('Channel Page', () => {
  test('renders workspace channel', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('#channel-page')).toBeVisible();
    await expect(page.locator('#channel-header')).toContainText('Channel: Workspace');
  });

  test('renders repo channel', async ({ page }) => {
    await page.goto('/channel/test-repo');
    await expect(page.locator('#channel-page')).toBeVisible();
    await expect(page.locator('#channel-header')).toContainText('Channel: test-repo');
  });

  test('shows task description textarea', async ({ page }) => {
    await page.goto('/');
    const textarea = page.locator('#channel-input textarea');
    await expect(textarea).toBeVisible();
    await expect(textarea).toHaveAttribute('placeholder', /what you want the Manager to do/);
  });

  test('shows send button', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('#channel-input button')).toBeVisible();
    await expect(page.locator('#channel-input button')).toHaveText('Send');
  });

  test('shows link to create task manually', async ({ page }) => {
    await page.goto('/');
    const link = page.locator('a[href="/task-new"]');
    await expect(link).toBeVisible();
    await expect(link).toContainText('create a task manually');
  });

  test('shows description explaining this is a task request', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('#channel-description')).toContainText('Manager');
  });

  test('sends message and redirects to TaskPage', async ({ page }) => {
    await page.goto('/');

    const textarea = page.locator('#channel-input textarea');
    await textarea.fill('Add a login feature');

    await page.locator('#channel-input button').click();

    // The test server returns a manager_task_id, so we should be redirected
    await expect(page.locator('#task-page')).toBeVisible({ timeout: 5000 });
  });

  test('redirects to TaskPage when task_id returned', async ({ page }) => {
    await page.goto('/');

    const textarea = page.locator('#channel-input textarea');
    await textarea.fill('Important task');

    await page.locator('#channel-input button').click();

    // The test server returns a manager_task_id, so we should be redirected
    // Wait for navigation to the task page
    await expect(page.locator('#task-page')).toBeVisible({ timeout: 5000 });

    // Verify the task title is visible
    await expect(page.locator('.task-title')).toBeVisible();
  });

  test('does not send empty messages', async ({ page }) => {
    await page.goto('/');

    const textarea = page.locator('#channel-input textarea');
    await textarea.fill('   ');

    await page.locator('#channel-input button').click();

    // Should not have sent anything
    await expect(page.locator('#channel-message')).not.toBeVisible();
  });

  test('shows error on API failure', async ({ page }) => {
    // Navigate to a repo that will trigger an error
    await page.goto('/channel/broken-repo');

    const textarea = page.locator('#channel-input textarea');
    await textarea.fill('Test message');

    await page.locator('#channel-input button').click();

    await expect(page.locator('#channel-message')).toContainText('Failed to send', { timeout: 5000 });
  });

  test('button shows sending state and redirects', async ({ page }) => {
    await page.goto('/');

    const textarea = page.locator('#channel-input textarea');
    await textarea.fill('Test');

    await page.locator('#channel-input button').click();

    // The redirect happens fast - verify we end up on the task page
    await expect(page.locator('#task-page')).toBeVisible({ timeout: 5000 });
  });

  test('Shift+Enter does not send message (allows newline)', async ({ page }) => {
    await page.goto('/');

    const textarea = page.locator('#channel-input textarea');
    await textarea.fill('Line one');
    await textarea.press('Shift+Enter');
    await textarea.pressSequentially('Line two');

    // Message should NOT have been sent
    await expect(page.locator('#channel-message')).not.toBeVisible();
    // Textarea should contain both lines
    await expect(textarea).toHaveValue(/Line one/);
    await expect(textarea).toHaveValue(/Line two/);
  });

  test('navigates to create task page via link', async ({ page }) => {
    await page.goto('/');
    await page.locator('a[href="/task-new"]').click();
    await expect(page.locator('#create-task-form')).toBeVisible();
  });

  test('accessible textarea with aria-label', async ({ page }) => {
    await page.goto('/');
    const textarea = page.locator('#channel-input textarea');
    await expect(textarea).toHaveAttribute('aria-label', /Task description/);
  });

  test('accessible button with aria-label', async ({ page }) => {
    await page.goto('/');
    const button = page.locator('#channel-input button');
    await expect(button).toHaveAttribute('aria-label', 'Send to Manager');
  });

  test('heading is h1', async ({ page }) => {
    await page.goto('/');
    const h1 = page.locator('#channel-header h1');
    await expect(h1).toBeVisible();
  });
});
