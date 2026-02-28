"""
matrixmouse/server.py

A lightweight FastAPI application providing remote visibility and control.

Responsible for:
    - Streaming agent events (thoughts, tool calls, tool results) to 
    connected browser clients via websocket.
    - Receiving human interjectinos via POST endpoints and placing them in the 
    comms queue.
    - Displaying current task, phase, active model, and recent history.
    - Accessible from any browser on the local network; no authentication 
    required on LAN

Not a full chat interface - read-heavy with a single text input for interjections. Designed to be usable from a mobile browser.
"""

