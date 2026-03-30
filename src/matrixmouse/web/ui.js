'use strict';

// ─── State ────────────────────────────────────────────────────────
let currentScope = 'workspace';
let currentTab = 'chat';
let currentSettingsSection = 'ws-general';
let settingsTarget = 'workspace';
let repos = [];
let pendingSettingsChanges = {};
let streamingRow = null;  // current token accumulation row
let thinkingRow = null;  // current thinking accumulation row
let inferring = false; // true while waiting for model response

// New state variables for UI overhaul
let tasks = [];  // full task list for client-side tree building
let selectedTask = null;  // currently selected task for task panel view
let decisionModal = null;  // current pending decision modal state
let interjectionReceipts = {};  // map of task_id to {received_at, read_at} timestamps

// Task tree expansion state
let expandedTasks = {};  // set of task_ids that are expanded

// ─── Utilities ────────────────────────────────────────────────────
function ts() { return new Date().toTimeString().slice(0, 8); }

function esc(s) {
  return String(s ?? '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

function escLines(s) { return esc(s).replace(/\n/g, '<br>'); }

function $id(id) { return document.getElementById(id); }

function formatTime(isoString) {
  if (!isoString) return '';
  const d = new Date(isoString);
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function formatRelativeTime(isoString) {
  if (!isoString) return '';
  const d = new Date(isoString);
  const now = new Date();
  const diff = Math.floor((now - d) / 1000);
  if (diff < 60) return 'just now';
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return formatTime(isoString);
}

// ─── Sidebar (mobile toggle) ──────────────────────────────────────
function toggleSidebar() {
  $id('sidebar').classList.toggle('open');
  $id('sidebar-backdrop').classList.toggle('visible');
}

function closeSidebar() {
  $id('sidebar').classList.remove('open');
  $id('sidebar-backdrop').classList.remove('visible');
}

// ─── Navigation ───────────────────────────────────────────────────
function selectScope(scope) {
  currentScope = scope;
  currentTab = 'chat';

  document.querySelectorAll('.sb-item[data-scope]').forEach(el => {
    el.classList.toggle('active', el.dataset.scope === scope);
  });
  document.querySelectorAll('.sb-item[data-tab]').forEach(el => {
    el.classList.remove('active');
  });

  $id('chat-scope-label').textContent =
    'channel: ' + (scope === 'workspace' ? 'workspace' : scope);
  $id('msg-input').placeholder =
    scope === 'workspace'
      ? 'Message agent (workspace)...'
      : `Message agent (${scope})...`;

  showPanel('chat-panel');
  loadContext(scope);
}

function selectTab(tab) {
  currentTab = tab;

  document.querySelectorAll('.sb-item[data-scope]').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('.sb-item[data-tab]').forEach(el => {
    el.classList.toggle('active', el.dataset.tab === tab);
  });

  if (tab === 'tasks') {
    showPanel('tasks-panel');
    loadTasks();
  } else if (tab === 'settings') {
    showPanel('settings-panel');
    loadConfig();
  } else if (tab === 'status') {
    showPanel('status-panel');
    loadStatusDashboard();
  } else if (tab === 'chat') {
    showPanel('chat-panel');
    loadContext(currentScope);
  }
}

function showPanel(panelId) {
  document.querySelectorAll('.tab-panel').forEach(p => {
    p.classList.toggle('active', p.id === panelId);
  });
}

// ─── Settings nav ─────────────────────────────────────────────────
function selectSettingsSection(sectionKey) {
  currentSettingsSection = sectionKey;

  document.querySelectorAll('.settings-nav-item').forEach(el => {
    el.classList.toggle('active', el.dataset.section === sectionKey);
  });
  document.querySelectorAll('.settings-section').forEach(el => {
    el.classList.toggle('active', el.id === 's-' + sectionKey);
  });

  settingsTarget = sectionKey.startsWith('ws-')
    ? 'workspace'
    : sectionKey.replace('repo-', '');

  pendingSettingsChanges = {};
  $id('settings-save-bar').classList.remove('visible');
}

// ─── Header status ────────────────────────────────────────────────
function updateStatus(data) {
  $id('v-task').textContent = data.task || '—';
  $id('v-phase').textContent = data.phase || '—';
  $id('v-model').textContent = data.model || '—';
  $id('v-turns').textContent = data.turns ?? '—';

  const v = $id('v-status');
  if (data.stopped) {
    v.textContent = 'STOPPED'; v.className = 'val stopped';
  } else if (data.blocked) {
    v.textContent = 'BLOCKED'; v.className = 'val blocked';
  } else if (data.idle) {
    v.textContent = 'idle'; v.className = 'val';
    setInferring(false);
  } else {
    v.textContent = 'running'; v.className = 'val active';
  }

  // Update sidebar spinner for active repo
  updateSidebarSpinners(data);
}

function updateSidebarSpinners(data) {
  const activeRepo = data.repo || null;
  const isRunning = !data.idle && !data.stopped;

  // Workspace spinner
  const wsItem = document.querySelector('.sb-item[data-scope="workspace"]');
  if (wsItem) wsItem.classList.toggle('inferring', isRunning && !activeRepo);

  // Repo spinners
  document.querySelectorAll('.sb-item[data-scope]').forEach(el => {
    if (el.dataset.scope === 'workspace') return;
    el.classList.toggle('inferring', isRunning && el.dataset.scope === activeRepo);
  });
}

// ─── Inference bar ────────────────────────────────────────────────
function setInferring(on, stage) {
  inferring = on;
  const bar = $id('inference-bar');
  bar.classList.toggle('visible', on);
  if (on && stage) $id('inference-stage').textContent = stage;
}

// ─── Event log ────────────────────────────────────────────────────
const EVENT_LABELS = {
  tool_call: 'tool',
  tool_result: 'result',
  content: 'agent',
  token: 'agent',
  phase_change: 'phase →',
  escalation: 'escalate',
  blocked_human: 'blocked',
  complete: '✓ done',
  error: 'error',
  you: 'you',
  system: 'sys',
  clarification_request: 'clarification',
  thinking: 'thinking',
};

// ─── Markdown renderer ───────────────────────────────────────────
// Applies to agent content output only (content + token event types).
// Handles: fenced code blocks, inline code, headers, bold, italic,
// unordered lists, ordered lists.
//
// Processing uses a placeholder pass so code spans are extracted
// before any inline rules run — prevents bold/italic rules from
// firing inside code content.
//
// Does NOT apply to tool_result rows — those stay as plain text
// (see renderToolResult for JSON pretty-printing).

function renderMarkdown(raw) {
  const placeholders = [];

  // Helper: stash a literal HTML string and return a placeholder token
  function stash(html) {
    const token = `\x00${placeholders.length}\x00`;
    placeholders.push(html);
    return token;
  }

  // Helper: restore all placeholders
  function restore(s) {
    return s.replace(/\x00(\d+)\x00/g, (_, i) => placeholders[+i]);
  }

  let s = raw;

  // 1. Fenced code blocks  ```lang\n...\n```
  //    Extracted before any other processing.
  s = s.replace(/```([^\n`]*)\n([\s\S]*?)```/g, (_, lang, code) => {
    const cls = lang.trim() ? ` class="lang-${esc(lang.trim())}"` : '';
    return stash(`<pre><code${cls}>${esc(code.trimEnd())}</code></pre>`);
  });

  // 2. Inline code  `code`
  s = s.replace(/`([^`\n]+)`/g, (_, code) =>
    stash(`<code>${esc(code)}</code>`)
  );

  // Process line by line for block-level elements
  const lines = s.split('\n');
  const out = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    // 3. ATX headers  # / ## / ###
    const hm = line.match(/^(#{1,3})\s+(.+)/);
    if (hm) {
      const level = hm[1].length;
      out.push(`<h${level}>${inlinePass(hm[2])}</h${level}>`);
      i++; continue;
    }

    // 4. Unordered list block  - item  or  * item
    if (/^[-*]\s+/.test(line)) {
      const items = [];
      while (i < lines.length && /^[-*]\s+/.test(lines[i])) {
        items.push(`<li>${inlinePass(lines[i].replace(/^[-*]\s+/, ''))}</li>`);
        i++;
      }
      out.push(`<ul>${items.join('')}</ul>`);
      continue;
    }

    // 5. Ordered list block  1. item
    if (/^\d+\.\s+/.test(line)) {
      const items = [];
      while (i < lines.length && /^\d+\.\s+/.test(lines[i])) {
        items.push(`<li>${inlinePass(lines[i].replace(/^\d+\.\s+/, ''))}</li>`);
        i++;
      }
      out.push(`<ol>${items.join('')}</ol>`);
      continue;
    }

    // 6. Blank line → paragraph break
    if (line.trim() === '') {
      out.push('<br>');
      i++; continue;
    }

    // 7. Plain line — run inline rules
    out.push(inlinePass(line) + '<br>');
    i++;
  }

  return restore(out.join(''));
}

// Inline-level rules: bold, italic (runs on already-placeholder-sanitised text)
function inlinePass(s) {
  // Bold  **text**
  s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  // Italic  _text_  (not preceded/followed by another _)
  s = s.replace(/(?<![_\w])_([^_]+)_(?![_\w])/g, '<em>$1</em>');
  // Italic  *text*  (single asterisk, not **)
  s = s.replace(/(?<!\*)\*([^*]+)\*(?!\*)/g, '<em>$1</em>');
  return s;
}


// ─── Tool result renderer ────────────────────────────────────────
// Keeps output raw/plain but pretty-prints JSON when detected.
// Returns an HTML-safe string.

function renderToolResult(raw) {
  const trimmed = raw.trim();
  if ((trimmed.startsWith('{') || trimmed.startsWith('[')) && trimmed.length > 2) {
    try {
      const parsed = JSON.parse(trimmed);
      return `<pre>${esc(JSON.stringify(parsed, null, 2))}</pre>`;
    } catch (_) {
      // Not valid JSON — fall through to plain rendering
    }
  }
  return escLines(raw);
}


function renderEvText(type, text) {
  if (type === 'content') return renderMarkdown(text);
  if (type === 'tool_result') return renderToolResult(text);
  return escLines(text);
}


function addEvent(type, label, text, historical) {
  thinkingRow = null;
  streamingRow = null;
  const div = document.createElement('div');
  div.className = 'ev ' + type + (historical ? ' historical' : '');
  div.innerHTML =
    `<span class="ev-ts">${ts()}</span>` +
    `<span class="ev-lbl">${esc(label || type)}</span>` +
    `<span class="ev-txt">${renderEvText(type, text)}</span>`;
  const log = $id('log');
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
  return div;
}

// Streaming thinking/token accumulation

function appendThinking(text) {
  const log = $id('log');
  if (!thinkingRow) {
    thinkingRow = document.createElement('div');
    thinkingRow.className = 'ev thinking';
    thinkingRow.innerHTML =
      `<span class="ev-ts">${ts()}</span>` +
      `<span class="ev-lbl">thinking</span>` +
      `<span class="ev-txt" data-raw=""></span>`;
    log.appendChild(thinkingRow);
  }
  const txtEl = thinkingRow.querySelector('.ev-txt');
  const raw = (txtEl.dataset.raw || '') + text;
  txtEl.dataset.raw = raw;
  txtEl.innerHTML = escLines(raw);  // plain text, not markdown
  log.scrollTop = log.scrollHeight;
}

function appendToken(text) {
  const log = $id('log');
  if (!streamingRow) {
    streamingRow = document.createElement('div');
    streamingRow.className = 'ev token';
    streamingRow.innerHTML =
      `<span class="ev-ts">${ts()}</span>` +
      `<span class="ev-lbl">agent</span>` +
      `<span class="ev-txt" data-raw=""></span>`;
    log.appendChild(streamingRow);
    setInferring(false); // first token means model is responding
  }
  const txtEl = streamingRow.querySelector('.ev-txt');
  const raw = (txtEl.dataset.raw || '') + text;
  txtEl.dataset.raw = raw;
  txtEl.innerHTML = renderMarkdown(raw);
  log.scrollTop = log.scrollHeight;
}

// ─── Context history ──────────────────────────────────────────────
async function loadContext(scope) {
  const log = $id('log');
  log.innerHTML = ''; // clear on channel switch
  streamingRow = null;

  const repo = scope === 'workspace' ? null : scope;
  const qs = repo ? `?repo=${encodeURIComponent(repo)}` : '';

  try {
    const data = await apiFetch('/context' + qs);
    const messages = data.messages || [];

    if (!messages.length) return;

    // Separator
    const sep = document.createElement('div');
    sep.className = 'ev context-summary';
    sep.innerHTML =
      `<span class="ev-ts">—</span>` +
      `<span class="ev-lbl">context</span>` +
      `<span class="ev-txt">— current agent context (${messages.length} messages) —</span>`;
    log.appendChild(sep);

    messages.forEach(m => {
      const role = m.role || 'unknown';
      const content = m.content || '';
      if (!content.trim()) return;

      // Detect context summary blocks
      const isSummary = content.includes('[CONTEXT SUMMARY');
      const type = isSummary ? 'context-summary' : (role === 'assistant' ? 'content' : 'system');
      const label = isSummary ? 'summary' : role;

      const div = document.createElement('div');
      const snippet = content.slice(0, 400) + (content.length > 400 ? '…' : '');
      div.className = `ev ${type} historical`;
      div.innerHTML =
        `<span class="ev-ts">ctx</span>` +
        `<span class="ev-lbl">${esc(label)}</span>` +
        `<span class="ev-txt">${isSummary ? escLines(snippet) : renderMarkdown(snippet)}</span>`
      log.appendChild(div);
    });

    const endSep = document.createElement('div');
    endSep.className = 'ev context-summary';
    endSep.innerHTML =
      `<span class="ev-ts">—</span>` +
      `<span class="ev-lbl">live</span>` +
      `<span class="ev-txt">— live events follow —</span>`;
    log.appendChild(endSep);

    log.scrollTop = log.scrollHeight;
  } catch (e) {
    // Context endpoint may not be available — not an error
  }
}

// ─── Clarification banner ─────────────────────────────────────────
function showClarification(question) {
  $id('clar-question').textContent = '🔕 ' + question;
  $id('clarification').classList.add('visible');
  $id('clar-input').focus();
  addEvent('blocked_human', 'blocked', question);
  setInferring(false);
}

function hideClarification() {
  $id('clarification').classList.remove('visible');
  $id('clar-input').value = '';
}

async function sendAnswer() {
  const reply = $id('clar-input').value.trim();
  if (!reply) return;
  addEvent('you', 'you', reply);
  hideClarification();

  // Use /tasks/{id}/answer if we have a selected task, otherwise use old endpoint
  if (selectedTask && selectedTask.id) {
    await apiPost(`/tasks/${selectedTask.id}/answer`, { message: reply });
  } else {
    // Fallback to workspace/repo interjection for non-task clarification
    await apiPost('/interject', {
      message: reply,
      repo: currentScope === 'workspace' ? null : currentScope,
    });
  }
}

$id('clar-input').addEventListener('keydown', e => {
  if (e.key === 'Enter') sendAnswer();
});

// Poll for pending clarification every 5s as backup to WebSocket
setInterval(async () => {
  try {
    const data = await apiFetch('/pending');
    const clar = $id('clarification');
    if (data.pending && !clar.classList.contains('visible')) {
      showClarification(data.pending);
    } else if (!data.pending && clar.classList.contains('visible')) {
      hideClarification();
    }
  } catch (e) { }
}, 5000);

// ─── Interjection ─────────────────────────────────────────────────
async function sendInterjection() {
  const input = $id('msg-input');
  const msg = input.value.trim();
  if (!msg) return;
  input.value = '';
  addEvent('you', 'you', msg);

  // Use new scoped interjection endpoints
  if (selectedTask && selectedTask.id) {
    // Task-scoped interjection
    await apiPost(`/tasks/${selectedTask.id}/interject`, { message: msg });
  } else if (currentScope === 'workspace') {
    // Workspace-wide interjection
    await apiPost('/interject/workspace', { message: msg });
  } else {
    // Repo-scoped interjection
    await apiPost(`/interject/repo/${encodeURIComponent(currentScope)}`, { message: msg });
  }
}

$id('msg-input').addEventListener('keydown', e => {
  if (e.key === 'Enter') sendInterjection();
});

// ─── Soft stop ────────────────────────────────────────────────────
$id('btn-stop').onclick = async () => {
  try {
    await apiPost('/stop', {});
    addEvent('system', 'sys', 'Soft stop requested — agent will halt after current tool call.');
  } catch (e) {
    addEvent('error', 'error', 'Failed to request stop: ' + e.message);
  }
};

// ─── E-STOP modal ─────────────────────────────────────────────────
$id('btn-kill').onclick = () => {
  $id('modal-overlay').classList.add('visible');
};

function closeModal() {
  $id('modal-overlay').classList.remove('visible');
}

async function confirmKill() {
  closeModal();
  try {
    await apiPost('/kill', {});
    addEvent('error', 'error', 'E-STOP engaged. Service shutting down.');
  } catch (e) {
    addEvent('error', 'error', 'E-STOP signal sent. Service may have shut down.');
  }
}

$id('modal-overlay').addEventListener('click', e => {
  if (e.target === $id('modal-overlay')) closeModal();
});

// ─── Task Tree Building ───────────────────────────────────────────
function buildTaskTree() {
  // Build hierarchical tree from flat task list using parent_task_id
  // Only include non-terminal tasks (not COMPLETE or CANCELLED)
  const terminalStatuses = ['complete', 'cancelled'];
  const nonTerminalTasks = tasks.filter(t => !terminalStatuses.includes(t.status));

  const taskMap = {};
  const rootTasks = [];

  // First pass: create map and initialize children arrays
  nonTerminalTasks.forEach(task => {
    taskMap[task.id] = { ...task, children: [] };
  });

  // Second pass: build tree structure
  nonTerminalTasks.forEach(task => {
    const parent = taskMap[task.parent_task_id];
    if (parent) {
      parent.children.push(taskMap[task.id]);
    } else {
      rootTasks.push(taskMap[task.id]);
    }
  });

  return rootTasks;
}

function renderSidebarTaskTree() {
  const sbRepos = $id('sb-repos');
  if (!sbRepos) return;

  // Clear existing repo items but keep workspace item
  const workspaceItem = sbRepos.querySelector('.sb-item[data-scope="workspace"]');
  sbRepos.innerHTML = '';
  if (workspaceItem) {
    sbRepos.appendChild(workspaceItem);
  }

  // Add repos with their task trees
  repos.forEach(repo => {
    const repoItem = document.createElement('div');
    repoItem.className = 'sb-item sb-repo-item';
    repoItem.dataset.scope = repo.name;
    repoItem.innerHTML =
      `<span class="sb-icon">⬡</span>` +
      `<span class="sb-name">${esc(repo.name)}</span>` +
      `<span class="sb-spinner"></span>`;
    repoItem.onclick = (e) => {
      e.stopPropagation();
      selectScope(repo.name);
      closeSidebar();
    };
    sbRepos.appendChild(repoItem);

    // Build and render task tree for this repo
    const repoTasks = tasks.filter(t => t.repo && t.repo.includes(repo.name));
    if (repoTasks.length > 0) {
      const taskTreeContainer = document.createElement('div');
      taskTreeContainer.className = 'task-tree-container';
      taskTreeContainer.dataset.repo = repo.name;

      const tree = buildTaskTree().filter(t => t.repo && t.repo.includes(repo.name));
      tree.forEach(taskNode => {
        taskTreeContainer.appendChild(renderTaskTreeNode(taskNode, 0));
      });

      sbRepos.appendChild(taskTreeContainer);
    }
  });
}

function renderTaskTreeNode(taskNode, depth) {
  const container = document.createElement('div');
  container.className = 'task-tree-node';
  container.dataset.taskId = taskNode.id;
  container.style.paddingLeft = `${depth * 16 + 8}px`;

  const isExpanded = expandedTasks[taskNode.id];
  const hasChildren = taskNode.children && taskNode.children.length > 0;

  const node = document.createElement('div');
  node.className = 'task-tree-item';
  node.innerHTML = `
    <span class="task-expand-arrow ${hasChildren ? 'expandable' : ''} ${isExpanded ? 'expanded' : ''}">
      ${hasChildren ? (isExpanded ? '▼' : '▶') : '•'}
    </span>
    <span class="task-status-dot ${dotClass(taskNode.status)}"></span>
    <span class="task-tree-title">${esc(taskNode.title)}</span>
  `;

  node.onclick = (e) => {
    e.stopPropagation();
    if (hasChildren && e.target.classList.contains('task-expand-arrow')) {
      toggleTaskExpand(taskNode.id);
    } else {
      selectTask(taskNode.id);
    }
  };

  container.appendChild(node);

  // Render children if expanded
  if (hasChildren && isExpanded) {
    taskNode.children.forEach(child => {
      container.appendChild(renderTaskTreeNode(child, depth + 1));
    });
  }

  return container;
}

function toggleTaskExpand(taskId) {
  expandedTasks[taskId] = !expandedTasks[taskId];
  renderSidebarTaskTree();
}

function selectTask(taskId) {
  const task = tasks.find(t => t.id === taskId);
  if (!task) return;

  selectedTask = taskId;
  showTaskPanel(taskId);
  closeSidebar();
}

// ─── Task Panel ───────────────────────────────────────────────────
function showTaskPanel(taskId) {
  const task = tasks.find(t => t.id === taskId);
  if (!task) return;

  showPanel('task-panel');

  // Render task header
  $id('task-panel-title').textContent = task.title;
  $id('task-panel-status').className = `task-status-badge status-${task.status}`;
  $id('task-panel-status').textContent = task.status;
  $id('task-panel-repo').textContent = (task.repo || []).join(', ') || 'workspace';
  $id('task-panel-phase').textContent = task.phase || '—';

  // Render conversation
  renderTaskConversation(task);

  // Setup interjection input
  const interjectionInput = $id('task-interjection-input');
  if (interjectionInput) {
    interjectionInput.value = '';
    interjectionInput.onkeydown = (e) => {
      if (e.key === 'Enter') {
        sendTaskInterjection(taskId, interjectionInput.value);
      }
    };
  }
}

function renderTaskConversation(task) {
  const conversationContainer = $id('task-conversation');
  if (!conversationContainer) return;

  conversationContainer.innerHTML = '';

  const contextMessages = task.context_messages || [];
  if (!contextMessages.length) {
    conversationContainer.innerHTML = '<div class="no-messages">No conversation yet</div>';
    return;
  }

  contextMessages.forEach(msg => {
    const bubble = document.createElement('div');
    bubble.className = `conversation-bubble bubble-${msg.role}`;

    let content = '';
    if (msg.role === 'user') {
      content = escLines(msg.content || '');
    } else if (msg.role === 'assistant') {
      content = renderMarkdown(msg.content || '');
    } else if (msg.role === 'tool_call') {
      content = `<div class="tool-call-label">Tool Call</div>${escLines(msg.content || '')}`;
    } else if (msg.role === 'tool_result') {
      content = `<div class="tool-result-label">Tool Result</div>${renderToolResult(msg.content || '')}`;
    } else {
      content = escLines(msg.content || '');
    }

    bubble.innerHTML = `
      <div class="bubble-role">${esc(msg.role)}</div>
      <div class="bubble-content">${content}</div>
    `;

    conversationContainer.appendChild(bubble);
  });

  // Scroll to bottom
  conversationContainer.scrollTop = conversationContainer.scrollHeight;
}

async function sendTaskInterjection(taskId, message) {
  const input = $id('task-interjection-input');
  const msg = typeof message === 'string' ? message.trim() : input?.value.trim();
  if (!msg) return;

  if (input) input.value = '';

  // Add to conversation view
  const conversationContainer = $id('task-conversation');
  const bubble = document.createElement('div');
  bubble.className = 'conversation-bubble bubble-user interjection';
  bubble.innerHTML = `
    <div class="bubble-role">interjection</div>
    <div class="bubble-content">${escLines(msg)}</div>
    <div class="interjection-receipt" data-task-id="${taskId}">
      <span class="receipt-status">pending</span>
    </div>
  `;
  conversationContainer.appendChild(bubble);
  conversationContainer.scrollTop = conversationContainer.scrollHeight;

  // Send to server
  try {
    await apiPost(`/tasks/${taskId}/interject`, { message: msg });

    // Initialize receipt
    updateReadReceipt(taskId, new Date().toISOString(), null);
  } catch (e) {
    addEvent('error', 'error', 'Failed to send interjection: ' + e.message);
  }
}

// ─── Confirmation Modal ───────────────────────────────────────────
function showConfirmationModal(config) {
  decisionModal = config;

  const modal = $id('confirmation-modal');
  const overlay = $id('modal-overlay');

  $id('confirm-modal-title').textContent = config.title || 'Confirmation Required';
  $id('confirm-modal-body').innerHTML = renderMarkdown(config.body || '');

  // Setup choices
  const choicesContainer = $id('confirm-modal-choices');
  choicesContainer.innerHTML = '';

  const choices = config.choices || [{ label: 'Confirm', value: 'confirm' }, { label: 'Deny', value: 'deny' }];
  choices.forEach(choice => {
    const btn = document.createElement('button');
    btn.className = 'confirm-choice-btn';
    btn.textContent = choice.label;
    btn.dataset.value = choice.value;
    btn.onclick = () => {
      const text = config.require_text ? $id('confirm-modal-text').value : '';
      if (config.require_text && !text.trim()) {
        $id('confirm-modal-text').focus();
        return;
      }
      handleModalResponse(choice.value, text);
    };
    choicesContainer.appendChild(btn);
  });

  // Setup text input if required
  const textContainer = $id('confirm-modal-text-container');
  if (config.require_text) {
    textContainer.classList.add('visible');
    $id('confirm-modal-text').placeholder = config.text_placeholder || 'Enter your response...';
    $id('confirm-modal-text').value = '';
  } else {
    textContainer.classList.remove('visible');
  }

  modal.classList.add('visible');
  overlay.classList.add('visible');
}

function hideConfirmationModal() {
  decisionModal = null;
  $id('confirmation-modal').classList.remove('visible');
  $id('modal-overlay').classList.remove('visible');
}

async function handleModalResponse(choice, text) {
  if (!decisionModal) return;

  const taskId = decisionModal.task_id;
  const decisionType = decisionModal.decision_type || 'confirmation';

  try {
    await submitDecision(taskId, decisionType, choice, text, decisionModal.metadata);
    hideConfirmationModal();
    addEvent('system', 'sys', `Decision submitted: ${choice}`);
  } catch (e) {
    addEvent('error', 'error', 'Failed to submit decision: ' + e.message);
  }
}

// ─── Read Receipts ────────────────────────────────────────────────
function updateReadReceipt(taskId, received_at, read_at) {
  if (!interjectionReceipts[taskId]) {
    interjectionReceipts[taskId] = {};
  }

  if (received_at) {
    interjectionReceipts[taskId].received_at = received_at;
  }
  if (read_at) {
    interjectionReceipts[taskId].read_at = read_at;
  }

  renderReadReceipt(taskId);
}

function renderReadReceipt(taskId) {
  const receipt = interjectionReceipts[taskId];
  if (!receipt) return;

  const receiptEl = document.querySelector(`.interjection-receipt[data-task-id="${taskId}"]`);
  if (!receiptEl) return;

  const receivedStr = receipt.received_at ? `received ${formatRelativeTime(receipt.received_at)}` : '';
  const readStr = receipt.read_at ? `read ${formatRelativeTime(receipt.read_at)}` : '';

  const statusEl = receiptEl.querySelector('.receipt-status');
  if (statusEl) {
    if (receipt.read_at) {
      statusEl.textContent = `${receivedStr} / ${readStr}`;
      statusEl.className = 'receipt-status read';
    } else if (receipt.received_at) {
      statusEl.textContent = receivedStr;
      statusEl.className = 'receipt-status received';
    } else {
      statusEl.textContent = 'pending';
      statusEl.className = 'receipt-status pending';
    }
  }
}

// ─── Decision Endpoint ────────────────────────────────────────────
async function submitDecision(taskId, decisionType, choice, note, metadata) {
  return await apiPost(`/tasks/${taskId}/decision`, {
    decision_type: decisionType,
    choice: choice,
    note: note,
    metadata: metadata || {},
  });
}

// ─── Tasks ────────────────────────────────────────────────────────
function toggleAddTask() {
  const f = $id('add-task-form');
  f.classList.toggle('open');
  if (f.classList.contains('open')) {
    populateRepoSelect('atf-repo');
    $id('atf-title').focus();
  }
}

function populateRepoSelect(selectId) {
  const sel = $id(selectId);
  if (!sel) return;
  sel.innerHTML = '<option value="">— none —</option>';
  repos.forEach(r => {
    const opt = document.createElement('option');
    opt.value = r.name;
    opt.textContent = r.name;
    sel.appendChild(opt);
  });
}

async function submitNewTask() {
  const title = $id('atf-title').value.trim();
  if (!title) { $id('atf-title').focus(); return; }

  try {
    await apiPost('/tasks', {
      title,
      description: $id('atf-desc').value.trim(),
      repo: $id('atf-repo').value ? [$id('atf-repo').value] : [],
      importance: parseFloat($id('atf-imp').value) || 0.5,
      urgency: parseFloat($id('atf-urg').value) || 0.5,
    });
    ['atf-title', 'atf-desc'].forEach(id => $id(id).value = '');
    $id('add-task-form').classList.remove('open');
    await loadTasks();
  } catch (e) {
    alert('Failed to create task: ' + e.message);
  }
}

async function loadTasks() {
  const filterEl = $id('task-filter-status');
  if (!filterEl) return;
  const filter = filterEl.value;

  let url = '/tasks';
  if (filter === 'all') url += '?all=true';
  else if (filter) url += '?status=' + filter;

  try {
    const data = await apiFetch(url);
    tasks = data.tasks || [];  // Store full task list for tree building
    renderTasks(tasks);
    renderSidebarTaskTree();  // Update sidebar tree
  } catch (e) {
    $id('tasks-list').innerHTML =
      '<div style="padding:14px;color:var(--text3)">Failed to load tasks.</div>';
  }
}

function dotClass(status) {
  return {
    pending: 'dot-pending', active: 'dot-active', blocked_human: 'dot-blocked',
    complete: 'dot-complete', cancelled: 'dot-cancelled',
    ready: 'dot-pending', running: 'dot-active', blocked_by_task: 'dot-blocked', blocked_by_human: 'dot-blocked'
  }[status?.toLowerCase()] || 'dot-pending';
}

function taskRowClass(status) {
  if (status === 'active' || status === 'running') return 'task-row active-task';
  if (status === 'blocked_human' || status === 'blocked_by_human' || status === 'blocked_by_task') return 'task-row blocked-task';
  if (status === 'complete' || status === 'cancelled') return 'task-row complete-task';
  return 'task-row';
}

function renderTasks(tasks) {
  const list = $id('tasks-list');
  if (!tasks.length) {
    list.innerHTML = '<div style="padding:14px;color:var(--text3)">No tasks.</div>';
    return;
  }
  list.innerHTML = '';
  tasks.forEach(t => {
    const score = (t.priority_score ?? 0).toFixed(3);
    const repo = (t.repo || []).join(', ') || '—';

    const row = document.createElement('div');
    row.className = taskRowClass(t.status);
    row.dataset.taskId = t.id;
    row.innerHTML = `
      <div><div class="task-status-dot ${dotClass(t.status)}"></div></div>
      <div>
        <div class="task-title">${esc(t.title)}</div>
        <div class="task-repo">${esc(repo)}</div>
      </div>
      <div class="task-score">${score}</div>
      <div class="task-phase">${esc(t.phase || '—')}</div>
      <div class="task-repo">${esc(t.status)}</div>
      <div class="task-actions">
        <button onclick="toggleTaskEdit('${t.id}',event)">✎</button>
      </div>`;
    list.appendChild(row);

    // Inline edit form
    const ef = document.createElement('div');
    ef.className = 'task-edit-form';
    ef.id = 'ef-' + t.id;
    ef.innerHTML = `
      <div><label>Title</label><input id="ef-title-${t.id}" type="text" value="${esc(t.title)}"></div>
      <div><label>Description</label><textarea id="ef-desc-${t.id}">${esc(t.description || '')}</textarea></div>
      <div class="ef-row">
        <div><label>Importance</label><input id="ef-imp-${t.id}" type="number" min="0" max="1" step="0.1" value="${t.importance ?? 0.5}"></div>
        <div><label>Urgency</label><input id="ef-urg-${t.id}" type="number" min="0" max="1" step="0.1" value="${t.urgency ?? 0.5}"></div>
      </div>
      <div class="ef-btns">
        <button class="save-btn"   onclick="saveTaskEdit('${t.id}')">Save</button>
        <button class="cancel-btn" onclick="toggleTaskEdit('${t.id}',null)">Cancel</button>
        <button style="margin-left:auto;border-color:var(--red2);color:var(--red)"
                onclick="cancelTask('${t.id}')">Cancel Task</button>
      </div>`;
    list.appendChild(ef);
  });
}

function toggleTaskEdit(id, e) {
  if (e) e.stopPropagation();
  const form = $id('ef-' + id);
  if (!form) return;
  const wasOpen = form.classList.contains('open');
  document.querySelectorAll('.task-edit-form.open').forEach(f => f.classList.remove('open'));
  if (!wasOpen) form.classList.add('open');
}

async function saveTaskEdit(id) {
  try {
    await apiPatch('/tasks/' + id, {
      title: $id('ef-title-' + id)?.value.trim(),
      description: $id('ef-desc-' + id)?.value.trim(),
      importance: parseFloat($id('ef-imp-' + id)?.value) || 0.5,
      urgency: parseFloat($id('ef-urg-' + id)?.value) || 0.5,
    });
    await loadTasks();
  } catch (e) { alert('Failed to save: ' + e.message); }
}

async function cancelTask(id) {
  if (!confirm('Cancel this task?')) return;
  try {
    await apiDelete('/tasks/' + id);
    await loadTasks();
  } catch (e) { alert('Failed: ' + e.message); }
}

setInterval(() => { if (currentTab === 'tasks') loadTasks(); }, 10000);

// ─── Status Dashboard ─────────────────────────────────────────────
async function loadStatusDashboard() {
  try {
    const data = await apiFetch('/blocked');
    renderStatusDashboard(data.report || { human: [], dependencies: [], waiting: [] });
  } catch (e) {
    $id('status-list-human').innerHTML = '<div style="padding:10px;color:var(--text3)">Failed to load status.</div>';
    $id('status-list-deps').innerHTML = '';
    $id('status-list-waiting').innerHTML = '';
  }
}

function renderStatusDashboard(report) {
  // Render blocked by human section
  const humanList = $id('status-list-human');
  if (humanList) {
    if (!report.human || report.human.length === 0) {
      humanList.innerHTML = '<div style="padding:10px;color:var(--text3)">No tasks blocked by human.</div>';
    } else {
      humanList.innerHTML = report.human.map(t => `
        <div class="status-task-row">
          <div class="status-task-title">${esc(t.title || 'Unknown task')}</div>
          <div class="status-task-reason">${esc(t.blocking_reason || 'Awaiting human input')}</div>
        </div>
      `).join('');
    }
  }

  // Render blocked by dependencies section
  const depsList = $id('status-list-deps');
  if (depsList) {
    if (!report.dependencies || report.dependencies.length === 0) {
      depsList.innerHTML = '<div style="padding:10px;color:var(--text3)">No tasks blocked by dependencies.</div>';
    } else {
      depsList.innerHTML = report.dependencies.map(t => `
        <div class="status-task-row">
          <div class="status-task-title">${esc(t.title || 'Unknown task')}</div>
          <div class="status-task-reason">${esc(t.blocking_reason || 'Blocked by dependencies')}</div>
        </div>
      `).join('');
    }
  }

  // Render waiting section
  const waitingList = $id('status-list-waiting');
  if (waitingList) {
    if (!report.waiting || report.waiting.length === 0) {
      waitingList.innerHTML = '<div style="padding:10px;color:var(--text3)">No tasks waiting.</div>';
    } else {
      waitingList.innerHTML = report.waiting.map(t => `
        <div class="status-task-row">
          <div class="status-task-title">${esc(t.title || 'Unknown task')}</div>
          <div class="status-task-reason">${esc(t.blocking_reason || 'Waiting on conditions')}</div>
        </div>
      `).join('');
    }
  }
}

// ─── Settings ─────────────────────────────────────────────────────
let _configCache = {};

async function loadConfig() {
  try {
    _configCache = await apiFetch('/config');
    populateSettingsFields(_configCache);
  } catch (e) { }
}

function populateSettingsFields(data) {
  document.querySelectorAll('[data-key]').forEach(el => {
    const key = el.dataset.key;
    if (!(key in data)) return;
    const val = data[key];
    if (el.type === 'checkbox') el.checked = !!val;
    else el.value = val ?? '';
  });
  // Attach change listeners (idempotent via named function)
  document.querySelectorAll('[data-key]').forEach(el => {
    el.onchange = () => onSettingChange(el, el.dataset.key);
    el.oninput = () => onSettingChange(el, el.dataset.key);
  });
}

function onSettingChange(el, key) {
  const val = el.type === 'checkbox' ? el.checked : el.value;
  pendingSettingsChanges[key] = val;
  $id('settings-save-bar').classList.add('visible');
}

async function saveSettings() {
  if (!Object.keys(pendingSettingsChanges).length) return;
  const endpoint = settingsTarget === 'workspace'
    ? '/config'
    : '/config/repos/' + settingsTarget;
  try {
    await apiPatch(endpoint, { values: pendingSettingsChanges });
    pendingSettingsChanges = {};
    $id('settings-save-bar').classList.remove('visible');
    addEvent('system', 'sys', 'Settings saved. Restart service to apply: sudo systemctl restart matrixmouse');
  } catch (e) { alert('Failed to save: ' + e.message); }
}

function cancelSettings() {
  pendingSettingsChanges = {};
  $id('settings-save-bar').classList.remove('visible');
  loadConfig();
}

function injectRepoSettings(repoList) {
  const nav = $id('settings-repo-nav');
  const sections = $id('settings-repo-sections');
  nav.innerHTML = '';
  sections.innerHTML = '';
  if (!repoList.length) return;

  const label = document.createElement('div');
  label.className = 'settings-nav-section';
  label.textContent = 'Repo Overrides';
  nav.appendChild(label);

  repoList.forEach(r => {
    const item = document.createElement('div');
    item.className = 'settings-nav-item';
    item.dataset.section = 'repo-' + r.name;
    item.textContent = r.name;
    item.onclick = () => selectSettingsSection('repo-' + r.name);
    nav.appendChild(item);

    const section = document.createElement('div');
    section.className = 'settings-section';
    section.id = 's-repo-' + r.name;
    section.innerHTML = `
      <div class="settings-group">
        <div class="settings-group-title">${esc(r.name)} — Repo Overrides</div>
        <p style="font-size:11px;color:var(--text3);margin-bottom:12px;line-height:1.6;">
          These values override workspace settings for this repo only.
          Saved to the untracked workspace state dir (layer 3).
        </p>
        <div class="setting-row">
          <div class="setting-key">Coder Model<small>Override for this repo</small></div>
          <div class="setting-val"><input type="text" data-key="coder_model" placeholder="e.g. ollama:qwen2.5-coder:7b"></div>
        </div>
        <div class="setting-row">
          <div class="setting-key">Coder Think<small>Override for this repo</small></div>
          <div class="setting-val"><input type="checkbox" data-key="coder_think"></div>
        </div>
      </div>`;
    sections.appendChild(section);
  });
}

// ─── Repos sidebar ────────────────────────────────────────────────
async function loadRepos() {
  try {
    const data = await apiFetch('/repos');
    repos = data.repos || [];

    const sbRepos = $id('sb-repos');
    sbRepos.innerHTML = '';

    // Workspace item
    const wsItem = document.createElement('div');
    wsItem.className = 'sb-item';
    wsItem.dataset.scope = 'workspace';
    wsItem.innerHTML =
      `<span class="sb-icon">◈</span>` +
      `<span class="sb-name">workspace</span>` +
      `<span class="sb-spinner"></span>`;
    wsItem.onclick = () => { selectScope('workspace'); closeSidebar(); };
    sbRepos.appendChild(wsItem);

    repos.forEach(r => {
      const item = document.createElement('div');
      item.className = 'sb-item';
      item.dataset.scope = r.name;
      item.innerHTML =
        `<span class="sb-icon">⬡</span>` +
        `<span class="sb-name">${esc(r.name)}</span>` +
        `<span class="sb-spinner"></span>`;
      item.onclick = () => { selectScope(r.name); closeSidebar(); };
      sbRepos.appendChild(item);
    });

    injectRepoSettings(repos);
    renderSidebarTaskTree();  // Render task trees under repos
  } catch (e) { }
}

// ─── WebSocket ────────────────────────────────────────────────────
function connect() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const ws = new WebSocket(`${proto}://${location.host}/ws`);

  ws.onopen = () => {
    $id('conn-dot').className = 'live';
    $id('conn-label').className = 'live';
    $id('conn-label').textContent = 'live';
  };

  ws.onmessage = e => {
    let msg;
    try { msg = JSON.parse(e.data); } catch { return; }

    if (msg.type === 'status_update') {
      updateStatus(msg.data);
      return;
    }

    if (msg.type === 'clarification_request') {
      showClarification(msg.data.question || JSON.stringify(msg.data));
      return;
    }

    if (msg.type === 'thinking') {
      appendThinking(msg.data.text || '');
      return;
    }

    if (msg.type === 'token') {
      appendToken(msg.data.text || '');
      return;
    }

    // Show inference bar when tool is dispatched (means model responded, now executing)
    if (msg.type === 'tool_call') {
      setInferring(false);
    }

    // After tool result, model is thinking again
    if (msg.type === 'tool_result') {
      setInferring(true, 'model thinking...');
    }

    // Content message = model responded
    if (msg.type === 'content') {
      setInferring(false);
    }

    const label = EVENT_LABELS[msg.type] || msg.type;
    const text = msg.data?.text
      ?? msg.data?.summary
      ?? msg.data?.question
      ?? JSON.stringify(msg.data);
    addEvent(msg.type, label, text);

    if (currentTab === 'tasks' &&
      ['complete', 'phase_change', 'escalation'].includes(msg.type)) {
      loadTasks();
    }

    // ─── New WebSocket Event Handlers ─────────────────────────────
    // Task tree update - rebuild sidebar task tree
    if (msg.type === 'task_tree_update') {
      tasks = msg.data.tasks || tasks;
      renderSidebarTaskTree();
      if (selectedTask) {
        const task = tasks.find(t => t.id === selectedTask);
        if (task) renderTaskConversation(task);
      }
      return;
    }

    // Decomposition confirmation required
    if (msg.type === 'decomposition_confirmation_required') {
      showConfirmationModal({
        task_id: msg.data.task_id,
        decision_type: 'decomposition',
        title: 'Decomposition Confirmation',
        body: msg.data.body || 'Please confirm the proposed decomposition.',
        choices: msg.data.choices || [
          { label: 'Approve', value: 'approve' },
          { label: 'Modify', value: 'modify' },
          { label: 'Reject', value: 'reject' }
        ],
        require_text: msg.data.require_text || false,
        text_placeholder: msg.data.text_placeholder || 'Explain your decision...',
        metadata: msg.data.metadata || {}
      });
      return;
    }

    // PR approval required
    if (msg.type === 'pr_approval_required') {
      showConfirmationModal({
        task_id: msg.data.task_id,
        decision_type: 'pr_approval',
        title: 'PR Approval Required',
        body: msg.data.body || 'Please review and approve the pull request.',
        choices: [
          { label: 'Approve', value: 'approve' },
          { label: 'Request Changes', value: 'request_changes' }
        ],
        require_text: false,
        metadata: msg.data.metadata || {}
      });
      return;
    }

    // PR rejection
    if (msg.type === 'pr_rejection') {
      showConfirmationModal({
        task_id: msg.data.task_id,
        decision_type: 'pr_rejection',
        title: 'PR Rejection',
        body: msg.data.body || 'The pull request was rejected. Please provide feedback.',
        choices: [{ label: 'Submit Feedback', value: 'submit' }],
        require_text: true,
        text_placeholder: 'Describe the changes needed...',
        metadata: msg.data.metadata || {}
      });
      return;
    }

    // Turn limit reached
    if (msg.type === 'turn_limit_reached') {
      showConfirmationModal({
        task_id: msg.data.task_id,
        decision_type: 'turn_limit',
        title: 'Turn Limit Reached',
        body: msg.data.body || 'The task has reached its turn limit. How would you like to proceed?',
        choices: [
          { label: 'Continue', value: 'continue' },
          { label: 'Stop', value: 'stop' }
        ],
        metadata: msg.data.metadata || {}
      });
      return;
    }

    // Critic turn limit reached
    if (msg.type === 'critic_turn_limit_reached') {
      showConfirmationModal({
        task_id: msg.data.task_id,
        decision_type: 'critic_turn_limit',
        title: 'Critic Turn Limit Reached',
        body: msg.data.body || 'The critic has reached its turn limit.',
        choices: [
          { label: 'Continue', value: 'continue' },
          { label: 'Accept', value: 'accept' }
        ],
        metadata: msg.data.metadata || {}
      });
      return;
    }

    // Merge conflict resolution turn limit reached
    if (msg.type === 'merge_conflict_resolution_turn_limit_reached') {
      showConfirmationModal({
        task_id: msg.data.task_id,
        decision_type: 'merge_conflict_turn_limit',
        title: 'Merge Conflict Resolution Limit',
        body: msg.data.body || 'Merge conflict resolution has reached its turn limit.',
        choices: [
          { label: 'Continue', value: 'continue' },
          { label: 'Abort', value: 'abort' }
        ],
        metadata: msg.data.metadata || {}
      });
      return;
    }

    // Planning turn limit reached
    if (msg.type === 'planning_turn_limit_reached') {
      showConfirmationModal({
        task_id: msg.data.task_id,
        decision_type: 'planning_turn_limit',
        title: 'Planning Turn Limit Reached',
        body: msg.data.body || 'Planning has reached its turn limit.',
        choices: [
          { label: 'Continue', value: 'continue' },
          { label: 'Proceed with Current Plan', value: 'proceed' }
        ],
        metadata: msg.data.metadata || {}
      });
      return;
    }

    // Message received - update read receipt received_at
    if (msg.type === 'message_received') {
      const taskId = msg.data.task_id;
      const receivedAt = msg.data.received_at || new Date().toISOString();
      updateReadReceipt(taskId, receivedAt, null);
      return;
    }

    // Message read - update read receipt read_at
    if (msg.type === 'message_read') {
      const taskId = msg.data.task_id;
      const readAt = msg.data.read_at || new Date().toISOString();
      updateReadReceipt(taskId, null, readAt);
      return;
    }
  };

  ws.onclose = () => {
    $id('conn-dot').className = '';
    $id('conn-label').className = '';
    $id('conn-label').textContent = 'reconnecting';
    setInferring(false);
    setTimeout(connect, 3000);
  };

  ws.onerror = () => ws.close();
}

// ─── API helpers ──────────────────────────────────────────────────
async function apiFetch(url) {
  const r = await fetch(url);
  if (!r.ok) {
    const b = await r.json().catch(() => ({}));
    throw new Error(b.detail || r.statusText);
  }
  return r.json();
}

async function apiPost(url, body) {
  const r = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    const b = await r.json().catch(() => ({}));
    throw new Error(b.detail || r.statusText);
  }
  return r.json().catch(() => ({}));
}

async function apiPatch(url, body) {
  const r = await fetch(url, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    const b = await r.json().catch(() => ({}));
    throw new Error(b.detail || r.statusText);
  }
  return r.json().catch(() => ({}));
}

async function apiDelete(url) {
  const r = await fetch(url, { method: 'DELETE' });
  if (!r.ok) {
    const b = await r.json().catch(() => ({}));
    throw new Error(b.detail || r.statusText);
  }
  return r.json().catch(() => ({}));
}

// ─── Init ─────────────────────────────────────────────────────────
connect();
loadRepos();
loadContext('workspace');
