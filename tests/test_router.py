"""
tests/test_router.py

Tests for matrixmouse.router — Router and parse_model_string.

Coverage:
    parse_model_string:
        - Local ollama (no host)
        - Local llamacpp (no host)
        - Remote ollama with http host
        - Remote anthropic
        - Remote openai
        - Model names with colons (e.g. qwen3:4b)
        - Missing backend raises ValueError
        - Unknown backend raises ValueError
        - Empty string raises ValueError

    local_only enforcement:
        - local_only=True with remote backend raises ValueError at construction
        - local_only=True with local backends passes

    model_for_role:
        - MANAGER returns manager_model
        - CRITIC returns critic_model
        - CODER returns first cascade tier by default
        - WRITER returns writer_model
        - Unknown role falls back to coder_model with warning

    parsed_model_for_role:
        - Returns ParsedModel with correct backend and model fields

    stream_for_role / think_for_role:
        - Each role returns configured value
        - Unknown role returns sensible default

    Cascade:
        - Single-tier cascade when coder_cascade empty
        - Multi-tier cascade built from config
        - current_tier starts at 0
        - at_ceiling False when below top
        - at_ceiling True at top

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
        - Contains system, instruction, handoff, recent messages
        - Handoff message contains role from summary
        - keep_recent limits included messages

    backend_for_role / get_backend:
        - Returns an LLMBackend instance
        - Same (host, backend) pair returns cached instance
        - Different hosts return different instances

    ensure_all_models:
        - Calls ensure_model on each backend for each unique model
        - Deduplicates same model on same backend
"""

from unittest.mock import MagicMock, patch

import pytest

from matrixmouse.router import Router, parse_model_string, ParsedModel
from matrixmouse.task import AgentRole


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# All model strings use the [host:]backend:model format.
# We use ollama: prefix throughout since it's always local and needs
# no API key. Tests that need remote backends override explicitly.

_OLLAMA_MODEL    = "ollama:test-model"
_OLLAMA_CASCADE  = ["ollama:small-model", "ollama:medium-model", "ollama:large-model"]


def make_config(**kwargs) -> MagicMock:
    cfg = MagicMock()
    cfg.local_only        = kwargs.get("local_only",        True)
    cfg.manager_model     = kwargs.get("manager_model",     "ollama:manager-model")
    cfg.critic_model      = kwargs.get("critic_model",      "ollama:critic-model")
    cfg.coder_model       = kwargs.get("coder_model",       "ollama:coder-model")
    cfg.writer_model      = kwargs.get("writer_model",      "ollama:writer-model")
    cfg.summarizer_model  = kwargs.get("summarizer_model",  "ollama:summarizer-model")
    cfg.merge_resolution_model = kwargs.get("merge_resolution_model", "")
    cfg.coder_cascade     = kwargs.get("coder_cascade",     ["ollama:coder-model"])
    cfg.manager_stream    = kwargs.get("manager_stream",    True)
    cfg.critic_stream     = kwargs.get("critic_stream",     True)
    cfg.coder_stream      = kwargs.get("coder_stream",      True)
    cfg.writer_stream     = kwargs.get("writer_stream",     True)
    cfg.manager_think     = kwargs.get("manager_think",     False)
    cfg.critic_think      = kwargs.get("critic_think",      False)
    cfg.coder_think       = kwargs.get("coder_think",       False)
    cfg.writer_think      = kwargs.get("writer_think",      False)
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
# parse_model_string
# ---------------------------------------------------------------------------

