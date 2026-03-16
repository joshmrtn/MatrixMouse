"""
matrixmouse/router.py

Manages model selection for each agent role and handles cascade escalation.

Responsibilities:
    - Assigning models to roles based on config
    - Maintaining the cascade ladder for Coder escalation
    - Escalating to the next model tier when stuck.py signals a stuck state
    - Constructing a clean handoff context when escalating
    - Gradually de-escalating after successful cycles
    - Providing the role-filtered tool list for each agent

Role-to-model mapping:
    MANAGER  → config.planner_model  (largest, most capable)
    CODER    → config.coder_cascade  (escalating ladder)
    WRITER   → config.writer_model   (defaults to coder_model)
    CRITIC   → config.planner_model  (same as Manager — strong reasoning)
    internal summarization → config.summarizer_model (not agent-facing)

Cascade ladder:
    Defined by config.coder_cascade (list, smallest to largest).
    Applies to CODER role only. All other roles use a fixed model
    with no escalation — if Manager or Critic is stuck, the task
    escalates to BLOCKED_BY_HUMAN rather than a larger model.

Do not add inference logic or tool dispatch here.
"""

import logging
from dataclasses import dataclass

from matrixmouse.config import MatrixMouseConfig
from matrixmouse.stuck import StuckDetector
from matrixmouse.task import AgentRole

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Handoff context
# ---------------------------------------------------------------------------

@dataclass
class EscalationHandoff:
    """
    Context passed to the larger model when escalating within the cascade.

    Summarises what the smaller model tried and why it failed so the
    larger model does not repeat the same mistakes.
    """
    from_model: str
    to_model: str
    stuck_summary: dict
    recent_messages: list       # last N messages from the failed run
    original_messages: list     # system prompt + task instruction only


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

