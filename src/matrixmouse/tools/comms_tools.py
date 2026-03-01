"""
matrixmouse/tools/comms_tools.py

Tools for communicating with a human operator.
"""

def request_clarification(question: str, blocking: bool = True) -> str:
    """
    Ask the human operator a question and optionally wait for a reply.
    Use this when you are genuinely stuck and need human input to proceed.
    Set blocking=False if the question is low-priority and you can continue.

    Args:
        question: The question to ask.
        blocking: If True, halt until a reply is received.
    """
    from matrixmouse.comms import get_manager
    m = get_manager()
    if m is None:
        return "ERROR: Comms not configured."
    return m.request_clarification(question, blocking=blocking)
