/**
 * Conversation Component Unit Tests
 * 
 * Tests for the Conversation component including:
 * - Message rendering
 * - Interjection sending
 * - Clarification handling
 * - Streaming support
 * - Error states
 */

import { Conversation } from '../../../src/components/Conversation';
import * as api from '../../../src/api';
import * as utils from '../../../src/utils';
import { vi, describe, it, expect, beforeEach, afterEach } from 'vitest';

// Mock API
vi.mock('../../../src/api', () => ({
  getContext: vi.fn(),
  interjectTask: vi.fn(),
  interjectRepo: vi.fn(),
  interjectWorkspace: vi.fn(),
  answerTask: vi.fn(),
}));

// Mock utils
vi.mock('../../../src/utils', () => ({
  renderMarkdown: vi.fn((text) => text),
  escapeHtml: vi.fn((text) => text),
  ts: vi.fn(),
}));

// Mock data
const mockMessages = [
  { role: 'user', content: 'Hello' },
  { role: 'assistant', content: 'Hi there!' },
  { role: 'system', content: 'System message' },
];

describe('Conversation', () => {
  let container: HTMLElement;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    vi.clearAllMocks();
  });

  afterEach(() => {
    document.body.removeChild(container);
  });

  describe('constructor()', () => {
    it('stores options', () => {
      const conv = new Conversation({ scope: 'workspace' });
      expect(conv).toBeDefined();
    });

    it('accepts taskId for task-specific conversation', () => {
      const conv = new Conversation({ scope: 'test-repo', taskId: 'task-123' });
      expect(conv).toBeDefined();
    });

    it('accepts onInterjection callback', () => {
      const onInterjection = vi.fn();
      const conv = new Conversation({ scope: 'workspace', onInterjection });
      expect(conv).toBeDefined();
    });
  });

  describe('render()', () => {
    it('creates conversation element', () => {
      const conv = new Conversation({ scope: 'workspace' });
      const element = conv.render();

      expect(element.id).toBe('conversation');
    });

    it('displays workspace header', () => {
      const conv = new Conversation({ scope: 'workspace' });
      container.appendChild(conv.render());

      const header = container.querySelector('#conversation-header');
      expect(header?.textContent).toContain('Channel: workspace');
    });

    it('displays repo header for repo conversations', () => {
      const conv = new Conversation({ scope: 'my-repo' });
      container.appendChild(conv.render());

      const header = container.querySelector('#conversation-header');
      expect(header?.textContent).toContain('Channel: my-repo');
    });

    it('displays task conversation header', () => {
      const conv = new Conversation({ scope: 'my-repo', taskId: 'task-123' });
      container.appendChild(conv.render());

      const header = container.querySelector('#conversation-header');
      expect(header?.textContent).toContain('Task Conversation');
    });

    it('creates conversation log', () => {
      const conv = new Conversation({ scope: 'workspace' });
      container.appendChild(conv.render());

      const log = container.querySelector('#conversation-log');
      expect(log).toBeDefined();
    });

    it('creates input field', () => {
      const conv = new Conversation({ scope: 'workspace' });
      container.appendChild(conv.render());

      const inputContainer = container.querySelector('#conversation-input');
      expect(inputContainer).toBeDefined();

      const input = inputContainer?.querySelector('input');
      const button = inputContainer?.querySelector('button');

      expect(input).toBeDefined();
      expect(button).toBeDefined();
    });

    it('creates hidden clarification banner', () => {
      const conv = new Conversation({ scope: 'workspace' });
      container.appendChild(conv.render());

      const banner = container.querySelector('#clarification-banner');
      expect(banner).toBeDefined();
      expect(banner?.getAttribute('style')).toContain('display:none');
    });

    it('creates hidden inference bar', () => {
      const conv = new Conversation({ scope: 'workspace' });
      container.appendChild(conv.render());

      const inferenceBar = container.querySelector('#inference-bar');
      expect(inferenceBar).toBeDefined();
      expect(inferenceBar?.getAttribute('style')).toContain('display:none');
    });

    it('loads conversation on render', async () => {
      vi.mocked(api.getContext).mockResolvedValue({ messages: [], count: 0, estimated_tokens: 0 });

      const conv = new Conversation({ scope: 'workspace' });
      container.appendChild(conv.render());

      // Wait for async
      await new Promise(resolve => setTimeout(resolve, 50));

      expect(api.getContext).toHaveBeenCalledWith('workspace');
    });
  });

  describe('loadConversation()', () => {
    it('displays empty state when no messages', async () => {
      vi.mocked(api.getContext).mockResolvedValue({ messages: [], count: 0, estimated_tokens: 0 });

      const conv = new Conversation({ scope: 'workspace' });
      container.appendChild(conv.render());

      await new Promise(resolve => setTimeout(resolve, 50));

      const log = container.querySelector('#conversation-log');
      expect(log?.textContent).toContain('No conversation yet');
    });

    it('displays messages when loaded', async () => {
      vi.mocked(api.getContext).mockResolvedValue({
        messages: mockMessages,
        count: 3,
        estimated_tokens: 100,
      });
      vi.mocked(utils.renderMarkdown).mockImplementation((text) => text);
      vi.mocked(utils.escapeHtml).mockImplementation((text) => text);

      const conv = new Conversation({ scope: 'workspace' });
      container.appendChild(conv.render());

      await new Promise(resolve => setTimeout(resolve, 50));

      const log = container.querySelector('#conversation-log');
      expect(log?.querySelectorAll('.message-bubble').length).toBe(3);
    });

    it('renders user messages with user class', async () => {
      vi.mocked(api.getContext).mockResolvedValue({
        messages: [{ role: 'user', content: 'Hello' }],
        count: 1,
        estimated_tokens: 50,
      });
      vi.mocked(utils.renderMarkdown).mockImplementation((text) => text);
      vi.mocked(utils.escapeHtml).mockImplementation((text) => text);

      const conv = new Conversation({ scope: 'workspace' });
      container.appendChild(conv.render());

      await new Promise(resolve => setTimeout(resolve, 50));

      const userBubble = container.querySelector('.message-bubble.user');
      expect(userBubble).toBeDefined();
    });

    it('renders assistant messages with assistant class', async () => {
      vi.mocked(api.getContext).mockResolvedValue({
        messages: [{ role: 'assistant', content: 'Hi!' }],
        count: 1,
        estimated_tokens: 50,
      });
      vi.mocked(utils.renderMarkdown).mockImplementation((text) => text);
      vi.mocked(utils.escapeHtml).mockImplementation((text) => text);

      const conv = new Conversation({ scope: 'workspace' });
      container.appendChild(conv.render());

      await new Promise(resolve => setTimeout(resolve, 50));

      const assistantBubble = container.querySelector('.message-bubble.assistant');
      expect(assistantBubble).toBeDefined();
    });

    it('renders system messages with system class', async () => {
      vi.mocked(api.getContext).mockResolvedValue({
        messages: [{ role: 'system', content: 'System msg' }],
        count: 1,
        estimated_tokens: 50,
      });
      vi.mocked(utils.renderMarkdown).mockImplementation((text) => text);
      vi.mocked(utils.escapeHtml).mockImplementation((text) => text);

      const conv = new Conversation({ scope: 'workspace' });
      container.appendChild(conv.render());

      await new Promise(resolve => setTimeout(resolve, 50));

      const systemBubble = container.querySelector('.message-bubble.system');
      expect(systemBubble).toBeDefined();
    });

    it('renders tool_call messages with preformatted text', async () => {
      vi.mocked(api.getContext).mockResolvedValue({
        messages: [{ role: 'tool_call', content: 'code here' }],
        count: 1,
        estimated_tokens: 50,
      });
      vi.mocked(utils.renderMarkdown).mockImplementation((text) => text);
      vi.mocked(utils.escapeHtml).mockImplementation((text) => text);

      const conv = new Conversation({ scope: 'workspace' });
      container.appendChild(conv.render());

      await new Promise(resolve => setTimeout(resolve, 50));

      const toolBubble = container.querySelector('.message-bubble');
      expect(toolBubble?.querySelector('pre')).toBeDefined();
    });

    it('skips empty messages', async () => {
      vi.mocked(api.getContext).mockResolvedValue({
        messages: [{ role: 'user', content: 'Hello' }, { role: 'user', content: '' }],
        count: 2,
        estimated_tokens: 50,
      });
      vi.mocked(utils.renderMarkdown).mockImplementation((text) => text);
      vi.mocked(utils.escapeHtml).mockImplementation((text) => text);

      const conv = new Conversation({ scope: 'workspace' });
      container.appendChild(conv.render());

      await new Promise(resolve => setTimeout(resolve, 50));

      const log = container.querySelector('#conversation-log');
      expect(log?.querySelectorAll('.message-bubble').length).toBe(1);
    });

    it('handles load error gracefully', async () => {
      vi.mocked(api.getContext).mockRejectedValue(new Error('Failed'));
      const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {});

      const conv = new Conversation({ scope: 'workspace' });
      container.appendChild(conv.render());

      await new Promise(resolve => setTimeout(resolve, 50));

      const log = container.querySelector('#conversation-log');
      expect(log?.textContent).toContain('Failed to load conversation');
      expect(consoleSpy).toHaveBeenCalled();
    });

    it('fetches task context when taskId provided', async () => {
      vi.mocked(api.getContext).mockResolvedValue({ messages: [], count: 0, estimated_tokens: 0 });

      const conv = new Conversation({ scope: 'my-repo', taskId: 'task-123' });
      container.appendChild(conv.render());

      await new Promise(resolve => setTimeout(resolve, 50));

      // Task ID provided, should fetch task context (undefined scope)
      expect(api.getContext).toHaveBeenCalledWith(undefined);
    });
  });

  describe('sendInterjection()', () => {
    it('sends message and clears input', async () => {
      vi.mocked(api.getContext).mockResolvedValue({ messages: [], count: 0, estimated_tokens: 0 });
      vi.mocked(api.interjectWorkspace).mockResolvedValue(undefined);

      const conv = new Conversation({ scope: 'workspace' });
      container.appendChild(conv.render());

      await new Promise(resolve => setTimeout(resolve, 50));

      const input = container.querySelector('#conversation-input input') as HTMLInputElement;
      const button = container.querySelector('#conversation-input button') as HTMLButtonElement;

      input.value = 'Test message';
      button.click();

      await new Promise(resolve => setTimeout(resolve, 50));

      expect(api.interjectWorkspace).toHaveBeenCalledWith('Test message');
      expect(input.value).toBe('');
    });

    it('does not send empty message', async () => {
      vi.mocked(api.getContext).mockResolvedValue({ messages: [], count: 0, estimated_tokens: 0 });

      const conv = new Conversation({ scope: 'workspace' });
      container.appendChild(conv.render());

      await new Promise(resolve => setTimeout(resolve, 50));

      const button = container.querySelector('#conversation-input button') as HTMLButtonElement;
      button.click();

      await new Promise(resolve => setTimeout(resolve, 50));

      expect(api.interjectWorkspace).not.toHaveBeenCalled();
    });

    it('sends to task interjection when taskId provided', async () => {
      vi.mocked(api.getContext).mockResolvedValue({ messages: [], count: 0, estimated_tokens: 0 });
      vi.mocked(api.interjectTask).mockResolvedValue(undefined);

      const conv = new Conversation({ scope: 'my-repo', taskId: 'task-123' });
      container.appendChild(conv.render());

      await new Promise(resolve => setTimeout(resolve, 50));

      const input = container.querySelector('#conversation-input input') as HTMLInputElement;
      const button = container.querySelector('#conversation-input button') as HTMLButtonElement;

      input.value = 'Task message';
      button.click();

      await new Promise(resolve => setTimeout(resolve, 50));

      expect(api.interjectTask).toHaveBeenCalledWith('task-123', 'Task message');
    });

    it('sends to repo interjection for repo scope', async () => {
      vi.mocked(api.getContext).mockResolvedValue({ messages: [], count: 0, estimated_tokens: 0 });
      vi.mocked(api.interjectRepo).mockResolvedValue(undefined);

      const conv = new Conversation({ scope: 'my-repo' });
      container.appendChild(conv.render());

      await new Promise(resolve => setTimeout(resolve, 50));

      const input = container.querySelector('#conversation-input input') as HTMLInputElement;
      const button = container.querySelector('#conversation-input button') as HTMLButtonElement;

      input.value = 'Repo message';
      button.click();

      await new Promise(resolve => setTimeout(resolve, 50));

      expect(api.interjectRepo).toHaveBeenCalledWith('my-repo', 'Repo message');
    });

    it('adds user message to conversation immediately', async () => {
      vi.mocked(api.getContext).mockResolvedValue({ messages: [], count: 0, estimated_tokens: 0 });
      vi.mocked(api.interjectWorkspace).mockResolvedValue(undefined);
      vi.mocked(utils.renderMarkdown).mockImplementation((text) => text);
      vi.mocked(utils.escapeHtml).mockImplementation((text) => text);

      const conv = new Conversation({ scope: 'workspace' });
      container.appendChild(conv.render());

      await new Promise(resolve => setTimeout(resolve, 50));

      const input = container.querySelector('#conversation-input input') as HTMLInputElement;
      const button = container.querySelector('#conversation-input button') as HTMLButtonElement;

      input.value = 'Optimistic message';
      button.click();

      await new Promise(resolve => setTimeout(resolve, 50));

      const userBubble = container.querySelector('.message-bubble.user');
      expect(userBubble?.textContent).toContain('Optimistic message');
    });

    it('shows error message on failure', async () => {
      vi.mocked(api.getContext).mockResolvedValue({ messages: [], count: 0, estimated_tokens: 0 });
      vi.mocked(api.interjectWorkspace).mockRejectedValue(new Error('Network error'));
      vi.mocked(utils.renderMarkdown).mockImplementation((text) => text);
      vi.mocked(utils.escapeHtml).mockImplementation((text) => text);
      const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {});

      const conv = new Conversation({ scope: 'workspace' });
      container.appendChild(conv.render());

      await new Promise(resolve => setTimeout(resolve, 50));

      const input = container.querySelector('#conversation-input input') as HTMLInputElement;
      const button = container.querySelector('#conversation-input button') as HTMLButtonElement;

      input.value = 'Test message';
      button.click();

      await new Promise(resolve => setTimeout(resolve, 50));

      const systemBubble = container.querySelector('.message-bubble.system');
      expect(systemBubble?.textContent).toContain('Error');
      expect(consoleSpy).toHaveBeenCalled();
    });

    it('sends on Enter key press', async () => {
      vi.mocked(api.getContext).mockResolvedValue({ messages: [], count: 0, estimated_tokens: 0 });
      vi.mocked(api.interjectWorkspace).mockResolvedValue(undefined);

      const conv = new Conversation({ scope: 'workspace' });
      container.appendChild(conv.render());

      await new Promise(resolve => setTimeout(resolve, 50));

      const input = container.querySelector('#conversation-input input') as HTMLInputElement;
      input.value = 'Enter message';
      input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }));

      await new Promise(resolve => setTimeout(resolve, 50));

      expect(api.interjectWorkspace).toHaveBeenCalledWith('Enter message');
    });
  });

  describe('clarification handling', () => {
    it('shows clarification banner with question', () => {
      const conv = new Conversation({ scope: 'workspace', taskId: 'task-123' });
      container.appendChild(conv.render());

      conv.showClarification('What do you want?');

      const banner = container.querySelector('#clarification-banner');
      expect(banner?.getAttribute('style')).not.toContain('display:none');

      const question = container.querySelector('.clar-q');
      expect(question?.textContent).toContain('What do you want?');
    });

    it('hides clarification banner', () => {
      const conv = new Conversation({ scope: 'workspace', taskId: 'task-123' });
      container.appendChild(conv.render());

      conv.showClarification('Question?');
      conv.hideClarification();

      const banner = container.querySelector('#clarification-banner');
      expect(banner?.getAttribute('style')).toMatch(/display:\s*none/);
    });

    it('sends clarification answer', async () => {
      vi.mocked(api.getContext).mockResolvedValue({ messages: [], count: 0, estimated_tokens: 0 });
      vi.mocked(api.answerTask).mockResolvedValue(undefined);
      vi.mocked(utils.renderMarkdown).mockImplementation((text) => text);
      vi.mocked(utils.escapeHtml).mockImplementation((text) => text);

      const conv = new Conversation({ scope: 'workspace', taskId: 'task-123' });
      container.appendChild(conv.render());

      await new Promise(resolve => setTimeout(resolve, 50));

      conv.showClarification('Question?');

      const input = container.querySelector('#clar-input') as HTMLInputElement;
      const button = container.querySelector('#clar-answer-btn') as HTMLButtonElement;

      input.value = 'My answer';
      button.click();

      await new Promise(resolve => setTimeout(resolve, 50));

      expect(api.answerTask).toHaveBeenCalledWith('task-123', 'My answer');

      const banner = container.querySelector('#clarification-banner');
      expect(banner?.getAttribute('style')).toMatch(/display:\s*none/);
    });

    it('does not send empty clarification answer', async () => {
      vi.mocked(api.getContext).mockResolvedValue({ messages: [], count: 0, estimated_tokens: 0 });

      const conv = new Conversation({ scope: 'workspace', taskId: 'task-123' });
      container.appendChild(conv.render());

      await new Promise(resolve => setTimeout(resolve, 50));

      conv.showClarification('Question?');

      const button = container.querySelector('#clar-answer-btn') as HTMLButtonElement;
      button.click();

      await new Promise(resolve => setTimeout(resolve, 50));

      expect(api.answerTask).not.toHaveBeenCalled();
    });

    it('sends clarification on Enter key', async () => {
      vi.mocked(api.getContext).mockResolvedValue({ messages: [], count: 0, estimated_tokens: 0 });
      vi.mocked(api.answerTask).mockResolvedValue(undefined);
      vi.mocked(utils.renderMarkdown).mockImplementation((text) => text);
      vi.mocked(utils.escapeHtml).mockImplementation((text) => text);

      const conv = new Conversation({ scope: 'workspace', taskId: 'task-123' });
      container.appendChild(conv.render());

      await new Promise(resolve => setTimeout(resolve, 50));

      conv.showClarification('Question?');

      const input = container.querySelector('#clar-input') as HTMLInputElement;
      input.value = 'Enter answer';
      input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }));

      await new Promise(resolve => setTimeout(resolve, 50));

      expect(api.answerTask).toHaveBeenCalledWith('task-123', 'Enter answer');
    });

    it('focuses input when showing clarification', () => {
      const conv = new Conversation({ scope: 'workspace', taskId: 'task-123' });
      container.appendChild(conv.render());

      const input = container.querySelector('#clar-input') as HTMLInputElement;
      const focusSpy = vi.spyOn(input, 'focus');

      conv.showClarification('Question?');

      expect(focusSpy).toHaveBeenCalled();
    });

    it('clears input when showing clarification', () => {
      const conv = new Conversation({ scope: 'workspace', taskId: 'task-123' });
      container.appendChild(conv.render());

      conv.showClarification('Question?');

      const input = container.querySelector('#clar-input') as HTMLInputElement;
      expect(input.value).toBe('');
    });
  });

  describe('streaming support', () => {
    it('creates streaming row on first token', () => {
      vi.mocked(api.getContext).mockResolvedValue({ messages: [], count: 0, estimated_tokens: 0 });
      vi.mocked(utils.renderMarkdown).mockImplementation((text) => text);

      const conv = new Conversation({ scope: 'workspace' });
      container.appendChild(conv.render());

      conv.appendToken('Hello');

      const streamingRow = container.querySelector('.message-bubble.streaming');
      expect(streamingRow).toBeDefined();
    });

    it('appends tokens to streaming row', () => {
      vi.mocked(api.getContext).mockResolvedValue({ messages: [], count: 0, estimated_tokens: 0 });
      vi.mocked(utils.renderMarkdown).mockImplementation((text) => text);

      const conv = new Conversation({ scope: 'workspace' });
      container.appendChild(conv.render());

      conv.appendToken('Hello');
      conv.appendToken(' World');

      const contentEl = container.querySelector('.message-bubble.streaming .message-content');
      expect(contentEl?.getAttribute('data-raw')).toBe('Hello World');
    });

    it('creates thinking row on first thinking token', () => {
      vi.mocked(api.getContext).mockResolvedValue({ messages: [], count: 0, estimated_tokens: 0 });
      vi.mocked(utils.renderMarkdown).mockImplementation((text) => text);

      const conv = new Conversation({ scope: 'workspace' });
      container.appendChild(conv.render());

      conv.appendThinking('Thinking...');

      const thinkingRow = container.querySelector('.message-bubble.thinking');
      expect(thinkingRow).toBeDefined();
    });

    it('appends tokens to thinking row', () => {
      vi.mocked(api.getContext).mockResolvedValue({ messages: [], count: 0, estimated_tokens: 0 });
      vi.mocked(utils.renderMarkdown).mockImplementation((text) => text);

      const conv = new Conversation({ scope: 'workspace' });
      container.appendChild(conv.render());

      conv.appendThinking('Hmm');
      conv.appendThinking(' let me think');

      const contentEl = container.querySelector('.message-bubble.thinking .message-content');
      expect(contentEl?.getAttribute('data-raw')).toBe('Hmm let me think');
    });
  });

  describe('accessibility', () => {
    it('has proper structure for screen readers', () => {
      const conv = new Conversation({ scope: 'workspace' });
      container.appendChild(conv.render());

      const header = container.querySelector('#conversation-header');
      const log = container.querySelector('#conversation-log');
      const input = container.querySelector('#conversation-input input');

      expect(header).toBeDefined();
      expect(log).toBeDefined();
      expect(input).toBeDefined();
    });

    it('has input with placeholder', () => {
      const conv = new Conversation({ scope: 'workspace' });
      container.appendChild(conv.render());

      const input = container.querySelector('#conversation-input input') as HTMLInputElement;
      expect(input.placeholder).toBe('Message...');
    });

    it('has send button', () => {
      const conv = new Conversation({ scope: 'workspace' });
      container.appendChild(conv.render());

      const button = container.querySelector('#conversation-input button');
      expect(button?.textContent).toBe('Send');
    });
  });
});

