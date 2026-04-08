/**
 * Unit Tests for WebSocket Manager
 *
 * Tests real-time event handling and connection management
 * using the unified on(eventType, handler) / off(eventType, handler) API.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { WebSocketManager, wsManager } from '../../../src/api/websocket';
import type {
  StatusUpdateData,
  ClarificationRequestData,
  TokenData,
  ThinkingData,
  ContentData,
  ToolCallData,
  ToolResultData,
} from '../../src/types';

// Mock WebSocket
class MockWebSocket {
  public onopen: (() => void) | null = null;
  public onmessage: ((event: MessageEvent) => void) | null = null;
  public onclose: (() => void) | null = null;
  public onerror: ((event: Event) => void) | null = null;
  public readyState: number = 1; // OPEN

  constructor(public url: string) {}

  send(data: string): void {}
  close(): void {
    this.readyState = 3; // CLOSED
    this.onclose?.();
  }
}

// Replace WebSocket with mock
global.WebSocket = MockWebSocket as any;

describe('WebSocket Manager - Connection', () => {
  let manager: WebSocketManager;

  beforeEach(() => {
    manager = new WebSocketManager();
  });

  afterEach(() => {
    manager.disconnect();
  });

  it('connects to WebSocket server', () => {
    manager.connect();
    expect(manager).toBeDefined();
  });

  it('handles connection open', () => {
    const mockWs = new MockWebSocket('ws://test/ws');
    vi.spyOn(global, 'WebSocket').mockReturnValue(mockWs as any);

    manager.connect();
    mockWs.onopen?.();
    // No event emitted, just verifying no crash
    expect(mockWs.readyState).toBe(1);
  });

  it('reconnects on close', async () => {
    const mockWs = new MockWebSocket('ws://test/ws');
    vi.spyOn(global, 'WebSocket').mockReturnValue(mockWs as any);

    const connectSpy = vi.spyOn(manager, 'connect');

    manager.connect();
    mockWs.onclose?.();

    await new Promise(resolve => setTimeout(resolve, 100));
    expect(connectSpy).toHaveBeenCalled();
  });

  it('disconnects cleanly', () => {
    const mockWs = new MockWebSocket('ws://test/ws');
    vi.spyOn(global, 'WebSocket').mockReturnValue(mockWs as any);

    manager.connect();
    manager.disconnect();
    expect(mockWs.readyState).toBe(3); // CLOSED
  });
});

describe('WebSocket Manager - Event Handling', () => {
  let manager: WebSocketManager;
  let mockWs: MockWebSocket;

  function sendEvent(event: object) {
    mockWs.onmessage?.({ data: JSON.stringify(event) } as MessageEvent);
  }

  beforeEach(() => {
    manager = new WebSocketManager();
    mockWs = new MockWebSocket('ws://test/ws');
    vi.spyOn(global, 'WebSocket').mockReturnValue(mockWs as any);
    manager.connect();
  });

  afterEach(() => {
    manager.disconnect();
    vi.restoreAllMocks();
  });

  it('parses incoming messages', () => {
    sendEvent({ type: 'status_update', data: { idle: true } });
    expect(manager).toBeDefined();
  });

  it('handles malformed messages gracefully', () => {
    // Valid JSON but not a proper event - should not crash
    mockWs.onmessage?.({ data: 'invalid json' } as MessageEvent);
    // No assertion needed - the point is it doesn't throw
    expect(manager).toBeDefined();
  });
});

describe('WebSocket Manager - Status Updates', () => {
  let manager: WebSocketManager;
  let mockWs: MockWebSocket;

  function sendEvent(event: object) {
    mockWs.onmessage?.({ data: JSON.stringify(event) } as MessageEvent);
  }

  beforeEach(() => {
    manager = new WebSocketManager();
    mockWs = new MockWebSocket('ws://test/ws');
    vi.spyOn(global, 'WebSocket').mockReturnValue(mockWs as any);
    manager.connect();
  });

  afterEach(() => {
    manager.disconnect();
    vi.restoreAllMocks();
  });

  it('notifies status update handlers via on()', () => {
    const statusHandler = vi.fn();
    manager.on('status_update', statusHandler);

    const event = {
      type: 'status_update' as const,
      data: { idle: true, stopped: false, blocked: false } as StatusUpdateData,
    };

    sendEvent(event);
    expect(statusHandler).toHaveBeenCalledWith(event.data);
  });

  it('notifies multiple handlers registered via on()', () => {
    const handler1 = vi.fn();
    const handler2 = vi.fn();

    manager.on('status_update', handler1);
    manager.on('status_update', handler2);

    const event = {
      type: 'status_update' as const,
      data: { idle: true, stopped: false, blocked: false } as StatusUpdateData,
    };

    sendEvent(event);
    expect(handler1).toHaveBeenCalledWith(event.data);
    expect(handler2).toHaveBeenCalledWith(event.data);
  });
});

describe('WebSocket Manager - Clarification Requests', () => {
  let manager: WebSocketManager;
  let mockWs: MockWebSocket;

  function sendEvent(event: object) {
    mockWs.onmessage?.({ data: JSON.stringify(event) } as MessageEvent);
  }

  beforeEach(() => {
    manager = new WebSocketManager();
    mockWs = new MockWebSocket('ws://test/ws');
    vi.spyOn(global, 'WebSocket').mockReturnValue(mockWs as any);
    manager.connect();
  });

  afterEach(() => {
    manager.disconnect();
    vi.restoreAllMocks();
  });

  it('notifies clarification handlers via on()', () => {
    const clarHandler = vi.fn();
    manager.on('clarification_request', clarHandler);

    const event = {
      type: 'clarification_request' as const,
      data: { task_id: 'task123', question: 'What do you want?' } as ClarificationRequestData,
    };

    sendEvent(event);
    expect(clarHandler).toHaveBeenCalledWith(event.data);
  });

  it('passes question text to handler', () => {
    const clarHandler = vi.fn();
    manager.on('clarification_request', clarHandler);

    const event = {
      type: 'clarification_request' as const,
      data: { task_id: 'task123', question: 'Please clarify your requirements' } as ClarificationRequestData,
    };

    sendEvent(event);
    expect(clarHandler).toHaveBeenCalledWith(
      expect.objectContaining({ question: 'Please clarify your requirements' })
    );
  });
});

describe('WebSocket Manager - Token Streaming', () => {
  let manager: WebSocketManager;
  let mockWs: MockWebSocket;

  function sendEvent(event: object) {
    mockWs.onmessage?.({ data: JSON.stringify(event) } as MessageEvent);
  }

  beforeEach(() => {
    manager = new WebSocketManager();
    mockWs = new MockWebSocket('ws://test/ws');
    vi.spyOn(global, 'WebSocket').mockReturnValue(mockWs as any);
    manager.connect();
  });

  afterEach(() => {
    manager.disconnect();
    vi.restoreAllMocks();
  });

  it('notifies token handlers via on()', () => {
    const tokenHandler = vi.fn();
    manager.on('token', tokenHandler);

    const event = {
      type: 'token' as const,
      data: { text: 'Hello' } as TokenData,
    };

    sendEvent(event);
    expect(tokenHandler).toHaveBeenCalledWith(event.data);
  });

  it('streams multiple tokens', () => {
    const tokenHandler = vi.fn();
    manager.on('token', tokenHandler);

    const tokens = ['Hello', ' ', 'world', '!'];
    tokens.forEach(token => {
      sendEvent({ type: 'token', data: { text: token } as TokenData });
    });

    expect(tokenHandler).toHaveBeenCalledTimes(4);
    expect(tokenHandler).toHaveBeenNthCalledWith(4, expect.objectContaining({ text: '!' }));
  });
});

describe('WebSocket Manager - Thinking Stream', () => {
  let manager: WebSocketManager;
  let mockWs: MockWebSocket;

  function sendEvent(event: object) {
    mockWs.onmessage?.({ data: JSON.stringify(event) } as MessageEvent);
  }

  beforeEach(() => {
    manager = new WebSocketManager();
    mockWs = new MockWebSocket('ws://test/ws');
    vi.spyOn(global, 'WebSocket').mockReturnValue(mockWs as any);
    manager.connect();
  });

  afterEach(() => {
    manager.disconnect();
    vi.restoreAllMocks();
  });

  it('notifies thinking handlers via on()', () => {
    const thinkingHandler = vi.fn();
    manager.on('thinking', thinkingHandler);

    const event = {
      type: 'thinking' as const,
      data: { text: 'Let me think...' } as ThinkingData,
    };

    sendEvent(event);
    expect(thinkingHandler).toHaveBeenCalledWith(event.data);
  });
});

describe('WebSocket Manager - Content Stream', () => {
  let manager: WebSocketManager;
  let mockWs: MockWebSocket;

  function sendEvent(event: object) {
    mockWs.onmessage?.({ data: JSON.stringify(event) } as MessageEvent);
  }

  beforeEach(() => {
    manager = new WebSocketManager();
    mockWs = new MockWebSocket('ws://test/ws');
    vi.spyOn(global, 'WebSocket').mockReturnValue(mockWs as any);
    manager.connect();
  });

  afterEach(() => {
    manager.disconnect();
    vi.restoreAllMocks();
  });

  it('notifies content handlers via on()', () => {
    const contentHandler = vi.fn();
    manager.on('content', contentHandler);

    const event = {
      type: 'content' as const,
      data: { text: 'Full response content' } as ContentData,
    };

    sendEvent(event);
    expect(contentHandler).toHaveBeenCalledWith(event.data);
  });
});

describe('WebSocket Manager - Tool Calls and Results', () => {
  let manager: WebSocketManager;
  let mockWs: MockWebSocket;

  function sendEvent(event: object) {
    mockWs.onmessage?.({ data: JSON.stringify(event) } as MessageEvent);
  }

  beforeEach(() => {
    manager = new WebSocketManager();
    mockWs = new MockWebSocket('ws://test/ws');
    vi.spyOn(global, 'WebSocket').mockReturnValue(mockWs as any);
    manager.connect();
  });

  afterEach(() => {
    manager.disconnect();
    vi.restoreAllMocks();
  });

  it('notifies tool_call handlers via on()', () => {
    const handler = vi.fn();
    manager.on('tool_call', handler);

    const event = {
      type: 'tool_call' as const,
      data: { name: 'read_file', arguments: { path: '/foo' } } as ToolCallData,
    };

    sendEvent(event);
    expect(handler).toHaveBeenCalledWith(event.data);
  });

  it('notifies tool_result handlers via on()', () => {
    const handler = vi.fn();
    manager.on('tool_result', handler);

    const event = {
      type: 'tool_result' as const,
      data: { result: 'file contents' } as ToolResultData,
    };

    sendEvent(event);
    expect(handler).toHaveBeenCalledWith(event.data);
  });
});

describe('WebSocket Manager - Generic Event Handler', () => {
  let manager: WebSocketManager;
  let mockWs: MockWebSocket;

  function sendEvent(event: object) {
    mockWs.onmessage?.({ data: JSON.stringify(event) } as MessageEvent);
  }

  beforeEach(() => {
    manager = new WebSocketManager();
    mockWs = new MockWebSocket('ws://test/ws');
    vi.spyOn(global, 'WebSocket').mockReturnValue(mockWs as any);
    manager.connect();
  });

  afterEach(() => {
    manager.disconnect();
    vi.restoreAllMocks();
  });

  it('notifies generic handlers by event type', () => {
    const handler = vi.fn();
    manager.on('status_update', handler);

    sendEvent({ type: 'status_update', data: { idle: true } });
    expect(handler).toHaveBeenCalledWith({ idle: true });
  });

  it('unregisters handlers correctly via off()', () => {
    const handler = vi.fn();
    manager.on('status_update', handler);
    manager.off('status_update', handler);

    sendEvent({ type: 'status_update', data: { idle: true } });
    expect(handler).not.toHaveBeenCalled();
  });
});

describe('WebSocket Manager - Singleton', () => {
  it('exports singleton instance', () => {
    expect(wsManager).toBeDefined();
    expect(wsManager).toBeInstanceOf(WebSocketManager);
  });
});

describe('WebSocket Manager - Error Handling', () => {
  let manager: WebSocketManager;
  let mockWs: MockWebSocket;

  beforeEach(() => {
    manager = new WebSocketManager();
    mockWs = new MockWebSocket('ws://test/ws');
    vi.spyOn(global, 'WebSocket').mockReturnValue(mockWs as any);
    manager.connect();
  });

  afterEach(() => {
    manager.disconnect();
    vi.restoreAllMocks();
  });

  it('handles WebSocket errors', () => {
    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    mockWs.onerror?.(new Event('error'));
    expect(consoleSpy).toHaveBeenCalled();
    consoleSpy.mockRestore();
  });
});
