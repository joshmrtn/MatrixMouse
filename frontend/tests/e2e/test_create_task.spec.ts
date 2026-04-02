/**
 * E2E Tests for Create Task Form
 *
 * Tests the complete task creation workflow from form submission to task display.
 */

import { test, expect } from '@playwright/test';

const mockTask = {
  id: 'e2e-test-123',
  title: 'E2E Test Task',
  description: 'Test description',
  repo: [],
  role: 'coder',
  status: 'ready',
  branch: 'mm/e2e-test-123',
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
};

const mockRepos = [
  { name: 'repo1', remote: 'https://github.com/test/repo1.git', local_path: '/test/repo1', added: '2024-01-01' },
  { name: 'repo2', remote: 'https://github.com/test/repo2.git', local_path: '/test/repo2', added: '2024-01-01' },
];

test.describe('Create Task - Desktop', () => {
  test.beforeEach(async ({ page }) => {
    // Mock API endpoints
    await page.route('**/repos', async route => {
      await route.fulfill({
        status: 200,
        json: { repos: mockRepos },
      });
    });

    await page.route('**/tasks', async route => {
      if (route.request().method() === 'GET') {
        await route.fulfill({
          status: 200,
          json: { tasks: [], count: 0 },
        });
      } else if (route.request().method() === 'POST') {
        await route.fulfill({
          status: 201,
          json: mockTask,
        });
      }
    });

    await page.route('**/tasks/e2e-test-123', async route => {
      await route.fulfill({
        status: 200,
        json: mockTask,
      });
    });

    await page.route('**/health', async route => {
      await route.fulfill({ status: 200, json: { status: 'ok' } });
    });
  });

  test('navigates to create task page from tasks list', async ({ page }) => {
    await page.goto('/task-list');

    // Click "+ New" button
    const newBtn = page.locator('#add-task-btn');
    await expect(newBtn).toBeVisible();
    await newBtn.click();

    // Should navigate to /task-new
    await expect(page).toHaveURL('/task-new');
  });

  test('displays create task form', async ({ page }) => {
    await page.goto('/task-new');

    // Check page header
    await expect(page.locator('h1')).toContainText('Create New Task');

    // Check form fields exist
    await expect(page.locator('#task-title')).toBeVisible();
    await expect(page.locator('#task-description')).toBeVisible();
    await expect(page.locator('#task-role')).toBeVisible();
    await expect(page.locator('#task-importance')).toBeVisible();
    await expect(page.locator('#task-urgency')).toBeVisible();
    await expect(page.locator('#task-target-files')).toBeVisible();
  });

  test('creates task with minimal fields (title only)', async ({ page }) => {
    await page.goto('/task-new');

    // Fill only title
    await page.fill('#task-title', 'Minimal Task');

    // Submit form
    await page.click('#btn-submit');

    // Should show success message
    await expect(page.locator('#create-task-message')).toContainText('Task created');
  });

  test('creates task with all fields', async ({ page }) => {
    await page.goto('/task-new');

    // Fill all fields
    await page.fill('#task-title', 'Complete Task');
    await page.fill('#task-description', 'This is a complete task description');
    await page.selectOption('#task-role', 'coder');
    await page.fill('#task-importance', '0.8');
    await page.fill('#task-urgency', '0.9');
    await page.fill('#task-target-files', 'src/file.py, tests/test.py');

    // Submit form
    await page.click('#btn-submit');

    // Should show success message
    await expect(page.locator('#create-task-message')).toContainText('Task created');
  });

  test('selects single repo', async ({ page }) => {
    await page.goto('/task-new');

    // Fill title
    await page.fill('#task-title', 'Single Repo Task');

    // Select repo
    await page.selectOption('#repo-select', 'repo1');

    // Repo should appear as tag
    await expect(page.locator('.repo-tag')).toContainText('repo1');

    // Submit
    await page.click('#btn-submit');
    await expect(page.locator('#create-task-message')).toContainText('Task created');
  });

  test('selects multiple repos and auto-switches to manager', async ({ page }) => {
    await page.goto('/task-new');

    // Fill title
    await page.fill('#task-title', 'Multi Repo Task');

    // Select first repo
    await page.selectOption('#repo-select', 'repo1');
    await expect(page.locator('.repo-tag').first()).toContainText('repo1');

    // Select second repo
    await page.selectOption('#repo-select', 'repo2');
    await expect(page.locator('.repo-tag').nth(1)).toContainText('repo2');

    // Role should auto-switch to manager
    const roleSelect = page.locator('#task-role');
    await expect(roleSelect).toHaveValue('manager');

    // Submit
    await page.click('#btn-submit');
    await expect(page.locator('#create-task-message')).toContainText('Task created');
  });

  test('removes selected repo', async ({ page }) => {
    await page.goto('/task-new');

    // Select repo
    await page.selectOption('#repo-select', 'repo1');
    await expect(page.locator('.repo-tag')).toContainText('repo1');

    // Remove repo by clicking X button
    await page.locator('.repo-tag button').click();

    // Repo tag should be gone
    await expect(page.locator('.repo-tag')).toHaveCount(0);
  });

  test('validates required title field', async ({ page }) => {
    await page.goto('/task-new');

    // Try to submit without title
    await page.click('#btn-submit');

    // Submit button should be disabled
    const submitBtn = page.locator('#btn-submit');
    await expect(submitBtn).toBeDisabled();
  });

  test('validates importance range (0-1)', async ({ page }) => {
    await page.goto('/task-new');

    await page.fill('#task-title', 'Test Task');
    await page.fill('#task-importance', '1.5');

    // Trigger validation
    await page.locator('#task-importance').blur();

    // Should show error
    await expect(page.locator('#importance-error')).toBeVisible();
    await expect(page.locator('#importance-error')).toContainText('Must be between 0 and 1');
  });

  test('validates urgency range (0-1)', async ({ page }) => {
    await page.goto('/task-new');

    await page.fill('#task-title', 'Test Task');
    await page.fill('#task-urgency', '-0.5');

    // Trigger validation
    await page.locator('#task-urgency').blur();

    // Should show error
    await expect(page.locator('#urgency-error')).toBeVisible();
    await expect(page.locator('#urgency-error')).toContainText('Must be between 0 and 1');
  });

  test('redirects to task detail after successful creation', async ({ page }) => {
    await page.goto('/task-new');

    await page.fill('#task-title', 'Redirect Test');
    await page.click('#btn-submit');

    // Wait for success message and redirect
    await expect(page.locator('#create-task-message')).toContainText('Task created');

    // Should redirect to task detail (wait for navigation)
    await page.waitForTimeout(1600);
    await expect(page).toHaveURL('/task/e2e-test-123');
  });

  test('cancels and returns to task list', async ({ page }) => {
    await page.goto('/task-new');

    // Fill some data
    await page.fill('#task-title', 'Cancelled Task');

    // Click cancel
    await page.click('#btn-cancel');

    // Should navigate back to task list
    await expect(page).toHaveURL('/task-list');
  });

  test('back button returns to task list', async ({ page }) => {
    await page.goto('/task-new');

    // Click back button
    await page.click('#back-btn');

    // Should navigate to task list
    await expect(page).toHaveURL('/task-list');
  });

  test('parses comma-separated target files', async ({ page }) => {
    await page.goto('/task-new');

    await page.fill('#task-title', 'Target Files Test');
    await page.fill('#task-target-files', 'file1.py, src/file2.ts, docs/readme.md');

    await page.click('#btn-submit');

    // Should succeed (API mock accepts the request)
    await expect(page.locator('#create-task-message')).toContainText('Task created');
  });
});

