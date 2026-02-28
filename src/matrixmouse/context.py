"""
matrixmouse/context.py

Responsible for keeping the message history within a safe working limit. 

Responsibilities:
    - Estimating token usage from current message history
    - Triggering summarisation when usage exceeds a configurable soft limit 
    (default: 60% of model context length, capped at ~32k tokens regardless of 
    model maximum)
    - Performing summarisation using a small, fast model (separate from the 
    working model)
    - Preserving: system prompt, original task instruction, last N turns 
    (default: 6)
    - Replacing middle history with a compressed summary message marked 
    [CONTEXT SUMMARY]
    - Maintaining a separate AGENT_NOTES.md write for any discoveries made 
    before they are compressed away

Context limits are set per model at startup via ollama.show(), not hardcoded.
"""

