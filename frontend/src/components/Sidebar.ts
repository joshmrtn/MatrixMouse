/**
 * Sidebar Component
 *
 * Responsive sidebar with collapse/expand toggle in header.
 * - Desktop: Starts expanded
 * - Mobile: Starts collapsed
 * - Toggle button is ALWAYS in header (not in sidebar)
 */

import { getState, setState, subscribe, buildTaskTree, toggleTaskExpansion } from '../state';
import { escapeHtml } from '../utils';
import type { TaskTreeNode } from '../state';

// Layout constants
const TASK_BASE_PADDING = 8;
const TASK_DEPTH_INCREMENT = 12;
const MOBILE_BREAKPOINT = 600;

export class Sidebar {
  private element: HTMLElement | null = null;
  private reposEl: HTMLElement | null = null;
  private taskTreesEl: HTMLElement | null = null;

  constructor() {
    subscribe((state) => {
      this.onStateChange(state);
    });

    // Listen for toggle events from header
    window.addEventListener('sidebar-toggle', (e) => {
      const event = e as CustomEvent<{ collapsed: boolean }>;
      this.setCollapsed(event.detail.collapsed);
    });
  }

  render(): HTMLElement {
    this.element = document.createElement('nav');
    this.element.id = 'sidebar';
    const state = getState();

    // On mobile, start collapsed; on desktop, start expanded
    const isMobile = window.innerWidth <= MOBILE_BREAKPOINT;
    if (isMobile) {
      this.element.classList.add('collapsed');
    }

    // NO collapse button in sidebar - it's only in the header
    this.element.innerHTML = `
      <div class="sidebar-header">
        <span class="sidebar-title">MatrixMouse</span>
      </div>
      <div id="sb-channels">
        <div class="sb-section-label">Channels</div>
        <div class="sb-item ${state.scope === 'workspace' ? 'active' : ''}" data-scope="workspace">
          <button class="sb-repo-expand">▶</button>
          <span class="sb-icon">◈</span>
          <span class="sb-name">Workspace</span>
          <span class="sb-spinner"></span>
        </div>
        <div id="sb-task-tree-workspace" class="sb-task-tree"></div>
        <div id="sb-repos"></div>
        <div id="sb-task-trees"></div>
      </div>
      <div id="sb-bottom">
        <div class="sb-item ${state.currentPage === 'dashboard' ? 'active' : ''}" data-tab="dashboard">
          <span class="sb-icon">𝌠</span>
          <span class="sb-name">Status</span>
        </div>
        <div class="sb-item ${state.currentPage === 'tasks' ? 'active' : ''}" data-tab="tasks">
          <span class="sb-icon">≡</span>
          <span class="sb-name">Tasks</span>
        </div>
        <div class="sb-item ${state.currentPage === 'settings' ? 'active' : ''}" data-tab="settings">
          <span class="sb-icon">⚙</span>
          <span class="sb-name">Settings</span>
        </div>
      </div>
    `;

    this.reposEl = this.element.querySelector('#sb-repos');
    this.taskTreesEl = this.element.querySelector('#sb-task-trees');

    // Setup event delegation for all click handling
    this.setupEventDelegation();

    // Render repos and task trees
    this.renderRepos();
    this.renderTaskTrees();

    return this.element;
  }

  /**
   * Set sidebar collapsed state
   */
  setCollapsed(collapsed: boolean): void {
    if (!this.element) return;

    if (collapsed) {
      this.element.classList.add('collapsed');
    } else {
      this.element.classList.remove('collapsed');
    }
  }

  /**
   * Check if sidebar is collapsed
   */
  isCollapsed(): boolean {
    return this.element?.classList.contains('collapsed') ?? false;
  }

