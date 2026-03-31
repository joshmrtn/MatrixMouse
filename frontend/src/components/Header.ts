/**
 * Header Component
 * 
 * Contains the sidebar toggle button that controls sidebar collapse/expand.
 * Toggle button is ALWAYS visible in the top-left corner.
 * - Arrow points LEFT (←) when sidebar is EXPANDED (click to collapse)
 * - Arrow points RIGHT (→) when sidebar is COLLAPSED (click to expand)
 */

import { getState, subscribe } from '../state';
import { formatStatus } from '../utils';
import { softStop, estop } from '../api';

export class Header {
  private element: HTMLElement | null = null;
  private statusEl: HTMLElement | null = null;
  private sidebarCollapsed = false;

  constructor() {
    subscribe((state) => this.onStateChange(state));
  }

  render(): HTMLElement {
    this.element = document.createElement('header');
    this.element.id = 'header';
    
    // Determine initial button direction based on viewport
    // Mobile starts collapsed (show expand →), desktop starts expanded (show collapse ←)
    const isMobile = window.innerWidth <= 600;
    this.sidebarCollapsed = isMobile;
    const arrow = this.sidebarCollapsed ? '»' : '«';
    
    this.element.innerHTML = `
      <button id="sidebar-toggle" aria-label="Toggle sidebar" title="${this.sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}">
        <span>${arrow}</span>
      </button>
      <div class="h-logo">
        <span class="h-logo-full">🐭 MatrixMouse</span>
        <span class="h-logo-mini">🐭</span>
      </div>
      <div class="h-fields">
        <div class="h-field">
          <span class="lbl">Status</span>
          <span class="val" id="header-status">idle</span>
        </div>
      </div>
      <div id="h-controls">
        <button id="btn-stop" title="Soft stop">
          <span>■</span> Stop
        </button>
        <button id="btn-kill" title="E-STOP">
          ⚠ E-STOP
        </button>
        <div id="conn-dot"></div>
        <span id="conn-label">connecting</span>
      </div>
    `;

    this.statusEl = this.element.querySelector('#header-status');

    // Set up sidebar toggle
    const toggleBtn = this.element.querySelector('#sidebar-toggle');
    toggleBtn?.addEventListener('click', () => {
      this.toggleSidebar();
    });

    // Set up event listeners
    this.element.querySelector('#btn-stop')?.addEventListener('click', () => this.handleSoftStop());
    this.element.querySelector('#btn-kill')?.addEventListener('click', () => this.handleEstop());

    // Update initial status
    this.updateStatus(getState().status);

    return this.element;
  }

  /**
   * Toggle sidebar collapsed/expanded state
   */
  toggleSidebar(): void {
    this.sidebarCollapsed = !this.sidebarCollapsed;
    this.updateToggleButton();
    
    // Dispatch event for sidebar to listen to
    window.dispatchEvent(new CustomEvent('sidebar-toggle', {
      detail: { collapsed: this.sidebarCollapsed }
    }));
  }

  /**
   * Update toggle button arrow direction
   */
  updateToggleButton(): void {
    const toggleBtn = this.element?.querySelector('#sidebar-toggle');
    const span = toggleBtn?.querySelector('span');
    if (span) {
      // ← when expanded (collapse), → when collapsed (expand)
      span.textContent = this.sidebarCollapsed ? '»' : '«';
      toggleBtn?.setAttribute('title', this.sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar');
    }
  }

  /**
   * Get current sidebar collapsed state
   */
  isSidebarCollapsed(): boolean {
    return this.sidebarCollapsed;
  }

  private onStateChange(state: ReturnType<typeof getState>): void {
    this.updateStatus(state.status);
    this.updateConnection(state.wsConnected);
  }

  private updateStatus(status: ReturnType<typeof getState>['status']): void {
    if (!this.statusEl) return;

    if (status?.stopped) {
      this.statusEl.textContent = 'STOPPED';
      this.statusEl.className = 'val stopped';
    } else if (status?.blocked) {
      this.statusEl.textContent = 'BLOCKED';
      this.statusEl.className = 'val blocked';
    } else if (status?.idle) {
      this.statusEl.textContent = 'idle';
      this.statusEl.className = 'val';
    } else {
      this.statusEl.textContent = 'running';
      this.statusEl.className = 'val active';
    }
  }

  private updateConnection(connected: boolean): void {
    const dot = this.element?.querySelector('#conn-dot');
    const label = this.element?.querySelector('#conn-label');

    if (dot && label) {
      if (connected) {
        dot.classList.add('live');
        label.classList.add('live');
        label.textContent = 'live';
      } else {
        dot.classList.remove('live');
        label.classList.remove('live');
        label.textContent = 'connecting';
      }
    }
  }

  private async handleSoftStop(): Promise<void> {
    try {
      await softStop();
      console.log('[Header] Soft stop requested');
    } catch (error) {
      console.error('[Header] Failed to request stop:', error);
    }
  }

  private async handleEstop(): Promise<void> {
    if (confirm('⚠ Emergency Stop\n\nThis will immediately shut down MatrixMouse and prevent automatic restart. Continue?')) {
      try {
        await estop();
        alert('E-STOP engaged. Service is shutting down.');
      } catch (error) {
        console.error('[Header] E-STOP error:', error);
      }
    }
  }
}
