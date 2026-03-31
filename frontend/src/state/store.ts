/**
 * Central state store for MatrixMouse frontend
 */

import type { Task, Repo, StatusResponse, BlockedTaskReport } from '../types';

/**
 * Application state interface
 */
export interface AppState {
  // Current scope (workspace or repo name)
  scope: string;
  
  // Currently selected task (null if viewing scope-level)
  selectedTask: Task | null;
  
  // All tasks (for task tree building)
  tasks: Task[];
  
  // All repositories
  repos: Repo[];
  
  // Expanded task IDs in tree view
  expandedTasks: Set<string>;
  
  // Blocked tasks report
  blockedReport: BlockedTaskReport | null;
  
  // Current status from WebSocket
  status: StatusResponse | null;
  
  // Pending clarification question
  pendingQuestion: string | null;
  
  // WebSocket connection state
  wsConnected: boolean;
  
  // Current route/page
  currentPage: string;
  
  // Route parameters
  routeParams: Record<string, string>;
  
  // Sidebar open state (mobile)
  sidebarOpen: boolean;
  
  // Loading state
  loading: boolean;
  
  // Error state
  error: string | null;
}

/**
 * Initial state
 */
export const initialState: AppState = {
  scope: 'workspace',
  selectedTask: null,
  tasks: [],
  repos: [],
  expandedTasks: new Set(),
  blockedReport: null,
  status: null,
  pendingQuestion: null,
  wsConnected: false,
  currentPage: 'channel',
  routeParams: {},
  sidebarOpen: false,
  loading: false,
  error: null,
};

/**
 * State listeners
 */
type StateListener = (state: AppState) => void;
const listeners = new Set<StateListener>();

/**
 * Current state (private)
 */
let currentState: AppState = { ...initialState };

/**
 * Get current state
 */
export function getState(): AppState {
  return { ...currentState };
}

/**
 * Update state and notify listeners
 */
export function setState<K extends keyof AppState>(
  key: K,
  value: AppState[K]
): void {
  currentState = { ...currentState, [key]: value };
  notifyListeners();
}

/**
 * Update multiple state keys at once
 */
export function setStates(updates: Partial<AppState>): void {
  currentState = { ...currentState, ...updates };
  notifyListeners();
}

/**
 * Reset state to initial values
 */
export function resetState(): void {
  currentState = { ...initialState };
  notifyListeners();
}

/**
 * Subscribe to state changes
 */
export function subscribe(listener: StateListener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/**
 * Notify all listeners of state change
 */
function notifyListeners(): void {
  listeners.forEach((listener) => listener(getState()));
}

// ============================================================================
// Task State Helpers
// ============================================================================

/**
 * Get task by ID
 */
export function getTaskById(taskId: string): Task | undefined {
  return currentState.tasks.find((t) => t.id === taskId);
}

/**
 * Get tasks for a specific repo
 */
export function getTasksForRepo(scope: string): Task[] {
  if (scope === 'workspace') {
    // Return tasks with no repo OR more than one repo (cross-repo tasks)
    return currentState.tasks.filter((t) => t.repo.length === 0 || t.repo.length > 1);
  }
  // Return tasks for specific repo
  return currentState.tasks.filter((t) => t.repo.includes(scope));
}

/**
 * Get blocked tasks
 */
export function getBlockedTasks(): Task[] {
  return currentState.tasks.filter(
    (t) =>
      t.status === 'blocked_by_human' || t.status === 'blocked_by_task'
  );
}

/**
 * Get waiting tasks
 */
export function getWaitingTasks(): Task[] {
  return currentState.tasks.filter((t) => t.status === 'waiting');
}

/**
 * Get active (non-terminal) tasks
 */
export function getActiveTasks(): Task[] {
  const terminal = new Set(['complete', 'cancelled']);
  return currentState.tasks.filter((t) => !terminal.has(t.status));
}

// ============================================================================
// Task Tree Helpers
// ============================================================================

/**
 * Build task tree from flat task list
 */
export interface TaskTreeNode extends Task {
  children: TaskTreeNode[];
}

export function buildTaskTree(): {
  taskMap: Map<string, TaskTreeNode>;
  rootTasks: TaskTreeNode[];
} {
  const taskMap = new Map<string, TaskTreeNode>();
  const rootTasks: TaskTreeNode[] = [];

  // Create task nodes
  currentState.tasks.forEach((task) => {
    taskMap.set(task.id, { ...task, children: [] });
  });

  // Build hierarchy
  currentState.tasks.forEach((task) => {
    const node = taskMap.get(task.id);
    if (!node) return;

    if (task.parent_task_id && taskMap.has(task.parent_task_id)) {
      const parent = taskMap.get(task.parent_task_id)!;
      parent.children.push(node);
    } else {
      rootTasks.push(node);
    }
  });

  return { taskMap, rootTasks };
}

/**
 * Toggle task expansion in tree
 */
export function toggleTaskExpansion(taskId: string): void {
  const expanded = new Set(currentState.expandedTasks);
  if (expanded.has(taskId)) {
    expanded.delete(taskId);
  } else {
    expanded.add(taskId);
  }
  setState('expandedTasks', expanded);
}

/**
 * Check if task is expanded
 */
export function isTaskExpanded(taskId: string): boolean {
  return currentState.expandedTasks.has(taskId);
}
