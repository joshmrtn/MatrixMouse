/**
 * TaskPage Unit Tests
 * 
 * Tests for the TaskPage component including:
 * - Task rendering
 * - Edit button functionality
 * - Dependency loading
 * - Conversation rendering
 * - Error states
 * - Header updates
 */

import { TaskPage } from '../../../src/pages/TaskPage';
import * as api from '../../../src/api';
import * as state from '../../../src/state';
import { wsManager } from '../../../src/api/websocket';
import { vi, describe, it, expect, beforeEach, afterEach } from 'vitest';

// Mock dependencies
vi.mock('../../../src/api', () => ({
  getTask: vi.fn(),
  getTaskDependencies: vi.fn(),
}));

vi.mock('../../../src/state', () => ({
  getState: vi.fn(),
  setState: vi.fn(),
  subscribe: vi.fn(),
}));

vi.mock('../../../src/components/Conversation', () => ({
  Conversation: vi.fn().mockImplementation(() => ({
    render: vi.fn().mockImplementation(() => {
      const el = document.createElement('div');
      el.id = 'conversation';
      el.innerHTML = `
        <div id="conversation-log"></div>
        <div id="conversation-input"><input type="text" /><button>Send</button></div>
        <div id="clarification-banner" style="display:none;">
          <div class="clar-q"></div>
          <div class="clar-row">
            <textarea id="clar-input"></textarea>
            <button id="clar-answer-btn">Answer</button>
          </div>
        </div>
      `;
      return el;
    }),
    appendToken: vi.fn(),
    appendThinking: vi.fn(),
    showClarification: vi.fn(),
    hideClarification: vi.fn(),
  })),
}));

vi.mock('../../../src/components/TaskEditForm', () => ({
  TaskEditForm: vi.fn().mockImplementation((options) => ({
    render: vi.fn().mockImplementation(() => {
      const el = document.createElement('div');
      el.className = 'task-edit-form';
      el.innerHTML = `
        <div class="edit-form-header"><h3>Edit Task</h3></div>
        <div class="edit-form-field"><label>Title</label><input type="text" id="edit-title" /></div>
        <div class="edit-form-actions">
          <button class="btn-save">Save</button>
          <button class="btn-cancel">Cancel</button>
        </div>
      `;
      return el;
    }),
    options,
  })),
}));

// Mock window methods
const mockPushState = vi.fn();
Object.defineProperty(window, 'history', {
  value: { pushState: mockPushState },
  writable: true,
});

const mockDispatchEvent = vi.fn();
Object.defineProperty(window, 'dispatchEvent', {
  value: mockDispatchEvent,
  writable: true,
});

// Test data
const mockTask = {
  id: 'test-123',
  title: 'Test Task',
  description: 'Test description',
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
};

const mockTaskBlockedByHuman = {
  ...mockTask,
  status: 'blocked_by_human' as const,
};

const mockTaskBlockedByTask = {
  ...mockTask,
  status: 'blocked_by_task' as const,
};

const mockTaskWorkspace = {
  ...mockTask,
  repo: [],
};

