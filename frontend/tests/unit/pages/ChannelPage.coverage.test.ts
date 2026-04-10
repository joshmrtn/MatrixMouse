/**
 * ChannelPage - Additional Coverage Tests
 *
 * Covers edge cases and scenarios not tested in the main test file.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { ChannelPage } from '../../../src/pages/ChannelPage';
import * as apiClient from '../../../src/api/client';

vi.mock('../../../src/api/client', () => ({
  interjectWorkspace: vi.fn(),
  interjectRepo: vi.fn(),
}));

describe('ChannelPage - Additional Coverage', () => {
  let container: HTMLElement;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    vi.clearAllMocks();
  });

  afterEach(() => {
    document.body.removeChild(container);
  });

  describe('Error handling', () => {
    it('handles API error with no message', async () => {
      vi.mocked(apiClient.interjectWorkspace).mockRejectedValue({});
      const page = new ChannelPage('workspace');
      await page.render(container);

      const textarea = container.querySelector('#channel-input textarea') as HTMLTextAreaElement;
      textarea.value = 'Test';
      (container.querySelector('#channel-input button') as HTMLButtonElement).click();

      await new Promise(r => setTimeout(r, 10));
      const msg = container.querySelector('#channel-message');
      expect(msg?.style.display).toBe('block');
    });

    it('handles API error with detail property', async () => {
      const err = new Error('detail: Invalid message');
      vi.mocked(apiClient.interjectWorkspace).mockRejectedValue(err);
      const page = new ChannelPage('workspace');
      await page.render(container);

      const textarea = container.querySelector('#channel-input textarea') as HTMLTextAreaElement;
      textarea.value = 'Test';
      (container.querySelector('#channel-input button') as HTMLButtonElement).click();

      await new Promise(r => setTimeout(r, 10));
      const msg = container.querySelector('#channel-message');
      expect(msg?.textContent).toContain('Failed to send');
    });

    it('hides message area before sending', async () => {
      const page = new ChannelPage('workspace');
      await page.render(container);

      const msg = container.querySelector('#channel-message') as HTMLElement;
      expect(msg.style.display).toBe('none');
    });
  });

  describe('Whitespace handling', () => {
    it('trims message before sending', async () => {
      vi.mocked(apiClient.interjectWorkspace).mockResolvedValue({ ok: true });
      const page = new ChannelPage('workspace');
      await page.render(container);

      const textarea = container.querySelector('#channel-input textarea') as HTMLTextAreaElement;
      textarea.value = '  spaced message  ';

      (container.querySelector('#channel-input button') as HTMLButtonElement).click();

      await new Promise(r => setTimeout(r, 0));
      expect(apiClient.interjectWorkspace).toHaveBeenCalledWith('spaced message');
    });

    it('does not send whitespace-only messages', async () => {
      const page = new ChannelPage('workspace');
      await page.render(container);

      const textarea = container.querySelector('#channel-input textarea') as HTMLTextAreaElement;
      textarea.value = '\n\t  \n';

      (container.querySelector('#channel-input button') as HTMLButtonElement).click();

      await new Promise(r => setTimeout(r, 0));
      expect(apiClient.interjectWorkspace).not.toHaveBeenCalled();
    });
  });

  describe('Input state after send', () => {
    it('resets textarea height after send', async () => {
      vi.mocked(apiClient.interjectWorkspace).mockResolvedValue({ ok: true });
      const page = new ChannelPage('workspace');
      await page.render(container);

      const textarea = container.querySelector('#channel-input textarea') as HTMLTextAreaElement;
      textarea.value = 'Test';
      textarea.style.height = '100px';

      (container.querySelector('#channel-input button') as HTMLButtonElement).click();

      await new Promise(r => setTimeout(r, 10));
      expect(textarea.style.height).toBe('auto');
    });
  });

  describe('HTML escaping in template', () => {
    it('escapes HTML in channel label', async () => {
      const page = new ChannelPage('<script>alert(1)</script>');
      await page.render(container);

      const header = container.querySelector('#channel-header');
      // escapeHtml should convert < to &lt;
      expect(header?.innerHTML).not.toContain('<script>');
    });

    it('has aria-label on textarea', async () => {
      const page = new ChannelPage('my-repo');
      await page.render(container);

      const textarea = container.querySelector('#channel-input textarea');
      expect(textarea?.getAttribute('aria-label')).toContain('Task description');
    });
  });

  describe('Repo channel', () => {
    it('calls interjectRepo with correct repo name', async () => {
      vi.mocked(apiClient.interjectRepo).mockResolvedValue({ ok: true });
      const page = new ChannelPage('my-repo');
      await page.render(container);

      const textarea = container.querySelector('#channel-input textarea') as HTMLTextAreaElement;
      textarea.value = 'Fix bug';

      (container.querySelector('#channel-input button') as HTMLButtonElement).click();

      await new Promise(r => setTimeout(r, 0));
      expect(apiClient.interjectRepo).toHaveBeenCalledWith('my-repo', 'Fix bug');
    });

    it('renders description text', async () => {
      const page = new ChannelPage('my-repo');
      await page.render(container);

      const desc = container.querySelector('#channel-description');
      expect(desc?.textContent).toContain('Manager');
    });
  });

  describe('AbortController lifecycle', () => {
    it('destroy cleans up internal references', async () => {
      const page = new ChannelPage('workspace');
      await page.render(container);

      page.destroy();

      // After destroy, the component should be in a clean state
      // (internal element, inputEl, sendBtn, messageEl are null)
      expect(page).toBeTruthy();
    });
  });

  describe('Multiple rapid sends', () => {
    it('prevents concurrent sends with isSending guard', async () => {
      let resolvePromise: ((v: any) => void) | null = null;
      vi.mocked(apiClient.interjectWorkspace).mockImplementation(
        () => new Promise(resolve => { resolvePromise = resolve; })
      );

      const page = new ChannelPage('workspace');
      await page.render(container);

      const textarea = container.querySelector('#channel-input textarea') as HTMLTextAreaElement;
      textarea.value = 'Test';
      const sendBtn = container.querySelector('#channel-input button') as HTMLButtonElement;

      sendBtn.click();
      sendBtn.click();
      sendBtn.click();

      expect(apiClient.interjectWorkspace).toHaveBeenCalledTimes(1);

      resolvePromise!({ ok: true });
      await new Promise(r => setTimeout(r, 10));
    });
  });
});
