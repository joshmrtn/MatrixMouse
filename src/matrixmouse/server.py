"""
matrixmouse/server.py

Web UI and websocket event streaming for MatrixMouse.

Responsibilities:
    - Serve the self-contained HTML UI at GET /
    - Stream agent events to connected browsers via websocket at /ws
    - Register as a comms listener to receive events from the agent loop

Architecture:
    - Imports the FastAPI app instance from api.py and registers /ws and /
      against it. All REST endpoints live in api.py.
    - Runs in a daemon thread (uvicorn) so it never blocks the agent loop.
    - Agent loop thread -> comms.emit() -> _on_event() -> asyncio queue ->
      websocket broadcast. The asyncio queue is the thread-safe bridge
      between the agent thread and the uvicorn event loop.

Do not add REST endpoints or agent logic here.
Dependencies: fastapi, uvicorn
"""

import asyncio
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
    Start the web server in a background daemon thread.

    Binds to 0.0.0.0 so it is reachable from other devices on the LAN.
    The thread exits automatically when the main process ends.

    Args:
        config: Active config (reads server_port).
        paths:  Resolved paths (reserved for future static file serving).
    """
    try:
        import uvicorn
        from matrixmouse.api import app
        from matrixmouse import comms as comms_module

        port = getattr(config, "server_port", 8080)

        # _broadcast_queue bridges the agent thread and the uvicorn event loop.
        # The agent thread puts events here; the websocket handler drains it.
        broadcast_queue: asyncio.Queue = None  # set inside the thread

        # Register the websocket and UI routes against the api.py app
        _register_routes(app, comms_module)

        def _run() -> None:
            nonlocal broadcast_queue

            # Create a fresh event loop for this thread
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            # Now that we have an event loop, create the queue and register
            # the comms listener that puts events into it
            broadcast_queue = asyncio.Queue()
            _register_comms_listener(comms_module, broadcast_queue, loop)

            # Pass the queue to the websocket handler via app state
            app.state.broadcast_queue = broadcast_queue

            uvicorn.run(
                app,
                host="0.0.0.0",
                port=port,
                log_level="warning",
                access_log=False,
                loop="none",         # we manage the loop ourselves
            )

        thread = threading.Thread(
            target=_run,
            daemon=True,
            name="matrixmouse-server",
        )
        thread.start()
        logger.info("Web server started on port %d", port)

    except ImportError:
        logger.warning(
            "fastapi or uvicorn not installed. Web UI disabled. "
            "Install with: pip install fastapi uvicorn"
        )
    except Exception as e:
        logger.warning(
            "Failed to start web server: %s. Continuing without UI.", e
        )


# ---------------------------------------------------------------------------
# Route registration — called once before uvicorn starts
# ---------------------------------------------------------------------------

def _register_routes(app, comms_module: Any) -> None:
    """
    Register the websocket and UI routes on the shared FastAPI app.
    Called once at startup. Safe to call multiple times — FastAPI
    deduplicates routes by path.
    """
    from fastapi import WebSocket, WebSocketDisconnect
    from fastapi.responses import HTMLResponse

    # Guard against double-registration if start_server is called twice
    existing_paths = {r.path for r in app.routes}
    if "/ws" in existing_paths:
        return

    # ------------------------------------------------------------------
    # Active websocket connections
    # ------------------------------------------------------------------
    _connections: list[WebSocket] = []
    _connections_lock = threading.Lock()

    @app.get("/", response_class=HTMLResponse)
    async def index():
        """Serve the self-contained web UI."""
        return HTMLResponse(_build_html())

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        """
        Websocket endpoint for real-time event streaming.

        On connect: sends the current status so the UI is not blank.
        Then drains app.state.broadcast_queue and forwards each event
        to all connected clients.
        """
        await websocket.accept()
        with _connections_lock:
            _connections.append(websocket)
        logger.debug(
            "Websocket client connected. Total: %d", len(_connections)
        )

        # Send current status immediately
        m = comms_module.get_manager()
        if m:
            await websocket.send_text(json.dumps({
                "type": "status_update",
                "data": m.status,
            }))

        try:
            # Drain the broadcast queue and forward to this client.
            # We also need to keep receiving from the client to detect
            # disconnects — run both concurrently.
            queue: asyncio.Queue = app.state.broadcast_queue

            async def _drain():
                try:
                    while True:
                        payload = await queue.get()
                        # Broadcast to all current connections
                        with _connections_lock:
                            live = list(_connections)
                        dead = []
                        for ws in live:
                            try:
                                await ws.send_text(payload)
                            except Exception:
                                dead.append(ws)
                        with _connections_lock:
                            for ws in dead:
                                if ws in _connections:
                                    _connections.remove(ws)
                except asyncio.CancelledError:
                    pass # normal cancellation when _receive exits first

            async def _receive():
                # Keep the connection alive; client sends nothing meaningful
                try:
                    while True:
                        data = await websocket.receive_text()
                        # For now, data is discarded
                        # TODO: Handlie incoming messages/signals
                except WebSocketDisconnect:
                    pass # Normal disconnect - let asyncio.wait() clean up

            drain_task   = asyncio.create_task(_drain())
            receive_task = asyncio.create_task(_receive())

            done, pending = await asyncio.wait(
                [drain_task, receive_task],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()

        except WebSocketDisconnect:
            pass
        except Exception as e:
            logger.debug("Websocket error: %s", e)
        finally:
            with _connections_lock:
                if websocket in _connections:
                    _connections.remove(websocket)
            logger.debug(
                "Websocket client disconnected. Total: %d",
                len(_connections),
            )


def _register_comms_listener(
    comms_module: Any,
    broadcast_queue: asyncio.Queue,
    loop: asyncio.AbstractEventLoop,
) -> None:
    """
    Register a comms listener that forwards agent events to the
    websocket broadcast queue.

    The listener is called from the agent loop thread. It uses
    asyncio.run_coroutine_threadsafe with the uvicorn event loop
    to safely enqueue the event for the websocket handler.
    """
    def _on_event(event) -> None:
        payload = json.dumps({
            "type": event.event_type,
            "data": event.data,
        })
        asyncio.run_coroutine_threadsafe(
            broadcast_queue.put(payload),
            loop,
        )

    manager = comms_module.get_manager()
    if manager:
        manager.register_listener(_on_event)
        logger.debug("Comms listener registered for websocket broadcast.")
    else:
        logger.warning(
            "Comms manager not ready when server started. "
            "Events will not be streamed to the web UI."
        )


# ---------------------------------------------------------------------------
# Self-contained HTML UI
# ---------------------------------------------------------------------------

def _build_html() -> str:
    """
    Return a self-contained single-page web UI as a string.
    No external dependencies — works on any browser including mobile.

    Current capabilities:
        - Live event stream via websocket
        - Status header (task, phase, model, turns)
        - Workspace-wide interjection input
        - Pending clarification banner with inline answer form

    TODO (future iterations):
        - Repo selector / tab for scoped interjections
        - Task graph visualisation
        - Config editor
    """
    return r"""<!DOCTYPE html>
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

  /* --- Header --- */
  #header {
    display: flex;
    gap: 16px;
    flex-wrap: wrap;
    align-items: center;
    padding: 8px 12px;
    background: #161616;
    border: 1px solid #2a2a2a;
    border-radius: 6px;
    font-size: 13px;
  }
  #header .field { color: #888; }
  #header .field b { color: #50fa7b; }
  #header .field.blocked b { color: #ff5555; }
  #conn {
    margin-left: auto;
    font-size: 11px;
    color: #555;
  }
  #conn.live { color: #50fa7b; }

  /* --- Clarification banner --- */
  #clarification {
    display: none;
    background: #1a1200;
    border: 1px solid #ffb86c;
    border-radius: 6px;
    padding: 10px 14px;
    font-size: 13px;
    gap: 8px;
    flex-direction: column;
  }
  #clarification.visible { display: flex; }
  #clarification .question {
    color: #ffb86c;
    font-weight: bold;
  }
  #clarification .answer-row {
    display: flex;
    gap: 8px;
  }
  #clarification input {
    flex: 1;
    background: #111;
    border: 1px solid #ffb86c;
    border-radius: 4px;
    color: #c8c8c8;
    padding: 6px 10px;
    font-family: monospace;
    font-size: 13px;
  }
  #clarification input:focus { outline: none; }
  #clarification button {
    background: #ffb86c;
    color: #0d0d0d;
    border: none;
    border-radius: 4px;
    padding: 6px 14px;
    font-family: monospace;
    font-weight: bold;
    cursor: pointer;
  }

  /* --- Event log --- */
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
  .ev { padding: 2px 0; border-bottom: 1px solid #1a1a1a; }
  .ev .ts { color: #555; margin-right: 8px; }
  .ev.tool_call     .lbl { color: #8be9fd; }
  .ev.tool_result   .lbl { color: #f1fa8c; }
  .ev.content       .lbl { color: #bd93f9; }
  .ev.phase_change  .lbl { color: #50fa7b; font-weight: bold; }
  .ev.escalation    .lbl { color: #ffb86c; }
  .ev.blocked_human .lbl { color: #ff5555; }
  .ev.complete      .lbl { color: #50fa7b; font-weight: bold; }
  .ev.error         .lbl { color: #ff5555; }
  .ev.you           .lbl { color: #bd93f9; }

  /* --- Interjection input --- */
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
  #send-btn {
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
  #send-btn:hover { background: #69ff94; }
</style>
</head>
<body>

<!-- Status header -->
<div id="header">
  <span class="field">🐭 <b>MatrixMouse</b></span>
  <span class="field">task: <b id="v-task">—</b></span>
  <span class="field">phase: <b id="v-phase">—</b></span>
  <span class="field">model: <b id="v-model">—</b></span>
  <span class="field">turns: <b id="v-turns">—</b></span>
  <span class="field" id="f-status">status: <b id="v-status">idle</b></span>
  <span id="conn">connecting...</span>
</div>

<!-- Clarification banner — shown when agent is blocked waiting for human -->
<div id="clarification">
  <div class="question" id="clarification-question"></div>
  <div class="answer-row">
    <input id="clarification-input" type="text"
           placeholder="Type your answer..." autocomplete="off">
    <button id="clarification-send">Answer</button>
  </div>
</div>

<!-- Event log -->
<div id="log"></div>

<!-- Interjection input -->
<div id="input-row">
  <input id="msg" type="text"
         placeholder="Send a message to the agent (workspace-wide)..."
         autocomplete="off">
  <button id="send-btn">Send</button>
</div>

<script>
const log        = document.getElementById('log');
const connEl     = document.getElementById('conn');
const clarDiv    = document.getElementById('clarification');
const clarQ      = document.getElementById('clarification-question');
const clarInput  = document.getElementById('clarification-input');

// --- Utilities ---

function ts() {
  return new Date().toTimeString().slice(0, 8);
}

function esc(s) {
  return String(s)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function addEvent(type, label, text) {
  const div = document.createElement('div');
  div.className = 'ev ' + type;
  div.innerHTML =
    `<span class="ts">${ts()}</span>` +
    `<span class="lbl">[${esc(label)}]</span> ${esc(text)}`;
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
}

// --- Status header ---

function updateStatus(data) {
  document.getElementById('v-task').textContent   = data.task  || '—';
  document.getElementById('v-phase').textContent  = data.phase || '—';
  document.getElementById('v-model').textContent  = data.model || '—';
  document.getElementById('v-turns').textContent  = data.turns ?? '—';
  const blocked = data.blocked;
  const idle    = data.idle;
  document.getElementById('v-status').textContent =
    blocked ? 'BLOCKED' : idle ? 'idle' : 'running';
  document.getElementById('f-status').className =
    'field' + (blocked ? ' blocked' : '');
}

// --- Clarification banner ---

function showClarification(question) {
  clarQ.textContent = '🔔 ' + question;
  clarDiv.classList.add('visible');
  clarInput.focus();
  addEvent('blocked_human', 'clarification', question);
}

function hideClarification() {
  clarDiv.classList.remove('visible');
  clarInput.value = '';
}

async function sendAnswer() {
  const reply = clarInput.value.trim();
  if (!reply) return;
  addEvent('you', 'you', reply);
  hideClarification();
  await postInterject(reply, null);
}

document.getElementById('clarification-send').onclick = sendAnswer;
clarInput.addEventListener('keydown', e => {
  if (e.key === 'Enter') sendAnswer();
});

// Poll for pending clarification questions every 5 seconds.
// This ensures the banner appears even if the websocket event is missed.
setInterval(async () => {
  try {
    const r = await fetch('/pending');
    const data = await r.json();
    if (data.pending && !clarDiv.classList.contains('visible')) {
      showClarification(data.pending);
    } else if (!data.pending && clarDiv.classList.contains('visible')) {
      hideClarification();
    }
  } catch(e) { /* ignore network errors during poll */ }
}, 5000);

// --- Websocket ---

const EVENT_LABELS = {
  tool_call:             'tool',
  tool_result:           'result',
  content:               'agent',
  phase_change:          'phase',
  escalation:            'escalate',
  blocked_human:         'blocked',
  complete:              'complete',
  error:                 'error',
  clarification_request: 'clarification',
};

function connect() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const ws    = new WebSocket(`${proto}://${location.host}/ws`);

  ws.onopen = () => {
    connEl.textContent = 'live';
    connEl.className   = 'live';
  };

  ws.onmessage = (e) => {
    const msg = JSON.parse(e.data);

    if (msg.type === 'status_update') {
      updateStatus(msg.data);
      return;
    }

    if (msg.type === 'clarification_request') {
      showClarification(msg.data.question || JSON.stringify(msg.data));
      return;
    }

    // Generic event
    const label = EVENT_LABELS[msg.type] || msg.type;
    const text  = msg.data.text
               || msg.data.summary
               || msg.data.question
               || JSON.stringify(msg.data);
    addEvent(msg.type, label, text);
  };

  ws.onclose = () => {
    connEl.textContent = 'reconnecting...';
    connEl.className   = '';
    setTimeout(connect, 3000);
  };

  ws.onerror = () => ws.close();
}

connect();

// --- Interjection ---

async function postInterject(message, repo) {
  try {
    const resp = await fetch('/interject', {
      method:  'POST',
      headers: {'Content-Type': 'application/json'},
      body:    JSON.stringify({ message, repo }),
    });
    if (!resp.ok) addEvent('error', 'error', 'Failed to send message.');
  } catch(e) {
    addEvent('error', 'error', 'Network error: ' + e.message);
  }
}

async function sendInterjection() {
  const input = document.getElementById('msg');
  const msg   = input.value.trim();
  if (!msg) return;
  input.value = '';
  addEvent('you', 'you', msg);
  await postInterject(msg, null);
}

document.getElementById('send-btn').onclick = sendInterjection;
document.getElementById('msg').addEventListener('keydown', e => {
  if (e.key === 'Enter') sendInterjection();
});
</script>
</body>
</html>"""