test.describe('Create Task - Mobile', () => {
  test.beforeEach(async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 667 });

    await page.route('**/repos', async route => {
      await route.fulfill({
        status: 200,
        json: { repos: mockRepos },
      });
    });

    await page.route('**/tasks', async route => {
      if (route.request().method() === 'GET') {
        await route.fulfill({
          status: 200,
          json: { tasks: [], count: 0 },
        });
      } else if (route.request().method() === 'POST') {
        await route.fulfill({
          status: 201,
          json: mockTask,
        });
      }
    });

    await page.route('**/health', async route => {
      await route.fulfill({ status: 200, json: { status: 'ok' } });
    });
  });

  test('displays correctly on mobile viewport', async ({ page }) => {
    await page.goto('/task-new');

    // Check page is visible
    await expect(page.locator('h1')).toBeVisible();

    // Check form fields are accessible
    await expect(page.locator('#task-title')).toBeVisible();
    await expect(page.locator('#btn-submit')).toBeVisible();
  });

  test('form fields are touch-friendly', async ({ page }) => {
    await page.goto('/task-new');

    // Check input fields have adequate height
    const titleInput = page.locator('#task-title');
    const boundingBox = await titleInput.boundingBox();

    expect(boundingBox).toBeTruthy();
    expect(boundingBox!.height).toBeGreaterThanOrEqual(40);
  });

  test('no horizontal scroll on mobile', async ({ page }) => {
    await page.goto('/task-new');

    const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
    const clientWidth = await page.evaluate(() => document.documentElement.clientWidth);

    expect(scrollWidth).toBeLessThanOrEqual(clientWidth);
  });

  test('submit button is accessible on mobile', async ({ page }) => {
    await page.goto('/task-new');

    await page.fill('#task-title', 'Mobile Task');

    const submitBtn = page.locator('#btn-submit');
    await expect(submitBtn).toBeEnabled();
    await submitBtn.click();

    await expect(page.locator('#create-task-message')).toContainText('Task created');
  });

  test('validation messages visible on mobile', async ({ page }) => {
    await page.goto('/task-new');

    await page.fill('#task-importance', '1.5');
    await page.locator('#task-importance').blur();

    await expect(page.locator('#importance-error')).toBeVisible();
  });

  test('success message visible on mobile', async ({ page }) => {
    await page.goto('/task-new');

    await page.fill('#task-title', 'Mobile Success');
    await page.click('#btn-submit');

    await expect(page.locator('#create-task-message')).toBeVisible();
    await expect(page.locator('#create-task-message')).toContainText('Task created');
  });

  test('navigation works on mobile', async ({ page }) => {
    await page.goto('/task-new');

    await page.click('#back-btn');

    await expect(page).toHaveURL('/task-list');
  });
});

