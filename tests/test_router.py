"""
tests/test_router.py

Tests for matrixmouse.router — Router.

Coverage:
    model_for_role:
        - MANAGER returns planner_model
        - CRITIC returns planner_model
        - CODER returns first cascade tier by default
        - WRITER returns writer_model
        - WRITER falls back to coder_model when writer_model absent
        - Unknown role falls back to coder_model with warning

    stream_for_role:
        - MANAGER/CRITIC return planner_stream
        - CODER returns coder_stream
        - WRITER returns writer_stream, falls back to coder_stream

    think_for_role:
        - MANAGER/CRITIC return planner_think
        - CODER returns coder_think
        - WRITER returns writer_think, falls back to coder_think

    Cascade:
        - Single-tier cascade when coder_cascade empty
        - Multi-tier cascade built from config
        - current_tier starts at 0
        - at_ceiling False when below top
        - at_ceiling True when at top

    escalate:
        - Returns (True, new_model) when below ceiling
        - Returns (False, None) when at ceiling
        - Advances tier on escalation
        - Resets successful_cycles on escalation

    record_success / de-escalation:
        - No-op at base tier
        - Increments counter
        - De-escalates after DEESCALATE_AFTER successes
        - Resets counter on de-escalation
        - Does not de-escalate below tier 0

    build_handoff:
        - Returns original messages if fewer than 2
        - Contains system message, instruction, handoff message, recent messages
        - Handoff message contains role from summary
        - keep_recent limits included messages
"""

from unittest.mock import MagicMock

import pytest

from matrixmouse.router import Router
from matrixmouse.task import AgentRole


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_config(**kwargs) -> MagicMock:
    cfg = MagicMock()
    cfg.planner_model    = kwargs.get("planner_model",    "planner-model")
    cfg.coder_model      = kwargs.get("coder_model",      "coder-model")
    cfg.summarizer_model = kwargs.get("summarizer_model", "summarizer-model")
    cfg.coder_cascade    = kwargs.get("coder_cascade",    ["coder-model"])
    cfg.planner_stream   = kwargs.get("planner_stream",   True)
    cfg.coder_stream     = kwargs.get("coder_stream",     True)
    cfg.planner_think    = kwargs.get("planner_think",    False)
    cfg.coder_think      = kwargs.get("coder_think",      False)

    # writer_model / writer_stream / writer_think via getattr fallback
    if "writer_model" in kwargs:
        cfg.writer_model = kwargs["writer_model"]
    else:
        del cfg.writer_model   # ensure getattr fallback is tested

    if "writer_stream" in kwargs:
        cfg.writer_stream = kwargs["writer_stream"]
    else:
        del cfg.writer_stream

    if "writer_think" in kwargs:
        cfg.writer_think = kwargs["writer_think"]
    else:
        del cfg.writer_think

    return cfg


def make_router(**kwargs) -> Router:
    return Router(make_config(**kwargs))


def make_detector(reason="repeated tool call", role=AgentRole.CODER):
    d = MagicMock()
    d.last_reason = reason
    d.summary = {
        "reason":              reason,
        "role":                role.value,
        "total_calls":         10,
        "consecutive_errors":  2,
        "turns_without_write": 5,
    }
    return d


# ---------------------------------------------------------------------------
# model_for_role
# ---------------------------------------------------------------------------

class TestModelForRole:
    def test_manager_returns_planner_model(self):
        r = make_router(planner_model="big-model")
        assert r.model_for_role(AgentRole.MANAGER) == "big-model"

    def test_critic_returns_planner_model(self):
        r = make_router(planner_model="big-model")
        assert r.model_for_role(AgentRole.CRITIC) == "big-model"

    def test_coder_returns_first_cascade_tier(self):
        r = make_router(coder_cascade=["small", "medium", "large"])
        assert r.model_for_role(AgentRole.CODER) == "small"

    def test_writer_returns_writer_model_when_set(self):
        r = make_router(writer_model="writer-model")
        assert r.model_for_role(AgentRole.WRITER) == "writer-model"

    def test_writer_falls_back_to_coder_model(self):
        # writer_model not set — should fall back to coder_model
        r = make_router(coder_model="coder-model")
        assert r.model_for_role(AgentRole.WRITER) == "coder-model"

    def test_unknown_role_falls_back_to_coder_model(self):
        r = make_router(coder_model="coder-model")
        # Pass a value that isn't a real AgentRole
        result = r.model_for_role("nonexistent_role")
        assert result == "coder-model"


