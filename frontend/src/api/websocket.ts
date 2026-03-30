import type { WebSocketEvent, Task, DecisionConfig } from '../types';

export type EventHandler = (event: WebSocketEvent) => void;

/**
 * WebSocket connection manager for real-time events
 */
export class WebSocketManager {
  private ws: WebSocket | null = null;
  private handlers: Set<EventHandler> = new Set();
  private reconnectDelay = 3000;
  private statusHandler: ((data: Record<string, unknown>) => void) | null = null;
  private clarificationHandler: ((question: string) => void) | null = null;
  private decisionHandler: ((config: DecisionConfig) => void) | null = null;
  private taskTreeHandler: ((tasks: Task[]) => void) | null = null;
  private tokenHandler: ((text: string) => void) | null = null;
  private thinkingHandler: ((text: string) => void) | null = null;

  connect(): void {
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
    const url = `${proto}://${window.location.host}/ws`;
    
    this.ws = new WebSocket(url);
    
    this.ws.onopen = () => {
      console.log('WebSocket connected');
    };
    
    this.ws.onmessage = (event) => {
      try {
        const wsEvent: WebSocketEvent = JSON.parse(event.data);
        this.handleEvent(wsEvent);
      } catch (e) {
        console.error('Failed to parse WebSocket message:', e);
      }
    };
    
    this.ws.onclose = () => {
      console.log('WebSocket disconnected, reconnecting...');
      setTimeout(() => this.connect(), this.reconnectDelay);
    };
    
    this.ws.onerror = (error) => {
      console.error('WebSocket error:', error);
      this.ws?.close();
    };
  }

  private handleEvent(event: WebSocketEvent): void {
    // Handle status updates
    if (event.type === 'status_update' && this.statusHandler) {
      this.statusHandler(event.data as Record<string, unknown>);
    }
    
    // Handle clarification requests
    if (event.type === 'clarification_request' && this.clarificationHandler) {
      this.clarificationHandler(event.data.question as string);
    }
    
    // Handle decision events
    if (this.isDecisionEvent(event.type) && this.decisionHandler) {
      const config: DecisionConfig = {
        taskId: event.data.task_id as string,
        decisionType: event.type,
        title: this.getDecisionTitle(event.type),
        body: event.data.message as string || event.data.body as string || '',
        choices: this.getDecisionChoices(event.type),
        requireText: this.requiresText(event.type),
        textPlaceholder: this.getTextPlaceholder(event.type),
      };
      this.decisionHandler(config);
    }
    
    // Handle task tree updates
    if (event.type === 'task_tree_update' && this.taskTreeHandler) {
      this.taskTreeHandler(event.data.tasks as Task[]);
    }
    
    // Handle streaming tokens
    if (event.type === 'token' && this.tokenHandler) {
      this.tokenHandler(event.data.text as string);
    }
    
    // Handle thinking stream
    if (event.type === 'thinking' && this.thinkingHandler) {
      this.thinkingHandler(event.data.text as string);
    }
    
    // Call generic handlers
    this.handlers.forEach(handler => handler(event));
  }

  private isDecisionEvent(type: string): boolean {
    const decisionTypes = [
      'decomposition_confirmation_required',
      'pr_approval_required',
      'pr_rejection',
      'turn_limit_reached',
      'critic_turn_limit_reached',
      'merge_conflict_resolution_turn_limit_reached',
      'planning_turn_limit_reached',
    ];
    return decisionTypes.includes(type);
  }

  private getDecisionTitle(type: string): string {
    const titles: Record<string, string> = {
      'decomposition_confirmation_required': 'Decomposition Request',
      'pr_approval_required': 'PR Approval Required',
      'pr_rejection': 'PR Rejected',
      'turn_limit_reached': 'Turn Limit Reached',
      'critic_turn_limit_reached': 'Critic Review',
      'merge_conflict_resolution_turn_limit_reached': 'Merge Conflict',
      'planning_turn_limit_reached': 'Planning Limit',
    };
    return titles[type] || 'Decision Required';
  }

  private getDecisionChoices(type: string): Array<{ label: string; value: string }> {
    const choices: Record<string, Array<{ label: string; value: string }>> = {
      'decomposition_confirmation_required': [
        { label: 'Allow', value: 'allow' },
        { label: 'Deny', value: 'deny' },
      ],
      'pr_approval_required': [
        { label: 'Approve', value: 'approve' },
        { label: 'Reject', value: 'reject' },
      ],
      'pr_rejection': [
        { label: 'Rework', value: 'rework' },
        { label: 'Manual', value: 'manual' },
      ],
      'turn_limit_reached': [
        { label: 'Extend', value: 'extend' },
        { label: 'Respec', value: 'respec' },
        { label: 'Cancel', value: 'cancel' },
      ],
      'critic_turn_limit_reached': [
        { label: 'Approve Task', value: 'approve_task' },
        { label: 'Extend Critic', value: 'extend_critic' },
        { label: 'Block Task', value: 'block_task' },
      ],
      'merge_conflict_resolution_turn_limit_reached': [
        { label: 'Extend', value: 'extend' },
        { label: 'Abort', value: 'abort' },
      ],
      'planning_turn_limit_reached': [
        { label: 'Extend', value: 'extend' },
        { label: 'Commit', value: 'commit' },
        { label: 'Cancel', value: 'cancel' },
      ],
    };
    return choices[type] || [];
  }

  private requiresText(type: string): boolean {
    const requiresText = [
      'decomposition_confirmation_required', // deny requires reason
      'turn_limit_reached', // respec requires note
    ];
    return requiresText.includes(type);
  }

  private getTextPlaceholder(type: string): string {
    const placeholders: Record<string, string> = {
      'decomposition_confirmation_required': 'Explain why decomposition should not be allowed...',
      'turn_limit_reached': 'Provide guidance for the agent...',
    };
    return placeholders[type] || 'Please provide details...';
  }

  // Event handler registration
  onStatusUpdate(handler: (data: Record<string, unknown>) => void): void {
    this.statusHandler = handler;
  }

  onClarificationRequest(handler: (question: string) => void): void {
    this.clarificationHandler = handler;
  }

  onDecisionRequired(handler: (config: DecisionConfig) => void): void {
    this.decisionHandler = handler;
  }

  onTaskTreeUpdate(handler: (tasks: Task[]) => void): void {
    this.taskTreeHandler = handler;
  }

  onToken(handler: (text: string) => void): void {
    this.tokenHandler = handler;
  }

  onThinking(handler: (text: string) => void): void {
    this.thinkingHandler = handler;
  }

  addHandler(handler: EventHandler): void {
    this.handlers.add(handler);
  }

  removeHandler(handler: EventHandler): void {
    this.handlers.delete(handler);
  }

  disconnect(): void {
    this.ws?.close();
    this.ws = null;
  }
}

// Singleton instance
export const wsManager = new WebSocketManager();