test.describe('Create Task - Integration', () => {
  test.beforeEach(async ({ page }) => {
    await page.route('**/repos', async route => {
      await route.fulfill({
        status: 200,
        json: { repos: mockRepos },
      });
    });

    await page.route('**/tasks', async route => {
      if (route.request().method() === 'GET') {
        await route.fulfill({
          status: 200,
          json: {
            tasks: [
              {
                ...mockTask,
                id: 'existing-1',
                title: 'Existing Task 1',
              },
            ],
            count: 1,
          },
        });
      } else if (route.request().method() === 'POST') {
        await route.fulfill({
          status: 201,
          json: mockTask,
        });
      }
    });

    await page.route('**/tasks/*', async route => {
      await route.fulfill({
        status: 200,
        json: mockTask,
      });
    });

    await page.route('**/health', async route => {
      await route.fulfill({ status: 200, json: { status: 'ok' } });
    });
  });

  test('new task appears in task list after creation', async ({ page }) => {
    // Go to task list first
    await page.goto('/task-list');

    // Click new task button
    await page.click('#add-task-btn');
    await expect(page).toHaveURL('/task-new');

    // Create task
    await page.fill('#task-title', 'Integration Test Task');
    await page.click('#btn-submit');

    // Wait for redirect
    await page.waitForTimeout(1600);

    // Navigate back to task list
    await page.goto('/task-list');

    // New task should appear (from mock)
    await expect(page.locator('.task-item')).toContainText('E2E Test Task');
  });

  test('role hint updates when selecting multiple repos', async ({ page }) => {
    await page.goto('/task-new');

    // Initial hint
    const roleHint = page.locator('#role-hint');
    await expect(roleHint).toContainText('Manager role is auto-selected');

    // Select first repo
    await page.selectOption('#repo-select', 'repo1');
    await expect(roleHint).toContainText('Manager role is auto-selected');

    // Select second repo - should auto-switch
    await page.selectOption('#repo-select', 'repo2');
    await expect(roleHint).toContainText('Auto-switched to Manager');
    await expect(roleHint).toHaveCSS('font-weight', '600');
  });

  test('form state persists during validation', async ({ page }) => {
    await page.goto('/task-new');

    // Fill form
    await page.fill('#task-title', 'Persistence Test');
    await page.fill('#task-description', 'Testing form persistence');
    await page.fill('#task-importance', '0.7');

    // Trigger validation
    await page.fill('#task-importance', '1.5');
    await page.locator('#task-importance').blur();

    // Other fields should still have values
    await expect(page.locator('#task-title')).toHaveValue('Persistence Test');
    await expect(page.locator('#task-description')).toHaveValue('Testing form persistence');
  });

  test('submit button state changes correctly', async ({ page }) => {
    await page.goto('/task-new');

    const submitBtn = page.locator('#btn-submit');

    // Initially disabled (no title)
    await expect(submitBtn).toBeDisabled();

    // Enable with title
    await page.fill('#task-title', 'Test');
    await expect(submitBtn).toBeEnabled();

    // Click submit - should disable during submission
    await submitBtn.click();

    // Should show success (mock is instant)
    await expect(page.locator('#create-task-message')).toContainText('Task created');
  });

  test('error message displays on API failure', async ({ page }) => {
    await page.route('**/tasks', async route => {
      if (route.request().method() === 'POST') {
        await route.fulfill({
          status: 400,
          json: { detail: 'API error message' },
        });
      }
    });

    await page.goto('/task-new');

    await page.fill('#task-title', 'Error Test');
    await page.click('#btn-submit');

    // Should show error message
    await expect(page.locator('#create-task-message')).toBeVisible();
    await expect(page.locator('#create-task-message')).toHaveClass(/error/);
  });
});
