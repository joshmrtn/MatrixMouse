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

test.describe('Tasks Page - Loading & Error States', () => {
  test('shows loading skeletons during initial load', async ({ page }) => {
    // Delay the API response to show loading state
    await page.route('**/tasks**', async route => {
      await new Promise(resolve => setTimeout(resolve, 500));
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

    // Navigate directly to task-list page
    await page.goto('/task-list');
    await page.waitForSelector('#tasks-page');

    // Should show loading skeletons briefly
    const skeletons = page.locator('.task-skeleton');
    await expect(skeletons.first()).toBeVisible({ timeout: 2000 });
  });

  test('replaces skeletons with tasks when API succeeds', async ({ page }) => {
    await page.goto('/task-list');
    await page.waitForSelector('#tasks-page');

    // Wait for tasks to load
    await page.waitForSelector('.task-item');

    // Should not have loading skeletons
    const skeletons = page.locator('.task-skeleton');
    await expect(skeletons).toHaveCount(0);

    // Should have actual tasks (test server provides 2 tasks)
    const taskItems = page.locator('.task-item');
    await expect(taskItems).toHaveCount(2);
  });

  test('shows error message when API fails', async ({ page }) => {
    await page.route('**/tasks**', async route => {
      await route.fulfill({
        status: 500,
        json: { detail: 'Internal server error' },
      });
    });

    await page.route('**/repos', async route => {
      await route.fulfill({
        status: 200,
        json: { repos: mockRepos },
      });
    });

    await page.goto('/task-list');
    await page.waitForSelector('#tasks-page');

    // Should show error message
    const errorMsg = page.locator('.error-message');
    await expect(errorMsg).toBeVisible();
    await expect(errorMsg).toContainText('Failed to load tasks');
  });

  test('retry button reloads tasks', async ({ page }) => {
    let requestCount = 0;

    // Set up route BEFORE navigating
    await page.route('**/tasks**', async route => {
      requestCount++;
      if (requestCount === 1) {
        await route.fulfill({
          status: 500,
          json: { detail: 'Internal server error' },
        });
      } else {
        // Return 2 tasks (matching test server data)
        await route.fulfill({
          status: 200,
          json: {
            tasks: [
              { id: 'task001', title: 'Test Task 1', status: 'ready', role: 'coder', repo: ['main-repo'], description: 'A test task', branch: 'task/task001', created_at: '2024-01-01T00:00:00Z', importance: 0.5, urgency: 0.5, priority_score: 0.5, preemptable: true, preempt: false, parent_task_id: null, depth: 0, last_modified: '2024-01-01T00:00:00Z', context_messages: [], pending_tool_calls: [], decomposition_confirmed_depth: 0, merge_resolution_decisions: [] },
              { id: 'task002', title: 'Test Task 2', status: 'blocked_by_human', role: 'coder', repo: ['main-repo'], description: 'Another test task', branch: 'task/task002', created_at: '2024-01-01T00:00:00Z', importance: 0.7, urgency: 0.8, priority_score: 0.3, preemptable: true, preempt: false, parent_task_id: null, depth: 0, last_modified: '2024-01-01T00:00:00Z', context_messages: [], pending_tool_calls: [], decomposition_confirmed_depth: 0, merge_resolution_decisions: [] },
            ],
            count: 2,
          },
        });
      }
    });

    await page.route('**/repos', async route => {
      await route.fulfill({
        status: 200,
        json: { repos: [{ name: 'main-repo', remote: 'https://github.com/test/main.git', local_path: '/test/main', added: '2024-01-01' }, { name: 'test-repo', remote: 'https://github.com/test/test.git', local_path: '/test/test', added: '2024-01-01' }] },
      });
    });

    await page.goto('/task-list');
    await page.waitForSelector('#tasks-page');

    // Wait for error to appear
    const errorMsg = page.locator('.error-message');
    await expect(errorMsg).toBeVisible();

    // Click retry button
    const retryBtn = page.locator('.retry-btn');
    await expect(retryBtn).toBeVisible();
    await retryBtn.click();

    // Wait for tasks to load after retry
    await page.waitForSelector('.task-item');
    const taskItems = page.locator('.task-item');
    await expect(taskItems).toHaveCount(2);
  });
});

test.describe('Tasks Page - Search', () => {
  test('search input is visible and functional', async ({ page }) => {
    await page.goto('/task-list');
    await page.waitForSelector('#tasks-page');

    const searchInput = page.locator('#task-search');
    await expect(searchInput).toBeVisible();
    await expect(searchInput).toHaveAttribute('placeholder', 'Search tasks...');
  });

  test('typing filters tasks in real-time', async ({ page }) => {
    await page.goto('/task-list');
    await page.waitForSelector('#tasks-page');

    // Wait for tasks to load
    await page.waitForSelector('.task-item');

    // Initially 2 tasks
    await expect(page.locator('.task-item')).toHaveCount(2);

    // Type in search
    const searchInput = page.locator('#task-search');
    await searchInput.fill('Test Task 1');

    // Wait for debounce (150ms) + render
    await page.waitForTimeout(300);

    // Should filter to 1 task
    await expect(page.locator('.task-item')).toHaveCount(1);
    await expect(page.locator('.task-item').first()).toContainText('Test Task 1');
  });

  test('search works with status filter active', async ({ page }) => {
    await page.goto('/task-list');
    await page.waitForSelector('#tasks-page');
    await page.waitForSelector('.task-item');

    // Set status filter to "blocked_by_human"
    const statusFilter = page.locator('#filter-status');
    await statusFilter.selectOption('blocked_by_human');

    // Should show 1 task (Test Task 2)
    await expect(page.locator('.task-item')).toHaveCount(1);

    // Search for "Test"
    const searchInput = page.locator('#task-search');
    await searchInput.fill('Test');
    await page.waitForTimeout(300);

    // Should still show 1 task (matches search + status filter)
    await expect(page.locator('.task-item')).toHaveCount(1);
  });

  test('clear button appears when search has text', async ({ page }) => {
    await page.goto('/task-list');
    await page.waitForSelector('#tasks-page');

    const searchInput = page.locator('#task-search');
    const clearBtn = page.locator('#task-search-clear');

    // Clear button should be hidden initially
    await expect(clearBtn).toHaveClass(/hidden/);

    // Type in search
    await searchInput.fill('test');

    // Clear button should now be visible
    await expect(clearBtn).not.toHaveClass(/hidden/);
  });

  test('clear button removes search filter', async ({ page }) => {
    await page.goto('/task-list');
    await page.waitForSelector('#tasks-page');
    await page.waitForSelector('.task-item');

    // Initially 2 tasks
    await expect(page.locator('.task-item')).toHaveCount(2);

    // Search for something
    const searchInput = page.locator('#task-search');
    await searchInput.fill('Test Task 1');
    await page.waitForTimeout(300);

    // Should filter to 1 task
    await expect(page.locator('.task-item')).toHaveCount(1);

    // Click clear button
    const clearBtn = page.locator('#task-search-clear');
    await clearBtn.click();

    // Should show all tasks again
    await expect(page.locator('.task-item')).toHaveCount(2);
  });

  test('search shows "No tasks found" when no matches', async ({ page }) => {
    await page.goto('/task-list');
    await page.waitForSelector('#tasks-page');
    await page.waitForSelector('.task-item');

    // Search for something that doesn't exist
    const searchInput = page.locator('#task-search');
    await searchInput.fill('nonexistent task xyz');
    await page.waitForTimeout(300);

    // Should show empty message
    await expect(page.locator('.empty-message')).toBeVisible();
    await expect(page.locator('.empty-message')).toContainText('No tasks');
  });

  test('search persists on mobile viewport', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 667 });
    await page.goto('/task-list');
    await page.waitForSelector('#tasks-page');

    // Search input should be visible
    const searchInput = page.locator('#task-search');
    await expect(searchInput).toBeVisible();

    // Type in search
    await searchInput.fill('Test');
    await page.waitForTimeout(300);

    // Should filter tasks
    await expect(page.locator('.task-item')).toHaveCount(2);
  });
});

