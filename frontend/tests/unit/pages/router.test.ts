/**
 * Unit Tests for Pages Router
 *
 * Tests the renderRouter function that maps routes to pages.
 */

import { describe, it, expect, beforeEach, vi } from 'vitest';
import { renderRouter } from '../../../src/pages';
import { ChannelPage } from '../../../src/pages/ChannelPage';
import { TaskPage } from '../../../src/pages/TaskPage';
import { TasksPage } from '../../../src/pages/TasksPage';
import { StatusPage } from '../../../src/pages/StatusPage';
import { SettingsPage } from '../../../src/pages/SettingsPage';

// Mock page classes
vi.mock('../../../src/pages/ChannelPage');
vi.mock('../../../src/pages/TaskPage');
vi.mock('../../../src/pages/TasksPage');
vi.mock('../../../src/pages/StatusPage');
vi.mock('../../../src/pages/SettingsPage');

describe('Pages Router', () => {
  let container: HTMLElement;

  beforeEach(() => {
    container = document.createElement('div');
    vi.clearAllMocks();
  });

  describe('route mapping', () => {
    it('renders ChannelPage for channel route', () => {
      renderRouter('channel', { scope: 'workspace' }, container);
      expect(ChannelPage).toHaveBeenCalledWith('workspace');
    });

    it('renders ChannelPage for workspace scope', () => {
      renderRouter('channel', { scope: 'workspace' }, container);
      const mockInstance = vi.mocked(ChannelPage).mock.results[0].value;
      expect(mockInstance.render).toHaveBeenCalledWith(container);
    });

    it('renders TaskPage for task route', () => {
      renderRouter('task', { id: 'abc123' }, container);
      expect(TaskPage).toHaveBeenCalledWith('abc123');
    });

    it('does not render TaskPage if id is missing', () => {
      renderRouter('task', {}, container);
      expect(TaskPage).not.toHaveBeenCalled();
    });

    it('renders TasksPage for tasks route', () => {
      renderRouter('tasks', {}, container);
      expect(TasksPage).toHaveBeenCalled();
      const mockInstance = vi.mocked(TasksPage).mock.results[0].value;
      expect(mockInstance.render).toHaveBeenCalledWith(container);
    });

    it('renders StatusPage for dashboard route', () => {
      renderRouter('dashboard', {}, container);
      expect(StatusPage).toHaveBeenCalled();
      const mockInstance = vi.mocked(StatusPage).mock.results[0].value;
      expect(mockInstance.render).toHaveBeenCalledWith(container);
    });

    it('does not render StatusPage for status route (deprecated)', () => {
      // /status route was removed - should fall through to default (channel)
      renderRouter('status', {}, container);
      expect(StatusPage).not.toHaveBeenCalled();
      expect(ChannelPage).toHaveBeenCalledWith('workspace');
    });

    it('renders SettingsPage for settings route', () => {
      renderRouter('settings', {}, container);
      expect(SettingsPage).toHaveBeenCalled();
      const mockInstance = vi.mocked(SettingsPage).mock.results[0].value;
      expect(mockInstance.render).toHaveBeenCalledWith(container);
    });

    it('renders ChannelPage as default for unknown routes', () => {
      renderRouter('unknown', {}, container);
      expect(ChannelPage).toHaveBeenCalledWith('workspace');
    });

    it('renders ChannelPage for empty page', () => {
      renderRouter('', {}, container);
      expect(ChannelPage).toHaveBeenCalledWith('workspace');
    });

    it('clears container before rendering', () => {
      container.innerHTML = '<div>existing content</div>';
      renderRouter('tasks', {}, container);
      expect(container.innerHTML).not.toContain('existing content');
    });
  });

  describe('route parameters', () => {
    it('passes scope parameter to ChannelPage', () => {
      renderRouter('channel', { scope: 'my-repo' }, container);
      expect(ChannelPage).toHaveBeenCalledWith('my-repo');
    });

    it('passes task id to TaskPage', () => {
      renderRouter('task', { id: 'task123' }, container);
      expect(TaskPage).toHaveBeenCalledWith('task123');
    });

    it('handles multiple parameters', () => {
      renderRouter('channel', { scope: 'repo1', extra: 'value' }, container);
      expect(ChannelPage).toHaveBeenCalledWith('repo1');
    });
  });

  describe('dashboard route', () => {
    it('renders StatusPage for dashboard route', () => {
      renderRouter('dashboard', {}, container);
      expect(StatusPage).toHaveBeenCalledTimes(1);

      const allCalls = vi.mocked(StatusPage).mock.results;
      expect(allCalls[0].value.render).toHaveBeenCalled();
    });

    it('does not have status route alias', () => {
      // Verify status route is not mapped
      renderRouter('status', {}, container);
      expect(StatusPage).not.toHaveBeenCalled();
    });
  });
});
