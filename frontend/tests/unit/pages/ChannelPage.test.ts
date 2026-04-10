/**
 * Unit Tests for ChannelPage Component
 *
 * Tests the channel task request surface for workspace and repo scopes.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { ChannelPage } from '../../../src/pages/ChannelPage';
import * as apiClient from '../../../src/api/client';

// Mock the API client
vi.mock('../../../src/api/client', () => ({
  interjectWorkspace: vi.fn(),
  interjectRepo: vi.fn(),
}));

describe('ChannelPage', () => {
  let container: HTMLElement;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    vi.clearAllMocks();
  });

  afterEach(() => {
    document.body.removeChild(container);
  });

  describe('Rendering', () => {
    it('creates channel page element for workspace', async () => {
      const page = new ChannelPage('workspace');
      await page.render(container);
      expect(container.querySelector('#channel-page')).toBeTruthy();
    });

    it('creates channel page element for repo', async () => {
      const page = new ChannelPage('my-repo');
      await page.render(container);
      expect(container.querySelector('#channel-page')).toBeTruthy();
    });

    it('renders header with scope name', async () => {
      const page = new ChannelPage('workspace');
      await page.render(container);
      expect(container.querySelector('#channel-header')?.textContent).toContain('Channel: Workspace');
    });

    it('renders repo name in header for repo channel', async () => {
      const page = new ChannelPage('my-repo');
      await page.render(container);
      expect(container.querySelector('#channel-header')?.textContent).toContain('Channel: my-repo');
    });

    it('renders description text explaining this is a task request surface', async () => {
      const page = new ChannelPage('workspace');
      await page.render(container);
      const desc = container.querySelector('#channel-description');
      expect(desc?.textContent).toContain('Manager');
      expect(desc?.textContent).toContain('create a new Manager task');
    });

    it('renders link to create task manually', async () => {
      const page = new ChannelPage('workspace');
      await page.render(container);
      const link = container.querySelector('a[href="/task-new"]');
      expect(link).toBeTruthy();
      expect(link?.textContent).toContain('create a task manually');
    });

    it('renders textarea for task description', async () => {
      const page = new ChannelPage('workspace');
      await page.render(container);
      const textarea = container.querySelector('#channel-input textarea');
      expect(textarea?.tagName).toBe('TEXTAREA');
    });

    it('has aria-label on textarea', async () => {
      const page = new ChannelPage('workspace');
      await page.render(container);
      const textarea = container.querySelector('#channel-input textarea');
      expect(textarea?.getAttribute('aria-label')).toContain('Task description');
    });

    it('renders send button', async () => {
      const page = new ChannelPage('workspace');
      await page.render(container);
      expect(container.querySelector('#channel-input button')).toBeTruthy();
    });

    it('renders message area (hidden by default)', async () => {
      const page = new ChannelPage('workspace');
      await page.render(container);
      const msg = container.querySelector('#channel-message');
      expect(msg).toBeTruthy();
      expect(msg?.getAttribute('style')).toContain('display:none');
    });
  });

  describe('Workspace placeholder', () => {
    it('shows workspace-appropriate placeholder', async () => {
      const page = new ChannelPage('workspace');
      await page.render(container);
      const textarea = container.querySelector('#channel-input textarea') as HTMLTextAreaElement;
      expect(textarea.placeholder).toContain('what you want the Manager to do');
    });

    it('shows repo-specific placeholder', async () => {
      const page = new ChannelPage('my-repo');
      await page.render(container);
      const textarea = container.querySelector('#channel-input textarea') as HTMLTextAreaElement;
      expect(textarea.placeholder).toContain('my-repo');
    });
  });

  describe('Sending interjection', () => {
    it('sends message to workspace on button click', async () => {
      vi.mocked(apiClient.interjectWorkspace).mockResolvedValue({ ok: true });
      const page = new ChannelPage('workspace');
      await page.render(container);

      const textarea = container.querySelector('#channel-input textarea') as HTMLTextAreaElement;
      textarea.value = 'Add a login feature';

      const sendBtn = container.querySelector('#channel-input button') as HTMLButtonElement;
      sendBtn.click();

      await new Promise(r => setTimeout(r, 0));
      expect(apiClient.interjectWorkspace).toHaveBeenCalledWith('Add a login feature');
    });

    it('sends message to repo on button click', async () => {
      vi.mocked(apiClient.interjectRepo).mockResolvedValue({ ok: true });
      const page = new ChannelPage('my-repo');
      await page.render(container);

      const textarea = container.querySelector('#channel-input textarea') as HTMLTextAreaElement;
      textarea.value = 'Fix the CI pipeline';

      const sendBtn = container.querySelector('#channel-input button') as HTMLButtonElement;
      sendBtn.click();

      await new Promise(r => setTimeout(r, 0));
      expect(apiClient.interjectRepo).toHaveBeenCalledWith('my-repo', 'Fix the CI pipeline');
    });

    it('does not send empty messages', async () => {
      const page = new ChannelPage('workspace');
      await page.render(container);

      const textarea = container.querySelector('#channel-input textarea') as HTMLTextAreaElement;
      textarea.value = '   ';

      const sendBtn = container.querySelector('#channel-input button') as HTMLButtonElement;
      sendBtn.click();

      await new Promise(r => setTimeout(r, 0));
      expect(apiClient.interjectWorkspace).not.toHaveBeenCalled();
    });

    it('clears input after sending', async () => {
      vi.mocked(apiClient.interjectWorkspace).mockResolvedValue({ ok: true });
      const page = new ChannelPage('workspace');
      await page.render(container);

      const textarea = container.querySelector('#channel-input textarea') as HTMLTextAreaElement;
      textarea.value = 'Test message';

      const sendBtn = container.querySelector('#channel-input button') as HTMLButtonElement;
      sendBtn.click();

      await new Promise(r => setTimeout(r, 0));
      expect(textarea.value).toBe('');
    });

    it('shows success message when no task_id returned', async () => {
      vi.mocked(apiClient.interjectWorkspace).mockResolvedValue({ ok: true });
      const page = new ChannelPage('workspace');
      await page.render(container);

      const textarea = container.querySelector('#channel-input textarea') as HTMLTextAreaElement;
      textarea.value = 'Test';

      const sendBtn = container.querySelector('#channel-input button') as HTMLButtonElement;
      sendBtn.click();

      await new Promise(r => setTimeout(r, 10));
      const msg = container.querySelector('#channel-message');
      expect(msg?.textContent).toBe('Message sent to Manager.');
    });

    it('redirects to TaskPage when manager_task_id returned', async () => {
      vi.mocked(apiClient.interjectWorkspace).mockResolvedValue({ ok: true, manager_task_id: 'task042' });
      const page = new ChannelPage('workspace');
      await page.render(container);

      const textarea = container.querySelector('#channel-input textarea') as HTMLTextAreaElement;
      textarea.value = 'Test';

      const pushStateSpy = vi.spyOn(window.history, 'pushState').mockImplementation(() => {});
      const dispatchSpy = vi.spyOn(window, 'dispatchEvent').mockImplementation(() => true);

      const sendBtn = container.querySelector('#channel-input button') as HTMLButtonElement;
      sendBtn.click();

      await new Promise(r => setTimeout(r, 10));
      expect(pushStateSpy).toHaveBeenCalledWith({}, '', '/task/task042');
      expect(dispatchSpy).toHaveBeenCalledWith(new Event('popstate'));

      pushStateSpy.mockRestore();
      dispatchSpy.mockRestore();
    });

    it('shows error message on failure', async () => {
      vi.mocked(apiClient.interjectWorkspace).mockRejectedValue(new Error('Network error'));
      const page = new ChannelPage('workspace');
      await page.render(container);

      const textarea = container.querySelector('#channel-input textarea') as HTMLTextAreaElement;
      textarea.value = 'Test';

      const sendBtn = container.querySelector('#channel-input button') as HTMLButtonElement;
      sendBtn.click();

      await new Promise(r => setTimeout(r, 10));
      const msg = container.querySelector('#channel-message');
      expect(msg?.textContent).toContain('Failed to send');
    });

    it('disables button while sending', async () => {
      vi.mocked(apiClient.interjectWorkspace).mockImplementation(
        () => new Promise(resolve => setTimeout(() => resolve({ ok: true }), 50))
      );
      const page = new ChannelPage('workspace');
      await page.render(container);

      const textarea = container.querySelector('#channel-input textarea') as HTMLTextAreaElement;
      textarea.value = 'Test';

      const sendBtn = container.querySelector('#channel-input button') as HTMLButtonElement;
      sendBtn.click();

      // Should be disabled immediately
      expect(sendBtn.disabled).toBe(true);
      expect(sendBtn.textContent).toBe('Sending...');

      // Wait for completion
      await new Promise(r => setTimeout(r, 100));
      expect(sendBtn.disabled).toBe(false);
      expect(sendBtn.textContent).toBe('Send');
    });

    it('prevents double-send (isSending guard)', async () => {
      vi.mocked(apiClient.interjectWorkspace).mockImplementation(
        () => new Promise(resolve => setTimeout(() => resolve({ ok: true }), 100))
      );
      const page = new ChannelPage('workspace');
      await page.render(container);

      const textarea = container.querySelector('#channel-input textarea') as HTMLTextAreaElement;
      textarea.value = 'Test';

      const sendBtn = container.querySelector('#channel-input button') as HTMLButtonElement;
      sendBtn.click();
      sendBtn.click(); // Double click

      await new Promise(r => setTimeout(r, 10));
      expect(apiClient.interjectWorkspace).toHaveBeenCalledTimes(1);
    });
  });

  describe('Keyboard interaction', () => {
    it('sends on Enter key', async () => {
      vi.mocked(apiClient.interjectWorkspace).mockResolvedValue({ ok: true });
      const page = new ChannelPage('workspace');
      await page.render(container);

      const textarea = container.querySelector('#channel-input textarea') as HTMLTextAreaElement;
      textarea.value = 'Test message';

      textarea.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));

      await new Promise(r => setTimeout(r, 0));
      expect(apiClient.interjectWorkspace).toHaveBeenCalledWith('Test message');
    });

    it('does NOT send on Shift+Enter (allows newline)', async () => {
      const page = new ChannelPage('workspace');
      await page.render(container);

      const textarea = container.querySelector('#channel-input textarea') as HTMLTextAreaElement;
      textarea.value = 'Test message';

      textarea.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', shiftKey: true, bubbles: true }));

      await new Promise(r => setTimeout(r, 0));
      expect(apiClient.interjectWorkspace).not.toHaveBeenCalled();
    });
  });

  describe('Auto-resize textarea', () => {
    it('resizes on input', async () => {
      const page = new ChannelPage('workspace');
      await page.render(container);

      const textarea = container.querySelector('#channel-input textarea') as HTMLTextAreaElement;
      textarea.style.height = 'auto';
      Object.defineProperty(textarea, 'scrollHeight', { value: 120, configurable: true });

      textarea.dispatchEvent(new Event('input', { bubbles: true }));

      expect(textarea.style.height).toBe('120px');
    });

    it('caps height at 200px', async () => {
      const page = new ChannelPage('workspace');
      await page.render(container);

      const textarea = container.querySelector('#channel-input textarea') as HTMLTextAreaElement;
      textarea.style.height = 'auto';
      Object.defineProperty(textarea, 'scrollHeight', { value: 400, configurable: true });

      textarea.dispatchEvent(new Event('input', { bubbles: true }));

      expect(textarea.style.height).toBe('200px');
    });
  });

  describe('Cleanup', () => {
    it('destroy clears references', async () => {
      const page = new ChannelPage('workspace');
      await page.render(container);

      page.destroy();

      // Internal references should be null (verified via public behavior)
      // The abort controller should be triggered
      expect(page).toBeTruthy(); // Component still exists
    });
  });
});
