/**
 * Create Task Form Component
 *
 * Allows users to create new tasks with the following fields:
 * - Title (required)
 * - Description (optional)
 * - Role (coder/writer/manager, auto-switches to manager if multiple repos selected)
 * - Repos (multi-select, optional)
 * - Target files (comma-separated, optional)
 * - Importance (0-1)
 * - Urgency (0-1)
 */

import { createTask } from '../api';
import { getState, subscribe } from '../state';
import type { Task, AgentRole, Repo } from '../types';
import type { TaskCreateRequest } from '../types/api';

export interface CreateTaskFormOptions {
  onSuccess?: (task: Task) => void;
  onCancel?: () => void;
}

export class CreateTaskForm {
  private element: HTMLElement | null = null;
  private options: CreateTaskFormOptions;
  private isSubmitting = false;
  private selectedRepos: string[] = [];
  private unsubscribe?: () => void;

  constructor(options: CreateTaskFormOptions) {
    this.options = options;
  }

  /**
   * Render the form
   */
  render(container: HTMLElement): void {
    this.element = document.createElement('div');
    this.element.className = 'create-task-form';
    this.element.innerHTML = `
      <form id="create-task-form" novalidate>
        <div class="form-field">
          <label for="task-title">Title <span class="required">*</span></label>
          <input
            type="text"
            id="task-title"
            name="title"
            required
            placeholder="Brief description of the task"
            autocomplete="off"
            aria-required="true"
            aria-describedby="title-hint"
          />
          <span class="field-error" id="title-error" style="display: none;" aria-live="polite"></span>
          <span class="field-hint" id="title-hint">A clear, concise title helps the agent understand the task</span>
        </div>

        <div class="form-field">
          <label for="task-description">Description</label>
          <textarea
            id="task-description"
            name="description"
            rows="4"
            placeholder="Provide additional context, requirements, or details..."
            aria-describedby="description-hint"
          ></textarea>
          <span class="field-hint" id="description-hint">Markdown is supported</span>
        </div>

        <div class="form-field">
          <label for="task-repos">Repositories</label>
          <div class="repo-multi-select" id="task-repos">
            <select id="repo-select" class="repo-select" aria-label="Add repository">
              <option value="">Select a repo...</option>
            </select>
          </div>
          <div class="selected-repos" id="selected-repos" aria-live="polite" aria-label="Selected repositories"></div>
          <span class="field-hint">Select repos this task applies to (multi-repo tasks become Manager tasks)</span>
        </div>

        <div class="form-field">
          <label for="task-target-files">Target Files</label>
          <input
            type="text"
            id="task-target-files"
            name="target_files"
            placeholder="file1.py, src/file2.ts, docs/file.md"
            aria-describedby="target-files-hint"
          />
          <span class="field-hint" id="target-files-hint">Comma-separated list of file paths</span>
        </div>

        <div class="form-row">
          <div class="form-field">
            <label for="task-role">Role</label>
            <select id="task-role" name="role" aria-describedby="role-hint">
              <option value="coder" selected>Coder</option>
              <option value="writer">Writer</option>
              <option value="manager">Manager</option>
            </select>
            <span class="field-hint" id="role-hint">Manager role is auto-selected for multi-repo tasks</span>
          </div>

          <div class="form-field">
            <label for="task-importance">Importance</label>
            <input
              type="number"
              id="task-importance"
              name="importance"
              min="0"
              max="1"
              step="0.1"
              value="0.5"
              aria-describedby="importance-hint"
            />
            <span class="field-error" id="importance-error" style="display: none;" aria-live="polite"></span>
            <span class="field-hint" id="importance-hint">Higher = more important (0.0 - 1.0)</span>
          </div>
        </div>

        <div class="form-field">
          <label for="task-urgency">Urgency</label>
          <input
            type="number"
            id="task-urgency"
            name="urgency"
            min="0"
            max="1"
            step="0.1"
            value="0.5"
            aria-describedby="urgency-hint"
          />
          <span class="field-error" id="urgency-error" style="display: none;" aria-live="polite"></span>
          <span class="field-hint" id="urgency-hint">Higher = more urgent (0.0 - 1.0)</span>
        </div>

        <div class="form-actions">
          <button type="submit" class="btn-submit" id="btn-submit" disabled>
            <span class="btn-text">Create Task</span>
            <span class="btn-spinner" style="display: none;">
              <svg class="spinner" viewBox="0 0 24 24" width="20" height="20">
                <circle class="spinner-circle" cx="12" cy="12" r="10" fill="none" stroke-width="3"></circle>
              </svg>
            </span>
          </button>
          <button type="button" class="btn-cancel" id="btn-cancel">
            Cancel
          </button>
        </div>

        <div class="form-message" id="form-message" style="display: none;"></div>
      </form>
    `;

    container.appendChild(this.element);
    this.setupRepoSelector();
    this.setupRepoTagDelegation();
    this.setupEventListeners();
    this.setupStateSubscription();
  }

