/**
 * MatrixMouse Web UI - Main Entry Point
 * 
 * Initializes the application and wires up all components
 */

import { wsManager } from './api/websocket';
import * as api from './api';
import { getState, setState, setStates, subscribe, buildTaskTree, getTasksForRepo, getStatusClass } from './state';
import type { Task, Repo, Scope, DecisionConfig, BlockedTaskEntry } from './types';

// DOM Elements
const elements = {
  // Sidebar
  sidebar: document.getElementById('sidebar'),
  sidebarBackdrop: document.getElementById('sidebar-backdrop'),
  sbRepos: document.getElementById('sb-repos'),
  sbTaskTrees: document.getElementById('sb-task-trees'),
  sbBottom: document.getElementById('sb-bottom'),
  
  // Main panels
  chatPanel: document.getElementById('chat-panel'),
  tasksPanel: document.getElementById('tasks-panel'),
  statusPanel: document.getElementById('status-panel'),
  settingsPanel: document.getElementById('settings-panel'),
  
  // Chat panel
  log: document.getElementById('log'),
  msgInput: document.getElementById('msg-input') as HTMLInputElement,
  sendBtn: document.getElementById('send-btn'),
  clarification: document.getElementById('clarification'),
  clarInput: document.getElementById('clar-input') as HTMLInputElement,
  
  // Header
  vStatus: document.getElementById('v-status'),
  connDot: document.getElementById('conn-dot'),
  connLabel: document.getElementById('conn-label'),
  
  // Modals
  confirmationModal: document.getElementById('confirmation-modal-overlay'),
  estopModal: document.getElementById('modal-overlay'),
};

// Initialize application
export function init(): void {
  console.log('MatrixMouse UI initializing...');
  
  // Connect WebSocket
  wsManager.connect();
  setupWebSocketHandlers();
  
  // Load initial data
  loadInitialData();
  
  // Setup event listeners
  setupEventListeners();
  
  // Subscribe to state changes
  subscribe(render);
  
  console.log('MatrixMouse UI initialized');
}

async function loadInitialData(): Promise<void> {
  try {
    // Load repos
    const reposData = await api.getRepos();
    setState('repos', reposData.repos);
    renderRepos();
    
    // Load tasks
    const tasksData = await api.getTasks({ all: true });
    setState('tasks', tasksData.tasks);
    renderTaskTrees();
    
    // Load status
    const status = await api.getStatus();
    setState('status', status);
    renderStatus(status);
    
    // Load config for settings panel
    // (loaded on-demand when settings tab is opened)
  } catch (error) {
    console.error('Failed to load initial data:', error);
  }
}

function setupWebSocketHandlers(): void {
  wsManager.onStatusUpdate((data) => {
    setState('status', data);
    renderStatus(data);
  });
  
  wsManager.onClarificationRequest((question) => {
    setState('pendingQuestion', question);
    showClarification(question);
  });
  
  wsManager.onDecisionRequired((config) => {
    showConfirmationModal(config);
  });
  
  wsManager.onTaskTreeUpdate((tasks) => {
    setState('tasks', tasks);
    renderTaskTrees();
  });
  
  wsManager.onToken((text) => {
    appendToken(text);
  });
  
  wsManager.onThinking((text) => {
    appendThinking(text);
  });
}

function setupEventListeners(): void {
  // Send button
  elements.sendBtn?.addEventListener('click', sendInterjection);
  
  // Enter key in message input
  elements.msgInput?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      sendInterjection();
    }
  });
  
  // Enter key in clarification input
  elements.clarInput?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      sendAnswer();
    }
  });
  
  // Sidebar backdrop (mobile)
  elements.sidebarBackdrop?.addEventListener('click', closeSidebar);
  
  // E-STOP modal
  document.getElementById('btn-kill')?.addEventListener('click', showEstopModal);
  document.getElementById('modal-cancel')?.addEventListener('click', hideEstopModal);
  document.getElementById('modal-confirm')?.addEventListener('click', confirmEstop);
  
  // Stop button
  document.getElementById('btn-stop')?.addEventListener('click', async () => {
    try {
      await api.softStop();
      addEvent('system', 'sys', 'Soft stop requested — agent will halt after current tool call.');
    } catch (error) {
      addEvent('error', 'error', `Failed to request stop: ${error}`);
    }
  });
}

