/**
 * Channel Page Component
 * Shows conversation for workspace or repo scope with interjection support
 *
 * Features:
 * - Displays conversation history from /context endpoint
 * - Sends interjections to workspace or repo channels
 * - Shows clarification questions with answer input
 * - Loading and error states
 * - Markdown rendering for assistant messages
 */

import { getContext, interjectWorkspace, interjectRepo, getPending } from '../api';
import { wsManager } from '../api/websocket';
import { renderMarkdown, escapeHtml } from '../utils';
import type { ContextMessage } from '../types';

export class ChannelPage {
  private element: HTMLElement | null = null;
  private logEl: HTMLElement | null = null;
  private inputEl: HTMLTextAreaElement | null = null;
  private sendBtn: HTMLElement | null = null;
  private scope: string;
  private isLoading: boolean = false;
  private isSending: boolean = false;  // Track sending state
  private scrollPending: boolean = false;  // Throttle scroll updates
  private error: string | null = null;
  private abortController = new AbortController();
  private messageIds = new Set<string>();
  private pendingCheckFailures = 0;
  private readonly MAX_MESSAGE_IDS = 1000;  // LRU cache limit (~100KB memory footprint for typical messages)

  constructor(scope: string) {
    this.scope = scope;
  }

  async render(container: HTMLElement): Promise<void> {
    // Reinitialize AbortController on each render to support re-render after destroy
    this.abortController = new AbortController();
    
    container.innerHTML = `
      <div id="channel-page">
        <div id="channel-header">
          <h1>Channel: ${escapeHtml(this.scope)}</h1>
        </div>

        <div id="clarification-banner" role="alert" aria-live="assertive">
          <div class="clar-q">🔔 Awaiting your answer...</div>
          <div class="clar-row">
            <textarea id="clar-input" placeholder="Type your answer..." aria-label="Answer clarification question"></textarea>
            <button id="clar-answer-btn" aria-label="Submit clarification answer">Answer</button>
          </div>
        </div>

        <div id="conversation">
          <div id="conversation-log" role="log" aria-live="polite" aria-label="Conversation history">
            <div class="loading-state">Loading conversation...</div>
          </div>
        </div>

        <div id="channel-input">
          <textarea placeholder="Message ${escapeHtml(this.scope)}..." aria-label="Message input for ${escapeHtml(this.scope)} channel"></textarea>
          <button aria-label="Send message">Send</button>
        </div>
      </div>
    `;

    this.element = container.querySelector('#channel-page');
    this.logEl = this.element?.querySelector('#conversation-log');
    this.inputEl = this.element?.querySelector('#channel-input textarea') as HTMLTextAreaElement;
    this.sendBtn = this.element?.querySelector('#channel-input button');

    // Setup event listeners
    this.setupEventListeners();

    // Setup WebSocket handlers for real-time updates
    this.setupWebSocketHandlers();

    // Load conversation and pending question
    await this.loadConversation();
    await this.checkPendingQuestion();
  }

  /**
   * Clean up event listeners and resources
   * Call this when navigating away from the page
   */
  destroy(): void {
    this.abortController.abort();
    this.element = null;
    this.logEl = null;
    this.inputEl = null;
    this.sendBtn = null;
    this.messageIds.clear();
    
    // Clean up WebSocket handlers
    wsManager.offToken(this.handleToken);
    wsManager.offContent(this.handleContent);
    wsManager.offToolCall(this.handleToolCall);
    wsManager.offToolResult(this.handleToolResult);
  }

