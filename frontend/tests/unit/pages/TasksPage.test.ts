/**
 * Unit tests for TasksPage component
 */

import { describe, it, expect, beforeEach, vi } from 'vitest';
import { TasksPage } from '../../../src/pages/TasksPage';
import { setState, resetState } from '../../../src/state/store';

describe('TasksPage', () => {
  let page: TasksPage;
  let container: HTMLElement;

  beforeEach(() => {
    resetState();
    page = new TasksPage();
    container = document.createElement('div');
    document.body.appendChild(container);
  });

  afterEach(() => {
    document.body.removeChild(container);
    container = null as unknown as HTMLElement;
  });

  describe('render', () => {
    it('creates tasks page element', () => {
      page.render(container);
      const element = container.querySelector('#tasks-page');
      expect(element).toBeTruthy();
    });

    it('renders page title', () => {
      page.render(container);
      const title = container.querySelector('h1');
      expect(title?.textContent).toBe('Tasks');
    });

    it('renders filters container', () => {
      page.render(container);
      const filters = container.querySelector('#tasks-filters');
      expect(filters).toBeTruthy();
    });

    it('renders task list container', () => {
      page.render(container);
      const taskList = container.querySelector('#tasks-list');
      expect(taskList).toBeTruthy();
    });

    it('renders status filter dropdown', () => {
      page.render(container);
      const filter = container.querySelector('#filter-status') as HTMLSelectElement;
      expect(filter).toBeTruthy();
      expect(filter?.querySelectorAll('option').length).toBeGreaterThan(1);
    });

    it('renders repo filter dropdown', () => {
      setState('repos', [
        { name: 'repo1', remote: 'https://github.com/test/repo1.git', local_path: '/test/repo1', added: '2024-01-01' },
      ]);

      page.render(container);
      const filter = container.querySelector('#filter-repo') as HTMLSelectElement;
      expect(filter).toBeTruthy();
    });

    it('renders add new task button', () => {
      page.render(container);
      const addBtn = container.querySelector('#add-task-btn');
      expect(addBtn).toBeTruthy();
      expect(addBtn?.textContent).toContain('New');
    });
  });

  describe('task list', () => {
    it('displays tasks from state', () => {
      setState('tasks', [
        {
          id: 'task1',
          title: 'Task 1',
          description: '',
          repo: [],
          role: 'coder' as const,
          status: 'ready' as const,
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
          id: 'task2',
          title: 'Task 2',
          description: '',
          repo: [],
          role: 'manager' as const,
          status: 'running' as const,
          branch: 'mm/task2',
          parent_task_id: null,
          depth: 0,
          importance: 0.7,
          urgency: 0.8,
          priority_score: 0.25,
          preemptable: true,
          preempt: false,
          created_at: '2024-01-01T00:00:00Z',
          last_modified: '2024-01-01T00:00:00Z',
          context_messages: [],
          pending_tool_calls: [],
          decomposition_confirmed_depth: 0,
          merge_resolution_decisions: [],
        },
      ]);

      page.render(container);
      const taskItems = container.querySelectorAll('.task-item');
      expect(taskItems.length).toBe(2);
    });

    it('displays task title and ID', () => {
      setState('tasks', [
        {
          id: 'abc123',
          title: 'Implement feature X',
          description: '',
          repo: [],
          role: 'coder' as const,
          status: 'ready' as const,
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
      ]);

      page.render(container);
      const taskItem = container.querySelector('.task-item');
      expect(taskItem?.textContent).toContain('Implement feature X');
      expect(taskItem?.textContent).toContain('abc123');
    });

    it('displays task status', () => {
      setState('tasks', [
        {
          id: 'task1',
          title: 'Task 1',
          description: '',
          repo: [],
          role: 'coder' as const,
          status: 'blocked_by_human' as const,
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
      ]);

      page.render(container);
      const statusEl = container.querySelector('.task-item .task-status');
      expect(statusEl?.textContent).toBe('Blocked By Human');
    });

    it('makes tasks clickable to navigate to task page', () => {
      setState('tasks', [
        {
          id: 'xyz789',
          title: 'Task 1',
          description: '',
          repo: [],
          role: 'coder' as const,
          status: 'ready' as const,
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
      ]);

      page.render(container);
      const taskLink = container.querySelector('.task-item a') as HTMLAnchorElement;
      expect(taskLink?.getAttribute('href')).toBe('/task/xyz789');
    });

    it('shows empty message when no tasks', () => {
      setState('tasks', []);

      page.render(container);
      const emptyMsg = container.querySelector('.empty-message');
      expect(emptyMsg).toBeTruthy();
    });
  });

  describe('filtering', () => {
    it('filters tasks by status', () => {
      setState('tasks', [
        {
          id: 'task1',
          title: 'Task 1',
          description: '',
          repo: [],
          role: 'coder' as const,
          status: 'ready' as const,
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
          id: 'task2',
          title: 'Task 2',
          description: '',
          repo: [],
          role: 'coder' as const,
          status: 'running' as const,
          branch: 'mm/task2',
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
          id: 'task3',
          title: 'Task 3',
          description: '',
          repo: [],
          role: 'coder' as const,
          status: 'complete' as const,
          branch: 'mm/task3',
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
      ]);

      page.render(container);
      const filter = container.querySelector('#filter-status') as HTMLSelectElement;
      
      // Simulate filtering by "running"
      filter.value = 'running';
      filter.dispatchEvent(new Event('change', { bubbles: true }));

      const taskItems = container.querySelectorAll('.task-item');
      expect(taskItems.length).toBe(1);
      expect(taskItems[0].textContent).toContain('Task 2');
    });

    it('filters tasks by repo', () => {
      setState('repos', [
        { name: 'repo1', remote: 'https://github.com/test/repo1.git', local_path: '/test/repo1', added: '2024-01-01' },
        { name: 'repo2', remote: 'https://github.com/test/repo2.git', local_path: '/test/repo2', added: '2024-01-01' },
      ]);
      setState('tasks', [
        {
          id: 'task1',
          title: 'Task 1',
          description: '',
          repo: ['repo1'],
          role: 'coder' as const,
          status: 'ready' as const,
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
          id: 'task2',
          title: 'Task 2',
          description: '',
          repo: ['repo2'],
          role: 'coder' as const,
          status: 'ready' as const,
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
      ]);

      page.render(container);
      const filter = container.querySelector('#filter-repo') as HTMLSelectElement;
      
      // Simulate filtering by "repo1"
      filter.value = 'repo1';
      filter.dispatchEvent(new Event('change', { bubbles: true }));

      const taskItems = container.querySelectorAll('.task-item');
      expect(taskItems.length).toBe(1);
      expect(taskItems[0].textContent).toContain('Task 1');
    });

    it('clears filters when "All" selected', () => {
      setState('tasks', [
        {
          id: 'task1',
          title: 'Task 1',
          description: '',
          repo: [],
          role: 'coder' as const,
          status: 'ready' as const,
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
          id: 'task2',
          title: 'Task 2',
          description: '',
          repo: [],
          role: 'coder' as const,
          status: 'running' as const,
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
      ]);

      page.render(container);
      const statusFilter = container.querySelector('#filter-status') as HTMLSelectElement;
      
      // First filter by "running"
      statusFilter.value = 'running';
      statusFilter.dispatchEvent(new Event('change', { bubbles: true }));
      
      let taskItems = container.querySelectorAll('.task-item');
      expect(taskItems.length).toBe(1);

      // Clear filter
      statusFilter.value = 'all';
      statusFilter.dispatchEvent(new Event('change', { bubbles: true }));

      taskItems = container.querySelectorAll('.task-item');
      expect(taskItems.length).toBe(2);
    });
  });

  describe('add new task', () => {
    it('navigates to add task form when clicked', () => {
      page.render(container);
      const addBtn = container.querySelector('#add-task-btn');
      
      const pushStateSpy = vi.spyOn(window.history, 'pushState');
      const dispatchEventSpy = vi.spyOn(window, 'dispatchEvent');

      addBtn?.dispatchEvent(new MouseEvent('click', { bubbles: true }));

      expect(pushStateSpy).toHaveBeenCalledWith({}, '', '/tasks/new');
      expect(dispatchEventSpy).toHaveBeenCalledWith(expect.any(Event));
    });
  });
});