// Render functions
function render(): void {
  const state = getState();
  
  // Render based on current tab
  switch (state.currentTab) {
    case 'chat':
      renderChatPanel();
      break;
    case 'tasks':
      // Tasks panel renders on demand
      break;
    case 'status':
      renderStatusPanel();
      break;
    case 'settings':
      // Settings panel renders on demand
      break;
  }
}

function renderRepos(): void {
  const { repos } = getState();
  if (!elements.sbRepos) return;
  
  elements.sbRepos.innerHTML = '';
  
  repos.forEach(repo => {
    // Create repo item
    const item = document.createElement('div');
    item.className = 'sb-item';
    item.dataset.scope = repo.name;
    item.innerHTML = `
      <button class="sb-repo-expand" onclick="window.mm_toggleRepoTasks(event, '${repo.name}')">▶</button>
      <span class="sb-icon">⬡</span>
      <span class="sb-name">${escapeHtml(repo.name)}</span>
      <span class="sb-spinner"></span>
    `;
    item.onclick = (e) => {
      if ((e.target as HTMLElement).className !== 'sb-repo-expand') {
        selectScope(repo.name);
      }
    };
    elements.sbRepos?.appendChild(item);
    
    // Create task tree container
    const treeContainer = document.createElement('div');
    treeContainer.id = `sb-task-tree-${repo.name}`;
    treeContainer.className = 'sb-task-tree';
    elements.sbRepos?.appendChild(treeContainer);
  });
  
  // Add workspace task tree container
  const workspaceTreeContainer = document.createElement('div');
  workspaceTreeContainer.id = 'sb-task-tree-workspace';
  workspaceTreeContainer.className = 'sb-task-tree';
  elements.sbRepos?.appendChild(workspaceTreeContainer);
}

function renderTaskTrees(): void {
  const { tasks, repos, expandedTasks, selectedTask } = getState();
  const { rootTasks } = buildTaskTree(tasks);
  
  // Group tasks by repo
  const tasksByRepo: Record<string, Task[]> = {};
  repos.forEach(r => { tasksByRepo[r.name] = []; });
  tasksByRepo['workspace'] = [];
  
  rootTasks.forEach(task => {
    if (task.repo.length === 0) {
      tasksByRepo['workspace'].push(task);
    } else {
      task.repo.forEach(repoName => {
        if (tasksByRepo[repoName]) {
          tasksByRepo[repoName].push(task);
        }
      });
    }
  });
  
  // Render task trees for each repo
  repos.forEach(repo => {
    const treeContainer = document.getElementById(`sb-task-tree-${repo.name}`);
    if (!treeContainer) return;
    
    treeContainer.innerHTML = '';
    const repoTasks = tasksByRepo[repo.name] || [];
    
    repoTasks.forEach(task => {
      const taskNode = renderTaskTreeNode(task, 0, expandedTasks, selectedTask);
      treeContainer.appendChild(taskNode);
    });
    
    // Show/hide based on tasks
    if (repoTasks.length > 0) {
      // Keep collapsed by default - user must click to expand
    } else {
      treeContainer.classList.remove('visible');
    }
  });
  
  // Render workspace task tree
  const workspaceTreeContainer = document.getElementById('sb-task-tree-workspace');
  if (workspaceTreeContainer) {
    workspaceTreeContainer.innerHTML = '';
    const workspaceTasks = tasksByRepo['workspace'] || [];
    
    workspaceTasks.forEach(task => {
      const taskNode = renderTaskTreeNode(task, 0, expandedTasks, selectedTask);
      workspaceTreeContainer.appendChild(taskNode);
    });
  }
}

