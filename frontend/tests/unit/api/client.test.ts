/**
 * Unit Tests for API Client
 * 
 * Tests the REST API client for all endpoints.
 */

import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import {
  getTasks,
  getTask,
  createTask,
  updateTask,
  cancelTask,
  getRepos,
  getStatus,
  getBlocked,
  getPending,
  getConfig,
  interjectWorkspace,
  interjectRepo,
} from '../../../src/api/client';

// Mock fetch
const mockFetch = vi.fn();
global.fetch = mockFetch;

describe('API Client - Tasks', () => {
  beforeEach(() => {
    mockFetch.mockClear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe('getTasks', () => {
    it('fetches all tasks without filters', async () => {
      const mockTasks = { tasks: [{ id: '1', title: 'Test' }], count: 1 };
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => mockTasks,
      });

      const result = await getTasks();

      expect(mockFetch).toHaveBeenCalledWith('/tasks', {
        headers: { 'Content-Type': 'application/json' },
      });
      expect(result).toEqual(mockTasks);
    });

    it('applies status filter', async () => {
      const mockTasks = { tasks: [], count: 0 };
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => mockTasks,
      });

      await getTasks({ status: 'ready' });

      expect(mockFetch).toHaveBeenCalledWith('/tasks?status=ready', expect.any(Object));
    });

    it('applies repo filter', async () => {
      const mockTasks = { tasks: [], count: 0 };
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => mockTasks,
      });

      await getTasks({ repo: 'test-repo' });

      expect(mockFetch).toHaveBeenCalledWith('/tasks?repo=test-repo', expect.any(Object));
    });

    it('applies all filter', async () => {
      const mockTasks = { tasks: [], count: 0 };
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => mockTasks,
      });

      await getTasks({ all: true });

      expect(mockFetch).toHaveBeenCalledWith('/tasks?all=true', expect.any(Object));
    });

    it('handles API errors', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 500,
        statusText: 'Internal Server Error',
      });

      await expect(getTasks()).rejects.toThrow();
    });
  });

  describe('getTask', () => {
    it('fetches single task by ID', async () => {
      const mockTask = { id: 'abc123', title: 'Test Task' };
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => mockTask,
      });

      const result = await getTask('abc123');

      expect(mockFetch).toHaveBeenCalledWith('/tasks/abc123', expect.any(Object));
      expect(result).toEqual(mockTask);
    });

    it('handles 404 for non-existent task', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 404,
      });

      await expect(getTask('nonexistent')).rejects.toThrow();
    });
  });

  describe('createTask', () => {
    it('creates a new task with minimal fields', async () => {
      const newTask = { title: 'New Task' };
      const createdTask = { ...newTask, id: 'new123', status: 'ready' };
      
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => createdTask,
      });

      const result = await createTask(newTask);

      expect(mockFetch).toHaveBeenCalledWith('/tasks', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newTask),
      });
      expect(result).toEqual(createdTask);
    });

    it('creates a task with all fields', async () => {
      const newTask = {
        title: 'Full Task',
        description: 'Description',
        repo: ['test-repo'],
        role: 'coder',
        target_files: ['src/test.ts'],
        importance: 0.8,
        urgency: 0.9,
      };
      const createdTask = { ...newTask, id: 'full123' };
      
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => createdTask,
      });

      const result = await createTask(newTask);

      expect(mockFetch).toHaveBeenCalledWith('/tasks', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newTask),
      });
      expect(result).toEqual(createdTask);
    });

    it('validates required title field', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 400,
      });

      await expect(createTask({} as any)).rejects.toThrow();
    });
  });

  describe('updateTask', () => {
    it('updates task fields', async () => {
      const updates = { title: 'Updated Title', importance: 0.9 };
      const updatedTask = { id: 'abc123', ...updates };
      
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => updatedTask,
      });

      const result = await updateTask('abc123', updates);

      expect(mockFetch).toHaveBeenCalledWith('/tasks/abc123', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updates),
      });
      expect(result).toEqual(updatedTask);
    });

    it('handles non-existent task', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 404,
      });

      await expect(updateTask('nonexistent', { title: 'Test' })).rejects.toThrow();
    });
  });

  describe('cancelTask', () => {
    it('cancels a task', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ ok: true, id: 'abc123' }),
      });

      const result = await cancelTask('abc123');

      expect(mockFetch).toHaveBeenCalledWith('/tasks/abc123', {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
      });
      expect(result.ok).toBe(true);
    });
  });
});

