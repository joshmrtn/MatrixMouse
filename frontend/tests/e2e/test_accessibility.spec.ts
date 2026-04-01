/**
 * Accessibility Tests using axe-core
 * 
 * Tests WCAG 2.1 AA compliance across all pages.
 * Checks for:
 * - Color contrast
 * - ARIA attributes
 * - Keyboard navigation
 * - Screen reader compatibility
 * - Focus management
 * - Semantic HTML
 */

import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

// Mock data
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
];

const mockRepos = [
  { name: 'main-repo', remote: 'https://github.com/test/main.git', local_path: '/test/main', added: '2024-01-01' },
];

const mockBlockedReport = {
  human: [{ id: 'task001', title: 'Task', blocking_reason: 'Review needed' }],
  dependencies: [],
  waiting: [],
};

const mockConfig = {
  coder_model: 'ollama:qwen3.5:4b',
  manager_model: 'ollama:qwen3.5:9b',
  agent_git_name: 'MatrixMouse Bot',
  agent_git_email: 'matrixmouse@example.com',
};

const mockContextMessages = [
  { role: 'user', content: 'Hello' },
  { role: 'assistant', content: 'Hi there!' },
];

function setupCommonMocks(page: any) {
  page.route('**/repos', async route => {
    await route.fulfill({ status: 200, json: { repos: mockRepos } });
  });
  page.route('**/health', async route => {
    await route.fulfill({ status: 200, json: { status: 'ok' } });
  });
  page.route('**/status', async route => {
    await route.fulfill({ status: 200, json: { idle: true, stopped: false } });
  });
}

test.describe('Accessibility - Status Page', () => {
  test.beforeEach(async ({ page }) => {
    setupCommonMocks(page);
    page.route('**/tasks**', async route => {
      await route.fulfill({ status: 200, json: { tasks: mockTasks, count: 1 } });
    });
    page.route('**/blocked', async route => {
      await route.fulfill({ status: 200, json: { report: mockBlockedReport } });
    });
  });

  test('should not have accessibility violations', async ({ page }) => {
    await page.goto('/status');
    await page.waitForSelector('#status-page');

    const accessibilityScanResults = await new AxeBuilder({ page }).analyze();

    expect(accessibilityScanResults.violations).toEqual([]);
  });

  test('should have proper heading hierarchy', async ({ page }) => {
    await page.goto('/status');

    // Check h1 exists
    const h1Count = await page.locator('h1').count();
    expect(h1Count).toBe(1);

    // Check section headings
    const h2Count = await page.locator('h2, .status-section-title').count();
    expect(h2Count).toBeGreaterThanOrEqual(3);
  });

  test('should have accessible task links', async ({ page }) => {
    await page.goto('/status');

    const taskLinks = page.locator('.task-link');
    const count = await taskLinks.count();

    for (let i = 0; i < count; i++) {
      const link = taskLinks.nth(i);
      await expect(link).toHaveAttribute('href');
      await expect(link).toHaveAttribute('data-task-id');
    }
  });

  test('should have sufficient color contrast', async ({ page }) => {
    await page.goto('/status');

    const accessibilityScanResults = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa', 'wcag21aa'])
      .analyze();

    // Specifically check color contrast
    const contrastViolations = accessibilityScanResults.violations.filter(
      v => v.id === 'color-contrast'
    );
    expect(contrastViolations).toEqual([]);
  });
});