class TestParseModelString:
    def test_local_ollama_no_host(self):
        p = parse_model_string("ollama:mymodel")
        assert p.backend == "ollama"
        assert p.model == "mymodel"
        assert p.host == "http://localhost:11434"
        assert p.is_remote is False

    def test_local_llamacpp_no_host(self):
        p = parse_model_string("llamacpp:mymodel.gguf")
        assert p.backend == "llamacpp"
        assert p.model == "mymodel.gguf"
        assert p.is_remote is False

    def test_remote_ollama_with_http_host(self):
        p = parse_model_string("http://192.168.1.42:ollama:qwen3:4b")
        assert p.host == "http://192.168.1.42"
        assert p.backend == "ollama"
        assert p.model == "qwen3:4b"
        assert p.is_remote is False  # ollama is local even when remote host

    def test_anthropic_backend(self):
        p = parse_model_string("anthropic:claude-sonnet-4-5")
        assert p.backend == "anthropic"
        assert p.model == "claude-sonnet-4-5"
        assert p.is_remote is True

    def test_openai_backend(self):
        p = parse_model_string("openai:gpt-4o")
        assert p.backend == "openai"
        assert p.model == "gpt-4o"
        assert p.is_remote is True

    def test_model_name_with_colons(self):
        """Model names like qwen3:4b contain colons — must be preserved."""
        p = parse_model_string("ollama:qwen3:4b")
        assert p.backend == "ollama"
        assert p.model == "qwen3:4b"

    def test_https_host_with_llamacpp(self):
        p = parse_model_string("https://192.168.1.42:llamacpp:model.gguf")
        assert p.host == "https://192.168.1.42"
        assert p.backend == "llamacpp"
        assert p.model == "model.gguf"

    def test_empty_string_raises(self):
        with pytest.raises(ValueError, match="empty"):
            parse_model_string("")

    def test_unknown_backend_raises(self):
        with pytest.raises(ValueError, match="Unknown backend"):
            parse_model_string("fakebackend:some-model")

    def test_missing_model_raises(self):
        with pytest.raises(ValueError, match="no model identifier after backend"):
            parse_model_string("ollama:")

    def test_returns_parsed_model_dataclass(self):
        p = parse_model_string("ollama:test")
        assert isinstance(p, ParsedModel)

    def test_raw_field_preserved(self):
        raw = "ollama:qwen3:4b"
        p = parse_model_string(raw)
        assert p.raw == raw


# ---------------------------------------------------------------------------
# local_only enforcement
# ---------------------------------------------------------------------------

class TestLocalOnly:
    def test_remote_backend_raises_when_local_only_true(self):
        with pytest.raises(ValueError, match="local_only"):
            make_router(
                local_only=True,
                coder_cascade=["anthropic:claude-sonnet-4-5"],
            )

    def test_remote_manager_model_raises_when_local_only(self):
        with pytest.raises(ValueError, match="local_only"):
            make_router(
                local_only=True,
                manager_model="openai:gpt-4o",
            )

    def test_local_backends_pass_when_local_only_true(self):
        """ollama and llamacpp are local — no error even with local_only=True."""
        router = make_router(
            local_only=True,
            coder_cascade=["ollama:small", "llamacpp:large.gguf"],
        )
        assert router is not None

    def test_local_only_false_allows_remote(self):
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
            router = make_router(
                local_only=False,
                coder_cascade=["anthropic:claude-sonnet-4-5"],
            )
        assert router is not None

    def test_violation_message_names_offending_keys(self):
        """Error message should name which config keys have remote backends."""
        with pytest.raises(ValueError) as exc_info:
            make_router(
                local_only=True,
                manager_model="openai:gpt-4o",
                critic_model="anthropic:claude-sonnet-4-5",
            )
        msg = str(exc_info.value)
        assert "manager_model" in msg
        assert "critic_model" in msg


# ---------------------------------------------------------------------------
# model_for_role
# ---------------------------------------------------------------------------

class TestModelForRole:
    def test_manager_returns_manager_model(self):
        r = make_router(manager_model="ollama:big-model")
        assert r.model_for_role(AgentRole.MANAGER) == "ollama:big-model"

    def test_critic_returns_critic_model(self):
        r = make_router(critic_model="ollama:big-model")
        assert r.model_for_role(AgentRole.CRITIC) == "ollama:big-model"

    def test_coder_returns_first_cascade_tier(self):
        r = make_router(coder_cascade=["ollama:small", "ollama:medium", "ollama:large"])
        assert r.model_for_role(AgentRole.CODER) == "ollama:small"

    def test_writer_returns_writer_model(self):
        r = make_router(writer_model="ollama:writer-model")
        assert r.model_for_role(AgentRole.WRITER) == "ollama:writer-model"

    def test_unknown_role_falls_back_to_coder_model(self):
        r = make_router(coder_model="ollama:coder-model")
        result = r.model_for_role("nonexistent_role") # type: ignore[arg-type]
        assert result == "ollama:coder-model"


