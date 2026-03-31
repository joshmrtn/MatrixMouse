/**
 * Visual Regression Tests
 * 
 * Captures and compares screenshots of all pages at different viewports.
 * Uses Playwright's built-in screenshot comparison.
 * 
 * Run with: npx playwright test --update-snapshots to update baselines
 */

import { test, expect } from '@playwright/test';

// Mock data for all pages
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
  {
    id: 'task003',
    title: 'Running task',
    description: 'Currently executing',
    repo: ['test-repo'],
    role: 'coder',
    status: 'running',
    branch: 'mm/feature',
    parent_task_id: null,
    depth: 0,
    importance: 0.9,
    urgency: 0.8,
    priority_score: 0.15,
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

const mockBlockedReport = {
  human: [
    { id: 'task002', title: 'Blocked task', blocking_reason: 'Awaiting review' },
  ],
  dependencies: [
    { id: 'task004', title: 'Waiting on dependency', blocking_reason: 'Waiting on: task002' },
  ],
  waiting: [
    { id: 'task005', title: 'Rate limited', blocking_reason: 'budget:api_limit' },
  ],
};

const mockConfig = {
  coder_model: 'ollama:qwen3.5:4b',
  manager_model: 'ollama:qwen3.5:9b',
  critic_model: 'ollama:qwen3.5:9b',
  writer_model: 'ollama:qwen3.5:4b',
  summarizer_model: 'ollama:qwen3.5:2b',
  agent_git_name: 'MatrixMouse Bot',
  agent_git_email: 'matrixmouse@example.com',
  server_port: 8080,
  log_level: 'INFO',
};

const mockContextMessages = [
  { role: 'system', content: 'You are MatrixMouse assistant.' },
  { role: 'user', content: 'Hello, can you help me with the project?' },
  { role: 'assistant', content: 'Of course! I\'d be happy to help. What would you like to work on?' },
  { role: 'user', content: 'I need to implement a new feature.' },
  { role: 'assistant', content: 'Great! Let me help you with that. Here\'s my plan:\n\n1. First, I\'ll analyze the requirements\n2. Then create a design\n3. Finally implement the feature\n\nShall I proceed?' },
];

// Setup common mocks
function setupCommonMocks(page: any) {
  page.route('**/repos', async route => {
    await route.fulfill({ status: 200, json: { repos: mockRepos } });
  });

  page.route('**/health', async route => {
    await route.fulfill({ status: 200, json: { status: 'ok' } });
  });

  page.route('**/status', async route => {
    await route.fulfill({ status: 200, json: { idle: true, stopped: false, blocked: false } });
  });
}

test.describe('Visual Regression - Desktop (1280x720)', () => {
  test.beforeEach(async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 720 });
    setupCommonMocks(page);
  });

  test('Status Page', async ({ page }) => {
    page.route('**/tasks**', async route => {
      await route.fulfill({ status: 200, json: { tasks: mockTasks, count: 3 } });
    });
    page.route('**/blocked', async route => {
      await route.fulfill({ status: 200, json: { report: mockBlockedReport } });
    });

    await page.goto('/status');
    await page.waitForSelector('#status-page');
    await expect(page).toHaveScreenshot('status-desktop.png', { fullPage: true });
  });

  test('Tasks Page - All Tasks', async ({ page }) => {
    page.route('**/tasks**', async route => {
      await route.fulfill({ status: 200, json: { tasks: mockTasks, count: 3 } });
    });

    await page.goto('/tasks');
    await page.waitForSelector('#tasks-page');
    await expect(page).toHaveScreenshot('tasks-all-desktop.png', { fullPage: true });
  });

  test('Tasks Page - Filtered', async ({ page }) => {
    page.route('**/tasks**', async route => {
      await route.fulfill({ status: 200, json: { tasks: mockTasks, count: 3 } });
    });

    await page.goto('/tasks');
    await page.waitForSelector('#tasks-page');
    
    // Apply filter
    await page.selectOption('#filter-status', 'blocked_by_human');
    await page.waitForTimeout(500);
    
    await expect(page).toHaveScreenshot('tasks-filtered-desktop.png', { fullPage: true });
  });

  test('Settings Page - Workspace', async ({ page }) => {
    page.route('**/config', async route => {
      if (route.request().method() === 'GET') {
        await route.fulfill({ status: 200, json: mockConfig });
      } else {
        await route.fulfill({ status: 200, json: { ok: true, updated: [] } });
      }
    });

    await page.goto('/settings');
    await page.waitForSelector('#settings-page');
    await expect(page).toHaveScreenshot('settings-workspace-desktop.png', { fullPage: true });
  });

  test('Channel Page - Conversation', async ({ page }) => {
    page.route('**/context**', async route => {
      await route.fulfill({
        status: 200,
        json: { messages: mockContextMessages, count: 5, estimated_tokens: 250 },
      });
    });
    page.route('**/pending', async route => {
      await route.fulfill({ status: 200, json: { pending: null } });
    });

    await page.goto('/channel/workspace');
    await page.waitForSelector('#channel-page');
    await expect(page).toHaveScreenshot('channel-conversation-desktop.png', { fullPage: true });
  });

  test('Channel Page - With Clarification', async ({ page }) => {
    page.route('**/context**', async route => {
      await route.fulfill({
        status: 200,
        json: { messages: mockContextMessages, count: 5, estimated_tokens: 250 },
      });
    });
    page.route('**/pending', async route => {
      await route.fulfill({ status: 200, json: { pending: 'What would you like me to do next?' } });
    });

    await page.goto('/channel/workspace');
    await page.waitForSelector('#clarification-banner');
    await expect(page).toHaveScreenshot('channel-clarification-desktop.png', { fullPage: true });
  });

  test('Task Page - Detail View', async ({ page }) => {
    page.route('**/tasks/task001', async route => {
      await route.fulfill({ status: 200, json: mockTasks[0] });
    });
    page.route('**/tasks/task001/dependencies', async route => {
      await route.fulfill({ status: 200, json: { task_id: 'task001', dependencies: [], count: 0 } });
    });
    page.route('**/context**', async route => {
      await route.fulfill({
        status: 200,
        json: { messages: mockContextMessages.slice(0, 3), count: 3, estimated_tokens: 150 },
      });
    });

    await page.goto('/task/task001');
    await page.waitForSelector('#task-page');
    await expect(page).toHaveScreenshot('task-detail-desktop.png', { fullPage: true });
  });

  test('Task Page - Edit Mode', async ({ page }) => {
    page.route('**/tasks/task001', async route => {
      await route.fulfill({ status: 200, json: mockTasks[0] });
    });
    page.route('**/tasks/task001/dependencies', async route => {
      await route.fulfill({ status: 200, json: { task_id: 'task001', dependencies: [], count: 0 } });
    });
    page.route('**/tasks/task001', async route => {
      if (route.request().method() === 'PATCH') {
        await route.fulfill({ status: 200, json: { ...mockTasks[0], title: 'Updated' } });
      }
    });

    await page.goto('/task/task001');
    await page.waitForSelector('#task-page');
    
    // Click edit
    await page.click('#task-edit-btn');
    await page.waitForSelector('.task-edit-form');
    await page.waitForTimeout(500);
    
    await expect(page).toHaveScreenshot('task-edit-desktop.png', { fullPage: true });
  });
});