  private setupEventListeners(): void {
    if (!this.element) return;

    const { signal } = this.abortController;

    // Send interjection on button click
    this.sendBtn?.addEventListener('click', () => this.sendInterjection(), { signal });

    // Send interjection on Enter key (Shift+Enter inserts newline)
    this.inputEl?.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();  // Prevent default newline insertion
        this.sendInterjection();
      }
      // If Shift+Enter: let default behavior insert newline
    }, { signal });

    // Setup auto-resize for channel textarea
    this.inputEl?.addEventListener('input', () => this.autoResizeTextarea(this.inputEl), { signal });

    // Clarification answer on button click
    const clarInput = this.element.querySelector('#clar-input') as HTMLTextAreaElement;
    const clarBtn = this.element.querySelector('#clar-answer-btn');
    clarBtn?.addEventListener('click', () => {
      if (clarInput) this.sendClarificationAnswer(clarInput.value);
    }, { signal });

    // Clarification answer on Enter key (Shift+Enter inserts newline)
    clarInput?.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey && clarInput.value.trim()) {
        e.preventDefault();  // Prevent default newline insertion
        this.sendClarificationAnswer(clarInput.value);
      }
      // If Shift+Enter: let default behavior insert newline
    }, { signal });

    // Setup auto-resize for clarification textarea
    clarInput?.addEventListener('input', () => this.autoResizeTextarea(clarInput), { signal });
  }

  private setupWebSocketHandlers(): void {
    // Register WebSocket handlers for real-time streaming
    wsManager.onToken(this.handleToken);
    wsManager.onContent(this.handleContent);
    wsManager.onToolCall(this.handleToolCall);
    wsManager.onToolResult(this.handleToolResult);
  }

  // WebSocket event handlers
  private handleToken = (data: { text: string }): void => {
    // Intentionally empty: token-by-token streaming is handled via content events
    // Keep this handler registered for API completeness and future token-streaming implementation
  };

  private handleContent = (data: { text: string }): void => {
    try {
      // Validate event data structure from backend
      if (!this.logEl || !data?.text || typeof data.text !== 'string') return;
      this.addMessage({ role: 'assistant', content: data.text });
    } catch (error) {
      console.error('[ChannelPage] handleContent failed:', error);
    }
  };

  private handleToolCall = (data: { name: string; arguments: Record<string, unknown> }): void => {
    try {
      // Validate event data structure from backend
      if (!this.logEl || !data?.name || typeof data.name !== 'string') return;
      if (!data.arguments || typeof data.arguments !== 'object') return;
      this.addMessage({
        role: 'tool_call',
        content: `${data.name}(${JSON.stringify(data.arguments)})`,
      });
    } catch (error) {
      console.error('[ChannelPage] handleToolCall failed:', error);
    }
  };

  private handleToolResult = (data: { result: string }): void => {
    try {
      // Validate event data structure from backend
      if (!this.logEl || !data?.result || typeof data.result !== 'string') return;
      this.addMessage({ role: 'tool_result', content: data.result });
    } catch (error) {
      console.error('[ChannelPage] handleToolResult failed:', error);
    }
  };

  private async loadConversation(): Promise<void> {
    if (!this.logEl || this.isLoading) return;  // Guard against concurrent calls

    this.isLoading = true;
    this.renderLoadingState();

    try {
      const data = await getContext(this.scope === 'workspace' ? undefined : this.scope);
      
      // Check if component was destroyed during async operation
      if (this.abortController.signal.aborted) return;
      
      const messages = data.messages || [];

      this.isLoading = false;
      this.error = null;  // Clear any previous error

      if (messages.length === 0) {
        this.renderEmptyState();
        return;
      }

      this.renderMessages(messages);
      this.scrollToBottom();
    } catch (error) {
      this.isLoading = false;
      this.error = error instanceof Error ? error.message : 'Unknown error';
      console.error('[ChannelPage] Failed to load conversation:', error);
      this.renderErrorState(this.error);
    }
  }

  private async checkPendingQuestion(): Promise<void> {
    try {
      const data = await getPending();
      this.pendingCheckFailures = 0;  // Reset on success
      
      // Validate response structure
      if (!data || typeof data.pending === 'undefined') {
        console.error('[ChannelPage] Invalid pending response');
        return;
      }
      
      if (data.pending) {
        this.showClarificationBanner(data.pending);
      }
    } catch (error) {
      this.pendingCheckFailures++;
      // Only log first 3 failures to avoid spam
      if (this.pendingCheckFailures <= 3) {
        console.error('[ChannelPage] Failed to check pending question:', error);
      }
    }
  }

  private renderLoadingState(): void {
    if (!this.logEl) return;
    this.logEl.innerHTML = '<div class="loading-state">Loading conversation...</div>';
  }

  private renderEmptyState(): void {
    if (!this.logEl) return;
    this.logEl.innerHTML = '<div class="empty-message">No conversation yet.</div>';
  }

  private renderErrorState(message: string): void {
    if (!this.logEl) return;
    this.logEl.innerHTML = `
      <div class="error-message">
        <div>⚠️ Failed to load conversation</div>
        <div class="error-detail">Please try again</div>
        <button class="retry-btn" id="retry-load">Retry</button>
      </div>
    `;

    const retryBtn = this.logEl.querySelector('#retry-load');
    retryBtn?.addEventListener('click', () => this.loadConversation(), { 
      signal: this.abortController.signal 
    });
  }

  private renderMessages(messages: ContextMessage[]): void {
    if (!this.logEl) return;

    // Filter out system messages for cleaner view and empty messages
    const visibleMessages = messages.filter(msg => {
      if (msg.role === 'system') return false;
      if (!msg.content || !msg.content.trim()) return false;
      return true;
    });

    if (visibleMessages.length === 0) {
      this.renderEmptyState();
      return;
    }

    this.logEl.innerHTML = visibleMessages
      .map(msg => this.renderMessage(msg))
      .join('');
  }

  private renderMessage(msg: ContextMessage): string {
    const role = msg.role || 'unknown';
    const content = msg.content || '';

    const bubbleClass =
      role === 'user'
        ? 'message-bubble user'
        : role === 'assistant'
          ? 'message-bubble assistant'
          : role === 'tool_call' || role === 'tool_result'
            ? 'message-bubble tool'
            : 'message-bubble system';

    // Escape HTML for user messages to prevent XSS
    // Assistant messages use markdown rendering (which now escapes HTML internally)
    const renderedContent =
      role === 'user'
        ? escapeHtml(content)  // Plain text, no markdown
        : role === 'tool_call' || role === 'tool_result'
          ? `<pre style="margin:0;white-space:pre-wrap;">${escapeHtml(content)}</pre>`
          : renderMarkdown(content);  // Assistant messages with markdown

    return `
      <div class="${bubbleClass}">
        <div class="message-role">${escapeHtml(role)}</div>
        <div class="message-content">${renderedContent}</div>
      </div>
    `;
  }

  /**
   * Auto-resize textarea to fit content (up to max-height)
   */
  private autoResizeTextarea(textarea: HTMLTextAreaElement | null): void {
    if (!textarea) return;

    // Reset height to 'auto' first to get accurate scrollHeight
    textarea.style.height = 'auto';

    // Cap height at max-height (200px)
    const newHeight = Math.min(textarea.scrollHeight, 200);
    textarea.style.height = `${newHeight}px`;
  }

  /**
   * Reset textarea height to initial state
   */
  private resetTextareaHeight(): void {
    if (this.inputEl) {
      this.inputEl.style.height = 'auto';
    }
  }

  private async sendInterjection(): Promise<void> {
    if (!this.inputEl || this.isSending) return;

    const message = this.inputEl.value.trim();
    if (!message) return;

    // Set sending state
    this.isSending = true;
    this.updateSendButtonState();

    // Clear input immediately (optimistic UI)
    this.inputEl.value = '';
    this.resetTextareaHeight();
    // Trigger input event to ensure auto-resize fires on empty content
    this.inputEl.dispatchEvent(new Event('input', { bubbles: true }));

    // Add user message to conversation optimistically
    this.addMessage({ role: 'user', content: message });

    try {
      await this.sendToChannel(message);
    } catch (error) {
      console.error('[ChannelPage] Failed to send interjection:', error);
      this.addMessage({ role: 'system', content: this.formatErrorMessage(error, 'Error') });
    } finally {
      // Clear sending state
      this.isSending = false;
      this.updateSendButtonState();
    }
  }

  /**
   * Send message to workspace or repo channel based on scope
   */
  private async sendToChannel(message: string): Promise<void> {
    if (this.scope === 'workspace') {
      await interjectWorkspace(message);
    } else {
      await interjectRepo(this.scope, message);
    }
  }

  /**
   * Format error message for display
   */
  private formatErrorMessage(error: unknown, prefix = 'Error'): string {
    const msg = error instanceof Error ? error.message : 'Unknown error';
    return `${prefix}: ${msg}`;
  }

  private updateSendButtonState(): void {
    if (this.sendBtn) {
      this.sendBtn.textContent = this.isSending ? 'Sending...' : 'Send';
      this.sendBtn.disabled = this.isSending;
      this.sendBtn.classList.toggle('sending', this.isSending);
    }
  }

  private async sendClarificationAnswer(answer: string): Promise<void> {
    if (!answer.trim()) return;

    // Store answer for potential recovery
    const clarInput = this.element?.querySelector('#clar-input') as HTMLTextAreaElement;
    const originalValue = clarInput?.value || '';

    try {
      // Send to backend first
      await this.sendToChannel(answer);

      // Only clear input and hide banner on success
      if (clarInput) clarInput.value = '';
      // Reset textarea height
      if (clarInput) clarInput.style.height = 'auto';
      this.hideClarificationBanner();
      this.addMessage({ role: 'user', content: answer });
    } catch (error) {
      console.error('[ChannelPage] Failed to send clarification answer:', error);
      this.addMessage({ role: 'system', content: this.formatErrorMessage(error, 'Failed to send answer') });

      // Restore input value on failure (only if component still exists)
      if (clarInput && this.element) {
        clarInput.value = originalValue;
        clarInput.focus();
      }
    }
  }

  private addMessage(msg: ContextMessage): void {
    if (!this.logEl) return;

    // Deduplicate messages by role + content + tool_call_id (use :: delimiter to prevent collisions)
    // Including tool_call_id prevents deduplicating distinct tool calls with same content
    const msgId = `${msg.role}::${msg.content}::${msg.tool_call_id || ''}`;
    if (this.messageIds.has(msgId)) return;

    this.messageIds.add(msgId);

    // Prevent unbounded growth of messageIds set (LRU eviction)
    if (this.messageIds.size > this.MAX_MESSAGE_IDS) {
      const firstKey = this.messageIds.keys().next().value;
      if (firstKey) this.messageIds.delete(firstKey);
    }

    // Remove "no conversation" placeholder if present
    const placeholder = this.logEl.querySelector('.empty-message');
    if (placeholder) placeholder.remove();

    // Remove loading state if present
    const loading = this.logEl.querySelector('.loading-state');
    if (loading) loading.remove();

    const messageHtml = this.renderMessage(msg);
    const messageEl = document.createElement('div');
    messageEl.innerHTML = messageHtml;
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
    const input = this.element.querySelector('#clar-input') as HTMLTextAreaElement;

    if (banner && questionEl && input) {
      banner.classList.add('active');
      questionEl.textContent = `🔔 ${question}`;
      input.value = '';
      input.focus();
    }
  }

  private hideClarificationBanner(): void {
    if (!this.element) return;

    const banner = this.element.querySelector('#clarification-banner');
    if (banner) {
      banner.classList.remove('active');
    }
  }

  private scrollToBottom(): void {
    if (this.logEl && !this.scrollPending) {
      this.scrollPending = true;
      requestAnimationFrame(() => {
        if (this.logEl) {
          this.logEl.scrollTop = this.logEl.scrollHeight;
        }
        this.scrollPending = false;
      });
    }
  }
}
