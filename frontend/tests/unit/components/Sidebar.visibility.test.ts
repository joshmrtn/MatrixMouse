/**
 * Unit tests for Sidebar component - Visibility
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { Sidebar } from '../../../src/components/Sidebar';
import { resetState } from '../../../src/state/store';

describe('Sidebar - Visibility', () => {
  let sidebar: Sidebar;
  let container: HTMLElement;

  beforeEach(() => {
    resetState();
    sidebar = new Sidebar();
    container = document.createElement('div');
    document.body.appendChild(container);
  });

  afterEach(() => {
    document.body.removeChild(container);
    container = null as unknown as HTMLElement;
    vi.restoreAllMocks();
  });

  /**
   * Helper to check if element has CSS that makes it visible
   */
  function hasVisibleStyles(element: Element | null): boolean {
    if (!element) return false;
    const style = window.getComputedStyle(element);
    return (
      style.display !== 'none' &&
      style.visibility !== 'hidden' &&
      style.opacity !== '0'
    );
  }

  describe('Desktop (>600px)', () => {
    beforeEach(() => {
      // Mock desktop viewport
      Object.defineProperty(window, 'innerWidth', {
        writable: true,
        configurable: true,
        value: 1280,
      });
    });

    it('renders sidebar without collapsed class on desktop', () => {
      const element = sidebar.render();
      expect(element.classList.contains('collapsed')).toBe(false);
    });

    it('sidebar header is visible', () => {
      const element = sidebar.render();
      const header = element.querySelector('.sidebar-header');
      expect(hasVisibleStyles(header)).toBe(true);
    });

    it('sidebar does NOT have collapse button in header', () => {
      const element = sidebar.render();
      const collapseBtn = element.querySelector('.sidebar-collapse');
      expect(collapseBtn).toBeFalsy();
    });

    it('setCollapsed(true) adds collapsed class', () => {
      const element = sidebar.render();
      sidebar.setCollapsed(true);
      expect(element.classList.contains('collapsed')).toBe(true);
    });

    it('setCollapsed(false) removes collapsed class', () => {
      const element = sidebar.render();
      sidebar.setCollapsed(true);
      sidebar.setCollapsed(false);
      expect(element.classList.contains('collapsed')).toBe(false);
    });
  });

  describe('Mobile (≤600px)', () => {
    beforeEach(() => {
      // Mock mobile viewport
      Object.defineProperty(window, 'innerWidth', {
        writable: true,
        configurable: true,
        value: 375,
      });
    });

    it('renders sidebar with collapsed class on mobile', () => {
      const element = sidebar.render();
      expect(element.classList.contains('collapsed')).toBe(true);
    });

    it('sidebar does NOT have collapse button in header', () => {
      const element = sidebar.render();
      const collapseBtn = element.querySelector('.sidebar-collapse');
      expect(collapseBtn).toBeFalsy();
    });

    it('setCollapsed(false) removes collapsed class', () => {
      const element = sidebar.render();
      sidebar.setCollapsed(false);
      expect(element.classList.contains('collapsed')).toBe(false);
    });

    it('setCollapsed(true) adds collapsed class', () => {
      const element = sidebar.render();
      sidebar.setCollapsed(false);
      sidebar.setCollapsed(true);
      expect(element.classList.contains('collapsed')).toBe(true);
    });

    it('maintains state after multiple setCollapsed calls', () => {
      const element = sidebar.render();
      
      sidebar.setCollapsed(false);
      expect(element.classList.contains('collapsed')).toBe(false);
      
      sidebar.setCollapsed(true);
      expect(element.classList.contains('collapsed')).toBe(true);
      
      sidebar.setCollapsed(false);
      expect(element.classList.contains('collapsed')).toBe(false);
    });
  });

  describe('Responsive behavior', () => {
    it('handles viewport change from desktop to mobile', () => {
      // Start desktop
      Object.defineProperty(window, 'innerWidth', { value: 1280 });
      const element = sidebar.render();
      expect(element.classList.contains('collapsed')).toBe(false);

      // Change to mobile and re-render
      Object.defineProperty(window, 'innerWidth', { value: 375 });
      const newSidebar = new Sidebar();
      const newElement = newSidebar.render();
      expect(newElement.classList.contains('collapsed')).toBe(true);
    });

    it('handles viewport change from mobile to desktop', () => {
      // Start mobile
      Object.defineProperty(window, 'innerWidth', { value: 375 });
      const element = sidebar.render();
      expect(element.classList.contains('collapsed')).toBe(true);

      // Change to desktop and re-render
      Object.defineProperty(window, 'innerWidth', { value: 1280 });
      const newSidebar = new Sidebar();
      const newElement = newSidebar.render();
      expect(newElement.classList.contains('collapsed')).toBe(false);
    });
  });
});
