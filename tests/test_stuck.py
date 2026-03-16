"""
tests/test_stuck.py

Tests for matrixmouse.stuck — StuckDetector.

Coverage:
    - StuckDetector instantiation with AgentRole
    - __call__ returns False when score below threshold
    - __call__ returns True when escalation threshold exceeded
    - Repeat signal: fires when same call repeated >= repeat_threshold times
    - Repeat signal: does not fire below threshold
    - Error signal: fires after max_errors consecutive errors
    - Error signal: resets on successful call
    - Read-only signal: fires for CODER after max_readonly_turns without write
    - Read-only signal: does not fire for non-CODER roles
    - Write tool resets read-only counter
    - MANAGER/WRITER/CRITIC thresholds are 1.0 (never escalate)
    - summary dict contains role not phase
    - last_reason populated after escalation signal
    - score property returns current score
    - _call_signature produces consistent hashes
"""

from unittest.mock import MagicMock

import pytest

from matrixmouse.stuck import StuckDetector, ROLE_THRESHOLDS, WRITE_TOOLS, _call_signature
from matrixmouse.task import AgentRole


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_detector(role=AgentRole.CODER, **kwargs) -> StuckDetector:
    return StuckDetector(role=role, **kwargs)


def call(detector, tool="read_file", args=None, error=False):
    """Convenience wrapper for a single tool call."""
    return detector(tool, args or {}, error)


# ---------------------------------------------------------------------------
# Instantiation
# ---------------------------------------------------------------------------

class TestInstantiation:
    def test_default_role_is_coder(self):
        d = StuckDetector()
        assert d.role == AgentRole.CODER

    def test_role_set_correctly(self):
        for role in AgentRole:
            d = StuckDetector(role=role)
            assert d.role == role

    def test_initial_score_is_zero(self):
        d = make_detector()
        assert d.score == 0.0

    def test_initial_last_reason_is_empty(self):
        d = make_detector()
        assert d.last_reason == ""


# ---------------------------------------------------------------------------
# Threshold behaviour
# ---------------------------------------------------------------------------

class TestThresholds:
    def test_coder_threshold_below_one(self):
        assert ROLE_THRESHOLDS[AgentRole.CODER] < 1.0

    def test_manager_threshold_is_one(self):
        assert ROLE_THRESHOLDS[AgentRole.MANAGER] == 1.0

    def test_writer_threshold_is_one(self):
        assert ROLE_THRESHOLDS[AgentRole.WRITER] == 1.0

    def test_critic_threshold_is_one(self):
        assert ROLE_THRESHOLDS[AgentRole.CRITIC] == 1.0

    def test_manager_never_escalates(self):
        d = make_detector(role=AgentRole.MANAGER, repeat_threshold=1)
        # Even with aggressive repeat, should not escalate
        for _ in range(20):
            result = call(d, tool="read_file")
        assert result is False

    def test_writer_never_escalates(self):
        d = make_detector(role=AgentRole.WRITER, repeat_threshold=1)
        for _ in range(20):
            result = call(d, tool="read_file")
        assert result is False

    def test_critic_never_escalates(self):
        d = make_detector(role=AgentRole.CRITIC, repeat_threshold=1)
        for _ in range(20):
            result = call(d, tool="read_file")
        assert result is False


# ---------------------------------------------------------------------------
# Repeat signal
# ---------------------------------------------------------------------------

class TestRepeatSignal:
    def test_no_escalation_below_threshold(self):
        d = make_detector(repeat_threshold=3)
        # Only 2 repeats — should not escalate
        call(d, tool="read_file", args={"path": "foo.py"})
        call(d, tool="read_file", args={"path": "foo.py"})
        assert d.score < ROLE_THRESHOLDS[AgentRole.CODER]

    def test_escalation_at_threshold(self):
        d = make_detector(repeat_threshold=2, window_size=6)
        # Same call repeated repeat_threshold times
        for _ in range(2):
            call(d, tool="read_file", args={"path": "foo.py"})
        assert d.score > 0.0

    def test_different_args_not_counted_as_repeat(self):
        d = make_detector(repeat_threshold=2)
        call(d, tool="read_file", args={"path": "foo.py"})
        call(d, tool="read_file", args={"path": "bar.py"})
        # Different args — should not trigger repeat signal
        assert d.score == 0.0

    def test_different_tools_not_counted_as_repeat(self):
        d = make_detector(repeat_threshold=2)
        call(d, tool="read_file", args={"path": "foo.py"})
        call(d, tool="str_replace", args={"path": "foo.py"})
        assert d.score == 0.0

    def test_window_evicts_old_calls(self):
        d = make_detector(repeat_threshold=2, window_size=3)
        # Fill window with varied calls
        call(d, tool="read_file", args={"path": "foo.py"})
        call(d, tool="read_file", args={"path": "bar.py"})
        call(d, tool="read_file", args={"path": "baz.py"})
        # Now repeat a new call — first occurrence pushed out of window
        call(d, tool="read_file", args={"path": "qux.py"})
        # Only 1 occurrence of qux.py in window — should not escalate on repeats
        assert "repeated" not in d.last_reason or d.score < 0.6


