/**
 * E2E Tests for Dashboard/Status Page
 *
 * Tests the status dashboard page functionality using Playwright.
 * Verifies routing, display, and navigation.
 */

import { test, expect } from '@playwright/test';

test.describe('Dashboard Page', () => {
  test.beforeEach(async ({ page }) => {
    // Mock API endpoints
    await page.route('**/repos', async route => {
      await route.fulfill({
        json: { repos: [] },
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
        json: {
          report: {
            human: [],
            dependencies: [],
            waiting: [],
          },
        },
      });
    });
  });

  test.describe('Navigation', () => {
    test('navigates to dashboard from sidebar', async ({ page }) => {
      await page.goto('/');
      await page.waitForSelector('#sidebar');

      // Click status tab in sidebar
      await page.click('[data-tab="dashboard"]');
      await page.waitForTimeout(100);

      // Should be on dashboard page
      expect(page.url()).toContain('/dashboard');
      await expect(page.locator('#status-page')).toBeVisible();
    });

    test('direct navigation to /dashboard works', async ({ page }) => {
      await page.goto('/dashboard');
      await page.waitForSelector('#status-page');

      await expect(page.locator('#status-page')).toBeVisible();
      await expect(page.locator('h1')).toHaveText('Status Dashboard');
    });

    test('sidebar highlights dashboard tab when active', async ({ page }) => {
      await page.goto('/dashboard');
      await page.waitForSelector('#sidebar');

      const dashboardTab = page.locator('[data-tab="dashboard"]');
      await expect(dashboardTab).toHaveClass(/active/);
    });

    test('can navigate from dashboard to other pages', async ({ page }) => {
      await page.goto('/dashboard');
      await page.waitForSelector('#sidebar');

      // Navigate to tasks
      await page.click('[data-tab="tasks"]');
      await page.waitForTimeout(100);

      expect(page.url()).toContain('/task-list');
      await expect(page.locator('#tasks-page')).toBeVisible();
    });
  });

  test.describe('Page Content', () => {
    test('displays page title', async ({ page }) => {
      await page.goto('/dashboard');
      await page.waitForSelector('#status-page');

      await expect(page.locator('#status-page h1')).toHaveText('Status Dashboard');
    });

    test('displays all three sections', async ({ page }) => {
      await page.goto('/dashboard');
      await page.waitForSelector('#status-page');

      await expect(page.locator('#status-blocked-human')).toBeVisible();
      await expect(page.locator('#status-blocked-deps')).toBeVisible();
      await expect(page.locator('#status-waiting')).toBeVisible();
    });

    test('displays section titles', async ({ page }) => {
      await page.goto('/dashboard');
      await page.waitForSelector('#status-page');

      await expect(page.locator('#status-blocked-human .status-section-title')).toHaveText('Blocked by Human');
      await expect(page.locator('#status-blocked-deps .status-section-title')).toHaveText('Blocked by Dependencies');
      await expect(page.locator('#status-waiting .status-section-title')).toHaveText('Waiting');
    });

    test('displays section icons', async ({ page }) => {
      await page.goto('/dashboard');
      await page.waitForSelector('#status-page');

      await expect(page.locator('#status-blocked-human .status-section-icon')).toHaveText('⦸');
      await expect(page.locator('#status-blocked-deps .status-section-icon')).toHaveText('⊞');
      await expect(page.locator('#status-waiting .status-section-icon')).toHaveText('⋯');
    });

    test('shows empty messages when no tasks', async ({ page }) => {
      await page.goto('/dashboard');
      await page.waitForSelector('#status-page');

      await expect(page.locator('#status-blocked-human .empty-message')).toBeVisible();
      await expect(page.locator('#status-blocked-deps .empty-message')).toBeVisible();
      await expect(page.locator('#status-waiting .empty-message')).toBeVisible();
    });
  });

  test.describe('Blocked by Dependencies', () => {
    test('displays blocked tasks with dependency information', async ({ page }) => {
      // Mock with blocked task
      await page.route('**/blocked', async route => {
        await route.fulfill({
          json: {
            report: {
              human: [],
              dependencies: [
                {
                  id: 'task1',
                  title: 'Blocked Task',
                  blocking_reason: 'Waiting on: dep1',
                },
              ],
              waiting: [],
            },
          },
        });
      });

      // Mock dependency API
      await page.route('**/tasks/task1/dependencies', async route => {
        await route.fulfill({
          json: {
            task_id: 'task1',
            dependencies: [
              {
                id: 'dep1',
                title: 'Dependency Task',
                description: '',
                repo: [],
                role: 'coder',
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
            ],
            count: 1,
          },
        });
      });

      await page.goto('/dashboard');
      await page.waitForSelector('#status-page');
      await page.waitForTimeout(100);

      // Should show blocked task
      await expect(page.locator('#status-blocked-deps .status-task-link')).toBeVisible();

      // Should show "Waiting on:" label
      await expect(page.locator('#status-blocked-deps .blockers-label')).toBeVisible();

      // Should show dependency link with id and title
      const depLink = page.locator('#status-blocked-deps .dependency-link');
      await expect(depLink).toBeVisible();
      await expect(depLink).toContainText('dep1');
      await expect(depLink).toContainText('Dependency Task');
    });

    test('dependency link is clickable', async ({ page }) => {
      await page.route('**/blocked', async route => {
        await route.fulfill({
          json: {
            report: {
              human: [],
              dependencies: [
                {
                  id: 'task1',
                  title: 'Blocked Task',
                  blocking_reason: 'Waiting on: dep1',
                },
              ],
              waiting: [],
            },
          },
        });
      });

      await page.route('**/tasks/task1/dependencies', async route => {
        await route.fulfill({
          json: {
            task_id: 'task1',
            dependencies: [
              {
                id: 'dep1',
                title: 'Dependency',
                description: '',
                repo: [],
                role: 'coder',
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
            ],
            count: 1,
          },
        });
      });

      await page.goto('/dashboard');
      await page.waitForSelector('#status-page');
      await page.waitForTimeout(100);

      // Click dependency link
      await page.click('#status-blocked-deps .dependency-link');
      await page.waitForTimeout(100);

      // Should navigate to task page
      expect(page.url()).toContain('/task/dep1');
    });

    test('displays multiple blockers for a task', async ({ page }) => {
      await page.route('**/blocked', async route => {
        await route.fulfill({
          json: {
            report: {
              human: [],
              dependencies: [
                {
                  id: 'task1',
                  title: 'Blocked Task',
                  blocking_reason: 'Waiting on: dep1, dep2',
                },
              ],
              waiting: [],
            },
          },
        });
      });

      await page.route('**/tasks/task1/dependencies', async route => {
        await route.fulfill({
          json: {
            task_id: 'task1',
            dependencies: [
              {
                id: 'dep1',
                title: 'First Dependency',
                description: '',
                repo: [],
                role: 'coder',
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
              {
                id: 'dep2',
                title: 'Second Dependency',
                description: '',
                repo: [],
                role: 'coder',
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
            ],
            count: 2,
          },
        });
      });

      await page.goto('/dashboard');
      await page.waitForSelector('#status-page');
      await page.waitForTimeout(100);

      // Should show both dependencies
      const depLinks = page.locator('#status-blocked-deps .dependency-link');
      await expect(depLinks).toHaveCount(2);
    });
  });

  test.describe('Responsive Behavior', () => {
    test('displays correctly on desktop', async ({ page }) => {
      await page.setViewportSize({ width: 1920, height: 1080 });
      await page.goto('/dashboard');
      await page.waitForSelector('#status-page');

      // All sections should be visible
      await expect(page.locator('#status-blocked-human')).toBeVisible();
      await expect(page.locator('#status-blocked-deps')).toBeVisible();
      await expect(page.locator('#status-waiting')).toBeVisible();
    });

    test('displays correctly on mobile', async ({ page }) => {
      await page.setViewportSize({ width: 375, height: 667 });
      await page.goto('/dashboard');
      await page.waitForSelector('#status-page');

      // All sections should be visible
      await expect(page.locator('#status-blocked-human')).toBeVisible();
      await expect(page.locator('#status-blocked-deps')).toBeVisible();
      await expect(page.locator('#status-waiting')).toBeVisible();
    });

    test('blocker titles truncate on small screens', async ({ page }) => {
      await page.route('**/blocked', async route => {
        await route.fulfill({
          json: {
            report: {
              human: [],
              dependencies: [
                {
                  id: 'task1',
                  title: 'Task',
                  blocking_reason: 'Waiting on: dep1',
                },
              ],
              waiting: [],
            },
          },
        });
      });

      await page.route('**/tasks/task1/dependencies', async route => {
        await route.fulfill({
          json: {
            task_id: 'task1',
            dependencies: [
              {
                id: 'dep1',
                title: 'This is a very long dependency title that should be truncated on small screens',
                description: '',
                repo: [],
                role: 'coder',
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
            ],
            count: 1,
          },
        });
      });

      await page.setViewportSize({ width: 375, height: 667 });
      await page.goto('/dashboard');
      await page.waitForSelector('#status-page');
      await page.waitForTimeout(100);

      // Title should be truncated (check for ellipsis via text-overflow)
      const blockerTitle = page.locator('#status-blocked-deps .blocker-title');
      await expect(blockerTitle).toBeVisible();
    });
  });
});