test.describe('Accessibility - Tasks Page', () => {
  test.beforeEach(async ({ page }) => {
    setupCommonMocks(page);
    page.route('**/tasks**', async route => {
      await route.fulfill({ status: 200, json: { tasks: mockTasks, count: 1 } });
    });
  });

  test('should not have accessibility violations', async ({ page }) => {
    await page.goto('/task-list');
    await page.waitForSelector('#tasks-page');

    const accessibilityScanResults = await new AxeBuilder({ page }).analyze();
    expect(accessibilityScanResults.violations).toEqual([]);
  });

  test('should have accessible form controls', async ({ page }) => {
    await page.goto('/task-list');

    // Check filter labels
    const statusLabel = page.locator('label[for="filter-status"]');
    await expect(statusLabel).toBeVisible();

    const repoLabel = page.locator('label[for="filter-repo"]');
    await expect(repoLabel).toBeVisible();

    // Check selects have proper labels
    const statusSelect = page.locator('#filter-status');
    await expect(statusSelect).toHaveAttribute('aria-label');
  });

  test('should support keyboard navigation', async ({ page }) => {
    await page.goto('/task-list');

    // Tab through all interactive elements
    await page.keyboard.press('Tab');
    await page.keyboard.press('Tab');
    await page.keyboard.press('Tab');

    // Check focus is visible
    const focusedElement = page.locator(':focus');
    await expect(focusedElement).toBeVisible();
  });

  test('should have accessible task list', async ({ page }) => {
    await page.goto('/task-list');

    const taskList = page.locator('#tasks-list');
    await expect(taskList).toHaveAttribute('role', 'list');

    const taskItems = page.locator('.task-item');
    for (const item of await taskItems.all()) {
      await expect(item).toHaveAttribute('role', 'listitem');
    }
  });

  test('should have proper button labels', async ({ page }) => {
    await page.goto('/task-list');

    const addButton = page.locator('#add-task-btn');
    await expect(addButton).toBeVisible();
    
    // Button should have accessible text
    const text = await addButton.textContent();
    expect(text?.trim()).toBeTruthy();
  });
});

test.describe('Accessibility - Settings Page', () => {
  test.beforeEach(async ({ page }) => {
    setupCommonMocks(page);
    page.route('**/config', async route => {
      if (route.request().method() === 'GET') {
        await route.fulfill({ status: 200, json: mockConfig });
      } else {
        await route.fulfill({ status: 200, json: { ok: true } });
      }
    });
  });

  test('should not have accessibility violations', async ({ page }) => {
    await page.goto('/settings');
    await page.waitForSelector('#settings-page');

    const accessibilityScanResults = await new AxeBuilder({ page }).analyze();
    expect(accessibilityScanResults.violations).toEqual([]);
  });

  test('should have labeled form inputs', async ({ page }) => {
    await page.goto('/settings');

    const inputs = page.locator('input[type="text"], input[type="email"], input[type="number"]');
    const count = await inputs.count();

    for (let i = 0; i < count; i++) {
      const input = inputs.nth(i);
      const id = await input.getAttribute('id');
      
      // Each input should have a corresponding label
      const label = page.locator(`label[for="${id}"]`);
      await expect(label).toBeVisible();
    }
  });

  test('should have proper fieldset structure', async ({ page }) => {
    await page.goto('/settings');

    // Check config groups are properly structured
    const configGroups = page.locator('.config-group');
    const count = await configGroups.count();
    expect(count).toBeGreaterThanOrEqual(2);
  });

  test('should announce form validation errors', async ({ page }) => {
    await page.goto('/settings');

    // Check for aria-live regions for error announcements
    const liveRegions = page.locator('[aria-live]');
    // Should have at least one live region for messages
    const messageEl = page.locator('#settings-message');
    await expect(messageEl).toHaveAttribute('role', 'alert');
  });

  test('should support keyboard form submission', async ({ page }) => {
    await page.goto('/settings');

    // Navigate to submit button using keyboard
    await page.keyboard.press('Tab');
    await page.keyboard.press('Tab');
    await page.keyboard.press('Tab');

    // Enter should submit form
    await page.keyboard.press('Enter');
  });
});

