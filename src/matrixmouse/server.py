"""
matrixmouse/server.py

Lightweight FastAPI web interface for remote visibility and control.

Responsibilities:
    - Stream agent events to connected browser clients via websocket
    - Receive human interjections via POST /interject
    - Serve a self-contained HTML UI at GET /
    - Display current task, phase, active model, turn count
    - Accessible from any browser on the local network

Architecture:
    - Runs in a daemon thread so it never blocks the agent loop
    - Registers itself as a comms listener to receive agent events
    - Writes interjections directly to the comms interjection queue
    - No authentication for MVP — rely on network-level access control

Do not add agent logic here. This module is presentation and IO only.

Dependencies:
    fastapi
    uvicorn
"""

import json
import logging
import threading
from typing import Any

from matrixmouse.config import MatrixMouseConfig, MatrixMousePaths

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Server startup
# ---------------------------------------------------------------------------

def start_server(config: MatrixMouseConfig, paths: MatrixMousePaths) -> None:
    """
    Start the FastAPI web server in a background daemon thread.

    Binds to 0.0.0.0 so it is reachable from other devices on the LAN.
    The thread is a daemon — it exits automatically when the main process
    ends, no cleanup required.

    Args:
        config: Active MatrixMouseConfig (reads server_port).
        paths:  Resolved MatrixMousePaths (unused currently, reserved
                for future static file serving).
    """
    try:
        import uvicorn
        from matrixmouse import comms as comms_module

        app = _build_app(comms_module)
        port = getattr(config, "server_port", 7654)

        def _run() -> None:
            uvicorn.run(
                app,
                host="0.0.0.0",
                port=port,
                log_level="warning",   # suppress uvicorn access logs in agent output
                access_log=False,
            )

        thread = threading.Thread(target=_run, daemon=True, name="matrixmouse-server")
        thread.start()
        logger.info("Web UI available at http://0.0.0.0:%d", port)

    except ImportError:
        logger.warning(
            "fastapi or uvicorn not installed. Web UI disabled. "
            "Install with: pip install fastapi uvicorn"
        )
    except Exception as e:
        logger.warning("Failed to start web server: %s. Continuing without UI.", e)


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def _build_app(comms_module: Any):
    """
    Build and return the FastAPI application.
    Separated from start_server so the import error is caught cleanly.
    """
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect
    from fastapi.responses import HTMLResponse
    from pydantic import BaseModel

    app = FastAPI(title="MatrixMouse", docs_url=None, redoc_url=None)

    # Active websocket connections — all receive every event
    _connections: list[WebSocket] = []
    _connections_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Comms listener — receives AgentEvents and broadcasts to websockets
    # ------------------------------------------------------------------

    def _on_event(event) -> None:
        """
        Called by comms.emit() for every agent event.
        Broadcasts to all connected websocket clients.
        Runs in the agent loop thread — uses asyncio.run_coroutine_threadsafe
        to safely hand off to the uvicorn event loop.
        """
        import asyncio

        payload = json.dumps({
            "type": event.event_type,
            "data": event.data,
        })

        with _connections_lock:
            dead = []
            for ws in _connections:
                try:
                    # Each websocket has its own event loop via uvicorn
                    future = asyncio.run_coroutine_threadsafe(
                        ws.send_text(payload),
                        ws.client_state.__class__._loop
                        if hasattr(ws.client_state.__class__, "_loop")
                        else asyncio.get_event_loop(),
                    )
                    future.result(timeout=1.0)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                _connections.remove(ws)

    # Register with comms so we receive all events
    manager = comms_module.get_manager()
    if manager:
        manager.register_listener(_on_event)

    # ------------------------------------------------------------------
    # Routes
    # ------------------------------------------------------------------

    @app.get("/", response_class=HTMLResponse)
    async def index():
        """Serve the self-contained web UI."""
        return HTMLResponse(_build_html())

    @app.get("/status")
    async def status():
        """Return current agent status as JSON."""
        m = comms_module.get_manager()
        return m.status if m else {"error": "comms not configured"}

    class InterjectionRequest(BaseModel):
        message: str
        repo: str | None = None

    @app.post("/interject")
    async def interject(body: InterjectionRequest):
        """
        Accept a human interjection and place it in the comms queue.
        The agent loop picks it up at the next iteration boundary.
        """
        m = comms_module.get_manager()
        if m is None:
            return {"error": "comms not configured"}
        if not body.message.strip():
            return {"error": "message cannot be empty"}
        m.put_interjection(body.message, repo=getattr(body, "repo", None))
        logger.info("Interjection received via web UI: %s", body.message[:80])
        return {"ok": True, "message": body.message}

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        """
        Websocket endpoint for real-time event streaming.
        Clients connect here and receive JSON events as the agent works.
        """
        await websocket.accept()
        with _connections_lock:
            _connections.append(websocket)
        logger.debug("Websocket client connected. Total: %d", len(_connections))

        # Send current status immediately on connect so the UI is not blank
        m = comms_module.get_manager()
        if m:
            await websocket.send_text(json.dumps({
                "type": "status_update",
                "data": m.status,
            }))

        try:
            while True:
                # Keep the connection alive by waiting for any client message.
                # The client doesn't send anything meaningful — this just
                # prevents the connection from timing out.
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            with _connections_lock:
                if websocket in _connections:
                    _connections.remove(websocket)
            logger.debug("Websocket client disconnected. Total: %d", len(_connections))

    return app


# ---------------------------------------------------------------------------
# Self-contained HTML UI
# ---------------------------------------------------------------------------