function renderTaskTreeNode(
  task: Task,
  depth: number,
  expandedTasks: Set<string>,
  selectedTask: Task | null
): HTMLElement {
  const div = document.createElement('div');
  div.className = 'sb-task-item' + (selectedTask?.id === task.id ? ' active' : '');
  div.dataset.taskId = task.id;
  div.style.marginLeft = `${depth * 16}px`;
  
  const hasChildren = task.parent_task_id && task.parent_task_id !== ''; // Simplified - should check actual children
  const isExpanded = expandedTasks.has(task.id);
  
  div.innerHTML = `
    <button class="sb-task-expand" data-task-id="${task.id}">${hasChildren ? (isExpanded ? '▼' : '▶') : '•'}</button>
    <span class="sb-task-status ${getStatusClass(task.status)}"></span>
    <span class="sb-task-title">${escapeHtml(task.title)}</span>
  `;
  
  div.onclick = (e) => {
    const target = e.target as HTMLElement;
    if (target.className === 'sb-task-expand') {
      toggleTaskExpand(task.id);
    } else {
      selectTask(task.id);
    }
  };
  
  return div;
}

function renderStatus(status: Record<string, unknown>): void {
  if (!elements.vStatus) return;
  
  const v = elements.vStatus;
  if (status.stopped as boolean) {
    v.textContent = 'STOPPED';
    v.className = 'val stopped';
  } else if (status.blocked as boolean) {
    v.textContent = 'BLOCKED';
    v.className = 'val blocked';
  } else if (status.idle as boolean) {
    v.textContent = 'idle';
    v.className = 'val';
  } else {
    v.textContent = 'running';
    v.className = 'val active';
  }
}

function renderChatPanel(): void {
  const { selectedTask, scope } = getState();
  
  // Update scope label
  const scopeLabel = document.getElementById('chat-scope-label');
  if (scopeLabel) {
    scopeLabel.textContent = selectedTask
      ? `Task: ${selectedTask.title}`
      : `channel: ${scope === 'workspace' ? 'workspace' : scope}`;
  }
  
  // Update input placeholder
  if (elements.msgInput) {
    elements.msgInput.placeholder = selectedTask
      ? 'Message task agent...'
      : scope === 'workspace'
        ? 'Message agent (workspace)...'
        : `Message agent (${scope})...`;
  }
}

function renderStatusPanel(): void {
  const { blockedReport } = getState();
  
  if (!blockedReport) {
    // Load blocked report
    api.getBlocked().then(({ report }) => {
      setState('blockedReport', report);
      renderStatusPanel();
    });
    return;
  }
  
  renderBlockedSection('status-list-human', blockedReport.human);
  renderBlockedSection('status-list-deps', blockedReport.dependencies);
  renderBlockedSection('status-list-waiting', blockedReport.waiting);
}

function renderBlockedSection(elementId: string, entries: BlockedTaskEntry[]): void {
  const element = document.getElementById(elementId);
  if (!element) return;
  
  if (entries.length === 0) {
    element.innerHTML = '<div style="padding:10px;color:var(--text3)">No tasks in this category.</div>';
    return;
  }
  
  element.innerHTML = entries.map(entry => `
    <div class="status-task-row" data-task-id="${entry.id}">
      <div class="status-task-title">${escapeHtml(entry.title)}</div>
      <div class="status-task-reason">${escapeHtml(entry.blocking_reason)}</div>
    </div>
  `).join('');
  
  // Add click handlers to navigate to task
  element.querySelectorAll('.status-task-row').forEach(row => {
    row.addEventListener('click', () => {
      const taskId = row.getAttribute('data-task-id');
      if (taskId) {
        selectTask(taskId);
      }
    });
  });
}

// Action functions
function selectScope(scope: Scope): void {
  setState('scope', scope);
  setState('selectedTask', null);
  setState('currentTab', 'chat');
  renderTaskTrees(); // Clear task highlight
  renderChatPanel();
  closeSidebar();
}

