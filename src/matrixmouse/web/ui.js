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

// Task tree state
let tasks = [];  // full task list for client-side tree building
let selectedTask = null;  // currently selected task for task panel view
let expandedTasks = {};  // set of task_ids that are expanded in tree

// ─── Utilities ────────────────────────────────────────────────────
function ts() { return new Date().toTimeString().slice(0, 8); }

function esc(s) {
  return String(s ?? '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

function escLines(s) { return esc(s).replace(/\n/g, '<br>'); }

function $id(id) { return document.getElementById(id); }

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

  // Clear selected task when switching scope
  selectedTask = null;

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

  // Re-render task trees to clear task highlight
  renderTaskTrees();
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
  const v = $id('v-status');
  if (!v) return; // Element may not exist during initial load

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


function addEvent(type, label, text, timestamp) {
  thinkingRow = null;
  streamingRow = null;
  const div = document.createElement('div');
  div.className = 'ev ' + type;

  let html =
    `<span class="ev-ts">${ts()}</span>` +
    `<span class="ev-lbl">${esc(label || type)}</span>` +
    `<span class="ev-txt">${renderEvText(type, text)}</span>`;

  // Add timestamp/receipt for user messages
  if (type === 'you' && timestamp) {
    html += `<span class="ev-receipt">sent at ${timestamp}</span>`;
  }

  div.innerHTML = html;
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
  $id('clar-question').textContent = '🔔 ' + question;
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

  // Clarification answers are workspace-wide (comms module handles distribution)
  await apiPost('/interject/workspace', { message: reply });
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

// ─── Confirmation Modal ───────────────────────────────────────────
let currentDecision = null;  // { taskId, decisionType, choices, requireText }

function showConfirmationModal(config) {
  currentDecision = config;

  const overlay = $id('confirmation-modal-overlay');
  const title = $id('confirmation-modal-title');
  const body = $id('confirmation-modal-body');
  const choices = $id('confirmation-modal-choices');
  const textContainer = $id('confirmation-modal-text-container');
  const textInput = $id('confirmation-modal-text-input');

  if (!overlay) return;

  title.textContent = config.title;
  body.innerHTML = renderMarkdown(config.body);

  // Render choice buttons
  choices.innerHTML = '';
  config.choices.forEach(choice => {
    const btn = document.createElement('button');
    btn.textContent = choice.label;
    btn.onclick = () => handleModalResponse(choice.value);
    choices.appendChild(btn);
  });

  // Show/hide text input
  if (config.requireText) {
    textContainer.style.display = 'block';
    textInput.placeholder = config.textPlaceholder || 'Please provide details...';
    textInput.value = '';
  } else {
    textContainer.style.display = 'none';
  }

  overlay.classList.add('visible');
}

function hideConfirmationModal() {
  const overlay = $id('confirmation-modal-overlay');
  if (overlay) overlay.classList.remove('visible');
  currentDecision = null;
}

async function handleModalResponse(choice) {
  if (!currentDecision) return;

  const textInput = $id('confirmation-modal-text-input');
  const note = textInput.value.trim();

  // Validate required text
  if (currentDecision.requireText && !note) {
    textInput.style.borderColor = 'var(--red)';
    return;
  }

  // Submit decision
  await apiPost(`/tasks/${currentDecision.taskId}/decision`, {
    decision_type: currentDecision.decisionType,
    choice: choice,
    note: note,
  });

  hideConfirmationModal();
}

$id('confirmation-modal-cancel').onclick = hideConfirmationModal;

// ─── Interjection ─────────────────────────────────────────────────
async function sendInterjection() {
  const input = $id('msg-input');
  const msg = input.value.trim();
  if (!msg) return;
  input.value = '';

  const timestamp = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  addEvent('you', 'you', msg, timestamp);

  // Priority: Task > Repo > Workspace
  if (selectedTask && selectedTask.id) {
    // Task-scoped interjection - goes directly to the task's agent
    await apiPost(`/tasks/${selectedTask.id}/interject`, { message: msg });
  } else if (currentScope === 'workspace') {
    // Workspace-wide interjection - goes to Manager
    await apiPost('/interject/workspace', { message: msg });
  } else {
    // Repo-scoped interjection - goes to Manager for that repo
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
    renderTasks(data.tasks || []);
  } catch (e) {
    $id('tasks-list').innerHTML =
      '<div style="padding:14px;color:var(--text3)">Failed to load tasks.</div>';
  }
}

function dotClass(status) {
  return {
    pending: 'dot-pending', active: 'dot-active', blocked_human: 'dot-blocked',
    complete: 'dot-complete', cancelled: 'dot-cancelled'
  }[status] || 'dot-pending';
}

function taskRowClass(status) {
  if (status === 'active') return 'task-row active-task';
  if (status === 'blocked_human') return 'task-row blocked-task';
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
      <div style="flex:1;min-width:0;">
        <div class="task-title" title="${esc(t.title)}">${esc(t.title)}</div>
        <div class="task-repo">${esc(repo)}</div>
      </div>
      <div class="task-score">${score}</div>
      <div class="task-phase">${esc(t.phase || '—')}</div>
      <div class="task-repo">${esc(t.status)}</div>
      <div class="task-actions">
        <button onclick="toggleTaskEdit('${t.id}',event)">✎</button>
        ${t.status === 'blocked_by_human' ? `<button onclick="unblockTask('${t.id}',event)" title="Unblock task">✓</button>` : ''}
      </div>`;
    list.appendChild(row);

    // Inline edit form with all editable fields
    const ef = document.createElement('div');
    ef.className = 'task-edit-form';
    ef.id = 'ef-' + t.id;
    ef.innerHTML = `
      <div><label>Title</label><input id="ef-title-${t.id}" type="text" value="${esc(t.title)}"></div>
      <div><label>Description</label><textarea id="ef-desc-${t.id}">${esc(t.description || '')}</textarea></div>
      <div><label>Notes</label><textarea id="ef-notes-${t.id}">${esc(t.notes || '')}</textarea></div>
      <div class="ef-row">
        <div><label>Branch</label><input id="ef-branch-${t.id}" type="text" value="${esc(t.branch || '')}"></div>
        <div><label>Role</label>
          <select id="ef-role-${t.id}">
            <option value="coder" ${t.role === 'coder' ? 'selected' : ''}>Coder</option>
            <option value="writer" ${t.role === 'writer' ? 'selected' : ''}>Writer</option>
            <option value="manager" ${t.role === 'manager' ? 'selected' : ''}>Manager</option>
            <option value="critic" ${t.role === 'critic' ? 'selected' : ''}>Critic</option>
            <option value="merge" ${t.role === 'merge' ? 'selected' : ''}>Merge</option>
          </select>
        </div>
      </div>
      <div class="ef-row">
        <div><label>Importance (0–1)</label><input id="ef-imp-${t.id}" type="number" min="0" max="1" step="0.1" value="${t.importance ?? 0.5}"></div>
        <div><label>Urgency (0–1)</label><input id="ef-urg-${t.id}" type="number" min="0" max="1" step="0.1" value="${t.urgency ?? 0.5}"></div>
        <div><label>Turn Limit</label><input id="ef-turns-${t.id}" type="number" min="0" value="${t.turn_limit || 0}"></div>
      </div>
      <div class="ef-btns">
        <button class="save-btn" onclick="saveTaskEdit('${t.id}')">Save</button>
        <button class="cancel-btn" onclick="toggleTaskEdit('${t.id}',null)">Cancel</button>
        <button style="margin-left:auto;border-color:var(--red2);color:var(--red)" onclick="cancelTask('${t.id}')">Cancel Task</button>
        ${t.status === 'blocked_by_human' ? `<button style="border-color:var(--green2);color:var(--green)" onclick="unblockTask('${t.id}',null)">Unblock</button>` : ''}
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
    const updates = {
      title: $id(`ef-title-${id}`)?.value.trim(),
      description: $id(`ef-desc-${id}`)?.value.trim(),
      notes: $id(`ef-notes-${id}`)?.value.trim(),
      branch: $id(`ef-branch-${id}`)?.value.trim(),
      role: $id(`ef-role-${id}`)?.value,
      importance: parseFloat($id(`ef-imp-${id}`)?.value) || 0.5,
      urgency: parseFloat($id(`ef-urg-${id}`)?.value) || 0.5,
      turn_limit: parseInt($id(`ef-turns-${id}`)?.value) || 0,
    };
    await apiPatch(`/tasks/${id}`, updates);
    await loadTasks();
  } catch (e) {
    alert('Failed to save: ' + e.message);
  }
}

async function unblockTask(id, e) {
  if (e) e.stopPropagation();

  const note = prompt('Optional note to include with unblock:');
  if (note === null) return; // User cancelled

  try {
    await apiPost(`/tasks/${id}/decision`, {
      decision_type: 'turn_limit_reached',  // Generic unblock
      choice: 'extend',
      note: note || 'Unblocked via UI',
    });
    await loadTasks();
    alert('Task unblocked successfully');
  } catch (e) {
    alert('Failed to unblock: ' + e.message);
  }
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

    repos.forEach(r => {
      // Create repo item with expand arrow (default collapsed ▶)
      const item = document.createElement('div');
      item.className = 'sb-item';
      item.dataset.scope = r.name;
      item.innerHTML =
        `<button class="sb-repo-expand" onclick="toggleRepoTasks(event, '${r.name}')">▶</button>` +
        `<span class="sb-icon">⬡</span>` +
        `<span class="sb-name">${esc(r.name)}</span>` +
        `<span class="sb-spinner"></span>`;
      item.onclick = (e) => {
        if (e.target.className !== 'sb-repo-expand') {
          selectScope(r.name); closeSidebar();
        }
      };
      sbRepos.appendChild(item);

      // Create task tree container for this repo (nested under repo item)
      const treeContainer = document.createElement('div');
      treeContainer.id = `sb-task-tree-${r.name}`;
      treeContainer.className = 'sb-task-tree';
      sbRepos.appendChild(treeContainer);
    });

    injectRepoSettings(repos);

    // Load tasks for task tree
    await loadTasksForTree();
  } catch (e) { }
}

function toggleRepoTasks(event, repoName) {
  event.stopPropagation();
  const treeContainer = $id(`sb-task-tree-${repoName}`);
  const expandBtn = event.target;

  if (treeContainer) {
    const isVisible = treeContainer.classList.contains('visible');
    if (isVisible) {
      // Collapse
      treeContainer.classList.remove('visible');
      expandBtn.textContent = '▶';
    } else {
      // Expand
      treeContainer.classList.add('visible');
      expandBtn.textContent = '▼';
    }
  }
}

function toggleWorkspaceTasks(event) {
  event.stopPropagation();
  const treeContainer = $id('sb-task-tree-workspace');
  const expandBtn = event.target;

  if (treeContainer) {
    const isVisible = treeContainer.classList.contains('visible');
    if (isVisible) {
      // Collapse
      treeContainer.classList.remove('visible');
      expandBtn.textContent = '▶';
    } else {
      // Expand
      treeContainer.classList.add('visible');
      expandBtn.textContent = '▼';
    }
  }
}

function selectScopeWorkspace(event) {
  event.stopPropagation();
  if (event.target.className !== 'sb-repo-expand') {
    // Clear selected task when switching to workspace scope
    selectedTask = null;
    selectScope('workspace');
    closeSidebar();
    // selectScope already calls renderTaskTrees()
  }
}

// ─── Task Tree ────────────────────────────────────────────────────
async function loadTasksForTree() {
  try {
    const data = await apiFetch('/tasks?all=true');
    tasks = data.tasks || [];
    renderTaskTrees();
  } catch (e) {
    console.error('Failed to load tasks for tree:', e);
  }
}

function buildTaskTree() {
  // Build hierarchical tree from flat task list using parent_task_id
  const taskMap = {};
  const rootTasks = [];

  tasks.forEach(t => {
    taskMap[t.id] = { ...t, children: [] };
  });

  tasks.forEach(t => {
    if (t.parent_task_id && taskMap[t.parent_task_id]) {
      taskMap[t.parent_task_id].children.push(taskMap[t.id]);
    } else {
      rootTasks.push(taskMap[t.id]);
    }
  });

  return { taskMap, rootTasks };
}

function getStatusClass(status) {
  const statusMap = {
    'pending': 'status-pending',
    'ready': 'status-ready',
    'running': 'status-running',
    'blocked_by_task': 'status-blocked-task',
    'blocked_by_human': 'status-blocked-human',
  };
  return statusMap[status] || 'status-pending';
}

function renderTaskTrees() {
  const { taskMap, rootTasks } = buildTaskTree();

  // Group tasks by repo
  const tasksByRepo = {};
  repos.forEach(r => { tasksByRepo[r.name] = []; });
  // Workspace channel for tasks without a repo
  tasksByRepo['workspace'] = [];

  rootTasks.forEach(t => {
    const repoList = t.repo || [];
    if (repoList.length === 0) {
      // Workspace-level task
      tasksByRepo['workspace'].push(t);
    } else {
      repoList.forEach(repoName => {
        if (tasksByRepo[repoName]) {
          tasksByRepo[repoName].push(t);
        }
      });
    }
  });

  // Render task tree for each repo (starts collapsed)
  repos.forEach(r => {
    const treeContainer = $id(`sb-task-tree-${r.name}`);
    if (treeContainer) {
      treeContainer.innerHTML = '';
      const repoTasks = tasksByRepo[r.name] || [];

      // Don't auto-expand - user must click to expand
      repoTasks.forEach(t => {
        const taskNode = renderTaskTreeNode(t, 0);
        treeContainer.appendChild(taskNode);
      });
    }
  });

  // Render task tree for Workspace channel (starts collapsed)
  const workspaceTreeContainer = $id('sb-task-tree-workspace');
  if (workspaceTreeContainer) {
    workspaceTreeContainer.innerHTML = '';
    const workspaceTasks = tasksByRepo['workspace'] || [];

    // Don't auto-expand - user must click to expand
    workspaceTasks.forEach(t => {
      const taskNode = renderTaskTreeNode(t, 0);
      workspaceTreeContainer.appendChild(taskNode);
    });
  }
}

function renderTaskTreeNode(task, depth) {
  const div = document.createElement('div');
  div.className = 'sb-task-item' + (selectedTask && selectedTask.id === task.id ? ' active' : '');
  div.dataset.taskId = task.id;

  const hasChildren = task.children && task.children.length > 0;
  const isExpanded = expandedTasks[task.id] || false;

  div.innerHTML =
    `<button class="sb-task-expand" onclick="toggleTaskExpand(event, '${task.id}')">${hasChildren ? (isExpanded ? '▼' : '▶') : '•'}</button>` +
    `<span class="sb-task-status ${getStatusClass(task.status)}"></span>` +
    `<span class="sb-task-title">${esc(task.title)}</span>`;

  div.onclick = (e) => {
    if (e.target.className !== 'sb-task-expand') {
      selectTask(task.id);
    }
  };

  // Add indentation via style
  div.style.marginLeft = (depth * 16) + 'px';

  // Render children if expanded
  if (hasChildren && isExpanded) {
    const childrenContainer = document.createElement('div');
    childrenContainer.className = 'sb-task-tree visible';
    task.children.forEach(child => {
      childrenContainer.appendChild(renderTaskTreeNode(child, depth + 1));
    });
    div.appendChild(childrenContainer);
  }

  return div;
}

function toggleTaskExpand(event, taskId) {
  event.stopPropagation();
  expandedTasks[taskId] = !expandedTasks[taskId];
  renderTaskTrees();
}

function selectTask(taskId) {
  const task = tasks.find(t => t.id === taskId);
  if (!task) return;

  selectedTask = task;

  // Update scope based on task's repo(s)
  const repoList = task.repo || [];
  if (repoList.length === 0) {
    // No repo = workspace task
    currentScope = 'workspace';
  } else if (repoList.length === 1) {
    // Single repo task - select that repo
    currentScope = repoList[0];
  } else {
    // Multi-repo task - treat as workspace-scoped (Manager owns it)
    currentScope = 'workspace';
  }

  // Update sidebar highlights
  document.querySelectorAll('.sb-item[data-scope]').forEach(el => {
    el.classList.toggle('active', el.dataset.scope === currentScope);
  });
  renderTaskTrees(); // Update task highlight

  // Switch to chat panel and show task conversation
  currentTab = 'chat';
  showPanel('chat-panel');
  loadTaskConversation(task);
}

function loadTaskConversation(task) {
  const log = $id('log');
  if (!log) return;

  log.innerHTML = '';

  // Show task header info
  const headerDiv = document.createElement('div');
  headerDiv.style.cssText = 'padding:14px;border-bottom:1px solid var(--border);background:var(--bg1);margin-bottom:8px;flex-shrink:0;';
  const repoList = task.repo || [];
  const repoDisplay = repoList.length === 0 ? 'workspace' :
    repoList.length === 1 ? repoList[0] :
      'multi-repo (' + repoList.join(', ') + ')';
  headerDiv.innerHTML = `
    <div style="font-size:12px;font-weight:500;color:var(--text);margin-bottom:4px;">${esc(task.title)}</div>
    <div style="font-size:10px;color:var(--text3);">
      ID: ${task.id} | Status: ${task.status} | Role: ${task.role}
      ${task.branch ? '| Branch: ' + esc(task.branch) : ''} | Repo: ${repoDisplay}
    </div>
  `;
  log.appendChild(headerDiv);

  // Show context messages as conversation
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
    if (!content || !content.trim()) return;

    const bubbleClass = role === 'user' ? 'context-bubble user' :
      role === 'assistant' ? 'context-bubble assistant' :
        'context-bubble system';

    const bubbleDiv = document.createElement('div');
    bubbleDiv.className = bubbleClass;
    bubbleDiv.innerHTML = role === 'tool_call' || role === 'tool_result' ?
      `<pre style="margin:0;white-space:pre-wrap;">${esc(content)}</pre>` :
      renderMarkdown(content);

    log.appendChild(bubbleDiv);
  });

  log.scrollTop = log.scrollHeight;
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
