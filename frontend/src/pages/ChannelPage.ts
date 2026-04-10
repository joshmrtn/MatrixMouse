/**
 * Channel Page Component
 *
 * Task request surface for the Manager agent.
 * - Describe what you want done informally → creates a Manager task
 * - Or use the formal task creation form
 *
 * NOT a chat interface. Interjections create Manager tasks via the backend.
 */

import { interjectWorkspace, interjectRepo } from '../api';
import { escapeHtml } from '../utils';

export class ChannelPage {
  private element: HTMLElement | null = null;
  private inputEl: HTMLTextAreaElement | null = null;
  private sendBtn: HTMLElement | null = null;
  private messageEl: HTMLElement | null = null;
  private scope: string;
  private isSending = false;
  private abortController = new AbortController();

  constructor(scope: string) {
    this.scope = scope;
  }

  async render(container: HTMLElement): Promise<void> {
    this.abortController = new AbortController();

    const channelLabel = this.scope === 'workspace' ? 'Workspace' : this.scope;
    const placeholder = `Describe what you want the Manager to do${this.scope !== 'workspace' ? ` for ${this.scope}` : ''}...`;

    container.innerHTML = `
      <div id="channel-page">
        <div id="channel-header">
          <h1>Channel: ${escapeHtml(channelLabel)}</h1>
        </div>

        <div id="channel-description">
          Describe a task for the Manager agent to handle.
          Your message will create a new Manager task.
          <a href="/task-new" class="channel-link">Or create a task manually →</a>
        </div>

        <div id="channel-input">
          <textarea placeholder="${escapeHtml(placeholder)}" aria-label="Task description for ${escapeHtml(channelLabel)}"></textarea>
          <button aria-label="Send to Manager">Send</button>
        </div>

        <div class="channel-message" id="channel-message" style="display:none;"></div>
      </div>
    `;

    this.element = container.querySelector('#channel-page');
    this.inputEl = this.element?.querySelector('#channel-input textarea') as HTMLTextAreaElement;
    this.sendBtn = this.element?.querySelector('#channel-input button');
    this.messageEl = this.element?.querySelector('#channel-message');

    this.setupEventListeners();
  }

  /**
   * Clean up event listeners and resources
   */
  destroy(): void {
    this.abortController.abort();
    this.element = null;
    this.inputEl = null;
    this.sendBtn = null;
    this.messageEl = null;
  }

  private setupEventListeners(): void {
    if (!this.element) return;

    const { signal } = this.abortController;

    this.sendBtn?.addEventListener('click', () => this.sendInterjection(), { signal });

    this.inputEl?.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        this.sendInterjection();
      }
    }, { signal });

    this.inputEl?.addEventListener('input', () => this.autoResizeTextarea(this.inputEl), { signal });
  }

  /**
   * Auto-resize textarea to fit content (up to 200px)
   */
  private autoResizeTextarea(textarea: HTMLTextAreaElement | null): void {
    if (!textarea) return;
    textarea.style.height = 'auto';
    const newHeight = Math.min(textarea.scrollHeight, 200);
    textarea.style.height = `${newHeight}px`;
  }

  private async sendInterjection(): Promise<void> {
    if (!this.inputEl || this.isSending) return;

    const message = this.inputEl.value.trim();
    if (!message) return;

    this.isSending = true;
    this.updateSendButtonState();

    this.inputEl.value = '';
    this.inputEl.style.height = 'auto';
    this.hideMessage();

    try {
      const result = await this.sendToChannel(message);

      // Redirect to the newly created Manager task's TaskPage
      const taskId = result?.manager_task_id;
      if (taskId) {
        window.history.pushState({}, '', `/task/${taskId}`);
        window.dispatchEvent(new Event('popstate'));
      } else {
        this.showMessage('Message sent to Manager.', 'success');
      }
    } catch (error) {
      const msg = error instanceof Error ? error.message : 'Unknown error';
      this.showMessage(`Failed to send: ${msg}`, 'error');
    } finally {
      this.isSending = false;
      this.updateSendButtonState();
    }
  }

  /**
   * Send message to workspace or repo channel
   */
  private async sendToChannel(message: string): Promise<{ ok: boolean; manager_task_id?: string }> {
    if (this.scope === 'workspace') {
      return interjectWorkspace(message);
    } else {
      return interjectRepo(this.scope, message);
    }
  }

  private updateSendButtonState(): void {
    if (this.sendBtn) {
      this.sendBtn.textContent = this.isSending ? 'Sending...' : 'Send';
      this.sendBtn.disabled = this.isSending;
      this.sendBtn.classList.toggle('sending', this.isSending);
    }
  }

  private showMessage(text: string, type: 'success' | 'error'): void {
    if (!this.messageEl) return;
    this.messageEl.textContent = text;
    this.messageEl.className = `channel-message ${type}`;
    this.messageEl.style.display = 'block';
  }

  private hideMessage(): void {
    if (!this.messageEl) return;
    this.messageEl.style.display = 'none';
  }
}
