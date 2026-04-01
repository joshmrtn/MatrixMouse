/**
 * Tasks List Page Component
 * Shows all tasks with filtering by status and repo
 */

import { getState, subscribe } from '../state';
import { escapeHtml, formatStatus } from '../utils';
import type { Task } from '../types';

export class TasksPage {
  private element: HTMLElement | null = null;
  private currentStatusFilter = 'all';
  private currentRepoFilter = 'all';

  constructor() {
    // Subscribe to state changes for real-time updates
    subscribe((state) => {
      // Re-render when tasks or repos change
      if (this.element) {
        // Re-populate repo filter when repos change
        if (state.repos.length > 0) {
          this.populateRepoFilter();
        }
        this.renderTaskList();
      }
    });
  }

  render(container: HTMLElement): void {
    container.innerHTML = `
      <div id="tasks-page">
        <h1>Tasks</h1>
        
        <div id="tasks-filters">
          <div class="filter-row">
            <label for="filter-status">Status:</label>
            <select id="filter-status">
              <option value="all">All</option>
              <option value="pending">Pending</option>
              <option value="ready">Ready</option>
              <option value="running">Running</option>
              <option value="blocked_by_human">Blocked by Human</option>
              <option value="blocked_by_task">Blocked by Dependencies</option>
              <option value="waiting">Waiting</option>
              <option value="complete">Complete</option>
              <option value="cancelled">Cancelled</option>
            </select>

            <label for="filter-repo">Repo:</label>
            <select id="filter-repo">
              <option value="all">All</option>
            </select>

            <button id="add-task-btn" class="btn-primary">+ New</button>
          </div>
        </div>

        <div id="tasks-list"></div>
      </div>
    `;

    this.element = container.querySelector('#tasks-page');

    // Set up filter event listeners
    const statusFilter = container.querySelector('#filter-status') as HTMLSelectElement;
    const repoFilter = container.querySelector('#filter-repo') as HTMLSelectElement;
    const addBtn = container.querySelector('#add-task-btn');

    statusFilter?.addEventListener('change', (e) => {
      this.currentStatusFilter = (e.target as HTMLSelectElement).value;
      this.renderTaskList();
    });

    repoFilter?.addEventListener('change', (e) => {
      this.currentRepoFilter = (e.target as HTMLSelectElement).value;
      this.renderTaskList();
    });

    addBtn?.addEventListener('click', () => {
      window.history.pushState({}, '', '/tasks/new');
      window.dispatchEvent(new Event('popstate'));
    });

    // Populate repo filter
    this.populateRepoFilter();

    // Render task list
    this.renderTaskList();
  }

  private populateRepoFilter(): void {
    if (!this.element) return;

    const repoFilter = this.element.querySelector('#filter-repo') as HTMLSelectElement;
    if (!repoFilter) return;

    // Clear existing options except "All"
    while (repoFilter.options.length > 1) {
      repoFilter.remove(1);
    }

    const { repos } = getState();
    repos.forEach((repo) => {
      const option = document.createElement('option');
      option.value = repo.name;
      option.textContent = repo.name;
      repoFilter.appendChild(option);
    });
  }

  private renderTaskList(): void {
    if (!this.element) return;

    const { tasks } = getState();
    const taskListEl = this.element.querySelector('#tasks-list');
    if (!taskListEl) return;

    // Filter tasks
    let filteredTasks = tasks;

    if (this.currentStatusFilter !== 'all') {
      filteredTasks = filteredTasks.filter(
        (task) => task.status === this.currentStatusFilter
      );
    }

    if (this.currentRepoFilter !== 'all') {
      filteredTasks = filteredTasks.filter(
        (task) => task.repo.includes(this.currentRepoFilter)
      );
    }

    if (filteredTasks.length === 0) {
      taskListEl.innerHTML = '<div class="empty-message">No tasks found.</div>';
      return;
    }

    // Sort by priority score (lower = higher priority)
    filteredTasks.sort((a, b) => a.priority_score - b.priority_score);

    taskListEl.innerHTML = filteredTasks
      .map((task) => this.renderTaskItem(task))
      .join('');
  }

  private renderTaskItem(task: Task): string {
    const statusClass = task.status.replace(/_/g, '-');
    const repoName = this.renderTaskRepo(task);
    return `
      <div class="task-item">
        <a href="/task/${escapeHtml(task.id)}" class="task-link">
          <div class="task-main">
            <div class="task-title">${escapeHtml(task.title)}</div>
            <div class="task-repo">${escapeHtml(repoName)}</div>
          </div>
          <div class="task-meta">
            <div class="task-status status-${escapeHtml(statusClass)}">${escapeHtml(formatStatus(task.status))}</div>
            <div class="task-id">${escapeHtml(task.id)}</div>
          </div>
        </a>
      </div>
    `;
  }

  private renderTaskRepo(task: Task): string {
    if (task.repo.length === 0) {
      return 'Workspace';
    }
    return task.repo.map(escapeHtml).join(', ');
  }
}
