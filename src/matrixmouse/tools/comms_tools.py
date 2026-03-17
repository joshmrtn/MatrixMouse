"""
matrixmouse/tools/comms_tools.py

Tools for communicating with a human operator.

Design notes:
    request_clarification always moves the task to BLOCKED_BY_HUMAN.
    This is intentional — an agent confused enough to ask for
    clarification should not continue making assumptions. The task
    is parked so the scheduler can work on other tasks while waiting.

    A grace period (clarification_grace_period_minutes) allows the
    human to respond immediately if they happen to be present. If no
    response arrives within the grace period, the task stays BLOCKED
    and the scheduler moves on. The task resumes when the operator
    provides an answer via the web UI or CLI.

    This mirrors OS I/O-wait scheduling: block the task, not the system.
"""

import logging
import time

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level state — set by configure()
# ---------------------------------------------------------------------------

_config = None


def configure(config) -> None:
    """
    Inject config for comms tools.

    Called by the orchestrator at task start alongside other tool
    configure() calls.

    Args:
        config: MatrixMouseConfig instance. Used for grace period timing.
    """
    global _config
    _config = config


def request_clarification(question: str) -> str:
    """
    Ask the human operator a question and park this task until answered.

    Use this when you genuinely cannot proceed without human input.
    Do not use this speculatively — only ask when stuck.

    The task is immediately moved to BLOCKED_BY_HUMAN so the scheduler
    can work on other tasks while waiting. A grace period allows the
    human to respond immediately if present. If no response arrives
    within the grace period, the scheduler moves on and the task
    resumes when the operator answers via the web UI or CLI.

    The answer will appear as a user message in your conversation
    history when the task resumes.

    Args:
        question (str): The question to ask. Be specific — include
            what you have tried, what is unclear, and what information
            you need to proceed. Vague questions produce vague answers.

    Returns:
        str: Acknowledgement that the question was sent and the task
            is now waiting. If a response arrives within the grace
            period, returns the operator's answer directly.
    """
    from matrixmouse.comms import get_manager
    from matrixmouse.tools import task_tools

    if not question or not question.strip():
        return "ERROR: question cannot be empty."

    queue = task_tools._queue
    active_task_id = task_tools._active_task_id

    if queue is None or active_task_id is None:
        return "ERROR: task_tools not configured. Cannot block task."

    # --- Move task to BLOCKED_BY_HUMAN ---
    try:
        queue.mark_blocked_by_human(
            active_task_id,
            reason=f"Awaiting clarification: {question[:120]}",
        )
    except Exception as e:
        logger.warning(
            "Failed to mark task [%s] blocked: %s", active_task_id, e
        )
        return f"ERROR: Could not block task: {e}"

    logger.info(
        "Task [%s] blocked pending clarification: %s",
        active_task_id, question[:80],
    )

    # --- Notify operator ---
    m = get_manager()
    if m:
        try:
            m.notify(
                f"Agent needs clarification on task [{active_task_id}]:\n"
                f"{question}"
            )
            m.emit("clarification_requested", {
                "task_id":  active_task_id,
                "question": question,
            })
        except Exception as e:
            logger.warning("Failed to send clarification notification: %s", e)

    # --- Grace period: poll for an answer ---
    # TODO: in the multi-threaded model this polling needs to be async or moved to a separate thread
    grace_minutes = (
        getattr(_config, "clarification_grace_period_minutes", 10)
        if _config is not None else 10
    )
    grace_seconds = grace_minutes * 60
    poll_interval = 5  # seconds between checks
    deadline = time.monotonic() + grace_seconds

    logger.info(
        "Waiting up to %.0f minutes for clarification response on task [%s].",
        grace_minutes, active_task_id,
    )

    while time.monotonic() < deadline:
        time.sleep(poll_interval)
        # Check whether the operator has unblocked the task by providing
        # an answer. The answer is injected as a user message in
        # context_messages and the task status is set back to READY
        # by the API when the operator responds.
        task = queue.get(active_task_id)
        if task is None:
            break
        if task.status.value == "ready":
            # Operator responded within grace period — find the answer
            # by looking for the most recent user message added after
            # the clarification request.
            answer = _extract_latest_answer(task.context_messages)
            logger.info(
                "Clarification answered within grace period for task [%s].",
                active_task_id,
            )
            return (
                f"Operator responded: {answer}"
                if answer else
                "Operator unblocked the task. Check your conversation history."
            )

    # Grace period elapsed with no response
    logger.info(
        "Grace period elapsed for task [%s]. "
        "Task remains BLOCKED_BY_HUMAN.",
        active_task_id,
    )
    return (
        f"Your question has been sent to the operator:\n\"{question}\"\n\n"
        f"No response arrived within the {grace_minutes}-minute grace period. "
        f"This task is now BLOCKED_BY_HUMAN. It will resume automatically "
        f"when the operator provides an answer via the web UI or CLI."
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _extract_latest_answer(context_messages: list) -> str | None:
    """
    Extract the most recent user message from context_messages.

    Used to surface the operator's answer after the grace period poll
    detects the task has been unblocked. The answer is injected by the
    API as a user message when the operator responds.

    Args:
        context_messages: The task's full conversation history.

    Returns:
        The content of the most recent user message, or None if not found.
    """
    for msg in reversed(context_messages):
        if isinstance(msg, dict) and msg.get("role") == "user":
            content = msg.get("content", "")
            # Skip the interjection-style prefix we add ourselves
            if not content.startswith("[Human operator note"):
                return content
    return None