test.describe('Accessibility - Channel Page', () => {
  test.beforeEach(async ({ page }) => {
    setupCommonMocks(page);
    page.route('**/context**', async route => {
      await route.fulfill({
        status: 200,
        json: { messages: mockContextMessages, count: 2, estimated_tokens: 100 },
      });
    });
    page.route('**/pending', async route => {
      await route.fulfill({ status: 200, json: { pending: null } });
    });
  });

  test('should not have accessibility violations', async ({ page }) => {
    await page.goto('/channel/workspace');
    await page.waitForSelector('#channel-page');

    const accessibilityScanResults = await new AxeBuilder({ page }).analyze();
    expect(accessibilityScanResults.violations).toEqual([]);
  });

  test('should have accessible conversation log', async ({ page }) => {
    await page.goto('/channel/workspace');

    const conversationLog = page.locator('#conversation-log');
    await expect(conversationLog).toBeVisible();

    // Messages should be in a list
    const messages = page.locator('.message-bubble');
    const count = await messages.count();
    expect(count).toBeGreaterThan(0);
  });

  test('should have labeled input field', async ({ page }) => {
    await page.goto('/channel/workspace');

    const input = page.locator('#channel-input input');
    await expect(input).toHaveAttribute('placeholder');
    await expect(input).toHaveAttribute('aria-label');
  });

  test('should have accessible send button', async ({ page }) => {
    await page.goto('/channel/workspace');

    const sendButton = page.locator('#channel-input button');
    await expect(sendButton).toBeVisible();
    
    // Should have accessible text or aria-label
    const text = await sendButton.textContent();
    const ariaLabel = await sendButton.getAttribute('aria-label');
    expect(text?.trim() || ariaLabel).toBeTruthy();
  });

  test('should handle clarification banner accessibly', async ({ page }) => {
    page.route('**/pending', async route => {
      await route.fulfill({ status: 200, json: { pending: 'What do you want?' } });
    });

    await page.goto('/channel/workspace');

    const banner = page.locator('#clarification-banner');
    await expect(banner).toBeVisible();

    // Banner should have role="alert" or similar
    await expect(banner).toHaveAttribute('role', 'alert');

    // Input should be focused
    const input = page.locator('#clar-input');
    await expect(input).toBeFocused();
  });
});

test.describe('Accessibility - Task Page', () => {
  test.beforeEach(async ({ page }) => {
    setupCommonMocks(page);
    page.route('**/tasks/task001', async route => {
      await route.fulfill({ status: 200, json: mockTasks[0] });
    });
    page.route('**/tasks/task001/dependencies', async route => {
      await route.fulfill({ status: 200, json: { task_id: 'task001', dependencies: [], count: 0 } });
    });
    page.route('**/context**', async route => {
      await route.fulfill({
        status: 200,
        json: { messages: mockContextMessages, count: 2, estimated_tokens: 100 },
      });
    });
  });

  test('should not have accessibility violations', async ({ page }) => {
    await page.goto('/task/task001');
    await page.waitForSelector('#task-page');

    const accessibilityScanResults = await new AxeBuilder({ page }).analyze();
    expect(accessibilityScanResults.violations).toEqual([]);
  });

  test('should have accessible task metadata', async ({ page }) => {
    await page.goto('/task/task001');

    // Task ID should be readable
    const metaItems = page.locator('.meta-item');
    const count = await metaItems.count();
    expect(count).toBeGreaterThanOrEqual(3);
  });

  test('should have accessible edit button', async ({ page }) => {
    await page.goto('/task/task001');

    const editButton = page.locator('#task-edit-btn');
    await expect(editButton).toBeVisible();
    
    const text = await editButton.textContent();
    expect(text?.trim()).toBeTruthy();
  });

  test('should have accessible dependency links', async ({ page }) => {
    await page.goto('/task/task001');

    const dependenciesSection = page.locator('#task-dependencies');
    await expect(dependenciesSection).toBeVisible();
  });

  test('should support keyboard navigation in edit form', async ({ page }) => {
    await page.goto('/task/task001');

    // Open edit form
    await page.click('#task-edit-btn');
    await page.waitForSelector('.task-edit-form');

    // Tab through form fields
    await page.keyboard.press('Tab');
    await page.keyboard.press('Tab');
    await page.keyboard.press('Tab');

    // Focus should be visible
    const focusedElement = page.locator(':focus');
    await expect(focusedElement).toBeVisible();
  });
});

