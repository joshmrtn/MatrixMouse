/**
 * Unit tests for Sidebar component
 */

import { describe, it, expect, beforeEach, vi } from 'vitest';
import { Sidebar } from '../../../src/components/Sidebar';
import { setState, resetState } from '../../../src/state/store';

describe('Sidebar', () => {
  let sidebar: Sidebar;
  let container: HTMLElement;

  beforeEach(() => {
    resetState();
    sidebar = new Sidebar();
    container = document.createElement('div');
    document.body.appendChild(container);
  });

  afterEach(() => {
    document.body.removeChild(container);
    container = null as unknown as HTMLElement;
  });

  describe('render', () => {
    it('creates sidebar element', () => {
      const element = sidebar.render();
      expect(element.tagName).toBe('NAV');
      expect(element.id).toBe('sidebar');
    });

    it('renders workspace channel', () => {
      const element = sidebar.render();
      const workspaceItem = element.querySelector('[data-scope="workspace"]');
      expect(workspaceItem).toBeTruthy();
    });

    it('renders status tab with correct unicode', () => {
      const element = sidebar.render();
      const statusTab = element.querySelector('[data-tab="status"] .sb-icon');
      expect(statusTab?.textContent).toBe('𝌠');
    });

    it('renders tasks tab with correct unicode', () => {
      const element = sidebar.render();
      const tasksTab = element.querySelector('[data-tab="tasks"] .sb-icon');
      expect(tasksTab?.textContent).toBe('≡');
    });

    it('renders settings tab with correct unicode', () => {
      const element = sidebar.render();
      const settingsTab = element.querySelector('[data-tab="settings"] .sb-icon');
      expect(settingsTab?.textContent).toBe('⚙');
    });

    it('highlights active scope', () => {
      setState('scope', 'workspace');
      const element = sidebar.render();
      const workspaceItem = element.querySelector('[data-scope="workspace"]');
      expect(workspaceItem?.classList.contains('active')).toBe(true);
    });

    it('highlights active tab', () => {
      setState('currentPage', 'status');
      const element = sidebar.render();
      const statusTab = element.querySelector('[data-tab="status"]');
      expect(statusTab?.classList.contains('active')).toBe(true);
    });

    it('starts expanded on desktop', () => {
      // Mock desktop viewport
      Object.defineProperty(window, 'innerWidth', { value: 1280, writable: true });
      const element = sidebar.render();
      expect(element.classList.contains('collapsed')).toBe(false);
    });

    it('starts collapsed on mobile', () => {
      // Mock mobile viewport
      Object.defineProperty(window, 'innerWidth', { value: 375, writable: true });
      const element = sidebar.render();
      expect(element.classList.contains('collapsed')).toBe(true);
    });
  });

  describe('setCollapsed and isCollapsed', () => {
    it('sets collapsed state via setCollapsed', () => {
      const element = sidebar.render();
      sidebar.setCollapsed(true);
      expect(sidebar.isCollapsed()).toBe(true);
      expect(element.classList.contains('collapsed')).toBe(true);
    });

    it('sets expanded state via setCollapsed', () => {
      const element = sidebar.render();
      sidebar.setCollapsed(false);
      expect(sidebar.isCollapsed()).toBe(false);
      expect(element.classList.contains('collapsed')).toBe(false);
    });

    it('returns false when element is null', () => {
      // Create sidebar but don't render
      const newSidebar = new Sidebar();
      expect(newSidebar.isCollapsed()).toBe(false);
    });

    it('handles setCollapsed when element is null', () => {
      // Create sidebar but don't render
      const newSidebar = new Sidebar();
      expect(() => newSidebar.setCollapsed(true)).not.toThrow();
    });
  });

  describe('sidebar-toggle event listener', () => {
    it('responds to sidebar-toggle custom event', () => {
      const element = sidebar.render();
      
      // Dispatch collapse event
      window.dispatchEvent(new CustomEvent('sidebar-toggle', {
        detail: { collapsed: true }
      }));

      expect(element.classList.contains('collapsed')).toBe(true);
      expect(sidebar.isCollapsed()).toBe(true);
    });

    it('responds to sidebar-toggle expand event', () => {
      const element = sidebar.render();
      sidebar.setCollapsed(true);

      // Dispatch expand event
      window.dispatchEvent(new CustomEvent('sidebar-toggle', {
        detail: { collapsed: false }
      }));

      expect(element.classList.contains('collapsed')).toBe(false);
      expect(sidebar.isCollapsed()).toBe(false);
    });
  });

  describe('repo rendering', () => {
    it('renders repos from state', () => {
      setState('repos', [
        { name: 'repo1', remote: 'https://github.com/test/repo1.git', local_path: '/test/repo1', added: '2024-01-01' },
        { name: 'repo2', remote: 'https://github.com/test/repo2.git', local_path: '/test/repo2', added: '2024-01-01' },
      ]);

      const element = sidebar.render();
      const repoItems = element.querySelectorAll('[data-repo]');
      expect(repoItems.length).toBe(2);
    });

    it('renders repo names correctly', () => {
      setState('repos', [
        { name: 'MatrixMouse', remote: 'https://github.com/test/MatrixMouse.git', local_path: '/test/MatrixMouse', added: '2024-01-01' },
      ]);

      const element = sidebar.render();
      const repoName = element.querySelector('[data-repo="MatrixMouse"] .sb-name');
      expect(repoName?.textContent).toBe('MatrixMouse');
    });

    it('includes expand button for repos', () => {
      setState('repos', [
        { name: 'test-repo', remote: 'https://github.com/test/repo.git', local_path: '/test/repo', added: '2024-01-01' },
      ]);

      const element = sidebar.render();
      const expandBtn = element.querySelector('[data-repo="test-repo"] .sb-repo-expand');
      expect(expandBtn).toBeTruthy();
    });
  });

  describe('task tree rendering', () => {
    it('renders task trees container', () => {
      const element = sidebar.render();
      const taskTreesEl = element.querySelector('#sb-task-trees');
      expect(taskTreesEl).toBeTruthy();
    });

    it('renders tasks under repos', () => {
      setState('repos', [
        { name: 'test-repo', remote: 'https://github.com/test/repo.git', local_path: '/test/repo', added: '2024-01-01' },
      ]);
      setState('tasks', [
        {
          id: 'task1',
          title: 'Test Task',
          description: '',
          repo: ['test-repo'],
          role: 'coder' as const,
          status: 'ready' as const,
          branch: 'mm/test',
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

      const element = sidebar.render();
      const taskItem = element.querySelector('[data-task-id="task1"]');
      expect(taskItem).toBeTruthy();
    });

    it('renders task status indicators', () => {
      setState('repos', [
        { name: 'test-repo', remote: 'https://github.com/test/repo.git', local_path: '/test/repo', added: '2024-01-01' },
      ]);
      setState('tasks', [
        {
          id: 'task1',
          title: 'Running Task',
          description: '',
          repo: ['test-repo'],
          role: 'coder' as const,
          status: 'running' as const,
          branch: 'mm/test',
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

      const element = sidebar.render();
      const statusDot = element.querySelector('[data-task-id="task1"] .sb-task-status');
      expect(statusDot?.classList.contains('status-running')).toBe(true);
    });
  });

  describe('event handling', () => {
    it('handles scope click navigation', () => {
      const element = sidebar.render();
      const workspaceItem = element.querySelector('[data-scope="workspace"]');
      
      const pushStateSpy = vi.spyOn(window.history, 'pushState');
      const dispatchEventSpy = vi.spyOn(window, 'dispatchEvent');

      workspaceItem?.dispatchEvent(new MouseEvent('click', { bubbles: true }));

      expect(pushStateSpy).toHaveBeenCalledWith({}, '', '/channel/workspace');
      expect(dispatchEventSpy).toHaveBeenCalledWith(expect.any(Event));
    });

    it('handles tab click navigation', () => {
      const element = sidebar.render();
      const statusTab = element.querySelector('[data-tab="status"]');
      
      const pushStateSpy = vi.spyOn(window.history, 'pushState');
      const dispatchEventSpy = vi.spyOn(window, 'dispatchEvent');

      statusTab?.dispatchEvent(new MouseEvent('click', { bubbles: true }));

      expect(pushStateSpy).toHaveBeenCalledWith({}, '', '/status');
      expect(dispatchEventSpy).toHaveBeenCalledWith(expect.any(Event));
    });

    it('handles task click navigation', () => {
      setState('repos', [
        { name: 'test-repo', remote: 'https://github.com/test/repo.git', local_path: '/test/repo', added: '2024-01-01' },
      ]);
      setState('tasks', [
        {
          id: 'task1',
          title: 'Test Task',
          description: '',
          repo: ['test-repo'],
          role: 'coder' as const,
          status: 'ready' as const,
          branch: 'mm/test',
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

      const element = sidebar.render();
      const taskItem = element.querySelector('[data-task-id="task1"]');
      
      const pushStateSpy = vi.spyOn(window.history, 'pushState');
      const dispatchEventSpy = vi.spyOn(window, 'dispatchEvent');

      taskItem?.dispatchEvent(new MouseEvent('click', { bubbles: true }));

      expect(pushStateSpy).toHaveBeenCalledWith({}, '', '/task/task1');
      expect(dispatchEventSpy).toHaveBeenCalledWith(expect.any(Event));
    });

    it('handles repo expand toggle', () => {
      setState('repos', [
        { name: 'test-repo', remote: 'https://github.com/test/repo.git', local_path: '/test/repo', added: '2024-01-01' },
      ]);

      const element = sidebar.render();
      const expandBtn = element.querySelector('[data-repo="test-repo"] .sb-repo-expand');
      const taskTree = element.querySelector('#sb-task-tree-test-repo');

      expect(taskTree?.classList.contains('visible')).toBe(false);

      expandBtn?.dispatchEvent(new MouseEvent('click', { bubbles: true }));

      expect(taskTree?.classList.contains('visible')).toBe(true);
      expect(expandBtn.textContent).toBe('▼');
    });
  });

  describe('workspace tasks', () => {
    it('renders workspace expand button', () => {
      const element = sidebar.render();
      const workspaceExpandBtn = element.querySelector('[data-scope="workspace"] .sb-repo-expand');
      expect(workspaceExpandBtn).toBeTruthy();
    });

    it('renders workspace task tree container', () => {
      const element = sidebar.render();
      const workspaceTree = element.querySelector('#sb-task-tree-workspace');
      expect(workspaceTree).toBeTruthy();
    });

    it('shows workspace tasks with no repo', () => {
      setState('tasks', [
        {
          id: 'ws-task1',
          title: 'Workspace Task',
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

      const element = sidebar.render();
      const taskItem = element.querySelector('[data-task-id="ws-task1"]');
      expect(taskItem).toBeTruthy();
    });

    it('shows workspace tasks with multiple repos', () => {
      setState('tasks', [
        {
          id: 'multi-repo-task',
          title: 'Multi-Repo Task',
          description: '',
          repo: ['repo1', 'repo2'],
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

      const element = sidebar.render();
      const taskItem = element.querySelector('[data-task-id="multi-repo-task"]');
      expect(taskItem).toBeTruthy();
    });

    it('hides workspace expand button when no workspace tasks', () => {
      setState('tasks', [
        {
          id: 'repo-task',
          title: 'Repo Task',
          description: '',
          repo: ['test-repo'],
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

      const element = sidebar.render();
      const workspaceExpandBtn = element.querySelector('[data-scope="workspace"] .sb-repo-expand') as HTMLElement;
      expect(workspaceExpandBtn.style.display).toBe('none');
    });

    it('shows workspace expand button when workspace tasks exist', () => {
      setState('tasks', [
        {
          id: 'ws-task1',
          title: 'Workspace Task',
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

      const element = sidebar.render();
      const workspaceExpandBtn = element.querySelector('[data-scope="workspace"] .sb-repo-expand') as HTMLElement;
      expect(workspaceExpandBtn.style.display).toBe('block');
    });

    it('handles workspace expand toggle', () => {
      setState('tasks', [
        {
          id: 'ws-task1',
          title: 'Workspace Task',
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

      const element = sidebar.render();
      const expandBtn = element.querySelector('[data-scope="workspace"] .sb-repo-expand');
      const taskTree = element.querySelector('#sb-task-tree-workspace');

      expect(taskTree?.classList.contains('visible')).toBe(false);

      expandBtn?.dispatchEvent(new MouseEvent('click', { bubbles: true }));

      expect(taskTree?.classList.contains('visible')).toBe(true);
      expect(expandBtn?.textContent).toBe('▼');
    });
  });

  describe('workspace task highlighting', () => {
    it('highlights workspace when workspace task is selected', () => {
      setState('tasks', [
        {
          id: 'ws-task1',
          title: 'Workspace Task',
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
      setState('selectedTask', {
        id: 'ws-task1',
        title: 'Workspace Task',
        description: '',
        repo: [],
        role: 'coder',
        status: 'ready',
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
      });

      const element = sidebar.render();
      const workspaceItem = element.querySelector('[data-scope="workspace"]');
      expect(workspaceItem?.classList.contains('active')).toBe(true);
    });

    it('highlights workspace when multi-repo task is selected', () => {
      setState('tasks', [
        {
          id: 'multi-task',
          title: 'Multi-Repo Task',
          description: '',
          repo: ['repo1', 'repo2'],
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
      setState('selectedTask', {
        id: 'multi-task',
        title: 'Multi-Repo Task',
        description: '',
        repo: ['repo1', 'repo2'],
        role: 'coder',
        status: 'ready',
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
      });

      const element = sidebar.render();
      const workspaceItem = element.querySelector('[data-scope="workspace"]');
      expect(workspaceItem?.classList.contains('active')).toBe(true);
    });

    it('highlights repo when single-repo task is selected', () => {
      setState('repos', [
        { name: 'test-repo', remote: 'https://github.com/test/repo.git', local_path: '/test/repo', added: '2024-01-01' },
      ]);
      setState('tasks', [
        {
          id: 'repo-task',
          title: 'Repo Task',
          description: '',
          repo: ['test-repo'],
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
      setState('selectedTask', {
        id: 'repo-task',
        title: 'Repo Task',
        description: '',
        repo: ['test-repo'],
        role: 'coder',
        status: 'ready',
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
      });

      const element = sidebar.render();
      const repoItem = element.querySelector('[data-repo="test-repo"]');
      expect(repoItem?.classList.contains('active')).toBe(true);
    });

    it('expands workspace when workspace task is selected', () => {
      setState('tasks', [
        {
          id: 'ws-task1',
          title: 'Workspace Task',
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
      setState('selectedTask', {
        id: 'ws-task1',
        title: 'Workspace Task',
        description: '',
        repo: [],
        role: 'coder',
        status: 'ready',
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
      });

      const element = sidebar.render();
      const workspaceTree = element.querySelector('#sb-task-tree-workspace');
      expect(workspaceTree?.classList.contains('visible')).toBe(true);
    });

    it('handles workspace task click navigation', () => {
      setState('tasks', [
        {
          id: 'ws-task1',
          title: 'Workspace Task',
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

      const element = sidebar.render();
      
      // Expand workspace first
      const expandBtn = element.querySelector('[data-scope="workspace"] .sb-repo-expand');
      expandBtn?.dispatchEvent(new MouseEvent('click', { bubbles: true }));

      const taskItem = element.querySelector('[data-task-id="ws-task1"]');
      
      const pushStateSpy = vi.spyOn(window.history, 'pushState');
      const dispatchEventSpy = vi.spyOn(window, 'dispatchEvent');

      taskItem?.dispatchEvent(new MouseEvent('click', { bubbles: true }));

      expect(pushStateSpy).toHaveBeenCalledWith({}, '', '/task/ws-task1');
      expect(dispatchEventSpy).toHaveBeenCalledWith(expect.any(Event));
    });

    it('handles workspace task expand toggle', () => {
      const childTask = {
        id: 'child-task',
        title: 'Child Task',
        description: '',
        repo: [],
        role: 'coder' as const,
        status: 'ready' as const,
        branch: '',
        parent_task_id: 'ws-task1',
        depth: 1,
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
      };
      const parentTask = {
        id: 'ws-task1',
        title: 'Parent Workspace Task',
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
      };
      setState('tasks', [parentTask, childTask]);

      const element = sidebar.render();
      
      // Expand workspace first
      const expandBtn = element.querySelector('[data-scope="workspace"] .sb-repo-expand');
      expandBtn?.dispatchEvent(new MouseEvent('click', { bubbles: true }));

      const taskItem = element.querySelector('[data-task-id="ws-task1"]');
      const taskExpandBtn = taskItem?.querySelector('.sb-task-expand');
      
      // Task with children should show expand arrow
      expect(taskExpandBtn?.textContent).toBe('▶');
      
      // Click expand
      taskExpandBtn?.dispatchEvent(new MouseEvent('click', { bubbles: true }));
      
      // Child should now be visible
      const childItem = element.querySelector('[data-task-id="child-task"]');
      expect(childItem).toBeTruthy();
    });

    it('shows task with no children as leaf node with bullet', () => {
      setState('tasks', [
        {
          id: 'leaf-task',
          title: 'Leaf Task',
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

      const element = sidebar.render();
      
      // Expand workspace first
      const expandBtn = element.querySelector('[data-scope="workspace"] .sb-repo-expand');
      expandBtn?.dispatchEvent(new MouseEvent('click', { bubbles: true }));

      const taskItem = element.querySelector('[data-task-id="leaf-task"]');
      const taskExpandBtn = taskItem?.querySelector('.sb-task-expand');
      
      // Task with no children should show bullet
      expect(taskExpandBtn?.textContent).toBe('•');
    });
  });

  describe('multi-repo tasks', () => {
    it('displays multi-repo task under workspace', () => {
      setState('repos', [
        { name: 'repo1', remote: 'https://github.com/test/repo1.git', local_path: '/test/repo1', added: '2024-01-01' },
        { name: 'repo2', remote: 'https://github.com/test/repo2.git', local_path: '/test/repo2', added: '2024-01-01' },
      ]);
      setState('tasks', [
        {
          id: 'multi-task',
          title: 'Multi-Repo Task',
          description: '',
          repo: ['repo1', 'repo2'],
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

      const element = sidebar.render();
      
      // Expand workspace
      const workspaceExpandBtn = element.querySelector('[data-scope="workspace"] .sb-repo-expand');
      workspaceExpandBtn?.dispatchEvent(new MouseEvent('click', { bubbles: true }));
      
      // Task should be in workspace
      const workspaceTask = element.querySelector('#sb-task-tree-workspace [data-task-id="multi-task"]');
      expect(workspaceTask).toBeTruthy();
    });

    it('displays multi-repo task under each repo', () => {
      setState('repos', [
        { name: 'repo1', remote: 'https://github.com/test/repo1.git', local_path: '/test/repo1', added: '2024-01-01' },
        { name: 'repo2', remote: 'https://github.com/test/repo2.git', local_path: '/test/repo2', added: '2024-01-01' },
      ]);
      setState('tasks', [
        {
          id: 'multi-task',
          title: 'Multi-Repo Task',
          description: '',
          repo: ['repo1', 'repo2'],
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

      const element = sidebar.render();
      
      // Expand repo1
      const repo1ExpandBtn = element.querySelector('[data-repo="repo1"] .sb-repo-expand');
      repo1ExpandBtn?.dispatchEvent(new MouseEvent('click', { bubbles: true }));
      
      // Task should be in repo1
      const repo1Task = element.querySelector('#sb-task-tree-repo1 [data-task-id="multi-task"]');
      expect(repo1Task).toBeTruthy();
      
      // Expand repo2
      const repo2ExpandBtn = element.querySelector('[data-repo="repo2"] .sb-repo-expand');
      repo2ExpandBtn?.dispatchEvent(new MouseEvent('click', { bubbles: true }));
      
      // Task should also be in repo2
      const repo2Task = element.querySelector('#sb-task-tree-repo2 [data-task-id="multi-task"]');
      expect(repo2Task).toBeTruthy();
    });
  });
});
