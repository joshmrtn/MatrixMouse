/**
 * Task status enum matching Python TaskStatus
 */
export type TaskStatus =
  | 'pending'
  | 'ready'
  | 'running'
  | 'blocked_by_task'
  | 'blocked_by_human'
  | 'waiting'
  | 'complete'
  | 'cancelled';

/**
 * Agent role enum matching Python AgentRole
 */
export type AgentRole = 'manager' | 'coder' | 'writer' | 'critic' | 'merge';

/**
 * PR state enum matching Python PRState
 */
export type PRState = '' | 'open' | 'merged' | 'closed';

/**
 * Task dataclass matching Python Task
 */
export interface Task {
  id: string;
  title: string;
  description: string;
  repo: string[];
  role: AgentRole;
  status: TaskStatus;
  branch: string;
  parent_task_id: string | null;
  depth: number;
  importance: number;
  urgency: number;
  priority_score: number;
  phase?: string;
  notes?: string;
  target_files?: string[];
  wip_commit_hash?: string;
  preemptable: boolean;
  preempt: boolean;
  created_at: string;
  started_at?: string;
  completed_at?: string;
  last_modified: string;
  context_messages: ContextMessage[];
  pending_tool_calls: ToolCall[];
  pending_question?: string;
  decomposition_confirmed_depth: number;
  merge_resolution_decisions: Record<string, unknown>[];
  pr_url?: string;
  pr_state?: PRState;
  pr_poll_next_at?: string;
  reviews_task_id?: string;
  wait_reason?: string;
  wait_until?: string;
  turn_limit?: number;
  turns_taken?: number;
}

/**
 * Context message structure
 */
export interface ContextMessage {
  role: 'user' | 'assistant' | 'system' | 'tool_call' | 'tool_result';
  content: string;
  tool_call_id?: string;
  name?: string;
}

/**
 * Tool call structure
 */
export interface ToolCall {
  name: string;
  arguments: Record<string, unknown>;
  call_id?: string;
}

/**
 * Repository structure
 */
export interface Repo {
  name: string;
  remote: string;
  local_path: string;
  added: string;
}

/**
 * Blocked task entry for status dashboard
 */
export interface BlockedTaskEntry {
  id: string;
  title: string;
  blocking_reason: string;
}

/**
 * Blocker task with full details
 */
export interface BlockerTask {
  id: string;
  title: string;
}

/**
 * Blocker load error state
 */
export interface BlockerLoadError {
  type: 'error';
  message: string;
  retryable: boolean;
}

/**
 * Blocker loading state
 */
export interface BlockerLoading {
  type: 'loading';
}

/**
 * Blocker display state - either a task, an error, or loading
 */
export type BlockerState = BlockerTask | BlockerLoadError | BlockerLoading;

/**
 * Blocked task report from /blocked endpoint
 */
export interface BlockedTaskReport {
  human: BlockedTaskEntry[];
  dependencies: BlockedTaskEntry[];
  waiting: BlockedTaskEntry[];
}

/**
 * Decision choice for confirmation modals
 */
export interface DecisionChoice {
  label: string;
  value: string;
}

/**
 * Decision configuration for modals
 */
export interface DecisionConfig {
  taskId: string;
  decisionType: string;
  title: string;
  body: string;
  choices: DecisionChoice[];
  requireText?: boolean;
  textPlaceholder?: string;
}
