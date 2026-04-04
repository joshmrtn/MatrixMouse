/**
 * Header Component Unit Tests
 * 
 * Tests for the Header component including:
 * - Status display
 * - Connection indicator
 * - Sidebar toggle
 * - Soft stop and E-STOP buttons
 * - Mobile/desktop responsive behavior
 */

import { Header } from '../../../src/components/Header';
import * as state from '../../../src/state';
import * as api from '../../../src/api';
import { vi, describe, it, expect, beforeEach, afterEach } from 'vitest';

// Mock dependencies
vi.mock('../../../src/state', () => ({
  getState: vi.fn(),
  setState: vi.fn(),
  subscribe: vi.fn(),
}));

vi.mock('../../../src/api', () => ({
  softStop: vi.fn(),
  estop: vi.fn(),
}));

// Mock window methods
const mockConfirm = vi.fn();
Object.defineProperty(window, 'confirm', { value: mockConfirm, writable: true });

const mockAlert = vi.fn();
Object.defineProperty(window, 'alert', { value: mockAlert, writable: true });

const mockDispatchEvent = vi.fn();
Object.defineProperty(window, 'dispatchEvent', { value: mockDispatchEvent, writable: true });

// Mock window innerWidth
let mockInnerWidth = 1024;
Object.defineProperty(window, 'innerWidth', {
  get: () => mockInnerWidth,
  set: (val) => { mockInnerWidth = val; },
});

