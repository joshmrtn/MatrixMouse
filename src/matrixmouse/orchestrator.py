"""
matrixmouse/orchestrator.py

Task and Phase Manager. The outermost control loop. 

Responsible for:
    - Fetching tasks from GitHub/Gitea issues or local queue
    - Scoping each task: identifying relevant files, design documents, and 
    prior notes
    - Managing the SDLC phase state machine: design → critique → implement 
    → test → review → done
    - Deciding which agent role (designer, implementer, critic) handles each 
    phase
    - Routing escalated or blocked tasks to the human via the comms module
    - Ensuring no phase is skipped; enforcing that implementation only begins 
    after design is approved
Batching tasks by type to minimise model-switching overhead

Phase transition rules:
    - design → critique: design document written, no code exists yet
    - critique → implement: design document status set to approved
    - implement → test: at least one write tool was called successfully
    - test → review: test suite passes
    - review → done: human approves PR, or auto-approved if confidence 
    threshold met
"""

