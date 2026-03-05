"""
matrixmouse/web_ui.py

Self-contained single-page web UI for MatrixMouse.

Returns the full HTML/CSS/JS application as a string via build_html().
Imported by server.py to serve at GET /.

UI structure:
    Header bar   — status fields, soft stop button, E-STOP button, connection indicator
    Sidebar      — Workspace channel, per-repo channels, Tasks nav, Settings nav
    Main panel   — Chat view (per channel) | Tasks tab | Settings tab

    Chat view    — event log + clarification banner + interjection input
    Tasks tab    — sortable task list with inline edit
    Settings tab — workspace config + per-repo overrides

Event types handled:
    status_update        — update header fields
    clarification_request — show answer banner
    tool_call            — log tool invocation
    tool_result          — log tool output
    content              — log agent text output
    phase_change         — log phase transition
    escalation           — log stuck detector event
    blocked_human        — show clarification banner
    complete             — log task completion
    error                — log error
    token                — streaming token (appended to last content row,
                           ready for when loop.py gains streaming support)

Do not add Python logic here. This module only builds and returns HTML strings.
"""


def build_html() -> str:
    """Return the complete single-page application as an HTML string."""
    return _HTML


# ---------------------------------------------------------------------------
# The SPA — industrial/utilitarian aesthetic with monospace DNA
# Inspired by terminal UIs, flight instrument panels, and Unix philosophy.
# Every pixel earns its place. Function is the form.
# ---------------------------------------------------------------------------

_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>MatrixMouse</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Martian+Mono:wght@300;400;500;700&family=Fragment+Mono&display=swap" rel="stylesheet">
<style>
/* ─── Reset & Base ───────────────────────────────────────────── */
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

:root {
  --bg:        #0a0a0a;
  --bg1:       #111111;
  --bg2:       #181818;
  --bg3:       #1f1f1f;
  --border:    #2a2a2a;
  --border2:   #333333;
  --text:      #c8c8c8;
  --text2:     #888888;
  --text3:     #555555;
  --green:     #39ff14;
  --green2:    #1a7a00;
  --amber:     #ffaa00;
  --amber2:    #7a4a00;
  --red:       #ff2244;
  --red2:      #7a0011;
  --blue:      #00aaff;
  --purple:    #aa66ff;
  --cyan:      #00ddcc;
  --font-mono: 'Fragment Mono', 'Martian Mono', monospace;
  --font-ui:   'Martian Mono', monospace;
  --sidebar-w: 180px;
  --header-h:  44px;
}

html, body {
  height: 100%;
  background: var(--bg);
  color: var(--text);
  font-family: var(--font-mono);
  font-size: 12px;
  line-height: 1.5;
  overflow: hidden;
}

/* ─── Layout Shell ───────────────────────────────────────────── */
#app {
  display: grid;
  grid-template-rows: var(--header-h) 1fr;
  grid-template-columns: var(--sidebar-w) 1fr;
  grid-template-areas:
    "header header"
    "sidebar main";
  height: 100vh;
}

/* ─── Header ─────────────────────────────────────────────────── */
#header {
  grid-area: header;
  display: flex;
  align-items: center;
  gap: 0;
  background: var(--bg1);
  border-bottom: 1px solid var(--border);
  padding: 0 12px;
  overflow: hidden;
}

.h-logo {
  font-family: var(--font-ui);
  font-weight: 700;
  font-size: 13px;
  color: var(--green);
  letter-spacing: 0.05em;
  padding-right: 16px;
  border-right: 1px solid var(--border);
  margin-right: 12px;
  white-space: nowrap;
  text-transform: uppercase;
}

.h-fields {
  display: flex;
  gap: 0;
  flex: 1;
  overflow: hidden;
}

.h-field {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 0 12px;
  border-right: 1px solid var(--border);
  font-size: 11px;
  white-space: nowrap;
}

.h-field .lbl { color: var(--text3); text-transform: uppercase; font-size: 9px; letter-spacing: 0.1em; }
.h-field .val { color: var(--text); font-weight: 500; }
.h-field .val.active { color: var(--green); }
.h-field .val.blocked { color: var(--amber); }
.h-field .val.stopped { color: var(--red); }

#h-controls {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-left: auto;
  padding-left: 12px;
}

/* Soft stop — square stop symbol */
#btn-stop {
  display: flex;
  align-items: center;
  gap: 5px;
  background: transparent;
  border: 1px solid var(--border2);
  color: var(--text2);
  padding: 4px 10px;
  font-family: var(--font-ui);
  font-size: 10px;
  cursor: pointer;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  transition: border-color 0.15s, color 0.15s;
}
#btn-stop:hover { border-color: var(--amber); color: var(--amber); }
#btn-stop .icon { font-size: 9px; }

/* E-STOP — red, distinct, alarming */
#btn-kill {
  display: flex;
  align-items: center;
  gap: 5px;
  background: var(--red2);
  border: 1px solid var(--red);
  color: var(--red);
  padding: 4px 10px;
  font-family: var(--font-ui);
  font-size: 10px;
  font-weight: 700;
  cursor: pointer;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  transition: background 0.15s;
}
#btn-kill:hover { background: var(--red); color: #000; }

#conn-dot {
  width: 7px; height: 7px;
  border-radius: 50%;
  background: var(--text3);
  transition: background 0.3s;
  flex-shrink: 0;
}
#conn-dot.live { background: var(--green); box-shadow: 0 0 6px var(--green); }
#conn-label { font-size: 10px; color: var(--text3); }
#conn-label.live { color: var(--green); }

/* ─── Sidebar ────────────────────────────────────────────────── */
#sidebar {
  grid-area: sidebar;
  background: var(--bg1);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  overflow-y: auto;
}

