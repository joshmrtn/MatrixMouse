/**
 * Conversation Component
 * Displays context messages as conversation bubbles
 */

import { interjectTask, interjectRepo, interjectWorkspace, answerTask } from '../api';
import { renderMarkdown, escapeHtml, ts } from '../utils';
import type { ContextMessage } from '../types';

export interface ConversationOptions {
  scope: string;
  taskId?: string;
  /** Pre-loaded conversation messages from task.context_messages. */
  contextMessages?: ContextMessage[];
  onInterjection?: (message: string) => Promise<void>;
}

export class Conversation {
  private element: HTMLElement | null = null;
  private logEl: HTMLElement | null = null;
  private inputEl: HTMLInputElement | null = null;
  private sendBtn: HTMLElement | null = null;
  private options: ConversationOptions;
  private streamingRow: HTMLElement | null = null;
  private thinkingRow: HTMLElement | null = null;

  constructor(options: ConversationOptions) {
    this.options = options;
  }

  render(): HTMLElement {
    this.element = document.createElement('div');
    this.element.id = 'conversation';
    this.element.innerHTML = `
      <div id="conversation-header">
        <span>${this.options.taskId ? 'Task Conversation' : `Channel: ${escapeHtml(this.options.scope)}`}</span>
      </div>
      <div id="clarification-banner" style="display:none;">
        <div class="clar-q">🔔 Awaiting your answer...</div>
        <div class="clar-row">
          <textarea id="clar-input" placeholder="Type your answer..." aria-label="Answer clarification question"></textarea>
          <button id="clar-answer-btn" aria-label="Submit clarification answer">Answer</button>
        </div>
      </div>
      <div id="inference-bar" style="display:none;">
        <div class="inf-spinner"></div>
        <span class="inf-stage">model thinking...</span>
      </div>
      <div id="conversation-log"></div>
      <div id="conversation-input">
        <input type="text" placeholder="Message..." />
        <button>Send</button>
      </div>
    `;

    this.logEl = this.element.querySelector('#conversation-log');
    this.inputEl = this.element.querySelector('#conversation-input input');
    this.sendBtn = this.element.querySelector('#conversation-input button');

    // Set up event listeners
    this.sendBtn?.addEventListener('click', () => this.sendInterjection());
    this.inputEl?.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') this.sendInterjection();
    });

    // Clarification answer
    const clarInput = this.element.querySelector('#clar-input') as HTMLTextAreaElement;
    const clarBtn = this.element.querySelector('#clar-answer-btn');
    clarBtn?.addEventListener('click', () => this.sendClarificationAnswer(clarInput.value));

    // Enter sends, Shift+Enter inserts newline
    clarInput?.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey && clarInput.value.trim()) {
        e.preventDefault();
        this.sendClarificationAnswer(clarInput.value);
      }
    });

    // Auto-resize clarification textarea
    clarInput?.addEventListener('input', () => {
      if (clarInput) {
        clarInput.style.height = 'auto';
        clarInput.style.height = `${Math.min(clarInput.scrollHeight, 150)}px`;
      }
    });

    // Load conversation
    this.loadConversation();

    return this.element;
  }

  private async loadConversation(): Promise<void> {
    if (!this.logEl) return;

    // Use pre-loaded messages from task.context_messages
    // (GET /tasks/{task_id} already returns context_messages — no need for /context)
    const messages = this.options.contextMessages || [];

    if (messages.length === 0) {
      this.logEl.innerHTML = '<div style="padding:14px;color:var(--text3)">No conversation yet.</div>';
      return;
    }

    this.logEl.innerHTML = messages
      .map((msg) => this.renderMessage(msg))
      .join('');

    this.logEl.scrollTop = this.logEl.scrollHeight;
  }

  private renderMessage(msg: ContextMessage): string {
    const role = msg.role || 'unknown';
    const content = msg.content || '';

    if (!content.trim()) return '';

    const bubbleClass =
      role === 'user'
        ? 'message-bubble user'
        : role === 'assistant'
          ? 'message-bubble assistant'
          : 'message-bubble system';

    const renderedContent =
      role === 'tool_call' || role === 'tool_result'
        ? `<pre style="margin:0;white-space:pre-wrap;">${escapeHtml(content)}</pre>`
        : renderMarkdown(content);

    return `
      <div class="${bubbleClass}">
        <div class="message-role">${escapeHtml(role)}</div>
        <div class="message-content">${renderedContent}</div>
      </div>
    `;
  }

  private async sendInterjection(): Promise<void> {
    if (!this.inputEl) return;

    const message = this.inputEl.value.trim();
    if (!message) return;

    this.inputEl.value = '';

    // Add user message to conversation
    this.addMessage({ role: 'user', content: message });

    try {
      if (this.options.taskId) {
        await interjectTask(this.options.taskId, message);
      } else if (this.options.scope === 'workspace') {
        await interjectWorkspace(message);
      } else {
        await interjectRepo(this.options.scope, message);
      }
    } catch (error) {
      console.error('[Conversation] Failed to send:', error);
      this.addMessage({ role: 'system', content: `Error: ${error}` });
    }
  }

  private sendClarificationAnswer(answer: string): void {
    if (!answer.trim() || !this.options.taskId) return;

    const clarBanner = this.element?.querySelector('#clarification-banner');
    if (clarBanner) {
      clarBanner.style.display = 'none';
    }

    // Reset textarea height
    const clarInput = this.element?.querySelector('#clar-input') as HTMLTextAreaElement;
    if (clarInput) clarInput.style.height = 'auto';

    this.addMessage({ role: 'user', content: answer });

    answerTask(this.options.taskId, answer).catch((error) => {
      console.error('[Conversation] Failed to send answer:', error);
    });
  }

  private addMessage(msg: ContextMessage): void {
    if (!this.logEl) return;

    const messageEl = document.createElement('div');
    messageEl.innerHTML = this.renderMessage(msg);
    const child = messageEl.firstElementChild;
    if (child) {
      this.logEl.appendChild(child);
      this.logEl.scrollTop = this.logEl.scrollHeight;
    }
  }

  appendToken(text: string): void {
    if (!this.logEl) return;

    if (!this.streamingRow) {
      this.streamingRow = document.createElement('div');
      this.streamingRow.className = 'message-bubble assistant streaming';
      this.streamingRow.innerHTML = `
        <div class="message-role">assistant</div>
        <div class="message-content" data-raw=""></div>
      `;
      this.logEl.appendChild(this.streamingRow);
    }

    const contentEl = this.streamingRow.querySelector('.message-content');
    if (contentEl) {
      const raw = (contentEl.getAttribute('data-raw') || '') + text;
      contentEl.setAttribute('data-raw', raw);
      contentEl.innerHTML = renderMarkdown(raw);
      this.logEl.scrollTop = this.logEl.scrollHeight;
    }
  }

  appendThinking(text: string): void {
    if (!this.logEl) return;

    if (!this.thinkingRow) {
      this.thinkingRow = document.createElement('div');
      this.thinkingRow.className = 'message-bubble thinking';
      this.thinkingRow.innerHTML = `
        <div class="message-role">thinking</div>
        <div class="message-content" data-raw=""></div>
      `;
      this.logEl.appendChild(this.thinkingRow);
    }

    const contentEl = this.thinkingRow.querySelector('.message-content');
    if (contentEl) {
      const raw = (contentEl.getAttribute('data-raw') || '') + text;
      contentEl.setAttribute('data-raw', raw);
      contentEl.textContent = raw;
      this.logEl.scrollTop = this.logEl.scrollHeight;
    }
  }

  showClarification(question: string): void {
    const banner = this.element?.querySelector('#clarification-banner');
    const questionEl = this.element?.querySelector('.clar-q');
    const input = this.element?.querySelector('#clar-input') as HTMLTextAreaElement;

    if (banner && questionEl && input) {
      banner.style.display = 'flex';
      questionEl.textContent = `🔔 ${question}`;
      input.value = '';
      input.style.height = 'auto';
      input.focus();
    }
  }

  hideClarification(): void {
    const banner = this.element?.querySelector('#clarification-banner');
    if (banner) {
      banner.style.display = 'none';
    }
  }
}
