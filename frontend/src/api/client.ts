/**
 * API client for MatrixMouse REST endpoints
 */

import type {
  Task,
  Repo,
  BlockedTaskReport,
  StatusResponse,
  ConfigResponse,
  TasksResponse,
  TaskCreateRequest,
  TaskUpdateRequest,
  InterjectionRequest,
  DecisionRequest,
  ConfigPatchRequest,
} from '../types';

/**
 * Base API URL - Vite dev server proxies to backend
 */
const API_BASE = '';

/**
 * Generic API error
 */
export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public detail?: string
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

/**
 * Make an API request
 */
async function request<T>(
  url: string,
  options: RequestInit = {}
): Promise<T> {
  const response = await fetch(`${API_BASE}${url}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options.headers,
    },
  });

  if (!response.ok) {
    let detail: string | undefined;
    try {
      const data = await response.json();
      detail = data.detail;
    } catch {
      // Ignore JSON parse errors
    }

    throw new ApiError(
      `API request failed: ${response.status} ${response.statusText}`,
      response.status,
      detail
    );
  }

  // Handle empty responses
  if (response.status === 204) {
    return {} as T;
  }

  return response.json();
}

// ============================================================================
// Task Endpoints
// ============================================================================

/**
 * Get all tasks with optional filtering
 */
export async function getTasks(params?: {
  status?: string;
  repo?: string;
  all?: boolean;
}): Promise<TasksResponse> {
  const searchParams = new URLSearchParams();
  if (params?.status) searchParams.append('status', params.status);
  if (params?.repo) searchParams.append('repo', params.repo);
  if (params?.all) searchParams.append('all', 'true');

  const qs = searchParams.toString();
  return request<TasksResponse>(`/tasks${qs ? `?${qs}` : ''}`);
}

/**
 * Get a single task by ID
 */
export async function getTask(taskId: string): Promise<Task> {
  return request<Task>(`/tasks/${taskId}`);
}

/**
 * Get task dependencies (tasks that block this one)
 */
export async function getTaskDependencies(taskId: string): Promise<{
  task_id: string;
  dependencies: Task[];
  count: number;
}> {
  return request(`/tasks/${taskId}/dependencies`);
}

/**
 * Create a new task
 */
export async function createTask(task: TaskCreateRequest): Promise<Task> {
  return request<Task>('/tasks', {
    method: 'POST',
    body: JSON.stringify(task),
  });
}

/**
 * Update a task
 */
export async function updateTask(
  taskId: string,
  updates: TaskUpdateRequest
): Promise<Task> {
  return request<Task>(`/tasks/${taskId}`, {
    method: 'PATCH',
    body: JSON.stringify(updates),
  });
}

/**
 * Cancel a task
 */
export async function cancelTask(taskId: string): Promise<{ ok: boolean; id: string }> {
  return request(`/tasks/${taskId}`, {
    method: 'DELETE',
  });
}

/**
 * Send interjection to a specific task
 */
export async function interjectTask(
  taskId: string,
  message: string
): Promise<{ ok: boolean; task_id: string }> {
  return request(`/tasks/${taskId}/interject`, {
    method: 'POST',
    body: JSON.stringify({ message }),
  });
}

/**
 * Answer a clarification question for a task
 */
export async function answerTask(
  taskId: string,
  message: string
): Promise<{ ok: boolean; task_id: string; unblocked: boolean }> {
  return request(`/tasks/${taskId}/answer`, {
    method: 'POST',
    body: JSON.stringify({ message }),
  });
}

/**
 * Submit a decision for a blocked task
 */
export async function submitDecision(
  taskId: string,
  decisionType: string,
  choice: string,
  note?: string,
  metadata?: Record<string, unknown>
): Promise<Record<string, unknown>> {
  return request(`/tasks/${taskId}/decision`, {
    method: 'POST',
    body: JSON.stringify({
      decision_type: decisionType,
      choice,
      note: note || '',
      metadata: metadata || {},
    }),
  });
}

// ============================================================================
// Interjection Endpoints
// ============================================================================

/**
 * Send workspace-wide interjection
 */
export async function interjectWorkspace(
  message: string
): Promise<{ ok: boolean; manager_task_id: string }> {
  return request('/interject/workspace', {
    method: 'POST',
    body: JSON.stringify({ message }),
  });
}

/**
 * Send repo-scoped interjection
 */
export async function interjectRepo(
  repoName: string,
  message: string
): Promise<{ ok: boolean; manager_task_id: string; repo: string }> {
  return request(`/interject/repo/${encodeURIComponent(repoName)}`, {
    method: 'POST',
    body: JSON.stringify({ message }),
  });
}

// ============================================================================
// Repository Endpoints
// ============================================================================

/**
 * Get all repositories
 */
export async function getRepos(): Promise<{ repos: Repo[] }> {
  return request('/repos');
}

/**
 * Add a new repository
 */
export async function addRepo(
  remote: string,
  name?: string
): Promise<{ ok: boolean; repo: Repo }> {
  return request('/repos', {
    method: 'POST',
    body: JSON.stringify({ remote, name }),
  });
}

/**
 * Remove a repository
 */
export async function removeRepo(name: string): Promise<{ ok: boolean; message: string }> {
  return request(`/repos/${name}`, {
    method: 'DELETE',
  });
}

// ============================================================================
// Status Endpoints
// ============================================================================

/**
 * Get current agent status
 */
export async function getStatus(): Promise<StatusResponse> {
  return request<StatusResponse>('/status');
}

/**
 * Get blocked/waiting tasks report
 */
export async function getBlocked(): Promise<{ report: BlockedTaskReport }> {
  return request('/blocked');
}

/**
 * Get pending clarification question
 */
export async function getPending(): Promise<{ pending: string | null }> {
  return request('/pending');
}

// ============================================================================
// Config Endpoints
// ============================================================================

/**
 * Get workspace configuration
 */
export async function getConfig(): Promise<ConfigResponse> {
  return request<ConfigResponse>('/config');
}

/**
 * Update workspace configuration
 */
export async function updateConfig(
  values: ConfigPatchRequest['values']
): Promise<{ ok: boolean; updated: string[] }> {
  return request('/config', {
    method: 'PATCH',
    body: JSON.stringify({ values }),
  });
}

/**
 * Get repo-level configuration
 */
export async function getRepoConfig(repoName: string): Promise<{
  local: Record<string, unknown>;
  committed: Record<string, unknown>;
  merged: Record<string, unknown>;
}> {
  return request(`/config/repos/${encodeURIComponent(repoName)}`);
}

/**
 * Update repo-level configuration
 */
export async function updateRepoConfig(
  repoName: string,
  values: ConfigPatchRequest['values'],
  commit = false
): Promise<{ ok: boolean; updated: string[] }> {
  const qs = commit ? '?commit=true' : '';
  return request(`/config/repos/${encodeURIComponent(repoName)}${qs}`, {
    method: 'PATCH',
    body: JSON.stringify({ values }),
  });
}

// ============================================================================
// Control Endpoints
// ============================================================================

/**
 * Request soft stop
 */
export async function softStop(): Promise<{ ok: boolean; message: string }> {
  return request('/stop', {
    method: 'POST',
  });
}

/**
 * Request emergency stop
 */
export async function estop(): Promise<{ ok: boolean; message: string }> {
  return request('/kill', {
    method: 'POST',
  });
}

/**
 * Get E-STOP status
 */
export async function getEstopStatus(): Promise<{ engaged: boolean; message?: string }> {
  return request('/estop');
}

/**
 * Reset E-STOP
 */
export async function resetEstop(): Promise<{ ok: boolean; message: string }> {
  return request('/estop/reset', {
    method: 'POST',
  });
}

/**
 * Pause orchestrator
 */
export async function pauseOrchestrator(): Promise<{ ok: boolean; paused: boolean }> {
  return request('/orchestrator/pause', {
    method: 'POST',
  });
}

/**
 * Resume orchestrator
 */
export async function resumeOrchestrator(): Promise<{ ok: boolean; paused: boolean }> {
  return request('/orchestrator/resume', {
    method: 'POST',
  });
}

/**
 * Get orchestrator status
 */
export async function getOrchestratorStatus(): Promise<{
  paused: boolean;
  stopped: boolean;
  status: StatusResponse;
}> {
  return request('/orchestrator/status');
}

// ============================================================================
// Context Endpoint
// ============================================================================

/**
 * Get context messages for a scope
 * @deprecated GET /tasks/{task_id} already returns context_messages.
 * This function is kept for backward compatibility only and will be removed.
 */
export async function getContext(repo?: string): Promise<{
  messages: Array<{ role: string; content: string }>;
  count: number;
  estimated_tokens: number;
}> {
  const qs = repo ? `?repo=${encodeURIComponent(repo)}` : '';
  return request(`/context${qs}`);
}