function selectTask(taskId: string): void {
  const { tasks } = getState();
  const task = tasks.find(t => t.id === taskId);
  if (!task) return;
  
  // Update scope based on task's repo(s)
  const repoList = task.repo || [];
  let scope: Scope = 'workspace';
  if (repoList.length === 1) {
    scope = repoList[0];
  } else if (repoList.length > 1) {
    scope = 'workspace'; // Multi-repo tasks are workspace-scoped
  }
  
  setState('scope', scope);
  setState('selectedTask', task);
  setState('currentTab', 'chat');
  renderTaskTrees(); // Update highlight
  renderChatPanel();
  
  // Load task conversation
  loadTaskConversation(task);
}

function toggleTaskExpand(taskId: string): void {
  const { expandedTasks } = getState();
  const newExpanded = new Set(expandedTasks);
  
  if (newExpanded.has(taskId)) {
    newExpanded.delete(taskId);
  } else {
    newExpanded.add(taskId);
  }
  
  setState('expandedTasks', newExpanded);
  renderTaskTrees();
}

async function sendInterjection(): Promise<void> {
  const { selectedTask, scope } = getState();
  const input = elements.msgInput;
  if (!input) return;
  
  const msg = input.value.trim();
  if (!msg) return;
  
  input.value = '';
  const timestamp = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  addEvent('you', 'you', msg, timestamp);
  
  try {
    if (selectedTask?.id) {
      await api.interjectTask(selectedTask.id, msg);
    } else if (scope === 'workspace') {
      await api.interjectWorkspace(msg);
    } else {
      await api.interjectRepo(scope as string, msg);
    }
  } catch (error) {
    addEvent('error', 'error', `Failed to send: ${error}`);
  }
}

async function sendAnswer(): Promise<void> {
  const { selectedTask } = getState();
  const input = elements.clarInput;
  if (!input) return;
  
  const reply = input.value.trim();
  if (!reply) return;
  
  input.value = '';
  addEvent('you', 'you', reply);
  hideClarification();
  
  try {
    if (selectedTask?.id) {
      await api.answerTask(selectedTask.id, reply);
    } else {
      await api.interjectWorkspace(reply);
    }
  } catch (error) {
    addEvent('error', 'error', `Failed to send answer: ${error}`);
  }
}

async function loadTaskConversation(task: Task): Promise<void> {
  const log = elements.log;
  if (!log) return;
  
  log.innerHTML = '';
  
  // Task header
  const headerDiv = document.createElement('div');
  headerDiv.style.cssText = 'padding:14px;border-bottom:1px solid var(--border);background:var(--bg1);margin-bottom:8px;flex-shrink:0;';
  const repoDisplay = task.repo.length === 0 ? 'workspace'
    : task.repo.length === 1 ? task.repo[0]
    : `multi-repo (${task.repo.join(', ')})`;
  
  headerDiv.innerHTML = `
    <div style="font-size:12px;font-weight:500;color:var(--text);margin-bottom:4px;">${escapeHtml(task.title)}</div>
    <div style="font-size:10px;color:var(--text3);">
      ID: ${task.id} | Status: ${task.status} | Role: ${task.role}
      ${task.branch ? `| Branch: ${escapeHtml(task.branch)}` : ''} | Repo: ${repoDisplay}
    </div>
  `;
  log.appendChild(headerDiv);
  
  // Context messages
  const contextMessages = task.context_messages || [];
  
  if (contextMessages.length === 0) {
    const emptyDiv = document.createElement('div');
    emptyDiv.style.cssText = 'padding:14px;color:var(--text3);';
    emptyDiv.textContent = 'No conversation yet.';
    log.appendChild(emptyDiv);
    return;
  }
  
  contextMessages.forEach(msg => {
    const role = msg.role || 'unknown';
    const content = msg.content || '';
    if (!content?.trim()) return;
    
    const bubbleDiv = document.createElement('div');
    bubbleDiv.className = `context-bubble ${role === 'user' ? 'user' : role === 'assistant' ? 'assistant' : 'system'}`;
    bubbleDiv.innerHTML = renderMarkdown(content);
    log.appendChild(bubbleDiv);
  });
  
  log.scrollTop = log.scrollHeight;
}

