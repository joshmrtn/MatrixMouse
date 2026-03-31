/**
 * Unit Tests for State Management Store
 * 
 * Tests the central state store for all state operations.
 */

import { describe, it, expect, beforeEach, vi } from 'vitest';
import {
  getState,
  setState,
  setStates,
  resetState,
  subscribe,
  getTaskById,
  getTasksForRepo,
  getBlockedTasks,
  getWaitingTasks,
  getActiveTasks,
  buildTaskTree,
  toggleTaskExpansion,
  isTaskExpanded,
  initialState,
} from '../../../src/state/store';

describe('State Store - Basic Operations', () => {
  beforeEach(() => {
    resetState();
  });

  it('returns initial state on first call', () => {
    const state = getState();
    
    expect(state.scope).toBe('workspace');
    expect(state.selectedTask).toBeNull();
    expect(state.tasks).toEqual([]);
    expect(state.repos).toEqual([]);
    expect(state.wsConnected).toBe(false);
    expect(state.currentPage).toBe('channel');
  });

  it('updates single state key', () => {
    setState('scope', 'test-repo');
    
    const state = getState();
    expect(state.scope).toBe('test-repo');
  });

  it('updates multiple state keys at once', () => {
    setStates({
      scope: 'main-repo',
      wsConnected: true,
      currentPage: 'tasks',
    });
    
    const state = getState();
    expect(state.scope).toBe('main-repo');
    expect(state.wsConnected).toBe(true);
    expect(state.currentPage).toBe('tasks');
  });

  it('resets state to initial values', () => {
    setState('scope', 'changed');
    setState('wsConnected', true);
    
    resetState();
    
    const state = getState();
    expect(state.scope).toBe('workspace');
    expect(state.wsConnected).toBe(false);
  });

  it('creates new object on each getState call', () => {
    const state1 = getState();
    const state2 = getState();
    
    expect(state1).not.toBe(state2);
    expect(state1).toEqual(state2);
  });
});

describe('State Store - Subscriptions', () => {
  beforeEach(() => {
    resetState();
  });

  it('notifies subscribers on state change', () => {
    const listener = vi.fn();
    subscribe(listener);
    
    setState('scope', 'new-repo');
    
    expect(listener).toHaveBeenCalledTimes(1);
    expect(listener).toHaveBeenCalledWith(getState());
  });

  it('notifies multiple subscribers', () => {
    const listener1 = vi.fn();
    const listener2 = vi.fn();
    
    subscribe(listener1);
    subscribe(listener2);
    
    setState('wsConnected', true);
    
    expect(listener1).toHaveBeenCalledTimes(1);
    expect(listener2).toHaveBeenCalledTimes(1);
  });

  it('unsubscribes correctly', () => {
    const listener = vi.fn();
    const unsubscribe = subscribe(listener);
    
    setState('scope', 'test');
    expect(listener).toHaveBeenCalledTimes(1);
    
    unsubscribe();
    
    setState('scope', 'test2');
    expect(listener).toHaveBeenCalledTimes(1); // Should not be called again
  });

  it('passes current state to subscriber on change', () => {
    const listener = vi.fn();
    subscribe(listener);
    
    setState('currentPage', 'status');
    
    expect(listener).toHaveBeenCalledWith(expect.objectContaining({
      currentPage: 'status',
    }));
  });
});

