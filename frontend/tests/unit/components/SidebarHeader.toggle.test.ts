/**
 * Unit tests for Sidebar and Header toggle functionality
 * Tests the core toggle logic without relying on DOM events
 */

import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { Sidebar } from '../../../src/components/Sidebar';
import { Header } from '../../../src/components/Header';
import { resetState } from '../../../src/state/store';

describe('Sidebar and Header Toggle Logic', () => {
  let sidebar: Sidebar;
  let header: Header;
  let container: HTMLElement;

  beforeEach(() => {
    resetState();
    sidebar = new Sidebar();
    header = new Header();
    container = document.createElement('div');
    document.body.appendChild(container);
  });

  afterEach(() => {
    document.body.removeChild(container);
    container = null as unknown as HTMLElement;
  });

  describe('Toggle button direction', () => {
    it('shows collapse arrow (←) when sidebar is expanded (desktop default)', () => {
      Object.defineProperty(window, 'innerWidth', { value: 1280 });
      const headerEl = header.render();
      container.appendChild(headerEl);
      
      const span = headerEl.querySelector('#sidebar-toggle span');
      expect(span?.textContent?.trim()).toBe('«');
    });

    it('shows expand arrow (→) when sidebar is collapsed (mobile default)', () => {
      Object.defineProperty(window, 'innerWidth', { value: 375 });
      const headerEl = header.render();
      container.appendChild(headerEl);
      
      const span = headerEl.querySelector('#sidebar-toggle span');
      expect(span?.textContent?.trim()).toBe('»');
    });

    it('updates to collapse arrow when sidebar expands', () => {
      const headerEl = header.render();
      container.appendChild(headerEl);
      
      // Simulate sidebar expanding
      header.toggleSidebar();
      
      const span = headerEl.querySelector('#sidebar-toggle span');
      expect(span?.textContent?.trim()).toBe('«');
    });

    it('updates to expand arrow when sidebar collapses', () => {
      Object.defineProperty(window, 'innerWidth', { value: 1280 });
      const headerEl = header.render();
      container.appendChild(headerEl);
      
      // Simulate sidebar collapsing
      header.toggleSidebar();
      
      const span = headerEl.querySelector('#sidebar-toggle span');
      expect(span?.textContent?.trim()).toBe('»');
    });
  });

  describe('Desktop (>600px)', () => {
    beforeEach(() => {
      Object.defineProperty(window, 'innerWidth', {
        writable: true,
        configurable: true,
        value: 1280,
      });
    });

    it('sidebar starts expanded', () => {
      const element = sidebar.render();
      expect(element.classList.contains('collapsed')).toBe(false);
    });

    it('header toggle button starts pointing left', () => {
      const headerEl = header.render();
      container.appendChild(headerEl);
      
      const span = headerEl.querySelector('#sidebar-toggle span');
      expect(span?.textContent?.trim()).toBe('«');
    });

    it('toggling header collapses sidebar', () => {
      const element = sidebar.render();
      const headerEl = header.render();
      container.appendChild(headerEl);
      
      // Simulate toggle event
      header.toggleSidebar();
      
      // Manually trigger sidebar update (since we're not using real DOM events in unit tests)
      sidebar.setCollapsed(header.isSidebarCollapsed());
      
      expect(element.classList.contains('collapsed')).toBe(true);
    });

    it('toggling twice returns to expanded state', () => {
      const element = sidebar.render();
      const headerEl = header.render();
      container.appendChild(headerEl);
      
      // Toggle twice
      header.toggleSidebar();
      sidebar.setCollapsed(header.isSidebarCollapsed());
      header.toggleSidebar();
      sidebar.setCollapsed(header.isSidebarCollapsed());
      
      expect(element.classList.contains('collapsed')).toBe(false);
      
      const span = headerEl.querySelector('#sidebar-toggle span');
      expect(span?.textContent?.trim()).toBe('«');
    });
  });

  describe('Mobile (≤600px)', () => {
    beforeEach(() => {
      Object.defineProperty(window, 'innerWidth', {
        writable: true,
        configurable: true,
        value: 375,
      });
    });

    it('sidebar starts collapsed', () => {
      const element = sidebar.render();
      expect(element.classList.contains('collapsed')).toBe(true);
    });

    it('header toggle button starts pointing right', () => {
      const headerEl = header.render();
      container.appendChild(headerEl);
      
      const span = headerEl.querySelector('#sidebar-toggle span');
      expect(span?.textContent?.trim()).toBe('»');
    });

    it('toggling header expands sidebar', () => {
      const element = sidebar.render();
      const headerEl = header.render();
      container.appendChild(headerEl);
      
      // Simulate toggle event
      header.toggleSidebar();
      
      // Manually trigger sidebar update
      sidebar.setCollapsed(header.isSidebarCollapsed());
      
      expect(element.classList.contains('collapsed')).toBe(false);
    });

    it('toggling twice returns to collapsed state', () => {
      const element = sidebar.render();
      const headerEl = header.render();
      container.appendChild(headerEl);
      
      // Toggle twice
      header.toggleSidebar();
      sidebar.setCollapsed(header.isSidebarCollapsed());
      header.toggleSidebar();
      sidebar.setCollapsed(header.isSidebarCollapsed());
      
      expect(element.classList.contains('collapsed')).toBe(true);
      
      const span = headerEl.querySelector('#sidebar-toggle span');
      expect(span?.textContent?.trim()).toBe('»');
    });
  });
});