# ---------------------------------------------------------------------------
# stream_for_role
# ---------------------------------------------------------------------------

class TestStreamForRole:
    def test_manager_returns_planner_stream(self):
        r = make_router(planner_stream=False)
        assert r.stream_for_role(AgentRole.MANAGER) is False

    def test_critic_returns_planner_stream(self):
        r = make_router(planner_stream=True)
        assert r.stream_for_role(AgentRole.CRITIC) is True

    def test_coder_returns_coder_stream(self):
        r = make_router(coder_stream=False)
        assert r.stream_for_role(AgentRole.CODER) is False

    def test_writer_returns_writer_stream_when_set(self):
        r = make_router(writer_stream=False)
        assert r.stream_for_role(AgentRole.WRITER) is False

    def test_writer_falls_back_to_coder_stream(self):
        r = make_router(coder_stream=True)
        assert r.stream_for_role(AgentRole.WRITER) is True

    def test_unknown_role_returns_true(self):
        r = make_router()
        assert r.stream_for_role("nonexistent") is True


# ---------------------------------------------------------------------------
# think_for_role
# ---------------------------------------------------------------------------

class TestThinkForRole:
    def test_manager_returns_planner_think(self):
        r = make_router(planner_think=True)
        assert r.think_for_role(AgentRole.MANAGER) is True

    def test_critic_returns_planner_think(self):
        r = make_router(planner_think=False)
        assert r.think_for_role(AgentRole.CRITIC) is False

    def test_coder_returns_coder_think(self):
        r = make_router(coder_think=True)
        assert r.think_for_role(AgentRole.CODER) is True

    def test_writer_returns_writer_think_when_set(self):
        r = make_router(writer_think=True)
        assert r.think_for_role(AgentRole.WRITER) is True

    def test_writer_falls_back_to_coder_think(self):
        r = make_router(coder_think=True)
        assert r.think_for_role(AgentRole.WRITER) is True

    def test_unknown_role_returns_false(self):
        r = make_router()
        assert r.think_for_role("nonexistent") is False


# ---------------------------------------------------------------------------
# Cascade construction
# ---------------------------------------------------------------------------

class TestCascade:
    def test_single_tier_when_cascade_empty(self):
        r = make_router(coder_cascade=[], coder_model="only-model")
        assert r._cascade == ["only-model"]

    def test_multi_tier_from_config(self):
        r = make_router(coder_cascade=["small", "medium", "large"])
        assert r._cascade == ["small", "medium", "large"]

    def test_current_tier_starts_at_zero(self):
        r = make_router(coder_cascade=["small", "large"])
        assert r.current_tier == 0

    def test_at_ceiling_false_when_below_top(self):
        r = make_router(coder_cascade=["small", "large"])
        assert r.at_ceiling is False

    def test_at_ceiling_true_with_single_tier(self):
        r = make_router(coder_cascade=["only-model"])
        assert r.at_ceiling is True

    def test_at_ceiling_true_when_at_top(self):
        r = make_router(coder_cascade=["small", "large"])
        r._current_tier = 1
        assert r.at_ceiling is True


# ---------------------------------------------------------------------------
# escalate
# ---------------------------------------------------------------------------

