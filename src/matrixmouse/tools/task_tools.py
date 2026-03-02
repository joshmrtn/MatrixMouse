"""
matrixmouse/tools/system_tools.py

Tools for agent lifecycle control.

Tools exposed:
    declare_complete — signal that the current task is finished

Do not add file, git, or navigation tools here.
"""

import logging

logger = logging.getLogger(__name__)


def declare_complete(summary: str) -> str:
    """
    Signal that the current task is complete.
    Call this when you have finished all required work for the task.

    Args:
        summary: A brief description of what was accomplished.

    Returns:
        Confirmation string (the loop intercepts this call before
        the return value is used).
    """
    # NOTE: The loop intercepts this tool call by name before dispatching
    # to TOOL_REGISTRY. This function exists so the tool appears in the
    # schema presented to the model. The return value is never used.
    logger.info("declare_complete called: %s", summary)
    return f"Task declared complete: {summary}"