.sb-section-label {
  padding: 10px 12px 4px;
  font-size: 9px;
  color: var(--text3);
  text-transform: uppercase;
  letter-spacing: 0.15em;
  border-top: 1px solid var(--border);
}
.sb-section-label:first-child { border-top: none; }

.sb-item {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 6px 12px;
  font-size: 11px;
  color: var(--text2);
  cursor: pointer;
  border-left: 2px solid transparent;
  transition: color 0.1s, background 0.1s;
  user-select: none;
}
.sb-item:hover { background: var(--bg2); color: var(--text); }
.sb-item.active {
  color: var(--green);
  border-left-color: var(--green);
  background: var(--bg2);
}
.sb-item .sb-icon { font-size: 10px; width: 14px; text-align: center; flex-shrink: 0; }
.sb-item .sb-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sb-item .sb-badge {
  margin-left: auto;
  background: var(--amber2);
  color: var(--amber);
  font-size: 9px;
  padding: 1px 4px;
  border-radius: 2px;
  flex-shrink: 0;
}

#sb-spacer { flex: 1; }

/* ─── Main Panel ─────────────────────────────────────────────── */
#main {
  grid-area: main;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* Tab panels */
.tab-panel { display: none; flex-direction: column; flex: 1; overflow: hidden; }
.tab-panel.active { display: flex; }
#settings-panel.active { flex-direction: row; }

/* ─── Chat View ──────────────────────────────────────────────── */
#chat-scope-label {
  padding: 6px 14px;
  font-size: 10px;
  color: var(--text3);
  border-bottom: 1px solid var(--border);
  background: var(--bg1);
  text-transform: uppercase;
  letter-spacing: 0.1em;
}

#clarification {
  display: none;
  flex-direction: column;
  gap: 8px;
  padding: 10px 14px;
  background: var(--bg2);
  border-bottom: 2px solid var(--amber);
}
#clarification.visible { display: flex; }
#clarification .clar-q { color: var(--amber); font-size: 12px; }
#clarification .clar-row { display: flex; gap: 8px; }
#clarification input {
  flex: 1;
  background: var(--bg1);
  border: 1px solid var(--amber);
  color: var(--text);
  padding: 5px 10px;
  font-family: var(--font-mono);
  font-size: 12px;
  outline: none;
}
#clarification button {
  background: var(--amber);
  color: #000;
  border: none;
  padding: 5px 14px;
  font-family: var(--font-ui);
  font-weight: 700;
  font-size: 11px;
  cursor: pointer;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

#log {
  flex: 1;
  overflow-y: auto;
  padding: 8px 0;
}

.ev {
  display: grid;
  grid-template-columns: 60px 80px 1fr;
  gap: 0 8px;
  padding: 2px 14px;
  border-bottom: 1px solid #131313;
  font-size: 11px;
  line-height: 1.6;
  align-items: baseline;
}
.ev:hover { background: #0f0f0f; }
.ev .ev-ts  { color: var(--text3); font-size: 10px; }
.ev .ev-lbl { font-size: 10px; text-transform: uppercase; letter-spacing: 0.06em; font-weight: 500; }
.ev .ev-txt { color: var(--text); white-space: pre-wrap; word-break: break-word; }

/* Label colours by event type */
.ev.tool_call     .ev-lbl { color: var(--cyan); }
.ev.tool_result   .ev-lbl { color: var(--amber); }
.ev.content       .ev-lbl { color: var(--purple); }
.ev.token         .ev-lbl { color: var(--purple); }
.ev.phase_change  .ev-lbl { color: var(--green); }
.ev.escalation    .ev-lbl { color: var(--amber); }
.ev.blocked_human .ev-lbl { color: var(--red); }
.ev.complete      .ev-lbl { color: var(--green); }
.ev.error         .ev-lbl { color: var(--red); }
.ev.you           .ev-lbl { color: var(--blue); }
.ev.system        .ev-lbl { color: var(--text3); }

/* Streaming token row — text appended in place */
.ev.token .ev-txt { color: var(--purple); }

#input-row {
  display: flex;
  gap: 0;
  border-top: 1px solid var(--border);
  background: var(--bg1);
}
#msg-input {
  flex: 1;
  background: transparent;
  border: none;
  color: var(--text);
  padding: 10px 14px;
  font-family: var(--font-mono);
  font-size: 12px;
  outline: none;
}
#msg-input::placeholder { color: var(--text3); }
#msg-input:focus { background: var(--bg2); }
#send-btn {
  background: var(--green2);
  border: none;
  border-left: 1px solid var(--border);
  color: var(--green);
  padding: 10px 18px;
  font-family: var(--font-ui);
  font-size: 11px;
  font-weight: 700;
  cursor: pointer;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  transition: background 0.15s;
}
#send-btn:hover { background: var(--green); color: #000; }

/* ─── Tasks Tab ──────────────────────────────────────────────── */
#tasks-panel {
  overflow: hidden;
  flex-direction: column;
}

#tasks-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 14px;
  border-bottom: 1px solid var(--border);
  background: var(--bg1);
}
#tasks-toolbar .tb-label {
  font-size: 10px;
  color: var(--text3);
  text-transform: uppercase;
  letter-spacing: 0.1em;
}
#tasks-toolbar select, #tasks-toolbar input[type=text] {
  background: var(--bg2);
  border: 1px solid var(--border);
  color: var(--text);
  padding: 3px 8px;
  font-family: var(--font-mono);
  font-size: 11px;
  outline: none;
}
#btn-add-task {
  margin-left: auto;
  background: transparent;
  border: 1px solid var(--green2);
  color: var(--green);
  padding: 3px 12px;
  font-family: var(--font-ui);
  font-size: 10px;
  cursor: pointer;
  text-transform: uppercase;
  letter-spacing: 0.08em;
}
#btn-add-task:hover { background: var(--green2); }

