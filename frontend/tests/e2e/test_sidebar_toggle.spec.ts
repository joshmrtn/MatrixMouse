/**
 * E2E Tests for Sidebar Toggle Functionality
 * 
 * Tests the sidebar toggle button behavior on both mobile and desktop.
 * Uses Playwright to verify actual visual rendering and behavior.
 */

import { test, expect } from '@playwright/test';

test.describe('Sidebar Toggle', () => {
  test.beforeEach(async ({ page }) => {
    // Mock the API endpoints
    await page.route('**/repos', async route => {
      await route.fulfill({ json: { repos: [] } });
    });
    await page.route('**/tasks**', async route => {
      await route.fulfill({ json: { tasks: [], count: 0 } });
    });
    await page.route('**/status', async route => {
      await route.fulfill({ json: { idle: true, stopped: false, blocked: false } });
    });
    await page.route('**/blocked', async route => {
      await route.fulfill({ json: { report: { human: [], dependencies: [], waiting: [] } } });
    });
  });

  test.describe('Desktop (1280px)', () => {
    test.use({ viewport: { width: 1280, height: 720 } });

    test('sidebar toggle button is visible on page load', async ({ page }) => {
      await page.goto('/');
      await page.waitForSelector('#sidebar-toggle');
      
      const toggleBtn = page.locator('#sidebar-toggle');
      await expect(toggleBtn).toBeVisible();
    });

    test('sidebar toggle button points left when sidebar is expanded', async ({ page }) => {
      await page.goto('/');
      await page.waitForSelector('#sidebar-toggle');
      
      const toggleBtn = page.locator('#sidebar-toggle span');
      const text = await toggleBtn.textContent();
      expect(text?.trim()).toBe('«');
    });

    test('clicking toggle button collapses sidebar and changes arrow', async ({ page }) => {
      await page.goto('/');
      await page.waitForSelector('#sidebar-toggle');
      
      // Click toggle
      await page.click('#sidebar-toggle');
      await page.waitForTimeout(100);
      
      // Sidebar should be collapsed
      const sidebar = page.locator('#sidebar');
      await expect(sidebar).toHaveClass(/collapsed/);
      
      // Arrow should point right
      const toggleBtn = page.locator('#sidebar-toggle span');
      const text = await toggleBtn.textContent();
      expect(text?.trim()).toBe('»');
    });

    test('clicking toggle button again expands sidebar', async ({ page }) => {
      await page.goto('/');
      await page.waitForSelector('#sidebar-toggle');
      
      // Click twice
      await page.click('#sidebar-toggle');
      await page.waitForTimeout(100);
      await page.click('#sidebar-toggle');
      await page.waitForTimeout(100);
      
      // Sidebar should be expanded
      const sidebar = page.locator('#sidebar');
      await expect(sidebar).not.toHaveClass(/collapsed/);
      
      // Arrow should point left
      const toggleBtn = page.locator('#sidebar-toggle span');
      const text = await toggleBtn.textContent();
      expect(text?.trim()).toBe('«');
    });

    test('toggle button is NOT inside sidebar', async ({ page }) => {
      await page.goto('/');
      await page.waitForSelector('#sidebar-toggle');
      
      // Toggle button should be in header, not in sidebar
      const sidebar = page.locator('#sidebar');
      const toggleInSidebar = sidebar.locator('#sidebar-toggle');
      await expect(toggleInSidebar).toHaveCount(0);
      
      // Toggle button should be in header
      const header = page.locator('#header');
      const toggleInHeader = header.locator('#sidebar-toggle');
      await expect(toggleInHeader).toHaveCount(1);
    });
  });

  test.describe('Mobile (375px)', () => {
    test.use({ viewport: { width: 375, height: 667 } });

    test('sidebar toggle button is visible on page load', async ({ page }) => {
      await page.goto('/');
      await page.waitForSelector('#sidebar-toggle');
      
      const toggleBtn = page.locator('#sidebar-toggle');
      await expect(toggleBtn).toBeVisible();
    });

    test('sidebar toggle button points right when sidebar is collapsed', async ({ page }) => {
      await page.goto('/');
      await page.waitForSelector('#sidebar-toggle');
      
      const toggleBtn = page.locator('#sidebar-toggle span');
      const text = await toggleBtn.textContent();
      expect(text?.trim()).toBe('»');
    });

    test('clicking toggle button expands sidebar and changes arrow', async ({ page }) => {
      await page.goto('/');
      await page.waitForSelector('#sidebar-toggle');
      
      // Click toggle
      await page.click('#sidebar-toggle');
      await page.waitForTimeout(100);
      
      // Sidebar should be expanded
      const sidebar = page.locator('#sidebar');
      await expect(sidebar).not.toHaveClass(/collapsed/);
      
      // Arrow should point left
      const toggleBtn = page.locator('#sidebar-toggle span');
      const text = await toggleBtn.textContent();
      expect(text?.trim()).toBe('«');
    });

    test('clicking toggle button again collapses sidebar', async ({ page }) => {
      await page.goto('/');
      await page.waitForSelector('#sidebar-toggle');
      
      // Click twice
      await page.click('#sidebar-toggle');
      await page.waitForTimeout(100);
      await page.click('#sidebar-toggle');
      await page.waitForTimeout(100);
      
      // Sidebar should be collapsed
      const sidebar = page.locator('#sidebar');
      await expect(sidebar).toHaveClass(/collapsed/);
      
      // Arrow should point right
      const toggleBtn = page.locator('#sidebar-toggle span');
      const text = await toggleBtn.textContent();
      expect(text?.trim()).toBe('»');
    });

    test('toggle button stays visible when sidebar expands', async ({ page }) => {
      await page.goto('/');
      await page.waitForSelector('#sidebar-toggle');

      // Expand sidebar
      await page.click('#sidebar-toggle');
      await page.waitForTimeout(100);

      // Toggle button should still be visible (not covered by sidebar)
      const toggleBtn = page.locator('#sidebar-toggle');
      await expect(toggleBtn).toBeVisible();

      // Toggle button should be clickable (on top)
      await expect(toggleBtn).toBeEnabled();
    });

    test('toggle button is NOT inside sidebar', async ({ page }) => {
      await page.goto('/');
      await page.waitForSelector('#sidebar-toggle');

      // Toggle button should be in header, not in sidebar
      const sidebar = page.locator('#sidebar');
      const toggleInSidebar = sidebar.locator('#sidebar-toggle');
      await expect(toggleInSidebar).toHaveCount(0);

      // Toggle button should be in header
      const header = page.locator('#header');
      const toggleInHeader = header.locator('#sidebar-toggle');
      await expect(toggleInHeader).toHaveCount(1);
    });

    test('header stays on top when sidebar expands', async ({ page }) => {
      await page.goto('/');
      await page.waitForSelector('#sidebar-toggle');

      // Get header z-index
      const header = page.locator('#header');
      const headerZIndex = await header.evaluate(el =>
        window.getComputedStyle(el).zIndex
      );
      expect(headerZIndex).toBe('100');

      // Get sidebar z-index
      const sidebar = page.locator('#sidebar');
      const sidebarZIndex = await sidebar.evaluate(el =>
        window.getComputedStyle(el).zIndex
      );
      expect(parseInt(sidebarZIndex)).toBeLessThan(100);

      // Expand sidebar
      await page.click('#sidebar-toggle');
      await page.waitForTimeout(100);

      // Header should still be on top
      const headerZIndexAfter = await header.evaluate(el =>
        window.getComputedStyle(el).zIndex
      );
      expect(headerZIndexAfter).toBe('100');
    });

    test('can toggle sidebar multiple times on mobile', async ({ page }) => {
      await page.goto('/');
      await page.waitForSelector('#sidebar-toggle');

      // Toggle multiple times
      for (let i = 0; i < 3; i++) {
        await page.click('#sidebar-toggle');
        await page.waitForTimeout(100);

        // Toggle button should still be visible and clickable
        const toggleBtn = page.locator('#sidebar-toggle');
        await expect(toggleBtn).toBeVisible();
        await expect(toggleBtn).toBeEnabled();
      }
    });

    test('toggle button is always on top of sidebar', async ({ page }) => {
      await page.goto('/');
      await page.waitForSelector('#sidebar-toggle');
      
      // Expand sidebar
      await page.click('#sidebar-toggle');
      await page.waitForTimeout(100);
      
      // Toggle button should still be clickable (on top)
      const toggleBtn = page.locator('#sidebar-toggle');
      await toggleBtn.click();
      await page.waitForTimeout(100);
      
      // Sidebar should now be collapsed
      const sidebar = page.locator('#sidebar');
      await expect(sidebar).toHaveClass(/collapsed/);
    });
  });
});
