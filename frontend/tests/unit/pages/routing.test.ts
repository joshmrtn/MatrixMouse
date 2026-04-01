/**
 * Unit Tests for App Routing
 *
 * Tests the renderRouter function to ensure correct page components
 * are rendered for each route.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { renderRouter } from '../../../src/pages';
import { ChannelPage } from '../../../src/pages/ChannelPage';
import { TaskPage } from '../../../src/pages/TaskPage';
import { TasksPage } from '../../../src/pages/TasksPage';
import { StatusPage } from '../../../src/pages/StatusPage';
import { SettingsPage } from '../../../src/pages/SettingsPage';

// Mock page components
vi.mock('../../../src/pages/ChannelPage');
vi.mock('../../../src/pages/TaskPage');
vi.mock('../../../src/pages/TasksPage');
vi.mock('../../../src/pages/StatusPage');
vi.mock('../../../src/pages/SettingsPage');

describe('App Routing', () => {
  let container: HTMLElement;

  beforeEach(() => {
    container = document.createElement('div');
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  describe('route to page mapping', () => {
    it('renders ChannelPage for root path', () => {
      renderRouter('channel', {}, container);

      expect(ChannelPage).toHaveBeenCalledWith('workspace');
      expect(ChannelPage).toHaveBeenCalledTimes(1);
    });

    it('renders ChannelPage for channel route with scope', () => {
      renderRouter('channel', { scope: 'my-repo' }, container);

      expect(ChannelPage).toHaveBeenCalledWith('my-repo');
    });

    it('renders TaskPage for task route with id', () => {
      renderRouter('task', { id: 'abc123' }, container);

      expect(TaskPage).toHaveBeenCalledWith('abc123');
    });

    it('does not render TaskPage when id is missing', () => {
      renderRouter('task', {}, container);

      expect(TaskPage).not.toHaveBeenCalled();
    });

    it('renders TasksPage for tasks route', () => {
      renderRouter('tasks', {}, container);

      expect(TasksPage).toHaveBeenCalled();
    });

    it('renders StatusPage for dashboard route', () => {
      renderRouter('dashboard', {}, container);

      expect(StatusPage).toHaveBeenCalled();
    });

    it('renders SettingsPage for settings route', () => {
      renderRouter('settings', {}, container);

      expect(SettingsPage).toHaveBeenCalled();
    });

    it('renders ChannelPage as default for unknown routes', () => {
      renderRouter('unknown', {}, container);

      expect(ChannelPage).toHaveBeenCalledWith('workspace');
    });

    it('renders ChannelPage for empty page type', () => {
      renderRouter('', {}, container);

      expect(ChannelPage).toHaveBeenCalledWith('workspace');
    });
  });

  describe('container management', () => {
    it('clears container before rendering', () => {
      container.innerHTML = '<div>existing content</div>';

      renderRouter('dashboard', {}, container);

      expect(container.innerHTML).not.toContain('existing content');
    });

    it('renders page component to container', () => {
      const mockRender = vi.fn();
      vi.mocked(StatusPage).mockImplementation(
        () => ({ render: mockRender } as unknown as StatusPage)
      );

      renderRouter('dashboard', {}, container);

      expect(mockRender).toHaveBeenCalledWith(container);
    });
  });

  describe('edge cases', () => {
    it('handles undefined params gracefully', () => {
      expect(() => {
        renderRouter('channel', undefined as unknown as Record<string, string>, container);
      }).not.toThrow();
    });

    it('handles empty params object', () => {
      expect(() => {
        renderRouter('channel', {}, container);
      }).not.toThrow();
    });

    it('handles task route without id parameter', () => {
      // Should not crash, just won't render TaskPage
      expect(() => {
        renderRouter('task', {}, container);
      }).not.toThrow();
    });

    it('handles channel route without scope parameter', () => {
      renderRouter('channel', {}, container);

      expect(ChannelPage).toHaveBeenCalledWith('workspace');
    });
  });

  describe('parameter passing', () => {
    it('passes scope parameter to ChannelPage', () => {
      const testCases = [
        { scope: 'workspace', expected: 'workspace' },
        { scope: 'my-repo', expected: 'my-repo' },
        { scope: 'org/repo', expected: 'org/repo' },
      ];

      testCases.forEach(({ scope, expected }) => {
        vi.clearAllMocks();
        renderRouter('channel', { scope }, container);
        expect(ChannelPage).toHaveBeenCalledWith(expected);
      });
    });

    it('passes task id to TaskPage', () => {
      const testCases = [
        { id: 'abc123' },
        { id: 'task-001' },
        { id: '550e8400-e29b-41d4-a716-446655440000' }, // UUID format
      ];

      testCases.forEach(({ id }) => {
        vi.clearAllMocks();
        renderRouter('task', { id }, container);
        expect(TaskPage).toHaveBeenCalledWith(id);
      });
    });
  });
});