#tasks-list {
  flex: 1;
  overflow-y: auto;
}

.task-row {
  display: grid;
  grid-template-columns: 18px 1fr 80px 60px 60px 32px;
  gap: 0 10px;
  align-items: center;
  padding: 7px 14px;
  border-bottom: 1px solid #131313;
  font-size: 11px;
  cursor: pointer;
  transition: background 0.1s;
}
.task-row:hover { background: var(--bg2); }
.task-row.active-task { border-left: 2px solid var(--green); background: #0d1a0d; }
.task-row.blocked-task { border-left: 2px solid var(--amber); }
.task-row.complete-task { opacity: 0.4; }

.task-status-dot {
  width: 8px; height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}
.dot-pending  { background: var(--text3); }
.dot-active   { background: var(--green); box-shadow: 0 0 4px var(--green); }
.dot-blocked  { background: var(--amber); }
.dot-complete { background: var(--text3); }
.dot-cancelled { background: var(--red); opacity: 0.5; }

.task-title { color: var(--text); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.task-repo  { color: var(--text3); font-size: 10px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.task-score { color: var(--cyan); font-size: 10px; text-align: right; }
.task-phase { color: var(--text3); font-size: 10px; }
.task-actions button {
  background: transparent;
  border: 1px solid var(--border);
  color: var(--text3);
  padding: 2px 5px;
  font-size: 10px;
  cursor: pointer;
  font-family: var(--font-mono);
}
.task-actions button:hover { border-color: var(--red); color: var(--red); }

/* Task edit form (inline expand) */
.task-edit-form {
  display: none;
  grid-column: 1 / -1;
  padding: 10px 14px;
  background: var(--bg2);
  border-bottom: 1px solid var(--border);
  gap: 8px;
  flex-direction: column;
}
.task-edit-form.open { display: flex; }
.task-edit-form label { font-size: 10px; color: var(--text3); text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 2px; }
.task-edit-form input, .task-edit-form textarea {
  background: var(--bg1);
  border: 1px solid var(--border2);
  color: var(--text);
  padding: 5px 8px;
  font-family: var(--font-mono);
  font-size: 11px;
  outline: none;
  width: 100%;
}
.task-edit-form textarea { resize: vertical; min-height: 60px; }
.task-edit-form .ef-row { display: flex; gap: 10px; }
.task-edit-form .ef-row > div { flex: 1; display: flex; flex-direction: column; }
.task-edit-form .ef-btns { display: flex; gap: 8px; margin-top: 4px; }
.ef-btns button {
  background: transparent;
  border: 1px solid var(--border2);
  color: var(--text2);
  padding: 4px 12px;
  font-family: var(--font-ui);
  font-size: 10px;
  cursor: pointer;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}
.ef-btns .save-btn { border-color: var(--green2); color: var(--green); }
.ef-btns .save-btn:hover { background: var(--green2); }
.ef-btns .cancel-btn:hover { border-color: var(--text2); }

/* Add task form */
#add-task-form {
  display: none;
  flex-direction: column;
  gap: 8px;
  padding: 12px 14px;
  border-bottom: 2px solid var(--green2);
  background: var(--bg2);
}
#add-task-form.open { display: flex; }
#add-task-form label { font-size: 10px; color: var(--text3); text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 2px; }
#add-task-form input, #add-task-form textarea, #add-task-form select {
  background: var(--bg1);
  border: 1px solid var(--border2);
  color: var(--text);
  padding: 5px 8px;
  font-family: var(--font-mono);
  font-size: 11px;
  outline: none;
  width: 100%;
}
#add-task-form textarea { resize: vertical; min-height: 60px; }
#add-task-form .atf-row { display: flex; gap: 10px; }
#add-task-form .atf-row > div { flex: 1; display: flex; flex-direction: column; }
#add-task-form .atf-btns { display: flex; gap: 8px; }
.atf-btns button {
  background: transparent;
  border: 1px solid var(--border2);
  color: var(--text2);
  padding: 5px 14px;
  font-family: var(--font-ui);
  font-size: 10px;
  cursor: pointer;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}
.atf-btns .submit-btn { border-color: var(--green2); color: var(--green); }
.atf-btns .submit-btn:hover { background: var(--green2); }
.atf-btns .dismiss-btn:hover { border-color: var(--text2); }

/* ─── Settings Tab ───────────────────────────────────────────── */
#settings-panel {
  overflow: hidden;
}

#settings-sidebar {
  width: 160px;
  flex-shrink: 0;
  border-right: 1px solid var(--border);
  background: var(--bg1);
  display: flex;
  flex-direction: column;
  overflow-y: auto;
}

.settings-nav-item {
  padding: 8px 12px;
  font-size: 11px;
  color: var(--text2);
  cursor: pointer;
  border-left: 2px solid transparent;
  transition: color 0.1s, background 0.1s;
}
.settings-nav-item:hover { background: var(--bg2); color: var(--text); }
.settings-nav-item.active { color: var(--green); border-left-color: var(--green); background: var(--bg2); }
.settings-nav-section {
  padding: 10px 12px 3px;
  font-size: 9px;
  color: var(--text3);
  text-transform: uppercase;
  letter-spacing: 0.12em;
  border-top: 1px solid var(--border);
}
.settings-nav-section:first-child { border-top: none; }

#settings-main {
  flex: 1;
  overflow-y: auto;
  padding: 16px 20px;
}

.settings-section { display: none; }
.settings-section.active { display: block; }

