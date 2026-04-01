/**
 * Status Dashboard Page Component
 * Shows blocked and waiting tasks in three sections:
 * - Blocked by Human: Tasks awaiting human input/decision
 * - Blocked by Dependencies: Tasks waiting on other tasks
 * - Waiting: Tasks waiting due to rate limits, budgets, etc.
 */

import { getState, subscribe } from '../state';
import { escapeHtml } from '../utils';
import { getTaskDependencies } from '../api/client';
import { BlockerStateRenderer } from '../components/BlockerStateRenderer';
import type { BlockedTaskEntry, BlockerState, BlockerLoadError } from '../types';

export class StatusPage {
  private element: HTMLElement | null = null;
  private blockerRenderer: BlockerStateRenderer;

  constructor() {
    this.blockerRenderer = new BlockerStateRenderer();

    // Subscribe to state changes for real-time updates
    subscribe((state) => {
      if (state.blockedReport) {
        this.renderSections();
      }
    });
  }

  render(container: HTMLElement): void {
    container.innerHTML = `
      <div id="status-page">
        <h1>Status Dashboard</h1>

        <div id="status-blocked-human">
          <div class="status-section-header">
            <span class="status-section-icon">⦸</span>
            <span class="status-section-title">Blocked by Human</span>
          </div>
          <div class="status-section-content"></div>
        </div>

        <div id="status-blocked-deps">
          <div class="status-section-header">
            <span class="status-section-icon">⊞</span>
            <span class="status-section-title">Blocked by Dependencies</span>
          </div>
          <div class="status-section-content"></div>
        </div>

        <div id="status-waiting">
          <div class="status-section-header">
            <span class="status-section-icon">⋯</span>
            <span class="status-section-title">Waiting</span>
          </div>
          <div class="status-section-content"></div>
        </div>
      </div>
    `;

    this.element = container.querySelector('#status-page');

    // Render sections immediately (in case state was set before render)
    this.renderSections();
  }

  private renderSections(): void {
    if (!this.element) return;

    const { blockedReport } = getState();
    if (!blockedReport) return;

    this.renderSection(
      '#status-blocked-human',
      blockedReport.human,
      'No tasks blocked by human input.'
    );

    this.renderSection(
      '#status-blocked-deps',
      blockedReport.dependencies,
      'No tasks blocked by dependencies.',
      true
    );

    this.renderSection(
      '#status-waiting',
      blockedReport.waiting,
      'No tasks waiting.'
    );
  }

