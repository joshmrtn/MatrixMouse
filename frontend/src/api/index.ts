import type { Task, Repo, BlockedTaskReport, DecisionConfig, Scope } from '../types';

/**
 * API client for MatrixMouse REST endpoints
 */

// Base API utilities
async function apiFetch<T>(url: string): Promise<T> {
  const response = await fetch(url);
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || response.statusText);
  }
  return response.json();
}

async function apiPost<T>(url: string, body: Record<string, unknown>): Promise<T> {
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || response.statusText);
  }
  return response.json();
}

async function apiPatch<T>(url: string, body: Record<string, unknown>): Promise<T> {
  const response = await fetch(url, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || response.statusText);
  }
  return response.json();
}

async function apiDelete<T>(url: string): Promise<T> {
  const response = await fetch(url, { method: 'DELETE' });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || response.statusText);
  }
  return response.json();
}

// Task endpoints
export async function getTasks(params?: { status?: string; repo?: string; all?: boolean }): Promise<{ tasks: Task[]; count: number }> {
  const qs = new URLSearchParams();
  if (params?.status) qs.append('status', params.status);
  if (params?.repo) qs.append('repo', params.repo);
  if (params?.all) qs.append('all', 'true');
  return apiFetch(`/tasks${qs.toString() ? `?${qs.toString()}` : ''}`);
}

export async function getTask(taskId: string): Promise<Task> {
  return apiFetch(`/tasks/${taskId}`);
}

export async function createTask(task: Partial<Task>): Promise<Task> {
  return apiPost('/tasks', task);
}

export async function updateTask(taskId: string, updates: Partial<Task>): Promise<Task> {
  return apiPatch(`/tasks/${taskId}`, updates);
}

export async function cancelTask(taskId: string): Promise<{ ok: boolean; id: string }> {
  return apiDelete(`/tasks/${taskId}`);
}

export async function answerTask(taskId: string, message: string): Promise<{ ok: boolean; task_id: string; unblocked: boolean }> {
  return apiPost(`/tasks/${taskId}/answer`, { message });
}

export async function interjectTask(taskId: string, message: string): Promise<{ ok: boolean; task_id: string }> {
  return apiPost(`/tasks/${taskId}/interject`, { message });
}

export async function submitDecision(
  taskId: string,
  decisionType: string,
  choice: string,
  note: string = '',
  metadata: Record<string, unknown> = {}
): Promise<Record<string, unknown>> {
  return apiPost(`/tasks/${taskId}/decision`, {
    decision_type: decisionType,
    choice,
    note,
    metadata,
  });
}

// Interjection endpoints
export async function interjectWorkspace(message: string): Promise<{ ok: boolean; manager_task_id: string }> {
  return apiPost('/interject/workspace', { message });
}

export async function interjectRepo(repoName: string, message: string): Promise<{ ok: boolean; manager_task_id: string; repo: string }> {
  return apiPost(`/interject/repo/${encodeURIComponent(repoName)}`, { message });
}

// Repo endpoints
export async function getRepos(): Promise<{ repos: Repo[] }> {
  return apiFetch('/repos');
}

export async function addRepo(remote: string, name?: string): Promise<{ ok: boolean; repo: Repo }> {
  return apiPost('/repos', { remote, name });
}

export async function removeRepo(name: string): Promise<{ ok: boolean; message: string }> {
  return apiDelete(`/repos/${name}`);
}

// Status endpoints
export async function getStatus(): Promise<Record<string, unknown>> {
  return apiFetch('/status');
}

export async function getBlocked(): Promise<{ report: BlockedTaskReport }> {
  return apiFetch('/blocked');
}

export async function getPending(): Promise<{ pending: string | null }> {
  return apiFetch('/pending');
}

// Config endpoints
export async function getConfig(): Promise<Record<string, unknown>> {
  return apiFetch('/config');
}

export async function updateConfig(values: Record<string, unknown>): Promise<{ ok: boolean; updated: string[] }> {
  return apiPatch('/config', { values });
}

// Control endpoints
export async function softStop(): Promise<{ ok: boolean; message: string }> {
  return apiPost('/stop', {});
}

export async function estop(): Promise<{ ok: boolean; message: string }> {
  return apiPost('/kill', {});
}

export async function pauseOrchestrator(): Promise<{ ok: boolean; paused: boolean }> {
  return apiPost('/orchestrator/pause', {});
}

export async function resumeOrchestrator(): Promise<{ ok: boolean; paused: boolean }> {
  return apiPost('/orchestrator/resume', {});
}

// Context endpoint
export async function getContext(repo?: string): Promise<{ messages: Array<{ role: string; content: string }>; count: number }> {
  const qs = repo ? `?repo=${encodeURIComponent(repo)}` : '';
  return apiFetch(`/context${qs}`);
}