def _build_html() -> str:
    """
    Return a self-contained HTML page as a string.
    No external dependencies — works on any browser including mobile.
    """
    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>MatrixMouse</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: monospace;
    background: #0d0d0d;
    color: #c8c8c8;
    display: flex;
    flex-direction: column;
    height: 100vh;
    padding: 12px;
    gap: 10px;
  }
  #header {
    display: flex;
    gap: 16px;
    flex-wrap: wrap;
    padding: 8px 12px;
    background: #161616;
    border: 1px solid #2a2a2a;
    border-radius: 6px;
    font-size: 13px;
  }
  #header span { color: #888; }
  #header span b { color: #50fa7b; }
  #header .blocked b { color: #ff5555; }
  #log {
    flex: 1;
    overflow-y: auto;
    background: #111;
    border: 1px solid #2a2a2a;
    border-radius: 6px;
    padding: 10px;
    font-size: 12px;
    line-height: 1.6;
  }
  .event { padding: 2px 0; border-bottom: 1px solid #1a1a1a; }
  .event .ts { color: #555; margin-right: 8px; }
  .event.tool_call .label { color: #8be9fd; }
  .event.tool_result .label { color: #f1fa8c; }
  .event.content .label { color: #bd93f9; }
  .event.phase_change .label { color: #50fa7b; font-weight: bold; }
  .event.escalation .label { color: #ffb86c; }
  .event.blocked .label { color: #ff5555; }
  .event.complete .label { color: #50fa7b; font-weight: bold; }
  .event.error .label { color: #ff5555; }
  .event.status_update { display: none; }
  #input-row {
    display: flex;
    gap: 8px;
  }
  #msg {
    flex: 1;
    background: #161616;
    border: 1px solid #2a2a2a;
    border-radius: 6px;
    color: #c8c8c8;
    padding: 8px 12px;
    font-family: monospace;
    font-size: 13px;
  }
  #msg:focus { outline: none; border-color: #50fa7b; }
  #send {
    background: #50fa7b;
    color: #0d0d0d;
    border: none;
    border-radius: 6px;
    padding: 8px 18px;
    font-family: monospace;
    font-weight: bold;
    cursor: pointer;
    font-size: 13px;
  }
  #send:hover { background: #69ff94; }
  #conn {
    font-size: 11px;
    color: #555;
    text-align: right;
  }
  #conn.live { color: #50fa7b; }
</style>
</head>
<body>

<div id="header">
  <span>🐭 <b>MatrixMouse</b></span>
  <span id="h-task">task: <b id="v-task">—</b></span>
  <span id="h-phase">phase: <b id="v-phase">—</b></span>
  <span id="h-model">model: <b id="v-model">—</b></span>
  <span id="h-turns">turns: <b id="v-turns">—</b></span>
  <span id="h-blocked">status: <b id="v-blocked">idle</b></span>
</div>

<div id="log"></div>

<div id="input-row">
  <input id="msg" type="text" placeholder="Send a message to the agent..." autocomplete="off">
  <button id="send">Send</button>
</div>
<div id="conn">connecting...</div>

<script>
const log = document.getElementById('log');
const connEl = document.getElementById('conn');

function ts() {
  const now = new Date();
  return now.toTimeString().slice(0,8);
}

function addEvent(type, label, text) {
  const div = document.createElement('div');
  div.className = 'event ' + type;
  div.innerHTML = `<span class="ts">${ts()}</span><span class="label">[${label}]</span> ${escHtml(text)}`;
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
}

function escHtml(s) {
  return String(s)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function updateStatus(data) {
  document.getElementById('v-task').textContent = data.task || '—';
  document.getElementById('v-phase').textContent = data.phase || '—';
  document.getElementById('v-model').textContent = data.model || '—';
  document.getElementById('v-turns').textContent = data.turns ?? '—';
  const blocked = data.blocked;
  document.getElementById('v-blocked').textContent = blocked ? 'BLOCKED' : 'running';
  document.getElementById('h-blocked').className = blocked ? 'blocked' : '';
}

const labels = {
  tool_call:    'tool',
  tool_result:  'result',
  content:      'agent',
  phase_change: 'phase',
  escalation:   'escalate',
  blocked:      'blocked',
  complete:     'complete',
  error:        'error',
  clarification_request: 'clarification',
};

function connect() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const ws = new WebSocket(`${proto}://${location.host}/ws`);

  ws.onopen = () => {
    connEl.textContent = 'connected';
    connEl.className = 'live';
  };

  ws.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    if (msg.type === 'status_update') {
      updateStatus(msg.data);
      return;
    }
    const label = labels[msg.type] || msg.type;
    const text = msg.data.text || msg.data.summary || msg.data.question
               || JSON.stringify(msg.data);
    addEvent(msg.type, label, text);
  };

  ws.onclose = () => {
    connEl.textContent = 'disconnected — retrying...';
    connEl.className = '';
    setTimeout(connect, 3000);
  };

  ws.onerror = () => ws.close();
}

connect();

async function sendMessage() {
  const input = document.getElementById('msg');
  const msg = input.value.trim();
  if (!msg) return;
  input.value = '';

  addEvent('content', 'you', msg);

  try {
    const resp = await fetch('/interject', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({message: msg}),
    });
    if (!resp.ok) addEvent('error', 'error', 'Failed to send message.');
  } catch(e) {
    addEvent('error', 'error', 'Network error: ' + e.message);
  }
}

document.getElementById('send').onclick = sendMessage;
document.getElementById('msg').addEventListener('keydown', e => {
  if (e.key === 'Enter') sendMessage();
});
</script>
</body>
</html>"""