  /**
   * Setup event delegation for all sidebar clicks.
   * Single listener on sidebar root handles all interactions.
   */
  private setupEventDelegation(): void {
    if (!this.element) return;

    this.element.addEventListener('click', (e) => {
      const target = e.target as HTMLElement;

      // === EXPAND BUTTONS (highest priority - prevent navigation) ===

      // Task expand button
      const taskExpand = target.closest('.sb-task-expand');
      if (taskExpand) {
        e.preventDefault();
        const taskItem = target.closest('.sb-task-item') as HTMLElement;
        const taskId = taskItem?.dataset.taskId;
        if (taskId) {
          toggleTaskExpansion(taskId);
          this.renderRepos();
        }
        return;
      }

      // Repo expand button (including workspace)
      const repoExpand = target.closest('.sb-repo-expand');
      if (repoExpand) {
        e.preventDefault();
        this.handleRepoExpand(repoExpand);
        return;
      }

      // === NAVIGATION (lower priority) ===

      // Task item navigation
      const taskItem = target.closest('.sb-task-item');
      if (taskItem) {
        const taskId = taskItem.dataset.taskId;
        if (taskId) {
          this.navigateToTask(taskId);
        }
        return;
      }

      // Repo item navigation
      const repoItem = target.closest('.sb-item[data-repo]');
      if (repoItem) {
        const repoName = (repoItem as HTMLElement).dataset.repo;
        if (repoName) {
          this.navigateToRepo(repoName);
        }
        return;
      }

      // Scope navigation (workspace)
      const scopeItem = target.closest('.sb-item[data-scope]');
      if (scopeItem) {
        const scope = (scopeItem as HTMLElement).dataset.scope;
        if (scope) {
          this.navigateToChannel(scope);
        }
        return;
      }

      // Tab navigation
      const tabItem = target.closest('.sb-item[data-tab]');
      if (tabItem) {
        const tab = (tabItem as HTMLElement).dataset.tab;
        if (tab) {
          this.navigateToTab(tab);
        }
        return;
      }
    });
  }

  /**
   * Handle repo/workspace expand button click
   */
  private handleRepoExpand(expandBtn: Element): void {
    // Check if it's the workspace expand button
    const scopeItem = expandBtn.closest('.sb-item[data-scope]');
    if (scopeItem) {
      const workspaceTree = this.element?.querySelector('#sb-task-tree-workspace');
      if (workspaceTree) {
        workspaceTree.classList.toggle('visible');
        (expandBtn as HTMLElement).textContent = workspaceTree.classList.contains('visible') ? '▼' : '▶';
      }
      return;
    }

    // Otherwise it's a repo expand button
    const repoItem = expandBtn.closest('.sb-item[data-repo]') as HTMLElement;
    const repoName = repoItem?.dataset.repo;
    if (repoName) {
      const treeEl = repoItem.nextElementSibling;
      if (treeEl && treeEl.classList.contains('sb-task-tree')) {
        treeEl.classList.toggle('visible');
        (expandBtn as HTMLElement).textContent = treeEl.classList.contains('visible') ? '▼' : '▶';
      }
    }
  }

  /**
   * Navigate to a task page
   */
  private navigateToTask(taskId: string): void {
    setState('sidebarOpen', false);
    window.history.pushState({}, '', `/task/${taskId}`);
    window.dispatchEvent(new Event('popstate'));
  }

  /**
   * Navigate to a repo channel
   */
  private navigateToRepo(repoName: string): void {
    setState('selectedTask', null);
    setState('scope', repoName);
    setState('sidebarOpen', false);
    window.history.pushState({}, '', `/channel/${repoName}`);
    window.dispatchEvent(new Event('popstate'));
  }

  /**
   * Navigate to a channel (workspace or repo)
   */
  private navigateToChannel(scope: string): void {
    setState('selectedTask', null);
    setState('scope', scope);
    setState('sidebarOpen', false);
    window.history.pushState({}, '', `/channel/${scope}`);
    window.dispatchEvent(new Event('popstate'));
  }

