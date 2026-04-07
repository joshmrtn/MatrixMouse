/**
 * Decision Banner types
 *
 * Type definitions for the DecisionBanner component and its event data.
 * These types correspond to the WebSocket events that trigger decision banners.
 */

/**
 * The type of decision modal to display
 */
export type DecisionModalType =
  | 'decomposition'
  | 'pr_approval'
  | 'turn_limit'
  | 'planning_turn_limit'
  | 'merge_turn_limit'
  | 'critic_turn_limit';

/**
 * Event data for decomposition confirmation (Manager)
 */
export interface DecompositionEventData {
  task_id: string;
  task_title: string;
  current_depth: number;
  allowed_depth: number;
  proposed_subtasks: unknown[];
  choices: Array<{ value: string; label: string; description: string }>;
}

/**
 * Event data for PR approval
 */
export interface PRApprovalEventData {
  task_id: string;
  task_title: string;
  branch: string;
  parent_branch: string;
  repo: string;
  choices: Array<{ value: string; label: string; description: string }>;
}

/**
 * Event data for generic turn limit reached (Coder, Writer)
 */
export interface TurnLimitEventData {
  task_id: string;
  task_title: string;
  role: string;
  turns_taken: number;
  turn_limit: number;
  choices: Array<{ value: string; label: string; description: string }>;
}

/**
 * Event data for planning turn limit reached (Manager in PLANNING mode)
 */
export interface PlanningTurnLimitEventData {
  task_id: string;
  task_title: string;
  turns_taken: number;
  choices: Array<{ value: string; label: string; description: string }>;
}

/**
 * Event data for merge conflict resolution turn limit (Merge agent)
 */
export interface MergeTurnLimitEventData {
  task_id: string;
  task_title: string;
  turns_taken: number;
  parent_branch: string;
  resolved_so_far: Array<{ file: string; resolution: string }>;
  choices: Array<{ value: string; label: string; description: string }>;
}

/**
 * Event data for critic turn limit reached
 */
export interface CriticTurnLimitEventData {
  task_id: string;
  task_title: string;
  reviewed_task_id: string;
  turns_taken: number;
  critic_max_turns: number;
  choices: Array<{ value: string; label: string; description: string }>;
}

/**
 * Union type of all decision event data
 */
export type DecisionEventData =
  | DecompositionEventData
  | PRApprovalEventData
  | TurnLimitEventData
  | PlanningTurnLimitEventData
  | MergeTurnLimitEventData
  | CriticTurnLimitEventData;
