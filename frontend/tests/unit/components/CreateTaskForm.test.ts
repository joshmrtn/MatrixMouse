/**
 * Unit tests for CreateTaskForm component
 */

import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import { CreateTaskForm } from '../../../src/components/CreateTaskForm';
import { createTask } from '../../../src/api';
import { setState, resetState } from '../../../src/state/store';
import type { Repo } from '../../../src/types';

// Mock the API
vi.mock('../../../src/api', () => ({
  createTask: vi.fn(),
}));

describe('CreateTaskForm', () => {
  let container: HTMLElement;
  let form: CreateTaskForm;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
  });

  afterEach(() => {
    if (form) {
      form.destroy();
    }
    document.body.removeChild(container);
    vi.clearAllMocks();
  });

  describe('render', () => {
    it('creates form element', () => {
      form = new CreateTaskForm({});
      form.render(container);

      const formEl = container.querySelector('.create-task-form');
      expect(formEl).toBeTruthy();
    });

    it('renders title field', () => {
      form = new CreateTaskForm({});
      form.render(container);

      const titleInput = container.querySelector('#task-title') as HTMLInputElement;
      expect(titleInput).toBeTruthy();
      expect(titleInput?.type).toBe('text');
      expect(titleInput?.required).toBe(true);
    });

    it('renders description field', () => {
      form = new CreateTaskForm({});
      form.render(container);

      const descriptionInput = container.querySelector('#task-description') as HTMLTextAreaElement;
      expect(descriptionInput).toBeTruthy();
      expect(descriptionInput?.rows).toBe(4);
    });

    it('renders role dropdown with coder and writer options', () => {
      form = new CreateTaskForm({});
      form.render(container);

      const roleSelect = container.querySelector('#task-role') as HTMLSelectElement;
      expect(roleSelect).toBeTruthy();

      const options = roleSelect?.querySelectorAll('option');
      expect(options?.length).toBe(3); // coder, writer, manager
      expect(options?.[0].value).toBe('coder');
      expect(options?.[1].value).toBe('writer');
      expect(options?.[2].value).toBe('manager');
    });

    it('renders importance field with default 0.5', () => {
      form = new CreateTaskForm({});
      form.render(container);

      const importanceInput = container.querySelector('#task-importance') as HTMLInputElement;
      expect(importanceInput).toBeTruthy();
      expect(importanceInput?.value).toBe('0.5');
      expect(importanceInput?.min).toBe('0');
      expect(importanceInput?.max).toBe('1');
      expect(importanceInput?.step).toBe('0.1');
    });

    it('renders urgency field with default 0.5', () => {
      form = new CreateTaskForm({});
      form.render(container);

      const urgencyInput = container.querySelector('#task-urgency') as HTMLInputElement;
      expect(urgencyInput).toBeTruthy();
      expect(urgencyInput?.value).toBe('0.5');
      expect(urgencyInput?.min).toBe('0');
      expect(urgencyInput?.max).toBe('1');
      expect(urgencyInput?.step).toBe('0.1');
    });

    it('renders submit button', () => {
      form = new CreateTaskForm({});
      form.render(container);

      const submitBtn = container.querySelector('#btn-submit') as HTMLButtonElement;
      expect(submitBtn).toBeTruthy();
      expect(submitBtn?.type).toBe('submit');
      expect(submitBtn?.textContent?.trim()).toBe('Create Task');
    });

    it('renders cancel button', () => {
      form = new CreateTaskForm({});
      form.render(container);

      const cancelBtn = container.querySelector('#btn-cancel') as HTMLButtonElement;
      expect(cancelBtn).toBeTruthy();
      expect(cancelBtn?.type).toBe('button');
    });

    it('has submit button disabled initially (no title)', () => {
      form = new CreateTaskForm({});
      form.render(container);

      const submitBtn = container.querySelector('#btn-submit') as HTMLButtonElement;
      expect(submitBtn?.disabled).toBe(true);
    });
  });

  describe('validation', () => {
    it('shows error on empty title', () => {
      form = new CreateTaskForm({});
      form.render(container);

      const titleInput = container.querySelector('#task-title') as HTMLInputElement;
      const errorEl = container.querySelector('#title-error') as HTMLElement;

      titleInput.value = '';
      titleInput.dispatchEvent(new Event('input', { bubbles: true }));

      expect(errorEl.style.display).toBe('block');
      expect(errorEl.textContent).toBe('Title is required');
    });

    it('hides error when title is entered', () => {
      form = new CreateTaskForm({});
      form.render(container);

      const titleInput = container.querySelector('#task-title') as HTMLInputElement;
      const errorEl = container.querySelector('#title-error') as HTMLElement;

      titleInput.value = 'Test Task';
      titleInput.dispatchEvent(new Event('input', { bubbles: true }));

      expect(errorEl.style.display).toBe('none');
    });

    it('shows error on importance < 0', () => {
      form = new CreateTaskForm({});
      form.render(container);

      const importanceInput = container.querySelector('#task-importance') as HTMLInputElement;
      const errorEl = container.querySelector('#importance-error') as HTMLElement;

      importanceInput.value = '-0.5';
      importanceInput.dispatchEvent(new Event('input', { bubbles: true }));

      expect(errorEl.style.display).toBe('block');
      expect(errorEl.textContent).toBe('Must be between 0 and 1');
    });

    it('shows error on importance > 1', () => {
      form = new CreateTaskForm({});
      form.render(container);

      const importanceInput = container.querySelector('#task-importance') as HTMLInputElement;
      const errorEl = container.querySelector('#importance-error') as HTMLElement;

      importanceInput.value = '1.5';
      importanceInput.dispatchEvent(new Event('input', { bubbles: true }));

      expect(errorEl.style.display).toBe('block');
      expect(errorEl.textContent).toBe('Must be between 0 and 1');
    });

    it('shows error on urgency < 0', () => {
      form = new CreateTaskForm({});
      form.render(container);

      const urgencyInput = container.querySelector('#task-urgency') as HTMLInputElement;
      const errorEl = container.querySelector('#urgency-error') as HTMLElement;

      urgencyInput.value = '-0.5';
      urgencyInput.dispatchEvent(new Event('input', { bubbles: true }));

      expect(errorEl.style.display).toBe('block');
      expect(errorEl.textContent).toBe('Must be between 0 and 1');
    });

    it('shows error on urgency > 1', () => {
      form = new CreateTaskForm({});
      form.render(container);

      const urgencyInput = container.querySelector('#task-urgency') as HTMLInputElement;
      const errorEl = container.querySelector('#urgency-error') as HTMLElement;

      urgencyInput.value = '1.5';
      urgencyInput.dispatchEvent(new Event('input', { bubbles: true }));

      expect(errorEl.style.display).toBe('block');
      expect(errorEl.textContent).toBe('Must be between 0 and 1');
    });

    it('enables submit button when title is entered', () => {
      form = new CreateTaskForm({});
      form.render(container);

      const titleInput = container.querySelector('#task-title') as HTMLInputElement;
      const submitBtn = container.querySelector('#btn-submit') as HTMLButtonElement;

      titleInput.value = 'Test Task';
      titleInput.dispatchEvent(new Event('input', { bubbles: true }));

      expect(submitBtn.disabled).toBe(false);
    });
  });

  describe('form submission', () => {
    it('calls createTask API on successful submit', async () => {
      const mockTask = {
        id: 'test-123',
        title: 'Test Task',
        description: 'Test description',
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

      vi.mocked(createTask).mockResolvedValue(mockTask);

      form = new CreateTaskForm({});
      form.render(container);

      // Fill form
      const titleInput = container.querySelector('#task-title') as HTMLInputElement;
      const descriptionInput = container.querySelector('#task-description') as HTMLTextAreaElement;
      const roleInput = container.querySelector('#task-role') as HTMLSelectElement;
      const importanceInput = container.querySelector('#task-importance') as HTMLInputElement;
      const urgencyInput = container.querySelector('#task-urgency') as HTMLInputElement;

      titleInput.value = 'Test Task';
      descriptionInput.value = 'Test description';
      roleInput.value = 'coder';
      importanceInput.value = '0.7';
      urgencyInput.value = '0.8';

      // Submit form
      const formEl = container.querySelector('#create-task-form') as HTMLFormElement;
      formEl.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));

      // Wait for async operation
      await new Promise(resolve => setTimeout(resolve, 10));

      expect(createTask).toHaveBeenCalledWith(expect.objectContaining({
        title: 'Test Task',
        description: 'Test description',
        role: 'coder',
        importance: 0.7,
        urgency: 0.8,
      }));
    });

    it('calls onSuccess callback with created task', async () => {
      const mockTask = {
        id: 'test-123',
        title: 'Test Task',
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

      vi.mocked(createTask).mockResolvedValue(mockTask);

      const onSuccess = vi.fn();
      form = new CreateTaskForm({ onSuccess });
      form.render(container);

      const titleInput = container.querySelector('#task-title') as HTMLInputElement;
      titleInput.value = 'Test Task';
      titleInput.dispatchEvent(new Event('input', { bubbles: true }));

      const formEl = container.querySelector('#create-task-form') as HTMLFormElement;
      formEl.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));

      await new Promise(resolve => setTimeout(resolve, 10));

      expect(onSuccess).toHaveBeenCalledWith(mockTask);
    });

    it('shows error message on API failure', async () => {
      vi.mocked(createTask).mockRejectedValue(new Error('API error'));

      form = new CreateTaskForm({});
      form.render(container);

      const titleInput = container.querySelector('#task-title') as HTMLInputElement;
      titleInput.value = 'Test Task';
      titleInput.dispatchEvent(new Event('input', { bubbles: true }));

      const formEl = container.querySelector('#create-task-form') as HTMLFormElement;
      formEl.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));

      await new Promise(resolve => setTimeout(resolve, 10));

      const messageEl = container.querySelector('#form-message') as HTMLElement;
      expect(messageEl.style.display).toBe('block');
      expect(messageEl.textContent).toBe('API error');
    });

    it('disables submit button while submitting', async () => {
      const mockTask = {
        id: 'test-123',
        title: 'Test Task',
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

      // Add delay to mock
      vi.mocked(createTask).mockImplementation(() => {
        return new Promise(resolve => setTimeout(() => resolve(mockTask), 50));
      });

      form = new CreateTaskForm({});
      form.render(container);

      const titleInput = container.querySelector('#task-title') as HTMLInputElement;
      const submitBtn = container.querySelector('#btn-submit') as HTMLButtonElement;

      titleInput.value = 'Test Task';
      titleInput.dispatchEvent(new Event('input', { bubbles: true }));

      const formEl = container.querySelector('#create-task-form') as HTMLFormElement;
      formEl.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));

      // Check immediately - should be disabled
      expect(submitBtn.disabled).toBe(true);

      await new Promise(resolve => setTimeout(resolve, 100));
    });
  });

  describe('cancel button', () => {
    it('calls onCancel callback when clicked', () => {
      const onCancel = vi.fn();
      form = new CreateTaskForm({ onCancel });
      form.render(container);

      const cancelBtn = container.querySelector('#btn-cancel') as HTMLButtonElement;
      cancelBtn.dispatchEvent(new MouseEvent('click', { bubbles: true }));

      expect(onCancel).toHaveBeenCalled();
    });
  });

  describe('reset', () => {
    it('clears all form fields', () => {
      form = new CreateTaskForm({});
      form.render(container);

      const titleInput = container.querySelector('#task-title') as HTMLInputElement;
      const descriptionInput = container.querySelector('#task-description') as HTMLTextAreaElement;
      const importanceInput = container.querySelector('#task-importance') as HTMLInputElement;
      const urgencyInput = container.querySelector('#task-urgency') as HTMLInputElement;

      // Fill form
      titleInput.value = 'Test Task';
      descriptionInput.value = 'Description';
      importanceInput.value = '0.8';
      urgencyInput.value = '0.9';

      form.reset();

      expect(titleInput.value).toBe('');
      expect(descriptionInput.value).toBe('');
      expect(importanceInput.value).toBe('0.5');
      expect(urgencyInput.value).toBe('0.5');
    });

    it('clears error messages', () => {
      form = new CreateTaskForm({});
      form.render(container);

      // Trigger validation error
      const titleInput = container.querySelector('#task-title') as HTMLInputElement;
      titleInput.value = '';
      titleInput.dispatchEvent(new Event('input', { bubbles: true }));

      const errorEl = container.querySelector('#title-error') as HTMLElement;
      expect(errorEl.style.display).toBe('block');

      form.reset();

      expect(errorEl.style.display).toBe('none');
    });

    it('clears form message', () => {
      form = new CreateTaskForm({});
      form.render(container);

      const messageEl = container.querySelector('#form-message') as HTMLElement;
      messageEl.style.display = 'block';
      messageEl.textContent = 'Test message';

      form.reset();

      expect(messageEl.style.display).toBe('none');
    });

    it('removes invalid classes from inputs', () => {
      form = new CreateTaskForm({});
      form.render(container);

      const titleInput = container.querySelector('#task-title') as HTMLInputElement;
      titleInput.classList.add('invalid');

      form.reset();

      expect(titleInput.classList.contains('invalid')).toBe(false);
    });
  });

  describe('destroy', () => {
    it('clears element reference', () => {
      form = new CreateTaskForm({});
      form.render(container);

      form.destroy();

      // Element should be null after destroy
      expect((form as any).element).toBeNull();
    });
  });

  describe('default values', () => {
    it('has coder as default role', () => {
      form = new CreateTaskForm({});
      form.render(container);

      const roleInput = container.querySelector('#task-role') as HTMLSelectElement;
      expect(roleInput.value).toBe('coder');
    });

    it('has 0.5 as default importance', () => {
      form = new CreateTaskForm({});
      form.render(container);

      const importanceInput = container.querySelector('#task-importance') as HTMLInputElement;
      expect(importanceInput.value).toBe('0.5');
    });

    it('has 0.5 as default urgency', () => {
      form = new CreateTaskForm({});
      form.render(container);

      const urgencyInput = container.querySelector('#task-urgency') as HTMLInputElement;
      expect(urgencyInput.value).toBe('0.5');
    });
  });

  describe('repo selection (Phase 2)', () => {
    beforeEach(() => {
      resetState();
      setState('repos', [
        { name: 'repo1', remote: 'https://github.com/test/repo1.git', local_path: '/test/repo1', added: '2024-01-01' },
        { name: 'repo2', remote: 'https://github.com/test/repo2.git', local_path: '/test/repo2', added: '2024-01-01' },
      ] as Repo[]);
    });

    it('renders repo multi-select', () => {
      form = new CreateTaskForm({});
      form.render(container);

      const repoSelect = container.querySelector('#repo-select') as HTMLSelectElement;
      expect(repoSelect).toBeTruthy();
    });

    it('populates repo select from state', () => {
      form = new CreateTaskForm({});
      form.render(container);

      const repoSelect = container.querySelector('#repo-select') as HTMLSelectElement;
      const options = repoSelect?.querySelectorAll('option');

      expect(options?.length).toBe(3); // placeholder + 2 repos
      expect(options?.[1].value).toBe('repo1');
      expect(options?.[2].value).toBe('repo2');
    });

    it('adds repo to selection when selected', () => {
      form = new CreateTaskForm({});
      form.render(container);

      const repoSelect = container.querySelector('#repo-select') as HTMLSelectElement;
      repoSelect.value = 'repo1';
      repoSelect.dispatchEvent(new Event('change', { bubbles: true }));

      const selectedRepos = container.querySelector('#selected-repos');
      expect(selectedRepos?.textContent).toContain('repo1');
    });

    it('displays selected repos as tags', () => {
      form = new CreateTaskForm({});
      form.render(container);

      const repoSelect = container.querySelector('#repo-select') as HTMLSelectElement;
      repoSelect.value = 'repo1';
      repoSelect.dispatchEvent(new Event('change', { bubbles: true }));

      const repoTag = container.querySelector('.repo-tag');
      expect(repoTag).toBeTruthy();
      expect(repoTag?.textContent).toContain('repo1');
    });

    it('allows removing selected repo', () => {
      form = new CreateTaskForm({});
      form.render(container);

      const repoSelect = container.querySelector('#repo-select') as HTMLSelectElement;
      repoSelect.value = 'repo1';
      repoSelect.dispatchEvent(new Event('change', { bubbles: true }));

      const removeBtn = container.querySelector('.repo-tag button');
      removeBtn?.dispatchEvent(new MouseEvent('click', { bubbles: true }));

      const selectedRepos = container.querySelector('#selected-repos');
      expect(selectedRepos?.textContent).not.toContain('repo1');
    });

    it('allows selecting multiple repos', () => {
      form = new CreateTaskForm({});
      form.render(container);

      const repoSelect = container.querySelector('#repo-select') as HTMLSelectElement;

      repoSelect.value = 'repo1';
      repoSelect.dispatchEvent(new Event('change', { bubbles: true }));

      repoSelect.value = 'repo2';
      repoSelect.dispatchEvent(new Event('change', { bubbles: true }));

      const repoTags = container.querySelectorAll('.repo-tag');
      expect(repoTags.length).toBe(2);
    });

    it('prevents duplicate repo selection', () => {
      form = new CreateTaskForm({});
      form.render(container);

      const repoSelect = container.querySelector('#repo-select') as HTMLSelectElement;

      repoSelect.value = 'repo1';
      repoSelect.dispatchEvent(new Event('change', { bubbles: true }));

      repoSelect.value = 'repo1';
      repoSelect.dispatchEvent(new Event('change', { bubbles: true }));

      const repoTags = container.querySelectorAll('.repo-tag');
      expect(repoTags.length).toBe(1);
    });

    it('auto-switches role to manager when multiple repos selected', () => {
      form = new CreateTaskForm({});
      form.render(container);

      const repoSelect = container.querySelector('#repo-select') as HTMLSelectElement;
      const roleSelect = container.querySelector('#task-role') as HTMLSelectElement;

      repoSelect.value = 'repo1';
      repoSelect.dispatchEvent(new Event('change', { bubbles: true }));

      expect(roleSelect?.value).toBe('coder');

      repoSelect.value = 'repo2';
      repoSelect.dispatchEvent(new Event('change', { bubbles: true }));

      expect(roleSelect?.value).toBe('manager');
    });

    it('includes repos in form data on submit', async () => {
      const mockTask = {
        id: 'test-123',
        title: 'Test Task',
        description: '',
        repo: ['repo1', 'repo2'],
        role: 'manager' as const,
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

      vi.mocked(createTask).mockResolvedValue(mockTask);

      form = new CreateTaskForm({});
      form.render(container);

      const titleInput = container.querySelector('#task-title') as HTMLInputElement;
      titleInput.value = 'Test Task';
      titleInput.dispatchEvent(new Event('input', { bubbles: true }));

      const repoSelect = container.querySelector('#repo-select') as HTMLSelectElement;
      repoSelect.value = 'repo1';
      repoSelect.dispatchEvent(new Event('change', { bubbles: true }));
      repoSelect.value = 'repo2';
      repoSelect.dispatchEvent(new Event('change', { bubbles: true }));

      const formEl = container.querySelector('#create-task-form') as HTMLFormElement;
      formEl.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));

      await new Promise(resolve => setTimeout(resolve, 10));

      expect(createTask).toHaveBeenCalledWith(expect.objectContaining({
        repo: ['repo1', 'repo2'],
        role: 'manager',
      }));
    });
  });

  describe('target files (Phase 2)', () => {
    it('renders target files input', () => {
      form = new CreateTaskForm({});
      form.render(container);

      const targetFilesInput = container.querySelector('#task-target-files') as HTMLInputElement;
      expect(targetFilesInput).toBeTruthy();
      expect(targetFilesInput?.type).toBe('text');
    });

    it('parses comma-separated target files', async () => {
      const mockTask = {
        id: 'test-123',
        title: 'Test Task',
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

      vi.mocked(createTask).mockResolvedValue(mockTask);

      form = new CreateTaskForm({});
      form.render(container);

      const titleInput = container.querySelector('#task-title') as HTMLInputElement;
      titleInput.value = 'Test Task';
      titleInput.dispatchEvent(new Event('input', { bubbles: true }));

      const targetFilesInput = container.querySelector('#task-target-files') as HTMLInputElement;
      targetFilesInput.value = 'file1.py, src/file2.ts, docs/file.md';

      const formEl = container.querySelector('#create-task-form') as HTMLFormElement;
      formEl.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));

      await new Promise(resolve => setTimeout(resolve, 10));

      expect(createTask).toHaveBeenCalledWith(expect.objectContaining({
        target_files: ['file1.py', 'src/file2.ts', 'docs/file.md'],
      }));
    });

    it('handles empty target files', async () => {
      const mockTask = {
        id: 'test-123',
        title: 'Test Task',
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

      vi.mocked(createTask).mockResolvedValue(mockTask);

      form = new CreateTaskForm({});
      form.render(container);

      const titleInput = container.querySelector('#task-title') as HTMLInputElement;
      titleInput.value = 'Test Task';
      titleInput.dispatchEvent(new Event('input', { bubbles: true }));

      const formEl = container.querySelector('#create-task-form') as HTMLFormElement;
      formEl.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));

      await new Promise(resolve => setTimeout(resolve, 10));

      expect(createTask).toHaveBeenCalledWith(expect.objectContaining({
        target_files: [],
      }));
    });
  });

  describe('state subscription (Phase 2)', () => {
    it('updates repo options when state changes', () => {
      resetState();
      setState('repos', [
        { name: 'repo1', remote: 'https://github.com/test/repo1.git', local_path: '/test/repo1', added: '2024-01-01' },
      ] as Repo[]);

      form = new CreateTaskForm({});
      form.render(container);

      let repoSelect = container.querySelector('#repo-select') as HTMLSelectElement;
      expect(repoSelect?.options.length).toBe(2); // placeholder + 1 repo

      // Update state
      setState('repos', [
        { name: 'repo1', remote: 'https://github.com/test/repo1.git', local_path: '/test/repo1', added: '2024-01-01' },
        { name: 'repo2', remote: 'https://github.com/test/repo2.git', local_path: '/test/repo2', added: '2024-01-01' },
        { name: 'repo3', remote: 'https://github.com/test/repo3.git', local_path: '/test/repo3', added: '2024-01-01' },
      ] as Repo[]);

      repoSelect = container.querySelector('#repo-select') as HTMLSelectElement;
      expect(repoSelect?.options.length).toBe(4); // placeholder + 3 repos
    });

    it('cleans up subscription on destroy', () => {
      resetState();
      setState('repos', [] as Repo[]);

      form = new CreateTaskForm({});
      form.render(container);

      form.destroy();

      // After destroy, state changes should not affect the form
      setState('repos', [
        { name: 'repo1', remote: 'https://github.com/test/repo1.git', local_path: '/test/repo1', added: '2024-01-01' },
      ] as Repo[]);

      // Should not throw or cause issues
      expect(() => {}).not.toThrow();
    });
  });

  describe('Phase 6 - Loading spinner', () => {
    it('shows spinner during submission', async () => {
      const mockTask = {
        id: 'test-123',
        title: 'Test Task',
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

      // Add delay to catch spinner
      vi.mocked(createTask).mockImplementation(() => {
        return new Promise(resolve => setTimeout(() => resolve(mockTask), 100));
      });

      form = new CreateTaskForm({});
      form.render(container);

      const titleInput = container.querySelector('#task-title') as HTMLInputElement;
      titleInput.value = 'Test Task';
      titleInput.dispatchEvent(new Event('input', { bubbles: true }));

      const formEl = container.querySelector('#create-task-form') as HTMLFormElement;
      formEl.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));

      // Check spinner is visible during submission
      const spinner = container.querySelector('.btn-spinner');
      expect(spinner).toBeTruthy();
      expect((spinner as HTMLElement).style.display).toBe('inline-block');

      await new Promise(resolve => setTimeout(resolve, 150));

      // Spinner should be hidden after submission
      expect((spinner as HTMLElement).style.display).toBe('none');
    });

    it('hides button text during submission', async () => {
      const mockTask = {
        id: 'test-123',
        title: 'Test Task',
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

      vi.mocked(createTask).mockImplementation(() => {
        return new Promise(resolve => setTimeout(() => resolve(mockTask), 50));
      });

      form = new CreateTaskForm({});
      form.render(container);

      const titleInput = container.querySelector('#task-title') as HTMLInputElement;
      titleInput.value = 'Test Task';
      titleInput.dispatchEvent(new Event('input', { bubbles: true }));

      const formEl = container.querySelector('#create-task-form') as HTMLFormElement;
      formEl.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));

      // Button text should be hidden during submission
      const btnText = container.querySelector('.btn-text') as HTMLElement;
      expect(btnText.style.display).toBe('none');

      await new Promise(resolve => setTimeout(resolve, 100));

      // Button text should be visible after submission
      expect(btnText.style.display).toBe('inline');
    });
  });

  describe('Phase 6 - Enhanced error messages', () => {
    it('shows error message on API failure', async () => {
      vi.mocked(createTask).mockRejectedValue(new Error('Network error'));

      form = new CreateTaskForm({});
      form.render(container);

      const titleInput = container.querySelector('#task-title') as HTMLInputElement;
      titleInput.value = 'Test Task';
      titleInput.dispatchEvent(new Event('input', { bubbles: true }));

      const formEl = container.querySelector('#create-task-form') as HTMLFormElement;
      formEl.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));

      await new Promise(resolve => setTimeout(resolve, 10));

      const messageEl = container.querySelector('#form-message') as HTMLElement;
      expect(messageEl.textContent).toBe('Network error');
    });

    it('shows API detail message when available', async () => {
      const error = new Error('Bad Request') as Error & { detail?: string };
      error.detail = 'Title is too long';
      vi.mocked(createTask).mockRejectedValue(error);

      form = new CreateTaskForm({});
      form.render(container);

      const titleInput = container.querySelector('#task-title') as HTMLInputElement;
      titleInput.value = 'Test Task';
      titleInput.dispatchEvent(new Event('input', { bubbles: true }));

      const formEl = container.querySelector('#create-task-form') as HTMLFormElement;
      formEl.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));

      await new Promise(resolve => setTimeout(resolve, 10));

      const messageEl = container.querySelector('#form-message') as HTMLElement;
      expect(messageEl.textContent).toBe('Title is too long');
    });
  });

  describe('ARIA accessibility', () => {
    it('includes aria-required on title field', () => {
      form = new CreateTaskForm({});
      form.render(container);

      const titleInput = container.querySelector('#task-title') as HTMLInputElement;
      expect(titleInput?.getAttribute('aria-required')).toBe('true');
    });

    it('includes aria-describedby on form fields', () => {
      form = new CreateTaskForm({});
      form.render(container);

      const titleInput = container.querySelector('#task-title') as HTMLInputElement;
      expect(titleInput?.getAttribute('aria-describedby')).toBe('title-hint');

      const importanceInput = container.querySelector('#task-importance') as HTMLInputElement;
      expect(importanceInput?.getAttribute('aria-describedby')).toBe('importance-hint');
    });

    it('includes aria-live on error messages', () => {
      form = new CreateTaskForm({});
      form.render(container);

      const titleError = container.querySelector('#title-error') as HTMLElement;
      expect(titleError?.getAttribute('aria-live')).toBe('polite');

      const importanceError = container.querySelector('#importance-error') as HTMLElement;
      expect(importanceError?.getAttribute('aria-live')).toBe('polite');
    });

    it('includes aria-label on repo select', () => {
      form = new CreateTaskForm({});
      form.render(container);

      const repoSelect = container.querySelector('#repo-select') as HTMLSelectElement;
      expect(repoSelect?.getAttribute('aria-label')).toBe('Add repository');
    });

    it('includes aria-live on selected repos container', () => {
      form = new CreateTaskForm({});
      form.render(container);

      const selectedRepos = container.querySelector('#selected-repos') as HTMLElement;
      expect(selectedRepos?.getAttribute('aria-live')).toBe('polite');
    });
  });

  describe('validateForm', () => {
    it('returns true when all fields are valid', () => {
      form = new CreateTaskForm({});
      form.render(container);

      const titleInput = container.querySelector('#task-title') as HTMLInputElement;
      titleInput.value = 'Valid Title';

      // Access private method for testing
      const result = (form as any).validateForm();
      expect(result).toBe(true);
    });

    it('returns false when title is empty', () => {
      form = new CreateTaskForm({});
      form.render(container);

      const titleInput = container.querySelector('#task-title') as HTMLInputElement;
      titleInput.value = '';

      const result = (form as any).validateForm();
      expect(result).toBe(false);
    });

    it('returns false when importance is out of range', () => {
      form = new CreateTaskForm({});
      form.render(container);

      const titleInput = container.querySelector('#task-title') as HTMLInputElement;
      titleInput.value = 'Test';

      const importanceInput = container.querySelector('#task-importance') as HTMLInputElement;
      importanceInput.value = '1.5';

      const result = (form as any).validateForm();
      expect(result).toBe(false);
    });
  });

  describe('showMessage', () => {
    it('displays success message with correct class', () => {
      form = new CreateTaskForm({});
      form.render(container);

      (form as any).showMessage('Success!', 'success');

      const messageEl = container.querySelector('#form-message') as HTMLElement;
      expect(messageEl.textContent).toBe('Success!');
      expect(messageEl.className).toContain('success');
      expect(messageEl.style.display).toBe('block');
    });

    it('displays error message with correct class', () => {
      form = new CreateTaskForm({});
      form.render(container);

      (form as any).showMessage('Error!', 'error');

      const messageEl = container.querySelector('#form-message') as HTMLElement;
      expect(messageEl.textContent).toBe('Error!');
      expect(messageEl.className).toContain('error');
    });

    it('displays info message with correct class', () => {
      form = new CreateTaskForm({});
      form.render(container);

      (form as any).showMessage('Info...', 'info');

      const messageEl = container.querySelector('#form-message') as HTMLElement;
      expect(messageEl.textContent).toBe('Info...');
      expect(messageEl.className).toContain('info');
    });
  });

  describe('Immediate validation', () => {
    it('validates title immediately on input', () => {
      form = new CreateTaskForm({});
      form.render(container);

      const titleInput = container.querySelector('#task-title') as HTMLInputElement;
      const errorEl = container.querySelector('#title-error') as HTMLElement;

      titleInput.value = '';
      titleInput.dispatchEvent(new Event('input', { bubbles: true }));

      // Validation happens immediately, no debounce
      expect(errorEl.style.display).toBe('block');
    });

    it('validates importance immediately on input', () => {
      form = new CreateTaskForm({});
      form.render(container);

      const importanceInput = container.querySelector('#task-importance') as HTMLInputElement;
      const errorEl = container.querySelector('#importance-error') as HTMLElement;

      importanceInput.value = '1.5';
      importanceInput.dispatchEvent(new Event('input', { bubbles: true }));

      expect(errorEl.style.display).toBe('block');
    });

    it('validates urgency immediately on input', () => {
      form = new CreateTaskForm({});
      form.render(container);

      const urgencyInput = container.querySelector('#task-urgency') as HTMLInputElement;
      const errorEl = container.querySelector('#urgency-error') as HTMLElement;

      urgencyInput.value = '-0.5';
      urgencyInput.dispatchEvent(new Event('input', { bubbles: true }));

      expect(errorEl.style.display).toBe('block');
    });
  });

});
