/**
 * Task Page Component
 * Shows task details, conversation, and EDIT form
 * THIS IS WHERE THE EDIT BUTTON FINALLY WORKS!
 */

import { getTask, getTaskDependencies } from '../api';
import { getState, setState, subscribe } from '../state';
import { formatStatus, formatRole, escapeHtml } from '../utils';
import { Conversation } from '../components/Conversation';
import { TaskEditForm } from '../components/TaskEditForm';
import { DecisionBanner } from '../components/DecisionModal';
import type { Task } from '../types';

export class TaskPage {
  private element: HTMLElement | null = null;
  private taskId: string;
  private task: Task | null = null;
  private conversation: Conversation | null = null;
  private editForm: TaskEditForm | null = null;
  private decisionBanner: DecisionBanner | null = null;
  private isEditing = false;

  constructor(taskId: string) {
    this.taskId = taskId;
    subscribe((state) => {
      if (state.selectedTask?.id === taskId) {
        this.task = state.selectedTask;
        this.updateHeader();
      }
    });
  }

  async render(container: HTMLElement): Promise<void> {
    // Load task data
    try {
      this.task = await getTask(this.taskId);
      setState('selectedTask', this.task);
    } catch (error) {
      console.error('[TaskPage] Failed to load task:', error);
      container.innerHTML = `<div style="padding:40px;color:var(--red)">Failed to load task: ${error}</div>`;
      return;
    }

    this.element = document.createElement('div');
    this.element.id = 'task-page';
    this.element.innerHTML = `
      <div id="task-header">
        <div class="task-header-main">
          <h1 class="task-title">${escapeHtml(this.task.title)}</h1>
          <div class="task-actions">
            <button id="task-edit-btn" class="btn-edit">✎ Edit</button>
            ${this.task.status === 'blocked_by_human' ? '<button id="task-unblock-btn" class="btn-unblock">✓ Unblock</button>' : ''}
          </div>
        </div>
        <div class="task-meta">
          <span class="meta-item">
            <span class="meta-label">ID:</span>
            <span class="meta-value">${escapeHtml(this.task.id)}</span>
          </span>
          <span class="meta-item">
            <span class="meta-label">Status:</span>
            <span class="meta-value status-${escapeHtml(this.task.status)}">${formatStatus(this.task.status)}</span>
          </span>
          <span class="meta-item" data-meta="role">
            <span class="meta-label">Role:</span>
            <span class="meta-value">${formatRole(this.task.role)}</span>
          </span>
          ${this.task.branch ? `
            <span class="meta-item">
              <span class="meta-label">Branch:</span>
              <span class="meta-value">${escapeHtml(this.task.branch)}</span>
            </span>
          ` : ''}
          <span class="meta-item">
            <span class="meta-label">Repo:</span>
            <span class="meta-value">${this.task.repo.length > 0 ? this.task.repo.map(escapeHtml).join(', ') : 'Workspace'}</span>
          </span>
        </div>
        <div id="task-dependencies" style="display:none;" role="region" aria-label="Task dependencies"></div>
      </div>
      
      <div id="task-edit-container"></div>

      <div id="task-decision-banner"></div>

      <div id="task-conversation-container"></div>
    `;

    // Set up edit button - THIS IS THE CRITICAL PART!
    const editBtn = this.element.querySelector('#task-edit-btn');
    editBtn?.addEventListener('click', () => this.handleEdit());

    // Set up unblock button
    const unblockBtn = this.element.querySelector('#task-unblock-btn');
    unblockBtn?.addEventListener('click', () => this.handleUnblock());

    // Load dependencies if blocked by task
    if (this.task.status === 'blocked_by_task') {
      this.loadDependencies();
    }

    // Render conversation
    this.renderConversation();

    container.appendChild(this.element);
  }

