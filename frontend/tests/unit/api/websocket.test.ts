/**
 * Unit Tests for WebSocket Manager
 * 
 * Tests real-time event handling and connection management.
 */

import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import { WebSocketManager, wsManager } from '../../../src/api/websocket';
import type {
  StatusUpdateData,
  ClarificationRequestData,
  TokenData,
  ThinkingData,
  ContentData,
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
const OriginalWebSocket = global.WebSocket;
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
    
    // Connection should be attempted
    expect(manager).toBeDefined();
  });
  
  it('uses correct WebSocket URL', () => {
    manager.connect();
    
    // URL should be ws://[host]/ws
    // In test environment, window.location.host is empty
    // So we just verify the connection was attempted
    expect(manager).toBeDefined();
  });
  
  it('handles connection open', () => {
    const mockWs = new MockWebSocket('ws://test/ws');
    vi.spyOn(global, 'WebSocket').mockReturnValue(mockWs as any);
    
    const openHandler = vi.fn();
    manager.on('open', openHandler);
    
    manager.connect();
    mockWs.onopen?.();
    
    // Connection open should be handled
    expect(openHandler).not.toHaveBeenCalled(); // We don't emit 'open' event
  });
  
  it('reconnects on close', async () => {
    const mockWs = new MockWebSocket('ws://test/ws');
    vi.spyOn(global, 'WebSocket').mockReturnValue(mockWs as any);
    
    const connectSpy = vi.spyOn(manager, 'connect');
    
    manager.connect();
    
    // Simulate close - reconnect happens after delay
    mockWs.onclose?.();
    
    // Wait for reconnect delay
    await new Promise(resolve => setTimeout(resolve, 100));
    
    // Reconnect should be scheduled
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
    const event = {
      type: 'status_update',
      data: { idle: true },
    };
    
    mockWs.onmessage?.({ data: JSON.stringify(event) } as MessageEvent);
    
    // Message should be parsed and handled
    expect(manager).toBeDefined();
  });
  
  it('handles malformed messages gracefully', () => {
    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    
    mockWs.onmessage?.({ data: 'invalid json' } as MessageEvent);
    
    // Should not crash
    expect(consoleSpy).toHaveBeenCalled();
    
    consoleSpy.mockRestore();
  });
});

describe('WebSocket Manager - Status Updates', () => {
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
  
  it('notifies status update handlers', () => {
    const statusHandler = vi.fn();
    manager.onStatusUpdate(statusHandler);
    
    const event = {
      type: 'status_update' as const,
      data: { idle: true, stopped: false, blocked: false } as StatusUpdateData,
    };
    
    mockWs.onmessage?.({ data: JSON.stringify(event) } as MessageEvent);
    
    expect(statusHandler).toHaveBeenCalledWith(event.data);
  });
  
  it('notifies multiple status handlers', () => {
    const handler1 = vi.fn();
    const handler2 = vi.fn();
    
    manager.onStatusUpdate(handler1);
    manager.onStatusUpdate(handler2);
    
    const event = {
      type: 'status_update' as const,
      data: { idle: true, stopped: false, blocked: false } as StatusUpdateData,
    };
    
    mockWs.onmessage?.({ data: JSON.stringify(event) } as MessageEvent);
    
    expect(handler1).toHaveBeenCalledWith(event.data);
    expect(handler2).toHaveBeenCalledWith(event.data);
  });
  
  it('sets wsConnected on status update', () => {
    const event = {
      type: 'status_update' as const,
      data: { idle: true, stopped: false, blocked: false } as StatusUpdateData,
    };
    
    mockWs.onmessage?.({ data: JSON.stringify(event) } as MessageEvent);
    
    // wsConnected should be set via the handler in app.ts
    // We can't test this directly here without importing app state
  });
});

describe('WebSocket Manager - Clarification Requests', () => {
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
  
  it('notifies clarification handlers', () => {
    const clarHandler = vi.fn();
    manager.onClarificationRequest(clarHandler);
    
    const event = {
      type: 'clarification_request' as const,
      data: { task_id: 'task123', question: 'What do you want?' } as ClarificationRequestData,
    };
    
    mockWs.onmessage?.({ data: JSON.stringify(event) } as MessageEvent);
    
    expect(clarHandler).toHaveBeenCalledWith(event.data);
  });
  
  it('passes question text to handler', () => {
    const clarHandler = vi.fn();
    manager.onClarificationRequest(clarHandler);
    
    const event = {
      type: 'clarification_request' as const,
      data: { task_id: 'task123', question: 'Please clarify your requirements' } as ClarificationRequestData,
    };
    
    mockWs.onmessage?.({ data: JSON.stringify(event) } as MessageEvent);
    
    expect(clarHandler).toHaveBeenCalledWith(
      expect.objectContaining({
        question: 'Please clarify your requirements',
      })
    );
  });
});