describe('State Store - Task Helpers', () => {
  beforeEach(() => {
    resetState();
  });

  const mockTasks = [
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
      repo: ['repo1'],
      role: 'coder' as const,
      status: 'running' as const,
      branch: 'mm/feature',
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
      repo: ['repo2'],
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
  ];

  describe('getTaskById', () => {
    it('returns task by exact ID', () => {
      setState('tasks', mockTasks);
      
      const task = getTaskById('task1');
      expect(task).toBeDefined();
      expect(task?.id).toBe('task1');
    });

    it('returns undefined for non-existent task', () => {
      setState('tasks', mockTasks);
      
      const task = getTaskById('nonexistent');
      expect(task).toBeUndefined();
    });
  });

  describe('getTasksForRepo', () => {
    beforeEach(() => {
      setState('tasks', mockTasks);
    });

    it('returns tasks for specific repo', () => {
      const repo1Tasks = getTasksForRepo('repo1');
      expect(repo1Tasks.length).toBe(2);
      expect(repo1Tasks.every(t => t.repo.includes('repo1'))).toBe(true);
    });

    it('returns workspace tasks when scope is workspace', () => {
      // Add workspace task (no repo)
      const workspaceTask = {
        ...mockTasks[0],
        id: 'ws-task',
        repo: [],
      };
      setState('tasks', [...mockTasks, workspaceTask]);

      const wsTasks = getTasksForRepo('workspace');
      expect(wsTasks.some(t => t.id === 'ws-task')).toBe(true);
    });

    it('returns multi-repo tasks for workspace', () => {
      // Add multi-repo task
      const multiRepoTask = {
        ...mockTasks[0],
        id: 'multi-repo-task',
        repo: ['repo1', 'repo2'],
      };
      setState('tasks', [...mockTasks, multiRepoTask]);

      const wsTasks = getTasksForRepo('workspace');
      expect(wsTasks.some(t => t.id === 'multi-repo-task')).toBe(true);
    });

    it('excludes single-repo tasks from workspace', () => {
      const wsTasks = getTasksForRepo('workspace');
      expect(wsTasks.every(t => t.repo.length !== 1)).toBe(true);
    });

    it('returns empty array when no workspace tasks', () => {
      const wsTasks = getTasksForRepo('workspace');
      expect(wsTasks.length).toBe(0);
    });
  });

  describe('getBlockedTasks', () => {
    it('returns only blocked tasks', () => {
      setState('tasks', mockTasks);
      
      const blocked = getBlockedTasks();
      expect(blocked.length).toBe(1);
      expect(blocked[0].status).toBe('blocked_by_human');
    });
  });

  describe('getWaitingTasks', () => {
    it('returns only waiting tasks', () => {
      const waitingTask = {
        ...mockTasks[0],
        id: 'waiting',
        status: 'waiting' as const,
        wait_until: '2024-01-02T00:00:00Z',
        wait_reason: 'budget:api_limit',
      };
      setState('tasks', [waitingTask]);
      
      const waiting = getWaitingTasks();
      expect(waiting.length).toBe(1);
      expect(waiting[0].status).toBe('waiting');
    });
  });

  describe('getActiveTasks', () => {
    it('excludes terminal tasks', () => {
      const tasks = [
        ...mockTasks,
        {
          ...mockTasks[0],
          id: 'complete',
          status: 'complete' as const,
        },
        {
          ...mockTasks[0],
          id: 'cancelled',
          status: 'cancelled' as const,
        },
      ];
      setState('tasks', tasks);
      
      const active = getActiveTasks();
      expect(active.some(t => t.status === 'complete')).toBe(false);
      expect(active.some(t => t.status === 'cancelled')).toBe(false);
    });
  });
});