.settings-group {
  margin-bottom: 24px;
}
.settings-group-title {
  font-size: 10px;
  color: var(--text3);
  text-transform: uppercase;
  letter-spacing: 0.12em;
  margin-bottom: 10px;
  padding-bottom: 5px;
  border-bottom: 1px solid var(--border);
}

.setting-row {
  display: grid;
  grid-template-columns: 200px 1fr;
  gap: 10px;
  align-items: start;
  padding: 7px 0;
  border-bottom: 1px solid #131313;
}
.setting-row:last-child { border-bottom: none; }
.setting-key {
  font-size: 11px;
  color: var(--text);
  padding-top: 4px;
}
.setting-key small { display: block; color: var(--text3); font-size: 10px; margin-top: 1px; }
.setting-val input, .setting-val select {
  width: 100%;
  background: var(--bg2);
  border: 1px solid var(--border2);
  color: var(--text);
  padding: 4px 8px;
  font-family: var(--font-mono);
  font-size: 11px;
  outline: none;
}
.setting-val input:focus, .setting-val select:focus { border-color: var(--green2); }
.setting-val input[type=checkbox] { width: auto; }

#settings-save-bar {
  display: none;
  align-items: center;
  gap: 10px;
  padding: 10px 20px;
  background: var(--bg2);
  border-top: 1px solid var(--amber);
}
#settings-save-bar.visible { display: flex; }
#settings-save-bar span { font-size: 11px; color: var(--amber); flex: 1; }
#btn-settings-save {
  background: var(--amber);
  color: #000;
  border: none;
  padding: 5px 16px;
  font-family: var(--font-ui);
  font-size: 11px;
  font-weight: 700;
  cursor: pointer;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}
#btn-settings-cancel {
  background: transparent;
  border: 1px solid var(--border2);
  color: var(--text2);
  padding: 5px 14px;
  font-family: var(--font-ui);
  font-size: 11px;
  cursor: pointer;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

/* ─── Modal (E-STOP confirmation) ────────────────────────────── */
#modal-overlay {
  display: none;
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.85);
  z-index: 100;
  align-items: center;
  justify-content: center;
}
#modal-overlay.visible { display: flex; }

#modal {
  background: var(--bg1);
  border: 2px solid var(--red);
  padding: 24px 28px;
  max-width: 420px;
  width: 90%;
}
#modal h2 {
  color: var(--red);
  font-size: 14px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  margin-bottom: 12px;
}
#modal p {
  font-size: 12px;
  color: var(--text2);
  line-height: 1.7;
  margin-bottom: 20px;
}
#modal p strong { color: var(--text); }
#modal .modal-btns { display: flex; gap: 10px; justify-content: flex-end; }
#modal-cancel {
  background: transparent;
  border: 1px solid var(--border2);
  color: var(--text2);
  padding: 6px 18px;
  font-family: var(--font-ui);
  font-size: 11px;
  cursor: pointer;
  text-transform: uppercase;
  letter-spacing: 0.06em;
}
#modal-cancel:hover { border-color: var(--text); color: var(--text); }
#modal-confirm {
  background: var(--red);
  border: 1px solid var(--red);
  color: #fff;
  padding: 6px 18px;
  font-family: var(--font-ui);
  font-size: 11px;
  font-weight: 700;
  cursor: pointer;
  text-transform: uppercase;
  letter-spacing: 0.08em;
}
#modal-confirm:hover { background: #ff0000; }

/* ─── Scrollbar ──────────────────────────────────────────────── */
::-webkit-scrollbar { width: 5px; height: 5px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--border2); border-radius: 2px; }
::-webkit-scrollbar-thumb:hover { background: var(--text3); }
</style>
</head>
<body>
<div id="app">

<!-- ═══ Header ═══════════════════════════════════════════════════ -->
<header id="header">
  <div class="h-logo">🐭 MatrixMouse</div>
  <div class="h-fields">
    <div class="h-field"><span class="lbl">Task</span><span class="val" id="v-task">—</span></div>
    <div class="h-field"><span class="lbl">Phase</span><span class="val" id="v-phase">—</span></div>
    <div class="h-field"><span class="lbl">Model</span><span class="val" id="v-model">—</span></div>
    <div class="h-field"><span class="lbl">Turns</span><span class="val" id="v-turns">—</span></div>
    <div class="h-field"><span class="lbl">Status</span><span class="val" id="v-status">idle</span></div>
  </div>
  <div id="h-controls">
    <button id="btn-stop" title="Soft stop — halt after current tool call">
      <span class="icon">■</span> Stop
    </button>
    <button id="btn-kill" title="E-STOP — emergency shutdown">
      ⚠ E-STOP
    </button>
    <div id="conn-dot"></div>
    <span id="conn-label">connecting</span>
  </div>
</header>

<!-- ═══ Sidebar ══════════════════════════════════════════════════ -->
<nav id="sidebar">
  <div class="sb-section-label">Channels</div>
  <div class="sb-item active" data-scope="workspace" onclick="selectScope('workspace')">
    <span class="sb-icon">◈</span>
    <span class="sb-name">Workspace</span>
  </div>
  <div id="sb-repos"><!-- repo items injected here --></div>

  <div id="sb-spacer"></div>

  <div class="sb-section-label">System</div>
  <div class="sb-item" data-tab="tasks" onclick="selectTab('tasks')">
    <span class="sb-icon">≡</span>
    <span class="sb-name">Tasks</span>
  </div>
  <div class="sb-item" data-tab="settings" onclick="selectTab('settings')">
    <span class="sb-icon">⚙</span>
    <span class="sb-name">Settings</span>
  </div>
</nav>

