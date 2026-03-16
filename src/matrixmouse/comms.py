"""
matrixmouse/comms.py

Manages all channels between the agent and the human operator.

Responsibilities:
    - Interjection queue: thread-safe queue of pending human messages.
      The loop polls this at each iteration boundary and injects any
      pending messages before the next inference call.
    - Notification dispatch: sends push notifications via ntfy when the
      agent is blocked or requires human input.
    - Status broadcast: pushes structured events to registered listeners
      (websocket clients via server.py) so the web UI stays current.
    - Clarification requests: blocking and non-blocking human input.
      Blocking halts the loop until a response arrives.

The interjection queue is the single source of truth for human → agent
messages. server.py writes to it via put_interjection(); loop.py reads
from it via get_interjection().

Do not add inference logic or tool dispatch here.
"""

import logging
import queue
import threading
import time
import os
from dataclasses import dataclass, field
from typing import Callable

import requests

from matrixmouse.config import MatrixMouseConfig

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Event types — structured data pushed to server.py listeners
# ---------------------------------------------------------------------------

@dataclass
class AgentEvent:
    """
    A structured event broadcast to connected web UI clients.
    server.py serialises these to JSON and sends over websocket.
    """
    event_type: str          # "tool_call" | "tool_result" | "content" | 
                             # "escalation" | "blocked" | "complete" | "error"
    data: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# CommsManager
# ---------------------------------------------------------------------------

