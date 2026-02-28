"""
matrixmouse/memory.py

Manages the agent's persistent external memory, which survices context compression. 

Responsibilities:
    - Reading and writing named sections of `AGENT_NOTES.md`
    - Maintaining section index so agents can request only the relevant section
    - Writing exploration results before compression discards them
    - Structured sections: `[file_map]`, `[key_functions]`, `[open_questions]`, 
    `[completed_subtasks]`, `[known_issues]`

Design documents in `docs/design/` are treated as read-only by the implementer agent. Only the designer agent and orchestrator may write or amend design documents.

"""

