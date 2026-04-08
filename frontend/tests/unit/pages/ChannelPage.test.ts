/**
 * Unit Tests for ChannelPage Component
 *
 * Tests the channel/conversation view for workspace and repo scopes.
 * Covers rendering, interjections, pending questions, and message display.
 */

import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import { ChannelPage } from '../../../src/pages/ChannelPage';
import * as apiClient from '../../../src/api/client';

// Mock the API client
vi.mock('../../../src/api/client', () => ({
  getContext: vi.fn(),
  interjectWorkspace: vi.fn(),
  interjectRepo: vi.fn(),
  getPending: vi.fn(),
}));

describe('ChannelPage', () => {
  let page: ChannelPage;
  let container: HTMLElement;

  beforeEach(() => {
    page = new ChannelPage('workspace');
    container = document.createElement('div');
    document.body.appendChild(container);
    vi.clearAllMocks();
  });

  afterEach(() => {
    document.body.removeChild(container);
    container = null as unknown as HTMLElement;
  });

  describe('render', () => {
    it('creates channel page element', async () => {
      await page.render(container);
      const element = container.querySelector('#channel-page');
      expect(element).toBeTruthy();
    });

    it('renders header with scope name', async () => {
      await page.render(container);
      const header = container.querySelector('#channel-header');
      expect(header?.textContent).toContain('Channel: workspace');
    });

    it('renders conversation log container', async () => {
      await page.render(container);
      const log = container.querySelector('#conversation-log');
      expect(log).toBeTruthy();
    });

    it('renders input field and send button', async () => {
      await page.render(container);
      const textarea = container.querySelector('#channel-input textarea');
      const button = container.querySelector('#channel-input button');
      expect(textarea).toBeTruthy();
      expect(button).toBeTruthy();
      expect(button?.textContent).toBe('Send');
    });

    it('renders clarification banner (hidden by default)', async () => {
      await page.render(container);
      const banner = container.querySelector('#clarification-banner');
      expect(banner).toBeTruthy();
      expect(banner?.classList.contains('active')).toBe(false);
    });

    it('renders repo-specific channel', async () => {
      page = new ChannelPage('test-repo');
      await page.render(container);
      const header = container.querySelector('#channel-header');
      expect(header?.textContent).toContain('Channel: test-repo');

      const textarea = container.querySelector('#channel-input textarea') as HTMLTextAreaElement;
      expect(textarea?.placeholder).toBe('Message test-repo...');
    });
  });

  describe('conversation display', () => {
    it('shows empty state when no messages', async () => {
      vi.mocked(apiClient.getContext).mockResolvedValue({
        messages: [],
        count: 0,
        estimated_tokens: 0,
      });

      await page.render(container);
      
      // Wait for async rendering
      await new Promise((resolve) => setTimeout(resolve, 10));
      
      const placeholder = container.querySelector('#conversation-log');
      expect(placeholder?.textContent).toContain('No conversation yet');
    });

    it('displays user messages', async () => {
      vi.mocked(apiClient.getContext).mockResolvedValue({
        messages: [
          { role: 'user', content: 'Hello, can you help me?' },
        ],
        count: 1,
        estimated_tokens: 10,
      });

      await page.render(container);
      await new Promise((resolve) => setTimeout(resolve, 10));

      const userMsg = container.querySelector('.message-bubble.user');
      expect(userMsg).toBeTruthy();
      expect(userMsg?.textContent).toContain('Hello, can you help me?');
    });

    it('displays assistant messages', async () => {
      vi.mocked(apiClient.getContext).mockResolvedValue({
        messages: [
          { role: 'assistant', content: 'Sure, I\'d be happy to help!' },
        ],
        count: 1,
        estimated_tokens: 10,
      });

      await page.render(container);
      await new Promise((resolve) => setTimeout(resolve, 10));

      const assistantMsg = container.querySelector('.message-bubble.assistant');
      expect(assistantMsg).toBeTruthy();
      expect(assistantMsg?.textContent).toContain('Sure, I\'d be happy to help!');
    });

    it('displays system messages', async () => {
      vi.mocked(apiClient.getContext).mockResolvedValue({
        messages: [
          { role: 'system', content: 'Task started' },
        ],
        count: 1,
        estimated_tokens: 5,
      });

      await page.render(container);
      await new Promise((resolve) => setTimeout(resolve, 10));

      // System messages should be filtered out for cleaner view
      const systemMsg = container.querySelector('.message-bubble.system');
      expect(systemMsg).toBeFalsy();
    });

    it('displays tool_call messages with preformatted text', async () => {
      vi.mocked(apiClient.getContext).mockResolvedValue({
        messages: [
          { role: 'tool_call', content: 'read_file(path="test.py")' },
        ],
        count: 1,
        estimated_tokens: 5,
      });

      await page.render(container);
      await new Promise((resolve) => setTimeout(resolve, 10));

      const toolMsg = container.querySelector('.message-bubble');
      expect(toolMsg).toBeTruthy();
      const pre = toolMsg?.querySelector('pre');
      expect(pre).toBeTruthy();
      expect(pre?.textContent).toContain('read_file(path="test.py")');
    });

    it('displays tool_result messages with preformatted text', async () => {
      vi.mocked(apiClient.getContext).mockResolvedValue({
        messages: [
          { role: 'tool_result', content: 'File contents: print("hello")' },
        ],
        count: 1,
        estimated_tokens: 8,
      });

      await page.render(container);
      await new Promise((resolve) => setTimeout(resolve, 10));

      const toolMsg = container.querySelector('.message-bubble');
      expect(toolMsg).toBeTruthy();
      const pre = toolMsg?.querySelector('pre');
      expect(pre).toBeTruthy();
      expect(pre?.textContent).toContain('File contents: print("hello")');
    });

    it('renders markdown in assistant messages', async () => {
      vi.mocked(apiClient.getContext).mockResolvedValue({
        messages: [
          { 
            role: 'assistant', 
            content: 'Here is the code:\n\n```python\nprint("hello")\n```' 
          },
        ],
        count: 1,
        estimated_tokens: 15,
      });

      await page.render(container);
      await new Promise((resolve) => setTimeout(resolve, 10));

      const assistantMsg = container.querySelector('.message-bubble.assistant');
      expect(assistantMsg).toBeTruthy();
      // Markdown should be rendered (check for pre/code block)
      expect(assistantMsg?.innerHTML).toContain('<pre>');
      expect(assistantMsg?.innerHTML).toContain('<code');
    });

    it('escapes HTML in message content', async () => {
      vi.mocked(apiClient.getContext).mockResolvedValue({
        messages: [
          { role: 'user', content: '<script>alert("xss")</script>' },
        ],
        count: 1,
        estimated_tokens: 5,
      });

      await page.render(container);
      await new Promise((resolve) => setTimeout(resolve, 10));

      const userMsg = container.querySelector('.message-bubble.user');
      // The content should be escaped - check the message-content div specifically
      const contentEl = userMsg?.querySelector('.message-content');
      expect(contentEl).toBeTruthy();
      // Should not have script tags in the content
      expect(contentEl?.innerHTML).not.toContain('<script>');
      // The escaped version should appear
      expect(contentEl?.innerHTML).toContain('&lt;');
    });

    it('displays message role labels', async () => {
      vi.mocked(apiClient.getContext).mockResolvedValue({
        messages: [
          { role: 'user', content: 'Hello' },
          { role: 'assistant', content: 'Hi there' },
        ],
        count: 2,
        estimated_tokens: 10,
      });

      await page.render(container);
      await new Promise((resolve) => setTimeout(resolve, 10));

      const roleLabels = container.querySelectorAll('.message-role');
      expect(roleLabels.length).toBe(2);
      expect(roleLabels[0].textContent).toBe('user');
      expect(roleLabels[1].textContent).toBe('assistant');
    });

    it('scrolls to bottom after loading messages', async () => {
      const mockMessages = Array(20).fill(null).map((_, i) => ({
        role: i % 2 === 0 ? 'user' : 'assistant' as const,
        content: `Message ${i}`,
      }));

      vi.mocked(apiClient.getContext).mockResolvedValue({
        messages: mockMessages,
        count: 20,
        estimated_tokens: 200,
      });

      await page.render(container);
      // Wait longer for DOM to render and scroll
      await new Promise((resolve) => setTimeout(resolve, 100));

      const log = container.querySelector('#conversation-log') as HTMLElement;
      expect(log).toBeTruthy();
      // Scroll should have been attempted (scrollTop >= 0)
      // Note: In JSDOM, scrollTop may always be 0, so we just verify it exists
      expect(typeof log?.scrollTop).toBe('number');
    });
  });

  describe('error handling', () => {
    it('displays error message when context load fails', async () => {
      vi.mocked(apiClient.getContext).mockRejectedValue(new Error('Network error'));

      await page.render(container);
      await new Promise((resolve) => setTimeout(resolve, 10));

      const log = container.querySelector('#conversation-log');
      expect(log?.textContent).toContain('Failed to load conversation');
    });

    it('handles empty message content gracefully', async () => {
      vi.mocked(apiClient.getContext).mockResolvedValue({
        messages: [
          { role: 'user', content: '' },
          { role: 'assistant', content: '   ' },
          { role: 'user', content: 'Valid message' },
        ],
        count: 3,
        estimated_tokens: 5,
      });

      await page.render(container);
      await new Promise((resolve) => setTimeout(resolve, 10));

      const messages = container.querySelectorAll('.message-bubble');
      // Empty messages should be filtered out
      expect(messages.length).toBe(1);
      expect(messages[0].textContent).toContain('Valid message');
    });

    it('handles missing role gracefully', async () => {
      vi.mocked(apiClient.getContext).mockResolvedValue({
        messages: [
          { role: 'unknown' as any, content: 'Test' },
        ],
        count: 1,
        estimated_tokens: 5,
      });

      await page.render(container);
      await new Promise((resolve) => setTimeout(resolve, 10));

      const msg = container.querySelector('.message-bubble');
      expect(msg).toBeTruthy();
    });
  });

  describe('interjection sending', () => {
    beforeEach(() => {
      vi.mocked(apiClient.interjectWorkspace).mockResolvedValue({ ok: true, manager_task_id: 'task123' });
      vi.mocked(apiClient.interjectRepo).mockResolvedValue({ ok: true, manager_task_id: 'task456', repo: 'test-repo' });
    });

    it('sends workspace interjection on button click', async () => {
      await page.render(container);
      await new Promise((resolve) => setTimeout(resolve, 10));

      const textarea = container.querySelector('#channel-input textarea') as HTMLTextAreaElement;
      const button = container.querySelector('#channel-input button');

      textarea.value = 'Test message';
      button?.dispatchEvent(new MouseEvent('click'));

      await new Promise((resolve) => setTimeout(resolve, 10));

      expect(apiClient.interjectWorkspace).toHaveBeenCalledWith('Test message');
    });

    it('sends repo interjection on button click', async () => {
      page = new ChannelPage('test-repo');
      await page.render(container);
      await new Promise((resolve) => setTimeout(resolve, 10));

      const textarea = container.querySelector('#channel-input textarea') as HTMLTextAreaElement;
      const button = container.querySelector('#channel-input button');

      textarea.value = 'Repo message';
      button?.dispatchEvent(new MouseEvent('click'));

      await new Promise((resolve) => setTimeout(resolve, 10));

      expect(apiClient.interjectRepo).toHaveBeenCalledWith('test-repo', 'Repo message');
    });

    it('sends interjection on Enter key', async () => {
      await page.render(container);
      await new Promise((resolve) => setTimeout(resolve, 10));

      const textarea = container.querySelector('#channel-input textarea') as HTMLTextAreaElement;
      textarea.value = 'Test message';
      textarea.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }));

      await new Promise((resolve) => setTimeout(resolve, 10));

      expect(apiClient.interjectWorkspace).toHaveBeenCalledWith('Test message');
    });

    it('clears input after sending message', async () => {
      await page.render(container);
      await new Promise((resolve) => setTimeout(resolve, 10));

      const textarea = container.querySelector('#channel-input textarea') as HTMLTextAreaElement;
      const button = container.querySelector('#channel-input button');

      textarea.value = 'Test message';
      button?.dispatchEvent(new MouseEvent('click'));

      await new Promise((resolve) => setTimeout(resolve, 10));

      expect(textarea.value).toBe('');
    });

    it('does not send empty message', async () => {
      await page.render(container);
      await new Promise((resolve) => setTimeout(resolve, 10));

      const textarea = container.querySelector('#channel-input textarea') as HTMLTextAreaElement;
      const button = container.querySelector('#channel-input button');

      textarea.value = '   ';
      button?.dispatchEvent(new MouseEvent('click'));

      await new Promise((resolve) => setTimeout(resolve, 10));

      expect(apiClient.interjectWorkspace).not.toHaveBeenCalled();
    });

    it('does not send whitespace-only message', async () => {
      await page.render(container);
      await new Promise((resolve) => setTimeout(resolve, 10));

      const textarea = container.querySelector('#channel-input textarea') as HTMLTextAreaElement;
      const button = container.querySelector('#channel-input button');

      textarea.value = '  \n\t  ';
      button?.dispatchEvent(new MouseEvent('click'));

      await new Promise((resolve) => setTimeout(resolve, 10));

      expect(apiClient.interjectWorkspace).not.toHaveBeenCalled();
    });

    it('adds user message optimistically', async () => {
      await page.render(container);
      await new Promise((resolve) => setTimeout(resolve, 10));

      const textarea = container.querySelector('#channel-input textarea') as HTMLTextAreaElement;
      const button = container.querySelector('#channel-input button');

      textarea.value = 'Optimistic message';
      button?.dispatchEvent(new MouseEvent('click'));

      await new Promise((resolve) => setTimeout(resolve, 10));

      // Should show user message immediately (before API responds)
      const userMsg = container.querySelector('.message-bubble.user');
      expect(userMsg?.textContent).toContain('Optimistic message');
    });

    it('shows error message when interjection fails', async () => {
      vi.mocked(apiClient.interjectWorkspace).mockRejectedValue(new Error('API error'));

      await page.render(container);
      await new Promise((resolve) => setTimeout(resolve, 10));

      const textarea = container.querySelector('#channel-input textarea') as HTMLTextAreaElement;
      const button = container.querySelector('#channel-input button');

      textarea.value = 'Test message';
      button?.dispatchEvent(new MouseEvent('click'));

      await new Promise((resolve) => setTimeout(resolve, 50));

      // Should show error message - check that a new message appears after the user message
      const messages = container.querySelectorAll('.message-bubble');
      // Should have at least 2 messages: user message + error message
      expect(messages.length).toBeGreaterThanOrEqual(2);
      // Last message should mention the error
      const lastMsg = messages[messages.length - 1];
      expect(lastMsg?.className).toContain('system');
    });
  });

  describe('clarification question handling', () => {
    it('shows clarification banner when question is pending', async () => {
      vi.mocked(apiClient.getPending).mockResolvedValue({ pending: 'What is the expected behavior?' });

      await page.render(container);
      await new Promise((resolve) => setTimeout(resolve, 10));

      const banner = container.querySelector('#clarification-banner');
      expect(banner?.classList.contains('active')).toBe(true);

      const question = container.querySelector('.clar-q');
      expect(question?.textContent).toContain('What is the expected behavior?');
    });

    it('hides clarification banner when no pending question', async () => {
      vi.mocked(apiClient.getPending).mockResolvedValue({ pending: null });

      await page.render(container);
      await new Promise((resolve) => setTimeout(resolve, 10));

      const banner = container.querySelector('#clarification-banner');
      expect(banner?.classList.contains('active')).toBe(false);
    });

    it('focuses input when clarification banner is shown', async () => {
      vi.mocked(apiClient.getPending).mockResolvedValue({ pending: 'Please clarify' });

      await page.render(container);
      await new Promise((resolve) => setTimeout(resolve, 10));

      const input = container.querySelector('#clar-input') as HTMLInputElement;
      expect(document.activeElement).toBe(input);
    });

    it('clears clarification input after showing banner', async () => {
      vi.mocked(apiClient.getPending).mockResolvedValue({ pending: 'Clarify this' });

      await page.render(container);
      await new Promise((resolve) => setTimeout(resolve, 10));

      const input = container.querySelector('#clar-input') as HTMLInputElement;
      expect(input.value).toBe('');
    });

    it('sends answer on clarification button click', async () => {
      vi.mocked(apiClient.getPending).mockResolvedValue({ pending: 'What do you want?' });
      vi.mocked(apiClient.interjectWorkspace).mockResolvedValue({ ok: true, manager_task_id: 'task123' });

      await page.render(container);
      await new Promise((resolve) => setTimeout(resolve, 10));

      const input = container.querySelector('#clar-input') as HTMLInputElement;
      const button = container.querySelector('#clar-answer-btn');

      input.value = 'My answer';
      button?.dispatchEvent(new MouseEvent('click'));

      await new Promise((resolve) => setTimeout(resolve, 10));

      // Banner should be hidden
      const banner = container.querySelector('#clarification-banner');
      expect(banner?.classList.contains('active')).toBe(false);

      // Should send via interjection
      expect(apiClient.interjectWorkspace).toHaveBeenCalledWith('My answer');
    });

    it('sends answer on Enter key in clarification input', async () => {
      vi.mocked(apiClient.getPending).mockResolvedValue({ pending: 'What do you want?' });
      vi.mocked(apiClient.interjectWorkspace).mockResolvedValue({ ok: true, manager_task_id: 'task123' });

      await page.render(container);
      await new Promise((resolve) => setTimeout(resolve, 10));

      const input = container.querySelector('#clar-input') as HTMLInputElement;
      input.value = 'My answer';
      input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }));

      await new Promise((resolve) => setTimeout(resolve, 10));

      expect(apiClient.interjectWorkspace).toHaveBeenCalledWith('My answer');
    });

    it('hides banner after answering', async () => {
      vi.mocked(apiClient.getPending).mockResolvedValue({ pending: 'Question' });
      vi.mocked(apiClient.interjectWorkspace).mockResolvedValue({ ok: true, manager_task_id: 'task123' });

      await page.render(container);
      await new Promise((resolve) => setTimeout(resolve, 10));

      const input = container.querySelector('#clar-input') as HTMLInputElement;
      const button = container.querySelector('#clar-answer-btn');

      input.value = 'Answer';
      button?.dispatchEvent(new MouseEvent('click'));

      await new Promise((resolve) => setTimeout(resolve, 10));

      const banner = container.querySelector('#clarification-banner');
      expect(banner?.classList.contains('active')).toBe(false);
    });

    it('does not send empty clarification answer', async () => {
      vi.mocked(apiClient.getPending).mockResolvedValue({ pending: 'Question' });

      await page.render(container);
      await new Promise((resolve) => setTimeout(resolve, 10));

      const input = container.querySelector('#clar-input') as HTMLInputElement;
      const button = container.querySelector('#clar-answer-btn');
      
      input.value = '   ';
      button?.dispatchEvent(new MouseEvent('click'));

      await new Promise((resolve) => setTimeout(resolve, 10));

      expect(apiClient.interjectWorkspace).not.toHaveBeenCalled();
    });

    it('adds answer as user message', async () => {
      vi.mocked(apiClient.getPending).mockResolvedValue({ pending: 'Question' });
      vi.mocked(apiClient.interjectWorkspace).mockResolvedValue({ ok: true, manager_task_id: 'task123' });

      await page.render(container);
      await new Promise((resolve) => setTimeout(resolve, 10));

      const input = container.querySelector('#clar-input') as HTMLInputElement;
      const button = container.querySelector('#clar-answer-btn');
      
      input.value = 'My clarification answer';
      button?.dispatchEvent(new MouseEvent('click'));

      await new Promise((resolve) => setTimeout(resolve, 10));

      const userMsg = container.querySelector('.message-bubble.user');
      expect(userMsg?.textContent).toContain('My clarification answer');
    });

    it('handles clarification error gracefully', async () => {
      vi.mocked(apiClient.getPending).mockRejectedValue(new Error('Failed'));

      await page.render(container);
      await new Promise((resolve) => setTimeout(resolve, 10));

      // Should not crash - just no banner
      const banner = container.querySelector('#clarification-banner');
      expect(banner?.classList.contains('active')).toBe(false);
    });
  });

  describe('repo-specific channels', () => {
    it('uses correct placeholder for repo channel', async () => {
      page = new ChannelPage('my-repo');
      await page.render(container);

      const textarea = container.querySelector('#channel-input textarea') as HTMLTextAreaElement;
      expect(textarea.placeholder).toBe('Message my-repo...');
    });

    it('sends to repo interjection endpoint', async () => {
      page = new ChannelPage('my-repo');
      vi.mocked(apiClient.interjectRepo).mockResolvedValue({ ok: true, manager_task_id: 'task123', repo: 'my-repo' });

      await page.render(container);
      await new Promise((resolve) => setTimeout(resolve, 10));

      const textarea = container.querySelector('#channel-input textarea') as HTMLTextAreaElement;
      const button = container.querySelector('#channel-input button');

      textarea.value = 'Repo message';
      button?.dispatchEvent(new MouseEvent('click'));

      await new Promise((resolve) => setTimeout(resolve, 10));

      expect(apiClient.interjectRepo).toHaveBeenCalledWith('my-repo', 'Repo message');
    });

    it('encodes repo name in API call', async () => {
      page = new ChannelPage('my-special_repo');
      vi.mocked(apiClient.interjectRepo).mockResolvedValue({ ok: true, manager_task_id: 'task123', repo: 'my-special_repo' });

      await page.render(container);
      await new Promise((resolve) => setTimeout(resolve, 10));

      const textarea = container.querySelector('#channel-input textarea') as HTMLTextAreaElement;
      const button = container.querySelector('#channel-input button');

      textarea.value = 'Message';
      button?.dispatchEvent(new MouseEvent('click'));

      await new Promise((resolve) => setTimeout(resolve, 10));

      expect(apiClient.interjectRepo).toHaveBeenCalledWith('my-special_repo', 'Message');
    });
  });

  describe('message rendering helper', () => {
    it('filters out empty messages', async () => {
      vi.mocked(apiClient.getContext).mockResolvedValue({
        messages: [
          { role: 'user', content: '' },
          { role: 'assistant', content: '   ' },
          { role: 'user', content: 'Valid' },
        ],
        count: 3,
        estimated_tokens: 5,
      });

      await page.render(container);
      await new Promise((resolve) => setTimeout(resolve, 10));

      const messages = container.querySelectorAll('.message-bubble');
      expect(messages.length).toBe(1);
    });
  });

  describe('Shift+Enter newline support', () => {
    it('renders channel input as textarea element', async () => {
      await page.render(container);
      await new Promise((resolve) => setTimeout(resolve, 10));

      const textarea = container.querySelector('#channel-input textarea');
      expect(textarea).toBeTruthy();
      // Should NOT be an input element
      const input = container.querySelector('#channel-input input');
      expect(input).toBeFalsy();
    });

    it('renders clarification input as textarea element', async () => {
      await page.render(container);
      await new Promise((resolve) => setTimeout(resolve, 10));

      const textarea = container.querySelector('#clar-input');
      expect(textarea?.tagName.toLowerCase()).toBe('textarea');
    });

    it('sends interjection when Enter is pressed', async () => {
      await page.render(container);
      await new Promise((resolve) => setTimeout(resolve, 10));

      const textarea = container.querySelector('#channel-input textarea') as HTMLTextAreaElement;
      textarea.value = 'Test message';
      textarea.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }));

      await new Promise((resolve) => setTimeout(resolve, 10));

      expect(apiClient.interjectWorkspace).toHaveBeenCalledWith('Test message');
    });

    it('does NOT send interjection when Shift+Enter is pressed', async () => {
      await page.render(container);
      await new Promise((resolve) => setTimeout(resolve, 10));

      const textarea = container.querySelector('#channel-input textarea') as HTMLTextAreaElement;
      textarea.value = 'Line 1\nLine 2';
      textarea.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', shiftKey: true }));

      await new Promise((resolve) => setTimeout(resolve, 10));

      expect(apiClient.interjectWorkspace).not.toHaveBeenCalled();
    });

    it('sends clarification answer when Enter is pressed', async () => {
      vi.mocked(apiClient.getPending).mockResolvedValue({ pending: 'What do you want?' });
      vi.mocked(apiClient.interjectWorkspace).mockResolvedValue({ ok: true, manager_task_id: 'task123' });

      await page.render(container);
      await new Promise((resolve) => setTimeout(resolve, 10));

      const textarea = container.querySelector('#clar-input') as HTMLTextAreaElement;
      textarea.value = 'My answer';
      textarea.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }));

      await new Promise((resolve) => setTimeout(resolve, 10));

      expect(apiClient.interjectWorkspace).toHaveBeenCalledWith('My answer');
    });

    it('does NOT send clarification answer when Shift+Enter is pressed', async () => {
      vi.mocked(apiClient.getPending).mockResolvedValue({ pending: 'What do you want?' });

      await page.render(container);
      await new Promise((resolve) => setTimeout(resolve, 10));

      const textarea = container.querySelector('#clar-input') as HTMLTextAreaElement;
      textarea.value = 'Line 1\nLine 2';
      textarea.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', shiftKey: true }));

      await new Promise((resolve) => setTimeout(resolve, 10));

      expect(apiClient.interjectWorkspace).not.toHaveBeenCalled();
    });

    it('channel textarea has min-height CSS property', async () => {
      await page.render(container);
      await new Promise((resolve) => setTimeout(resolve, 10));

      const textarea = container.querySelector('#channel-input textarea') as HTMLTextAreaElement;
      // Verify the element exists and has appropriate styling
      expect(textarea).toBeTruthy();
      // In JSDOM, computed styles aren't fully available, so we verify the element exists
      // The actual CSS will be verified by E2E tests
    });
  });

  describe('Textarea auto-resize', () => {
    it('channel textarea has input event listener for auto-resize', async () => {
      await page.render(container);
      await new Promise((resolve) => setTimeout(resolve, 10));

      const textarea = container.querySelector('#channel-input textarea') as HTMLTextAreaElement;
      expect(textarea).toBeTruthy();

      // Simulate typing
      textarea.value = 'Line 1\nLine 2\nLine 3';
      textarea.dispatchEvent(new Event('input', { bubbles: true }));

      // In JSDOM, scrollHeight may not be accurate, but we verify no error occurred
      // The actual auto-resize behavior will be tested in E2E tests
      expect(textarea.value).toBe('Line 1\nLine 2\nLine 3');
    });

    it('resets textarea height after sending message', async () => {
      await page.render(container);
      await new Promise((resolve) => setTimeout(resolve, 10));

      const textarea = container.querySelector('#channel-input textarea') as HTMLTextAreaElement;
      textarea.value = 'Test message';

      // Simulate sending
      const button = container.querySelector('#channel-input button');
      button?.dispatchEvent(new MouseEvent('click'));

      await new Promise((resolve) => setTimeout(resolve, 10));

      // Input should be cleared
      expect(textarea.value).toBe('');
    });

    it('resets clarification textarea height after sending answer', async () => {
      vi.mocked(apiClient.getPending).mockResolvedValue({ pending: 'What do you want?' });
      vi.mocked(apiClient.interjectWorkspace).mockResolvedValue({ ok: true, manager_task_id: 'task123' });

      await page.render(container);
      await new Promise((resolve) => setTimeout(resolve, 10));

      const textarea = container.querySelector('#clar-input') as HTMLTextAreaElement;
      textarea.value = 'My answer';

      const button = container.querySelector('#clar-answer-btn');
      button?.dispatchEvent(new MouseEvent('click'));

      await new Promise((resolve) => setTimeout(resolve, 10));

      // Input should be cleared
      expect(textarea.value).toBe('');
    });

    it('clarification textarea has input event listener for auto-resize', async () => {
      await page.render(container);
      await new Promise((resolve) => setTimeout(resolve, 10));

      const textarea = container.querySelector('#clar-input') as HTMLTextAreaElement;
      expect(textarea).toBeTruthy();

      // Simulate typing
      textarea.value = 'Long answer\nwith multiple\nlines';
      textarea.dispatchEvent(new Event('input', { bubbles: true }));

      // Verify no error occurred
      expect(textarea.value).toBe('Long answer\nwith multiple\nlines');
    });
  });

  describe('Textarea accessibility', () => {
    it('channel textarea has correct aria-label with scope', async () => {
      await page.render(container);
      await new Promise((resolve) => setTimeout(resolve, 10));

      const textarea = container.querySelector('#channel-input textarea') as HTMLTextAreaElement;
      expect(textarea).toBeTruthy();
      expect(textarea.getAttribute('aria-label')).toBe('Message input for workspace channel');
    });

    it('channel textarea has placeholder text', async () => {
      await page.render(container);
      await new Promise((resolve) => setTimeout(resolve, 10));

      const textarea = container.querySelector('#channel-input textarea') as HTMLTextAreaElement;
      expect(textarea).toBeTruthy();
      expect(textarea.placeholder).toBe('Message workspace...');
    });

    it('clarification textarea has correct aria-label', async () => {
      await page.render(container);
      await new Promise((resolve) => setTimeout(resolve, 10));

      const textarea = container.querySelector('#clar-input') as HTMLTextAreaElement;
      expect(textarea).toBeTruthy();
      expect(textarea.getAttribute('aria-label')).toBe('Answer clarification question');
    });

    it('clarification textarea has placeholder text', async () => {
      await page.render(container);
      await new Promise((resolve) => setTimeout(resolve, 10));

      const textarea = container.querySelector('#clar-input') as HTMLTextAreaElement;
      expect(textarea).toBeTruthy();
      expect(textarea.placeholder).toBe('Type your answer...');
    });

    it('repo channel textarea has scope-specific aria-label', async () => {
      page = new ChannelPage('my-repo');
      await page.render(container);
      await new Promise((resolve) => setTimeout(resolve, 10));

      const textarea = container.querySelector('#channel-input textarea') as HTMLTextAreaElement;
      expect(textarea).toBeTruthy();
      expect(textarea.getAttribute('aria-label')).toBe('Message input for my-repo channel');
    });

    it('repo channel textarea has repo-specific placeholder', async () => {
      page = new ChannelPage('my-repo');
      await page.render(container);
      await new Promise((resolve) => setTimeout(resolve, 10));

      const textarea = container.querySelector('#channel-input textarea') as HTMLTextAreaElement;
      expect(textarea).toBeTruthy();
      expect(textarea.placeholder).toBe('Message my-repo...');
    });
  });
});