# ---------------------------------------------------------------------------
# parsed_model_for_role
# ---------------------------------------------------------------------------

class TestParsedModelForRole:
    def test_returns_parsed_model(self):
        r = make_router(manager_model="ollama:big-model")
        p = r.parsed_model_for_role(AgentRole.MANAGER)
        assert isinstance(p, ParsedModel)
        assert p.backend == "ollama"
        assert p.model == "big-model"

    def test_coder_model_with_colon_in_name(self):
        r = make_router(coder_cascade=["ollama:qwen3:4b"])
        p = r.parsed_model_for_role(AgentRole.CODER)
        assert p.model == "qwen3:4b"

    def test_local_model_for_role_strips_prefix(self):
        r = make_router(manager_model="ollama:my-model")
        assert r.local_model_for_role("ollama:my-model") == "my-model"

    def test_parsed_model_for_role_for_merge_role(self):
        """parsed_model_for_role for MERGE role returns correct model."""
        r = make_router(merge_resolution_model="ollama:merge-model")
        p = r.parsed_model_for_role(AgentRole.MERGE)
        assert isinstance(p, ParsedModel)
        assert p.backend == "ollama"
        assert p.model == "merge-model"

    def test_parsed_model_for_role_merge_falls_back_to_cascade_top(self):
        """MERGE role falls back to top of cascade when merge_resolution_model empty."""
        r = make_router(
            merge_resolution_model="",
            coder_cascade=["ollama:small", "ollama:medium", "ollama:large"],
        )
        p = r.parsed_model_for_role(AgentRole.MERGE)
        assert isinstance(p, ParsedModel)
        assert p.model == "large"  # Top of cascade


# ---------------------------------------------------------------------------
# _merge_model
# ---------------------------------------------------------------------------

class TestMergeModel:
    """Tests for Router._merge_model method."""

    def test_returns_configured_merge_model(self):
        r = make_router(merge_resolution_model="ollama:merge-model")
        assert r._merge_model() == "ollama:merge-model"

    def test_falls_back_to_top_of_cascade_when_empty(self):
        """_merge_model falls back to top of cascade when merge_resolution_model empty."""
        r = make_router(
            merge_resolution_model="",
            coder_cascade=["ollama:small", "ollama:medium", "ollama:large"],
        )
        assert r._merge_model() == "ollama:large"

    def test_falls_back_to_coder_model_when_cascade_empty(self):
        """_merge_model falls back to coder_model when cascade is also empty."""
        r = make_router(
            merge_resolution_model="",
            coder_cascade=[],
            coder_model="ollama:fallback-model",
        )
        assert r._merge_model() == "ollama:fallback-model"


# ---------------------------------------------------------------------------
# stream_for_role
# ---------------------------------------------------------------------------

class TestStreamForRole:
    def test_manager_returns_manager_stream(self):
        r = make_router(manager_stream=False)
        assert r.stream_for_role(AgentRole.MANAGER) is False

    def test_critic_returns_critic_stream(self):
        r = make_router(critic_stream=True)
        assert r.stream_for_role(AgentRole.CRITIC) is True

    def test_coder_returns_coder_stream(self):
        r = make_router(coder_stream=False)
        assert r.stream_for_role(AgentRole.CODER) is False

    def test_writer_returns_writer_stream(self):
        r = make_router(writer_stream=False)
        assert r.stream_for_role(AgentRole.WRITER) is False

    def test_unknown_role_returns_true(self):
        r = make_router()
        assert r.stream_for_role("nonexistent") is True # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# think_for_role
# ---------------------------------------------------------------------------

