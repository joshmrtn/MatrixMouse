"""
MatrixMouse - autonomous agent manager.

Modules:
    main: The entry point. Initializes all subsystems at startup.
    init: Handles repo initialization.
    config: Configuration loader. Handles default, global, and local configs.
    orchestrator: Task and phase manager. The outermost control loop.
    loop: The inner loop that drives a single agent role for a single task.
    context: Context management. Keeping message history within safe limits.
    router: Manages model selection by task and role and handles escalation.
    stuck: Monitors agent behavior for escalation signals
    memory: Manages agent's external persistent memory.
    graph: AST project analysis, builds a static call graph of a project.
    comms: Manages channels between the agent and the human operator.
    server: A lightweight FastAPI web app for visibility and control.

Packages:
    tools: Exposes all agent-usable tools for dispatch via a TOOL_REGISTRY
    utils: Internal utilities for the system.
"""
