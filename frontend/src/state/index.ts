import type { Task, Repo, Scope, TaskTreeNode, BlockedTaskReport } from '../types';

/**
 * Application state management
 */

export interface AppState {
  // Current scope (workspace or repo name)
  scope: Scope;
  
  // Selected task (null if viewing scope-level chat)
  selectedTask: Task | null;
  
  // All tasks (for task tree building)
  tasks: Task[];
  
  // All repos
  repos: Repo[];
  
  // Expanded tasks in tree (set of task IDs)
  expandedTasks: Set<string>;
  
  // Blocked tasks report
  blockedReport: BlockedTaskReport | null;
  
  // Current status from WebSocket
  status: Record<string, unknown> | null;
  
  // Pending clarification question
  pendingQuestion: string | null;
  
  // WebSocket connection state
  wsConnected: boolean;
  
  // Current tab (chat, tasks, status, settings)
  currentTab: 'chat' | 'tasks' | 'status' | 'settings';
  
  // Sidebar open state (mobile)
  sidebarOpen: boolean;
}

// Initial state
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
  currentTab: 'chat',
  sidebarOpen: false,
};

// State listeners
type StateListener = (state: AppState) => void;
const listeners = new Set<StateListener>();

// Current state (private)
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
export function setState<K extends keyof AppState>(key: K, value: AppState[K]): void {
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
  listeners.forEach(listener => listener(getState()));
}

// Helper functions for task tree
export function buildTaskTree(tasks: Task[]): { taskMap: Map<string, TaskTreeNode>; rootTasks: TaskTreeNode[] } {
  const taskMap = new Map<string, TaskTreeNode>();
  const rootTasks: TaskTreeNode[] = [];
  
  // Create task nodes
  tasks.forEach(task => {
    taskMap.set(task.id, { ...task, children: [] });
  });
  
  // Build hierarchy
  tasks.forEach(task => {
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
 * Get tasks for a specific repo
 */
export function getTasksForRepo(scope: Scope, tasks: Task[]): Task[] {
  if (scope === 'workspace') {
    // Return tasks with no repo (workspace-level tasks)
    return tasks.filter(t => t.repo.length === 0);
  }
  // Return tasks for specific repo
  return tasks.filter(t => t.repo.includes(scope));
}

/**
 * Get status class for a task
 */
export function getStatusClass(status: string): string {
  const statusMap: Record<string, string> = {
    'pending': 'status-pending',
    'ready': 'status-ready',
    'running': 'status-running',
    'blocked_by_task': 'status-blocked-task',
    'blocked_by_human': 'status-blocked-human',
    'waiting': 'status-waiting',
    'complete': 'status-complete',
    'cancelled': 'status-cancelled',
  };
  return statusMap[status] || 'status-pending';
}