class Router:
    """
    Selects the appropriate model for each agent role and manages escalation.

    Instantiated once by the orchestrator. Maintains cascade state across
    the lifetime of a task so escalation persists across time slice
    boundaries — a task that escalated to a larger model stays on that
    model when it resumes after a context switch.

    Escalation applies to CODER only. Manager and Critic use fixed models;
    if they cannot complete their work within the turn limit the task moves
    to BLOCKED_BY_HUMAN.
    """

    # Number of successful Coder cycles before stepping down one cascade tier
    DEESCALATE_AFTER = 2

    def __init__(self, config: MatrixMouseConfig):
        self.config = config
        self._cascade = self._build_cascade()
        self._current_tier = 0
        self._successful_cycles = 0

        logger.info(
            "Router initialised. Cascade: %s. Planner: %s. "
            "Writer: %s. Summarizer: %s.",
            self._cascade,
            config.planner_model,
            getattr(config, "writer_model", config.coder_model),
            config.summarizer_model,
        )

    # -----------------------------------------------------------------------
    # Model selection
    # -----------------------------------------------------------------------

    def model_for_role(self, role: AgentRole) -> str:
        """
        Return the model to use for a given agent role.

        MANAGER and CRITIC use planner_model — both require strong
        reasoning and benefit from the largest configured model.
        CODER uses the current cascade tier.
        WRITER uses writer_model, defaulting to coder_model if not
        separately configured.

        Args:
            role: The AgentRole of the running agent.

        Returns:
            str: Model name string for passing to the inference backend.
        """
        if role in (AgentRole.MANAGER, AgentRole.CRITIC):
            return self.config.planner_model

        if role == AgentRole.CODER:
            return self._current_model()

        if role == AgentRole.WRITER:
            return getattr(
                self.config, "writer_model", self.config.coder_model
            )

        # Unknown role — fall back to coder_model and log a warning
        logger.warning(
            "model_for_role called with unknown role %r — "
            "falling back to coder_model.",
            role,
        )
        return self.config.coder_model

    def stream_for_role(self, role: AgentRole) -> bool:
        """
        Return whether to stream model output for a given role.

        Streaming is configured per role in config. Defaults to True
        for all roles — disable per-role if a model misbehaves with
        streaming enabled.

        Args:
            role: The AgentRole of the running agent.

        Returns:
            bool: True if streaming should be enabled.
        """
        if role in (AgentRole.MANAGER, AgentRole.CRITIC):
            return getattr(self.config, "planner_stream", True)

        if role == AgentRole.CODER:
            return getattr(self.config, "coder_stream", True)

        if role == AgentRole.WRITER:
            return getattr(
                self.config, "writer_stream",
                getattr(self.config, "coder_stream", True),
            )

        return True

    def think_for_role(self, role: AgentRole) -> bool:
        """
        Return whether to enable extended thinking for a given role.

        Thinking is disabled by default — it consumes significant context
        budget and is only worthwhile for complex reasoning tasks where
        the model supports it.

        Args:
            role: The AgentRole of the running agent.

        Returns:
            bool: True if extended thinking should be enabled.
        """
        if role in (AgentRole.MANAGER, AgentRole.CRITIC):
            return getattr(self.config, "planner_think", False)

        if role == AgentRole.CODER:
            return getattr(self.config, "coder_think", False)

        if role == AgentRole.WRITER:
            return getattr(
                self.config, "writer_think",
                getattr(self.config, "coder_think", False),
            )

        return False

    # -----------------------------------------------------------------------
    # Cascade escalation (Coder only)
    # -----------------------------------------------------------------------

    def escalate(self, detector: StuckDetector) -> tuple[bool, str | None]:
        """
        Attempt to escalate the Coder to the next cascade tier.

        Only applies to the Coder role. Manager and Critic do not
        escalate — they move to BLOCKED_BY_HUMAN at their turn limit.

        Args:
            detector: StuckDetector from the failed loop run. Used to
                log diagnostics and build handoff context.

        Returns:
            tuple: (escalated: bool, new_model: str | None)
                escalated is False if already at the top of the cascade.
        """
        if self._current_tier >= len(self._cascade) - 1:
            logger.warning(
                "Escalation requested but already at top of cascade (%s). "
                "Human intervention required.",
                self._current_model(),
            )
            return False, None

        old_model = self._current_model()
        self._current_tier += 1
        new_model = self._current_model()
        self._successful_cycles = 0

        logger.info(
            "Escalating Coder: %s → %s. Stuck reason: %s",
            old_model, new_model, detector.last_reason,
        )
        return True, new_model

    def record_success(self) -> None:
        """
        Record a successful Coder cycle toward de-escalation.

        After DEESCALATE_AFTER consecutive successes, step down one
        cascade tier. Call this from the orchestrator when a Coder task
        completes cleanly.
        """
        if self._current_tier == 0:
            return

        self._successful_cycles += 1
        logger.debug(
            "Successful Coder cycle recorded (%d/%d toward de-escalation).",
            self._successful_cycles, self.DEESCALATE_AFTER,
        )

        if self._successful_cycles >= self.DEESCALATE_AFTER:
            old_model = self._current_model()
            self._current_tier = max(0, self._current_tier - 1)
            new_model = self._current_model()
            self._successful_cycles = 0
            logger.info(
                "De-escalating Coder after %d successful cycles: %s → %s.",
                self.DEESCALATE_AFTER, old_model, new_model,
            )

    def build_handoff(
        self,
        detector: StuckDetector,
        messages: list,
        keep_recent: int = 6,
    ) -> list:
        """
        Build a clean starting message history for the escalated model.

        Rather than passing the full confused history, the larger model
        receives the original system prompt, task instruction, a handoff
        summary describing what failed, and the last N messages for
        immediate context. This prevents the larger model from inheriting
        the smaller model's confusion while still giving it enough context
        to continue.

        Args:
            detector:    StuckDetector with diagnostics from the failed run.
            messages:    Full message history from the failed run.
            keep_recent: Number of recent messages to include verbatim.

        Returns:
            list: Trimmed message list ready to pass to AgentLoop.
        """
        if len(messages) < 2:
            return messages

        system_msg     = messages[0]
        instruction_msg = messages[1]
        recent = (
            messages[-keep_recent:]
            if len(messages) > keep_recent + 2
            else messages[2:]
        )

        summary = detector.summary
        handoff_msg = {
            "role": "system",
            "content": (
                "[ESCALATION HANDOFF]\n"
                f"A smaller model was unable to make progress and has "
                f"escalated to you.\n\n"
                f"Stuck reason: {summary.get('reason', 'unknown')}\n"
                f"Turns taken: {summary.get('total_calls', 0)}\n"
                f"Consecutive errors: {summary.get('consecutive_errors', 0)}\n"
                f"Turns without a write: "
                f"{summary.get('turns_without_write', 0)}\n\n"
                "Please review the recent context below and continue the "
                "task, avoiding the same approaches that caused the smaller "
                "model to stall.\n"
                "[END HANDOFF]"
            ),
        }

        return [system_msg, instruction_msg, handoff_msg] + list(recent)

    @property
    def current_tier(self) -> int:
        """Current position in the Coder cascade (0 = smallest model)."""
        return self._current_tier

    @property
    def at_ceiling(self) -> bool:
        """True if the Coder is already at the top of the cascade."""
        return self._current_tier >= len(self._cascade) - 1

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    def _build_cascade(self) -> list[str]:
        """
        Build the ordered Coder cascade ladder from config.

        If config.coder_cascade is set, use it directly. Otherwise fall
        back to a single-tier ladder containing only config.coder_model —
        escalation is effectively disabled.
        """
        if self.config.coder_cascade:
            cascade = list(self.config.coder_cascade)
            logger.info("Coder cascade ladder: %s", cascade)
            return cascade

        logger.info(
            "No coder_cascade configured. Single-tier Coder ladder: [%s]. "
            "Set coder_cascade in config.toml to enable escalation.",
            self.config.coder_model,
        )
        return [self.config.coder_model]

    def _current_model(self) -> str:
        """Return the Coder model at the current cascade tier."""
        return self._cascade[self._current_tier]