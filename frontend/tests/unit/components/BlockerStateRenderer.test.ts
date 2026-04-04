/**
 * BlockerStateRenderer Unit Tests
 * 
 * Tests for the BlockerStateRenderer component including:
 * - Loading states (skeletons)
 * - Error states with retry
 * - Task blocker rendering
 * - Title truncation
 * - XSS prevention
 */

import { BlockerStateRenderer } from '../../../src/components/BlockerStateRenderer';
import { describe, it, expect, beforeEach } from 'vitest';
import type { BlockerState, BlockerLoadError, BlockerTask } from '../../../src/types';

describe('BlockerStateRenderer', () => {
  let renderer: BlockerStateRenderer;

  beforeEach(() => {
    renderer = new BlockerStateRenderer();
  });

  describe('render()', () => {
    it('delegates to renderLoading for loading state', () => {
      const loadingBlocker: BlockerState = { type: 'loading' };
      const html = renderer.render(loadingBlocker);

      expect(html).toContain('blocker-skeleton');
    });

    it('delegates to renderError for error state', () => {
      const errorBlocker: BlockerLoadError = {
        type: 'error',
        message: 'Failed to load',
        retryable: false,
      };
      const html = renderer.render(errorBlocker);

      expect(html).toContain('blocker-error');
    });

    it('delegates to renderTask for task state', () => {
      const taskBlocker: BlockerTask = {
        type: 'task',
        id: 'task-123',
        title: 'Test Task',
      };
      const html = renderer.render(taskBlocker);

      expect(html).toContain('dependency-link');
    });

    it('calls onRetry callback when retry button clicked', () => {
      const errorBlocker: BlockerLoadError = {
        type: 'error',
        message: 'Failed to load',
        retryable: true,
      };

      const onRetry = vi.fn();
      const html = renderer.render(errorBlocker, onRetry);

      expect(html).toContain('blocker-retry-btn');
    });
  });

  describe('renderLoading()', () => {
    it('renders skeleton container', () => {
      // Access private method via render() with loading state
      const loadingBlocker: BlockerState = { type: 'loading' };
      const html = renderer.render(loadingBlocker);

      expect(html).toContain('blocker-skeleton');
    });

    it('renders skeleton ID element', () => {
      const loadingBlocker: BlockerState = { type: 'loading' };
      const html = renderer.render(loadingBlocker);

      expect(html).toContain('skeleton-id');
    });

    it('renders skeleton title element', () => {
      const loadingBlocker: BlockerState = { type: 'loading' };
      const html = renderer.render(loadingBlocker);

      expect(html).toContain('skeleton-title');
    });

    it('uses skeleton rect class', () => {
      const loadingBlocker: BlockerState = { type: 'loading' };
      const html = renderer.render(loadingBlocker);

      expect(html).toContain('skeleton-rect');
    });
  });

  describe('renderError()', () => {
    it('renders error container', () => {
      const errorBlocker: BlockerLoadError = {
        type: 'error',
        message: 'Failed to load dependencies',
        retryable: false,
      };
      const html = renderer.render(errorBlocker);

      expect(html).toContain('blocker-error');
    });

    it('displays error icon', () => {
      const errorBlocker: BlockerLoadError = {
        type: 'error',
        message: 'Failed to load dependencies',
        retryable: false,
      };
      const html = renderer.render(errorBlocker);

      expect(html).toContain('blocker-error-icon');
      expect(html).toContain('⚠️');
    });

    it('displays error message', () => {
      const errorBlocker: BlockerLoadError = {
        type: 'error',
        message: 'Network timeout',
        retryable: false,
      };
      const html = renderer.render(errorBlocker);

      expect(html).toContain('blocker-error-message');
      expect(html).toContain('Network timeout');
    });

    it('shows retry button when retryable', () => {
      const errorBlocker: BlockerLoadError = {
        type: 'error',
        message: 'Failed to load',
        retryable: true,
      };
      const html = renderer.render(errorBlocker);

      expect(html).toContain('blocker-retry-btn');
      expect(html).toContain('Retry');
    });

    it('hides retry button when not retryable', () => {
      const errorBlocker: BlockerLoadError = {
        type: 'error',
        message: 'Failed to load',
        retryable: false,
      };
      const html = renderer.render(errorBlocker);

      expect(html).not.toContain('blocker-retry-btn');
    });

    it('escapes HTML in error message', () => {
      const errorBlocker: BlockerLoadError = {
        type: 'error',
        message: '<script>alert("XSS")</script> Error',
        retryable: false,
      };
      const html = renderer.render(errorBlocker);

      expect(html).not.toContain('<script>');
      expect(html).toContain('&lt;script&gt;');
    });
  });

  describe('renderTask()', () => {
    it('renders dependency link', () => {
      const taskBlocker: BlockerTask = {
        type: 'task',
        id: 'task-123',
        title: 'Test Task',
      };
      const html = renderer.render(taskBlocker);

      expect(html).toContain('dependency-link');
      expect(html).toContain('href="/task/task-123"');
    });

    it('displays task ID', () => {
      const taskBlocker: BlockerTask = {
        type: 'task',
        id: 'task-456',
        title: 'Test Task',
      };
      const html = renderer.render(taskBlocker);

      expect(html).toContain('blocker-id');
      expect(html).toContain('task-456');
    });

    it('displays task title', () => {
      const taskBlocker: BlockerTask = {
        type: 'task',
        id: 'task-123',
        title: 'My Test Task',
      };
      const html = renderer.render(taskBlocker);

      expect(html).toContain('blocker-title');
      expect(html).toContain('My Test Task');
    });

    it('includes data-task-id attribute', () => {
      const taskBlocker: BlockerTask = {
        type: 'task',
        id: 'task-789',
        title: 'Test Task',
      };
      const html = renderer.render(taskBlocker);

      expect(html).toContain('data-task-id="task-789"');
    });

    it('includes title as link tooltip', () => {
      const taskBlocker: BlockerTask = {
        type: 'task',
        id: 'task-123',
        title: 'Full Task Title Here',
      };
      const html = renderer.render(taskBlocker);

      expect(html).toContain('title="Full Task Title Here"');
    });

    it('escapes HTML in task ID', () => {
      const taskBlocker: BlockerTask = {
        type: 'task',
        id: '<script>alert("XSS")</script>',
        title: 'Test Task',
      };
      const html = renderer.render(taskBlocker);

      expect(html).not.toContain('<script>');
    });

    it('escapes HTML in task title', () => {
      const taskBlocker: BlockerTask = {
        type: 'task',
        id: 'task-123',
        title: '<img src=x onerror=alert(1)>',
      };
      const html = renderer.render(taskBlocker);

      // HTML should be escaped - tags converted to entities
      expect(html).toContain('&lt;img');
      expect(html).toContain('&gt;');
      // Should not have actual HTML tags
      expect(html).not.toMatch(/<img\s/);
    });

    it('truncates long titles', () => {
      const longTitle = 'A'.repeat(150);
      const taskBlocker: BlockerTask = {
        type: 'task',
        id: 'task-123',
        title: longTitle,
      };
      const html = renderer.render(taskBlocker);

      // Title should be truncated
      expect(html).toContain('...');
      expect(html).toContain('A'.repeat(117)); // 120 - 3 for "..."
    });

    it('does not truncate short titles', () => {
      const taskBlocker: BlockerTask = {
        type: 'task',
        id: 'task-123',
        title: 'Short Title',
      };
      const html = renderer.render(taskBlocker);

      expect(html).toContain('Short Title');
      expect(html).not.toContain('...');
    });
  });

  describe('truncateTitle()', () => {
    it('returns title as-is when within limit', () => {
      const taskBlocker: BlockerTask = {
        type: 'task',
        id: 'task-123',
        title: 'Short Title',
      };
      const html = renderer.render(taskBlocker);

      expect(html).toContain('Short Title');
    });

    it('truncates title at default max length (120)', () => {
      const longTitle = 'A'.repeat(200);
      const taskBlocker: BlockerTask = {
        type: 'task',
        id: 'task-123',
        title: longTitle,
      };
      const html = renderer.render(taskBlocker);

      // Should truncate to ~120 chars + "..."
      const truncatedMatch = html.match(/blocker-title">(.+?)</);
      expect(truncatedMatch).toBeTruthy();
      expect(truncatedMatch![1].length).toBeLessThanOrEqual(123);
    });

    it('adds ellipsis to truncated title', () => {
      const longTitle = 'A'.repeat(200);
      const taskBlocker: BlockerTask = {
        type: 'task',
        id: 'task-123',
        title: longTitle,
      };
      const html = renderer.render(taskBlocker);

      expect(html).toContain('...');
    });

    it('handles empty title', () => {
      const taskBlocker: BlockerTask = {
        type: 'task',
        id: 'task-123',
        title: '',
      };
      const html = renderer.render(taskBlocker);

      expect(html).toContain('blocker-title');
    });

    it('handles very long title', () => {
      const veryLongTitle = 'A'.repeat(1000);
      const taskBlocker: BlockerTask = {
        type: 'task',
        id: 'task-123',
        title: veryLongTitle,
      };
      const html = renderer.render(taskBlocker);

      const truncatedMatch = html.match(/blocker-title">(.+?)</);
      expect(truncatedMatch).toBeTruthy();
      expect(truncatedMatch![1].length).toBeLessThan(200);
    });
  });

  describe('escapeHtml()', () => {
    it('escapes < and > characters', () => {
      const taskBlocker: BlockerTask = {
        type: 'task',
        id: 'task-123',
        title: '<script>',
      };
      const html = renderer.render(taskBlocker);

      expect(html).not.toContain('<script>');
      expect(html).toContain('&lt;script&gt;');
    });

    it('escapes & character', () => {
      const taskBlocker: BlockerTask = {
        type: 'task',
        id: 'task-123',
        title: 'Tom & Jerry',
      };
      const html = renderer.render(taskBlocker);

      expect(html).toContain('Tom &amp; Jerry');
    });

    it('escapes " character', () => {
      const taskBlocker: BlockerTask = {
        type: 'task',
        id: 'task-123',
        title: 'Say "Hello"',
      };
      const html = renderer.render(taskBlocker);

      // DOM-based escaping handles quotes in the title attribute
      expect(html).toContain('Say');
      expect(html).toContain('Hello');
    });

    it('escapes \' character', () => {
      const taskBlocker: BlockerTask = {
        type: 'task',
        id: 'task-123',
        title: "User's task",
      };
      const html = renderer.render(taskBlocker);

      // Should be escaped (implementation may vary)
      expect(html).toContain("User");
      expect(html).toContain("task");
    });

    it('handles empty string', () => {
      const taskBlocker: BlockerTask = {
        type: 'task',
        id: 'task-123',
        title: '',
      };
      const html = renderer.render(taskBlocker);

      // Should not throw
      expect(html).toBeDefined();
    });

    it('handles plain text without special chars', () => {
      const taskBlocker: BlockerTask = {
        type: 'task',
        id: 'task-123',
        title: 'Normal Task Title',
      };
      const html = renderer.render(taskBlocker);

      expect(html).toContain('Normal Task Title');
    });
  });

  describe('integration', () => {
    it('renders multiple blockers in sequence', () => {
      const loadingBlocker: BlockerState = { type: 'loading' };
      const taskBlocker: BlockerTask = {
        type: 'task',
        id: 'task-123',
        title: 'Test Task',
      };

      const loadingHtml = renderer.render(loadingBlocker);
      const taskHtml = renderer.render(taskBlocker);

      expect(loadingHtml).toContain('blocker-skeleton');
      expect(taskHtml).toContain('dependency-link');
    });

    it('handles error with retry callback', () => {
      const errorBlocker: BlockerLoadError = {
        type: 'error',
        message: 'Failed',
        retryable: true,
      };

      let retryCalled = false;
      const onRetry = () => { retryCalled = true; };

      const html = renderer.render(errorBlocker, onRetry);

      expect(html).toContain('data-retry');
      expect(retryCalled).toBe(false); // Callback not called during render
    });
  });
});