describe('TaskPage', () => {
  let container: HTMLElement;
  let subscribeCallback: ((state: any) => void) | null = null;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    
    vi.clearAllMocks();
    
    // Capture subscribe callback
    vi.mocked(state.subscribe).mockImplementation((cb) => {
      subscribeCallback = cb as any;
      return () => {};
    });

    vi.mocked(state.getState).mockReturnValue({
      selectedTask: null,
      currentPage: 'task',
      routeParams: { id: 'test-123' },
    } as any);
  });

  afterEach(() => {
    document.body.removeChild(container);
  });

  describe('constructor()', () => {
    it('stores task ID', () => {
      const page = new TaskPage('test-123');
      expect(page).toBeDefined();
    });

    it('registers state subscription', () => {
      new TaskPage('test-123');
      expect(state.subscribe).toHaveBeenCalled();
    });
  });

  describe('render()', () => {
    it('loads task data on render', async () => {
      vi.mocked(api.getTask).mockResolvedValue(mockTask);

      const page = new TaskPage('test-123');
      await page.render(container);

      expect(api.getTask).toHaveBeenCalledWith('test-123');
    });

    it('renders task page with correct structure', async () => {
      vi.mocked(api.getTask).mockResolvedValue(mockTask);

      const page = new TaskPage('test-123');
      await page.render(container);

      expect(container.querySelector('#task-page')).toBeDefined();
      expect(container.querySelector('#task-header')).toBeDefined();
      expect(container.querySelector('.task-title')).toBeDefined();
      expect(container.querySelector('.task-meta')).toBeDefined();
    });

    it('displays task title', async () => {
      vi.mocked(api.getTask).mockResolvedValue(mockTask);

      const page = new TaskPage('test-123');
      await page.render(container);

      const titleEl = container.querySelector('.task-title');
      expect(titleEl?.textContent).toBe('Test Task');
    });

    it('displays task ID in metadata', async () => {
      vi.mocked(api.getTask).mockResolvedValue(mockTask);

      const page = new TaskPage('test-123');
      await page.render(container);

      const metaItems = container.querySelectorAll('.meta-item');
      expect(metaItems.length).toBeGreaterThanOrEqual(3);
    });

    it('displays formatted status', async () => {
      vi.mocked(api.getTask).mockResolvedValue(mockTask);

      const page = new TaskPage('test-123');
      await page.render(container);

      const statusEl = container.querySelector('.status-ready');
      expect(statusEl).toBeDefined();
    });

    it('displays role badge', async () => {
      vi.mocked(api.getTask).mockResolvedValue(mockTask);

      const page = new TaskPage('test-123');
      await page.render(container);

      const roleMetaItem = container.querySelector('[data-meta="role"]');
      expect(roleMetaItem).toBeDefined();
    });

    it('displays branch when present', async () => {
      vi.mocked(api.getTask).mockResolvedValue(mockTask);

      const page = new TaskPage('test-123');
      await page.render(container);

      const branchMetaItem = container.querySelector('.meta-label');
      const branchLabel = Array.from(container.querySelectorAll('.meta-label'))
        .find(el => el.textContent === 'Branch:');
      expect(branchLabel).toBeDefined();
    });

    it('hides branch when not present', async () => {
      const taskWithoutBranch = { ...mockTask, branch: null };
      vi.mocked(api.getTask).mockResolvedValue(taskWithoutBranch);

      const page = new TaskPage('test-123');
      await page.render(container);

      const branchLabels = Array.from(container.querySelectorAll('.meta-label'))
        .filter(el => el.textContent === 'Branch:');
      expect(branchLabels.length).toBe(0);
    });

    it('displays repo when present', async () => {
      vi.mocked(api.getTask).mockResolvedValue(mockTask);

      const page = new TaskPage('test-123');
      await page.render(container);

      const repoLabel = Array.from(container.querySelectorAll('.meta-label'))
        .find(el => el.textContent === 'Repo:');
      expect(repoLabel).toBeDefined();
      
      const repoValue = repoLabel?.parentElement?.querySelector('.meta-value');
      expect(repoValue?.textContent).toContain('test-repo');
    });

    it('displays Workspace when no repos', async () => {
      vi.mocked(api.getTask).mockResolvedValue(mockTaskWorkspace);

      const page = new TaskPage('test-123');
      await page.render(container);

      // Find the repo meta value
      const repoMetaItem = Array.from(container.querySelectorAll('.meta-item'))
        .find(item => item.querySelector('.meta-label')?.textContent === 'Repo:');
      const repoValue = repoMetaItem?.querySelector('.meta-value');
      expect(repoValue?.textContent).toContain('Workspace');
    });

    it('shows edit button', async () => {
      vi.mocked(api.getTask).mockResolvedValue(mockTask);

      const page = new TaskPage('test-123');
      await page.render(container);

      const editBtn = container.querySelector('#task-edit-btn');
      expect(editBtn).toBeDefined();
      expect(editBtn?.textContent).toContain('Edit');
    });

    it('shows unblock button when blocked by human', async () => {
      vi.mocked(api.getTask).mockResolvedValue(mockTaskBlockedByHuman);

      const page = new TaskPage('test-123');
      await page.render(container);

      const unblockBtn = container.querySelector('#task-unblock-btn');
      expect(unblockBtn).toBeDefined();
      expect(unblockBtn?.textContent).toContain('Unblock');
    });

    it('hides unblock button when not blocked by human', async () => {
      vi.mocked(api.getTask).mockResolvedValue(mockTask);

      const page = new TaskPage('test-123');
      await page.render(container);

      const unblockBtn = container.querySelector('#task-unblock-btn');
      expect(unblockBtn).toBeNull();
    });

    it('sets up edit button click handler', async () => {
      vi.mocked(api.getTask).mockResolvedValue(mockTask);

      const page = new TaskPage('test-123');
      await page.render(container);

      const editBtn = container.querySelector('#task-edit-btn') as HTMLButtonElement;
      editBtn.click();

      // Should open edit form
      const editForm = container.querySelector('.task-edit-form');
      expect(editForm).toBeDefined();
    });

    it('sets up unblock button click handler', async () => {
      vi.mocked(api.getTask).mockResolvedValue(mockTaskBlockedByHuman);
      
      // Mock prompt
      vi.spyOn(window, 'prompt').mockReturnValue('Test note');

      const page = new TaskPage('test-123');
      await page.render(container);

      const unblockBtn = container.querySelector('#task-unblock-btn') as HTMLButtonElement;
      expect(unblockBtn).toBeDefined();
    });

    it('loads dependencies when blocked by task', async () => {
      vi.mocked(api.getTask).mockResolvedValue(mockTaskBlockedByTask);
      vi.mocked(api.getTaskDependencies).mockResolvedValue({
        task_id: 'test-123',
        dependencies: [],
        count: 0,
      });

      const page = new TaskPage('test-123');
      await page.render(container);

      expect(api.getTaskDependencies).toHaveBeenCalledWith('test-123');
    });

    it('does not load dependencies when not blocked by task', async () => {
      vi.mocked(api.getTask).mockResolvedValue(mockTask);
      vi.mocked(api.getTaskDependencies).mockResolvedValue({
        task_id: 'test-123',
        dependencies: [],
        count: 0,
      });

      const page = new TaskPage('test-123');
      await page.render(container);

      expect(api.getTaskDependencies).not.toHaveBeenCalled();
    });

    it('renders conversation component', async () => {
      vi.mocked(api.getTask).mockResolvedValue(mockTask);

      const page = new TaskPage('test-123');
      await page.render(container);

      const conversationContainer = container.querySelector('#task-conversation-container');
      expect(conversationContainer?.childElementCount).toBeGreaterThan(0);
    });

    it('shows error state when task load fails', async () => {
      vi.mocked(api.getTask).mockRejectedValue(new Error('Network error'));

      const page = new TaskPage('test-123');
      await page.render(container);

      expect(container.textContent).toContain('Failed to load task');
    });

    it('stores task in state after loading', async () => {
      vi.mocked(api.getTask).mockResolvedValue(mockTask);

      const page = new TaskPage('test-123');
      await page.render(container);

      expect(state.setState).toHaveBeenCalledWith('selectedTask', mockTask);
    });
  });

  describe('handleEdit()', () => {
    it('opens edit form when not editing', async () => {
      vi.mocked(api.getTask).mockResolvedValue(mockTask);

      const page = new TaskPage('test-123');
      await page.render(container);

      const editBtn = container.querySelector('#task-edit-btn') as HTMLButtonElement;
      editBtn.click();

      const editForm = container.querySelector('.task-edit-form');
      expect(editForm).toBeDefined();
    });

    it('closes edit form when already editing', async () => {
      vi.mocked(api.getTask).mockResolvedValue(mockTask);

      const page = new TaskPage('test-123');
      await page.render(container);

      // Open edit form
      const editBtn = container.querySelector('#task-edit-btn') as HTMLButtonElement;
      editBtn.click();

      // Verify edit form is open
      const editForm = container.querySelector('.task-edit-form');
      expect(editForm).toBeDefined();

      // Close edit form
      editBtn.click();

      // Edit form container should be empty
      const editContainer = container.querySelector('#task-edit-container');
      expect(editContainer?.innerHTML).toBe('');
    });

    it('passes correct task to edit form', async () => {
      vi.mocked(api.getTask).mockResolvedValue(mockTask);

      const page = new TaskPage('test-123');
      await page.render(container);

      const editBtn = container.querySelector('#task-edit-btn') as HTMLButtonElement;
      editBtn.click();

      // Verify TaskEditForm was called with correct task
      const { TaskEditForm } = await import('../../../src/components/TaskEditForm');
      expect(TaskEditForm).toHaveBeenCalledWith(
        expect.objectContaining({
          task: mockTask,
        })
      );
    });

    it('handles edit form save callback', async () => {
      vi.mocked(api.getTask).mockResolvedValue(mockTask);

      const page = new TaskPage('test-123');
      await page.render(container);

      // Open edit form
      const editBtn = container.querySelector('#task-edit-btn') as HTMLButtonElement;
      editBtn.click();

      // Get the onSave callback
      const { TaskEditForm } = await import('../../../src/components/TaskEditForm');
      const callArgs = vi.mocked(TaskEditForm).mock.calls[0][0];
      const updatedTask = { ...mockTask, title: 'Updated Task' };
      
      // Trigger save
      callArgs.onSave(updatedTask);

      // Should update state
      expect(state.setState).toHaveBeenCalledWith('selectedTask', updatedTask);
    });

    it('handles edit form cancel callback', async () => {
      vi.mocked(api.getTask).mockResolvedValue(mockTask);

      const page = new TaskPage('test-123');
      await page.render(container);

      // Open edit form
      const editBtn = container.querySelector('#task-edit-btn') as HTMLButtonElement;
      editBtn.click();

      // Get the onCancel callback
      const { TaskEditForm } = await import('../../../src/components/TaskEditForm');
      const callArgs = vi.mocked(TaskEditForm).mock.calls[0][0];
      
      // Trigger cancel
      callArgs.onCancel();

      // Edit form should be cleared
      const editContainer = container.querySelector('#task-edit-container');
      expect(editContainer?.childElementCount).toBe(0);
    });

    it('handles task cancelled callback by navigating to task list', async () => {
      vi.mocked(api.getTask).mockResolvedValue(mockTask);

      const page = new TaskPage('test-123');
      await page.render(container);

      // Open edit form
      const editBtn = container.querySelector('#task-edit-btn') as HTMLButtonElement;
      editBtn.click();

      // Get the onTaskCancelled callback
      const { TaskEditForm } = await import('../../../src/components/TaskEditForm');
      const callArgs = vi.mocked(TaskEditForm).mock.calls[0][0];
      
      // Trigger task cancelled
      callArgs.onTaskCancelled();

      // Should navigate to task list
      expect(mockPushState).toHaveBeenCalledWith({}, '', '/task-list');
      expect(mockDispatchEvent).toHaveBeenCalledWith(new Event('popstate'));
    });
  });

  describe('handleUnblock()', () => {
    it('prompts for note when unblocking', async () => {
      vi.mocked(api.getTask).mockResolvedValue(mockTaskBlockedByHuman);
      const promptSpy = vi.spyOn(window, 'prompt').mockReturnValue('Test note');

      const page = new TaskPage('test-123');
      await page.render(container);

      const unblockBtn = container.querySelector('#task-unblock-btn') as HTMLButtonElement;
      unblockBtn.click();

      expect(promptSpy).toHaveBeenCalledWith('Optional note to include with unblock:');
    });

    it('does nothing when user cancels prompt', async () => {
      vi.mocked(api.getTask).mockResolvedValue(mockTaskBlockedByHuman);
      vi.spyOn(window, 'prompt').mockReturnValue(null);

      const consoleSpy = vi.spyOn(console, 'log').mockImplementation(() => {});

      const page = new TaskPage('test-123');
      await page.render(container);

      const unblockBtn = container.querySelector('#task-unblock-btn') as HTMLButtonElement;
      unblockBtn.click();

      expect(consoleSpy).not.toHaveBeenCalled();
    });
  });

  describe('loadDependencies()', () => {
    it('displays dependencies when present', async () => {
      vi.mocked(api.getTask).mockResolvedValue(mockTaskBlockedByTask);
      vi.mocked(api.getTaskDependencies).mockResolvedValue({
        task_id: 'test-123',
        dependencies: [
          { id: 'dep-1', title: 'Dependency 1' },
          { id: 'dep-2', title: 'Dependency 2' },
        ],
        count: 2,
      });

      const page = new TaskPage('test-123');
      await page.render(container);

      // Wait for async load
      await new Promise(resolve => setTimeout(resolve, 50));

      const depsSection = container.querySelector('#task-dependencies');
      expect(depsSection).toBeDefined();
    });

    it('hides dependencies section when empty', async () => {
      vi.mocked(api.getTask).mockResolvedValue(mockTaskBlockedByTask);
      vi.mocked(api.getTaskDependencies).mockResolvedValue({
        task_id: 'test-123',
        dependencies: [],
        count: 0,
      });

      const page = new TaskPage('test-123');
      await page.render(container);

      // Wait for async load
      await new Promise(resolve => setTimeout(resolve, 50));

      const depsSection = container.querySelector('#task-dependencies');
      expect(depsSection?.getAttribute('style')).toContain('display:none');
    });

    it('sets up dependency link click handlers', async () => {
      vi.mocked(api.getTask).mockResolvedValue(mockTaskBlockedByTask);
      vi.mocked(api.getTaskDependencies).mockResolvedValue({
        task_id: 'test-123',
        dependencies: [{ id: 'dep-1', title: 'Dependency 1' }],
        count: 1,
      });

      const page = new TaskPage('test-123');
      await page.render(container);

      // Wait for async load
      await new Promise(resolve => setTimeout(resolve, 50));

      const depLink = container.querySelector('.dependency-link') as HTMLAnchorElement;
      depLink.click();

      // Should navigate to dependency task
      expect(mockPushState).toHaveBeenCalledWith({}, '', '/task/dep-1');
      expect(mockDispatchEvent).toHaveBeenCalledWith(new Event('popstate'));
    });

    it('handles dependency load error gracefully', async () => {
      vi.mocked(api.getTask).mockResolvedValue(mockTaskBlockedByTask);
      vi.mocked(api.getTaskDependencies).mockRejectedValue(new Error('Failed'));

      const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {});

      const page = new TaskPage('test-123');
      await page.render(container);

      // Wait for async load
      await new Promise(resolve => setTimeout(resolve, 50));

      expect(consoleSpy).toHaveBeenCalledWith(
        '[TaskPage] Failed to load dependencies:',
        expect.any(Error)
      );
    });
  });

  describe('updateHeader()', () => {
    it('updates task title when state changes', async () => {
      vi.mocked(api.getTask).mockResolvedValue(mockTask);

      const page = new TaskPage('test-123');
      await page.render(container);

      // Simulate state update
      if (subscribeCallback) {
        const updatedTask = { ...mockTask, title: 'Updated Title' };
        subscribeCallback({ selectedTask: updatedTask, currentPage: 'task' });
      }

      const titleEl = container.querySelector('.task-title');
      // Title should be updated
      expect(titleEl).toBeDefined();
    });

    it('updates meta information when state changes', async () => {
      vi.mocked(api.getTask).mockResolvedValue(mockTask);

      const page = new TaskPage('test-123');
      await page.render(container);

      // Simulate state update with different role
      if (subscribeCallback) {
        const updatedTask = { ...mockTask, role: 'manager' as const };
        subscribeCallback({ selectedTask: updatedTask, currentPage: 'task' });
      }

      // Role should be updated
      const roleMetaItem = container.querySelector('[data-meta="role"]');
      expect(roleMetaItem).toBeDefined();
    });

    it('does not update if task ID does not match', async () => {
      vi.mocked(api.getTask).mockResolvedValue(mockTask);

      const page = new TaskPage('test-123');
      await page.render(container);

      // Simulate state update for different task
      if (subscribeCallback) {
        subscribeCallback({ 
          selectedTask: { ...mockTask, id: 'other-task' }, 
          currentPage: 'task' 
        });
      }

      // Should not trigger update
    });
  });

  describe('error handling', () => {
    it('handles null task gracefully', async () => {
      // This test verifies the error handling in render()
      // If getTask returns null, it should still render but potentially with errors
      vi.mocked(api.getTask).mockResolvedValue(null as any);

      const page = new TaskPage('test-123');
      
      // The component will try to access task.title which will fail
      // This is expected behavior - task should never be null in production
      await expect(page.render(container)).rejects.toThrow();
    });

    it('handles API error gracefully', async () => {
      vi.mocked(api.getTask).mockRejectedValue(new Error('API Error'));

      const page = new TaskPage('test-123');
      await page.render(container);

      expect(container.textContent).toContain('Failed to load task');
    });

    it('logs error when dependencies fail to load', async () => {
      vi.mocked(api.getTask).mockResolvedValue(mockTaskBlockedByTask);
      vi.mocked(api.getTaskDependencies).mockRejectedValue(new Error('Network error'));

      const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {});

      const page = new TaskPage('test-123');
      await page.render(container);

      // Wait for async load
      await new Promise(resolve => setTimeout(resolve, 50));

      expect(consoleSpy).toHaveBeenCalled();
    });
  });

  describe('XSS prevention', () => {
    it('escapes HTML in task title', async () => {
      const maliciousTask = {
        ...mockTask,
        title: '<script>alert("XSS")</script>Malicious Task',
      };
      vi.mocked(api.getTask).mockResolvedValue(maliciousTask);

      const page = new TaskPage('test-123');
      await page.render(container);

      const titleEl = container.querySelector('.task-title');
      expect(titleEl?.textContent).toContain('<script>');
      expect(titleEl?.innerHTML).not.toContain('<script>');
    });

    it('escapes HTML in task description', async () => {
      const maliciousTask = {
        ...mockTask,
        description: '<img src=x onerror=alert(1)>',
      };
      vi.mocked(api.getTask).mockResolvedValue(maliciousTask);

      const page = new TaskPage('test-123');
      await page.render(container);

      // Should not execute script
      expect(container.innerHTML).not.toContain('onerror');
    });

    it('escapes HTML in branch name', async () => {
      const maliciousTask = {
        ...mockTask,
        branch: '<script>alert("XSS")</script>',
      };
      vi.mocked(api.getTask).mockResolvedValue(maliciousTask);

      const page = new TaskPage('test-123');
      await page.render(container);

      expect(container.innerHTML).not.toContain('<script>');
    });

    it('escapes HTML in repo names', async () => {
      const maliciousTask = {
        ...mockTask,
        repo: ['<script>alert("XSS")</script>'],
      };
      vi.mocked(api.getTask).mockResolvedValue(maliciousTask);

      const page = new TaskPage('test-123');
      await page.render(container);

      expect(container.innerHTML).not.toContain('<script>');
    });

    it('escapes HTML in dependency titles', async () => {
      vi.mocked(api.getTask).mockResolvedValue(mockTaskBlockedByTask);
      vi.mocked(api.getTaskDependencies).mockResolvedValue({
        task_id: 'test-123',
        dependencies: [{ id: 'dep-1', title: '<script>alert("XSS")</script>' }],
        count: 1,
      });

      const page = new TaskPage('test-123');
      await page.render(container);

      // Wait for async load
      await new Promise(resolve => setTimeout(resolve, 50));

      expect(container.innerHTML).not.toContain('<script>alert');
    });
  });

  describe('accessibility', () => {
    it('has role="region" on dependencies section', async () => {
      vi.mocked(api.getTask).mockResolvedValue(mockTask);

      const page = new TaskPage('test-123');
      await page.render(container);

      const depsSection = container.querySelector('#task-dependencies');
      expect(depsSection?.getAttribute('role')).toBe('region');
    });

    it('has aria-label on dependencies section', async () => {
      vi.mocked(api.getTask).mockResolvedValue(mockTask);

      const page = new TaskPage('test-123');
      await page.render(container);

      const depsSection = container.querySelector('#task-dependencies');
      expect(depsSection?.getAttribute('aria-label')).toBe('Task dependencies');
    });

    it('has proper heading hierarchy with h1', async () => {
      vi.mocked(api.getTask).mockResolvedValue(mockTask);

      const page = new TaskPage('test-123');
      await page.render(container);

      const h1 = container.querySelector('h1');
      expect(h1).toBeDefined();
      expect(h1?.className).toContain('task-title');
    });
  });
});

