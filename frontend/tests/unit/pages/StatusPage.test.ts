/**
 * Unit tests for StatusPage component
 */

import { describe, it, expect, beforeEach, vi } from 'vitest';
import { StatusPage } from '../../../src/pages/StatusPage';
import { setState, resetState } from '../../../src/state/store';
import * as apiClient from '../../../src/api/client';

// Mock the API client
vi.mock('../../../src/api/client', () => ({
  getTaskDependencies: vi.fn(),
}));

describe('StatusPage', () => {
  let page: StatusPage;
  let container: HTMLElement;

  beforeEach(() => {
    resetState();
    page = new StatusPage();
    container = document.createElement('div');
    document.body.appendChild(container);
    vi.clearAllMocks();
  });

  afterEach(() => {
    document.body.removeChild(container);
    container = null as unknown as HTMLElement;
  });

  describe('render', () => {
    it('creates status page element', () => {
      page.render(container);
      const element = container.querySelector('#status-page');
      expect(element).toBeTruthy();
    });

    it('renders page title', () => {
      page.render(container);
      const title = container.querySelector('h1');
      expect(title?.textContent).toBe('Status Dashboard');
    });

    it('renders Blocked by Human section', () => {
      page.render(container);
      const section = container.querySelector('#status-blocked-human');
      expect(section).toBeTruthy();
      expect(section?.querySelector('.status-section-title')?.textContent).toBe('Blocked by Human');
    });

    it('renders Blocked by Dependencies section', () => {
      page.render(container);
      const section = container.querySelector('#status-blocked-deps');
      expect(section).toBeTruthy();
      expect(section?.querySelector('.status-section-title')?.textContent).toBe('Blocked by Dependencies');
    });

    it('renders Waiting section', () => {
      page.render(container);
      const section = container.querySelector('#status-waiting');
      expect(section).toBeTruthy();
      expect(section?.querySelector('.status-section-title')?.textContent).toBe('Waiting');
    });

    it('uses correct unicode icons for sections', () => {
      page.render(container);
      
      const humanIcon = container.querySelector('#status-blocked-human .status-section-icon');
      expect(humanIcon?.textContent).toBe('⦸');
      
      const depsIcon = container.querySelector('#status-blocked-deps .status-section-icon');
      expect(depsIcon?.textContent).toBe('⊞');
      
      const waitingIcon = container.querySelector('#status-waiting .status-section-icon');
      expect(waitingIcon?.textContent).toBe('⋯');
    });
  });

  describe('blocked by human section', () => {
    it('displays blocked tasks from state', () => {
      setState('blockedReport', {
        human: [
          { id: 'task1', title: 'Task 1', blocking_reason: 'Needs human review' },
          { id: 'task2', title: 'Task 2', blocking_reason: 'Awaiting decision' },
        ],
        dependencies: [],
        waiting: [],
      });

      page.render(container);
      const taskLinks = container.querySelectorAll('#status-blocked-human .status-task-link');
      expect(taskLinks.length).toBe(2);
    });

    it('displays task titles in blocked section', () => {
      setState('blockedReport', {
        human: [
          { id: 'task1', title: 'Implement feature X', blocking_reason: 'Needs review' },
        ],
        dependencies: [],
        waiting: [],
      });

      page.render(container);
      const taskLink = container.querySelector('#status-blocked-human .status-task-link');
      expect(taskLink?.textContent).toContain('Implement feature X');
    });

    it('displays blocking reason', () => {
      setState('blockedReport', {
        human: [
          { id: 'task1', title: 'Task 1', blocking_reason: 'Awaiting user input' },
        ],
        dependencies: [],
        waiting: [],
      });

      page.render(container);
      const reasonEl = container.querySelector('#status-blocked-human .status-task-reason');
      expect(reasonEl?.textContent).toBe('Awaiting user input');
    });

    it('shows empty message when no blocked tasks', () => {
      setState('blockedReport', {
        human: [],
        dependencies: [],
        waiting: [],
      });

      page.render(container);
      const emptyMsg = container.querySelector('#status-blocked-human .empty-message');
      expect(emptyMsg).toBeTruthy();
    });

    it('makes task links clickable', () => {
      setState('blockedReport', {
        human: [
          { id: 'abc123', title: 'Task 1', blocking_reason: 'Review needed' },
        ],
        dependencies: [],
        waiting: [],
      });

      page.render(container);
      const taskLink = container.querySelector('#status-blocked-human .status-task-link') as HTMLAnchorElement;
      expect(taskLink?.dataset.taskId).toBe('abc123');
      expect(taskLink?.getAttribute('href')).toBe('/task/abc123');
    });
  });

  describe('blocked by dependencies section', () => {
    it('displays tasks blocked by dependencies', async () => {
      vi.mocked(apiClient.getTaskDependencies).mockResolvedValue({
        task_id: 'task1',
        dependencies: [],
        count: 0,
      });

      setState('blockedReport', {
        human: [],
        dependencies: [
          { id: 'task1', title: 'Task 1', blocking_reason: 'Waiting on: dep1' },
        ],
        waiting: [],
      });

      page.render(container);
      // Wait for async rendering
      await new Promise((resolve) => setTimeout(resolve, 10));

      const taskLinks = container.querySelectorAll('#status-blocked-deps .status-task-link');
      expect(taskLinks.length).toBe(1);
    });

    it('displays blockers list with Waiting on label', async () => {
      vi.mocked(apiClient.getTaskDependencies).mockResolvedValue({
        task_id: 'task1',
        dependencies: [
          { id: 'abc123', title: 'Dependency Task', description: '', repo: [], role: 'coder', status: 'ready', branch: '', parent_task_id: null, depth: 0, importance: 0.5, urgency: 0.5, priority_score: 0.5, preemptable: true, preempt: false, created_at: '2024-01-01T00:00:00Z', last_modified: '2024-01-01T00:00:00Z', context_messages: [], pending_tool_calls: [], decomposition_confirmed_depth: 0, merge_resolution_decisions: [] },
        ],
        count: 1,
      });

      setState('blockedReport', {
        human: [],
        dependencies: [
          { id: 'task1', title: 'Task 1', blocking_reason: 'Waiting on: abc123' },
        ],
        waiting: [],
      });

      page.render(container);
      // Wait for async rendering
      await new Promise((resolve) => setTimeout(resolve, 10));

      const blockersLabel = container.querySelector('#status-blocked-deps .blockers-label');
      expect(blockersLabel?.textContent).toBe('Waiting on:');
    });

    it('displays blocker id and title', async () => {
      vi.mocked(apiClient.getTaskDependencies).mockResolvedValue({
        task_id: 'task1',
        dependencies: [
          { id: 'abc123', title: 'This is a task title', description: '', repo: [], role: 'coder', status: 'ready', branch: '', parent_task_id: null, depth: 0, importance: 0.5, urgency: 0.5, priority_score: 0.5, preemptable: true, preempt: false, created_at: '2024-01-01T00:00:00Z', last_modified: '2024-01-01T00:00:00Z', context_messages: [], pending_tool_calls: [], decomposition_confirmed_depth: 0, merge_resolution_decisions: [] },
        ],
        count: 1,
      });

      setState('blockedReport', {
        human: [],
        dependencies: [
          { id: 'task1', title: 'Task 1', blocking_reason: 'Waiting on: abc123' },
        ],
        waiting: [],
      });

      page.render(container);
      // Wait for async rendering
      await new Promise((resolve) => setTimeout(resolve, 10));

      const blockerLink = container.querySelector('#status-blocked-deps .blockers-list .dependency-link');
      expect(blockerLink).toBeTruthy();
      const text = blockerLink?.textContent?.replace(/\s+/g, ' ').trim();
      expect(text).toContain('abc123');
      expect(text).toContain('This is a task title');
    });

    it('shows empty message when no blocked tasks', () => {
      setState('blockedReport', {
        human: [],
        dependencies: [],
        waiting: [],
      });

      page.render(container);
      const emptyMsg = container.querySelector('#status-blocked-deps .empty-message');
      expect(emptyMsg).toBeTruthy();
    });

    it('makes dependency links clickable', async () => {
      vi.mocked(apiClient.getTaskDependencies).mockResolvedValue({
        task_id: 'task1',
        dependencies: [
          { id: 'dep1', title: 'Dependency', description: '', repo: [], role: 'coder', status: 'ready', branch: '', parent_task_id: null, depth: 0, importance: 0.5, urgency: 0.5, priority_score: 0.5, preemptable: true, preempt: false, created_at: '2024-01-01T00:00:00Z', last_modified: '2024-01-01T00:00:00Z', context_messages: [], pending_tool_calls: [], decomposition_confirmed_depth: 0, merge_resolution_decisions: [] },
        ],
        count: 1,
      });

      setState('blockedReport', {
        human: [],
        dependencies: [
          { id: 'task1', title: 'Task 1', blocking_reason: 'Waiting on: dep1' },
        ],
        waiting: [],
      });

      page.render(container);
      // Wait for async rendering
      await new Promise((resolve) => setTimeout(resolve, 10));

      const depLink = container.querySelector('#status-blocked-deps .blockers-list .dependency-link') as HTMLAnchorElement;
      expect(depLink?.dataset.taskId).toBe('dep1');
      expect(depLink?.getAttribute('href')).toBe('/task/dep1');
    });
  });

  describe('waiting section', () => {
    it('displays waiting tasks', () => {
      setState('blockedReport', {
        human: [],
        dependencies: [],
        waiting: [
          { id: 'task1', title: 'Task 1', blocking_reason: 'Rate limit until 2024-01-01' },
        ],
      });

      page.render(container);
      const taskLinks = container.querySelectorAll('#status-waiting .status-task-link');
      expect(taskLinks.length).toBe(1);
    });

    it('displays wait reason', () => {
      setState('blockedReport', {
        human: [],
        dependencies: [],
        waiting: [
          { id: 'task1', title: 'Task 1', blocking_reason: 'Budget reset in 2 hours' },
        ],
      });

      page.render(container);
      const reasonEl = container.querySelector('#status-waiting .status-task-reason');
      expect(reasonEl?.textContent).toBe('Budget reset in 2 hours');
    });
  });
});
