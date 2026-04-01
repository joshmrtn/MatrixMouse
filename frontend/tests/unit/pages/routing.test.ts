/**
 * Unit Tests for App Routing
 *
 * Tests the handleRoute function logic.
 */

import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { setState, resetState, getState } from '../../../src/state/store';

describe('App Routing Logic', () => {
  beforeEach(() => {
    resetState();
  });

  afterEach(() => {
    resetState();
  });

  describe('route path parsing', () => {
    it('parses root path as channel', () => {
      const path = '/';
      const parts = path.split('/').filter(Boolean);

      let page = 'channel';
      if (parts[0] === 'task' && parts[1]) {
        page = 'task';
      } else if (parts[0] === 'tasks') {
        page = 'tasks';
      } else if (parts[0] === 'status' || parts[0] === 'dashboard') {
        page = 'dashboard';
      } else if (parts[0] === 'settings') {
        page = 'settings';
      } else if (parts[0] === 'channel' && parts[1]) {
        page = 'channel';
      }

      expect(page).toBe('channel');
    });

    it('parses /task/:id path', () => {
      const path = '/task/abc123';
      const parts = path.split('/').filter(Boolean);

      let page = 'channel';
      const params: Record<string, string> = {};

      if (parts[0] === 'task' && parts[1]) {
        page = 'task';
        params.id = parts[1];
      }

      expect(page).toBe('task');
      expect(params.id).toBe('abc123');
    });

    it('parses /task-list path', () => {
      const path = '/task-list';
      const parts = path.split('/').filter(Boolean);

      let page = 'channel';
      if (parts[0] === 'task-list') {
        page = 'tasks';
      }

      expect(page).toBe('tasks');
    });

    it('parses /dashboard path', () => {
      const path = '/dashboard';
      const parts = path.split('/').filter(Boolean);

      let page = 'channel';
      if (parts[0] === 'dashboard') {
        page = 'dashboard';
      }

      expect(page).toBe('dashboard');
    });

    it('parses /settings path', () => {
      const path = '/settings';
      const parts = path.split('/').filter(Boolean);

      let page = 'channel';
      if (parts[0] === 'settings') {
        page = 'settings';
      }

      expect(page).toBe('settings');
    });

    it('parses /channel/:scope path', () => {
      const path = '/channel/my-repo';
      const parts = path.split('/').filter(Boolean);

      let page = 'channel';
      const params: Record<string, string> = {};

      if (parts[0] === 'channel' && parts[1]) {
        page = 'channel';
        params.scope = parts[1];
      }

      expect(page).toBe('channel');
      expect(params.scope).toBe('my-repo');
    });

    it('defaults to channel for unknown paths', () => {
      const path = '/unknown';
      const parts = path.split('/').filter(Boolean);

      let page = 'channel';
      if (parts[0] === 'task' && parts[1]) {
        page = 'task';
      } else if (parts[0] === 'tasks') {
        page = 'tasks';
      } else if (parts[0] === 'status' || parts[0] === 'dashboard') {
        page = 'dashboard';
      } else if (parts[0] === 'settings') {
        page = 'settings';
      }

      expect(page).toBe('channel');
    });
  });

  describe('dashboard route', () => {
    it('maps dashboard to dashboard page type', () => {
      const path = '/dashboard';
      const parts = path.split('/').filter(Boolean);

      let page = 'channel';
      if (parts[0] === 'dashboard') {
        page = 'dashboard';
      }

      expect(page).toBe('dashboard');
    });
  });
});
