"""
matrixmouse/server.py

Web server startup and WebSocket event streaming for MatrixMouse.

Responsibilities:
    - Start uvicorn in a background daemon thread
    - Register /ws and / routes on the shared FastAPI app from api.py
    - Implement fan-out broadcast so all connected clients receive events
    - Bridge the agent loop thread to the async websocket via a thread-safe queue
    - Register as a comms listener to receive events from the agent loop

Architecture:
    Agent loop thread
        → comms.emit()
        → _on_event() [sync callback, agent thread]
        → asyncio.run_coroutine_threadsafe → _broadcaster_queue
        → _broadcaster() [async task, uvicorn event loop]
        → per-connection queue for each live WebSocket client
        → websocket.send_text()

    Each WebSocket connection gets its own queue. The broadcaster drains
    the single shared input queue and fans out to all per-connection queues.
    This ensures all connected clients receive all events — the previous
    single-queue design caused events to be consumed by whichever _drain
    task ran first.

    The HTML/JS/CSS frontend lives in web_ui.py.

Do not add REST endpoints or agent logic here.
Dependencies: fastapi, uvicorn, websockets (via uvicorn[standard])
"""

import asyncio
import json
import logging
import threading
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket

from matrixmouse.config import MatrixMouseConfig, MatrixMousePaths

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Server startup
# ---------------------------------------------------------------------------

def start_server(config: MatrixMouseConfig, paths: MatrixMousePaths) -> None:
    """
    Start the web server in a background daemon thread.

    Binds to 0.0.0.0 so it is reachable via nginx reverse proxy.
    The thread exits automatically when the main process ends.

    Args:
        config: Active config (reads server_port).
        paths:  Resolved paths (reserved for future static file serving).
    """
    try:
        import uvicorn
        from matrixmouse.api import app
        from matrixmouse import comms as comms_module

        port = config.server_port

        _register_routes(app, comms_module)

        def _run() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            # Single shared input queue — agent thread puts events here.
            # _broadcaster fans out to per-connection queues.
            broadcaster_queue: asyncio.Queue = asyncio.Queue()
            _register_comms_listener(comms_module, broadcaster_queue, loop)
            app.state.broadcaster_queue = broadcaster_queue

            uvicorn.run(
                app,
                host="0.0.0.0",
                port=port,
                log_level="warning",
                access_log=False,
                loop="none",
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
            "Install with: pip install 'fastapi' 'uvicorn[standard]'"
        )
    except Exception as e:
        logger.warning(
            "Failed to start web server: %s. Continuing without UI.", e
        )


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------