  /**
   * Set up repo selector
   */
  private setupRepoSelector(): void {
    if (!this.element) return;

    const repoSelect = this.element.querySelector('#repo-select') as HTMLSelectElement;
    if (!repoSelect) return;

    this.populateRepoOptions(repoSelect);
  }

  /**
   * Populate repo options from state
   */
  private populateRepoOptions(select: HTMLSelectElement): void {
    const { repos } = getState();

    while (select.options.length > 1) {
      select.remove(1);
    }

    repos.forEach((repo: Repo) => {
      const option = document.createElement('option');
      option.value = repo.name;
      option.textContent = repo.name;
      select.appendChild(option);
    });
  }

  /**
   * Set up state subscription for repo updates
   */
  private setupStateSubscription(): void {
    this.unsubscribe = subscribe((state) => {
      if (this.element) {
        const repoSelect = this.element.querySelector('#repo-select') as HTMLSelectElement;
        if (repoSelect) {
          this.populateRepoOptions(repoSelect);
        }
      }
    });
  }

  /**
   * Add repo to selection
   */
  private addRepo(repoName: string): void {
    if (!repoName || this.selectedRepos.includes(repoName)) return;

    this.selectedRepos.push(repoName);
    this.renderSelectedRepos();
    this.checkRoleAutoSwitch();
  }

  /**
   * Remove repo from selection
   */
  private removeRepo(repoName: string): void {
    this.selectedRepos = this.selectedRepos.filter((r) => r !== repoName);
    this.renderSelectedRepos();
    this.checkRoleAutoSwitch();
  }

  /**
   * Render selected repos as tags
   */
  private renderSelectedRepos(): void {
    if (!this.element) return;

    const container = this.element.querySelector('#selected-repos');
    if (!container) return;

    if (this.selectedRepos.length === 0) {
      container.innerHTML = '';
      return;
    }

    container.innerHTML = this.selectedRepos
      .map(
        (repo) => `
          <span class="repo-tag">
            ${repo}
            <button type="button" data-remove-repo="${repo}" aria-label="Remove ${repo}">&times;</button>
          </span>
        `
      )
      .join('');
  }

  /**
   * Set up repo tag event delegation
   */
  private setupRepoTagDelegation(): void {
    if (!this.element) return;

    const container = this.element.querySelector('#selected-repos');
    if (!container) return;

    container.addEventListener('click', (e) => {
      const btn = (e.target as HTMLElement).closest('[data-remove-repo]');
      if (btn) {
        const repoName = btn.getAttribute('data-remove-repo');
        if (repoName) {
          this.removeRepo(repoName);
        }
      }
    });
  }

  /**
   * Auto-switch role to manager if multiple repos selected
   */
  private checkRoleAutoSwitch(): void {
    if (!this.element) return;

    const roleSelect = this.element.querySelector('#task-role') as HTMLSelectElement;
    const roleHint = this.element.querySelector('#role-hint') as HTMLElement;

    if (this.selectedRepos.length > 1) {
      roleSelect.value = 'manager';
      roleHint.textContent = 'Auto-switched to Manager for multi-repo task';
      roleHint.style.color = 'var(--primary-color, #007bff)';
      roleHint.style.fontWeight = '600';
    } else {
      roleSelect.value = 'coder';
      roleHint.textContent = 'Manager role is auto-selected for multi-repo tasks';
      roleHint.style.color = '';
      roleHint.style.fontWeight = '';
    }
  }

