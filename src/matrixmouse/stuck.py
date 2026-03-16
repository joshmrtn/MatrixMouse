"""
matrixmouse/stuck.py

Monitors the agent's behaviour within a task and emits escalation signals.

Detects:
    - Repeated identical tool calls within a sliding window (hash-based)
    - Consecutive tool call errors without a successful write
    - Extended read-only stretches for roles that should be producing output

Produces a float escalation score (0.0-1.0) internally. The callable
interface returns a bool for loop.py (simple, no refactoring needed).
The score is exposed as a property so router.py can make more informed
escalation decisions when it receives LoopExitReason.ESCALATE.

Does not directly escalate — reports to loop.py which reports to
orchestrator.py which decides action.

Escalation only applies to the Coder role (cascade escalation). For
Manager and Critic, the turn limit mechanism handles stuck detection.
For Writer, escalation is not currently supported — Writers use the same
turn limit path as Manager and Critic.

TODO: Add periodic self-assessment (ask the model if it's stuck every N turns)
      once the latency cost is acceptable.
      Self-assessment adds an inference call per check but gives the richest
      signal, especially for tasks where tool patterns don't reveal confusion.
"""

import hashlib
import logging
from collections import deque
from dataclasses import dataclass, field

from matrixmouse.task import AgentRole

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Per-role escalation thresholds
# ---------------------------------------------------------------------------
# Higher threshold = more tolerance before escalating.
#
# Manager and Critic: set to 1.0 (never escalate via stuck detector —
# they use the turn limit path instead). This ensures stuck detection
# does not interfere with their fixed-model operation.
#
# Writer: set to 1.0 — Writers produce prose, which naturally involves
# many reads. The read-only signal would produce false positives.
#
# Coder: lower threshold — should be producing writes. Escalates through
# the coder cascade when stuck.

ROLE_THRESHOLDS: dict[AgentRole, float] = {
    AgentRole.MANAGER: 1.00,  # never escalate — use turn limit path
    AgentRole.CODER:   0.65,
    AgentRole.WRITER:  1.00,  # never escalate — use turn limit path
    AgentRole.CRITIC:  1.00,  # never escalate — use turn limit path
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

    Escalation via this detector is only meaningful for the Coder role,
    which has a cascade of larger models to escalate through. All other
    roles have their thresholds set to 1.0 and will never trigger
    escalation here — they use the turn limit path instead.

    Usage:
        detector = StuckDetector(role=AgentRole.CODER)
        loop = AgentLoop(..., stuck_detector=detector)

        # After loop exits with ESCALATE:
        print(detector.score)        # float 0.0-1.0
        print(detector.last_reason)  # human-readable explanation
    """

    role: AgentRole = AgentRole.CODER
    window_size: int = 6        # sliding window for repeat detection
    repeat_threshold: int = 2   # how many repeats in window triggers signal
    max_errors: int = 3         # consecutive errors before signalling
    max_readonly_turns: int = 8 # read-only turns before signalling (Coder only)

    # Internal state — not constructor arguments
    _recent_calls: deque = field(
        default_factory=lambda: deque(maxlen=6), init=False
    )
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
            True if the escalation score exceeds the role threshold.
        """
        self._total_calls += 1
        self._record_call(tool_name, arguments, had_error)
        self._score = self._compute_score()

        threshold = ROLE_THRESHOLDS.get(self.role, DEFAULT_THRESHOLD)
        should_escalate = self._score >= threshold

        if should_escalate:
            logger.warning(
                "StuckDetector escalating. Score: %.2f (threshold %.2f). "
                "Reason: %s. Role: %s. Total calls: %d.",
                self._score, threshold, self._last_reason,
                self.role.value, self._total_calls,
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
            "score":               self._score,
            "reason":              self._last_reason,
            "role":                self.role.value,
            "total_calls":         self._total_calls,
            "consecutive_errors":  self._consecutive_errors,
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
        sig = _call_signature(tool_name, arguments)
        self._recent_calls.append(sig)

        if had_error:
            self._consecutive_errors += 1
        else:
            self._consecutive_errors = 0

        if tool_name in WRITE_TOOLS and not had_error:
            self._turns_without_write = 0
        else:
            self._turns_without_write += 1

    def _compute_score(self) -> float:
        """
        Compute the current escalation score from all active signals.

        Returns the maximum signal strength rather than averaging, so a
        single strong signal is enough to escalate regardless of others.
        The read-only signal is only evaluated for the Coder role — other
        roles naturally spend many turns reading without writing.
        """
        signals: list[tuple[float, str]] = []

        # Signal 1: repeated identical tool calls
        signals.append(self._score_repeats())

        # Signal 2: consecutive errors
        signals.append(self._score_errors())

        # Signal 3: extended read-only stretch — Coder only
        if self.role == AgentRole.CODER:
            signals.append(self._score_readonly())

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

        counts: dict[str, int] = {}
        for sig in self._recent_calls:
            counts[sig] = counts.get(sig, 0) + 1

        max_repeats = max(counts.values())
        if max_repeats < self.repeat_threshold:
            return 0.0, ""

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

        score = min(
            0.5 + 0.4 * (self._consecutive_errors - 2) /
            max(1, self.max_errors - 2),
            1.0
        )
        reason = (
            f"{self._consecutive_errors} consecutive tool errors "
            f"without a successful write."
        )
        return score, reason

    def _score_readonly(self) -> tuple[float, str]:
        """
        Score based on how long the Coder has gone without writing anything.

        Only called for CODER role — other roles read extensively by design.
        """
        if self._turns_without_write < self.max_readonly_turns // 2:
            return 0.0, ""

        score = min(
            0.4 + 0.6 * (
                self._turns_without_write - self.max_readonly_turns // 2
            ) / max(1, self.max_readonly_turns // 2),
            1.0
        )
        reason = (
            f"{self._turns_without_write} turns without a write "
            f"(Coder role — expected to be producing output)."
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