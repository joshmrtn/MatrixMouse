"""
matrixmouse/loop.py

The inner loop that drives a single agent role for a single task. 

Responsibilities:
    - Calling the active model via Ollama
    - Catching malformed tool call parsing errors at the chat_completion 
    level and feeding them back as error messages
    - Executing tool calls and appending results to message history
    - Calling stuck.py after each turn to check for escalation signals
    - Calling context.py before each inference to ensure the context window 
    is within bounds
    - Checking comms.py for pending human interjections at the top of each 
    iteration
    - Terminating on declare_complete or when the orchestrator signals phase 
    transition
"""

