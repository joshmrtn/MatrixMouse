"""
matrixmouse/router.py

Manages model selection for each agent role and handles cascade escalation.

Responsibilities:
    - Assigning models to roles based on the current phase
    - Maintaining the cascade ladder for coder escalation
    - Escalating to the next model tier when stuck.py signals a stuck state
    - Constructing a clean handoff context when escalating
    - Gradually de-escalating after successful write+test cycles
    - Batching tasks of the same type to amortise model load time

Role-to-model mapping:
    DESIGN, CRITIQUE, REVIEW  → config.planner (general reasoning)
    IMPLEMENT                 → coder cascade (coding-specialised)
    TEST                      → config.coder (coding, no cascade)
    summarization             → config.summarizer (internal, not agent-facing)

Cascade ladder:
    Defined by config.coder_cascade (list, smallest to largest).
    If empty, config.coder is used as a single-tier ladder with no escalation.

Do not add inference logic or tool dispatch here.
"""

import logging
from dataclasses import dataclass, field

from matrixmouse.config import MatrixMouseConfig
from matrixmouse.phases import Phase
from matrixmouse.stuck import StuckDetector

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Handoff context
# ---------------------------------------------------------------------------

@dataclass
class EscalationHandoff:
    """
    Context passed to the larger model when escalating.
    Summarises what the smaller model tried and why it failed,
    so the larger model doesn't repeat the same mistakes.
    """
    from_model: str
    to_model: str
    stuck_summary: dict
    recent_messages: list        # last N messages from the failed run
    original_messages: list      # system prompt + task instruction only


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

class Router:
    """
    Selects the appropriate model for each phase and manages escalation.

    Instantiated once per task in the orchestrator. Maintains escalation
    state across phases so a task that escalates during IMPLEMENT stays
    on the larger model for TEST and REVIEW unless de-escalation is earned.
    """

    # Number of successful write+test cycles before stepping down one tier
    DEESCALATE_AFTER = 2

    def __init__(self, config: MatrixMouseConfig):
        self.config = config
        self._cascade = self._build_cascade()
        self._current_tier = 0
        self._successful_cycles = 0  # counts write+test successes toward de-escalation

        logger.info(
            "Router initialised. Cascade: %s. Planner: %s. Summarizer: %s.",
            self._cascade, config.planner, config.summarizer
        )

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def model_for_phase(self, phase: Phase) -> str:
        """
        Return the model to use for a given phase.

        DESIGN, CRITIQUE, REVIEW use the planner model — these are
        reasoning tasks, not coding tasks.
        IMPLEMENT uses the current cascade tier.
        TEST uses the coder model directly — no cascade needed for
        running and interpreting tests.

        Args:
            phase: The current SDLC phase.

        Returns:
            Model name string suitable for passing to ollama.chat().
        """
        if phase in (Phase.DESIGN, Phase.CRITIQUE, Phase.REVIEW):
            return self.config.planner

        if phase == Phase.IMPLEMENT:
            return self._current_model()

        if phase == Phase.TEST:
            return self.config.coder

        # DONE and unknown phases — fall back to coder
        return self.config.coder

    def escalate(self, detector: StuckDetector) -> tuple[bool, str | None]:
        """
        Attempt to escalate to the next model tier.

        Args:
            detector: The StuckDetector from the failed loop run.
                      Used to build the handoff context and log diagnostics.

        Returns:
            (escalated: bool, new_model: str | None)
            escalated is False if already at the top of the cascade.
        """
        if self._current_tier >= len(self._cascade) - 1:
            logger.warning(
                "Escalation requested but already at top of cascade (%s). "
                "Human intervention required.",
                self._current_model()
            )
            return False, None

        old_model = self._current_model()
        self._current_tier += 1
        new_model = self._current_model()
        self._successful_cycles = 0  # reset de-escalation counter on escalation

        logger.info(
            "Escalating: %s → %s. Stuck reason: %s",
            old_model, new_model, detector.last_reason
        )
        return True, new_model

    def record_success(self) -> None:
        """
        Record a successful write+test cycle. After DEESCALATE_AFTER
        consecutive successes, step down one tier.

        Call this from the orchestrator when a phase completes cleanly
        with passing tests.
        """
        if self._current_tier == 0:
            return  # already at base tier, nothing to de-escalate

        self._successful_cycles += 1
        logger.debug(
            "Successful cycle recorded (%d/%d toward de-escalation).",
            self._successful_cycles, self.DEESCALATE_AFTER
        )

        if self._successful_cycles >= self.DEESCALATE_AFTER:
            old_model = self._current_model()
            self._current_tier = max(0, self._current_tier - 1)
            new_model = self._current_model()
            self._successful_cycles = 0

            logger.info(
                "De-escalating after %d successful cycles: %s → %s.",
                self.DEESCALATE_AFTER, old_model, new_model
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
        receives:
            - The original system prompt and task instruction
            - A summary of what was tried and why it failed
            - The last N messages for immediate context

        This prevents the larger model from inheriting the smaller
        model's confusion while still giving it enough context to continue.

        Args:
            detector:    StuckDetector with diagnostics from the failed run.
            messages:    Full message history from the failed run.
            keep_recent: Number of recent messages to include verbatim.

        Returns:
            Trimmed message list ready to pass to AgentLoop.
        """
        if len(messages) < 2:
            return messages

        system_msg = messages[0]
        instruction_msg = messages[1]
        recent = messages[-keep_recent:] if len(messages) > keep_recent + 2 else messages[2:]

        summary = detector.summary
        handoff_msg = {
            "role": "system",
            "content": (
                "[ESCALATION HANDOFF]\n"
                f"A smaller model ({summary.get('phase', 'unknown')} phase) "
                f"was unable to make progress and has escalated to you.\n\n"
                f"Stuck reason: {summary.get('reason', 'unknown')}\n"
                f"Turns taken: {summary.get('total_calls', 0)}\n"
                f"Consecutive errors: {summary.get('consecutive_errors', 0)}\n"
                f"Turns without a write: {summary.get('turns_without_write', 0)}\n\n"
                "Please review the recent context below and continue the task, "
                "avoiding the same approaches that caused the smaller model to stall.\n"
                "[END HANDOFF]"
            ),
        }

        return [system_msg, instruction_msg, handoff_msg] + list(recent)

    @property
    def current_tier(self) -> int:
        """Current position in the cascade ladder (0 = smallest model)."""
        return self._current_tier

    @property
    def at_ceiling(self) -> bool:
        """True if already at the top of the cascade ladder."""
        return self._current_tier >= len(self._cascade) - 1

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_cascade(self) -> list[str]:
        """
        Build the ordered cascade ladder from config.

        If config.coder_cascade is set, use it directly.
        Otherwise, fall back to a single-tier ladder containing only
        config.coder — escalation is effectively disabled.
        """
        if self.config.coder_cascade:
            cascade = list(self.config.coder_cascade)
            logger.info("Cascade ladder from config: %s", cascade)
            return cascade

        logger.info(
            "No coder_cascade configured. Using single-tier ladder: [%s]. "
            "Set coder_cascade in config.toml to enable escalation.",
            self.config.coder
        )
        return [self.config.coder]

    def _current_model(self) -> str:
        """Return the model at the current cascade tier."""
        return self._cascade[self._current_tier]