describe('Header', () => {
  let container: HTMLElement;
  let subscribeCallback: ((state: any) => void) | null = null;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    vi.clearAllMocks();
    mockInnerWidth = 1024; // Desktop width

    // Capture subscribe callback
    vi.mocked(state.subscribe).mockImplementation((cb) => {
      subscribeCallback = cb as any;
      return () => {};
    });

    vi.mocked(state.getState).mockReturnValue({
      status: { idle: true, stopped: false, blocked: false },
      wsConnected: false,
      currentPage: 'dashboard',
    } as any);
  });

  afterEach(() => {
    document.body.removeChild(container);
  });

  describe('constructor()', () => {
    it('registers state subscription', () => {
      new Header();
      expect(state.subscribe).toHaveBeenCalled();
    });
  });

  describe('render()', () => {
    it('creates header element', () => {
      const header = new Header();
      const element = header.render();

      expect(element.tagName.toLowerCase()).toBe('header');
      expect(element.id).toBe('header');
    });

    it('displays sidebar toggle button', () => {
      const header = new Header();
      container.appendChild(header.render());

      const toggleBtn = container.querySelector('#sidebar-toggle');
      expect(toggleBtn).toBeDefined();
      expect(toggleBtn?.getAttribute('aria-label')).toBe('Toggle sidebar');
    });

    it('displays logo', () => {
      const header = new Header();
      container.appendChild(header.render());

      const logo = container.querySelector('.h-logo');
      expect(logo).toBeDefined();

      const logoFull = container.querySelector('.h-logo-full');
      expect(logoFull?.textContent).toContain('MatrixMouse');
    });

    it('displays status field', () => {
      const header = new Header();
      container.appendChild(header.render());

      const statusField = container.querySelector('#header-status');
      expect(statusField).toBeDefined();
    });

    it('displays soft stop button', () => {
      const header = new Header();
      container.appendChild(header.render());

      const stopBtn = container.querySelector('#btn-stop');
      expect(stopBtn).toBeDefined();
      expect(stopBtn?.textContent).toContain('Stop');
    });

    it('displays E-STOP button', () => {
      const header = new Header();
      container.appendChild(header.render());

      const killBtn = container.querySelector('#btn-kill');
      expect(killBtn).toBeDefined();
      expect(killBtn?.textContent).toContain('E-STOP');
    });

    it('displays connection indicator', () => {
      const header = new Header();
      container.appendChild(header.render());

      const connDot = container.querySelector('#conn-dot');
      const connLabel = container.querySelector('#conn-label');

      expect(connDot).toBeDefined();
      expect(connLabel).toBeDefined();
    });

    it('shows arrow pointing left on desktop (expanded)', () => {
      mockInnerWidth = 1024;
      const header = new Header();
      container.appendChild(header.render());

      const arrow = container.querySelector('#sidebar-toggle span');
      expect(arrow?.textContent).toBe('«');
    });

    it('shows arrow pointing right on mobile (collapsed)', () => {
      mockInnerWidth = 375;
      const header = new Header();
      container.appendChild(header.render());

      const arrow = container.querySelector('#sidebar-toggle span');
      expect(arrow?.textContent).toBe('»');
    });
  });

  describe('status display', () => {
    it('shows idle status', () => {
      vi.mocked(state.getState).mockReturnValue({
        status: { idle: true, stopped: false, blocked: false },
        wsConnected: false,
      } as any);

      const header = new Header();
      container.appendChild(header.render());

      const statusEl = container.querySelector('#header-status');
      expect(statusEl?.textContent).toBe('idle');
      expect(statusEl?.className).not.toContain('stopped');
      expect(statusEl?.className).not.toContain('blocked');
    });

    it('shows stopped status', () => {
      vi.mocked(state.getState).mockReturnValue({
        status: { idle: false, stopped: true, blocked: false },
        wsConnected: false,
      } as any);

      const header = new Header();
      container.appendChild(header.render());

      const statusEl = container.querySelector('#header-status');
      expect(statusEl?.textContent).toBe('STOPPED');
      expect(statusEl?.className).toContain('stopped');
    });

    it('shows blocked status', () => {
      vi.mocked(state.getState).mockReturnValue({
        status: { idle: false, stopped: false, blocked: true },
        wsConnected: false,
      } as any);

      const header = new Header();
      container.appendChild(header.render());

      const statusEl = container.querySelector('#header-status');
      expect(statusEl?.textContent).toBe('BLOCKED');
      expect(statusEl?.className).toContain('blocked');
    });

    it('shows running status when not idle/stopped/blocked', () => {
      vi.mocked(state.getState).mockReturnValue({
        status: { idle: false, stopped: false, blocked: false },
        wsConnected: false,
      } as any);

      const header = new Header();
      container.appendChild(header.render());

      const statusEl = container.querySelector('#header-status');
      expect(statusEl?.textContent).toBe('running');
      expect(statusEl?.className).toContain('active');
    });

    it('updates status when state changes', () => {
      const header = new Header();
      container.appendChild(header.render());

      // Simulate state change to stopped
      if (subscribeCallback) {
        subscribeCallback({
          status: { idle: false, stopped: true, blocked: false },
          wsConnected: false,
        });
      }

      const statusEl = container.querySelector('#header-status');
      expect(statusEl?.textContent).toBe('STOPPED');
    });
  });

  describe('connection indicator', () => {
    it('shows connecting state initially', () => {
      vi.mocked(state.getState).mockReturnValue({
        status: { idle: true },
        wsConnected: false,
      } as any);

      const header = new Header();
      container.appendChild(header.render());

      const label = container.querySelector('#conn-label');
      expect(label?.textContent).toBe('connecting');

      const dot = container.querySelector('#conn-dot');
      expect(dot?.classList.contains('live')).toBe(false);
    });

    it('shows live when connected', () => {
      const header = new Header();
      container.appendChild(header.render());

      // Simulate connection
      if (subscribeCallback) {
        subscribeCallback({
          status: { idle: true },
          wsConnected: true,
        });
      }

      const label = container.querySelector('#conn-label');
      expect(label?.textContent).toBe('live');

      const dot = container.querySelector('#conn-dot');
      expect(dot?.classList.contains('live')).toBe(true);
    });

    it('updates when connection state changes', () => {
      const header = new Header();
      container.appendChild(header.render());

      // Connect
      if (subscribeCallback) {
        subscribeCallback({
          status: { idle: true },
          wsConnected: true,
        });
      }

      let label = container.querySelector('#conn-label');
      expect(label?.textContent).toBe('live');

      // Disconnect
      if (subscribeCallback) {
        subscribeCallback({
          status: { idle: true },
          wsConnected: false,
        });
      }

      label = container.querySelector('#conn-label');
      expect(label?.textContent).toBe('connecting');
    });
  });

  describe('sidebar toggle', () => {
    it('toggles sidebar state on button click', () => {
      const header = new Header();
      container.appendChild(header.render());

      // Desktop starts expanded (not collapsed)
      expect(header.isSidebarCollapsed()).toBe(false);

      const toggleBtn = container.querySelector('#sidebar-toggle') as HTMLButtonElement;
      toggleBtn.click();

      expect(header.isSidebarCollapsed()).toBe(true);
    });

    it('dispatches sidebar-toggle event', () => {
      const header = new Header();
      container.appendChild(header.render());

      const toggleBtn = container.querySelector('#sidebar-toggle') as HTMLButtonElement;
      toggleBtn.click();

      expect(mockDispatchEvent).toHaveBeenCalledWith(
        expect.objectContaining({ type: 'sidebar-toggle' })
      );
    });

    it('updates button arrow on toggle', () => {
      const header = new Header();
      container.appendChild(header.render());

      const toggleBtn = container.querySelector('#sidebar-toggle') as HTMLButtonElement;
      const arrow = container.querySelector('#sidebar-toggle span');

      // Desktop starts with « (expanded)
      expect(arrow?.textContent).toBe('«');

      toggleBtn.click();

      // Now collapsed, should show »
      expect(arrow?.textContent).toBe('»');
    });

    it('updates button title on toggle', () => {
      const header = new Header();
      container.appendChild(header.render());

      const toggleBtn = container.querySelector('#sidebar-toggle') as HTMLButtonElement;

      // Desktop starts expanded
      expect(toggleBtn.getAttribute('title')).toContain('Collapse');

      toggleBtn.click();

      expect(toggleBtn.getAttribute('title')).toContain('Expand');
    });

    it('toggles back and forth', () => {
      const header = new Header();
      container.appendChild(header.render());

      const toggleBtn = container.querySelector('#sidebar-toggle') as HTMLButtonElement;

      expect(header.isSidebarCollapsed()).toBe(false);

      toggleBtn.click();
      expect(header.isSidebarCollapsed()).toBe(true);

      toggleBtn.click();
      expect(header.isSidebarCollapsed()).toBe(false);
    });
  });

  describe('soft stop', () => {
    it('calls softStop API when button clicked', async () => {
      vi.mocked(api.softStop).mockResolvedValue(undefined);
      const consoleSpy = vi.spyOn(console, 'log').mockImplementation(() => {});

      const header = new Header();
      container.appendChild(header.render());

      const stopBtn = container.querySelector('#btn-stop') as HTMLButtonElement;
      stopBtn.click();

      // Wait for async
      await new Promise(resolve => setTimeout(resolve, 50));

      expect(api.softStop).toHaveBeenCalled();
      expect(consoleSpy).toHaveBeenCalledWith('[Header] Soft stop requested');
    });

    it('handles soft stop error gracefully', async () => {
      vi.mocked(api.softStop).mockRejectedValue(new Error('Network error'));
      const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {});

      const header = new Header();
      container.appendChild(header.render());

      const stopBtn = container.querySelector('#btn-stop') as HTMLButtonElement;
      stopBtn.click();

      // Wait for async
      await new Promise(resolve => setTimeout(resolve, 50));

      expect(consoleSpy).toHaveBeenCalledWith(
        '[Header] Failed to request stop:',
        expect.any(Error)
      );
    });
  });

  describe('E-STOP', () => {
    it('prompts for confirmation before E-STOP', async () => {
      mockConfirm.mockReturnValue(false);
      vi.mocked(api.estop).mockResolvedValue(undefined);

      const header = new Header();
      container.appendChild(header.render());

      const killBtn = container.querySelector('#btn-kill') as HTMLButtonElement;
      killBtn.click();

      await new Promise(resolve => setTimeout(resolve, 50));

      expect(mockConfirm).toHaveBeenCalledWith(
        expect.stringContaining('Emergency Stop')
      );
    });

    it('calls estop when confirmed', async () => {
      mockConfirm.mockReturnValue(true);
      vi.mocked(api.estop).mockResolvedValue(undefined);

      const header = new Header();
      container.appendChild(header.render());

      const killBtn = container.querySelector('#btn-kill') as HTMLButtonElement;
      killBtn.click();

      await new Promise(resolve => setTimeout(resolve, 50));

      expect(api.estop).toHaveBeenCalled();
      expect(mockAlert).toHaveBeenCalledWith('E-STOP engaged. Service is shutting down.');
    });

    it('does not call estop when declined', async () => {
      mockConfirm.mockReturnValue(false);
      vi.mocked(api.estop).mockResolvedValue(undefined);

      const header = new Header();
      container.appendChild(header.render());

      const killBtn = container.querySelector('#btn-kill') as HTMLButtonElement;
      killBtn.click();

      await new Promise(resolve => setTimeout(resolve, 50));

      expect(api.estop).not.toHaveBeenCalled();
    });

    it('handles estop error gracefully', async () => {
      mockConfirm.mockReturnValue(true);
      vi.mocked(api.estop).mockRejectedValue(new Error('Failed'));
      const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {});

      const header = new Header();
      container.appendChild(header.render());

      const killBtn = container.querySelector('#btn-kill') as HTMLButtonElement;
      killBtn.click();

      await new Promise(resolve => setTimeout(resolve, 50));

      expect(consoleSpy).toHaveBeenCalledWith(
        '[Header] E-STOP error:',
        expect.any(Error)
      );
    });
  });

  describe('accessibility', () => {
    it('has aria-label on sidebar toggle', () => {
      const header = new Header();
      container.appendChild(header.render());

      const toggleBtn = container.querySelector('#sidebar-toggle');
      expect(toggleBtn?.getAttribute('aria-label')).toBe('Toggle sidebar');
    });

    it('has title attribute on sidebar toggle', () => {
      const header = new Header();
      container.appendChild(header.render());

      const toggleBtn = container.querySelector('#sidebar-toggle');
      expect(toggleBtn?.getAttribute('title')).toBeDefined();
    });

    it('has title on soft stop button', () => {
      const header = new Header();
      container.appendChild(header.render());

      const stopBtn = container.querySelector('#btn-stop');
      expect(stopBtn?.getAttribute('title')).toBe('Soft stop');
    });

    it('has title on E-STOP button', () => {
      const header = new Header();
      container.appendChild(header.render());

      const killBtn = container.querySelector('#btn-kill');
      expect(killBtn?.getAttribute('title')).toBe('E-STOP');
    });

    it('has proper header semantics', () => {
      const header = new Header();
      const element = header.render();

      expect(element.tagName.toLowerCase()).toBe('header');
    });
  });
});
