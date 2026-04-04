/**
 * Tasks List Page Component
 * Shows all tasks with filtering by status and repo
 */

import { getState, subscribe } from '../state';
import { escapeHtml, formatStatus } from '../utils';
import { getTasks } from '../api/client';
import type { Task } from '../types';

const STORAGE_KEY = 'matrixmouse.tasks.filters';

export class TasksPage {
  private element: HTMLElement | null = null;
  private currentStatusFilter = 'all';
  private currentRepoFilter = 'all';
  private searchQuery = '';
  private searchDisplayValue = '';
  private searchDebounceTimer: ReturnType<typeof setTimeout> | null = null;
  private tasksLoaded = false;
  private isLoading = false;
  private hasError = false;
  private isDestroyed = false;

  constructor() {
    // Subscribe to state changes for real-time updates
    subscribe((state) => {
      // Re-render when tasks or repos change
      if (this.element) {
        // Re-populate repo filter when repos change
        if (state.repos.length > 0) {
          this.populateRepoFilter();
        }
        // Re-render task list when tasks change (but not during loading)
        if (!this.isLoading) {
          this.renderTaskList();
        }
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

            <div class="search-container">
              <input type="text" id="task-search" placeholder="Search tasks..." aria-label="Search tasks" />
              <button id="task-search-clear" class="hidden" aria-label="Clear search">\u00d7</button>
            </div>

            <button id="add-task-btn" class="btn-primary">+ New</button>
          </div>
        </div>

        <div id="tasks-list"></div>
      </div>
    `;

    this.element = container;

    // Set up filter event listeners
    const statusFilter = container.querySelector('#filter-status') as HTMLSelectElement;
    const repoFilter = container.querySelector('#filter-repo') as HTMLSelectElement;
    const addBtn = container.querySelector('#add-task-btn');

    statusFilter?.addEventListener('change', (e) => {
      this.currentStatusFilter = (e.target as HTMLSelectElement).value;
      this.saveFilters();
      this.renderTaskList();
    });

    repoFilter?.addEventListener('change', (e) => {
      this.currentRepoFilter = (e.target as HTMLSelectElement).value;
      this.saveFilters();
      this.renderTaskList();
    });

    addBtn?.addEventListener('click', () => {
      window.history.pushState({}, '', '/task-new');  // Updated to /task-new to avoid API collision
      window.dispatchEvent(new Event('popstate'));
    });

    // Set up search input
    const searchInput = container.querySelector('#task-search') as HTMLInputElement;
    const clearBtn = container.querySelector('#task-search-clear');

    searchInput?.addEventListener('input', (e) => {
      const value = (e.target as HTMLInputElement).value;
      this.handleSearchInput(value);

      // Show/hide clear button
      if (clearBtn) {
        if (value.trim()) {
          clearBtn.classList.remove('hidden');
        } else {
          clearBtn.classList.add('hidden');
        }
      }
    });

    clearBtn?.addEventListener('click', () => {
      searchInput.value = '';
      this.searchQuery = '';
      this.searchDisplayValue = '';
      clearBtn.classList.add('hidden');
      this.saveFilters();
      this.renderTaskList();
    });

    // Populate repo filter
    this.populateRepoFilter();

    // Restore filters from localStorage
    this.restoreFilters();

    // Check if tasks are already in state (e.g., loaded by app.ts)
    const { tasks } = getState();
    if (tasks.length > 0) {
      this.tasksLoaded = true;
      // Re-render with restored filters
      this.renderTaskList();
    }

    // Load tasks if not already loaded
    this.loadTasks();
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

    // If there's an error, show error message (check this FIRST)
    if (this.hasError) {
      this.renderError(taskListEl);
      return;
    }

    // If tasks haven't been loaded yet, show skeletons
    if (!this.tasksLoaded) {
      this.renderLoadingSkeletons(taskListEl);
      return;
    }

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

    // Apply search filter
    if (this.searchQuery) {
      filteredTasks = filteredTasks.filter((task) => {
        const query = this.searchQuery;
        return (
          task.title.toLowerCase().includes(query) ||
          task.id.toLowerCase().includes(query) ||
          task.description?.toLowerCase().includes(query) ||
          task.notes?.toLowerCase().includes(query)
        );
      });
    }

    if (filteredTasks.length === 0) {
      taskListEl.innerHTML = '<div class="empty-message">No tasks found.</div>';
      return;
    }

    // Sort by priority score (lower = higher priority)
    filteredTasks.sort((a, b) => a.priority_score - b.priority_score);

    // Build task count display
    const totalCount = tasks.length;
    const filteredCount = filteredTasks.length;
    const countText = filteredCount === totalCount
      ? `${filteredCount} task${filteredCount !== 1 ? 's' : ''}`
      : `Showing ${filteredCount} of ${totalCount} task${totalCount !== 1 ? 's' : ''}`;

    taskListEl.innerHTML = `
      <div class="task-count">${escapeHtml(countText)}</div>
      ${filteredTasks.map((task) => this.renderTaskItem(task)).join('')}
    `;
  }

  private renderTaskItem(task: Task): string {
    const statusClass = task.status.replace(/_/g, '-');
    const repoName = this.renderTaskRepo(task);

    // Role badge
    const roleLabel = task.role.charAt(0).toUpperCase() + task.role.slice(1);
    const roleBadge = `<span class="task-role">${escapeHtml(roleLabel)}</span>`;

    // Priority indicator - only show for high priority tasks (score > 0.7)
    const priorityIndicator = task.priority_score > 0.7
      ? `<span class="task-priority" title="Priority: ${task.priority_score}">\u25c6 ${task.priority_score.toFixed(2)}</span>`
      : '';

    // Terminal state class for complete/cancelled tasks
    const terminalStatuses = new Set(['complete', 'cancelled']);
    const terminalClass = terminalStatuses.has(task.status) ? ' terminal' : '';

    return `
      <div class="task-item${terminalClass}">
        <a href="/task/${escapeHtml(task.id)}" class="task-link">
          <div class="task-main">
            <div class="task-title">${escapeHtml(task.title)}</div>
            <div class="task-repo">${escapeHtml(repoName)}</div>
          </div>
          <div class="task-meta">
            <div class="task-status status-${escapeHtml(statusClass)}">${escapeHtml(formatStatus(task.status))}</div>
            ${roleBadge}
            ${priorityIndicator}
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

  /**
   * Save filter preferences to localStorage
   */
  private saveFilters(): void {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({
        status: this.currentStatusFilter,
        repo: this.currentRepoFilter,
        search: this.searchDisplayValue,
      }));
    } catch {
      // Ignore if localStorage unavailable
    }
  }

  /**
   * Restore filter preferences from localStorage
   */
  private restoreFilters(): void {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (saved) {
        const filters = JSON.parse(saved);
        if (filters.status) this.currentStatusFilter = filters.status;
        if (filters.repo) this.currentRepoFilter = filters.repo;
        if (filters.search) {
          this.searchDisplayValue = filters.search;
          this.searchQuery = filters.search.toLowerCase().trim();
        }

        // Apply restored filters to UI
        const statusFilter = this.element?.querySelector('#filter-status') as HTMLSelectElement | null;
        const repoFilter = this.element?.querySelector('#filter-repo') as HTMLSelectElement | null;
        const searchInput = this.element?.querySelector('#task-search') as HTMLInputElement | null;
        const clearBtn = this.element?.querySelector('#task-search-clear');

        if (statusFilter && this.currentStatusFilter !== 'all') {
          statusFilter.value = this.currentStatusFilter;
        }
        if (repoFilter && this.currentRepoFilter !== 'all') {
          repoFilter.value = this.currentRepoFilter;
        }
        if (searchInput && this.searchDisplayValue) {
          searchInput.value = this.searchDisplayValue;
          clearBtn?.classList.remove('hidden');
        }
      }
    } catch {
      // Ignore corrupted data
    }
  }

  /**
   * Handle search input with debouncing
   */
  private handleSearchInput(value: string): void {
    if (this.searchDebounceTimer) clearTimeout(this.searchDebounceTimer);

    this.searchDebounceTimer = setTimeout(() => {
      this.searchDisplayValue = value;
      this.searchQuery = value.toLowerCase().trim();
      this.saveFilters();
      this.renderTaskList();
    }, 150);
  }

  /**
   * Load tasks from API
   */
  private async loadTasks(): Promise<void> {
    if (this.isLoading || this.isDestroyed) return;

    // Check if tasks are already in state (e.g., loaded by app.ts or set in tests)
    const { tasks } = getState();
    if (tasks.length > 0) {
      this.tasksLoaded = true;
      this.isLoading = false;
      this.hasError = false;
      this.renderTaskList();
      return;
    }

    // Mark that we're loading and render skeletons
    this.isLoading = true;
    this.hasError = false;
    this.renderTaskList();

    try {
      const tasksData = await getTasks({ all: true });
      
      if (this.isDestroyed) return;
      
      this.tasksLoaded = true;
      this.isLoading = false;
      this.hasError = false;
      
      // Update state with fetched tasks
      // Use dynamic import to avoid circular dependency
      const stateModule = await import('../state');
      stateModule.setState('tasks', tasksData.tasks || []);
      
      this.renderTaskList();
    } catch (error) {
      if (this.isDestroyed) return;
      
      this.isLoading = false;
      this.hasError = true;
      this.renderTaskList(); // Show error
    }
  }

  /**
   * Render loading skeletons
   */
  private renderLoadingSkeletons(taskListEl: Element): void {
    const skeletons = Array.from({ length: 5 }, (_, i) => `
      <div class="task-skeleton">
        <div class="task-skeleton-content">
          <div class="skeleton skeleton-rect" style="width: 150px; height: 14px;"></div>
          <div class="skeleton skeleton-rect" style="width: 80px; height: 10px; margin-top: 4px;"></div>
        </div>
        <div class="task-skeleton-meta">
          <div class="skeleton skeleton-rect" style="width: 60px; height: 12px;"></div>
          <div class="skeleton skeleton-rect" style="width: 50px; height: 10px; margin-top: 4px;"></div>
        </div>
      </div>
    `).join('');

    taskListEl.innerHTML = skeletons;
  }

  /**
   * Render error message with retry button
   */
  private renderError(taskListEl: Element): void {
    taskListEl.innerHTML = `
      <div class="error-message">
        <p>Failed to load tasks. Please try again.</p>
        <button class="retry-btn" aria-label="Retry loading tasks">Retry</button>
      </div>
    `;

    const retryBtn = taskListEl.querySelector('.retry-btn');
    retryBtn?.addEventListener('click', () => {
      this.retryLoadTasks();
    });
  }

  /**
   * Retry loading tasks
   */
  private async retryLoadTasks(): Promise<void> {
    if (this.isDestroyed) return;

    this.hasError = false;
    this.tasksLoaded = false;
    await this.loadTasks();
  }

  /**
   * Clean up resources
   */
  destroy(): void {
    this.isDestroyed = true;
    this.element = null;
  }
}