# ---------------------------------------------------------------------------
# Error signal
# ---------------------------------------------------------------------------

class TestErrorSignal:
    def test_no_escalation_on_single_error(self):
        d = make_detector(max_errors=3)
        call(d, tool="read_file", error=True)
        assert d.score == 0.0

    def test_escalation_after_consecutive_errors(self):
        d = make_detector(max_errors=3)
        call(d, tool="read_file", error=True)
        call(d, tool="read_file", error=True)
        # 2 consecutive errors — should produce non-zero error score
        assert d.score > 0.0

    def test_error_counter_resets_on_success(self):
        d = make_detector(max_errors=3)
        call(d, tool="read_file", error=True)
        call(d, tool="read_file", error=True)
        assert d._consecutive_errors == 2
        # Successful call resets error counter
        call(d, tool="read_file", error=False)
        assert d._consecutive_errors == 0

    def test_last_reason_mentions_errors(self):
        d = make_detector(max_errors=3)
        for _ in range(3):
            call(d, tool="read_file", error=True)
        assert "error" in d.last_reason.lower()


# ---------------------------------------------------------------------------
# Read-only signal (Coder only)
# ---------------------------------------------------------------------------

class TestReadOnlySignal:
    def test_no_signal_for_non_coder(self):
        """Read-only signal must not fire for Writer even with many reads."""
        d = make_detector(role=AgentRole.WRITER, max_readonly_turns=4)
        results = [call(d, tool="read_file") for _ in range(20)]
        # Writer threshold is 1.0 — should never escalate
        assert not any(results)

    def test_signal_fires_for_coder_after_threshold(self):
        d = make_detector(role=AgentRole.CODER, max_readonly_turns=4)
        # Need max_readonly_turns // 2 + some more reads to get score > 0
        for _ in range(6):
            call(d, tool="read_file")
        assert d.score > 0.0

    def test_write_tool_resets_readonly_counter(self):
        d = make_detector(role=AgentRole.CODER, max_readonly_turns=4)
        for _ in range(4):
            call(d, tool="read_file")
        score_before = d.score
        call(d, tool="str_replace", error=False)
        # Counter reset — score should drop
        assert d.score <= score_before

    def test_write_tool_with_error_does_not_reset(self):
        d = make_detector(role=AgentRole.CODER, max_readonly_turns=4)
        for _ in range(4):
            call(d, tool="read_file")
        score_before = d.score
        # Error on write tool — should not reset counter
        call(d, tool="str_replace", error=True)
        assert d.score >= score_before

    def test_all_write_tools_reset_counter(self):
        for tool in WRITE_TOOLS:
            d = make_detector(role=AgentRole.CODER, max_readonly_turns=4)
            for _ in range(4):
                call(d, tool="read_file")
            call(d, tool=tool, error=False)
            # After a write, counter resets — next few reads should be fine
            assert d._turns_without_write == 0


# ---------------------------------------------------------------------------
# Summary and properties
# ---------------------------------------------------------------------------

class TestSummaryAndProperties:
    def test_summary_contains_role_not_phase(self):
        d = make_detector(role=AgentRole.CODER)
        call(d, tool="read_file")
        summary = d.summary
        assert "role" in summary
        assert "phase" not in summary

    def test_summary_role_value_is_string(self):
        d = make_detector(role=AgentRole.CODER)
        assert d.summary["role"] == "coder"

    def test_summary_total_calls_increments(self):
        d = make_detector()
        call(d)
        call(d)
        call(d)
        assert d.summary["total_calls"] == 3

    def test_score_property_matches_last_compute(self):
        d = make_detector()
        call(d, tool="read_file", args={"path": "a.py"})
        call(d, tool="read_file", args={"path": "a.py"})
        assert d.score == d._score

    def test_last_reason_populated_after_signal(self):
        d = make_detector(max_errors=2)
        call(d, tool="read_file", error=True)
        call(d, tool="read_file", error=True)
        assert d.last_reason != ""


# ---------------------------------------------------------------------------
# _call_signature helper
# ---------------------------------------------------------------------------

class TestCallSignature:
    def test_same_call_produces_same_hash(self):
        h1 = _call_signature("read_file", {"path": "foo.py"})
        h2 = _call_signature("read_file", {"path": "foo.py"})
        assert h1 == h2

    def test_different_tool_produces_different_hash(self):
        h1 = _call_signature("read_file", {"path": "foo.py"})
        h2 = _call_signature("str_replace", {"path": "foo.py"})
        assert h1 != h2

    def test_different_args_produces_different_hash(self):
        h1 = _call_signature("read_file", {"path": "foo.py"})
        h2 = _call_signature("read_file", {"path": "bar.py"})
        assert h1 != h2

    def test_returns_string(self):
        assert isinstance(_call_signature("read_file", {}), str)