class TestEscalate:
    def test_escalation_advances_tier(self):
        r = make_router(coder_cascade=["small", "medium", "large"])
        detector = make_detector()
        r.escalate(detector)
        assert r.current_tier == 1

    def test_escalation_returns_new_model(self):
        r = make_router(coder_cascade=["small", "medium", "large"])
        detector = make_detector()
        escalated, new_model = r.escalate(detector)
        assert escalated is True
        assert new_model == "medium"

    def test_escalation_at_ceiling_returns_false(self):
        r = make_router(coder_cascade=["small", "large"])
        r._current_tier = 1
        detector = make_detector()
        escalated, new_model = r.escalate(detector)
        assert escalated is False
        assert new_model is None

    def test_escalation_resets_successful_cycles(self):
        r = make_router(coder_cascade=["small", "large"])
        r._successful_cycles = 1
        r.escalate(make_detector())
        assert r._successful_cycles == 0

    def test_model_for_coder_reflects_new_tier(self):
        r = make_router(coder_cascade=["small", "medium", "large"])
        r.escalate(make_detector())
        assert r.model_for_role(AgentRole.CODER) == "medium"


# ---------------------------------------------------------------------------
# record_success / de-escalation
# ---------------------------------------------------------------------------

class TestDeEscalation:
    def test_noop_at_base_tier(self):
        r = make_router(coder_cascade=["small", "large"])
        r.record_success()
        assert r.current_tier == 0
        assert r._successful_cycles == 0

    def test_increments_cycle_counter(self):
        r = make_router(coder_cascade=["small", "large"])
        r._current_tier = 1
        r.record_success()
        assert r._successful_cycles == 1

    def test_de_escalates_after_threshold(self):
        r = make_router(coder_cascade=["small", "large"])
        r._current_tier = 1
        for _ in range(Router.DEESCALATE_AFTER):
            r.record_success()
        assert r.current_tier == 0

    def test_resets_counter_on_de_escalation(self):
        r = make_router(coder_cascade=["small", "large"])
        r._current_tier = 1
        for _ in range(Router.DEESCALATE_AFTER):
            r.record_success()
        assert r._successful_cycles == 0

    def test_does_not_go_below_tier_zero(self):
        r = make_router(coder_cascade=["small", "medium", "large"])
        r._current_tier = 1
        # De-escalate once
        for _ in range(Router.DEESCALATE_AFTER):
            r.record_success()
        # Try to de-escalate again — should stay at 0
        for _ in range(Router.DEESCALATE_AFTER):
            r.record_success()
        assert r.current_tier == 0


# ---------------------------------------------------------------------------
# build_handoff
# ---------------------------------------------------------------------------

class TestBuildHandoff:
    def test_returns_original_when_fewer_than_two_messages(self):
        r = make_router()
        msgs = [{"role": "system", "content": "sys"}]
        assert r.build_handoff(make_detector(), msgs) is msgs

    def test_result_starts_with_system_message(self):
        r = make_router()
        msgs = [
            {"role": "system",    "content": "sys"},
            {"role": "user",      "content": "task"},
            {"role": "assistant", "content": "thinking"},
            {"role": "tool",      "content": "result"},
        ]
        result = r.build_handoff(make_detector(), msgs)
        assert result[0] == msgs[0]

    def test_result_includes_handoff_message(self):
        r = make_router()
        msgs = [
            {"role": "system",    "content": "sys"},
            {"role": "user",      "content": "task"},
            {"role": "assistant", "content": "thinking"},
        ]
        result = r.build_handoff(make_detector(), msgs)
        handoff = next(
            m for m in result
            if isinstance(m.get("content"), str)
            and "ESCALATION HANDOFF" in m["content"]
        )
        assert handoff is not None

    def test_handoff_message_contains_role(self):
        r = make_router()
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user",   "content": "task"},
            {"role": "assistant", "content": "work"},
        ]
        detector = make_detector(role=AgentRole.CODER)
        result = r.build_handoff(detector, msgs)
        handoff_content = next(
            m["content"] for m in result
            if isinstance(m.get("content"), str)
            and "ESCALATION HANDOFF" in m["content"]
        )
        assert "coder" in handoff_content.lower()

    def test_keep_recent_limits_appended_messages(self):
        r = make_router()
        msgs = (
            [{"role": "system", "content": "sys"},
             {"role": "user",   "content": "task"}]
            + [{"role": "assistant", "content": f"msg{i}"} for i in range(10)]
        )
        result = r.build_handoff(make_detector(), msgs, keep_recent=3)
        # system + instruction + handoff + 3 recent = 6
        assert len(result) == 6