<!-- ═══ Main Panel ════════════════════════════════════════════════ -->
<main id="main">

  <!-- ── Chat Panel ── -->
  <div id="chat-panel" class="tab-panel active">
    <div id="chat-scope-label">channel: workspace</div>

    <div id="clarification">
      <div class="clar-q" id="clar-question">🔔 Awaiting your answer...</div>
      <div class="clar-row">
        <input id="clar-input" type="text" placeholder="Type your answer..." autocomplete="off">
        <button onclick="sendAnswer()">Answer</button>
      </div>
    </div>

    <div id="log"></div>

    <div id="input-row">
      <input id="msg-input" type="text"
             placeholder="Message agent (workspace)..."
             autocomplete="off">
      <button id="send-btn" onclick="sendInterjection()">Send</button>
    </div>
  </div>

  <!-- ── Tasks Panel ── -->
  <div id="tasks-panel" class="tab-panel">
    <div id="tasks-toolbar">
      <span class="tb-label">Tasks</span>
      <select id="task-filter-status" onchange="loadTasks()">
        <option value="">All active</option>
        <option value="pending">Pending</option>
        <option value="active">Active</option>
        <option value="blocked_human">Blocked</option>
        <option value="all">All (incl. done)</option>
      </select>
      <button id="btn-add-task" onclick="toggleAddTask()">+ New Task</button>
    </div>

    <div id="add-task-form">
      <div><label>Title</label><input id="atf-title" type="text" placeholder="Task title"></div>
      <div><label>Description</label><textarea id="atf-desc" placeholder="What should the agent do?"></textarea></div>
      <div class="atf-row">
        <div><label>Repo</label><select id="atf-repo"><option value="">— none —</option></select></div>
        <div><label>Importance (0–1)</label><input id="atf-imp" type="number" min="0" max="1" step="0.1" value="0.5"></div>
        <div><label>Urgency (0–1)</label><input id="atf-urg" type="number" min="0" max="1" step="0.1" value="0.5"></div>
      </div>
      <div class="atf-btns">
        <button class="submit-btn" onclick="submitNewTask()">Create Task</button>
        <button class="dismiss-btn" onclick="toggleAddTask()">Cancel</button>
      </div>
    </div>

    <div id="tasks-list"></div>
  </div>

  <!-- ── Settings Panel ── -->
  <div id="settings-panel" class="tab-panel">
    <div id="settings-sidebar">
      <div class="settings-nav-section">Workspace</div>
      <div class="settings-nav-item active" onclick="selectSettingsSection('ws-general')">General</div>
      <div class="settings-nav-item" onclick="selectSettingsSection('ws-models')">Models</div>
      <div class="settings-nav-item" onclick="selectSettingsSection('ws-context')">Context</div>
      <div id="settings-repo-nav"><!-- repo nav items injected --></div>
    </div>

    <div style="flex:1; display:flex; flex-direction:column; overflow:hidden;">
      <div id="settings-main">

        <!-- Workspace: General -->
        <div id="s-ws-general" class="settings-section active">
          <div class="settings-group">
            <div class="settings-group-title">General</div>
            <div class="setting-row">
              <div class="setting-key">Log Level<small>Service log verbosity</small></div>
              <div class="setting-val">
                <select data-key="log_level">
                  <option value="DEBUG">DEBUG</option>
                  <option value="INFO" selected>INFO</option>
                  <option value="WARNING">WARNING</option>
                  <option value="ERROR">ERROR</option>
                </select>
              </div>
            </div>
            <div class="setting-row">
              <div class="setting-key">Log to File<small>Write logs to workspace</small></div>
              <div class="setting-val"><input type="checkbox" data-key="log_to_file"></div>
            </div>
            <div class="setting-row">
              <div class="setting-key">Server Port<small>Web UI port (restart required)</small></div>
              <div class="setting-val"><input type="number" data-key="server_port" placeholder="8080"></div>
            </div>
          </div>
        </div>

        <!-- Workspace: Models -->
        <div id="s-ws-models" class="settings-section">
          <div class="settings-group">
            <div class="settings-group-title">Model Selection</div>
            <div class="setting-row">
              <div class="setting-key">Coder Model<small>Primary implementation model</small></div>
              <div class="setting-val"><input type="text" data-key="coder_model" placeholder="e.g. qwen2.5-coder:7b"></div>
            </div>
            <div class="setting-row">
              <div class="setting-key">Planner Model<small>Design and planning phases</small></div>
              <div class="setting-val"><input type="text" data-key="planner_model" placeholder="e.g. qwen3.5:9b"></div>
            </div>
            <div class="setting-row">
              <div class="setting-key">Summarizer Model<small>Context compression</small></div>
              <div class="setting-val"><input type="text" data-key="summarizer" placeholder="e.g. qwen3.5:4b"></div>
            </div>
            <div class="setting-row">
              <div class="setting-key">Coder Cascade<small>Escalation ladder (comma-separated)</small></div>
              <div class="setting-val"><input type="text" data-key="coder_cascade" placeholder="e.g. qwen2.5-coder:7b,qwen2.5-coder:32b"></div>
            </div>
          </div>
          <div class="settings-group">
            <div class="settings-group-title">Thinking Control</div>
            <p style="font-size:11px;color:var(--text3);margin-bottom:10px;">
              Extended thinking allows models to reason before responding but can consume
              large amounts of context on simple tasks. Disable per-role if needed.
            </p>
            <div class="setting-row">
              <div class="setting-key">Coder Think<small>Extended thinking for coder</small></div>
              <div class="setting-val"><input type="checkbox" data-key="coder_think"></div>
            </div>
            <div class="setting-row">
              <div class="setting-key">Planner Think<small>Extended thinking for planner</small></div>
              <div class="setting-val"><input type="checkbox" data-key="planner_think"></div>
            </div>
            <div class="setting-row">
              <div class="setting-key">Judge Think<small>Extended thinking for judge/critique</small></div>
              <div class="setting-val"><input type="checkbox" data-key="judge_think"></div>
            </div>
            <div class="setting-row">
              <div class="setting-key">Summarizer Think<small>Extended thinking for summarizer</small></div>
              <div class="setting-val"><input type="checkbox" data-key="summarizer_think"></div>
            </div>
          </div>
        </div>

        <!-- Workspace: Context -->
        <div id="s-ws-context" class="settings-section">
          <div class="settings-group">
            <div class="settings-group-title">Context Window</div>
            <div class="setting-row">
              <div class="setting-key">Soft Limit (tokens)<small>Cap below model maximum</small></div>
              <div class="setting-val"><input type="number" data-key="context_soft_limit" placeholder="32000"></div>
            </div>
            <div class="setting-row">
              <div class="setting-key">Compress Threshold<small>Fraction of limit to trigger compression</small></div>
              <div class="setting-val"><input type="number" min="0" max="1" step="0.05" data-key="compress_threshold" placeholder="0.6"></div>
            </div>
            <div class="setting-row">
              <div class="setting-key">Keep Last N Turns<small>Turns preserved during compression</small></div>
              <div class="setting-val"><input type="number" data-key="keep_last_n_turns" placeholder="6"></div>
            </div>
          </div>
        </div>

        <!-- Repo sections injected dynamically -->
        <div id="settings-repo-sections"></div>

      </div>

      <div id="settings-save-bar">
        <span>Unsaved changes — restart required to apply.</span>
        <button id="btn-settings-cancel" onclick="cancelSettings()">Cancel</button>
        <button id="btn-settings-save" onclick="saveSettings()">Save Changes</button>
      </div>
    </div>
  </div>