test.describe('Visual Regression - Mobile (375x667)', () => {
  test.beforeEach(async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 667 });
    setupCommonMocks(page);
  });

  test('Status Page - Mobile', async ({ page }) => {
    page.route('**/tasks**', async route => {
      await route.fulfill({ status: 200, json: { tasks: mockTasks, count: 3 } });
    });
    page.route('**/blocked', async route => {
      await route.fulfill({ status: 200, json: { report: mockBlockedReport } });
    });

    await page.goto('/status');
    await page.waitForSelector('#status-page');
    await expect(page).toHaveScreenshot('status-mobile.png', { fullPage: true });
  });

  test('Tasks Page - Mobile', async ({ page }) => {
    page.route('**/tasks**', async route => {
      await route.fulfill({ status: 200, json: { tasks: mockTasks, count: 3 } });
    });

    await page.goto('/tasks');
    await page.waitForSelector('#tasks-page');
    await expect(page).toHaveScreenshot('tasks-mobile.png', { fullPage: true });
  });

  test('Settings Page - Mobile', async ({ page }) => {
    page.route('**/config', async route => {
      if (route.request().method() === 'GET') {
        await route.fulfill({ status: 200, json: mockConfig });
      } else {
        await route.fulfill({ status: 200, json: { ok: true, updated: [] } });
      }
    });

    await page.goto('/settings');
    await page.waitForSelector('#settings-page');
    await expect(page).toHaveScreenshot('settings-mobile.png', { fullPage: true });
  });

  test('Channel Page - Mobile', async ({ page }) => {
    page.route('**/context**', async route => {
      await route.fulfill({
        status: 200,
        json: { messages: mockContextMessages, count: 5, estimated_tokens: 250 },
      });
    });
    page.route('**/pending', async route => {
      await route.fulfill({ status: 200, json: { pending: null } });
    });

    await page.goto('/channel/workspace');
    await page.waitForSelector('#channel-page');
    await expect(page).toHaveScreenshot('channel-mobile.png', { fullPage: true });
  });

  test('Sidebar Open - Mobile', async ({ page }) => {
    page.route('**/tasks**', async route => {
      await route.fulfill({ status: 200, json: { tasks: mockTasks, count: 3 } });
    });

    await page.goto('/tasks');
    await page.waitForSelector('#hamburger-menu');
    
    // Open sidebar
    await page.click('#hamburger-menu');
    await page.waitForTimeout(300);
    
    await expect(page).toHaveScreenshot('sidebar-open-mobile.png', { fullPage: true });
  });
});

