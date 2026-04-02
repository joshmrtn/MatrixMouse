import type { Task, Repo, BlockedTaskReport, DecisionConfig, ContextMessage } from './task';

/**
 * API response wrappers
 */
export interface ApiResponse<T> {
  ok?: boolean;
  data?: T;
  error?: string;
}

export interface TasksResponse {
  tasks: Task[];
  count: number;
}

export interface TaskCreateRequest {
  title: string;
  description?: string;
  repo?: string[];
  role?: string;
  target_files?: string[];
  importance?: number;
  urgency?: number;
}

export interface TaskUpdateRequest {
  title?: string;
  description?: string;
  repo?: string[];
  target_files?: string[];
  importance?: number;
  urgency?: number;
  notes?: string;
  branch?: string;
  role?: string;
  turn_limit?: number;
}

export interface InterjectionRequest {
  message: string;
}

export interface DecisionRequest {
  decision_type: string;
  choice: string;
  note?: string;
  metadata?: Record<string, unknown>;
}

export interface StatusResponse {
  idle?: boolean;
  stopped?: boolean;
  blocked?: boolean;
  task?: string;
  phase?: string;
  model?: string;
  turns?: number;
}

export interface ConfigResponse {
  [key: string]: unknown;
}

export interface ConfigPatchRequest {
  values: Record<string, unknown>;
}

/**
 * Context/conversation API response
 */
export interface ContextResponse {
  messages: ContextMessage[];
  count: number;
  estimated_tokens: number;
}

/**
 * Pending clarification question response
 */
export interface PendingResponse {
  pending: string | null;
}

/**
 * Interjection API response
 */
export interface InterjectionResponse {
  ok: boolean;
  manager_task_id?: string;
  repo?: string;
  task_id?: string;
}