</main>
</div>

<!-- ═══ E-STOP Modal ═════════════════════════════════════════════ -->
<div id="modal-overlay">
  <div id="modal">
    <h2>⚠ Emergency Stop</h2>
    <p>
      This will <strong>immediately shut down MatrixMouse</strong> and prevent
      automatic restart. The agent will stop mid-task and may leave work in
      an inconsistent state.
    </p>
    <p>
      To resume, a human operator must reset the E-STOP and manually start
      the service:<br>
      <code style="color:var(--amber)">sudo systemctl start matrixmouse</code>
    </p>
    <p>For routine interruptions, use the <strong>■ Stop</strong> button instead.</p>
    <div class="modal-btns">
      <button id="modal-cancel" onclick="closeModal()">Cancel</button>
      <button id="modal-confirm" onclick="confirmKill()">Engage E-STOP</button>
    </div>
  </div>
</div>

<script>
'use strict';

// ─── State ────────────────────────────────────────────────────────
let currentScope  = 'workspace'; // 'workspace' | repo name
let currentTab    = 'chat';      // 'chat' | 'tasks' | 'settings'
let currentSettingsSection = 'ws-general';
let currentSettingsRepo    = null;
let repos         = [];
let pendingSettingsChanges = {};  // { key: value }
let settingsTarget = 'workspace'; // 'workspace' | repo name
let streamingRow  = null; // current token accumulation row
let taskEditOpen  = null; // id of task with edit form open

// ─── Utilities ────────────────────────────────────────────────────
function ts() { return new Date().toTimeString().slice(0, 8); }

function esc(s) {
  return String(s ?? '')
    .replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;');
}

// Convert newlines to <br> and escape HTML
function escLines(s) {
  return esc(s).replace(/\n/g, '<br>');
}

function $id(id) { return document.getElementById(id); }

// ─── Navigation ───────────────────────────────────────────────────
function selectScope(scope) {
  currentScope = scope;
  currentTab   = 'chat';

  // Update sidebar active state
  document.querySelectorAll('.sb-item').forEach(el => {
    el.classList.toggle('active',
      el.dataset.scope === scope && !el.dataset.tab);
  });

  // Update chat header
  $id('chat-scope-label').textContent =
    'channel: ' + (scope === 'workspace' ? 'workspace' : scope);

  // Update input placeholder
  $id('msg-input').placeholder =
    scope === 'workspace'
      ? 'Message agent (workspace)...'
      : `Message agent (${scope})...`;

  // Show chat panel
  showPanel('chat-panel');
}

function selectTab(tab) {
  currentTab = tab;

  // Deactivate all scope items
  document.querySelectorAll('.sb-item[data-scope]').forEach(el => {
    el.classList.remove('active');
  });

  // Activate tab item
  document.querySelectorAll('.sb-item[data-tab]').forEach(el => {
    el.classList.toggle('active', el.dataset.tab === tab);
  });

  if (tab === 'tasks') {
    showPanel('tasks-panel');
    loadTasks();
  } else if (tab === 'settings') {
    showPanel('settings-panel');
    loadConfig();
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

  // Show the right section
  document.querySelectorAll('.settings-section').forEach(el => {
    el.classList.toggle('active', el.id === 's-' + sectionKey);
  });

  // Determine target scope for save
  if (sectionKey.startsWith('ws-')) {
    settingsTarget = 'workspace';
  } else {
    settingsTarget = sectionKey.replace('repo-', '');
  }

  pendingSettingsChanges = {};
  $id('settings-save-bar').classList.remove('visible');
}

// ─── Header status ────────────────────────────────────────────────
function updateStatus(data) {
  $id('v-task').textContent  = data.task  || '—';
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
  } else {
    v.textContent = 'running'; v.className = 'val active';
  }
}