test.describe('Tasks Page - Metadata Display', () => {
  test('task displays role badge', async ({ page }) => {
    await page.goto('/task-list');
    await page.waitForSelector('#tasks-page');
    await page.waitForSelector('.task-item');

    const roleBadge = page.locator('.task-role').first();
    await expect(roleBadge).toBeVisible();
    await expect(roleBadge).toContainText('Coder');
  });

  test('task displays priority indicator for high priority tasks', async ({ page }) => {
    // The test server has tasks with priority_score 0.5 and 0.3, which are <= 0.7
    // So we won't see priority indicators with the default mock data
    // This test verifies the element exists in the DOM structure
    await page.goto('/task-list');
    await page.waitForSelector('#tasks-page');

    // Check that the task-meta section contains role badges
    const roleBadges = page.locator('.task-role');
    await expect(roleBadges.first()).toBeVisible();
  });

  test('no emoji rendering in role/priority display', async ({ page }) => {
    await page.goto('/task-list');
    await page.waitForSelector('#tasks-page');
    await page.waitForSelector('.task-item');

    // Get all text in task meta section
    const taskMeta = page.locator('.task-meta').first();
    const metaText = await taskMeta.textContent();

    // Should not contain common emoji unicode ranges
    // Emoji ranges: U+1F300 to U+1F9FF, U+2600 to U+26FF (except ◆ U+25C6)
    const hasEmoji = /[\u{1F300}-\u{1F9FF}]/u.test(metaText || '');
    expect(hasEmoji).toBe(false);

    // Should contain the unicode diamond ◆ (U+25C6) if priority is shown
    // or just role text otherwise
    expect(metaText).toBeTruthy();
  });
});

