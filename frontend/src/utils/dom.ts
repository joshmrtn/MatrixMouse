/**
 * DOM helper utilities
 */

/**
 * Get element by ID with type safety
 */
export function $id<T extends HTMLElement>(id: string): T | null {
  return document.getElementById(id) as T | null;
}

/**
 * Create element with attributes
 */
export function createElement<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  attributes: Record<string, string> = {},
  children: (Node | string)[] = []
): HTMLElementTagNameMap[K] {
  const el = document.createElement(tag);
  
  Object.entries(attributes).forEach(([key, value]) => {
    if (key === 'className') {
      el.className = value;
    } else if (key.startsWith('data-')) {
      el.setAttribute(key, value);
    } else if (key.startsWith('on') && typeof value === 'string') {
      // Handle inline event handlers if needed
    } else {
      el.setAttribute(key, value);
    }
  });
  
  children.forEach((child) => {
    if (typeof child === 'string') {
      el.appendChild(document.createTextNode(child));
    } else {
      el.appendChild(child);
    }
  });
  
  return el;
}

/**
 * Clear all children from an element
 */
export function clearChildren(el: Element): void {
  while (el.firstChild) {
    el.removeChild(el.firstChild);
  }
}

/**
 * Toggle class on element
 */
export function toggleClass(el: Element, className: string, force?: boolean): void {
  el.classList.toggle(className, force);
}

/**
 * Check if element has class
 */
export function hasClass(el: Element, className: string): boolean {
  return el.classList.contains(className);
}

/**
 * Add class to element
 */
export function addClass(el: Element, ...classNames: string[]): void {
  el.classList.add(...classNames);
}

/**
 * Remove class from element
 */
export function removeClass(el: Element, ...classNames: string[]): void {
  el.classList.remove(...classNames);
}

/**
 * Get current timestamp string (HH:MM:SS)
 */
export function ts(): string {
  return new Date().toTimeString().slice(0, 8);
}
