"""
matrixmouse/stuck.py

Monitors the agent's behaviour within a task and emits escalation signals.

Detects:
    - Repeated identical tool calls within a sliding window (hash-based)
    - Consecutive tool call errors without a successful write
    - Extended read-only stretches late in an implementation phase

Produces a float escalation score (0.0-1.0) internally. The callable
interface returns a bool for loop.py (simple, no refactoring needed).
The score is exposed as a property so router.py can make more informed
escalation decisions when it receives LoopExitReason.ESCALATE.

Does not directly escalate — reports to loop.py which reports to
orchestrator.py which decides action.

TODO: Add periodic self-assessment (ask the model if it's stuck every N turns)
      once the latency cost is acceptable and router.py is implemented.
      Self-assessment adds an inference call per check but gives the richest
      signal, especially for tasks where tool patterns don't reveal confusion.
"""

import hashlib
import logging
from collections import deque
from dataclasses import dataclass, field

from matrixmouse.orchestrator import Phase

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Per-phase escalation thresholds
# ---------------------------------------------------------------------------
# Higher threshold = more tolerance before escalating.
# Exploration phases (DESIGN, CRITIQUE) naturally involve many reads with
# few writes, so we tolerate more before flagging. Implementation phases
# should be producing output, so we escalate sooner.

PHASE_THRESHOLDS: dict[Phase, float] = {
    Phase.DESIGN:     0.85,
    Phase.CRITIQUE:   0.85,
    Phase.IMPLEMENT:  0.65,
    Phase.TEST:       0.70,
    Phase.REVIEW:     0.80,
    Phase.DONE:       1.00,  # never escalate from DONE
}

DEFAULT_THRESHOLD = 0.70

# Tools that count as "productive writes" — reset failure and read-only counters
WRITE_TOOLS = {
    "str_replace",
    "append_to_file",
    "commit_progress",
    "create_task_branch",
    "push_branch",
}


# ---------------------------------------------------------------------------
# StuckDetector
# ---------------------------------------------------------------------------