class CommsManager:
    """
    Central communications hub for the MatrixMouse session.

    Instantiated once in the orchestrator and shared across all loops.
    Thread-safe — the interjection queue can be written from the web
    server thread and read from the agent loop thread safely.
    """

    def __init__(self, config: MatrixMouseConfig):
        self.config = config

        # Thread-safe queue for human → agent messages
        self._interjection_queue: queue.Queue[str] = queue.Queue()

        # Registered event listeners (server.py registers here)
        self._listeners: list[Callable[[AgentEvent], None]] = []

        # Track current status for the web UI
        self._status: dict = {
            "task": None,
            "role": None,
            "model": None,
            "turns": 0,
            "blocked": False,
        }

        logger.info("CommsManager initialised.")

    # ------------------------------------------------------------------
    # Interjection queue — human → agent
    # ------------------------------------------------------------------


    def put_interjection(self, message: str, repo: str | None = None) -> None:
        """
        Add a human message to the interjection queue.
        Called by server.py when a POST /interject request arrives,
        or directly by the CLI cmd_interject command.

        Args:
            message: The human's message to inject into the agent loop.
            repo:    Optional repo scope. If set, the loop should only
                     inject this message when working on that repo.
                     None means workspace-wide (inject regardless of repo).
        """
        item = {"message": message.strip(), "repo": repo}
        self._interjection_queue.put(item)
        scope = f"repo='{repo}'" if repo else "workspace-wide"
        logger.info("Interjection queued (%s): %s", scope, message[:80])



    def get_interjection(self, current_repo: str | None = None) -> str | None:
        """
        Return the next pending interjection message, or None if empty.
        Non-blocking — never waits.

        Repo-scoped interjections are only returned when current_repo
        matches. Workspace-wide interjections (repo=None) are always
        returned regardless of current_repo.

        Args:
            current_repo: The repo subdirectory name currently being
                          worked on. Pass None if not in a repo context.

        Returns:
            Message string if one is pending and in-scope, None otherwise.
        """
        try:
            item = self._interjection_queue.get_nowait()
        except queue.Empty:
            return None

        item_repo = item.get("repo")

        # Workspace-wide interjection — always deliver
        if item_repo is None:
            return item["message"]

        # Repo-scoped — only deliver if it matches current context
        if item_repo == current_repo:
            return item["message"]

        # Out of scope — put it back and return None
        # put() goes to the back of the queue, which is acceptable since
        # repo-scoped interjections are rare and order within repo is
        # preserved across cycles.
        self._interjection_queue.put(item)
        return None


    # ------------------------------------------------------------------
    # Notifications — agent → human (push)
    # ------------------------------------------------------------------

    def notify(self, title: str, message: str, priority: str = "default") -> None:
        """
        Send a push notification to the operator via ntfy.

        Silently skips if ntfy is not configured (ntfy_url not set).
        Never raises — a failed notification must not crash the agent.

        Args:
            title:    Notification title shown on the device.
            message:  Notification body.
            priority: ntfy priority: "min" | "low" | "default" | "high" | "urgent"
        """
        url = getattr(self.config, "ntfy_url", None)
        topic = getattr(self.config, "ntfy_topic", "matrixmouse")
        web_ui = getattr(self.config, "web_ui_url", "")
        username = os.environ.get("NTFY_USERNAME", "")
        password = os.environ.get("NTFY_PASSWORD", "")

        if not url:
            logger.debug("ntfy not configured. Skipping notification: %s", title)
            return

        endpoint = f"{url.rstrip('/')}/{topic}"

        # Append web UI link to message body if configured
        if web_ui:
            message = f"{message}\n\n{web_ui.rstrip('/')}"

        headers = {
                "Title": title,
                "Priority": priority,
                "Tags": "robot",
                }
        if web_ui:
            headers["Actions"] = f"view, Open Web UI, {web_ui.rstrip('/')}"

        auth = (username, password) if username else None

        try:
            response = requests.post(
                endpoint,
                data=message.encode("utf-8"),
                headers=headers,
                auth=auth,
                timeout=5,
            )
            if response.status_code == 200:
                logger.info("Notification sent: %s", title)
            else:
                logger.warning(
                    "ntfy returned %d for notification '%s'.",
                    response.status_code, title
                )
        except requests.exceptions.ConnectionError:
            logger.warning("Could not reach ntfy at %s. Is it running?", endpoint)
        except Exception as e:
            logger.warning("Notification failed: %s", e)

    def notify_blocked(self, message: str) -> None:
        """
        Convenience wrapper for blocked-task notifications.

        Args:
            message: Human-readable description of the block, including
                    task ID and reason.
        """
        self.notify(
            title="MatrixMouse needs attention",
            message=message,
            priority="high",
        )

    # ------------------------------------------------------------------
    # Status broadcast — agent → web UI
    # ------------------------------------------------------------------

    def register_listener(self, callback: Callable[[AgentEvent], None]) -> None:
        """
        Register a callback to receive agent events.
        server.py calls this to hook its websocket broadcast into comms.

        Args:
            callback: Called with each AgentEvent as it is emitted.
        """
        self._listeners.append(callback)
        logger.debug("Event listener registered. Total: %d", len(self._listeners))

    def emit(self, event_type: str, data: dict | None = None) -> None:
        """
        Broadcast a structured event to all registered listeners.
        Called throughout the agent loop to keep the web UI current.

        Args:
            event_type: Type string identifying the event.
            data:       Event payload. Must be JSON-serialisable.
        """
        event = AgentEvent(event_type=event_type, data=data or {})
        for listener in self._listeners:
            try:
                listener(event)
            except Exception as e:
                logger.warning("Event listener raised: %s", e)

    def update_status(
        self,
        task: str | None = None,
        role: str | None = None,
        model: str | None = None,
        turns: int | None = None,
        blocked: bool | None = None,
    ) -> None:
        """
        Update the current status and broadcast a status_update event.
        Called by the orchestrator at task transitions and by the loop
        each turn.

        Args:
            task:    Current task ID.
            role:    Current agent role name.
            model:   Active model name.
            turns:   Turn count for the current task.
            blocked: Whether the agent is currently blocked.
        """
        if task is not None:
            self._status["task"] = task
        if role is not None:
            self._status["role"] = role
        if model is not None:
            self._status["model"] = model
        if turns is not None:
            self._status["turns"] = turns
        if blocked is not None:
            self._status["blocked"] = blocked

        self.emit("status_update", dict(self._status))

    @property
    def status(self) -> dict:
        """Current agent status snapshot."""
        return dict(self._status)


    def set_pending_question(self, question: str | None) -> None:
        """
        Record the current pending clarification question so the CLI
        and web UI can display it to the operator.

        Args:
            question: The question text, or None to clear.
        """
        self._status["pending_question"] = question

    def get_pending_question(self) -> str | None:
        """Return the current pending clarification question, or None."""
        return self._status.get("pending_question")



# ---------------------------------------------------------------------------
# Module-level singleton — configured at startup
# ---------------------------------------------------------------------------

_manager: CommsManager | None = None


def configure(config: MatrixMouseConfig) -> None:
    """
    Initialise the module-level CommsManager.
    Call once at startup in cmd_run.

    Args:
        config: Active MatrixMouseConfig.
    """
    global _manager
    _manager = CommsManager(config)
    logger.info("Comms manager configured.")


def get_manager() -> CommsManager | None:
    """
    Return the active CommsManager, or None if not configured.
    Used by server.py and tool wrappers to access the shared instance.
    """
    if _manager is None:
        logger.error(
            "Comms not configured. Call comms.configure(config) at startup."
        )
    return _manager


# ---------------------------------------------------------------------------
# Callable for AgentLoop — polls the interjection queue
# ---------------------------------------------------------------------------


def poll_interjection(current_repo: str | None = None) -> str | None:
    """
    Poll the interjection queue for pending human messages.
    Passed to AgentLoop as the comms callable.

    Args:
        current_repo: The repo currently being worked on, for scope filtering.

    Returns:
        Pending message string, or None if queue is empty or no in-scope message.
    """
    if _manager is None:
        return None
    return _manager.get_interjection(current_repo=current_repo)