describe('API Client - Repositories', () => {
  beforeEach(() => {
    mockFetch.mockClear();
  });

  describe('getRepos', () => {
    it('fetches all repositories', async () => {
      const mockRepos = { repos: [{ name: 'test-repo', remote: 'https://...' }] };
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => mockRepos,
      });

      const result = await getRepos();

      expect(mockFetch).toHaveBeenCalledWith('/repos', expect.any(Object));
      expect(result).toEqual(mockRepos);
    });

    it('handles empty repo list', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ repos: [] }),
      });

      const result = await getRepos();

      expect(result.repos).toEqual([]);
    });
  });
});

describe('API Client - Status & Health', () => {
  beforeEach(() => {
    mockFetch.mockClear();
  });

  describe('getStatus', () => {
    it('fetches current agent status', async () => {
      const mockStatus = { idle: true, stopped: false, blocked: false };
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => mockStatus,
      });

      const result = await getStatus();

      expect(mockFetch).toHaveBeenCalledWith('/status', expect.any(Object));
      expect(result).toEqual(mockStatus);
    });
  });

  describe('getBlocked', () => {
    it('fetches blocked tasks report', async () => {
      const mockReport = {
        report: {
          human: [{ id: '1', title: 'Blocked', blocking_reason: 'Review' }],
          dependencies: [],
          waiting: [],
        },
      };
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => mockReport,
      });

      const result = await getBlocked();

      expect(mockFetch).toHaveBeenCalledWith('/blocked', expect.any(Object));
      expect(result).toEqual(mockReport);
    });
  });

  describe('getPending', () => {
    it('fetches pending clarification question', async () => {
      const mockPending = { pending: 'What do you want?' };
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => mockPending,
      });

      const result = await getPending();

      expect(mockFetch).toHaveBeenCalledWith('/pending', expect.any(Object));
      expect(result).toEqual(mockPending);
    });

    it('handles no pending question', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ pending: null }),
      });

      const result = await getPending();

      expect(result.pending).toBeNull();
    });
  });
});

describe('API Client - Configuration', () => {
  beforeEach(() => {
    mockFetch.mockClear();
  });

  describe('getConfig', () => {
    it('fetches workspace configuration', async () => {
      const mockConfig = {
        coder_model: 'ollama:qwen3.5:4b',
        manager_model: 'ollama:qwen3.5:9b',
        server_port: 8080,
      };
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => mockConfig,
      });

      const result = await getConfig();

      expect(mockFetch).toHaveBeenCalledWith('/config', expect.any(Object));
      expect(result).toEqual(mockConfig);
    });
  });
});

describe('API Client - Interjections', () => {
  beforeEach(() => {
    mockFetch.mockClear();
  });

  describe('interjectWorkspace', () => {
    it('sends workspace-wide interjection', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ ok: true, manager_task_id: 'mgr123' }),
      });

      const result = await interjectWorkspace('Hello workspace');

      expect(mockFetch).toHaveBeenCalledWith('/interject/workspace', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: 'Hello workspace' }),
      });
      expect(result.ok).toBe(true);
    });

    it('validates non-empty message', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 400,
      });

      await expect(interjectWorkspace('')).rejects.toThrow();
    });
  });

  describe('interjectRepo', () => {
    it('sends repo-scoped interjection', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ ok: true, manager_task_id: 'mgr123', repo: 'test-repo' }),
      });

      const result = await interjectRepo('test-repo', 'Hello repo');

      expect(mockFetch).toHaveBeenCalledWith('/interject/repo/test-repo', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: 'Hello repo' }),
      });
      expect(result.ok).toBe(true);
    });

    it('encodes repo name in URL', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ ok: true }),
      });

      await interjectRepo('test/repo', 'Hello');

      expect(mockFetch).toHaveBeenCalledWith('/interject/repo/test%2Frepo', expect.any(Object));
    });
  });
});

describe('API Client - Error Handling', () => {
  beforeEach(() => {
    mockFetch.mockClear();
  });

  it('handles network errors', async () => {
    mockFetch.mockRejectedValueOnce(new Error('Network error'));

    await expect(getTasks()).rejects.toThrow('Network error');
  });

  it('handles 500 server errors', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 500,
      statusText: 'Internal Server Error',
    });

    await expect(getTasks()).rejects.toThrow();
  });

  it('handles 401 unauthorized', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 401,
    });

    await expect(getTasks()).rejects.toThrow();
  });

  it('handles timeout errors', async () => {
    mockFetch.mockRejectedValueOnce(new DOMException('Timeout', 'AbortError'));

    await expect(getTasks()).rejects.toThrow();
  });
});
