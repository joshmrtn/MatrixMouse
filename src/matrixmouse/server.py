"""
matrixmouse/server.py

Lightweight FastAPI web interface for remote visibility and control.

Responsibilities:
    - Stream agent events (thoughts, tool calls, results) to connected
      browser clients via websocket
    - Receive human interjections via POST endpoint and place them in
      the comms queue
    - Display current task, phase, active model, and recent history
    - Accessible from any browser on the local network


Not a full chat interface - read-heavy with a single text input for 
interjections. Designed to be usable from a mobile browser.

Do not add agent logic here. This module is presentation and IO only.

TODO: Implement when comms.py is ready. The server and comms module
are tightly coupled — the server exposes the interjection endpoint
and comms owns the queue that the agent loop reads from.
"""

import logging
from matrixmouse.config import MatrixMouseConfig, MatrixMousePaths

logger = logging.getLogger(__name__)


def start_server(config: MatrixMouseConfig, paths: MatrixMousePaths) -> None:
    """
    Start the FastAPI web server in a background thread.

    TODO: Implement with FastAPI + websocket streaming.
          See architecture document section 3.10 for full spec.
    """
    logger.info("Web server not yet implemented. Skipping.")