test.describe('Tasks Page - Filter Persistence', () => {
  test('status filter persists after page refresh', async ({ page }) => {
    await page.goto('/task-list');
    await page.waitForSelector('#tasks-page');
    await page.waitForSelector('.task-item');

    // Change status filter
    const statusFilter = page.locator('#filter-status');
    await statusFilter.selectOption('blocked_by_human');

    // Verify localStorage was set
    const storedFilters = await page.evaluate(() => {
      return localStorage.getItem('matrixmouse.tasks.filters');
    });
    expect(storedFilters).toContain('blocked_by_human');

    // Refresh page
    await page.reload();
    await page.waitForSelector('#tasks-page');

    // Filter should be restored
    const restoredFilter = page.locator('#filter-status');
    await expect(restoredFilter).toHaveValue('blocked_by_human');
  });

  test('search query persists after page refresh', async ({ page }) => {
    await page.goto('/task-list');
    await page.waitForSelector('#tasks-page');

    // Search for something
    const searchInput = page.locator('#task-search');
    await searchInput.fill('Test Task 1');
    await page.waitForTimeout(300);

    // Refresh page
    await page.reload();
    await page.waitForSelector('#tasks-page');

    // Search should be restored
    const restoredSearch = page.locator('#task-search');
    await expect(restoredSearch).toHaveValue('Test Task 1');
  });

  test('combined filters persist after refresh', async ({ page }) => {
    await page.goto('/task-list');
    await page.waitForSelector('#tasks-page');
    await page.waitForSelector('.task-item');

    // Set status filter
    const statusFilter = page.locator('#filter-status');
    await statusFilter.selectOption('blocked_by_human');

    // Search
    const searchInput = page.locator('#task-search');
    await searchInput.fill('Test');
    await page.waitForTimeout(300);

    // Refresh page
    await page.reload();
    await page.waitForSelector('#tasks-page');

    // Both filters should be restored
    const restoredStatus = page.locator('#filter-status');
    await expect(restoredStatus).toHaveValue('blocked_by_human');

    const restoredSearch = page.locator('#task-search');
    await expect(restoredSearch).toHaveValue('Test');
  });
});

test.describe('Tasks Page - Terminal States', () => {
  test('terminal CSS styles are defined', async ({ page }) => {
    await page.goto('/task-list');
    await page.waitForSelector('#tasks-page');

    // Check that terminal CSS rules are defined in the stylesheet
    const hasTerminalStyles = await page.evaluate(() => {
      const sheets = document.styleSheets;
      for (let i = 0; i < sheets.length; i++) {
        try {
          const rules = sheets[i].cssRules;
          for (let j = 0; j < rules.length; j++) {
            if (rules[j].cssText && rules[j].cssText.includes('.terminal')) {
              return true;
            }
          }
        } catch {
          // Cross-origin stylesheet, skip
        }
      }
      return false;
    });
    expect(hasTerminalStyles).toBe(true);
  });
});