  /**
   * Set up form event listeners
   */
  private setupEventListeners(): void {
    if (!this.element) return;

    const form = this.element.querySelector('#create-task-form') as HTMLFormElement;
    const cancelBtn = this.element.querySelector('#btn-cancel') as HTMLButtonElement;
    const repoSelect = this.element.querySelector('#repo-select') as HTMLSelectElement;

    const titleInput = this.element.querySelector('#task-title') as HTMLInputElement;
    const importanceInput = this.element.querySelector('#task-importance') as HTMLInputElement;
    const urgencyInput = this.element.querySelector('#task-urgency') as HTMLInputElement;

    // Validation on input
    titleInput?.addEventListener('input', () => {
      this.validateTitle();
      this.updateSubmitButton();
    });

    importanceInput?.addEventListener('input', () => {
      this.validateRange('task-importance', 'importance-error');
    });

    urgencyInput?.addEventListener('input', () => {
      this.validateRange('task-urgency', 'urgency-error');
    });

    // Repo selection
    repoSelect?.addEventListener('change', (e) => {
      const value = (e.target as HTMLSelectElement).value;
      if (value) {
        this.addRepo(value);
        repoSelect.value = '';
      }
    });

    // Form submission
    form?.addEventListener('submit', (e) => {
      e.preventDefault();
      this.handleSubmit();
    });

    // Cancel button
    cancelBtn?.addEventListener('click', () => {
      if (this.options.onCancel) {
        this.options.onCancel();
      }
    });

    // Initial validation
    this.updateSubmitButton();
  }

  /**
   * Validate title field
   */
  private validateTitle(): boolean {
    if (!this.element) return false;

    const titleInput = this.element.querySelector('#task-title') as HTMLInputElement;
    const errorEl = this.element.querySelector('#title-error') as HTMLElement;
    const title = titleInput?.value.trim() || '';

    if (!title) {
      errorEl.textContent = 'Title is required';
      errorEl.style.display = 'block';
      titleInput.classList.add('invalid');
      return false;
    }

    errorEl.style.display = 'none';
    titleInput.classList.remove('invalid');
    return true;
  }

  /**
   * Validate a numeric range field (importance/urgency)
   */
  private validateRange(inputId: string, errorId: string): boolean {
    if (!this.element) return false;

    const input = this.element.querySelector(`#${inputId}`) as HTMLInputElement;
    const errorEl = this.element.querySelector(`#${errorId}`) as HTMLElement;
    const value = parseFloat(input?.value || '0');

    if (value < 0 || value > 1) {
      errorEl.textContent = 'Must be between 0 and 1';
      errorEl.style.display = 'block';
      input.classList.add('invalid');
      return false;
    }

    errorEl.style.display = 'none';
    input.classList.remove('invalid');
    return true;
  }

  /**
   * Validate all fields
   */
  private validateForm(): boolean {
    const titleValid = this.validateTitle();
    const importanceValid = this.validateRange('task-importance', 'importance-error');
    const urgencyValid = this.validateRange('task-urgency', 'urgency-error');

    return titleValid && importanceValid && urgencyValid;
  }

  /**
   * Update submit button state
   */
  private updateSubmitButton(): void {
    if (!this.element) return;

    const submitBtn = this.element.querySelector('#btn-submit') as HTMLButtonElement;
    const titleInput = this.element.querySelector('#task-title') as HTMLInputElement;
    const title = titleInput?.value.trim() || '';

    submitBtn.disabled = !title || this.isSubmitting;
  }

