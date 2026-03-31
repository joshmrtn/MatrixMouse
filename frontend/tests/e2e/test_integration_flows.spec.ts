/**
 * Integration Tests for Critical User Flows
 * 
 * Tests complete user journeys across multiple pages.
 */

import { test, expect } from '@playwright/test';

const mockTasks = [
  {
    id: 'task001',
    title: 'Implement feature',
    description: 'Build the feature',
    repo: ['main-repo'],
    role: 'coder',
    status: 'ready',
    branch: '',
    parent_task_id: null,
    depth: 0,
    importance: 0.8,
    urgency: 0.7,
    priority_score: 0.25,
    preemptable: true,
    preempt: false,
    created_at: '2024-01-01T00:00:00Z',
    last_modified: '2024-01-01T00:00:00Z',
    context_messages: [],
    pending_tool_calls: [],
    decomposition_confirmed_depth: 0,
    merge_resolution_decisions: [],
  },
  {
    id: 'task002',
    title: 'Blocked task',
    description: 'Waiting for review',
    repo: ['main-repo'],
    role: 'critic',
    status: 'blocked_by_human',
    branch: '',
    parent_task_id: null,
    depth: 0,
    importance: 0.6,
    urgency: 0.5,
    priority_score: 0.45,
    preemptable: true,
    preempt: false,
    created_at: '2024-01-01T00:00:00Z',
    last_modified: '2024-01-01T00:00:00Z',
    context_messages: [],
    pending_tool_calls: [],
    decomposition_confirmed_depth: 0,
    merge_resolution_decisions: [],
    notes: '[BLOCKED] Awaiting review',
  },
];

const mockRepos = [
  { name: 'main-repo', remote: 'https://github.com/test/main.git', local_path: '/test/main', added: '2024-01-01' },
];

const mockBlockedReport = {
  human: [
    { id: 'task002', title: 'Blocked task', blocking_reason: 'Awaiting review' },
  ],
  dependencies: [],
  waiting: [],
};