// Event log functions
let streamingRow: HTMLElement | null = null;
let thinkingRow: HTMLElement | null = null;

function addEvent(type: string, label: string, text: string, timestamp?: string): void {
  thinkingRow = null;
  streamingRow = null;
  
  const div = document.createElement('div');
  div.className = `ev ${type}`;
  
  let html = `
    <span class="ev-ts">${new Date().toTimeString().slice(0, 8)}</span>
    <span class="ev-lbl">${escapeHtml(label || type)}</span>
    <span class="ev-txt">${renderMarkdown(text)}</span>
  `;
  
  if (type === 'you' && timestamp) {
    html += `<span class="ev-receipt">sent at ${timestamp}</span>`;
  }
  
  div.innerHTML = html;
  elements.log?.appendChild(div);
  if (elements.log) {
    elements.log.scrollTop = elements.log.scrollHeight;
  }
}

function appendToken(text: string): void {
  const log = elements.log;
  if (!log) return;
  
  if (!streamingRow) {
    streamingRow = document.createElement('div');
    streamingRow.className = 'ev token';
    streamingRow.innerHTML = `
      <span class="ev-ts">${new Date().toTimeString().slice(0, 8)}</span>
      <span class="ev-lbl">agent</span>
      <span class="ev-txt" data-raw=""></span>
    `;
    log.appendChild(streamingRow);
  }
  
  const txtEl = streamingRow.querySelector('.ev-txt');
  if (txtEl) {
    const raw = (txtEl.getAttribute('data-raw') || '') + text;
    txtEl.setAttribute('data-raw', raw);
    txtEl.innerHTML = renderMarkdown(raw);
    log.scrollTop = log.scrollHeight;
  }
}

function appendThinking(text: string): void {
  const log = elements.log;
  if (!log) return;
  
  if (!thinkingRow) {
    thinkingRow = document.createElement('div');
    thinkingRow.className = 'ev thinking';
    thinkingRow.innerHTML = `
      <span class="ev-ts">${new Date().toTimeString().slice(0, 8)}</span>
      <span class="ev-lbl">thinking</span>
      <span class="ev-txt" data-raw=""></span>
    `;
    log.appendChild(thinkingRow);
  }
  
  const txtEl = thinkingRow.querySelector('.ev-txt');
  if (txtEl) {
    const raw = (txtEl.getAttribute('data-raw') || '') + text;
    txtEl.setAttribute('data-raw', raw);
    txtEl.textContent = raw; // Plain text for thinking
    log.scrollTop = log.scrollHeight;
  }
}

// Clarification functions
function showClarification(question: string): void {
  if (elements.clarification) {
    elements.clarification.classList.add('visible');
  }
  if (elements.clarInput) {
    elements.clarInput.value = '';
    elements.clarInput.focus();
  }
  const clarQuestion = document.getElementById('clar-question');
  if (clarQuestion) {
    clarQuestion.textContent = `🔔 ${question}`;
  }
  addEvent('blocked_human', 'blocked', question);
}

function hideClarification(): void {
  elements.clarification?.classList.remove('visible');
  if (elements.clarInput) {
    elements.clarInput.value = '';
  }
}

// Confirmation modal functions
function showConfirmationModal(config: DecisionConfig): void {
  const overlay = elements.confirmationModal;
  if (!overlay) return;
  
  const title = document.getElementById('confirmation-modal-title');
  const body = document.getElementById('confirmation-modal-body');
  const choices = document.getElementById('confirmation-modal-choices');
  const textContainer = document.getElementById('confirmation-modal-text-container');
  const textInput = document.getElementById('confirmation-modal-text-input') as HTMLInputElement;
  
  if (title) title.textContent = config.title;
  if (body) body.innerHTML = renderMarkdown(config.body);
  
  // Render choice buttons
  if (choices) {
    choices.innerHTML = '';
    config.choices.forEach(choice => {
      const btn = document.createElement('button');
      btn.textContent = choice.label;
      btn.onclick = () => handleModalResponse(config, choice.value);
      choices.appendChild(btn);
    });
  }
  
  // Show/hide text input
  if (textContainer && textInput) {
    if (config.requireText) {
      textContainer.style.display = 'block';
      textInput.placeholder = config.textPlaceholder || 'Please provide details...';
      textInput.value = '';
    } else {
      textContainer.style.display = 'none';
    }
  }
  
  overlay.classList.add('visible');
}

