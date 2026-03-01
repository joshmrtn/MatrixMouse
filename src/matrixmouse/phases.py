"""
matrixmouse/phases.py

SDLC phase definitions shared across orchestrator.py, stuck.py, and loop.py.
Kept in a separate module to avoid circular imports.
"""

from enum import Enum, auto


class Phase(Enum):
    """
    SDLC phases a task moves through in order.
    The orchestrator enforces that no phase is skipped.
    """
    DESIGN      = auto()
    CRITIQUE    = auto()
    IMPLEMENT   = auto()
    TEST        = auto()
    REVIEW      = auto()
    DONE        = auto()


PHASE_SEQUENCE = [
    Phase.DESIGN,
    Phase.CRITIQUE,
    Phase.IMPLEMENT,
    Phase.TEST,
    Phase.REVIEW,
    Phase.DONE,
]


def next_phase(current: Phase):
    """Return the phase that follows current, or None if already DONE."""
    idx = PHASE_SEQUENCE.index(current)
    if idx + 1 < len(PHASE_SEQUENCE):
        return PHASE_SEQUENCE[idx + 1]
    return None