  private handleEdit(): void {
    if (!this.task || !this.element) return;

    const editContainer = this.element.querySelector('#task-edit-container');
    if (!editContainer) return;

    if (this.isEditing) {
      // Close edit form
      editContainer.innerHTML = '';
      this.editForm = null;
      this.isEditing = false;
    } else {
      // Open edit form - THIS MAKES EDIT WORK!
      this.editForm = new TaskEditForm({
        task: this.task,
        onSave: (updatedTask) => {
          this.task = updatedTask;
          setState('selectedTask', updatedTask);
          this.updateHeader();
          this.isEditing = false;
          const editContainer = this.element?.querySelector('#task-edit-container');
          if (editContainer) editContainer.innerHTML = '';
        },
        onCancel: () => {
          this.isEditing = false;
          const editContainer = this.element?.querySelector('#task-edit-container');
          if (editContainer) editContainer.innerHTML = '';
        },
        onTaskCancelled: () => {
          // Navigate back to tasks list
          window.history.pushState({}, '', '/task-list');
          window.dispatchEvent(new Event('popstate'));
        },
      });

      editContainer.appendChild(this.editForm.render());
      this.isEditing = true;
    }
  }

  private async handleUnblock(): Promise<void> {
    if (!this.task) return;

    const note = prompt('Optional note to include with unblock:');
    if (note === null) return; // User cancelled

    // Navigate to tasks and trigger unblock
    // (Will be implemented with proper API call)
    console.log('[TaskPage] Unblock task:', this.task.id, 'with note:', note);
  }

  private async loadDependencies(): Promise<void> {
    if (!this.element) return;

    try {
      const data = await getTaskDependencies(this.taskId);
      const depsEl = this.element.querySelector('#task-dependencies');

      if (depsEl && data.dependencies.length > 0) {
        depsEl.style.display = 'block';
        depsEl.innerHTML = `
          <div class="dependencies-section">
            <div class="dependencies-label">Blocked by:</div>
            ${data.dependencies
              .map(
                (dep) => `
              <a href="#" class="dependency-link" data-task-id="${escapeHtml(dep.id)}">
                <span class="dep-id">${escapeHtml(dep.id)}</span>
                <span class="dep-title">${escapeHtml(dep.title)}</span>
              </a>
            `
              )
              .join('')}
          </div>
        `;

        // Set up dependency link clicks
        depsEl.querySelectorAll('.dependency-link').forEach((link) => {
          link.addEventListener('click', (e) => {
            e.preventDefault();
            const depTaskId = (link as HTMLElement).dataset.taskId;
            if (depTaskId) {
              window.history.pushState({}, '', `/task/${depTaskId}`);
              window.dispatchEvent(new Event('popstate'));
            }
          });
        });
      }
    } catch (error) {
      console.error('[TaskPage] Failed to load dependencies:', error);
    }
  }

  private renderConversation(): void {
    if (!this.element) return;

    const container = this.element.querySelector('#task-conversation-container');
    if (!container) return;

    this.conversation = new Conversation({
      scope: this.task?.repo?.[0] || 'workspace',
      taskId: this.taskId,
    });

    container.appendChild(this.conversation.render());

    // Render decision banner
    const bannerContainer = this.element.querySelector('#task-decision-banner');
    if (bannerContainer) {
      // Destroy previous banner if it exists to prevent listener accumulation
      if (this.decisionBanner) {
        this.decisionBanner.destroy();
      }
      this.decisionBanner = new DecisionBanner();
      this.decisionBanner.render(bannerContainer);
    }
  }

  private updateHeader(): void {
    if (!this.element || !this.task) return;

    const titleEl = this.element.querySelector('.task-title');
    if (titleEl) {
      titleEl.textContent = this.task.title;
    }

    this.updateMeta();
  }

  private updateMeta(): void {
    if (!this.element || !this.task) return;

    // Update status
    const statusEl = this.element.querySelector('.status-' + this.task.status);
    if (statusEl) {
      statusEl.textContent = formatStatus(this.task.status);
    }

    // Update role using stable data attribute selector
    const roleMetaItem = this.element.querySelector('[data-meta="role"]');
    if (roleMetaItem) {
      const roleValue = roleMetaItem.querySelector('.meta-value');
      if (roleValue) {
        roleValue.textContent = formatRole(this.task.role);
      }
    }
  }
}
