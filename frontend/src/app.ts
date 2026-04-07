/**
 * Main Application Component
 */

import { wsManager } from './api';
import { getState, setState, setStates, subscribe } from './state';
import { renderRouter } from './pages';
import { Header } from './components/Header';
import { Sidebar } from './components/Sidebar';
import { getRepos, getTasks, getBlocked } from './api/client';

/**
 * Application class
 */
export class App {
  private container: HTMLElement | null = null;
  private header: Header | null = null;
  private sidebar: Sidebar | null = null;
  private mainEl: HTMLElement | null = null;

  /**
   * Initialize application
   */
  init(): void {
    console.log('[App] Initializing...');

    // Get container
    this.container = document.getElementById('app');
    if (!this.container) {
      console.error('[App] Container not found!');
      return;
    }

    // Render header (includes hamburger for mobile)
    this.header = new Header();
    this.container.appendChild(this.header.render());

    // Render sidebar
    this.sidebar = new Sidebar();
    this.container.appendChild(this.sidebar.render());

    // Create backdrop for mobile sidebar
    const backdrop = document.createElement('div');
    backdrop.id = 'sidebar-backdrop';
    this.container.appendChild(backdrop);

    // Create main panel
    this.mainEl = document.createElement('main');
    this.mainEl.id = 'main';
    this.container.appendChild(this.mainEl);

    // Connect WebSocket
    wsManager.connect();

    // Set up WebSocket event handlers
    this.setupWebSocketHandlers();

    // Set up state subscription for UI updates
    subscribe((state) => {
      this.onStateChange(state);
    });

    // Set up routing
    this.setupRouting();

    // Load initial data
    this.loadInitialData();

    console.log('[App] Initialized');
  }

  /**
   * Set up WebSocket event handlers
   */
  private setupWebSocketHandlers(): void {
    // Status updates
    wsManager.onStatusUpdate((data) => {
      setState('status', data);
      if (data.idle) {
        setState('wsConnected', true);
      }
    });

    // Clarification requests
    wsManager.onClarificationRequest((data) => {
      setState('pendingQuestion', data.question);
    });

    // Connection state
    wsManager.on('status_update', () => {
      setState('wsConnected', true);
    });

    // Decision modal events - dispatch as CustomEvents for components to listen
    wsManager.on('decomposition_confirmation_required', (data) => {
      window.dispatchEvent(new CustomEvent('decomposition_confirmation_required', { detail: data }));
    });

    wsManager.on('pr_approval_required', (data) => {
      window.dispatchEvent(new CustomEvent('pr_approval_required', { detail: data }));
    });

    wsManager.on('turn_limit_reached', (data) => {
      window.dispatchEvent(new CustomEvent('turn_limit_reached', { detail: data }));
    });

    wsManager.on('planning_turn_limit_reached', (data) => {
      window.dispatchEvent(new CustomEvent('planning_turn_limit_reached', { detail: data }));
    });

    wsManager.on('merge_conflict_resolution_turn_limit_reached', (data) => {
      window.dispatchEvent(new CustomEvent('merge_conflict_resolution_turn_limit_reached', { detail: data }));
    });

    wsManager.on('critic_turn_limit_reached', (data) => {
      window.dispatchEvent(new CustomEvent('critic_turn_limit_reached', { detail: data }));
    });
  }

  /**
   * Set up routing
   */
  private setupRouting(): void {
    // Handle initial route
    this.handleRoute();

    // Handle route changes
    window.addEventListener('popstate', () => {
      this.handleRoute();
    });
  }

  /**
   * Handle current route
   */
  private handleRoute(): void {
    const path = window.location.pathname;
    const parts = path.split('/').filter(Boolean);

    let page = 'channel';
    const params: Record<string, string> = {};

    if (parts[0] === 'task' && parts[1]) {
      page = 'task';
      params.id = parts[1];
    } else if (parts[0] === 'task-new') {  // NEW route for task creation
      page = 'task-new';
    } else if (parts[0] === 'task-list') {
      page = 'tasks';
    } else if (parts[0] === 'dashboard' || parts[0] === 'status') {
      // Support both /dashboard and /status (for backwards compatibility)
      if (parts[0] === 'status') {
        // Redirect to /dashboard
        window.history.replaceState({}, '', '/dashboard');
      }
      page = 'dashboard';
    } else if (parts[0] === 'settings') {
      page = 'settings';
    } else if (parts[0] === 'channel' && parts[1]) {
      page = 'channel';
      params.scope = parts[1];
    }

    setStates({
      currentPage: page,
      routeParams: params,
    });

    // Render the appropriate page
    if (this.mainEl) {
      renderRouter(page, params, this.mainEl);
    }
  }

  /**
   * Handle state changes
   */
  private onStateChange(state: ReturnType<typeof getState>): void {
    // Update document title
    if (state.selectedTask) {
      document.title = `${state.selectedTask.title} - MatrixMouse`;
    } else {
      document.title = 'MatrixMouse';
    }
  }

  /**
   * Load initial data
   */
  private async loadInitialData(): Promise<void> {
    try {
      // Load repos
      const reposData = await getRepos();
      setState('repos', reposData.repos || []);

      // Load tasks
      const tasksData = await getTasks({ all: true });
      setState('tasks', tasksData.tasks || []);

      // Load status
      const status = await fetch('/status').then((r) => r.json());
      setState('status', status);

      // Load blocked tasks for status dashboard
      try {
        const blockedData = await getBlocked();
        setState('blockedReport', blockedData.report);
      } catch {
        // Ignore if blocked endpoint fails
      }

      console.log('[App] Initial data loaded');
    } catch (error) {
      console.error('[App] Failed to load initial data:', error);
    }
  }

  /**
   * Navigate to a route
   */
  navigate(path: string): void {
    window.history.pushState({}, '', path);
    this.handleRoute();
  }
}
