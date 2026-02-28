"""
/matrixmouse/comms.py

Manages all channels between the agent and the human operator. 

Responsble for:
    - Interjection queue: polls for pending human messages, injects them into 
    the message history at the next loop iteration boundary.
    - Notification dispatch: sends push notifications (via ntfy) when the agent 
    is blocked and requires human input.
    - Status broadcast: pushes structured events to connected websocket clients 
    for the web UI.
    - Clarification requests: exposes `request_clarification(question, blocking)` 
    tool; `blocking=True` halts the loop until a response is received.
"""
