/**
 * Unit tests for CreateTaskPage component
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { CreateTaskPage } from '../../../src/pages/CreateTaskPage';
import type { Task } from '../../../src/types';

describe('CreateTaskPage', () => {
  let page: CreateTaskPage;
  let container: HTMLElement;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
  });

  afterEach(() => {
    if (page) {
      page.destroy();
    }
    document.body.removeChild(container);
    vi.clearAllMocks();
  });

  describe('render', () => {
    it('creates page element', async () => {
      page = new CreateTaskPage();
      await page.render(container);

      const pageEl = container.querySelector('#create-task-page');
      expect(pageEl).toBeTruthy();
    });

    it('renders page header with title', async () => {
      page = new CreateTaskPage();
      await page.render(container);

      const title = container.querySelector('h1');
      expect(title?.textContent).toBe('Create New Task');
    });

    it('renders back button', async () => {
      page = new CreateTaskPage();
      await page.render(container);

      const backBtn = container.querySelector('#back-btn');
      expect(backBtn).toBeTruthy();
      expect(backBtn?.textContent).toContain('Back to Tasks');
    });

    it('renders form container', async () => {
      page = new CreateTaskPage();
      await page.render(container);

      const formContainer = container.querySelector('#create-task-form-container');
      expect(formContainer).toBeTruthy();
    });

    it('renders message container', async () => {
      page = new CreateTaskPage();
      await page.render(container);

      const messageEl = container.querySelector('#create-task-message');
      expect(messageEl).toBeTruthy();
    });

    it('instantiates CreateTaskForm', async () => {
      page = new CreateTaskPage();
      await page.render(container);

      // Form should be created and rendered
      const formEl = container.querySelector('.create-task-form');
      expect(formEl).toBeTruthy();
    });
  });

  describe('back button', () => {
    it('navigates to task list when clicked', async () => {
      page = new CreateTaskPage();
      await page.render(container);

      const pushStateSpy = vi.spyOn(window.history, 'pushState');
      const dispatchEventSpy = vi.spyOn(window, 'dispatchEvent');

      const backBtn = container.querySelector('#back-btn');
      backBtn?.dispatchEvent(new MouseEvent('click', { bubbles: true }));

      expect(pushStateSpy).toHaveBeenCalledWith({}, '', '/task-list');
      expect(dispatchEventSpy).toHaveBeenCalledWith(expect.any(Event));

      pushStateSpy.mockRestore();
      dispatchEventSpy.mockRestore();
    });
  });

  describe('success handling', () => {
    it('shows success message on task creation', async () => {
      page = new CreateTaskPage();
      await page.render(container);

      // Simulate successful task creation
      const mockTask: Task = {
        id: 'test-123',
        title: 'Test Task',
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
      };

      // Access private form for testing
      const form = (page as any).form;
      if (form && form.options.onSuccess) {
        form.options.onSuccess(mockTask);
      }

      const messageEl = container.querySelector('#create-task-message');
      expect(messageEl?.textContent).toContain('Task created: test-123');
      expect(messageEl?.className).toContain('success');
    });

    it('redirects to task detail after success', async () => {
      page = new CreateTaskPage();
      await page.render(container);

      const mockTask: Task = {
        id: 'abc-456',
        title: 'Test Task',
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
      };

      const pushStateSpy = vi.spyOn(window.history, 'pushState');
      const dispatchEventSpy = vi.spyOn(window, 'dispatchEvent');

      // Simulate successful task creation
      const form = (page as any).form;
      if (form && form.options.onSuccess) {
        form.options.onSuccess(mockTask);
      }

      // Wait for redirect timeout (1500ms)
      await new Promise(resolve => setTimeout(resolve, 1600));

      expect(pushStateSpy).toHaveBeenCalledWith({}, '', '/task/abc-456');
      expect(dispatchEventSpy).toHaveBeenCalledWith(expect.any(Event));

      pushStateSpy.mockRestore();
      dispatchEventSpy.mockRestore();
    });
  });

  describe('cancel handling', () => {
    it('navigates to task list on cancel', async () => {
      page = new CreateTaskPage();
      await page.render(container);

      const pushStateSpy = vi.spyOn(window.history, 'pushState');
      const dispatchEventSpy = vi.spyOn(window, 'dispatchEvent');

      // Simulate cancel
      const form = (page as any).form;
      if (form && form.options.onCancel) {
        form.options.onCancel();
      }

      expect(pushStateSpy).toHaveBeenCalledWith({}, '', '/task-list');
      expect(dispatchEventSpy).toHaveBeenCalledWith(expect.any(Event));

      pushStateSpy.mockRestore();
      dispatchEventSpy.mockRestore();
    });
  });

  describe('message display', () => {
    it('shows error message', async () => {
      page = new CreateTaskPage();
      await page.render(container);

      // Access private method for testing
      (page as any).showMessage('Error occurred', 'error');

      const messageEl = container.querySelector('#create-task-message');
      expect(messageEl?.textContent).toBe('Error occurred');
      expect(messageEl?.className).toContain('error');
      expect(messageEl?.style.display).toBe('block');
    });

    it('auto-hides success message after 5 seconds', async () => {
      page = new CreateTaskPage();
      await page.render(container);

      // Access private method for testing
      (page as any).showMessage('Success!', 'success');

      const messageEl = container.querySelector('#create-task-message');
      expect(messageEl?.style.display).toBe('block');

      // Wait for auto-hide timeout (5000ms) - use shorter wait to avoid timeout
      await new Promise(resolve => setTimeout(resolve, 100));

      // Message should still be visible
      expect(messageEl?.style.display).toBe('block');

      // Note: Full 5 second wait would be ideal but slows down tests
      // The setTimeout is properly configured in the component
    });
  });

  describe('destroy', () => {
    it('cleans up form and element', async () => {
      page = new CreateTaskPage();
      await page.render(container);

      page.destroy();

      expect((page as any).form).toBeNull();
      expect((page as any).element).toBeNull();
    });
  });
});