def _register_routes(app, comms_module: Any) -> None:
    """
    Register /ws and / routes on the shared FastAPI app.
    Called once at startup. Guarded against double-registration.
    """
    from fastapi import WebSocket, WebSocketDisconnect
    from fastapi.responses import HTMLResponse
    from matrixmouse.web_ui import build_html

    existing_paths = {r.path for r in app.routes}
    if "/ws" in existing_paths:
        return

    # Registry of per-connection queues.
    # broadcaster() puts into all of these; each _drain() reads from its own.
    _client_queues: list[asyncio.Queue] = []
    _client_queues_lock = threading.Lock()

    @app.get("/", response_class=HTMLResponse)
    async def index():
        """Serve the self-contained web UI."""
        return HTMLResponse(build_html())

    @app.get("/{path:path}")
    async def spa_fallback(path: str):
        """
        Serve index.html for SPA routes (client-side routing).

        This allows direct navigation and page refresh on any frontend route
        like /task-list, /dashboard, /task/{id}, etc.

        API routes are excluded and will return 404 from this handler.
        """
        API_PREFIXES = (
            'tasks/', 'repos/', 'status', 'blocked',
            'config', 'context', 'health', 'ws',
            'stop', 'kill', 'estop', 'pending',
            'token_usage', 'orchestrator', 'interject',
        )
        if any(path.startswith(p) for p in API_PREFIXES):
            raise HTTPException(status_code=404)
        return HTMLResponse(build_html())

    # -----------------------------------------------------------------------
    # Lifespan — replaces deprecated @app.on_event("startup")
    # -----------------------------------------------------------------------
    @asynccontextmanager
    async def _lifespan(application):
        """Start the fan-out broadcaster as a background asyncio task."""
        async def _broadcaster():
            while not hasattr(application.state, "broadcaster_queue"):
                await asyncio.sleep(0.05)

            queue: asyncio.Queue = application.state.broadcaster_queue
            while True:
                try:
                    payload = await queue.get()
                    with _client_queues_lock:
                        targets = list(_client_queues)
                    for q in targets:
                        try:
                            q.put_nowait(payload)
                        except asyncio.QueueFull:
                            pass
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.debug("Broadcaster error: %s", e)

        task = asyncio.create_task(_broadcaster(), name="matrixmouse-broadcaster")
        yield
        task.cancel()

    app.router.lifespan_context = _lifespan

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        """
        WebSocket endpoint for real-time event streaming.

        On connect: sends current status snapshot so the UI is not blank.
        Then drains this connection's personal queue, forwarding each event
        to the client. Handles disconnects cleanly.
        """
        await websocket.accept()

        # Each connection gets its own queue fed by the broadcaster.
        my_queue: asyncio.Queue = asyncio.Queue(maxsize=256)
        with _client_queues_lock:
            _client_queues.append(my_queue)

        logger.debug(
            "WebSocket client connected. Total: %d", len(_client_queues)
        )

        # Send current status snapshot immediately on connect
        m = comms_module.get_manager()
        if m:
            try:
                await websocket.send_text(json.dumps({
                    "type": "status_update",
                    "data": m.status,
                }))
            except Exception:
                pass

        try:
            async def _drain():
                """Drain this connection's queue and send to client."""
                try:
                    while True:
                        payload = await my_queue.get()
                        await websocket.send_text(payload)
                except asyncio.CancelledError:
                    pass
                except Exception:
                    pass  # client disconnected mid-send

            async def _receive():
                """Keep connection alive and detect client disconnect."""
                try:
                    while True:
                        await websocket.receive_text()
                        # Incoming messages currently unused.
                        # Future: handle client-side signals here.
                except WebSocketDisconnect:
                    pass
                except Exception:
                    pass

            drain_task   = asyncio.create_task(_drain())
            receive_task = asyncio.create_task(_receive())

            await asyncio.wait(
                [drain_task, receive_task],
                return_when=asyncio.FIRST_COMPLETED,
            )
            drain_task.cancel()
            receive_task.cancel()

        except WebSocketDisconnect:
            pass
        except Exception as e:
            logger.debug("WebSocket error: %s", e)
        finally:
            with _client_queues_lock:
                if my_queue in _client_queues:
                    _client_queues.remove(my_queue)
            logger.debug(
                "WebSocket client disconnected. Total: %d", len(_client_queues)
            )


# ---------------------------------------------------------------------------
# Comms listener — bridges agent thread to async broadcast queue
# ---------------------------------------------------------------------------

def _register_comms_listener(
    comms_module: Any,
    broadcaster_queue: asyncio.Queue,
    loop: asyncio.AbstractEventLoop,
) -> None:
    """
    Register a listener on the comms manager that forwards agent events
    to the broadcaster queue using thread-safe asyncio bridging.

    The listener is called from the agent loop thread (synchronous context).
    asyncio.run_coroutine_threadsafe safely hands the event to the uvicorn
    event loop without blocking the agent thread.
    """
    def _on_event(event) -> None:
        payload = json.dumps({
            "type": event.event_type,
            "data": event.data,
        })
        asyncio.run_coroutine_threadsafe(
            broadcaster_queue.put(payload),
            loop,
        )

    manager = comms_module.get_manager()
    if manager:
        manager.register_listener(_on_event)
        logger.debug("Comms listener registered for WebSocket broadcast.")
    else:
        logger.warning(
            "Comms manager not ready when server started. "
            "Events will not be streamed to the web UI."
        )
