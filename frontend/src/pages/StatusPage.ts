/**
 * Status Dashboard Page Component
 * Shows blocked and waiting tasks in three sections:
 * - Blocked by Human: Tasks awaiting human input/decision
 * - Blocked by Dependencies: Tasks waiting on other tasks
 * - Waiting: Tasks waiting due to rate limits, budgets, etc.
 */

import { getState, subscribe } from '../state';
import { escapeHtml } from '../utils';
import type { BlockedTaskEntry } from '../types';

export class StatusPage {
  private element: HTMLElement | null = null;

  constructor() {
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

  private renderSection(
    sectionSelector: string,
    tasks: BlockedTaskEntry[],
    emptyMessage: string,
    showDependencyLinks = false
  ): void {
    if (!this.element) return;

    const section = this.element.querySelector(sectionSelector);
    if (!section) return;

    const contentEl = section.querySelector('.status-section-content');
    if (!contentEl) return;

    if (tasks.length === 0) {
      contentEl.innerHTML = `<div class="empty-message">${emptyMessage}</div>`;
      return;
    }

    contentEl.innerHTML = tasks
      .map((task) => this.renderTaskItem(task, showDependencyLinks))
      .join('');

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
    task: BlockedTaskEntry,
    showDependencyLinks = false
  ): string {
    const taskHtml = `
      <div class="status-task-item">
        <a href="/task/${escapeHtml(task.id)}" class="status-task-link" data-task-id="${escapeHtml(task.id)}">
          <span class="status-task-id">${escapeHtml(task.id)}</span>
          <span class="status-task-title">${escapeHtml(task.title)}</span>
        </a>
        <div class="status-task-reason">${escapeHtml(task.blocking_reason)}</div>
        ${this.renderDependencyLinks(task, showDependencyLinks)}
      </div>
    `;
    return taskHtml;
  }

  private renderDependencyLinks(
    task: BlockedTaskEntry,
    showDependencyLinks: boolean
  ): string {
    if (!showDependencyLinks) return '';

    // Parse "Waiting on: task_id" format (task IDs are alphanumeric)
    const match = task.blocking_reason.match(/Waiting on:\s*([a-zA-Z0-9]+)/i);
    if (match) {
      const depId = match[1].trim();
      return `<div class="dependency-info">Waiting on: <a href="/task/${escapeHtml(depId)}" class="dependency-link" data-task-id="${escapeHtml(depId)}" title="View task ${escapeHtml(depId)}">${escapeHtml(depId)}</a></div>`;
    }
    return '';
  }
}