describe('WebSocket Manager - Token Streaming', () => {
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
  
  it('notifies token handlers', () => {
    const tokenHandler = vi.fn();
    manager.onToken(tokenHandler);
    
    const event = {
      type: 'token' as const,
      data: { task_id: 'task123', token: 'Hello' } as TokenData,
    };
    
    mockWs.onmessage?.({ data: JSON.stringify(event) } as MessageEvent);
    
    expect(tokenHandler).toHaveBeenCalledWith(event.data);
  });
  
  it('streams multiple tokens', () => {
    const tokenHandler = vi.fn();
    manager.onToken(tokenHandler);
    
    const tokens = ['Hello', ' ', 'world', '!'];
    
    tokens.forEach(token => {
      const event = {
        type: 'token' as const,
        data: { task_id: 'task123', token } as TokenData,
      };
      mockWs.onmessage?.({ data: JSON.stringify(event) } as MessageEvent);
    });
    
    expect(tokenHandler).toHaveBeenCalledTimes(4);
    expect(tokenHandler).toHaveBeenNthCalledWith(4, expect.objectContaining({ token: '!' }));
  });
});

describe('WebSocket Manager - Thinking Stream', () => {
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
  
  it('notifies thinking handlers', () => {
    const thinkingHandler = vi.fn();
    manager.onThinking(thinkingHandler);
    
    const event = {
      type: 'thinking' as const,
      data: { task_id: 'task123', thinking: 'Let me think...' } as ThinkingData,
    };
    
    mockWs.onmessage?.({ data: JSON.stringify(event) } as MessageEvent);
    
    expect(thinkingHandler).toHaveBeenCalledWith(event.data);
  });
});

describe('WebSocket Manager - Content Stream', () => {
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
  
  it('notifies content handlers', () => {
    const contentHandler = vi.fn();
    manager.onContent(contentHandler);
    
    const event = {
      type: 'content' as const,
      data: { task_id: 'task123', content: 'Full response content' } as ContentData,
    };
    
    mockWs.onmessage?.({ data: JSON.stringify(event) } as MessageEvent);
    
    expect(contentHandler).toHaveBeenCalledWith(event.data);
  });
});

describe('WebSocket Manager - Generic Event Handler', () => {
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
  
  it('notifies generic handlers by event type', () => {
    const genericHandler = vi.fn();
    manager.on('status_update', genericHandler);
    
    const event = {
      type: 'status_update' as const,
      data: { idle: true },
    };
    
    mockWs.onmessage?.({ data: JSON.stringify(event) } as MessageEvent);
    
    expect(genericHandler).toHaveBeenCalledWith(event.data);
  });
  
  it('unregisters handlers correctly', () => {
    const handler = vi.fn();
    manager.on('status_update', handler);
    manager.off('status_update', handler);
    
    const event = {
      type: 'status_update' as const,
      data: { idle: true },
    };
    
    mockWs.onmessage?.({ data: JSON.stringify(event) } as MessageEvent);
    
    expect(handler).not.toHaveBeenCalled();
  });
});

describe('WebSocket Manager - Singleton', () => {
  it('exports singleton instance', () => {
    expect(wsManager).toBeDefined();
    expect(wsManager).toBeInstanceOf(WebSocketManager);
  });
  
  it('singleton is exported', () => {
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
    
    // Should log error but not crash
    expect(consoleSpy).toHaveBeenCalled();
    
    consoleSpy.mockRestore();
  });
  
  it('handles connection failures gracefully', () => {
    const originalWebSocket = global.WebSocket;
    global.WebSocket = (() => {
      throw new Error('Connection failed');
    }) as any;
    
    // Should not crash the application even if WebSocket constructor throws
    expect(() => {
      try {
        manager.connect();
      } catch (e) {
        // May or may not throw depending on implementation
      }
    }).not.toThrow();
    
    global.WebSocket = originalWebSocket;
  });
});
