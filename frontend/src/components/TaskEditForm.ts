/**
 * Task Edit Form Component
 * This is what makes the EDIT button actually work!
 */

import { updateTask, cancelTask } from '../api';
import { escapeHtml } from '../utils';
import type { Task, AgentRole } from '../types';

export interface TaskEditFormOptions {
  task: Task;
  onSave?: (task: Task) => void;
  onCancel?: () => void;
  onTaskCancelled?: () => void;
}

export class TaskEditForm {
  private element: HTMLElement | null = null;
  private options: TaskEditFormOptions;
  private isDirty = false;

  constructor(options: TaskEditFormOptions) {
    this.options = options;
  }

  render(): HTMLElement {
    const { task } = this.options;

    this.element = document.createElement('div');
    this.element.className = 'task-edit-form';
    this.element.id = `task-edit-form-${task.id}`;
    this.element.innerHTML = `
      <div class="edit-form-header">
        <h3>Edit Task</h3>
      </div>
      
      <div class="edit-form-field">
        <label>Title</label>
        <input type="text" id="edit-title" value="${escapeHtml(task.title)}" />
      </div>
      
      <div class="edit-form-field">
        <label>Description</label>
        <textarea id="edit-description">${escapeHtml(task.description)}</textarea>
      </div>
      
      <div class="edit-form-field">
        <label>Notes</label>
        <textarea id="edit-notes">${escapeHtml(task.notes || '')}</textarea>
      </div>
      
      <div class="edit-form-row">
        <div class="edit-form-field">
          <label>Branch</label>
          <input type="text" id="edit-branch" value="${escapeHtml(task.branch)}" />
        </div>
        
        <div class="edit-form-field">
          <label>Role</label>
          <select id="edit-role">
            ${this.renderRoleOptions(task.role)}
          </select>
        </div>
      </div>
      
      <div class="edit-form-row">
        <div class="edit-form-field">
          <label>Importance (0-1)</label>
          <input type="number" id="edit-importance" min="0" max="1" step="0.1" value="${task.importance}" />
        </div>
        
        <div class="edit-form-field">
          <label>Urgency (0-1)</label>
          <input type="number" id="edit-urgency" min="0" max="1" step="0.1" value="${task.urgency}" />
        </div>
        
        <div class="edit-form-field">
          <label>Turn Limit</label>
          <input type="number" id="edit-turn-limit" min="0" value="${task.turn_limit || 0}" />
        </div>
      </div>
      
      <div class="edit-form-actions">
        <button class="btn-save">Save</button>
        <button class="btn-cancel">Cancel</button>
        <button class="btn-cancel-task">Cancel Task</button>
      </div>
    `;

    // Set up event listeners
    this.setupEventListeners();

    return this.element;
  }

  private renderRoleOptions(currentRole: AgentRole): string {
    const roles: AgentRole[] = ['manager', 'coder', 'writer', 'critic', 'merge'];
    return roles
      .map(
        (role) => `<option value="${role}" ${role === currentRole ? 'selected' : ''}>
          ${role.charAt(0).toUpperCase() + role.slice(1)}
        </option>`
      )
      .join('');
  }

  private setupEventListeners(): void {
    if (!this.element) return;

    // Mark form as dirty on any change
    this.element.querySelectorAll('input, textarea, select').forEach((input) => {
      input.addEventListener('change', () => (this.isDirty = true));
      input.addEventListener('input', () => (this.isDirty = true));
    });

    // Save button
    const saveBtn = this.element.querySelector('.btn-save');
    saveBtn?.addEventListener('click', () => this.handleSave());

    // Cancel button
    const cancelBtn = this.element.querySelector('.btn-cancel');
    cancelBtn?.addEventListener('click', () => {
      if (this.options.onCancel) {
        this.options.onCancel();
      }
    });

    // Cancel task button
    const cancelTaskBtn = this.element.querySelector('.btn-cancel-task');
    cancelTaskBtn?.addEventListener('click', () => this.handleCancelTask());
  }

  private async handleSave(): Promise<void> {
    if (!this.element || !this.options.task) return;

    const updates = {
      title: (this.element.querySelector('#edit-title') as HTMLInputElement).value.trim(),
      description: (this.element.querySelector('#edit-description') as HTMLTextAreaElement).value.trim(),
      notes: (this.element.querySelector('#edit-notes') as HTMLTextAreaElement).value.trim(),
      branch: (this.element.querySelector('#edit-branch') as HTMLInputElement).value.trim(),
      role: (this.element.querySelector('#edit-role') as HTMLSelectElement).value as AgentRole,
      importance: parseFloat((this.element.querySelector('#edit-importance') as HTMLInputElement).value) || 0.5,
      urgency: parseFloat((this.element.querySelector('#edit-urgency') as HTMLInputElement).value) || 0.5,
      turn_limit: parseInt((this.element.querySelector('#edit-turn-limit') as HTMLInputElement).value) || 0,
    };

    if (!updates.title) {
      alert('Title is required');
      return;
    }

    try {
      const updatedTask = await updateTask(this.options.task.id, updates);
      this.isDirty = false;

      if (this.options.onSave) {
        this.options.onSave(updatedTask);
      }

      console.log('[TaskEditForm] Task saved successfully');
    } catch (error) {
      console.error('[TaskEditForm] Failed to save:', error);
      alert(`Failed to save: ${error}`);
    }
  }

  private async handleCancelTask(): Promise<void> {
    if (!confirm('Are you sure you want to cancel this task?')) return;

    try {
      await cancelTask(this.options.task.id);

      if (this.options.onTaskCancelled) {
        this.options.onTaskCancelled();
      }

      console.log('[TaskEditForm] Task cancelled');
    } catch (error) {
      console.error('[TaskEditForm] Failed to cancel task:', error);
      alert(`Failed to cancel task: ${error}`);
    }
  }
}
