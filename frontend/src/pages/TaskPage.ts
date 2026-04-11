/**
 * Task Page Component
 * Shows task details, conversation, and EDIT form
 * THIS IS WHERE THE EDIT BUTTON FINALLY WORKS!
 */

import { getTask, getTaskDependencies } from '../api';
import { wsManager } from '../api/websocket';
import { setState, subscribe } from '../state';
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
  /** DecisionBanner instance — public for test access */
  decisionBanner: DecisionBanner | null = null;
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
    const unblockBtnText = this.task.status === 'blocked_by_human'
      ? this.getUnblockButtonText()
      : '';
    this.element.innerHTML = `
      <div id="task-header">
        <div class="task-header-main">
          <h1 class="task-title">${escapeHtml(this.task.title)}</h1>
          <div class="task-actions">
            <button id="task-edit-btn" class="btn-edit">Edit</button>
            ${this.task.status === 'blocked_by_human' ? `<button id="task-unblock-btn" class="btn-unblock">${escapeHtml(unblockBtnText)}</button>` : ''}
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

  /**
   * Determine the unblock button text based on current task state.
   * - If pending_question exists: "Answer Question"
   * - If DecisionBanner is showing: "Review Decision"
   * - Otherwise: "See Blocking Reason"
   */
  private getUnblockButtonText(): string {
    if (!this.task) return 'Unblock';

    // Check for pending clarification question
    if (this.task.pending_question && this.task.pending_question.trim() !== '') {
      return 'Answer Question';
    }

    // Check for pending decision
    if (this.decisionBanner?.isShowing) {
      return 'Review Decision';
    }

    // Generic — show task notes
    return 'See Blocking Reason';
  }

  /**
   * Update the unblock button text to reflect current state.
   * Called when WebSocket events arrive that change the block reason.
   * Public for test access.
   */
  updateUnblockButton(): void {
    if (!this.element || !this.task) return;
    if (this.task.status !== 'blocked_by_human') return;

    const btn = this.element.querySelector('#task-unblock-btn');
    if (btn) {
      btn.textContent = this.getUnblockButtonText();
    }
  }

  private async handleUnblock(): Promise<void> {
    if (!this.task || !this.element) return;

    // Check for pending clarification question
    if (this.task.pending_question && this.task.pending_question.trim() !== '') {
      // Scroll to clarification input
      const clarInput = this.element.querySelector('#clar-input') as HTMLTextAreaElement;
      if (clarInput) {
        clarInput.scrollIntoView({ behavior: 'smooth', block: 'center' });
        clarInput.focus();
      }
      return;
    }

    // Check for pending decision
    if (this.decisionBanner?.isShowing) {
      // Scroll to decision banner
      const banner = this.element.querySelector('#decision-banner');
      if (banner) {
        banner.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }
      return;
    }

    // No specific action available — show blocking reason in notes
    // The task notes contain the blocking reason
    const notesSection = this.element.querySelector('.task-meta') as HTMLElement | null;
    if (notesSection) {
      notesSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  }

  private async loadDependencies(): Promise<void> {
    if (!this.element) return;

    try {
      const data = await getTaskDependencies(this.taskId);
      const depsEl = this.element.querySelector('#task-dependencies') as HTMLElement | null;

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
      contextMessages: this.task?.context_messages || [],
    });

    container.appendChild(this.conversation.render());

    // Wire WebSocket events to Conversation for live streaming + clarification
    this.setupStreamingHandlers();

    // Render decision banner
    const bannerContainer = this.element.querySelector('#task-decision-banner') as HTMLElement | null;
    if (bannerContainer) {
      // Destroy previous banner if it exists to prevent listener accumulation
      if (this.decisionBanner) {
        this.decisionBanner.destroy();
      }
      this.decisionBanner = new DecisionBanner();
      this.decisionBanner.render(bannerContainer);
    }

    // Listen for decision events to update unblock button
    this.setupDecisionEventListeners();
  }

  /**
   * Listen for decision events so the unblock button text updates
   * when a new decision is pending.
   */
  private setupDecisionEventListeners(): void {
    const decisionEvents = [
      'decomposition_confirmation_required',
      'pr_approval_required',
      'turn_limit_reached',
      'planning_turn_limit_reached',
      'merge_conflict_resolution_turn_limit_reached',
      'critic_turn_limit_reached',
    ];

    for (const eventName of decisionEvents) {
      window.addEventListener(eventName, () => {
        this.updateUnblockButton();
      });
    }
  }

  /**
   * Wire WebSocket streaming events to the Conversation component.
   * Filters by taskId so only events for THIS task are displayed.
   */
  private setupStreamingHandlers(): void {
    const conv = this.conversation;
    if (!conv) return;

    const taskId = this.taskId;

    // Token-by-token streaming
    wsManager.on('token', (data: { text: string; task_id?: string }) => {
      if (data.task_id === taskId && data.text) {
        conv.appendToken(data.text);
      }
    });

    // Thinking/reasoning streaming
    wsManager.on('thinking', (data: { text: string; task_id?: string }) => {
      if (data.task_id === taskId && data.text) {
        conv.appendThinking(data.text);
      }
    });

    // Full content messages
    wsManager.on('content', (data: { text: string; task_id?: string }) => {
      if (data.task_id === taskId && data.text) {
        conv.appendToken(data.text); // Reuse appendToken for content (same rendering)
      }
    });

    // Tool calls
    wsManager.on('tool_call', (data: { name: string; arguments: Record<string, unknown>; task_id?: string }) => {
      if (data.task_id === taskId) {
        const callText = `${data.name}(${JSON.stringify(data.arguments)})`;
        conv.appendToken(callText); // Render as message content
      }
    });

    // Tool results
    wsManager.on('tool_result', (data: { result: string; task_id?: string }) => {
      if (data.task_id === taskId) {
        conv.appendToken(data.result); // Render as message content
      }
    });

    // Clarification requests
    wsManager.on('clarification_request', (data: { question: string; task_id?: string }) => {
      if (data.task_id === taskId && data.question) {
        conv.showClarification(data.question);
      }
    });
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