describe('Conversation - Clarification Textarea', () => {
  let container: HTMLElement;

  beforeEach(() => {
    container = document.createElement('div');
    vi.mocked(api.getContext).mockResolvedValue({ messages: [], count: 0, estimated_tokens: 0 });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('uses textarea for clarification input', () => {
    const conv = new Conversation({ scope: 'workspace', taskId: 'task-001' });
    container.appendChild(conv.render());

    const clarInput = container.querySelector('#clar-input');
    expect(clarInput?.tagName).toBe('TEXTAREA');
  });

  it('has aria-label on clarification input', () => {
    const conv = new Conversation({ scope: 'workspace', taskId: 'task-001' });
    container.appendChild(conv.render());

    const clarInput = container.querySelector('#clar-input');
    expect(clarInput?.getAttribute('aria-label')).toBe('Answer clarification question');
  });

  it('has aria-label on clarification answer button', () => {
    const conv = new Conversation({ scope: 'workspace', taskId: 'task-001' });
    container.appendChild(conv.render());

    const clarBtn = container.querySelector('#clar-answer-btn');
    expect(clarBtn?.getAttribute('aria-label')).toBe('Submit clarification answer');
  });

  it('showClarification displays banner and focuses input', () => {
    const conv = new Conversation({ scope: 'workspace', taskId: 'task-001' });
    container.appendChild(conv.render());

    conv.showClarification('What do you mean?');

    const banner = container.querySelector('#clarification-banner');
    expect(banner?.getAttribute('style')).toContain('display: flex');

    const questionEl = container.querySelector('.clar-q');
    expect(questionEl?.textContent).toContain('What do you mean?');

    const clarInput = container.querySelector('#clar-input') as HTMLTextAreaElement;
    expect(clarInput.value).toBe('');
  });

  it('resets textarea height on showClarification', () => {
    const conv = new Conversation({ scope: 'workspace', taskId: 'task-001' });
    container.appendChild(conv.render());

    const clarInput = container.querySelector('#clar-input') as HTMLTextAreaElement;
    clarInput.style.height = '100px';

    conv.showClarification('Test question');
    expect(clarInput.style.height).toBe('auto');
  });

  it('hides clarification banner', () => {
    const conv = new Conversation({ scope: 'workspace', taskId: 'task-001' });
    container.appendChild(conv.render());

    conv.showClarification('Question?');
    conv.hideClarification();

    const banner = container.querySelector('#clarification-banner');
    expect(banner?.getAttribute('style')).toContain('display: none');
  });

  it('auto-resizes textarea on input event', () => {
    const conv = new Conversation({ scope: 'workspace', taskId: 'task-001' });
    container.appendChild(conv.render());

    const clarInput = container.querySelector('#clar-input') as HTMLTextAreaElement;
    clarInput.value = 'Some text\nwith\nnewlines';
    clarInput.style.height = 'auto';
    // Simulate scrollHeight (JSDOM doesn't compute real scrollHeight)
    Object.defineProperty(clarInput, 'scrollHeight', { value: 80, configurable: true });

    clarInput.dispatchEvent(new Event('input', { bubbles: true }));

    expect(clarInput.style.height).toBe('80px');
  });
});
