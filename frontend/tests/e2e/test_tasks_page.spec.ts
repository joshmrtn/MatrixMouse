/**
 * E2E Tests for Tasks Page
 * 
 * Tests the task list, filtering, sorting, and navigation.
 * Uses mock API server for deterministic testing.
 */

import { test, expect } from '@playwright/test';

// Mock API responses
const mockTasks = [
  {
    id: 'task001',
    title: 'High Priority Task',
    description: 'This is urgent',
    repo: ['main-repo'],
    role: 'coder',
    status: 'ready',
    branch: '',
    parent_task_id: null,
    depth: 0,
    importance: 0.9,
    urgency: 0.9,
    priority_score: 0.1,
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
    title: 'Running Task',
    description: 'Currently executing',
    repo: ['main-repo'],
    role: 'coder',
    status: 'running',
    branch: 'mm/feature',
    parent_task_id: null,
    depth: 0,
    importance: 0.7,
    urgency: 0.8,
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
    id: 'task003',
    title: 'Blocked by Human',
    description: 'Waiting for review',
    repo: ['test-repo'],
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
  {
    id: 'task004',
    title: 'Completed Task',
    description: 'Already done',
    repo: ['main-repo'],
    role: 'manager',
    status: 'complete',
    branch: 'mm/done',
    parent_task_id: null,
    depth: 0,
    importance: 0.8,
    urgency: 0.7,
    priority_score: 0.3,
    preemptable: false,
    preempt: false,
    created_at: '2024-01-01T00:00:00Z',
    completed_at: '2024-01-02T00:00:00Z',
    last_modified: '2024-01-02T00:00:00Z',
    context_messages: [],
    pending_tool_calls: [],
    decomposition_confirmed_depth: 0,
    merge_resolution_decisions: [],
  },
  {
    id: 'task005',
    title: 'Workspace Task',
    description: 'No repo assigned',
    repo: [],
    role: 'writer',
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
];

const mockRepos = [
  { name: 'main-repo', remote: 'https://github.com/test/main.git', local_path: '/test/main', added: '2024-01-01' },
  { name: 'test-repo', remote: 'https://github.com/test/test.git', local_path: '/test/test', added: '2024-01-01' },
];

test.describe('Tasks Page', () => {
  test.beforeEach(async ({ page }) => {
    // Setup mock API responses
    await page.route('**/tasks**', async route => {
      await route.fulfill({
        status: 200,
        json: { tasks: mockTasks, count: mockTasks.length },
      });
    });

    await page.route('**/repos', async route => {
      await route.fulfill({
        status: 200,
        json: { repos: mockRepos },
      });
    });

    await page.route('**/blocked', async route => {
      await route.fulfill({
        status: 200,
        json: { report: { human: [], dependencies: [], waiting: [] } },
      });
    });

    await page.route('**/status', async route => {
      await route.fulfill({
        status: 200,
        json: { idle: true, stopped: false, blocked: false },
      });
    });

    await page.route('**/health', async route => {
      await route.fulfill({ status: 200, json: { status: 'ok' } });
    });
  });

  test('loads tasks page successfully', async ({ page }) => {
    // Navigate to root first, then click Tasks tab
    await page.goto('/');
    await page.waitForSelector('#app');
    
    // Check viewport to determine if we need to open hamburger
    const viewport = page.viewportSize();
    const isMobile = viewport && viewport.width < 768;
    
    if (isMobile) {
      // Open hamburger menu on mobile
      await page.locator('#hamburger-menu').click();
      await page.waitForSelector('#sidebar.open');
    }
    
    // Click Tasks tab in sidebar
    await page.locator('[data-tab="tasks"]').click();
    
    // Wait for tasks page to load
    await page.waitForSelector('#tasks-page');
    
    // Check page header
    await expect(page.locator('h1')).toContainText('Tasks');
  });

  test('displays all tasks in list', async ({ page }) => {
    // Navigate from root to ensure app is initialized
    await page.goto('/');
    await page.waitForSelector('#app');
    
    // Check viewport to determine if we need to open hamburger
    const viewport = page.viewportSize();
    const isMobile = viewport && viewport.width < 768;
    
    if (isMobile) {
      // Open hamburger menu on mobile
      await page.locator('#hamburger-menu').click();
      await page.waitForSelector('#sidebar.open');
    }
    
    // Click Tasks tab
    await page.locator('[data-tab="tasks"]').click();
    
    // Wait for tasks to load
    await page.waitForSelector('.task-item');
    
    // Should show all 5 tasks
    const taskItems = page.locator('.task-item');
    await expect(taskItems).toHaveCount(5);
  });

  test('displays task title and ID', async ({ page }) => {
    await page.goto('/'); await page.waitForSelector('#app'); const viewport = page.viewportSize(); const isMobile = viewport && viewport.width < 768; if (isMobile) { await page.locator('#hamburger-menu').click(); await page.waitForSelector('#sidebar.open'); } await page.locator('[data-tab="tasks"]').click();
    
    const firstTask = page.locator('.task-item').first();
    
    // Check title is visible
    await expect(firstTask.locator('.task-title')).toBeVisible();
    
    // Check ID is visible (mono font)
    await expect(firstTask.locator('.task-id')).toBeVisible();
  });

  test('displays task status with correct styling', async ({ page }) => {
    await page.goto('/'); await page.waitForSelector('#app'); const viewport = page.viewportSize(); const isMobile = viewport && viewport.width < 768; if (isMobile) { await page.locator('#hamburger-menu').click(); await page.waitForSelector('#sidebar.open'); } await page.locator('[data-tab="tasks"]').click();
    
    // Find running task
    const runningTask = page.locator('.task-item:has-text("Running Task")');
    
    // Check status text
    await expect(runningTask.locator('.task-status')).toContainText('Running');
    
    // Check status class
    await expect(runningTask.locator('.task-status')).toHaveClass(/status-running/);
  });

  test('displays repo information', async ({ page }) => {
    await page.goto('/'); await page.waitForSelector('#app'); const viewport = page.viewportSize(); const isMobile = viewport && viewport.width < 768; if (isMobile) { await page.locator('#hamburger-menu').click(); await page.waitForSelector('#sidebar.open'); } await page.locator('[data-tab="tasks"]').click();
    
    // Task with repo
    const repoTask = page.locator('.task-item:has-text("High Priority Task")');
    await expect(repoTask.locator('.task-repo')).toContainText('main-repo');
    
    // Workspace task (no repo)
    const workspaceTask = page.locator('.task-item:has-text("Workspace Task")');
    await expect(workspaceTask.locator('.task-repo')).toContainText('Workspace');
  });

  test('clicking task navigates to task page', async ({ page }) => {
    await page.goto('/'); await page.waitForSelector('#app'); const viewport = page.viewportSize(); const isMobile = viewport && viewport.width < 768; if (isMobile) { await page.locator('#hamburger-menu').click(); await page.waitForSelector('#sidebar.open'); } await page.locator('[data-tab="tasks"]').click();
    
    // Click on first task
    const firstTaskLink = page.locator('.task-item').first().locator('a');
    await firstTaskLink.click();
    
    // Should navigate to task page
    await expect(page).toHaveURL(/\/task\/task\d+/);
  });

  test('filters tasks by status', async ({ page }) => {
    await page.goto('/'); await page.waitForSelector('#app'); const viewport = page.viewportSize(); const isMobile = viewport && viewport.width < 768; if (isMobile) { await page.locator('#hamburger-menu').click(); await page.waitForSelector('#sidebar.open'); } await page.locator('[data-tab="tasks"]').click();
    
    // Initially all tasks shown
    await expect(page.locator('.task-item')).toHaveCount(5);
    
    // Filter by "running"
    const statusFilter = page.locator('#filter-status');
    await statusFilter.selectOption('running');
    
    // Should only show running task
    await expect(page.locator('.task-item')).toHaveCount(1);
    await expect(page.locator('.task-item')).toContainText('Running Task');
  });

  test('filters tasks by repo', async ({ page }) => {
    await page.goto('/'); await page.waitForSelector('#app'); const viewport = page.viewportSize(); const isMobile = viewport && viewport.width < 768; if (isMobile) { await page.locator('#hamburger-menu').click(); await page.waitForSelector('#sidebar.open'); } await page.locator('[data-tab="tasks"]').click();
    
    // Filter by main-repo
    const repoFilter = page.locator('#filter-repo');
    await repoFilter.selectOption('main-repo');
    
    // Should show tasks in main-repo only (3 tasks)
    const taskItems = page.locator('.task-item');
    await expect(taskItems).toHaveCount(3);
    
    // Verify all shown tasks are from main-repo
    for (const item of await taskItems.all()) {
      await expect(item.locator('.task-repo')).toContainText('main-repo');
    }
  });

  test('clears filters when "All" selected', async ({ page }) => {
    await page.goto('/'); await page.waitForSelector('#app'); const viewport = page.viewportSize(); const isMobile = viewport && viewport.width < 768; if (isMobile) { await page.locator('#hamburger-menu').click(); await page.waitForSelector('#sidebar.open'); } await page.locator('[data-tab="tasks"]').click();
    
    // Apply filter
    const statusFilter = page.locator('#filter-status');
    await statusFilter.selectOption('complete');
    await expect(page.locator('.task-item')).toHaveCount(1);
    
    // Clear filter
    await statusFilter.selectOption('all');
    
    // Should show all tasks again
    await expect(page.locator('.task-item')).toHaveCount(5);
  });

  test('sorts tasks by priority (lower score = higher priority)', async ({ page }) => {
    await page.goto('/'); await page.waitForSelector('#app'); const viewport = page.viewportSize(); const isMobile = viewport && viewport.width < 768; if (isMobile) { await page.locator('#hamburger-menu').click(); await page.waitForSelector('#sidebar.open'); } await page.locator('[data-tab="tasks"]').click();
    
    // High priority task (score 0.1) should appear first
    const firstTask = page.locator('.task-item').first();
    await expect(firstTask.locator('.task-title')).toContainText('High Priority Task');
  });

  test('add new task button navigates to create form', async ({ page }) => {
    await page.goto('/'); await page.waitForSelector('#app'); const viewport = page.viewportSize(); const isMobile = viewport && viewport.width < 768; if (isMobile) { await page.locator('#hamburger-menu').click(); await page.waitForSelector('#sidebar.open'); } await page.locator('[data-tab="tasks"]').click();
    
    // Click add button
    const addButton = page.locator('#add-task-btn');
    await addButton.click();
    
    // Should navigate to new task page
    await expect(page).toHaveURL('/tasks/new');
  });

  test('shows empty state when no tasks', async ({ page }) => {
    // Override mock to return empty tasks
    await page.route('**/tasks**', async route => {
      await route.fulfill({
        status: 200,
        json: { tasks: [], count: 0 },
      });
    });

    await page.goto('/'); await page.waitForSelector('#app'); const viewport = page.viewportSize(); const isMobile = viewport && viewport.width < 768; if (isMobile) { await page.locator('#hamburger-menu').click(); await page.waitForSelector('#sidebar.open'); } await page.locator('[data-tab="tasks"]').click();
    
    // Should show empty message
    await expect(page.locator('.empty-message')).toBeVisible();
    await expect(page.locator('.empty-message')).toContainText(/no tasks/i);
  });

  test('status filter has all options', async ({ page }) => {
    await page.goto('/'); await page.waitForSelector('#app'); const viewport = page.viewportSize(); const isMobile = viewport && viewport.width < 768; if (isMobile) { await page.locator('#hamburger-menu').click(); await page.waitForSelector('#sidebar.open'); } await page.locator('[data-tab="tasks"]').click();
    
    const statusFilter = page.locator('#filter-status');
    const options = statusFilter.locator('option');
    
    // Check all status options exist
    await expect(options).toHaveCount(9); // All + 8 statuses
    
    const optionTexts = await options.allTextContents();
    expect(optionTexts).toContain('All');
    expect(optionTexts).toContain('Pending');
    expect(optionTexts).toContain('Ready');
    expect(optionTexts).toContain('Running');
    expect(optionTexts).toContain('Blocked by Human');
    expect(optionTexts).toContain('Blocked by Dependencies');
    expect(optionTexts).toContain('Waiting');
    expect(optionTexts).toContain('Complete');
    expect(optionTexts).toContain('Cancelled');
  });

  test('repo filter populated from repos', async ({ page }) => {
    await page.goto('/'); await page.waitForSelector('#app'); const viewport = page.viewportSize(); const isMobile = viewport && viewport.width < 768; if (isMobile) { await page.locator('#hamburger-menu').click(); await page.waitForSelector('#sidebar.open'); } await page.locator('[data-tab="tasks"]').click();
    
    const repoFilter = page.locator('#filter-repo');
    const options = repoFilter.locator('option');
    
    // Check repo options
    const optionTexts = await options.allTextContents();
    expect(optionTexts).toContain('All');
    expect(optionTexts).toContain('main-repo');
    expect(optionTexts).toContain('test-repo');
  });
});

test.describe('Tasks Page - Mobile', () => {
  test.beforeEach(async ({ page }) => {
    // Setup mock API responses
    await page.route('**/tasks**', async route => {
      await route.fulfill({
        status: 200,
        json: { tasks: mockTasks, count: mockTasks.length },
      });
    });

    await page.route('**/repos', async route => {
      await route.fulfill({
        status: 200,
        json: { repos: mockRepos },
      });
    });
  });

  test('displays correctly on mobile viewport', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 667 }); // iPhone SE
    await page.goto('/'); await page.waitForSelector('#app'); const viewport = page.viewportSize(); const isMobile = viewport && viewport.width < 768; if (isMobile) { await page.locator('#hamburger-menu').click(); await page.waitForSelector('#sidebar.open'); } await page.locator('[data-tab="tasks"]').click();
    
    // Check page is visible
    await expect(page.locator('h1')).toBeVisible();
    
    // Check tasks are visible
    await expect(page.locator('.task-item').first()).toBeVisible();
    
    // No horizontal scroll
    const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
    const clientWidth = await page.evaluate(() => document.documentElement.clientWidth);
    expect(scrollWidth).toBeLessThanOrEqual(clientWidth);
  });
});