class TestThinkForRole:
    def test_manager_returns_manager_think(self):
        r = make_router(manager_think=True)
        assert r.think_for_role(AgentRole.MANAGER) is True

    def test_critic_returns_critic_think(self):
        r = make_router(critic_think=False)
        assert r.think_for_role(AgentRole.CRITIC) is False

    def test_coder_returns_coder_think(self):
        r = make_router(coder_think=True)
        assert r.think_for_role(AgentRole.CODER) is True

    def test_writer_returns_writer_think(self):
        r = make_router(writer_think=True)
        assert r.think_for_role(AgentRole.WRITER) is True

    def test_unknown_role_returns_false(self):
        r = make_router()
        assert r.think_for_role("nonexistent") is False # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Cascade construction
# ---------------------------------------------------------------------------

class TestCascade:
    def test_single_tier_when_cascade_empty(self):
        r = make_router(coder_cascade=[], coder_model="ollama:only-model")
        assert r._cascade == ["ollama:only-model"]

    def test_multi_tier_from_config(self):
        r = make_router(coder_cascade=["ollama:small", "ollama:medium", "ollama:large"])
        assert r._cascade == ["ollama:small", "ollama:medium", "ollama:large"]

    def test_current_tier_starts_at_zero(self):
        r = make_router(coder_cascade=["ollama:small", "ollama:large"])
        assert r.current_tier == 0

    def test_at_ceiling_false_when_below_top(self):
        r = make_router(coder_cascade=["ollama:small", "ollama:large"])
        assert r.at_ceiling is False

    def test_at_ceiling_true_with_single_tier(self):
        r = make_router(coder_cascade=["ollama:only-model"])
        assert r.at_ceiling is True

    def test_at_ceiling_true_when_at_top(self):
        r = make_router(coder_cascade=["ollama:small", "ollama:large"])
        r._current_tier = 1
        assert r.at_ceiling is True


# ---------------------------------------------------------------------------
# escalate
# ---------------------------------------------------------------------------

class TestEscalate:
    def test_escalation_advances_tier(self):
        r = make_router(coder_cascade=["ollama:small", "ollama:medium", "ollama:large"])
        r.escalate(make_detector())
        assert r.current_tier == 1

    def test_escalation_returns_new_model(self):
        r = make_router(coder_cascade=["ollama:small", "ollama:medium", "ollama:large"])
        escalated, new_model = r.escalate(make_detector())
        assert escalated is True
        assert new_model == "ollama:medium"

    def test_escalation_at_ceiling_returns_false(self):
        r = make_router(coder_cascade=["ollama:small", "ollama:large"])
        r._current_tier = 1
        escalated, new_model = r.escalate(make_detector())
        assert escalated is False
        assert new_model is None

    def test_escalation_resets_successful_cycles(self):
        r = make_router(coder_cascade=["ollama:small", "ollama:large"])
        r._successful_cycles = 1
        r.escalate(make_detector())
        assert r._successful_cycles == 0

    def test_model_for_coder_reflects_new_tier(self):
        r = make_router(coder_cascade=["ollama:small", "ollama:medium", "ollama:large"])
        r.escalate(make_detector())
        assert r.model_for_role(AgentRole.CODER) == "ollama:medium"


# ---------------------------------------------------------------------------
# record_success / de-escalation
# ---------------------------------------------------------------------------

class TestDeEscalation:
    def test_noop_at_base_tier(self):
        r = make_router(coder_cascade=["ollama:small", "ollama:large"])
        r.record_success()
        assert r.current_tier == 0
        assert r._successful_cycles == 0

    def test_increments_cycle_counter(self):
        r = make_router(coder_cascade=["ollama:small", "ollama:large"])
        r._current_tier = 1
        r.record_success()
        assert r._successful_cycles == 1

    def test_de_escalates_after_threshold(self):
        r = make_router(coder_cascade=["ollama:small", "ollama:large"])
        r._current_tier = 1
        for _ in range(Router.DEESCALATE_AFTER):
            r.record_success()
        assert r.current_tier == 0

    def test_resets_counter_on_de_escalation(self):
        r = make_router(coder_cascade=["ollama:small", "ollama:large"])
        r._current_tier = 1
        for _ in range(Router.DEESCALATE_AFTER):
            r.record_success()
        assert r._successful_cycles == 0

    def test_does_not_go_below_tier_zero(self):
        r = make_router(coder_cascade=["ollama:small", "ollama:medium", "ollama:large"])
        r._current_tier = 1
        for _ in range(Router.DEESCALATE_AFTER):
            r.record_success()
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
            {"role": "system",    "content": "sys"},
            {"role": "user",      "content": "task"},
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