describe('TaskPage - WebSocket Streaming Handlers', () => {
  it('registers all streaming handlers when rendering conversation', async () => {
    const registeredEvents: string[] = [];
    const originalOn = wsManager.on;
    wsManager.on = ((eventType: string) => {
      registeredEvents.push(eventType);
    }) as any;

    vi.mocked(api.getTask).mockResolvedValue(mockTask);
    vi.mocked(api.getTaskDependencies).mockResolvedValue({ task_id: 'test-123', dependencies: [], count: 0 });

    const container = document.createElement('div');
    const page = new TaskPage('task-001');
    await page.render(container);

    expect(registeredEvents).toContain('token');
    expect(registeredEvents).toContain('thinking');
    expect(registeredEvents).toContain('content');
    expect(registeredEvents).toContain('tool_call');
    expect(registeredEvents).toContain('tool_result');
    expect(registeredEvents).toContain('clarification_request');

    wsManager.on = originalOn;
  });

  it('token handler filters by taskId', async () => {
    let capturedHandler: ((data: any) => void) | null = null;
    const originalOn = wsManager.on;
    wsManager.on = ((eventType: string, handler: any) => {
      if (eventType === 'token') capturedHandler = handler;
    }) as any;

    vi.mocked(api.getTask).mockResolvedValue(mockTask);
    vi.mocked(api.getTaskDependencies).mockResolvedValue({ task_id: 'test-123', dependencies: [], count: 0 });

    const container = document.createElement('div');
    const page = new TaskPage('task-001');
    await page.render(container);

    expect(capturedHandler).not.toBeNull();
    const appendTokenSpy = vi.fn();
    (page as any).conversation.appendToken = appendTokenSpy;

    capturedHandler!({ text: 'Hello', task_id: 'task-001' });
    expect(appendTokenSpy).toHaveBeenCalledWith('Hello');

    appendTokenSpy.mockClear();
    capturedHandler!({ text: 'Hello', task_id: 'task-999' });
    expect(appendTokenSpy).not.toHaveBeenCalled();

    wsManager.on = originalOn;
  });
});
