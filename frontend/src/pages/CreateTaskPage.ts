/**
 * Create Task Page Component
 *
 * Wrapper page for the CreateTaskForm.
 * Provides:
 * - Page layout with header
 * - Back button navigation
 * - Success/error message display
 * - Post-creation redirect
 */

import { CreateTaskForm } from '../components/CreateTaskForm';
import type { Task } from '../types';

export class CreateTaskPage {
  private element: HTMLElement | null = null;
  private form: CreateTaskForm | null = null;

  /**
   * Render the page
   */
  async render(container: HTMLElement): Promise<void> {
    container.innerHTML = `
      <div id="create-task-page">
        <div class="page-header">
          <h1>Create New Task</h1>
          <button class="btn-back" id="back-btn">← Back to Tasks</button>
        </div>

        <div id="create-task-form-container"></div>
        <div id="create-task-message" class="message" style="display: none;"></div>
      </div>
    `;

    this.element = container.querySelector('#create-task-page');
    this.setupBackButton();
    this.renderForm();
  }

  /**
   * Set up back button navigation
   */
  private setupBackButton(): void {
    const backBtn = this.element?.querySelector('#back-btn');
    backBtn?.addEventListener('click', () => {
      window.history.pushState({}, '', '/task-list');
      window.dispatchEvent(new Event('popstate'));
    });
  }

  /**
   * Render the form component
   */
  private renderForm(): void {
    const container = this.element?.querySelector('#create-task-form-container');
    if (!container) return;

    this.form = new CreateTaskForm({
      onSuccess: (task) => this.handleSuccess(task),
      onCancel: () => this.handleCancel(),
    });

    this.form.render(container);
  }

  /**
   * Handle successful task creation
   */
  private handleSuccess(task: Task): void {
    this.showMessage(`Task created: ${task.id}`, 'success');

    // Redirect to task detail after short delay
    setTimeout(() => {
      window.history.pushState({}, '', `/task/${task.id}`);
      window.dispatchEvent(new Event('popstate'));
    }, 1500);
  }

  /**
   * Handle form cancellation
   */
  private handleCancel(): void {
    window.history.pushState({}, '', '/task-list');
    window.dispatchEvent(new Event('popstate'));
  }

  /**
   * Show message to user
   */
  private showMessage(text: string, type: 'success' | 'error'): void {
    if (!this.element) return;

    const messageEl = this.element.querySelector('#create-task-message') as HTMLElement;
    if (messageEl) {
      messageEl.textContent = text;
      messageEl.className = `message ${type}`;
      messageEl.style.display = 'block';

      // Auto-hide success messages after 5 seconds
      if (type === 'success') {
        setTimeout(() => {
          messageEl.style.display = 'none';
        }, 5000);
      }
    }
  }

  /**
   * Clean up
   */
  destroy(): void {
    if (this.form) {
      this.form.destroy();
      this.form = null;
    }
    this.element = null;
  }
}
