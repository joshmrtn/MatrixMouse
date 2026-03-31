/**
 * WebSocket connection manager for real-time events
 */

import type {
  WebSocketEvent,
  WebSocketEventType,
  StatusUpdateData,
  TaskTreeUpdateData,
  ClarificationRequestData,
  TokenData,
  ThinkingData,
  ContentData,
} from '../types';

/**
 * Event handler type
 */
export type EventHandler<T = unknown> = (data: T) => void;

/**
 * WebSocket Manager class
 */
export class WebSocketManager {
  private ws: WebSocket | null = null;
  private reconnectDelay = 3000;
  private handlers = new Map<WebSocketEventType, Set<EventHandler>>();
  private statusHandlers = new Set<EventHandler<StatusUpdateData>>();
  private clarificationHandlers = new Set<EventHandler<ClarificationRequestData>>();
  private tokenHandlers = new Set<EventHandler<TokenData>>();
  private thinkingHandlers = new Set<EventHandler<ThinkingData>>();
  private contentHandlers = new Set<EventHandler<ContentData>>();

  /**
   * Connect to WebSocket server
   */
  connect(): void {
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
    const url = `${proto}://${window.location.host}/ws`;

    console.log('[WebSocket] Connecting to', url);
    this.ws = new WebSocket(url);

    this.ws.onopen = () => {
      console.log('[WebSocket] Connected');
    };

    this.ws.onmessage = (event) => {
      try {
        const wsEvent: WebSocketEvent = JSON.parse(event.data);
        this.handleEvent(wsEvent);
      } catch (error) {
        console.error('[WebSocket] Failed to parse message:', error);
      }
    };

    this.ws.onclose = () => {
      console.log('[WebSocket] Disconnected, reconnecting...');
      setTimeout(() => this.connect(), this.reconnectDelay);
    };

    this.ws.onerror = (error) => {
      console.error('[WebSocket] Error:', error);
      this.ws?.close();
    };
  }

  /**
   * Handle incoming WebSocket event
   */
  private handleEvent(event: WebSocketEvent): void {
    // Handle specific event types
    switch (event.type) {
      case 'status_update':
        this.statusHandlers.forEach((handler) =>
          handler(event.data as StatusUpdateData)
        );
        break;

      case 'clarification_request':
        this.clarificationHandlers.forEach((handler) =>
          handler(event.data as ClarificationRequestData)
        );
        break;

      case 'token':
        this.tokenHandlers.forEach((handler) =>
          handler(event.data as TokenData)
        );
        break;

      case 'thinking':
        this.thinkingHandlers.forEach((handler) =>
          handler(event.data as ThinkingData)
        );
        break;

      case 'content':
        this.contentHandlers.forEach((handler) =>
          handler(event.data as ContentData)
        );
        break;
    }

    // Call generic handlers for this event type
    const typeHandlers = this.handlers.get(event.type);
    if (typeHandlers) {
      typeHandlers.forEach((handler) => handler(event.data));
    }
  }

  /**
   * Register event handler
   */
  on<T = unknown>(eventType: WebSocketEventType, handler: EventHandler<T>): void {
    if (!this.handlers.has(eventType)) {
      this.handlers.set(eventType, new Set());
    }
    this.handlers.get(eventType)!.add(handler as EventHandler);
  }

  /**
   * Unregister event handler
   */
  off<T = unknown>(eventType: WebSocketEventType, handler: EventHandler<T>): void {
    const typeHandlers = this.handlers.get(eventType);
    if (typeHandlers) {
      typeHandlers.delete(handler as EventHandler);
    }
  }

  /**
   * Register status update handler
   */
  onStatusUpdate(handler: EventHandler<StatusUpdateData>): void {
    this.statusHandlers.add(handler);
  }

  /**
   * Register clarification request handler
   */
  onClarificationRequest(handler: EventHandler<ClarificationRequestData>): void {
    this.clarificationHandlers.add(handler);
  }

  /**
   * Register token stream handler
   */
  onToken(handler: EventHandler<TokenData>): void {
    this.tokenHandlers.add(handler);
  }

  /**
   * Register thinking stream handler
   */
  onThinking(handler: EventHandler<ThinkingData>): void {
    this.thinkingHandlers.add(handler);
  }

  /**
   * Register content handler
   */
  onContent(handler: EventHandler<ContentData>): void {
    this.contentHandlers.add(handler);
  }

  /**
   * Disconnect from WebSocket
   */
  disconnect(): void {
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
  }
}

/**
 * Singleton WebSocket manager instance
 */
export const wsManager = new WebSocketManager();
