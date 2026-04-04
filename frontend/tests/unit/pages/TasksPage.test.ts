/**
 * Unit tests for TasksPage component
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { TasksPage } from '../../../src/pages/TasksPage';
import { setState, resetState, getState } from '../../../src/state/store';
import * as apiClient from '../../../src/api/client';
import type { TasksResponse } from '../../../src/types';

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
    vi.restoreAllMocks();
    window.localStorage.clear();
    vi.useRealTimers();
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

    it('shows empty message when no tasks', async () => {
      setState('tasks', []);
      
      // Mock getTasks to return empty array
      vi.spyOn(apiClient, 'getTasks').mockResolvedValue({ tasks: [], count: 0 });

      page.render(container);
      
      // Wait for async loadTasks to complete
      await vi.dynamicImportSettled();

      const emptyMsg = container.querySelector('.empty-message');
      expect(emptyMsg).toBeTruthy();
      expect(emptyMsg?.textContent).toContain('No tasks');
    });
  });

  describe('filtering', () => {
    beforeEach(() => {
      // Mock getTasks to prevent API calls during filtering tests
      vi.spyOn(apiClient, 'getTasks').mockResolvedValue({ tasks: [], count: 0 });
      // Reset state to ensure clean slate
      resetState();
      page = new TasksPage();
    });

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
    it('navigates to add task form when clicked', async () => {
      page = new TasksPage();
      page.render(container);

      const addBtn = container.querySelector('#add-task-btn');

      const pushStateSpy = vi.spyOn(window.history, 'pushState');
      const dispatchEventSpy = vi.spyOn(window, 'dispatchEvent');

      addBtn?.dispatchEvent(new MouseEvent('click', { bubbles: true }));

      expect(pushStateSpy).toHaveBeenCalledWith({}, '', '/task-new');
      expect(dispatchEventSpy).toHaveBeenCalledWith(expect.any(Event));

      pushStateSpy.mockRestore();
      dispatchEventSpy.mockRestore();
    });
  });

  describe('loading state', () => {
    it('shows loading skeletons when tasks not loaded', () => {
      setState('tasks', []);
      page.render(container);

      const skeletons = container.querySelectorAll('.task-skeleton');
      expect(skeletons.length).toBeGreaterThan(0);
    });

    it('hides loading skeletons when tasks arrive', () => {
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
      ]);

      page.render(container);
      const skeletons = container.querySelectorAll('.task-skeleton');
      const taskItems = container.querySelectorAll('.task-item');
      expect(skeletons.length).toBe(0);
      expect(taskItems.length).toBe(1);
    });
  });

  describe('error state', () => {
    it('shows error message when API fails', async () => {
      // Mock must be set up BEFORE render, since render() calls loadTasks()
      const mockFn = vi.spyOn(apiClient, 'getTasks').mockRejectedValue(new Error('Network error'));

      page.render(container);

      // Use setTimeout to allow the async loadTasks to complete
      await new Promise(resolve => setTimeout(resolve, 50));

      const errorMsg = container.querySelector('.error-message');
      expect(errorMsg).toBeTruthy();
      expect(errorMsg?.textContent).toContain('Failed to load tasks');
      
      mockFn.mockRestore();
    });

    it('error message includes retry button', async () => {
      const mockFn = vi.spyOn(apiClient, 'getTasks').mockRejectedValue(new Error('Network error'));

      page.render(container);
      await new Promise(resolve => setTimeout(resolve, 50));

      const retryBtn = container.querySelector('.retry-btn');
      expect(retryBtn).toBeTruthy();
      expect(retryBtn?.textContent).toContain('Retry');
      
      mockFn.mockRestore();
    });

    it('retry button re-fetches tasks', async () => {
      const mockTasks: TasksResponse = {
        tasks: [
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
        ],
        count: 1,
      };

      // First call fails, second call (retry) succeeds
      const mockFn = vi.spyOn(apiClient, 'getTasks')
        .mockRejectedValueOnce(new Error('Network error'))
        .mockResolvedValueOnce(mockTasks);

      page.render(container);
      
      // Wait for first (failed) load
      await new Promise(resolve => setTimeout(resolve, 50));

      // Verify error state
      const errorMsg = container.querySelector('.error-message');
      expect(errorMsg).toBeTruthy();

      // Click retry
      const retryBtn = container.querySelector('.retry-btn');
      expect(retryBtn).toBeTruthy();
      retryBtn?.dispatchEvent(new MouseEvent('click', { bubbles: true }));

      // Wait for retry to complete
      await new Promise(resolve => setTimeout(resolve, 50));

      // Should show task now
      const taskItems = container.querySelectorAll('.task-item');
      expect(taskItems.length).toBe(1);
      expect(taskItems[0].textContent).toContain('Task 1');
      
      mockFn.mockRestore();
    });

    it('destroy() cleans up loading state', () => {
      page.render(container);
      page.destroy();

      // After destroy, no errors should occur if async operations complete
      // This tests that the component properly cleans up timers/refs
      expect(() => page.destroy()).not.toThrow();
    });
  });

  describe('search functionality', () => {
    beforeEach(() => {
      vi.spyOn(apiClient, 'getTasks').mockResolvedValue({ tasks: [], count: 0 });
      vi.useFakeTimers();
    });

    it('renders search input', () => {
      setState('tasks', []);
      page.render(container);

      const searchInput = container.querySelector('#task-search');
      expect(searchInput).toBeTruthy();
      expect(searchInput?.getAttribute('placeholder')).toBe('Search tasks...');
    });

    it('filters tasks by title', async () => {
      setState('tasks', [
        {
          id: 'task1',
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
        {
          id: 'task2',
          title: 'Fix bug Y',
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
      const searchInput = container.querySelector('#task-search') as HTMLInputElement;

      // Type in search input
      searchInput.value = 'feature';
      searchInput.dispatchEvent(new Event('input', { bubbles: true }));

      // Advance timers past debounce (150ms)
      await vi.advanceTimersByTimeAsync(200);

      const taskItems = container.querySelectorAll('.task-item');
      expect(taskItems.length).toBe(1);
      expect(taskItems[0].textContent).toContain('Implement feature X');
    });

    it('filters tasks by ID', async () => {
      setState('tasks', [
        {
          id: 'abc123',
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
          id: 'xyz789',
          title: 'Task 2',
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
      const searchInput = container.querySelector('#task-search') as HTMLInputElement;

      searchInput.value = 'xyz789';
      searchInput.dispatchEvent(new Event('input', { bubbles: true }));

      await vi.advanceTimersByTimeAsync(200);

      const taskItems = container.querySelectorAll('.task-item');
      expect(taskItems.length).toBe(1);
      expect(taskItems[0].textContent).toContain('xyz789');
    });

    it('search is case-insensitive', async () => {
      setState('tasks', [
        {
          id: 'task1',
          title: 'Implement Feature X',
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
      const searchInput = container.querySelector('#task-search') as HTMLInputElement;

      searchInput.value = 'feature';  // lowercase
      searchInput.dispatchEvent(new Event('input', { bubbles: true }));

      await vi.advanceTimersByTimeAsync(200);

      const taskItems = container.querySelectorAll('.task-item');
      expect(taskItems.length).toBe(1);
    });

    it('clear button appears when search has text', () => {
      setState('tasks', []);
      page.render(container);

      const searchInput = container.querySelector('#task-search') as HTMLInputElement;
      const clearBtn = container.querySelector('#task-search-clear');

      // Clear button should be hidden initially
      expect(clearBtn?.classList.contains('hidden')).toBe(true);

      // Type in search (no debounce needed for UI update)
      searchInput.value = 'test';
      searchInput.dispatchEvent(new Event('input', { bubbles: true }));

      // Clear button should now be visible (this is synchronous)
      expect(clearBtn?.classList.contains('hidden')).toBe(false);
    });

    it('clear button removes search filter', async () => {
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
      const searchInput = container.querySelector('#task-search') as HTMLInputElement;
      const clearBtn = container.querySelector('#task-search-clear');

      // Search for something
      searchInput.value = 'Task 1';
      searchInput.dispatchEvent(new Event('input', { bubbles: true }));

      await vi.advanceTimersByTimeAsync(200);

      let taskItems = container.querySelectorAll('.task-item');
      expect(taskItems.length).toBe(1);

      // Click clear button
      clearBtn?.dispatchEvent(new MouseEvent('click', { bubbles: true }));

      // Should show all tasks again (synchronous)
      taskItems = container.querySelectorAll('.task-item');
      expect(taskItems.length).toBe(2);
    });

    it('search combines with status filter', async () => {
      setState('tasks', [
        {
          id: 'task1',
          title: 'Running Task',
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
        {
          id: 'task2',
          title: 'Ready Task',
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

      // Set status filter to "running"
      const statusFilter = container.querySelector('#filter-status') as HTMLSelectElement;
      statusFilter.value = 'running';
      statusFilter.dispatchEvent(new Event('change', { bubbles: true }));

      // Search for "Task"
      const searchInput = container.querySelector('#task-search') as HTMLInputElement;
      searchInput.value = 'Task';
      searchInput.dispatchEvent(new Event('input', { bubbles: true }));

      await vi.advanceTimersByTimeAsync(200);

      const taskItems = container.querySelectorAll('.task-item');
      // Should only show running tasks that match search
      expect(taskItems.length).toBe(1);
      expect(taskItems[0].textContent).toContain('Running Task');
    });

    it('empty search shows all filtered tasks', async () => {
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
      const searchInput = container.querySelector('#task-search') as HTMLInputElement;

      // Search then clear
      searchInput.value = 'Task 1';
      searchInput.dispatchEvent(new Event('input', { bubbles: true }));

      await vi.advanceTimersByTimeAsync(200);

      let taskItems = container.querySelectorAll('.task-item');
      expect(taskItems.length).toBe(1);

      // Clear search
      searchInput.value = '';
      searchInput.dispatchEvent(new Event('input', { bubbles: true }));

      await vi.advanceTimersByTimeAsync(200);

      taskItems = container.querySelectorAll('.task-item');
      expect(taskItems.length).toBe(2);
    });
  });

  describe('metadata display', () => {
    beforeEach(() => {
      vi.spyOn(apiClient, 'getTasks').mockResolvedValue({ tasks: [], count: 0 });
    });

    it('shows role badge', () => {
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
      ]);

      page.render(container);
      const roleBadge = container.querySelector('.task-role');
      expect(roleBadge).toBeTruthy();
      expect(roleBadge?.textContent).toBe('Coder');
    });

    it('shows priority indicator for high priority tasks (score > 0.7)', () => {
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
          importance: 0.9,
          urgency: 0.9,
          priority_score: 0.85,  // High priority
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
      const priorityIndicator = container.querySelector('.task-priority');
      expect(priorityIndicator).toBeTruthy();
      expect(priorityIndicator?.textContent).toContain('0.85');
    });

    it('hides priority indicator for normal priority tasks (score <= 0.7)', () => {
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
          priority_score: 0.5,  // Normal priority
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
      const priorityIndicator = container.querySelector('.task-priority');
      expect(priorityIndicator).toBeFalsy();
    });

    it('priority indicator uses unicode character not emoji', () => {
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
          importance: 0.9,
          urgency: 0.9,
          priority_score: 0.85,
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
      const priorityIndicator = container.querySelector('.task-priority');
      // Check that it uses unicode \u25c6 (◆) not an emoji
      expect(priorityIndicator?.textContent).toContain('\u25c6');
    });
  });

  describe('filter persistence', () => {
    beforeEach(() => {
      vi.spyOn(apiClient, 'getTasks').mockResolvedValue({ tasks: [], count: 0 });
      // Clear localStorage before each test
      window.localStorage.clear();
    });

    it('saves status filter to localStorage on change', () => {
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
      ]);

      page.render(container);

      // Change status filter
      const statusFilter = container.querySelector('#filter-status') as HTMLSelectElement;
      statusFilter.value = 'running';
      statusFilter.dispatchEvent(new Event('change', { bubbles: true }));

      // Check localStorage
      const saved = JSON.parse(window.localStorage.getItem('matrixmouse.tasks.filters') || '{}');
      expect(saved.status).toBe('running');
    });

    it('saves repo filter to localStorage on change', () => {
      setState('repos', [
        { name: 'repo1', remote: 'https://github.com/test/repo1.git', local_path: '/test/repo1', added: '2024-01-01' },
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
      ]);

      page.render(container);

      // Change repo filter
      const repoFilter = container.querySelector('#filter-repo') as HTMLSelectElement;
      repoFilter.value = 'repo1';
      repoFilter.dispatchEvent(new Event('change', { bubbles: true }));

      // Check localStorage
      const saved = JSON.parse(window.localStorage.getItem('matrixmouse.tasks.filters') || '{}');
      expect(saved.repo).toBe('repo1');
    });

    it('restores filters from localStorage on mount', () => {
      // Save filters to localStorage
      window.localStorage.setItem('matrixmouse.tasks.filters', JSON.stringify({
        status: 'running',
        repo: 'repo1',
        search: 'test',
      }));

      setState('tasks', [
        {
          id: 'task1',
          title: 'Running Task',
          description: '',
          repo: ['repo1'],
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
        {
          id: 'task2',
          title: 'Ready Task',
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

      // Check that filters were restored
      const statusFilter = container.querySelector('#filter-status') as HTMLSelectElement;
      expect(statusFilter.value).toBe('running');
    });

    it('handles corrupted localStorage data gracefully', () => {
      // Save corrupted data
      window.localStorage.setItem('matrixmouse.tasks.filters', 'invalid json');

      setState('tasks', []);

      // Should not throw
      expect(() => page.render(container)).not.toThrow();
    });

    it('handles missing localStorage keys', () => {
      // Save partial data (missing some keys)
      window.localStorage.setItem('matrixmouse.tasks.filters', JSON.stringify({
        status: 'running',
        // Missing repo and search
      }));

      setState('tasks', []);

      // Should not throw
      expect(() => page.render(container)).not.toThrow();
    });
  });

  describe('terminal state distinction', () => {
    beforeEach(() => {
      vi.spyOn(apiClient, 'getTasks').mockResolvedValue({ tasks: [], count: 0 });
    });

    it('complete tasks have terminal CSS class', () => {
      setState('tasks', [
        {
          id: 'task1',
          title: 'Completed Task',
          description: '',
          repo: [],
          role: 'coder' as const,
          status: 'complete' as const,
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
      expect(taskItem?.classList.contains('terminal')).toBe(true);
    });

    it('cancelled tasks have terminal CSS class', () => {
      setState('tasks', [
        {
          id: 'task1',
          title: 'Cancelled Task',
          description: '',
          repo: [],
          role: 'coder' as const,
          status: 'cancelled' as const,
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
      expect(taskItem?.classList.contains('terminal')).toBe(true);
    });

    it('active tasks do not have terminal CSS class', () => {
      setState('tasks', [
        {
          id: 'task1',
          title: 'Active Task',
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
      expect(taskItem?.classList.contains('terminal')).toBe(false);
    });
  });

  describe('task count display', () => {
    beforeEach(() => {
      vi.spyOn(apiClient, 'getTasks').mockResolvedValue({ tasks: [], count: 0 });
    });

    it('shows task count after render', () => {
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
      const countDisplay = container.querySelector('.task-count');
      expect(countDisplay).toBeTruthy();
      expect(countDisplay?.textContent).toBe('2 tasks');
    });

    it('count updates when filters change', () => {
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

      // Initially shows "2 tasks"
      let countDisplay = container.querySelector('.task-count');
      expect(countDisplay?.textContent).toBe('2 tasks');

      // Filter by "running"
      const statusFilter = container.querySelector('#filter-status') as HTMLSelectElement;
      statusFilter.value = 'running';
      statusFilter.dispatchEvent(new Event('change', { bubbles: true }));

      // Should now show "Showing 1 of 2 tasks"
      countDisplay = container.querySelector('.task-count');
      expect(countDisplay?.textContent).toBe('Showing 1 of 2 tasks');
    });

    it('count shows filtered vs total when filtering', () => {
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
        {
          id: 'task3',
          title: 'Task 3',
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

      // Filter by "running"
      const statusFilter = container.querySelector('#filter-status') as HTMLSelectElement;
      statusFilter.value = 'running';
      statusFilter.dispatchEvent(new Event('change', { bubbles: true }));

      const countDisplay = container.querySelector('.task-count');
      expect(countDisplay?.textContent).toBe('Showing 1 of 3 tasks');
    });
  });

  describe('renderTaskRepo', () => {
    beforeEach(() => {
      vi.spyOn(apiClient, 'getTasks').mockResolvedValue({ tasks: [], count: 0 });
    });

    it('shows "Workspace" for tasks with no repos', () => {
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
      ]);

      page.render(container);
      const taskRepo = container.querySelector('.task-repo');
      expect(taskRepo?.textContent).toBe('Workspace');
    });

    it('shows single repo name', () => {
      setState('tasks', [
        {
          id: 'task1',
          title: 'Task 1',
          description: '',
          repo: ['my-repo'],
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
      const taskRepo = container.querySelector('.task-repo');
      expect(taskRepo?.textContent).toBe('my-repo');
    });

    it('shows multiple repos comma-separated', () => {
      setState('tasks', [
        {
          id: 'task1',
          title: 'Task 1',
          description: '',
          repo: ['repo-a', 'repo-b'],
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
      const taskRepo = container.querySelector('.task-repo');
      expect(taskRepo?.textContent).toBe('repo-a, repo-b');
    });
  });

  describe('renderTaskItem', () => {
    beforeEach(() => {
      vi.spyOn(apiClient, 'getTasks').mockResolvedValue({ tasks: [], count: 0 });
    });

    it('escapes HTML in task title (XSS prevention)', () => {
      setState('tasks', [
        {
          id: 'task1',
          title: '<script>alert("xss")</script>',
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
      const taskTitle = container.querySelector('.task-title');
      // Should be escaped, not rendered as HTML
      expect(taskTitle?.textContent).toBe('<script>alert("xss")</script>');
      expect(taskTitle?.innerHTML).not.toContain('<script>');
    });

    it('escapes HTML in task ID', () => {
      setState('tasks', [
        {
          id: '<img src=x onerror=alert(1)>',
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
      const taskId = container.querySelector('.task-id');
      expect(taskId?.textContent).toBe('<img src=x onerror=alert(1)>');
      expect(taskId?.innerHTML).not.toContain('<img');
    });

    it('priority indicator hidden at exactly 0.7 (boundary)', () => {
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
          priority_score: 0.7,  // Exactly at threshold
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
      const priorityIndicator = container.querySelector('.task-priority');
      expect(priorityIndicator).toBeFalsy();
    });

    it('priority indicator shown at 0.71 (just above boundary)', () => {
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
          priority_score: 0.71,  // Just above threshold
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
      const priorityIndicator = container.querySelector('.task-priority');
      expect(priorityIndicator).toBeTruthy();
      expect(priorityIndicator?.textContent).toContain('0.71');
    });

    it('task link href uses escaped task ID', () => {
      setState('tasks', [
        {
          id: 'task/with?special&chars',
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
      const taskLink = container.querySelector('.task-link') as HTMLAnchorElement;
      expect(taskLink?.getAttribute('href')).toBe('/task/task/with?special&chars');
    });
  });

  describe('state subscription', () => {
    beforeEach(() => {
      vi.spyOn(apiClient, 'getTasks').mockResolvedValue({ tasks: [], count: 0 });
    });

    it('re-renders task list when tasks change in state', async () => {
      // Set tasks in state BEFORE render so loadTasks sees them and returns early
      const testTasks = [
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
      ];
      setState('tasks', testTasks);
      page.render(container);

      // Should show tasks immediately (loadTasks returned early)
      let taskItems = container.querySelectorAll('.task-item');
      expect(taskItems.length).toBe(1);

      // Now add another task to state - subscription should trigger re-render
      const newTask = {
        ...testTasks[0],
        id: 'task2',
        title: 'Task 2',
      };
      setState('tasks', [...testTasks, newTask]);

      // Should have re-rendered with both tasks
      taskItems = container.querySelectorAll('.task-item');
      expect(taskItems.length).toBe(2);
      expect(taskItems[1].textContent).toContain('Task 2');
    });

    it('re-populates repo filter when repos change in state', () => {
      setState('tasks', []);
      setState('repos', []);
      page.render(container);

      // Initially no repo options (except "All")
      let repoFilter = container.querySelector('#filter-repo') as HTMLSelectElement;
      expect(repoFilter?.options.length).toBe(1);

      // Simulate repos being added to state
      setState('repos', [
        { name: 'new-repo', remote: 'https://github.com/test/new.git', local_path: '/test/new', added: '2024-01-01' },
      ]);

      // Should re-populate repo filter
      repoFilter = container.querySelector('#filter-repo') as HTMLSelectElement;
      expect(repoFilter?.options.length).toBe(2);
      expect(repoFilter?.options[1]?.value).toBe('new-repo');
    });

    it('does not re-render during loading (isLoading guard)', async () => {
      // Start with empty tasks so loadTasks will be triggered
      setState('tasks', []);
      
      // Mock API to delay response
      const mockFn = vi.spyOn(apiClient, 'getTasks').mockImplementation(
        () => new Promise(resolve => setTimeout(() => resolve({ tasks: [], count: 0 }), 100))
      );

      page.render(container);

      // isLoading should be true now
      expect((page as any).isLoading).toBe(true);

      // Wait for the mock API call to complete to avoid polluting subsequent tests
      await new Promise(resolve => setTimeout(resolve, 150));
      
      mockFn.mockRestore();
    });
  });

  describe('combined filters', () => {
    beforeEach(() => {
      // Clear any pending timers from previous tests
      vi.clearAllTimers();
      vi.useRealTimers();
      vi.spyOn(apiClient, 'getTasks').mockResolvedValue({ tasks: [], count: 0 });
      vi.useFakeTimers();
      // Reset state and page instance to avoid pollution from previous tests
      resetState();
      page = new TasksPage();
      // Clean up previous container and create fresh one
      if (container && container.parentNode) {
        document.body.removeChild(container);
      }
      container = document.createElement('div');
      document.body.appendChild(container);
    });

    it('combines search + status + repo filters', async () => {
      // Set up state BEFORE render so loadTasks() sees them
      setState('repos', [
        { name: 'repo-a', remote: 'https://github.com/test/a.git', local_path: '/test/a', added: '2024-01-01' },
        { name: 'repo-b', remote: 'https://github.com/test/b.git', local_path: '/test/b', added: '2024-01-01' },
      ]);
      setState('tasks', [
        {
          id: 'task1',
          title: 'Running Task A',
          description: 'In repo a',
          repo: ['repo-a'],
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
        {
          id: 'task2',
          title: 'Ready Task A',
          description: 'In repo a',
          repo: ['repo-a'],
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
          id: 'task3',
          title: 'Running Task B',
          description: 'In repo b',
          repo: ['repo-b'],
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

      // Set status filter to "running"
      const statusFilter = container.querySelector('#filter-status') as HTMLSelectElement;
      statusFilter.value = 'running';
      statusFilter.dispatchEvent(new Event('change', { bubbles: true }));

      // Set repo filter to "repo-a"
      const repoFilter = container.querySelector('#filter-repo') as HTMLSelectElement;
      repoFilter.value = 'repo-a';
      repoFilter.dispatchEvent(new Event('change', { bubbles: true }));

      // Search for "Task"
      const searchInput = container.querySelector('#task-search') as HTMLInputElement;
      searchInput.value = 'Task';
      searchInput.dispatchEvent(new Event('input', { bubbles: true }));

      await vi.advanceTimersByTimeAsync(200);

      // Should only show "Running Task A" (running + repo-a + matches "Task")
      const taskItems = container.querySelectorAll('.task-item');
      expect(taskItems.length).toBe(1);
      expect(taskItems[0].textContent).toContain('Running Task A');
    });

    it('restored filters from localStorage actually filter tasks', async () => {
      // Set up localStorage with saved filters
      window.localStorage.setItem('matrixmouse.tasks.filters', JSON.stringify({
        status: 'running',
        repo: 'repo-a',
        search: 'Running',
      }));

      setState('repos', [
        { name: 'repo-a', remote: 'https://github.com/test/a.git', local_path: '/test/a', added: '2024-01-01' },
      ]);
      setState('tasks', [
        {
          id: 'task1',
          title: 'Running Task',
          description: '',
          repo: ['repo-a'],
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
        {
          id: 'task2',
          title: 'Ready Task',
          description: '',
          repo: ['repo-a'],
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

      // Should have applied filters
      // Status filter should be "running"
      const statusFilter = container.querySelector('#filter-status') as HTMLSelectElement;
      expect(statusFilter.value).toBe('running');

      // Search input should have "Running"
      const searchInput = container.querySelector('#task-search') as HTMLInputElement;
      expect(searchInput.value).toBe('Running');

      // Should only show "Running Task" (running status + "Running" search)
      const taskItems = container.querySelectorAll('.task-item');
      expect(taskItems.length).toBe(1);
      expect(taskItems[0].textContent).toContain('Running Task');
    });

    it('search with empty string shows all tasks', async () => {
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

      // Search with empty string
      const searchInput = container.querySelector('#task-search') as HTMLInputElement;
      searchInput.value = '';
      searchInput.dispatchEvent(new Event('input', { bubbles: true }));

      await vi.advanceTimersByTimeAsync(200);

      // Should show all tasks
      const taskItems = container.querySelectorAll('.task-item');
      expect(taskItems.length).toBe(2);
    });

    it('search matches task description or notes', async () => {
      setState('tasks', [
        {
          id: 'task1',
          title: 'Task 1',
          description: 'This has a secret keyword in description',
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
          notes: 'Another secret keyword in notes',
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
          id: 'task3',
          title: 'Task 3',
          description: 'No match here',
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

      // Search for keyword that's only in description/notes
      const searchInput = container.querySelector('#task-search') as HTMLInputElement;
      searchInput.value = 'secret keyword';
      searchInput.dispatchEvent(new Event('input', { bubbles: true }));

      await vi.advanceTimersByTimeAsync(200);

      // Should match task1 (description) and task2 (notes)
      const taskItems = container.querySelectorAll('.task-item');
      expect(taskItems.length).toBe(2);
    });
  });
});