test.describe('Visual Regression - Tablet (768x1024)', () => {
  test.beforeEach(async ({ page }) => {
    await page.setViewportSize({ width: 768, height: 1024 });
    setupCommonMocks(page);
  });

  test('Status Page - Tablet', async ({ page }) => {
    page.route('**/tasks**', async route => {
      await route.fulfill({ status: 200, json: { tasks: mockTasks, count: 3 } });
    });
    page.route('**/blocked', async route => {
      await route.fulfill({ status: 200, json: { report: mockBlockedReport } });
    });

    await page.goto('/status');
    await page.waitForSelector('#status-page');
    await expect(page).toHaveScreenshot('status-tablet.png', { fullPage: true });
  });

  test('Tasks Page - Tablet', async ({ page }) => {
    page.route('**/tasks**', async route => {
      await route.fulfill({ status: 200, json: { tasks: mockTasks, count: 3 } });
    });

    await page.goto('/tasks');
    await page.waitForSelector('#tasks-page');
    await expect(page).toHaveScreenshot('tasks-tablet.png', { fullPage: true });
  });
});

test.describe('Visual Regression - Component States', () => {
  test.beforeEach(async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 720 });
    setupCommonMocks(page);
  });

  test('Empty State - Tasks', async ({ page }) => {
    page.route('**/tasks**', async route => {
      await route.fulfill({ status: 200, json: { tasks: [], count: 0 } });
    });

    await page.goto('/tasks');
    await page.waitForSelector('.empty-message');
    await expect(page).toHaveScreenshot('tasks-empty-state.png', { fullPage: true });
  });

  test('Loading State - Settings', async ({ page }) => {
    page.route('**/config', async route => {
      await new Promise(resolve => setTimeout(resolve, 2000));
      await route.fulfill({ status: 200, json: mockConfig });
    });

    await page.goto('/settings');
    // Capture during loading
    await page.waitForTimeout(500);
    await expect(page).toHaveScreenshot('settings-loading.png', { fullPage: true });
  });

  test('Error State - Failed API', async ({ page }) => {
    page.route('**/tasks**', async route => {
      await route.fulfill({ status: 500, json: { detail: 'Internal server error' } });
    });

    await page.goto('/tasks');
    await page.waitForSelector('#tasks-page');
    await expect(page).toHaveScreenshot('tasks-error-state.png', { fullPage: true });
  });

  test('Hover States - Task Items', async ({ page }) => {
    page.route('**/tasks**', async route => {
      await route.fulfill({ status: 200, json: { tasks: mockTasks, count: 3 } });
    });

    await page.goto('/tasks');
    await page.waitForSelector('.task-item');
    
    // Hover over first task
    const firstTask = page.locator('.task-item').first();
    await firstTask.hover();
    await page.waitForTimeout(300);
    
    await expect(page).toHaveScreenshot('task-item-hover.png', { fullPage: true });
  });

  test('Focus States - Form Inputs', async ({ page }) => {
    page.route('**/config', async route => {
      await route.fulfill({ status: 200, json: mockConfig });
    });

    await page.goto('/settings');
    await page.waitForSelector('input[name="coder_model"]');
    
    // Focus on input
    const input = page.locator('input[name="coder_model"]');
    await input.focus();
    await page.waitForTimeout(300);
    
    await expect(page).toHaveScreenshot('input-focus-state.png', { fullPage: true });
  });
});

test.describe('Visual Regression - Dark/Light Themes', () => {
  test.beforeEach(async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 720 });
    setupCommonMocks(page);
  });

  test('Tasks Page - Light Theme', async ({ page }) => {
    page.route('**/tasks**', async route => {
      await route.fulfill({ status: 200, json: { tasks: mockTasks, count: 3 } });
    });

    await page.goto('/tasks');
    await page.waitForSelector('#tasks-page');
    
    // Ensure light theme (default)
    await page.evaluate(() => {
      document.documentElement.style.setProperty('--bg1', '#ffffff');
      document.documentElement.style.setProperty('--text', '#000000');
    });
    
    await expect(page).toHaveScreenshot('tasks-light-theme.png', { fullPage: true });
  });
});