@dataclass
class StuckDetector:
    """
    Tracks agent tool call behaviour and emits escalation signals.

    Instantiated per AgentLoop run. Pass as the stuck_detector callable
    to AgentLoop — it will be called after each tool dispatch.

    Usage:
        detector = StuckDetector(phase=Phase.IMPLEMENT)
        loop = AgentLoop(..., stuck_detector=detector)

        # After loop exits with ESCALATE:
        print(detector.score)        # float 0.0-1.0
        print(detector.last_reason)  # human-readable explanation
    """

    phase: Phase = Phase.IMPLEMENT
    window_size: int = 6        # sliding window for repeat detection
    repeat_threshold: int = 2   # how many repeats in window triggers signal
    max_errors: int = 3         # consecutive errors before signalling
    max_readonly_turns: int = 8 # read-only turns before signalling (in IMPLEMENT/TEST)

    # Internal state — not constructor arguments
    _recent_calls: deque = field(default_factory=lambda: deque(maxlen=6), init=False)
    _consecutive_errors: int = field(default=0, init=False)
    _turns_without_write: int = field(default=0, init=False)
    _total_calls: int = field(default=0, init=False)
    _score: float = field(default=0.0, init=False)
    _last_reason: str = field(default="", init=False)

    def __post_init__(self) -> None:
        # Keep window_size and deque maxlen in sync
        self._recent_calls = deque(maxlen=self.window_size)

    # ------------------------------------------------------------------
    # Callable interface — used by loop.py
    # ------------------------------------------------------------------

    def __call__(
        self,
        tool_name: str,
        arguments: dict,
        had_error: bool,
    ) -> bool:
        """
        Record a tool call and return True if the agent should escalate.

        Args:
            tool_name:  Name of the tool that was called.
            arguments:  Arguments passed to the tool.
            had_error:  True if the tool returned an error result.

        Returns:
            True if the escalation score exceeds the phase threshold.
        """
        self._total_calls += 1
        self._record_call(tool_name, arguments, had_error)
        self._score = self._compute_score(tool_name)

        threshold = PHASE_THRESHOLDS.get(self.phase, DEFAULT_THRESHOLD)
        should_escalate = self._score >= threshold

        if should_escalate:
            logger.warning(
                "StuckDetector escalating. Score: %.2f (threshold %.2f). "
                "Reason: %s. Phase: %s. Total calls: %d.",
                self._score, threshold, self._last_reason,
                self.phase.name, self._total_calls,
            )

        return should_escalate

    # ------------------------------------------------------------------
    # Properties for router.py to query after escalation
    # ------------------------------------------------------------------

    @property
    def score(self) -> float:
        """Current escalation score, 0.0 (fine) to 1.0 (definitely stuck)."""
        return self._score

    @property
    def last_reason(self) -> str:
        """Human-readable explanation of the highest-scoring signal."""
        return self._last_reason

    @property
    def summary(self) -> dict:
        """
        Full diagnostic summary for the orchestrator/router to log or act on.
        """
        return {
            "score": self._score,
            "reason": self._last_reason,
            "phase": self.phase.name,
            "total_calls": self._total_calls,
            "consecutive_errors": self._consecutive_errors,
            "turns_without_write": self._turns_without_write,
        }

    # ------------------------------------------------------------------
    # Internal signal computation
    # ------------------------------------------------------------------

    def _record_call(
        self,
        tool_name: str,
        arguments: dict,
        had_error: bool,
    ) -> None:
        """Update internal counters based on the latest tool call."""
        # Hash the call signature for repeat detection
        sig = _call_signature(tool_name, arguments)
        self._recent_calls.append(sig)

        # Update error counter
        if had_error:
            self._consecutive_errors += 1
        else:
            self._consecutive_errors = 0

        # Update write counter — reset on any productive write
        if tool_name in WRITE_TOOLS and not had_error:
            self._turns_without_write = 0
        else:
            self._turns_without_write += 1

    def _compute_score(self, tool_name: str) -> float:
        """
        Compute the current escalation score from all active signals.
        Returns the maximum signal strength rather than averaging, so a
        single strong signal is enough to escalate regardless of others.
        """
        signals: list[tuple[float, str]] = []

        # Signal 1: repeated identical tool calls
        repeat_score, repeat_reason = self._score_repeats()
        signals.append((repeat_score, repeat_reason))

        # Signal 2: consecutive errors
        error_score, error_reason = self._score_errors()
        signals.append((error_score, error_reason))

        # Signal 3: extended read-only stretch (only meaningful in
        # phases where the agent should be producing output)
        if self.phase in (Phase.IMPLEMENT, Phase.TEST):
            readonly_score, readonly_reason = self._score_readonly()
            signals.append((readonly_score, readonly_reason))

        # Take the strongest signal
        best_score, best_reason = max(signals, key=lambda x: x[0])
        self._last_reason = best_reason

        logger.debug(
            "StuckDetector scores — repeat: %.2f, errors: %.2f%s",
            signals[0][0], signals[1][0],
            f", readonly: {signals[2][0]:.2f}" if len(signals) > 2 else "",
        )

        return best_score

    def _score_repeats(self) -> tuple[float, str]:
        """Score based on how many recent calls are identical."""
        if len(self._recent_calls) < 2:
            return 0.0, ""

        # Count the most frequent call in the window
        counts: dict[str, int] = {}
        for sig in self._recent_calls:
            counts[sig] = counts.get(sig, 0) + 1

        max_repeats = max(counts.values())
        if max_repeats < self.repeat_threshold:
            return 0.0, ""

        # Scale: repeat_threshold repeats = 0.6, window fully saturated = 1.0
        score = min(
            0.6 + 0.4 * (max_repeats - self.repeat_threshold) /
            max(1, self.window_size - self.repeat_threshold),
            1.0
        )
        reason = (
            f"Same tool call repeated {max_repeats} times "
            f"in last {len(self._recent_calls)} turns."
        )
        return score, reason

    def _score_errors(self) -> tuple[float, str]:
        """Score based on consecutive tool call errors."""
        if self._consecutive_errors < 2:
            return 0.0, ""

        # Scale: 2 errors = 0.5, max_errors = 0.9, beyond = 1.0
        score = min(
            0.5 + 0.4 * (self._consecutive_errors - 2) /
            max(1, self.max_errors - 2),
            1.0
        )
        reason = f"{self._consecutive_errors} consecutive tool errors without a successful write."
        return score, reason

    def _score_readonly(self) -> tuple[float, str]:
        """Score based on how long the agent has gone without writing anything."""
        if self._turns_without_write < self.max_readonly_turns // 2:
            return 0.0, ""

        # Scale: half of max = 0.4, at max = 0.8, beyond = 1.0
        score = min(
            0.4 + 0.6 * (self._turns_without_write - self.max_readonly_turns // 2) /
            max(1, self.max_readonly_turns // 2),
            1.0
        )
        reason = (
            f"{self._turns_without_write} turns without a write "
            f"during {self.phase.name} phase."
        )
        return score, reason


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _call_signature(tool_name: str, arguments: dict) -> str:
    """
    Produce a stable hash string for a tool call.
    Used to detect repeated identical calls in the sliding window.
    """
    content = f"{tool_name}:{sorted(arguments.items())}"
    return hashlib.md5(content.encode()).hexdigest()