test.describe('Critical User Flows', () => {
  test.beforeEach(async ({ page }) => {
    // Setup comprehensive mock API
    await page.route('**/tasks**', async route => {
      await route.fulfill({ status: 200, json: { tasks: mockTasks, count: 2 } });
    });

    await page.route('**/repos', async route => {
      await route.fulfill({ status: 200, json: { repos: mockRepos } });
    });

    await page.route('**/blocked', async route => {
      await route.fulfill({ status: 200, json: { report: mockBlockedReport } });
    });

    await page.route('**/status', async route => {
      await route.fulfill({ status: 200, json: { idle: true, stopped: false } });
    });

    await page.route('**/health', async route => {
      await route.fulfill({ status: 200, json: { status: 'ok' } });
    });

    await page.route('**/tasks/task001', async route => {
      await route.fulfill({ status: 200, json: mockTasks[0] });
    });

    await page.route('**/tasks/task002', async route => {
      await route.fulfill({ status: 200, json: mockTasks[1] });
    });

    await page.route('**/tasks/task001/dependencies', async route => {
      await route.fulfill({ status: 200, json: { task_id: 'task001', dependencies: [], count: 0 } });
    });

    await page.route('**/context**', async route => {
      await route.fulfill({
        status: 200,
        json: { messages: [], count: 0, estimated_tokens: 0 },
      });
    });

    await page.route('**/config', async route => {
      if (route.request().method() === 'GET') {
        await route.fulfill({
          status: 200,
          json: { coder_model: 'ollama:qwen3.5:4b', manager_model: 'ollama:qwen3.5:9b' },
        });
      } else {
        await route.fulfill({ status: 200, json: { ok: true, updated: ['coder_model'] } });
      }
    });
  });

  test('complete flow: Status → Tasks → Task Detail → Edit', async ({ page }) => {
    // Start at Status page
    await page.goto('/status');
    await expect(page).toHaveURL('/status');
    
    // Verify blocked task is shown
    await expect(page.locator('#status-blocked-human .task-link')).toHaveCount(1);
    
    // Click on blocked task
    await page.locator('#status-blocked-human .task-link').first().click();
    
    // Should navigate to task page
    await expect(page).toHaveURL('/task/task002');
    
    // Verify task details
    await expect(page.locator('.task-title')).toContainText('Blocked task');
    
    // Click EDIT button
    await page.locator('#task-edit-btn').click();
    
    // Edit form should appear
    await expect(page.locator('.task-edit-form')).toBeVisible();
    
    // Change title
    const titleInput = page.locator('#edit-title');
    await titleInput.fill('Updated blocked task');
    
    // Save
    await page.locator('.btn-save').click();
    
    // Title should update
    await expect(page.locator('.task-title')).toContainText('Updated blocked task');
  });

  test('complete flow: Tasks → Filter → Select → Navigate to Status', async ({ page }) => {
    // Start at Tasks page
    await page.goto('/tasks');
    await expect(page).toHaveURL('/tasks');
    
    // Filter by blocked
    const statusFilter = page.locator('#filter-status');
    await statusFilter.selectOption('blocked_by_human');
    
    // Should show only blocked task
    await expect(page.locator('.task-item')).toHaveCount(1);
    
    // Click on task
    await page.locator('.task-item').first().click();
    
    // Should navigate to task page
    await expect(page).toHaveURL('/task/task002');
    
    // Navigate to Status from sidebar
    await page.locator('[data-tab="status"]').click();
    
    // Should be on Status page
    await expect(page).toHaveURL('/status');
    
    // Blocked task should be shown
    await expect(page.locator('#status-blocked-human .task-link')).toHaveCount(1);
  });

  test('complete flow: Tasks → Settings → Change Config → Back to Tasks', async ({ page }) => {
    // Start at Tasks page
    await page.goto('/tasks');
    
    // Navigate to Settings
    await page.locator('[data-tab="settings"]').click();
    await expect(page).toHaveURL('/settings');
    
    // Change coder model
    const coderInput = page.locator('input[name="coder_model"]');
    await coderInput.fill('ollama:new-model:7b');
    
    // Save
    await page.locator('#workspace-config-form .btn-save').click();
    
    // Should show success message
    await expect(page.locator('#settings-message.success')).toBeVisible();
    
    // Navigate back to Tasks
    await page.locator('[data-tab="tasks"]').click();
    await expect(page).toHaveURL('/tasks');
    
    // Tasks should still be visible
    await expect(page.locator('.task-item')).toHaveCount(2);
  });

  test('complete flow: Sidebar navigation across all pages', async ({ page }) => {
    // Start at workspace channel
    await page.goto('/channel/workspace');
    
    // Navigate to Status
    await page.locator('[data-tab="status"]').click();
    await expect(page).toHaveURL('/status');
    
    // Navigate to Tasks
    await page.locator('[data-tab="tasks"]').click();
    await expect(page).toHaveURL('/tasks');
    
    // Navigate to Settings
    await page.locator('[data-tab="settings"]').click();
    await expect(page).toHaveURL('/settings');
    
    // Navigate to repo channel
    await page.locator('[data-repo="main-repo"]').click();
    await expect(page).toHaveURL('/channel/main-repo');
    
    // Navigate back to workspace
    await page.locator('[data-scope="workspace"]').click();
    await expect(page).toHaveURL('/channel/workspace');
  });

  test('complete flow: Create task → View in list → Edit → View in Status', async ({ page }) => {
    // Mock create endpoint
    await page.route('**/tasks', async route => {
      if (route.request().method() === 'POST') {
        await route.fulfill({
          status: 201,
          json: {
            ...mockTasks[0],
            id: 'new-task',
            title: 'New Task',
          },
        });
      } else {
        await route.fulfill({
          status: 200,
          json: { tasks: [...mockTasks, { ...mockTasks[0], id: 'new-task', title: 'New Task' }], count: 3 },
        });
      }
    });

    // Go to Tasks page
    await page.goto('/tasks');
    
    // Click New button
    await page.locator('#add-task-btn').click();
    await expect(page).toHaveURL('/tasks/new');
    
    // For now, just verify navigation - form implementation pending
    // In a real test, we would fill the form and submit
  });

  test('complete flow: Mobile navigation with hamburger menu', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 667 });
    
    // Start at Tasks
    await page.goto('/tasks');
    
    // Open hamburger menu
    await page.locator('#hamburger-menu').click();
    
    // Sidebar should be open
    await expect(page.locator('#sidebar')).toHaveClass(/open/);
    
    // Click Status tab
    await page.locator('[data-tab="status"]').click();
    
    // Should navigate and close sidebar
    await expect(page).toHaveURL('/status');
    await expect(page.locator('#sidebar')).not.toHaveClass(/open/);
    
    // Open menu again
    await page.locator('#hamburger-menu').click();
    
    // Click Settings
    await page.locator('[data-tab="settings"]').click();
    await expect(page).toHaveURL('/settings');
  });

  test('complete flow: Repo channel → Task → Back to repo', async ({ page }) => {
    // Start at repo channel
    await page.goto('/channel/main-repo');
    await expect(page).toHaveURL('/channel/main-repo');
    
    // Navigate to Tasks
    await page.locator('[data-tab="tasks"]').click();
    
    // Filter by repo
    const repoFilter = page.locator('#filter-repo');
    await repoFilter.selectOption('main-repo');
    
    // Click on task
    await page.locator('.task-item').first().click();
    
    // Should be on task page
    await expect(page).toHaveURL('/task/task001');
    
    // Navigate back to repo channel via sidebar
    await page.locator('[data-repo="main-repo"]').click();
    await expect(page).toHaveURL('/channel/main-repo');
  });
});

test.describe('Error Handling Flows', () => {
  test('handles API errors gracefully', async ({ page }) => {
    // Mock API error
    await page.route('**/tasks**', async route => {
      await route.fulfill({ status: 500, json: { detail: 'Internal server error' } });
    });

    await page.goto('/tasks');
    
    // Should show empty state or error message
    await expect(page.locator('.empty-message')).toBeVisible();
  });

  test('handles network errors gracefully', async ({ page }) => {
    // Mock network error
    await page.route('**/tasks**', async route => {
      await route.abort('failed');
    });

    await page.goto('/tasks');
    
    // Should not crash
    await expect(page.locator('#tasks-page')).toBeVisible();
  });
});