  /**
   * Navigate to a tab/page
   */
  private navigateToTab(tab: string): void {
    if (tab === 'tasks') {
      window.history.pushState({}, '', '/task-list');
    } else {
      window.history.pushState({}, '', `/${tab}`);
    }
    window.dispatchEvent(new Event('popstate'));
  }

  private onStateChange(state: ReturnType<typeof getState>): void {
    if (!this.element) return;

    // Update active scope items (workspace and repos)
    this.element.querySelectorAll('.sb-item[data-scope]').forEach((item) => {
      const scope = (item as HTMLElement).dataset.scope;
      let isActive = false;

      if (state.selectedTask) {
        // Highlight based on selected task's repo(s)
        if (scope === 'workspace') {
          // Workspace is active if task has no repo or multiple repos
          isActive = state.selectedTask.repo.length === 0 || state.selectedTask.repo.length > 1;
        } else if (scope) {
          // Repo is active if task belongs to this repo
          isActive = state.selectedTask.repo.includes(scope);
        }
      } else {
        // No selected task - use current scope
        isActive = scope === state.scope;
      }

      item.classList.toggle('active', isActive);
    });

    // Update active tab
    this.element.querySelectorAll('.sb-item[data-tab]').forEach((item) => {
      const tab = (item as HTMLElement).dataset.tab;
      item.classList.toggle('active', tab === state.currentPage);
    });

    // Expand repo when viewing a task in that repo
    if (state.selectedTask && state.selectedTask.repo.length > 0) {
      const taskRepo = state.selectedTask.repo[0];
      const taskTree = this.element.querySelector(`#sb-task-tree-${taskRepo}`);
      const expandBtn = this.element.querySelector(`[data-repo="${taskRepo}"] .sb-repo-expand`);

      if (taskTree && !taskTree.classList.contains('visible') && expandBtn) {
        taskTree.classList.add('visible');
        if (expandBtn instanceof HTMLElement) {
          expandBtn.textContent = '▼';
        }
      }
    }

    // Expand workspace when viewing a workspace-scoped task
    if (state.selectedTask && (state.selectedTask.repo.length === 0 || state.selectedTask.repo.length > 1)) {
      const workspaceTree = this.element.querySelector('#sb-task-tree-workspace');
      const workspaceExpandBtn = this.element.querySelector('[data-scope="workspace"] .sb-repo-expand');

      if (workspaceTree && !workspaceTree.classList.contains('visible') && workspaceExpandBtn) {
        workspaceTree.classList.add('visible');
        (workspaceExpandBtn as HTMLElement).textContent = '▼';
      }
    }

    // Collapse all repos when sidebar is collapsed
    const isCollapsed = this.element.classList.contains('collapsed');
    if (isCollapsed) {
      this.element.querySelectorAll('.sb-task-tree.visible').forEach((tree) => {
        tree.classList.remove('visible');
      });
      this.element.querySelectorAll('.sb-repo-expand').forEach((btn) => {
        btn.textContent = '▶';
      });
    }

    // Re-render repos when tasks change or selectedTask changes
    this.renderRepos();
    this.renderTaskTrees();
  }