  /**
   * Handle form submission
   */
  private async handleSubmit(): Promise<void> {
    if (!this.element || this.isSubmitting) return;

    this.isSubmitting = true;
    this.updateSubmitButton();
    this.setSubmittingState(true);

    if (!this.validateForm()) {
      this.isSubmitting = false;
      this.setSubmittingState(false);
      this.updateSubmitButton();
      this.showMessage('Please fix the errors above', 'error');
      return;
    }

    const formData = this.getFormData();

    try {
      this.showMessage('Creating task...', 'info');

      const task = await createTask(formData);

      this.isSubmitting = false;
      this.setSubmittingState(false);
      this.updateSubmitButton();

      if (this.options.onSuccess) {
        this.options.onSuccess(task);
      }
    } catch (error) {
      this.isSubmitting = false;
      this.setSubmittingState(false);
      this.updateSubmitButton();

      const errorMessage = error instanceof Error && 'detail' in error
        ? (error as Error & { detail: string }).detail
        : error instanceof Error
          ? error.message
          : 'Failed to create task. Please try again.';
      this.showMessage(errorMessage, 'error');
    }
  }

  /**
   * Set submitting state (show/hide spinner)
   */
  private setSubmittingState(isSubmitting: boolean): void {
    if (!this.element) return;

    const btnText = this.element.querySelector('.btn-text') as HTMLElement;
    const btnSpinner = this.element.querySelector('.btn-spinner') as HTMLElement;
    const submitBtn = this.element.querySelector('#btn-submit') as HTMLButtonElement;

    if (isSubmitting) {
      btnText.style.display = 'none';
      btnSpinner.style.display = 'inline-block';
      submitBtn.disabled = true;
    } else {
      btnText.style.display = 'inline';
      btnSpinner.style.display = 'none';
      submitBtn.disabled = false;
    }
  }

  /**
   * Get form data for API submission
   */
  private getFormData(): TaskCreateRequest {
    if (!this.element) {
      throw new Error('Form element not found');
    }

    const titleInput = this.element.querySelector('#task-title') as HTMLInputElement;
    const descriptionInput = this.element.querySelector('#task-description') as HTMLTextAreaElement;
    const roleInput = this.element.querySelector('#task-role') as HTMLSelectElement;
    const importanceInput = this.element.querySelector('#task-importance') as HTMLInputElement;
    const urgencyInput = this.element.querySelector('#task-urgency') as HTMLInputElement;
    const targetFilesInput = this.element.querySelector('#task-target-files') as HTMLInputElement;

    const roleValue = roleInput.value;
    const validRoles = ['coder', 'writer', 'manager'];
    if (!validRoles.includes(roleValue)) {
      throw new Error(`Invalid role: ${roleValue}. Valid roles are: ${validRoles.join(', ')}`);
    }

    const targetFilesValue = targetFilesInput.value.trim();
    const targetFiles = targetFilesValue
      ? targetFilesValue.split(',').map((f) => f.trim()).filter((f) => f.length > 0)
      : [];

    return {
      title: titleInput.value.trim(),
      description: descriptionInput.value.trim(),
      role: roleValue as AgentRole,
      repo: [...this.selectedRepos],
      target_files: targetFiles,
      importance: parseFloat(importanceInput.value) || 0.5,
      urgency: parseFloat(urgencyInput.value) || 0.5,
    };
  }

  /**
   * Show message to user
   */
  private showMessage(text: string, type: 'success' | 'error' | 'info'): void {
    if (!this.element) return;

    const messageEl = this.element.querySelector('#form-message') as HTMLElement;
    if (messageEl) {
      messageEl.textContent = text;
      messageEl.className = `form-message ${type}`;
      messageEl.style.display = 'block';
    }
  }

  /**
   * Reset form to initial state
   */
  reset(): void {
    if (!this.element) return;

    const form = this.element.querySelector('#create-task-form') as HTMLFormElement;
    form?.reset();

    this.selectedRepos = [];
    this.renderSelectedRepos();
    this.checkRoleAutoSwitch();

    this.element.querySelectorAll('.field-error').forEach((el) => {
      (el as HTMLElement).style.display = 'none';
    });

    const messageEl = this.element.querySelector('#form-message') as HTMLElement;
    if (messageEl) {
      messageEl.style.display = 'none';
    }

    this.element.querySelectorAll('input, textarea, select').forEach((el) => {
      el.classList.remove('invalid');
    });

    this.isSubmitting = false;
    this.updateSubmitButton();
  }

  /**
   * Clean up
   */
  destroy(): void {
    if (this.unsubscribe) {
      this.unsubscribe();
    }
    this.element = null;
  }
}