async function handleModalResponse(config: DecisionConfig, choice: string): Promise<void> {
  const textInput = document.getElementById('confirmation-modal-text-input') as HTMLInputElement;
  const note = textInput?.value.trim() || '';
  
  // Validate required text
  if (config.requireText && !note) {
    if (textInput) {
      textInput.style.borderColor = 'var(--red)';
    }
    return;
  }
  
  try {
    await api.submitDecision(config.taskId, config.decisionType, choice, note);
    hideConfirmationModal();
  } catch (error) {
    addEvent('error', 'error', `Failed to submit decision: ${error}`);
  }
}

function hideConfirmationModal(): void {
  elements.confirmationModal?.classList.remove('visible');
}

// E-STOP modal functions
function showEstopModal(): void {
  elements.estopModal?.classList.add('visible');
}

function hideEstopModal(): void {
  elements.estopModal?.classList.remove('visible');
}

async function confirmEstop(): Promise<void> {
  hideEstopModal();
  try {
    await api.estop();
    addEvent('error', 'error', 'E-STOP engaged. Service shutting down.');
  } catch (error) {
    addEvent('error', 'error', `E-STOP signal sent: ${error}`);
  }
}

// Sidebar functions
function closeSidebar(): void {
  elements.sidebar?.classList.remove('open');
  elements.sidebarBackdrop?.classList.remove('visible');
}

// Utility functions
function escapeHtml(text: string): string {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

function renderMarkdown(raw: string): string {
  // Simplified markdown renderer - same logic as original
  const placeholders: string[] = [];
  
  function stash(html: string): string {
    const token = `\x00${placeholders.length}\x00`;
    placeholders.push(html);
    return token;
  }
  
  function restore(s: string): string {
    return s.replace(/\x00(\d+)\x00/g, (_, i) => placeholders[+i]);
  }
  
  let s = raw;
  
  // Fenced code blocks
  s = s.replace(/```([^\n`]*)\n([\s\S]*?)```/g, (_, lang, code) => {
    const cls = lang.trim() ? ` class="lang-${escapeHtml(lang.trim())}"` : '';
    return stash(`<pre><code${cls}>${escapeHtml(code.trimEnd())}</code></pre>`);
  });
  
  // Inline code
  s = s.replace(/`([^`\n]+)`/g, (_, code) => stash(`<code>${escapeHtml(code)}</code>`));
  
  // Headers
  s = s.replace(/^(#{1,3})\s+(.+)/gm, (_, level, text) => {
    return `<h${level}>${text}</h${level}>`;
  });
  
  // Bold
  s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  
  // Italic
  s = s.replace(/(?<![_\w])_([^_]+)_(?![_\w])/g, '<em>$1</em>');
  s = s.replace(/(?<!\*)\*([^*]+)\*(?!\*)/g, '<em>$1</em>');
  
  return restore(s);
}

// Export functions for HTML onclick handlers
(window as unknown as Record<string, unknown>).mm_toggleRepoTasks = function toggleRepoTasks(event: Event, repoName: string): void {
  event.stopPropagation();
  const treeContainer = document.getElementById(`sb-task-tree-${repoName}`);
  const expandBtn = (event.target as HTMLElement);
  
  if (treeContainer) {
    const isVisible = treeContainer.classList.contains('visible');
    if (isVisible) {
      treeContainer.classList.remove('visible');
      expandBtn.textContent = '▶';
    } else {
      treeContainer.classList.add('visible');
      expandBtn.textContent = '▼';
    }
  }
};

// Initialize on DOM ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