// ─── Event log ────────────────────────────────────────────────────
const EVENT_LABELS = {
  tool_call:             'tool',
  tool_result:           'result',
  content:               'agent',
  token:                 'agent',
  phase_change:          'phase →',
  escalation:            'escalate',
  blocked_human:         'blocked',
  complete:              '✓ done',
  error:                 'error',
  you:                   'you',
  system:                'sys',
  clarification_request: 'clarification',
};

function addEvent(type, label, text) {
  streamingRow = null; // new event breaks streaming accumulation
  const div = document.createElement('div');
  div.className = 'ev ' + type;
  div.innerHTML =
    `<span class="ev-ts">${ts()}</span>` +
    `<span class="ev-lbl">${esc(label || type)}</span>` +
    `<span class="ev-txt">${escLines(text)}</span>`;
  const log = $id('log');
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
  return div;
}

// Streaming token — append to last content row if it exists,
// otherwise create a new row. Ready for loop.py streaming support.
function appendToken(text) {
  const log = $id('log');
  if (!streamingRow) {
    streamingRow = document.createElement('div');
    streamingRow.className = 'ev token';
    streamingRow.innerHTML =
      `<span class="ev-ts">${ts()}</span>` +
      `<span class="ev-lbl">agent</span>` +
      `<span class="ev-txt"></span>`;
    log.appendChild(streamingRow);
  }
  streamingRow.querySelector('.ev-txt').textContent += text;
  log.scrollTop = log.scrollHeight;
}

// ─── Clarification banner ─────────────────────────────────────────
function showClarification(question) {
  $id('clar-question').textContent = '🔔 ' + question;
  $id('clarification').classList.add('visible');
  $id('clar-input').focus();
  addEvent('blocked_human', 'blocked', question);
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
  await apiPost('/interject', { message: reply, repo: currentScope === 'workspace' ? null : currentScope });
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
  } catch(e) {}
}, 5000);

// ─── Interjection ─────────────────────────────────────────────────
async function sendInterjection() {
  const input = $id('msg-input');
  const msg   = input.value.trim();
  if (!msg) return;
  input.value = '';
  addEvent('you', 'you', msg);
  await apiPost('/interject', {
    message: msg,
    repo: currentScope === 'workspace' ? null : currentScope,
  });
}

$id('msg-input').addEventListener('keydown', e => {
  if (e.key === 'Enter') sendInterjection();
});

// ─── Soft stop ────────────────────────────────────────────────────
$id('btn-stop').onclick = async () => {
  try {
    await apiPost('/stop', {});
    addEvent('system', 'sys', 'Soft stop requested — agent will halt after current tool call.');
  } catch(e) {
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
  } catch(e) {
    // The service may have shut down before responding — that's expected.
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
    // Populate repo select
    const sel = $id('atf-repo');
    sel.innerHTML = '<option value="">— none —</option>';
    repos.forEach(r => {
      const opt = document.createElement('option');
      opt.value = r.name;
      opt.textContent = r.name;
      sel.appendChild(opt);
    });
    $id('atf-title').focus();
  }
}

async function submitNewTask() {
  const title = $id('atf-title').value.trim();
  if (!title) { $id('atf-title').focus(); return; }

  const body = {
    title,
    description: $id('atf-desc').value.trim(),
    repo: $id('atf-repo').value ? [$id('atf-repo').value] : [],
    importance: parseFloat($id('atf-imp').value) || 0.5,
    urgency:    parseFloat($id('atf-urg').value) || 0.5,
  };

  try {
    await apiPost('/tasks', body);
    // Clear form
    ['atf-title','atf-desc'].forEach(id => $id(id).value = '');
    $id('add-task-form').classList.remove('open');
    await loadTasks();
  } catch(e) {
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
  } catch(e) {
    $id('tasks-list').innerHTML =
      '<div style="padding:14px;color:var(--text3)">Failed to load tasks.</div>';
  }
}

function dotClass(status) {
  return {
    pending:        'dot-pending',
    active:         'dot-active',
    blocked_human:  'dot-blocked',
    complete:       'dot-complete',
    cancelled:      'dot-cancelled',
  }[status] || 'dot-pending';
}