  private renderRepos(): void {
    if (!this.reposEl || !this.element) return;

    const { repos, scope, selectedTask } = getState();

    // Determine which repo should be highlighted
    // If a task is selected, highlight its repo; otherwise use current scope
    let activeRepo: string | null = null;
    if (selectedTask && selectedTask.repo.length > 0) {
      activeRepo = selectedTask.repo[0] ?? null;
    }

    // Track which repos are currently expanded (including workspace)
    const expandedRepos = new Set<string>();
    this.reposEl.querySelectorAll('.sb-task-tree.visible').forEach((tree) => {
      const match = tree.id.match(/^sb-task-tree-(.+)$/);
      if (match && match[1]) {
        expandedRepos.add(match[1]);
      }
    });

    // Also check workspace expansion
    const workspaceTree = this.element.querySelector('#sb-task-tree-workspace');
    if (workspaceTree && workspaceTree.classList.contains('visible')) {
      expandedRepos.add('workspace');
    }

    // Render repos
    const reposHtml = repos
      .map(
        (repo) => {
          // Highlight if this repo matches the active repo (from selectedTask) or current scope
          const isActive = activeRepo ? repo.name === activeRepo : scope === repo.name;
          return `
        <div class="sb-item ${isActive ? 'active' : ''}" data-repo="${escapeHtml(repo.name)}">
          <button class="sb-repo-expand">${expandedRepos.has(repo.name) ? '▼' : '▶'}</button>
          <span class="sb-icon">⬡</span>
          <span class="sb-name">${escapeHtml(repo.name)}</span>
          <span class="sb-spinner"></span>
        </div>
        <div id="sb-task-tree-${escapeHtml(repo.name)}" class="sb-task-tree${expandedRepos.has(repo.name) ? ' visible' : ''}">
          ${this.renderTaskTreeNodesForRepo(repo.name)}
        </div>
      `;
        }
      )
      .join('');

    this.reposEl.innerHTML = reposHtml;

    // Update workspace task tree
    if (workspaceTree) {
      const workspaceContent = this.renderTaskTreeNodesForRepo('workspace');
      workspaceTree.innerHTML = workspaceContent;
      if (expandedRepos.has('workspace')) {
        workspaceTree.classList.add('visible');
      }
      // Hide expand button if no workspace tasks
      const workspaceExpandBtn = this.element.querySelector('[data-scope="workspace"] .sb-repo-expand');
      if (workspaceExpandBtn) {
        const hasTasks = workspaceContent.trim().length > 0;
        (workspaceExpandBtn as HTMLElement).style.display = hasTasks ? 'block' : 'none';
      }
    }

    // Auto-expand workspace if workspace task is selected (initial render)
    if (selectedTask && (selectedTask.repo.length === 0 || selectedTask.repo.length > 1)) {
      const workspaceTreeEl = this.element.querySelector('#sb-task-tree-workspace');
      const workspaceExpandBtnEl = this.element.querySelector('[data-scope="workspace"] .sb-repo-expand');
      if (workspaceTreeEl && !workspaceTreeEl.classList.contains('visible') && workspaceExpandBtnEl) {
        workspaceTreeEl.classList.add('visible');
        (workspaceExpandBtnEl as HTMLElement).textContent = '▼';
      }
    }
  }

  private renderTaskTreeNodesForRepo(repoName: string): string {
    const { rootTasks } = buildTaskTree();
    const tasks = rootTasks.filter((task) => {
      if (repoName === 'workspace') {
        // Workspace shows tasks with no repo OR multiple repos
        return task.repo.length === 0 || task.repo.length > 1;
      } else {
        // Repo shows tasks that include this repo
        return task.repo.includes(repoName);
      }
    });
    return this.renderTaskTreeNodes(tasks);
  }

  private renderTaskTrees(): void {
    // Task trees are now rendered inline with repos in renderRepos()
    if (!this.taskTreesEl) return;
    this.taskTreesEl.innerHTML = '';
  }

  private renderTaskTreeNodes(tasks: TaskTreeNode[], depth = 0): string {
    if (tasks.length === 0) return '';

    const { selectedTask } = getState();

    return tasks
      .map(
        (task) => `
        <div class="sb-task-item${selectedTask?.id === task.id ? ' active' : ''}" data-task-id="${escapeHtml(task.id)}" style="padding-left: ${TASK_BASE_PADDING + depth * TASK_DEPTH_INCREMENT}px">
          <button class="sb-task-expand">${task.children.length > 0 ? '▶' : '•'}</button>
          <span class="sb-task-status status-${escapeHtml(task.status)}"></span>
          <span class="sb-task-title">${escapeHtml(task.title)}</span>
        </div>
        ${this.renderTaskTreeNodes(task.children, depth + 1)}
      `
      )
      .join('');
  }
}