# ---------------------------------------------------------------------------
# backend_for_role / get_backend / caching
# ---------------------------------------------------------------------------

class TestBackendCaching:
    def test_backend_for_role_returns_llmbackend(self):
        from matrixmouse.inference.base import LLMBackend
        r = make_router()
        with patch("matrixmouse.inference.ollama.OllamaBackend") as MockOllama:
            MockOllama.return_value = MagicMock(spec=LLMBackend)
            backend = r.backend_for_role(AgentRole.MANAGER)
        assert backend is not None

    def test_same_host_backend_pair_returns_cached_instance(self):
        """Two calls for the same (host, backend) return the identical object."""
        r = make_router(
            manager_model="ollama:model-a",
            critic_model="ollama:model-b",
        )
        with patch("matrixmouse.inference.ollama.OllamaBackend") as MockOllama:
            instance = MagicMock()
            MockOllama.return_value = instance
            b1 = r.backend_for_role(AgentRole.MANAGER)
            b2 = r.backend_for_role(AgentRole.CRITIC)
        # Both use ollama @ localhost — same cached instance
        assert b1 is b2
        assert MockOllama.call_count == 1

    def test_different_hosts_return_different_instances(self):
        r = make_router(
            manager_model="http://192.168.1.10:ollama:model-a",
            critic_model="http://192.168.1.11:ollama:model-b",
            local_only=False,
        )
        with patch("matrixmouse.inference.ollama.OllamaBackend") as MockOllama:
            MockOllama.side_effect = [MagicMock(), MagicMock()]
            b1 = r.backend_for_role(AgentRole.MANAGER)
            b2 = r.backend_for_role(AgentRole.CRITIC)
        assert b1 is not b2
        assert MockOllama.call_count == 2

    def test_get_backend_uses_same_cache(self):
        """get_backend() and backend_for_role() share the same cache."""
        r = make_router(manager_model="ollama:test-model")
        with patch("matrixmouse.inference.ollama.OllamaBackend") as MockOllama:
            instance = MagicMock()
            MockOllama.return_value = instance
            b1 = r.backend_for_role(AgentRole.MANAGER)
            b2 = r.get_backend("ollama:test-model")
        assert b1 is b2
        assert MockOllama.call_count == 1


# ---------------------------------------------------------------------------
# ensure_all_models
# ---------------------------------------------------------------------------

class TestEnsureAllModels:
    def test_calls_ensure_model_for_each_configured_model(self):
        r = make_router(
            manager_model="ollama:manager",
            critic_model="ollama:critic",
            coder_cascade=["ollama:coder"],
            writer_model="ollama:writer",
            summarizer_model="ollama:summarizer",
        )
        mock_backend = MagicMock()
        with patch.object(r, "_get_or_create_backend", return_value=mock_backend):
            r.ensure_all_models()
        assert mock_backend.ensure_model.called

    def test_deduplicates_same_model_on_same_backend(self):
        """Same model string on the same backend is only ensured once."""
        r = make_router(
            manager_model="ollama:shared-model",
            critic_model="ollama:shared-model",
            coder_cascade=["ollama:shared-model"],
            writer_model="ollama:shared-model",
            summarizer_model="ollama:shared-model",
        )
        mock_backend = MagicMock()
        with patch.object(r, "_get_or_create_backend", return_value=mock_backend):
            r.ensure_all_models()
        assert mock_backend.ensure_model.call_count == 1

    def test_skips_empty_model_strings(self):
        """Empty merge_resolution_model should not cause an error."""
        r = make_router(merge_resolution_model="")
        mock_backend = MagicMock()
        with patch.object(r, "_get_or_create_backend", return_value=mock_backend):
            r.ensure_all_models()
        # Should complete without raising