function taskRowClass(status) {
  if (status === 'active')        return 'task-row active-task';
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
    const repo  = (t.repo || []).join(', ') || '—';
    const phase = t.phase || '—';

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
      <div class="task-phase">${esc(phase)}</div>
      <div class="task-repo">${esc(t.status)}</div>
      <div class="task-actions">
        <button title="Edit" onclick="toggleTaskEdit('${t.id}', event)">✎</button>
      </div>
    `;
    list.appendChild(row);

    // Inline edit form (hidden by default)
    const editForm = document.createElement('div');
    editForm.className = 'task-edit-form';
    editForm.id = 'ef-' + t.id;
    editForm.innerHTML = `
      <div><label>Title</label><input id="ef-title-${t.id}" type="text" value="${esc(t.title)}"></div>
      <div><label>Description</label><textarea id="ef-desc-${t.id}">${esc(t.description || '')}</textarea></div>
      <div class="ef-row">
        <div><label>Importance</label><input id="ef-imp-${t.id}" type="number" min="0" max="1" step="0.1" value="${t.importance ?? 0.5}"></div>
        <div><label>Urgency</label><input id="ef-urg-${t.id}" type="number" min="0" max="1" step="0.1" value="${t.urgency ?? 0.5}"></div>
      </div>
      <div class="ef-btns">
        <button class="save-btn" onclick="saveTaskEdit('${t.id}')">Save</button>
        <button class="cancel-btn" onclick="toggleTaskEdit('${t.id}', null)">Cancel</button>
        <button style="margin-left:auto;border-color:var(--red2);color:var(--red)"
                onclick="cancelTask('${t.id}')">Cancel Task</button>
      </div>
    `;
    list.appendChild(editForm);
  });
}

function toggleTaskEdit(id, e) {
  if (e) e.stopPropagation();
  const form = $id('ef-' + id);
  if (!form) return;

  const isOpen = form.classList.contains('open');

  // Close any other open forms
  document.querySelectorAll('.task-edit-form.open').forEach(f => f.classList.remove('open'));

  if (!isOpen) {
    form.classList.add('open');
    taskEditOpen = id;
  } else {
    taskEditOpen = null;
  }
}

async function saveTaskEdit(id) {
  const body = {
    title:       $id('ef-title-' + id)?.value.trim(),
    description: $id('ef-desc-'  + id)?.value.trim(),
    importance:  parseFloat($id('ef-imp-' + id)?.value) || 0.5,
    urgency:     parseFloat($id('ef-urg-' + id)?.value) || 0.5,
  };
  try {
    await apiPatch('/tasks/' + id, body);
    await loadTasks();
  } catch(e) {
    alert('Failed to save: ' + e.message);
  }
}

async function cancelTask(id) {
  if (!confirm('Cancel this task?')) return;
  try {
    await apiDelete('/tasks/' + id);
    await loadTasks();
  } catch(e) {
    alert('Failed to cancel task: ' + e.message);
  }
}

// Refresh tasks every 10s when the tab is visible
setInterval(() => {
  if (currentTab === 'tasks') loadTasks();
}, 10000);

// ─── Settings ─────────────────────────────────────────────────────
let _configCache = {};

async function loadConfig() {
  try {
    const data = await apiFetch('/config');
    _configCache = data;
    populateSettingsFields(data, 'ws-');
  } catch(e) {}
}

function populateSettingsFields(data, prefix) {
  document.querySelectorAll('[data-key]').forEach(el => {
    const key = el.dataset.key;
    if (!(key in data)) return;
    const val = data[key];
    if (el.type === 'checkbox') {
      el.checked = !!val;
    } else {
      el.value = val ?? '';
    }
    // Track changes
    el.addEventListener('change', () => onSettingChange(el, key), { once: false });
    el.addEventListener('input',  () => onSettingChange(el, key), { once: false });
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
  } catch(e) {
    alert('Failed to save settings: ' + e.message);
  }
}

function cancelSettings() {
  pendingSettingsChanges = {};
  $id('settings-save-bar').classList.remove('visible');
  loadConfig(); // reload to reset fields
}

function injectRepoSettings(repoList) {
  const nav      = $id('settings-repo-nav');
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
        <p style="font-size:11px;color:var(--text3);margin-bottom:12px;">
          These values override workspace settings for this repo only.
          Saved to the untracked workspace state dir (layer 3).
          Use CLI with --commit to write to the repo tree (layer 4).
        </p>
        <div class="setting-row">
          <div class="setting-key">Coder Model<small>Override for this repo</small></div>
          <div class="setting-val"><input type="text" data-key="coder_model" placeholder="(inherit from workspace)"></div>
        </div>
        <div class="setting-row">
          <div class="setting-key">Coder Think<small>Override thinking for coder</small></div>
          <div class="setting-val"><input type="checkbox" data-key="coder_think"></div>
        </div>
      </div>
    `;
    sections.appendChild(section);
  });
}

// ─── Repos sidebar injection ──────────────────────────────────────
async function loadRepos() {
  try {
    const data = await apiFetch('/repos');
    repos = data.repos || [];

    const sbRepos = $id('sb-repos');
    sbRepos.innerHTML = '';
    repos.forEach(r => {
      const item = document.createElement('div');
      item.className = 'sb-item';
      item.dataset.scope = r.name;
      item.innerHTML =
        `<span class="sb-icon">⬡</span>` +
        `<span class="sb-name">${esc(r.name)}</span>`;
      item.onclick = () => selectScope(r.name);
      sbRepos.appendChild(item);
    });

    injectRepoSettings(repos);

    // Populate task add repo select if open
    const sel = $id('atf-repo');
    if (sel) {
      sel.innerHTML = '<option value="">— none —</option>';
      repos.forEach(r => {
        const opt = document.createElement('option');
        opt.value = r.name;
        opt.textContent = r.name;
        sel.appendChild(opt);
      });
    }
  } catch(e) {}
}

// ─── WebSocket ────────────────────────────────────────────────────
function connect() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const ws    = new WebSocket(`${proto}://${location.host}/ws`);

  ws.onopen = () => {
    $id('conn-dot').className   = 'live';
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

    if (msg.type === 'token') {
      appendToken(msg.data.text || '');
      return;
    }

    // Generic event
    const label = EVENT_LABELS[msg.type] || msg.type;
    const text  = msg.data?.text
               ?? msg.data?.summary
               ?? msg.data?.question
               ?? JSON.stringify(msg.data);
    addEvent(msg.type, label, text);

    // Reload tasks pane if active and a task-relevant event arrives
    if (currentTab === 'tasks' &&
        ['complete','phase_change','escalation'].includes(msg.type)) {
      loadTasks();
    }
  };

  ws.onclose = () => {
    $id('conn-dot').className   = '';
    $id('conn-label').className = '';
    $id('conn-label').textContent = 'reconnecting';
    setTimeout(connect, 3000);
  };

  ws.onerror = () => ws.close();
}

// ─── API helpers ──────────────────────────────────────────────────
async function apiFetch(url) {
  const r = await fetch(url);
  if (!r.ok) {
    const body = await r.json().catch(() => ({}));
    throw new Error(body.detail || r.statusText);
  }
  return r.json();
}

async function apiPost(url, body) {
  const r = await fetch(url, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
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
    headers: {'Content-Type': 'application/json'},
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
</script>
</body>
</html>"""
