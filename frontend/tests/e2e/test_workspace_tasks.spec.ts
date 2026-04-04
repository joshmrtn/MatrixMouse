/**
 * E2E Tests for Workspace Task Functionality
 *
 * Tests the workspace task display, expand/collapse, and highlighting behavior.
 * Uses Playwright with the fake test server to verify actual visual rendering.
 */

import { test, expect } from '@playwright/test';

test.describe('Workspace Tasks', () => {
  test.beforeEach(async ({ page }) => {
    // Mock API endpoints with workspace tasks
    await page.route('**/repos', async route => {
      await route.fulfill({
        json: {
          repos: [
            { name: 'repo1', remote: 'https://github.com/test/repo1.git', local_path: '/test/repo1', added: '2024-01-01' },
            { name: 'repo2', remote: 'https://github.com/test/repo2.git', local_path: '/test/repo2', added: '2024-01-01' },
          ]
        }
      });
    });
  });

  test.describe('Workspace Expand Button', () => {
    test('workspace expand button is always rendered', async ({ page }) => {
      // Mock with no workspace tasks
      await page.route('**/tasks**', async route => {
        await route.fulfill({ json: { tasks: [], count: 0 } });
      });

      await page.goto('/');
      await page.waitForSelector('#sidebar');

      // Expand button should exist (may be hidden via CSS)
      const expandBtn = page.locator('[data-scope="workspace"] .sb-repo-expand');
      await expect(expandBtn).toHaveCount(1);
    });

    test('workspace expand button is visible when workspace has tasks', async ({ page }) => {
      // Mock with workspace task (no repo)
      await page.route('**/tasks**', async route => {
        await route.fulfill({
          json: {
            tasks: [
              {
                id: 'ws-task1',
                title: 'Workspace Task',
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
              }
            ],
            count: 1
          }
        });
      });

      await page.goto('/');
      await page.waitForSelector('#sidebar');

      const expandBtn = page.locator('[data-scope="workspace"] .sb-repo-expand');
      await expect(expandBtn).toBeVisible();
    });

    test('workspace expand button is hidden when no workspace tasks', async ({ page }) => {
      // Mock with only repo tasks
      await page.route('**/tasks**', async route => {
        await route.fulfill({
          json: {
            tasks: [
              {
                id: 'repo-task',
                title: 'Repo Task',
                description: '',
                repo: ['repo1'],
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
              }
            ],
            count: 1
          }
        });
      });

      await page.goto('/');
      await page.waitForSelector('#sidebar');

      const expandBtn = page.locator('[data-scope="workspace"] .sb-repo-expand');
      // Button exists but should be hidden via CSS display property
      const display = await expandBtn.evaluate(el => window.getComputedStyle(el).display);
      expect(display).toBe('none');
    });
  });

  test.describe('Workspace Task Display', () => {
    test('workspace tasks with no repo appear under workspace', async ({ page }) => {
      await page.route('**/tasks**', async route => {
        await route.fulfill({
          json: {
            tasks: [
              {
                id: 'ws-task1',
                title: 'Workspace Task No Repo',
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
              }
            ],
            count: 1
          }
        });
      });

      await page.goto('/');
      await page.waitForSelector('#sidebar');

      // Expand workspace
      await page.click('[data-scope="workspace"] .sb-repo-expand');
      await page.waitForTimeout(100);

      // Task should be visible under workspace
      const taskItem = page.locator('[data-task-id="ws-task1"]');
      await expect(taskItem).toBeVisible();

      // Verify task is under workspace, not under a repo
      const workspaceTree = page.locator('#sb-task-tree-workspace');
      await expect(workspaceTree).toContainText('Workspace Task No Repo');
    });

    test('multi-repo tasks appear under workspace', async ({ page }) => {
      await page.route('**/tasks**', async route => {
        await route.fulfill({
          json: {
            tasks: [
              {
                id: 'multi-task',
                title: 'Multi-Repo Task',
                description: '',
                repo: ['repo1', 'repo2'],
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
              }
            ],
            count: 1
          }
        });
      });

      await page.goto('/');
      await page.waitForSelector('#sidebar');

      // Expand workspace
      await page.click('[data-scope="workspace"] .sb-repo-expand');
      await page.waitForTimeout(100);

      // Task should be visible under workspace
      const taskItem = workspaceTree.locator('[data-task-id="multi-task"]');
      await expect(taskItem).toBeVisible();
    });

    test('multi-repo tasks also appear under each repo', async ({ page }) => {
      await page.route('**/tasks**', async route => {
        await route.fulfill({
          json: {
            tasks: [
              {
                id: 'multi-task',
                title: 'Multi-Repo Task',
                description: '',
                repo: ['repo1', 'repo2'],
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
              }
            ],
            count: 1
          }
        });
      });

      await page.goto('/');
      await page.waitForSelector('#sidebar');

      // Expand repo1
      await page.click('[data-repo="repo1"] .sb-repo-expand');
      await page.waitForTimeout(100);

      // Task should be visible under repo1
      const taskInRepo1 = page.locator('[data-repo="repo1"] + #sb-task-tree-repo1 [data-task-id="multi-task"]');
      await expect(taskInRepo1).toBeVisible();

      // Expand repo2
      await page.click('[data-repo="repo2"] .sb-repo-expand');
      await page.waitForTimeout(100);

      // Task should also be visible under repo2
      const taskInRepo2 = page.locator('[data-repo="repo2"] + #sb-task-tree-repo2 [data-task-id="multi-task"]');
      await expect(taskInRepo2).toBeVisible();
    });

    test('single-repo tasks do NOT appear under workspace', async ({ page }) => {
      await page.route('**/tasks**', async route => {
        await route.fulfill({
          json: {
            tasks: [
              {
                id: 'repo-task',
                title: 'Single Repo Task',
                description: '',
                repo: ['repo1'],
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
              }
            ],
            count: 1
          }
        });
      });

      await page.goto('/');
      await page.waitForSelector('#sidebar');

      // Expand workspace
      await page.click('[data-scope="workspace"] .sb-repo-expand');
      await page.waitForTimeout(100);

      // Task should NOT be under workspace
      const workspaceTree = page.locator('#sb-task-tree-workspace');
      await expect(workspaceTree).not.toContainText('Single Repo Task');
    });
  });

  test.describe('Workspace Expand/Collapse', () => {
    test('clicking workspace expand button shows task tree', async ({ page }) => {
      await page.route('**/tasks**', async route => {
        await route.fulfill({
          json: {
            tasks: [
              {
                id: 'ws-task1',
                title: 'Workspace Task',
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
              }
            ],
            count: 1
          }
        });
      });

      await page.goto('/');
      await page.waitForSelector('#sidebar');

      // Task tree should be hidden initially
      const workspaceTree = page.locator('#sb-task-tree-workspace');
      await expect(workspaceTree).not.toHaveClass(/visible/);

      // Click expand
      await page.click('[data-scope="workspace"] .sb-repo-expand');
      await page.waitForTimeout(100);

      // Task tree should be visible
      await expect(workspaceTree).toHaveClass(/visible/);

      // Arrow should point down
      const expandBtn = page.locator('[data-scope="workspace"] .sb-repo-expand');
      const text = await expandBtn.textContent();
      expect(text?.trim()).toBe('▼');
    });

    test('clicking workspace expand button again collapses task tree', async ({ page }) => {
      await page.route('**/tasks**', async route => {
        await route.fulfill({
          json: {
            tasks: [
              {
                id: 'ws-task1',
                title: 'Workspace Task',
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
              }
            ],
            count: 1
          }
        });
      });

      await page.goto('/');
      await page.waitForSelector('#sidebar');

      // Expand
      await page.click('[data-scope="workspace"] .sb-repo-expand');
      await page.waitForTimeout(100);

      // Collapse
      await page.click('[data-scope="workspace"] .sb-repo-expand');
      await page.waitForTimeout(100);

      // Task tree should be hidden
      const workspaceTree = page.locator('#sb-task-tree-workspace');
      await expect(workspaceTree).not.toHaveClass(/visible/);

      // Arrow should point right
      const expandBtn = page.locator('[data-scope="workspace"] .sb-repo-expand');
      const text = await expandBtn.textContent();
      expect(text?.trim()).toBe('▶');
    });
  });

  test.describe('Workspace Task Highlighting', () => {
    test('workspace is highlighted when workspace task is selected', async ({ page }) => {
      await page.route('**/tasks**', async route => {
        await route.fulfill({
          json: {
            tasks: [
              {
                id: 'ws-task1',
                title: 'Workspace Task',
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
              }
            ],
            count: 1
          }
        });
      });

      await page.goto('/task/ws-task1');
      await page.waitForSelector('#sidebar');
      await page.waitForTimeout(100);

      // Workspace should be highlighted
      const workspaceItem = page.locator('[data-scope="workspace"]');
      await expect(workspaceItem).toHaveClass(/active/);
    });

    test('workspace is highlighted when multi-repo task is selected', async ({ page }) => {
      await page.route('**/tasks**', async route => {
        await route.fulfill({
          json: {
            tasks: [
              {
                id: 'multi-task',
                title: 'Multi-Repo Task',
                description: '',
                repo: ['repo1', 'repo2'],
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
              }
            ],
            count: 1
          }
        });
      });

      await page.goto('/task/multi-task');
      await page.waitForSelector('#sidebar');
      await page.waitForTimeout(100);

      // Workspace should be highlighted
      const workspaceItem = page.locator('[data-scope="workspace"]');
      await expect(workspaceItem).toHaveClass(/active/);
    });

    test('repo is highlighted when single-repo task is selected', async ({ page }) => {
      await page.route('**/tasks**', async route => {
        await route.fulfill({
          json: {
            tasks: [
              {
                id: 'repo-task',
                title: 'Repo Task',
                description: '',
                repo: ['repo1'],
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
              }
            ],
            count: 1
          }
        });
      });

      await page.goto('/task/repo-task');
      await page.waitForSelector('#sidebar');
      await page.waitForTimeout(100);

      // Repo1 should be highlighted
      const repo1Item = page.locator('[data-repo="repo1"]');
      await expect(repo1Item).toHaveClass(/active/);

      // Workspace should NOT be highlighted
      const workspaceItem = page.locator('[data-scope="workspace"]');
      await expect(workspaceItem).not.toHaveClass(/active/);
    });

    test('workspace expands automatically when workspace task is selected', async ({ page }) => {
      await page.route('**/tasks**', async route => {
        await route.fulfill({
          json: {
            tasks: [
              {
                id: 'ws-task1',
                title: 'Workspace Task',
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
              }
            ],
            count: 1
          }
        });
      });

      await page.goto('/task/ws-task1');
      await page.waitForSelector('#sidebar');
      await page.waitForTimeout(100);

      // Workspace task tree should be expanded
      const workspaceTree = page.locator('#sb-task-tree-workspace');
      await expect(workspaceTree).toHaveClass(/visible/);
    });
  });

  test.describe('Mixed Tasks', () => {
    test('workspace and repo tasks display correctly together', async ({ page }) => {
      await page.route('**/tasks**', async route => {
        await route.fulfill({
          json: {
            tasks: [
              {
                id: 'ws-task',
                title: 'Workspace Task',
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
                id: 'repo1-task',
                title: 'Repo1 Task',
                description: '',
                repo: ['repo1'],
                role: 'coder',
                status: 'running',
                branch: 'mm/feature',
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
                id: 'repo2-task',
                title: 'Repo2 Task',
                description: '',
                repo: ['repo2'],
                role: 'writer',
                status: 'complete',
                branch: 'mm/docs',
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
              }
            ],
            count: 3
          }
        });
      });

      await page.goto('/');
      await page.waitForSelector('#sidebar');

      // Expand workspace
      await page.click('[data-scope="workspace"] .sb-repo-expand');
      await page.waitForTimeout(100);

      // Workspace should only show workspace task
      const workspaceTree = page.locator('#sb-task-tree-workspace');
      await expect(workspaceTree).toContainText('Workspace Task');
      await expect(workspaceTree).not.toContainText('Repo1 Task');
      await expect(workspaceTree).not.toContainText('Repo2 Task');

      // Expand repo1
      await page.click('[data-repo="repo1"] .sb-repo-expand');
      await page.waitForTimeout(100);

      // Repo1 should only show repo1 task
      const repo1Tree = page.locator('#sb-task-tree-repo1');
      await expect(repo1Tree).toContainText('Repo1 Task');
      await expect(repo1Tree).not.toContainText('Workspace Task');
    });
  });
});
