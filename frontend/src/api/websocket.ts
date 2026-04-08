/**
 * WebSocket connection manager for real-time events
 *
 * Unified handler API: use on(eventType, handler) / off(eventType, handler)
 * for all event types. No specialized methods needed.
 */

import type {
  WebSocketEvent,
  WebSocketEventType,
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
    const typeHandlers = this.handlers.get(event.type);
    if (typeHandlers) {
      typeHandlers.forEach((handler) => handler(event.data));
    }
  }

  /**
   * Register event handler for a specific event type.
   *
   * @example
   * wsManager.on('token', (data) => console.log(data.text));
   * wsManager.on('status_update', (data) => updateStatus(data));
   */
  on<T = unknown>(eventType: WebSocketEventType, handler: EventHandler<T>): void {
    if (!this.handlers.has(eventType)) {
      this.handlers.set(eventType, new Set());
    }
    this.handlers.get(eventType)!.add(handler as EventHandler);
  }

  /**
   * Unregister event handler.
   *
   * @example
   * wsManager.off('token', myHandler);
   */
  off<T = unknown>(eventType: WebSocketEventType, handler: EventHandler<T>): void {
    const typeHandlers = this.handlers.get(eventType);
    if (typeHandlers) {
      typeHandlers.delete(handler as EventHandler);
    }
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