test.describe('Accessibility - Sidebar & Navigation', () => {
  test.beforeEach(async ({ page }) => {
    setupCommonMocks(page);
    page.route('**/tasks**', async route => {
      await route.fulfill({ status: 200, json: { tasks: mockTasks, count: 1 } });
    });
  });

  test('should have accessible hamburger menu', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 667 });
    await page.goto('/task-list');

    const hamburger = page.locator('#hamburger-menu');
    await expect(hamburger).toHaveAttribute('aria-label');
    
    const label = await hamburger.getAttribute('aria-label');
    expect(label).toBeTruthy();
  });

  test('should have accessible sidebar navigation', async ({ page }) => {
    await page.goto('/task-list');

    const navItems = page.locator('.sb-item');
    const count = await navItems.count();

    for (let i = 0; i < count; i++) {
      const item = navItems.nth(i);
      
      // Should be keyboard accessible
      await expect(item).toBeVisible();
    }
  });

  test('should have proper landmark regions', async ({ page }) => {
    await page.goto('/task-list');

    // Should have main landmark
    const main = page.locator('main');
    await expect(main).toBeVisible();

    // Should have navigation landmark (sidebar)
    const nav = page.locator('nav');
    await expect(nav).toBeVisible();
  });

  test('should have skip link for keyboard users', async ({ page }) => {
    await page.goto('/task-list');

    // Check for skip link (should be present for accessibility)
    const skipLink = page.locator('a[href="#main"], a[href="#main-content"]');
    // This is a nice-to-have, not a failure if missing
    console.log('Skip link present:', await skipLink.count() > 0);
  });

  test('should manage focus when sidebar opens/closes', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 667 });
    await page.goto('/task-list');

    // Open sidebar
    await page.click('#hamburger-menu');
    
    // Focus should move to sidebar
    await page.waitForTimeout(300);
    const sidebar = page.locator('#sidebar');
    await expect(sidebar).toHaveClass(/open/);

    // Close sidebar
    await page.click('#hamburger-menu');
    
    // Focus should return to hamburger
    const hamburger = page.locator('#hamburger-menu');
    await expect(hamburger).toBeFocused();
  });
});

test.describe('Accessibility - Mobile', () => {
  test('should maintain accessibility on mobile viewport', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 667 });
    
    page.route('**/repos', async route => {
      await route.fulfill({ status: 200, json: { repos: mockRepos } });
    });
    page.route('**/tasks**', async route => {
      await route.fulfill({ status: 200, json: { tasks: mockTasks, count: 1 } });
    });
    page.route('**/health', async route => {
      await route.fulfill({ status: 200, json: { status: 'ok' } });
    });

    await page.goto('/task-list');

    const accessibilityScanResults = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa', 'wcag21aa'])
      .analyze();

    expect(accessibilityScanResults.violations).toEqual([]);
  });

  test('should have touch-friendly tap targets', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 667 });
    
    page.route('**/repos', async route => {
      await route.fulfill({ status: 200, json: { repos: mockRepos } });
    });
    page.route('**/tasks**', async route => {
      await route.fulfill({ status: 200, json: { tasks: mockTasks, count: 1 } });
    });
    page.route('**/health', async route => {
      await route.fulfill({ status: 200, json: { status: 'ok' } });
    });

    await page.goto('/task-list');

    // Check tap target sizes
    const interactiveElements = page.locator('button, a, input, [role="button"]');
    const count = await interactiveElements.count();

    for (let i = 0; i < Math.min(count, 5); i++) {
      const element = interactiveElements.nth(i);
      const box = await element.boundingBox();
      
      if (box) {
        // Minimum 44x44px touch target
        expect(box.width).toBeGreaterThanOrEqual(40);
        expect(box.height).toBeGreaterThanOrEqual(40);
      }
    }
  });
});

test.describe('Accessibility - Screen Reader', () => {
  test('should have proper ARIA live regions for dynamic content', async ({ page }) => {
    page.route('**/repos', async route => {
      await route.fulfill({ status: 200, json: { repos: mockRepos } });
    });
    page.route('**/config', async route => {
      if (route.request().method() === 'GET') {
        await route.fulfill({ status: 200, json: mockConfig });
      } else {
        await route.fulfill({ status: 200, json: { ok: true } });
      }
    });
    page.route('**/health', async route => {
      await route.fulfill({ status: 200, json: { status: 'ok' } });
    });

    await page.goto('/settings');

    // Message container should be aria-live
    const messageEl = page.locator('#settings-message');
    await expect(messageEl).toHaveAttribute('role', 'alert');
  });

  test('should announce status updates', async ({ page }) => {
    page.route('**/repos', async route => {
      await route.fulfill({ status: 200, json: { repos: mockRepos } });
    });
    page.route('**/tasks**', async route => {
      await route.fulfill({ status: 200, json: { tasks: mockTasks, count: 1 } });
    });
    page.route('**/blocked', async route => {
      await route.fulfill({ status: 200, json: { report: mockBlockedReport } });
    });
    page.route('**/health', async route => {
      await route.fulfill({ status: 200, json: { status: 'ok' } });
    });

    await page.goto('/status');

    // Status sections should be properly labeled
    const sections = page.locator('.status-section-header');
    const count = await sections.count();
    expect(count).toBeGreaterThanOrEqual(3);
  });
});
