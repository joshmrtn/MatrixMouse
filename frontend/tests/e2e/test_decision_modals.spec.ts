/**
 * E2E Tests for Decision Banner
 *
 * Tests decision/approval banner display and functionality.
 * The banner appears inline in the task conversation view when
 * the agent requires human approval. It is NOT a blocking modal —
 * users can still read conversation history and interact with the
 * rest of the page while deciding.
 *
 * NOTE: These tests mock WebSocket events since we don't have a running backend.
 * In production, these events would come from the WebSocket connection.
 */

import { test, expect } from '@playwright/test';

test.describe('Decision Banner', () => {
  const mockTask = {
    id: 'test-123',
    title: 'Test Task',
    description: 'Test',
    repo: ['test-repo'],
    role: 'coder',
    status: 'blocked_by_human',
    branch: 'mm/test',
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

  test.beforeEach(async ({ page }) => {
    await page.route('**/repos', async route => {
      await route.fulfill({ json: { repos: [] } });
    });
    await page.route('**/tasks**', async route => {
      await route.fulfill({
        json: { tasks: [mockTask], count: 1 },
      });
    });
    await page.route('**/tasks/test-123', async route => {
      await route.fulfill({ json: mockTask });
    });
    await page.route('**/tasks/abc-123', async route => {
      await route.fulfill({ json: { ...mockTask, id: 'abc-123' } });
    });
    await page.route('**/tasks/*/dependencies', async route => {
      await route.fulfill({ json: { task_id: 'test-123', dependencies: [], count: 0 } });
    });
    await page.route('**/context**', async route => {
      await route.fulfill({ json: { messages: [], count: 0, estimated_tokens: 0 } });
    });
    await page.route('**/status', async route => {
      await route.fulfill({ json: { idle: true, stopped: false, blocked: false } });
    });
    await page.route('**/tasks/*/decision', async route => {
      await route.fulfill({ json: { success: true } });
    });
  });

  test.describe('Banner Display', () => {
    test('decomposition banner displays with correct title and message', async ({ page }) => {
      await page.goto('/task/test-123');
      await page.waitForSelector('#task-page');

      await page.evaluate(() => {
        window.dispatchEvent(new CustomEvent('decomposition_confirmation_required', {
          detail: {
            task_id: 'test-123',
            task_title: 'Test Task',
            current_depth: 1,
            allowed_depth: 3,
            proposed_subtasks: [],
            choices: [
              { value: 'allow', label: 'Allow further decomposition', description: 'Grant another 3 levels.' },
              { value: 'deny', label: 'Do not decompose further', description: 'Complete within current depth.' },
            ],
          },
        }));
      });

      const banner = page.locator('#decision-banner');
      await expect(banner).toBeVisible({ timeout: 5000 });

      const title = page.locator('#decision-banner-title');
      await expect(title).toBeVisible();
      await expect(title).toContainText(/decomposition/i);

      const body = page.locator('#decision-banner-body');
      await expect(body).toBeVisible();
      await expect(body).toContainText(/Test Task/i);
      await expect(body).toContainText(/1/);
    });

    test('decomposition banner shows Allow and Deny choices', async ({ page }) => {
      await page.goto('/task/test-123');
      await page.waitForSelector('#task-page');

      await page.evaluate(() => {
        window.dispatchEvent(new CustomEvent('decomposition_confirmation_required', {
          detail: {
            task_id: 'test-123', task_title: 'Test Task', current_depth: 1, allowed_depth: 3,
            proposed_subtasks: [],
            choices: [
              { value: 'allow', label: 'Allow further decomposition', description: '' },
              { value: 'deny', label: 'Do not decompose further', description: '' },
            ],
          },
        }));
      });

      await expect(page.locator('#decision-banner')).toBeVisible();

      const allowBtn = page.locator('#decision-banner-choices button:has-text("Allow further decomposition")');
      await expect(allowBtn).toBeVisible();
      await expect(allowBtn).toBeEnabled();

      const denyBtn = page.locator('#decision-banner-choices button:has-text("Do not decompose further")');
      await expect(denyBtn).toBeVisible();
      await expect(denyBtn).toBeEnabled();
    });

    test('PR approval banner displays with correct title', async ({ page }) => {
      await page.goto('/task/test-123');
      await page.waitForSelector('#task-page');

      await page.evaluate(() => {
        window.dispatchEvent(new CustomEvent('pr_approval_required', {
          detail: {
            task_id: 'test-123',
            task_title: 'Test Task',
            branch: 'mm/test',
            parent_branch: 'main',
            repo: 'test-repo',
            choices: [
              { value: 'approve', label: 'Push branch and open PR', description: '' },
              { value: 'reject', label: 'Block for manual resolution', description: '' },
            ],
          },
        }));
      });

      const banner = page.locator('#decision-banner');
      await expect(banner).toBeVisible({ timeout: 5000 });

      const title = page.locator('#decision-banner-title');
      await expect(title).toContainText(/pull request|approval/i);
    });

    test('PR approval banner shows Approve and Reject choices', async ({ page }) => {
      await page.goto('/task/test-123');
      await page.waitForSelector('#task-page');

      await page.evaluate(() => {
        window.dispatchEvent(new CustomEvent('pr_approval_required', {
          detail: {
            task_id: 'test-123', task_title: 'Test Task', branch: 'mm/test',
            parent_branch: 'main', repo: 'test-repo',
            choices: [
              { value: 'approve', label: 'Push branch and open PR', description: '' },
              { value: 'reject', label: 'Block for manual resolution', description: '' },
            ],
          },
        }));
      });

      await expect(page.locator('#decision-banner')).toBeVisible();

      const approveBtn = page.locator('#decision-banner-choices button:has-text("Push branch and open PR")');
      await expect(approveBtn).toBeVisible();
      await expect(approveBtn).toBeEnabled();

      const rejectBtn = page.locator('#decision-banner-choices button:has-text("Block for manual resolution")');
      await expect(rejectBtn).toBeVisible();
      await expect(rejectBtn).toBeEnabled();
    });

    test('turn limit banner displays with correct choices', async ({ page }) => {
      await page.goto('/task/test-123');
      await page.waitForSelector('#task-page');

      await page.evaluate(() => {
        window.dispatchEvent(new CustomEvent('turn_limit_reached', {
          detail: {
            task_id: 'test-123',
            task_title: 'Test Task',
            role: 'coder',
            turns_taken: 10,
            turn_limit: 10,
            choices: [
              { value: 'extend', label: 'Extend turn limit', description: '' },
              { value: 'respec', label: 'Respecify and reset', description: '' },
              { value: 'cancel', label: 'Cancel task', description: '' },
            ],
          },
        }));
      });

      const banner = page.locator('#decision-banner');
      await expect(banner).toBeVisible({ timeout: 5000 });

      const title = page.locator('#decision-banner-title');
      await expect(title).toContainText(/turn.*limit/i);
    });

    test('turn limit banner shows Extend, Respecify, and Cancel choices', async ({ page }) => {
      await page.goto('/task/test-123');
      await page.waitForSelector('#task-page');

      await page.evaluate(() => {
        window.dispatchEvent(new CustomEvent('turn_limit_reached', {
          detail: {
            task_id: 'test-123', task_title: 'Test Task', role: 'coder',
            turns_taken: 10, turn_limit: 10,
            choices: [
              { value: 'extend', label: 'Extend turn limit', description: '' },
              { value: 'respec', label: 'Respecify and reset', description: '' },
              { value: 'cancel', label: 'Cancel task', description: '' },
            ],
          },
        }));
      });

      await expect(page.locator('#decision-banner')).toBeVisible();

      const choiceButtons = page.locator('#decision-banner-choices button');
      const count = await choiceButtons.count();
      expect(count).toBeGreaterThanOrEqual(3);
    });
  });

  test.describe('Non-blocking behavior', () => {
    test('banner does not block interaction with conversation', async ({ page }) => {
      await page.goto('/task/test-123');
      await page.waitForSelector('#task-page');

      await page.evaluate(() => {
        window.dispatchEvent(new CustomEvent('decomposition_confirmation_required', {
          detail: {
            task_id: 'test-123', task_title: 'Test Task', current_depth: 1, allowed_depth: 3,
            proposed_subtasks: [],
            choices: [{ value: 'allow', label: 'Allow', description: '' }, { value: 'deny', label: 'Deny', description: '' }],
          },
        }));
      });

      await expect(page.locator('#decision-banner')).toBeVisible();

      // The task page and conversation should still be visible and interactable
      await expect(page.locator('#task-page')).toBeVisible();
      const bannerBox = await page.locator('#decision-banner').boundingBox();
      const taskPageBox = await page.locator('#task-page').boundingBox();
      expect(bannerBox).toBeTruthy();
      expect(taskPageBox).toBeTruthy();
    });

    test('banner can be collapsed and expanded', async ({ page }) => {
      await page.goto('/task/test-123');
      await page.waitForSelector('#task-page');

      await page.evaluate(() => {
        window.dispatchEvent(new CustomEvent('decomposition_confirmation_required', {
          detail: {
            task_id: 'test-123', task_title: 'Test Task', current_depth: 1, allowed_depth: 3,
            proposed_subtasks: [],
            choices: [{ value: 'allow', label: 'Allow', description: '' }, { value: 'deny', label: 'Deny', description: '' }],
          },
        }));
      });

      await expect(page.locator('#decision-banner')).toBeVisible();

      // Collapse
      await page.locator('.decision-collapse-btn').click();
      await expect(page.locator('.decision-banner-body')).not.toBeVisible();

      // Expand
      await page.locator('.decision-collapse-btn').click();
      await expect(page.locator('.decision-banner-body')).toBeVisible();
    });
  });

  test.describe('Text Input Validation', () => {
    test('deny decomposition requires text input', async ({ page }) => {
      await page.goto('/task/test-123');
      await page.waitForSelector('#task-page');

      await page.evaluate(() => {
        window.dispatchEvent(new CustomEvent('decomposition_confirmation_required', {
          detail: {
            task_id: 'test-123', task_title: 'Test Task', current_depth: 1, allowed_depth: 3,
            proposed_subtasks: [],
            choices: [{ value: 'allow', label: 'Allow', description: '' }, { value: 'deny', label: 'Deny', description: '' }],
          },
        }));
      });

      await expect(page.locator('#decision-banner')).toBeVisible();

      const textInput = page.locator('#decision-banner #decision-banner-note');
      await expect(textInput).toBeVisible();
    });

    test('empty text input is rejected', async ({ page }) => {
      await page.goto('/task/test-123');
      await page.waitForSelector('#task-page');

      let apiCalled = false;
      await page.route('**/tasks/*/decision', async route => {
        apiCalled = true;
        await route.fulfill({ json: { success: true } });
      });

      await page.evaluate(() => {
        window.dispatchEvent(new CustomEvent('decomposition_confirmation_required', {
          detail: {
            task_id: 'test-123', task_title: 'Test Task', current_depth: 1, allowed_depth: 3,
            proposed_subtasks: [],
            choices: [{ value: 'allow', label: 'Allow', description: '' }, { value: 'deny', label: 'Deny', description: '' }],
          },
        }));
      });

      await expect(page.locator('#decision-banner')).toBeVisible();

      const textInput = page.locator('#decision-banner #decision-banner-note');
      await textInput.clear();
      await page.locator('#decision-banner-choices button:has-text("Deny")').click();

      await page.waitForTimeout(300);
      expect(apiCalled).toBeFalsy();
    });

    test('whitespace-only text input is rejected', async ({ page }) => {
      await page.goto('/task/test-123');
      await page.waitForSelector('#task-page');

      let apiCalled = false;
      await page.route('**/tasks/*/decision', async route => {
        apiCalled = true;
        await route.fulfill({ json: { success: true } });
      });

      await page.evaluate(() => {
        window.dispatchEvent(new CustomEvent('decomposition_confirmation_required', {
          detail: {
            task_id: 'test-123', task_title: 'Test Task', current_depth: 1, allowed_depth: 3,
            proposed_subtasks: [],
            choices: [{ value: 'allow', label: 'Allow', description: '' }, { value: 'deny', label: 'Deny', description: '' }],
          },
        }));
      });

      await expect(page.locator('#decision-banner')).toBeVisible();

      const textInput = page.locator('#decision-banner #decision-banner-note');
      await textInput.fill('   \n\t  ');
      await page.locator('#decision-banner-choices button:has-text("Deny")').click();

      await page.waitForTimeout(300);
      expect(apiCalled).toBeFalsy();
    });

    test('valid text input is accepted', async ({ page }) => {
      await page.goto('/task/test-123');
      await page.waitForSelector('#task-page');

      let apiCallMade = false;
      await page.route('**/tasks/*/decision', async route => {
        apiCallMade = true;
        await route.fulfill({ json: { success: true } });
      });

      await page.evaluate(() => {
        window.dispatchEvent(new CustomEvent('decomposition_confirmation_required', {
          detail: {
            task_id: 'test-123', task_title: 'Test Task', current_depth: 1, allowed_depth: 3,
            proposed_subtasks: [],
            choices: [{ value: 'allow', label: 'Allow', description: '' }, { value: 'deny', label: 'Deny', description: '' }],
          },
        }));
      });

      await expect(page.locator('#decision-banner')).toBeVisible();

      const textInput = page.locator('#decision-banner #decision-banner-note');
      await textInput.fill('This is a valid reason for denial');
      await page.locator('#decision-banner-choices button:has-text("Deny")').click();

      await page.waitForTimeout(500);
      expect(apiCallMade).toBeTruthy();
    });
  });

  test.describe('Banner Submission', () => {
    test('submit decision triggers API call', async ({ page }) => {
      await page.goto('/task/test-123');
      await page.waitForSelector('#task-page');

      let decisionApiCalled = false;
      await page.route('**/tasks/*/decision', async route => {
        decisionApiCalled = true;
        const postData = route.request().postDataJSON();
        const url = route.request().url();
        expect(postData).toHaveProperty('choice');
        expect(url).toMatch(/\/tasks\/[^/]+\/decision/);
        await route.fulfill({ json: { success: true } });
      });

      await page.evaluate(() => {
        window.dispatchEvent(new CustomEvent('decomposition_confirmation_required', {
          detail: {
            task_id: 'test-123', task_title: 'Test Task', current_depth: 1, allowed_depth: 3,
            proposed_subtasks: [],
            choices: [{ value: 'allow', label: 'Allow', description: '' }, { value: 'deny', label: 'Deny', description: '' }],
          },
        }));
      });

      await expect(page.locator('#decision-banner')).toBeVisible();

      const allowBtn = page.locator('#decision-banner-choices button:has-text("Allow")');
      await allowBtn.first().click();

      await page.waitForTimeout(500);
      expect(decisionApiCalled).toBeTruthy();
    });

    test('submit decision includes correct task_id', async ({ page }) => {
      await page.goto('/task/abc-123');
      await page.waitForSelector('#task-page');

      let capturedTaskId: string | null = null;
      await page.route('**/tasks/*/decision', async route => {
        const url = route.request().url();
        const match = url.match(/\/tasks\/([^/]+)\/decision/);
        if (match) capturedTaskId = match[1];
        await route.fulfill({ json: { success: true } });
      });

      await page.evaluate(() => {
        window.dispatchEvent(new CustomEvent('decomposition_confirmation_required', {
          detail: {
            task_id: 'abc-123', task_title: 'Test Task', current_depth: 1, allowed_depth: 3,
            proposed_subtasks: [],
            choices: [{ value: 'allow', label: 'Allow', description: '' }, { value: 'deny', label: 'Deny', description: '' }],
          },
        }));
      });

      await expect(page.locator('#decision-banner')).toBeVisible();

      const allowBtn = page.locator('#decision-banner-choices button:has-text("Allow")');
      await allowBtn.first().click();

      await page.waitForTimeout(500);
      expect(capturedTaskId).toBe('abc-123');
    });

    test('submit decision includes correct choice', async ({ page }) => {
      await page.goto('/task/test-123');
      await page.waitForSelector('#task-page');

      let capturedChoice: string | null = null;
      await page.route('**/tasks/*/decision', async route => {
        const postData = route.request().postDataJSON();
        capturedChoice = postData.choice;
        await route.fulfill({ json: { success: true } });
      });

      await page.evaluate(() => {
        window.dispatchEvent(new CustomEvent('decomposition_confirmation_required', {
          detail: {
            task_id: 'test-123', task_title: 'Test Task', current_depth: 1, allowed_depth: 3,
            proposed_subtasks: [],
            choices: [{ value: 'allow', label: 'Allow', description: '' }, { value: 'deny', label: 'Deny', description: '' }],
          },
        }));
      });

      await expect(page.locator('#decision-banner')).toBeVisible();

      const textInput = page.locator('#decision-banner #decision-banner-note');
      await textInput.fill('Test reason');
      const denyBtn = page.locator('#decision-banner-choices button:has-text("Deny")');
      await denyBtn.click();

      await page.waitForTimeout(500);
      expect(capturedChoice).toBeTruthy();
      expect(capturedChoice!.toLowerCase()).toMatch(/deny/);
    });

    test('submit decision with note includes metadata', async ({ page }) => {
      await page.goto('/task/test-123');
      await page.waitForSelector('#task-page');

      let capturedNote: string | null = null;
      await page.route('**/tasks/*/decision', async route => {
        const postData = route.request().postDataJSON();
        capturedNote = postData.note;
        await route.fulfill({ json: { success: true } });
      });

      await page.evaluate(() => {
        window.dispatchEvent(new CustomEvent('decomposition_confirmation_required', {
          detail: {
            task_id: 'test-123', task_title: 'Test Task', current_depth: 1, allowed_depth: 3,
            proposed_subtasks: [],
            choices: [{ value: 'allow', label: 'Allow', description: '' }, { value: 'deny', label: 'Deny', description: '' }],
          },
        }));
      });

      await expect(page.locator('#decision-banner')).toBeVisible();

      const noteField = page.locator('#decision-banner #decision-banner-note');
      await noteField.fill('Test note for decision');
      await page.locator('#decision-banner-choices button:has-text("Deny")').click();

      await page.waitForTimeout(500);
      expect(capturedNote).toBe('Test note for decision');
    });

    test('banner hides after successful submission', async ({ page }) => {
      await page.goto('/task/test-123');
      await page.waitForSelector('#task-page');

      await page.route('**/tasks/*/decision', async route => {
        await route.fulfill({ json: { success: true } });
      });

      await page.evaluate(() => {
        window.dispatchEvent(new CustomEvent('decomposition_confirmation_required', {
          detail: {
            task_id: 'test-123', task_title: 'Test Task', current_depth: 1, allowed_depth: 3,
            proposed_subtasks: [],
            choices: [{ value: 'allow', label: 'Allow', description: '' }, { value: 'deny', label: 'Deny', description: '' }],
          },
        }));
      });

      await expect(page.locator('#decision-banner')).toBeVisible();

      const allowBtn = page.locator('#decision-banner-choices button:has-text("Allow")');
      await allowBtn.first().click();

      await page.waitForTimeout(1000);
      await expect(page.locator('#decision-banner')).not.toBeVisible();
    });
  });

  test.describe('Error Handling', () => {
    test('handles API error on decision submission', async ({ page }) => {
      await page.goto('/task/test-123');
      await page.waitForSelector('#task-page');

      await page.route('**/tasks/*/decision', async route => {
        await route.fulfill({ status: 500, json: { error: 'Failed' } });
      });

      await page.evaluate(() => {
        window.dispatchEvent(new CustomEvent('decomposition_confirmation_required', {
          detail: {
            task_id: 'test-123', task_title: 'Test Task', current_depth: 1, allowed_depth: 3,
            proposed_subtasks: [],
            choices: [{ value: 'allow', label: 'Allow', description: '' }, { value: 'deny', label: 'Deny', description: '' }],
          },
        }));
      });

      await expect(page.locator('#decision-banner')).toBeVisible();

      const allowBtn = page.locator('#decision-banner-choices button:has-text("Allow")');
      await allowBtn.first().click();

      await page.waitForTimeout(500);
      await expect(page.locator('#decision-banner')).toBeVisible();
    });

    test('handles network timeout on decision submission', async ({ page }) => {
      await page.goto('/task/test-123');
      await page.waitForSelector('#task-page');

      await page.route('**/tasks/*/decision', async route => {
        route.abort('failed');
      });

      await page.evaluate(() => {
        window.dispatchEvent(new CustomEvent('decomposition_confirmation_required', {
          detail: {
            task_id: 'test-123', task_title: 'Test Task', current_depth: 1, allowed_depth: 3,
            proposed_subtasks: [],
            choices: [{ value: 'allow', label: 'Allow', description: '' }, { value: 'deny', label: 'Deny', description: '' }],
          },
        }));
      });

      await expect(page.locator('#decision-banner')).toBeVisible();

      const allowBtn = page.locator('#decision-banner-choices button:has-text("Allow")');
      await allowBtn.first().click();

      await page.waitForTimeout(1000);
      await expect(page.locator('#task-page')).toBeVisible();
    });
  });

  test.describe('Additional Modal Types', () => {
    test('planning turn limit banner displays', async ({ page }) => {
      await page.goto('/task/test-123');
      await page.waitForSelector('#task-page');

      await page.evaluate(() => {
        window.dispatchEvent(new CustomEvent('planning_turn_limit_reached', {
          detail: {
            task_id: 'test-123', task_title: 'Plan Feature', turns_taken: 10,
            choices: [
              { value: 'extend', label: 'Extend', description: '' },
              { value: 'commit', label: 'Commit', description: '' },
              { value: 'cancel', label: 'Cancel', description: '' },
            ],
          },
        }));
      });

      const banner = page.locator('#decision-banner');
      await expect(banner).toBeVisible({ timeout: 5000 });
      await expect(page.locator('#decision-banner-title')).toContainText(/planning.*turn/i);
      await expect(page.locator('#decision-banner-body')).toContainText(/Plan Feature/i);
      expect(await page.locator('#decision-banner-choices button').count()).toBeGreaterThanOrEqual(3);
    });

    test('merge turn limit banner displays', async ({ page }) => {
      await page.goto('/task/test-123');
      await page.waitForSelector('#task-page');

      await page.evaluate(() => {
        window.dispatchEvent(new CustomEvent('merge_conflict_resolution_turn_limit_reached', {
          detail: {
            task_id: 'test-123', task_title: 'Resolve Conflicts', turns_taken: 5,
            parent_branch: 'main', resolved_so_far: [{ file: 'a.txt', resolution: 'ours' }],
            choices: [
              { value: 'extend', label: 'Extend', description: '' },
              { value: 'abort', label: 'Abort', description: '' },
            ],
          },
        }));
      });

      const banner = page.locator('#decision-banner');
      await expect(banner).toBeVisible({ timeout: 5000 });
      await expect(page.locator('#decision-banner-title')).toContainText(/merge/i);
      await expect(page.locator('#decision-banner-body')).toContainText(/main/i);
      await expect(page.locator('#decision-banner-body')).toContainText(/a.txt/i);
      expect(await page.locator('#decision-banner-choices button').count()).toBeGreaterThanOrEqual(2);
    });

    test('critic turn limit banner displays', async ({ page }) => {
      await page.goto('/task/test-123');
      await page.waitForSelector('#task-page');

      await page.evaluate(() => {
        window.dispatchEvent(new CustomEvent('critic_turn_limit_reached', {
          detail: {
            task_id: 'test-123', task_title: 'Review Code', reviewed_task_id: 'task-001',
            turns_taken: 15, critic_max_turns: 20,
            choices: [
              { value: 'approve_task', label: 'Approve', description: '' },
              { value: 'extend_critic', label: 'Extend', description: '' },
              { value: 'block_task', label: 'Block', description: '' },
            ],
          },
        }));
      });

      const banner = page.locator('#decision-banner');
      await expect(banner).toBeVisible({ timeout: 5000 });
      await expect(page.locator('#decision-banner-title')).toContainText(/critic.*turn/i);
      await expect(page.locator('#decision-banner-body')).toContainText(/Review Code/i);
      await expect(page.locator('#decision-banner-body')).toContainText(/task-001/i);
      expect(await page.locator('#decision-banner-choices button').count()).toBeGreaterThanOrEqual(3);
    });

    test('planning turn limit submit decision', async ({ page }) => {
      await page.goto('/task/test-123');
      await page.waitForSelector('#task-page');

      let captured: any = {};
      await page.route('**/tasks/*/decision', async route => {
        captured = route.request().postDataJSON();
        await route.fulfill({ json: { ok: true } });
      });

      await page.evaluate(() => {
        window.dispatchEvent(new CustomEvent('planning_turn_limit_reached', {
          detail: {
            task_id: 'test-123', task_title: 'Plan', turns_taken: 10,
            choices: [
              { value: 'extend', label: 'Extend', description: '' },
              { value: 'commit', label: 'Commit', description: '' },
              { value: 'cancel', label: 'Cancel', description: '' },
            ],
          },
        }));
      });

      await page.locator('#decision-banner').waitFor({ state: 'visible' });
      await page.locator('#decision-banner-choices button:has-text("Commit")').click();
      await page.waitForTimeout(500);
      expect(captured.choice).toBe('commit');
      expect(captured.decision_type).toBe('planning_turn_limit_reached');
    });

    test('merge turn limit submit decision', async ({ page }) => {
      await page.goto('/task/test-123');
      await page.waitForSelector('#task-page');

      let captured: any = {};
      await page.route('**/tasks/*/decision', async route => {
        captured = route.request().postDataJSON();
        await route.fulfill({ json: { ok: true } });
      });

      await page.evaluate(() => {
        window.dispatchEvent(new CustomEvent('merge_conflict_resolution_turn_limit_reached', {
          detail: {
            task_id: 'test-123', task_title: 'Merge', turns_taken: 5, parent_branch: 'main',
            resolved_so_far: [],
            choices: [
              { value: 'extend', label: 'Extend', description: '' },
              { value: 'abort', label: 'Abort', description: '' },
            ],
          },
        }));
      });

      await page.locator('#decision-banner').waitFor({ state: 'visible' });
      await page.locator('#decision-banner-choices button:has-text("Abort")').click();
      await page.waitForTimeout(500);
      expect(captured.choice).toBe('abort');
      expect(captured.decision_type).toBe('merge_conflict_resolution_turn_limit_reached');
    });

    test('critic turn limit submit decision', async ({ page }) => {
      await page.goto('/task/test-123');
      await page.waitForSelector('#task-page');

      let captured: any = {};
      await page.route('**/tasks/*/decision', async route => {
        captured = route.request().postDataJSON();
        await route.fulfill({ json: { ok: true } });
      });

      await page.evaluate(() => {
        window.dispatchEvent(new CustomEvent('critic_turn_limit_reached', {
          detail: {
            task_id: 'test-123', task_title: 'Critic', reviewed_task_id: 'r-1',
            turns_taken: 15, critic_max_turns: 20,
            choices: [
              { value: 'approve_task', label: 'Approve', description: '' },
              { value: 'extend_critic', label: 'Extend', description: '' },
              { value: 'block_task', label: 'Block', description: '' },
            ],
          },
        }));
      });

      await page.locator('#decision-banner').waitFor({ state: 'visible' });
      await page.locator('#decision-banner-choices button:has-text("Approve")').click();
      await page.waitForTimeout(500);
      expect(captured.choice).toBe('approve_task');
      expect(captured.decision_type).toBe('critic_turn_limit_reached');
    });
  });
});
