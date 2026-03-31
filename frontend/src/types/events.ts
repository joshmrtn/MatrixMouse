import type { Task, StatusResponse, BlockedTaskReport, DecisionConfig } from './task';

/**
 * WebSocket event types
 */
export type WebSocketEventType =
  | 'status_update'
  | 'task_tree_update'
  | 'clarification_request'
  | 'decomposition_confirmation_required'
  | 'pr_approval_required'
  | 'pr_rejection'
  | 'turn_limit_reached'
  | 'critic_turn_limit_reached'
  | 'merge_conflict_resolution_turn_limit_reached'
  | 'planning_turn_limit_reached'
  | 'message_received'
  | 'message_read'
  | 'task_context_update'
  | 'token'
  | 'thinking'
  | 'tool_call'
  | 'tool_result'
  | 'content'
  | 'phase_change'
  | 'escalation'
  | 'blocked_human'
  | 'complete'
  | 'error'
  | 'you'
  | 'system';

/**
 * WebSocket event structure
 */
export interface WebSocketEvent<T = unknown> {
  type: WebSocketEventType;
  data: T;
}

/**
 * Status update event data
 */
export interface StatusUpdateData extends StatusResponse {}

/**
 * Task tree update event data
 */
export interface TaskTreeUpdateData {
  tasks: Task[];
}

/**
 * Clarification request event data
 */
export interface ClarificationRequestData {
  question: string;
  task_id?: string;
}

/**
 * Token stream event data
 */
export interface TokenData {
  text: string;
  task_id?: string;
}

/**
 * Thinking stream event data
 */
export interface ThinkingData {
  text: string;
  task_id?: string;
}

/**
 * Content message event data
 */
export interface ContentData {
  text: string;
  task_id?: string;
}

/**
 * Tool call event data
 */
export interface ToolCallData {
  name: string;
  arguments: Record<string, unknown>;
  task_id?: string;
}

/**
 * Tool result event data
 */
export interface ToolResultData {
  result: string;
  task_id?: string;
}
