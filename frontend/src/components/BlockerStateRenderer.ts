/**
 * Blocker Error Component
 *
 * Displays error or loading states for dependency blockers.
 */

import type { BlockerState } from '../types';

export class BlockerStateRenderer {
  /**
   * Render a blocker state (task, error, or loading)
   */
  render(blocker: BlockerState, onRetry?: (taskId?: string) => void): string {
    if (blocker.type === 'loading') {
      return this.renderLoading();
    }

    if (blocker.type === 'error') {
      return this.renderError(blocker, onRetry);
    }

    return this.renderTask(blocker);
  }

  /**
   * Render loading skeleton
   */
  private renderLoading(): string {
    return `
      <div class="blocker-skeleton">
        <div class="skeleton skeleton-rect skeleton-id"></div>
        <div class="skeleton skeleton-rect skeleton-title"></div>
      </div>
    `;
  }

  /**
   * Render error state with retry button
   */
  private renderError(error: BlockerLoadError, onRetry?: (taskId?: string) => void): string {
    const retryHtml = error.retryable
      ? `<button class="blocker-retry-btn" data-retry>Retry</button>`
      : '';

    return `
      <div class="blocker-error">
        <span class="blocker-error-icon">⚠️</span>
        <span class="blocker-error-message">${this.escapeHtml(error.message)}</span>
        ${retryHtml}
      </div>
    `;
  }

  /**
   * Render task blocker with id and title
   */
  private renderTask(task: BlockerTask): string {
    const truncatedTitle = this.truncateTitle(task.title);

    return `
      <a href="/task/${this.escapeHtml(task.id)}" class="dependency-link" data-task-id="${this.escapeHtml(task.id)}" title="${this.escapeHtml(task.title)}">
        <span class="blocker-id">${this.escapeHtml(task.id)}</span>
        <span class="blocker-title">${this.escapeHtml(truncatedTitle)}</span>
      </a>
    `;
  }

  /**
   * Truncate title for display
   */
  private truncateTitle(title: string, maxLength = 120): string {
    if (title.length <= maxLength) return title;
    return title.slice(0, maxLength - 3) + '...';
  }

  /**
   * Escape HTML special characters
   */
  private escapeHtml(text: string): string {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }
}