describe('State Store - Task Tree', () => {
  beforeEach(() => {
    resetState();
  });

  const mockTasks = [
    {
      id: 'parent',
      title: 'Parent Task',
      description: '',
      repo: [],
      role: 'manager' as const,
      status: 'blocked_by_task' as const,
      branch: 'mm/parent',
      parent_task_id: null,
      depth: 0,
      importance: 0.8,
      urgency: 0.7,
      priority_score: 0.3,
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
      id: 'child1',
      title: 'Child Task 1',
      description: '',
      repo: [],
      role: 'coder' as const,
      status: 'ready' as const,
      branch: 'mm/parent/child1',
      parent_task_id: 'parent',
      depth: 1,
      importance: 0.6,
      urgency: 0.5,
      priority_score: 0.45,
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
      id: 'child2',
      title: 'Child Task 2',
      description: '',
      repo: [],
      role: 'coder' as const,
      status: 'running' as const,
      branch: 'mm/parent/child2',
      parent_task_id: 'parent',
      depth: 1,
      importance: 0.6,
      urgency: 0.5,
      priority_score: 0.45,
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
      id: 'grandchild',
      title: 'Grandchild Task',
      description: '',
      repo: [],
      role: 'coder' as const,
      status: 'pending' as const,
      branch: 'mm/parent/child1/grandchild',
      parent_task_id: 'child1',
      depth: 2,
      importance: 0.4,
      urgency: 0.3,
      priority_score: 0.65,
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

  describe('buildTaskTree', () => {
    it('builds correct tree structure', () => {
      setState('tasks', mockTasks);
      
      const { rootTasks } = buildTaskTree();
      
      expect(rootTasks.length).toBe(1);
      expect(rootTasks[0].id).toBe('parent');
      expect(rootTasks[0].children.length).toBe(2);
    });

    it('includes grandchildren', () => {
      setState('tasks', mockTasks);
      
      const { rootTasks } = buildTaskTree();
      
      const parent = rootTasks[0];
      const child1 = parent.children.find(c => c.id === 'child1');
      expect(child1).toBeDefined();
      expect(child1?.children.length).toBe(1);
      expect(child1?.children[0].id).toBe('grandchild');
    });

    it('creates task map for quick lookup', () => {
      setState('tasks', mockTasks);
      
      const { taskMap } = buildTaskTree();
      
      expect(taskMap.size).toBe(4);
      expect(taskMap.has('parent')).toBe(true);
      expect(taskMap.has('child1')).toBe(true);
      expect(taskMap.has('grandchild')).toBe(true);
    });

    it('handles orphan tasks', () => {
      const orphanTask = {
        ...mockTasks[0],
        id: 'orphan',
        parent_task_id: 'nonexistent',
      };
      setState('tasks', [orphanTask]);
      
      const { rootTasks } = buildTaskTree();
      
      // Orphan should be a root task since parent doesn't exist
      expect(rootTasks.some(t => t.id === 'orphan')).toBe(true);
    });

    it('handles empty task list', () => {
      setState('tasks', []);
      
      const { rootTasks, taskMap } = buildTaskTree();
      
      expect(rootTasks.length).toBe(0);
      expect(taskMap.size).toBe(0);
    });
  });

  describe('toggleTaskExpansion', () => {
    it('toggles task expansion state', () => {
      expect(isTaskExpanded('task1')).toBe(false);
      
      toggleTaskExpansion('task1');
      expect(isTaskExpanded('task1')).toBe(true);
      
      toggleTaskExpansion('task1');
      expect(isTaskExpanded('task1')).toBe(false);
    });

    it('tracks expansion per task', () => {
      toggleTaskExpansion('task1');
      toggleTaskExpansion('task2');
      
      expect(isTaskExpanded('task1')).toBe(true);
      expect(isTaskExpanded('task2')).toBe(true);
      expect(isTaskExpanded('task3')).toBe(false);
    });
  });

  describe('isTaskExpanded', () => {
    it('returns false for untracked tasks', () => {
      expect(isTaskExpanded('nonexistent')).toBe(false);
    });

    it('returns true after toggle', () => {
      toggleTaskExpansion('task1');
      expect(isTaskExpanded('task1')).toBe(true);
    });
  });
});

describe('State Store - Edge Cases', () => {
  beforeEach(() => {
    resetState();
  });

  it('handles rapid state updates', () => {
    for (let i = 0; i < 100; i++) {
      setState('scope', `repo-${i}`);
    }
    
    expect(getState().scope).toBe('repo-99');
  });

  it('handles concurrent subscriptions', () => {
    const listeners = Array(10).fill(null).map(() => vi.fn());
    listeners.forEach(l => subscribe(l));
    
    setState('wsConnected', true);
    
    listeners.forEach(l => {
      expect(l).toHaveBeenCalledTimes(1);
    });
  });

  it('preserves state shape on partial updates', () => {
    setStates({ scope: 'test' });
    
    const state = getState();
    expect(state).toHaveProperty('repos');
    expect(state).toHaveProperty('tasks');
    expect(state).toHaveProperty('expandedTasks');
  });
});
