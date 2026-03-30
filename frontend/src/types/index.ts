// Task status enum matching Python TaskStatus
export type TaskStatus =
  | 'pending'
  | 'ready'
  | 'running'
  | 'blocked_by_task'
  | 'blocked_by_human'
  | 'waiting'
  | 'complete'
  | 'cancelled';

// Agent role enum matching Python AgentRole
export type AgentRole = 'manager' | 'coder' | 'writer' | 'critic' | 'merge';

// Task dataclass matching Python Task
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
  pr_state?: string;
  pr_poll_next_at?: string;
  reviews_task_id?: string;
  wait_reason?: string;
  wait_until?: string;
  turn_limit?: number;
  turns_taken?: number;
}

// Context message structure
export interface ContextMessage {
  role: 'user' | 'assistant' | 'system' | 'tool_call' | 'tool_result';
  content: string;
  tool_call_id?: string;
  name?: string;
}

// Tool call structure
export interface ToolCall {
  name: string;
  arguments: Record<string, unknown>;
  call_id?: string;
}

// Repo structure
export interface Repo {
  name: string;
  remote: string;
  local_path: string;
  added: string;
}

// WebSocket event structure
export interface WebSocketEvent {
  type: string;
  data: Record<string, unknown>;
}

// Decision modal configuration
export interface DecisionConfig {
  taskId: string;
  decisionType: string;
  title: string;
  body: string;
  choices: Choice[];
  requireText?: boolean;
  textPlaceholder?: string;
}

export interface Choice {
  label: string;
  value: string;
}

// Scope type for interjection routing
export type Scope = 'workspace' | string; // string = repo name

// Task tree node (extends Task with children)
export interface TaskTreeNode extends Task {
  children: TaskTreeNode[];
}

// Blocked task report structure
export interface BlockedTaskReport {
  human: BlockedTaskEntry[];
  dependencies: BlockedTaskEntry[];
  waiting: BlockedTaskEntry[];
}

export interface BlockedTaskEntry {
  id: string;
  title: string;
  blocking_reason: string;
}
