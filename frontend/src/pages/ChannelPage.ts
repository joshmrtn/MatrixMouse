/**
 * Channel Page Component
 * Shows conversation for workspace or repo scope with interjection support
 */

import { getContext, interjectWorkspace, interjectRepo, getPending } from '../api';
import { renderMarkdown, escapeHtml } from '../utils';
import type { ContextMessage } from '../types';

export class ChannelPage {
  private element: HTMLElement | null = null;
  private logEl: HTMLElement | null = null;
  private inputEl: HTMLInputElement | null = null;
  private sendBtn: HTMLElement | null = null;
  private scope: string;
  private pendingQuestion: string | null = null;

  constructor(scope: string) {
    this.scope = scope;
  }

  async render(container: HTMLElement): Promise<void> {
    container.innerHTML = `
      <div id="channel-page">
        <div id="channel-header">
          <span>Channel: ${escapeHtml(this.scope)}</span>
        </div>
        <div id="clarification-banner" style="display:none;">
          <div class="clar-q">🔔 Awaiting your answer...</div>
          <div class="clar-row">
            <input id="clar-input" type="text" placeholder="Type your answer..." />
            <button id="clar-answer-btn">Answer</button>
          </div>
        </div>
        <div id="conversation">
          <div id="conversation-log"></div>
        </div>
        <div id="channel-input">
          <input type="text" placeholder="Message ${escapeHtml(this.scope)}..." />
          <button>Send</button>
        </div>
      </div>
    `;

    this.element = container.querySelector('#channel-page');
    this.logEl = this.element?.querySelector('#conversation-log');
    this.inputEl = this.element?.querySelector('#channel-input input');
    this.sendBtn = this.element?.querySelector('#channel-input button');

    // Setup event listeners
    this.setupEventListeners();

    // Load conversation and pending question
    await this.loadConversation();
    await this.checkPendingQuestion();
  }

  private setupEventListeners(): void {
    if (!this.element) return;

    // Send interjection on button click
    this.sendBtn?.addEventListener('click', () => this.sendInterjection());

    // Send interjection on Enter key
    this.inputEl?.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        this.sendInterjection();
      }
    });

    // Clarification answer on button click
    const clarInput = this.element.querySelector('#clar-input') as HTMLInputElement;
    const clarBtn = this.element.querySelector('#clar-answer-btn');
    clarBtn?.addEventListener('click', () => {
      if (clarInput) this.sendClarificationAnswer(clarInput.value);
    });

    // Clarification answer on Enter key
    clarInput?.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && clarInput.value.trim()) {
        this.sendClarificationAnswer(clarInput.value);
      }
    });
  }

  private async loadConversation(): Promise<void> {
    if (!this.logEl) return;

    try {
      const data = await getContext(this.scope === 'workspace' ? undefined : this.scope);
      const messages = data.messages || [];

      if (messages.length === 0) {
        this.logEl.innerHTML = '<div style="padding:14px;color:var(--text3)">No conversation yet.</div>';
        return;
      }

      this.logEl.innerHTML = messages
        .filter(msg => msg.role !== 'system') // Filter out system messages for cleaner view
        .map(msg => this.renderMessage(msg))
        .join('');

      this.scrollToBottom();
    } catch (error) {
      console.error('[ChannelPage] Failed to load conversation:', error);
      this.logEl.innerHTML = '<div style="padding:14px;color:var(--text3)">Failed to load conversation.</div>';
    }
  }

  private async checkPendingQuestion(): Promise<void> {
    try {
      const data = await getPending();
      if (data.pending) {
        this.pendingQuestion = data.pending;
        this.showClarificationBanner(data.pending);
      }
    } catch (error) {
      // No pending question or error - that's ok
    }
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

    // Clear input immediately
    this.inputEl.value = '';

    // Add user message to conversation optimistically
    this.addMessage({ role: 'user', content: message });

    try {
      if (this.scope === 'workspace') {
        await interjectWorkspace(message);
      } else {
        await interjectRepo(this.scope, message);
      }
    } catch (error) {
      console.error('[ChannelPage] Failed to send interjection:', error);
      this.addMessage({ role: 'system', content: `Error: ${error}` });
    }
  }

  private sendClarificationAnswer(answer: string): void {
    if (!answer.trim()) return;

    // Hide banner
    this.hideClarificationBanner();

    // Add answer as user message
    this.addMessage({ role: 'user', content: answer });

    // Send to backend
    if (this.scope === 'workspace') {
      interjectWorkspace(answer).catch(console.error);
    } else {
      interjectRepo(this.scope, answer).catch(console.error);
    }

    // Clear input
    const clarInput = this.element?.querySelector('#clar-input') as HTMLInputElement;
    if (clarInput) clarInput.value = '';
  }

  private addMessage(msg: ContextMessage): void {
    if (!this.logEl) return;

    // Remove "no conversation" placeholder if present
    const placeholder = this.logEl.querySelector('[style*="color:var(--text3)"]');
    if (placeholder) placeholder.remove();

    const messageEl = document.createElement('div');
    messageEl.innerHTML = this.renderMessage(msg);
    const child = messageEl.firstElementChild;
    if (child) {
      this.logEl.appendChild(child);
      this.scrollToBottom();
    }
  }

  private showClarificationBanner(question: string): void {
    if (!this.element) return;

    const banner = this.element.querySelector('#clarification-banner');
    const questionEl = this.element.querySelector('.clar-q');
    const input = this.element.querySelector('#clar-input') as HTMLInputElement;

    if (banner && questionEl && input) {
      banner.style.display = 'flex';
      questionEl.textContent = `🔔 ${question}`;
      input.value = '';
      input.focus();
    }
  }

  private hideClarificationBanner(): void {
    if (!this.element) return;

    const banner = this.element.querySelector('#clarification-banner');
    if (banner) {
      banner.style.display = 'none';
    }
    this.pendingQuestion = null;
  }

  private scrollToBottom(): void {
    if (this.logEl) {
      this.logEl.scrollTop = this.logEl.scrollHeight;
    }
  }
}
