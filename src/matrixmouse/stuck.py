"""
matrixmouse/stuck.py

Monitors the agent's behavior within a task and emits escalation signals.

Detects:
    - Repeated identical tool calls within a sliding window (hash-based).
    - Consecutive tool call errors without a successful write.
    - Extended read-only stretches late in an implementation phase.
    - Explicit `"stuck"` self-assessment from periodic model progress checks

Produces a float escalation score (0.0-1.0). Escalation triggers when score 
exceeds a configurable threshold, which varies by task phase (higher threshold 
during exploration, lower during implementation).
Does not directly escalate - reports score to `orchestrator.py`, which decides 
action.
"""
