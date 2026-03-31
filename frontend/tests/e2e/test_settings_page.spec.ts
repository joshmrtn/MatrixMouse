/**
 * E2E Tests for Settings Page
 * 
 * Tests workspace and repo configuration management.
 */

import { test, expect } from '@playwright/test';

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

const mockRepos = [
  { name: 'main-repo', remote: 'https://github.com/test/main.git', local_path: '/test/main', added: '2024-01-01' },
  { name: 'test-repo', remote: 'https://github.com/test/test.git', local_path: '/test/test', added: '2024-01-01' },
];

test.describe('Settings Page', () => {
  test.beforeEach(async ({ page }) => {
    // Setup mock API responses
    await page.route('**/config', async route => {
      if (route.request().method() === 'GET') {
        await route.fulfill({
          status: 200,
          json: mockConfig,
        });
      } else if (route.request().method() === 'PATCH') {
        await route.fulfill({
          status: 200,
          json: { ok: true, updated: ['coder_model'] },
        });
      }
    });

    await page.route('**/repos', async route => {
      await route.fulfill({
        status: 200,
        json: { repos: mockRepos },
      });
    });

    await page.route('**/config/repos/**', async route => {
      if (route.request().method() === 'GET') {
        await route.fulfill({
          status: 200,
          json: {
            local: { coder_model: 'ollama:custom:1b' },
            committed: {},
            merged: { coder_model: 'ollama:custom:1b' },
          },
        });
      } else if (route.request().method() === 'PATCH') {
        await route.fulfill({
          status: 200,
          json: { ok: true, updated: ['coder_model'] },
        });
      }
    });

    await page.route('**/health', async route => {
      await route.fulfill({ status: 200, json: { status: 'ok' } });
    });
  });

  test('loads settings page successfully', async ({ page }) => {
    await page.goto('/settings');
    
    // Check page title
    await expect(page).toHaveTitle(/MatrixMouse/);
    
    // Check page header
    await expect(page.locator('h1')).toContainText('Settings');
  });

  test('displays workspace settings section', async ({ page }) => {
    await page.goto('/settings');
    
    // Check workspace section exists
    await expect(page.locator('#workspace-settings')).toBeVisible();
    await expect(page.locator('#workspace-settings h2')).toContainText('Workspace');
  });

  test('displays model configuration fields', async ({ page }) => {
    await page.goto('/settings');
    
    // Check model fields exist
    await expect(page.locator('label:has-text("Coder Model")')).toBeVisible();
    await expect(page.locator('label:has-text("Manager Model")')).toBeVisible();
    await expect(page.locator('label:has-text("Critic Model")')).toBeVisible();
    await expect(page.locator('label:has-text("Writer Model")')).toBeVisible();
    await expect(page.locator('label:has-text("Summarizer Model")')).toBeVisible();
  });

  test('pre-fills current config values', async ({ page }) => {
    await page.goto('/settings');
    
    // Check values are pre-filled
    const coderModelInput = page.locator('input[name="coder_model"]');
    await expect(coderModelInput).toHaveValue('ollama:qwen3.5:4b');
    
    const managerModelInput = page.locator('input[name="manager_model"]');
    await expect(managerModelInput).toHaveValue('ollama:qwen3.5:9b');
  });

  test('saves workspace config changes', async ({ page }) => {
    await page.goto('/settings');
    
    // Change coder model
    const coderModelInput = page.locator('input[name="coder_model"]');
    await coderModelInput.fill('ollama:new-model:7b');
    
    // Click save
    const saveButton = page.locator('button:has-text("Save")');
    await saveButton.click();
    
    // Should show success message
    await expect(page.locator('.success-message')).toBeVisible();
    await expect(page.locator('.success-message')).toContainText('Settings saved');
  });

  test('displays repo override section', async ({ page }) => {
    await page.goto('/settings');
    
    // Check repo override section exists
    await expect(page.locator('#repo-overrides')).toBeVisible();
    await expect(page.locator('#repo-overrides h2')).toContainText('Repo Overrides');
  });

  test('allows selecting repo for overrides', async ({ page }) => {
    await page.goto('/settings');
    
    // Check repo selector exists
    const repoSelect = page.locator('select[name="repo"]');
    await expect(repoSelect).toBeVisible();
    
    // Check repos are listed
    const options = repoSelect.locator('option');
    await expect(options).toHaveCount(3); // Default + 2 repos
  });

  test('loads repo-specific config when selected', async ({ page }) => {
    await page.goto('/settings');
    
    // Select repo
    const repoSelect = page.locator('select[name="repo"]');
    await repoSelect.selectOption('main-repo');
    
    // Should load repo config
    await expect(page.locator('.repo-config-loaded')).toBeVisible();
  });

  test('saves repo-specific config', async ({ page }) => {
    await page.goto('/settings');
    
    // Select repo
    const repoSelect = page.locator('select[name="repo"]');
    await repoSelect.selectOption('main-repo');
    
    // Change repo-specific model
    const coderModelInput = page.locator('input[name="repo_coder_model"]');
    await coderModelInput.fill('ollama:repo-specific:2b');
    
    // Click save
    const saveButton = page.locator('button:has-text("Save Repo Config")');
    await saveButton.click();
    
    // Should show success message
    await expect(page.locator('.success-message')).toBeVisible();
  });

  test('shows validation errors for invalid values', async ({ page }) => {
    await page.goto('/settings');
    
    // Enter invalid model format
    const coderModelInput = page.locator('input[name="coder_model"]');
    await coderModelInput.fill('invalid-format');
    
    // Click save
    const saveButton = page.locator('button:has-text("Save")');
    await saveButton.click();
    
    // Should show error
    await expect(page.locator('.error-message')).toBeVisible();
  });

  test('cancel button discards changes', async ({ page }) => {
    await page.goto('/settings');
    
    // Change value
    const coderModelInput = page.locator('input[name="coder_model"]');
    const originalValue = await coderModelInput.inputValue();
    await coderModelInput.fill('ollama:changed:1b');
    
    // Click cancel
    const cancelButton = page.locator('button:has-text("Cancel")');
    await cancelButton.click();
    
    // Value should be reset
    await expect(coderModelInput).toHaveValue(originalValue);
  });

  test('displays current config values in readable format', async ({ page }) => {
    await page.goto('/settings');
    
    // Check config is displayed in a readable table/list
    const configList = page.locator('.config-list');
    await expect(configList).toBeVisible();
    
    // Should show key-value pairs
    await expect(page.locator('.config-item:has-text("coder_model")')).toBeVisible();
    await expect(page.locator('.config-item:has-text("ollama:qwen3.5:4b")')).toBeVisible();
  });
});

test.describe('Settings Page - Mobile', () => {
  test.beforeEach(async ({ page }) => {
    await page.route('**/config', async route => {
      await route.fulfill({ status: 200, json: mockConfig });
    });

    await page.route('**/repos', async route => {
      await route.fulfill({ status: 200, json: { repos: mockRepos } });
    });
  });

  test('displays correctly on mobile viewport', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 667 });
    await page.goto('/settings');
    
    // Check page is visible
    await expect(page.locator('h1')).toBeVisible();
    
    // Check form fields are accessible
    await expect(page.locator('input[name="coder_model"]')).toBeVisible();
    
    // No horizontal scroll
    const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
    const clientWidth = await page.evaluate(() => document.documentElement.clientWidth);
    expect(scrollWidth).toBeLessThanOrEqual(clientWidth);
  });

  test('form fields are touch-friendly on mobile', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 667 });
    await page.goto('/settings');
    
    // Check input fields have adequate size for touch
    const inputs = page.locator('input[type="text"]');
    const firstInput = inputs.first();
    
    const boundingBox = await firstInput.boundingBox();
    expect(boundingBox).toBeTruthy();
    expect(boundingBox!.height).toBeGreaterThanOrEqual(40); // Minimum touch target
  });
});