  private async renderSection(
    sectionSelector: string,
    tasks: BlockedTaskEntry[],
    emptyMessage: string,
    showDependencyLinks = false
  ): Promise<void> {
    if (!this.element) return;

    const section = this.element.querySelector(sectionSelector);
    if (!section) return;

    const contentEl = section.querySelector('.status-section-content');
    if (!contentEl) return;

    if (tasks.length === 0) {
      contentEl.innerHTML = `<div class="empty-message">${emptyMessage}</div>`;
      return;
    }

    // For dependencies section, show loading skeletons first, then fetch blocker details
    if (showDependencyLinks) {
      // Show loading state immediately
      contentEl.innerHTML = tasks
        .map((task) => this.renderTaskItemWithLoading(task))
        .join('');

      // Fetch blocker details in background
      const tasksWithBlockers = await Promise.all(
        tasks.map(async (task) => {
          try {
            const deps = await getTaskDependencies(task.id);
            const blockers: BlockerState[] = deps.dependencies.map((d) => ({
              type: 'task',
              id: d.id,
              title: d.title,
            }));
            return { ...task, blockers };
          } catch (e) {
            console.error(`Failed to fetch dependencies for task ${task.id}:`, e);
            const errorBlocker: BlockerLoadError = {
              type: 'error',
              message: 'Failed to load dependencies',
              retryable: true,
            };
            return { ...task, blockers: [errorBlocker], error: errorBlocker };
          }
        })
      );

      // Re-render with actual data
      contentEl.innerHTML = tasksWithBlockers
        .map((task) => this.renderTaskItem(task, true))
        .join('');

      // Set up retry handlers
      this.setupRetryHandlers(contentEl, tasksWithBlockers);
    } else {
      contentEl.innerHTML = tasks
        .map((task) => this.renderTaskItem(task, false))
        .join('');
    }

    // Set up dependency link clicks
    if (showDependencyLinks) {
      contentEl.querySelectorAll('.dependency-link').forEach((link) => {
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
  }

  private renderTaskItem(
    task: BlockedTaskEntry & { blockers?: BlockerState[] },
    showDependencyLinks = false
  ): string {
    const taskHtml = `
      <div class="status-task-item">
        <a href="/task/${escapeHtml(task.id)}" class="status-task-link" data-task-id="${escapeHtml(task.id)}">
          <span class="status-task-id">${escapeHtml(task.id)}</span>
          <span class="status-task-title">${escapeHtml(task.title)}</span>
        </a>
        ${showDependencyLinks
          ? this.renderBlockersList(task.blockers || [])
          : `<div class="status-task-reason">${escapeHtml(task.blocking_reason)}</div>`
        }
      </div>
    `;
    return taskHtml;
  }

  private renderTaskItemWithLoading(task: BlockedTaskEntry): string {
    return `
      <div class="status-task-item">
        <a href="/task/${escapeHtml(task.id)}" class="status-task-link" data-task-id="${escapeHtml(task.id)}">
          <span class="status-task-id">${escapeHtml(task.id)}</span>
          <span class="status-task-title">${escapeHtml(task.title)}</span>
        </a>
        <div class="blockers-list">
          <div class="blockers-label">Waiting on:</div>
          ${this.blockerRenderer.render({ type: 'loading' })}
        </div>
      </div>
    `;
  }

  private renderBlockersList(blockers: BlockerState[]): string {
    if (!blockers || blockers.length === 0) return '';

    const blockerItems = blockers
      .map((blocker) => this.blockerRenderer.render(blocker))
      .join('');

    return `
      <div class="blockers-list">
        <div class="blockers-label">Waiting on:</div>
        ${blockerItems}
      </div>
    `;
  }

  private setupRetryHandlers(
    contentEl: Element,
    tasksWithBlockers: (BlockedTaskEntry & { blockers?: BlockerState[]; error?: BlockerLoadError })[]
  ): void {
    // Set up retry button handlers
    contentEl.querySelectorAll('.blocker-retry-btn').forEach((btn, index) => {
      btn.addEventListener('click', async (e) => {
        e.stopPropagation();
        const task = tasksWithBlockers[index];
        if (!task) return;

        // Show loading state while retrying
        const blockerEl = (btn as HTMLElement).closest('.blocker-error');
        if (blockerEl) {
          blockerEl.innerHTML = this.blockerRenderer.render({ type: 'loading' });
        }

        // Retry fetching dependencies
        try {
          const deps = await getTaskDependencies(task.id);
          const blockers: BlockerState[] = deps.dependencies.map((d) => ({
            type: 'task',
            id: d.id,
            title: d.title,
          }));

          // Re-render blockers list
          const blockersList = blockerEl?.closest('.blockers-list');
          if (blockersList) {
            blockersList.innerHTML = `
              <div class="blockers-label">Waiting on:</div>
              ${this.renderBlockersList(blockers)}
            `;
          }
        } catch (retryError) {
          console.error(`Retry failed for task ${task.id}:`, retryError);
          // Re-show error
          if (blockerEl) {
            blockerEl.innerHTML = this.blockerRenderer.render({
              type: 'error',
              message: 'Retry failed',
              retryable: true,
            });
          }
        }
      });
    });
  }

  private truncateTitle(title: string, maxLength = 120): string {
    if (title.length <= maxLength) return title;
    return title.slice(0, maxLength - 3) + '...';
  }
}
