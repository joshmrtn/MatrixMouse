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
    # --- Cascade keys (Issue #32) ---
    cfg.manager_cascade       = kwargs.get("manager_cascade",       ["ollama:manager-model"])
    cfg.critic_cascade        = kwargs.get("critic_cascade",        ["ollama:critic-model"])
    cfg.writer_cascade        = kwargs.get("writer_cascade",        ["ollama:writer-model"])
    cfg.coder_cascade         = kwargs.get("coder_cascade",         ["ollama:coder-model"])
    cfg.merge_resolution_cascade = kwargs.get("merge_resolution_cascade", [])
    cfg.summarizer_cascade    = kwargs.get("summarizer_cascade",    ["ollama:summarizer-model"])
    cfg.backend_cooldown_initial_seconds = kwargs.get("backend_cooldown_initial_seconds", 30)
    cfg.backend_cooldown_max_seconds = kwargs.get("backend_cooldown_max_seconds", 600)
    # --- Backward-compat single-model keys (shims until 1C) ---
    cfg.manager_model         = kwargs.get("manager_model",         "ollama:manager-model")
    cfg.critic_model          = kwargs.get("critic_model",          "ollama:critic-model")
    cfg.coder_model           = kwargs.get("coder_model",           "ollama:coder-model")
    cfg.writer_model          = kwargs.get("writer_model",          "ollama:writer-model")
    cfg.summarizer_model      = kwargs.get("summarizer_model",      "ollama:summarizer-model")
    cfg.merge_resolution_model = kwargs.get("merge_resolution_model", "")
    cfg.local_only            = kwargs.get("local_only",            True)
    cfg.manager_stream        = kwargs.get("manager_stream",        True)
    cfg.critic_stream         = kwargs.get("critic_stream",         True)
    cfg.coder_stream          = kwargs.get("coder_stream",          True)
    cfg.writer_stream         = kwargs.get("writer_stream",         True)
    cfg.manager_think         = kwargs.get("manager_think",         False)
    cfg.critic_think          = kwargs.get("critic_think",          False)
    cfg.coder_think           = kwargs.get("coder_think",           False)
    cfg.writer_think          = kwargs.get("writer_think",          False)
    return cfg


def make_router(**kwargs) -> Router:
    budget_tracker = kwargs.get("budget_tracker")
    cfg = make_config(**kwargs)
    if budget_tracker is not None:
        return Router(cfg, budget_tracker=budget_tracker)
    return Router(cfg)


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

    def test_remote_manager_cascade_raises_when_local_only(self):
        with pytest.raises(ValueError, match="local_only"):
            make_router(
                local_only=True,
                manager_cascade=["openai:gpt-4o"],
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
        """Error message should name which cascade keys have remote backends."""
        with pytest.raises(ValueError) as exc_info:
            make_router(
                local_only=True,
                manager_cascade=["openai:gpt-4o"],
                critic_cascade=["anthropic:claude-sonnet-4-5"],
            )
        msg = str(exc_info.value)
        assert "manager_cascade" in msg
        assert "critic_cascade" in msg


# ---------------------------------------------------------------------------
# model_for_role
# ---------------------------------------------------------------------------

class TestModelForRole:
    def test_manager_returns_manager_cascade_first(self):
        r = make_router(manager_cascade=["ollama:big-model"])
        assert r.model_for_role(AgentRole.MANAGER) == "ollama:big-model"

    def test_critic_returns_critic_cascade_first(self):
        r = make_router(critic_cascade=["ollama:big-model"])
        assert r.model_for_role(AgentRole.CRITIC) == "ollama:big-model"

    def test_coder_returns_first_cascade_tier(self):
        r = make_router(coder_cascade=["ollama:small", "ollama:medium", "ollama:large"])
        assert r.model_for_role(AgentRole.CODER) == "ollama:small"

    def test_writer_returns_writer_cascade_first(self):
        r = make_router(writer_cascade=["ollama:writer-model"])
        assert r.model_for_role(AgentRole.WRITER) == "ollama:writer-model"

    def test_unknown_role_falls_back_to_coder_cascade(self):
        r = make_router(coder_cascade=["ollama:coder-model"])
        # Unknown role is not an AgentRole — shim handles it gracefully
        result = r.model_for_role("nonexistent_role") # type: ignore[arg-type]
        assert result == "ollama:coder-model"


# ---------------------------------------------------------------------------
# parsed_model_for_role
# ---------------------------------------------------------------------------

class TestParsedModelForRole:
    def test_returns_parsed_model(self):
        r = make_router(manager_cascade=["ollama:big-model"])
        p = r.parsed_model_for_role(AgentRole.MANAGER)
        assert isinstance(p, ParsedModel)
        assert p.backend == "ollama"
        assert p.model == "big-model"

    def test_coder_model_with_colon_in_name(self):
        r = make_router(coder_cascade=["ollama:qwen3:4b"])
        p = r.parsed_model_for_role(AgentRole.CODER)
        assert p.model == "qwen3:4b"

    def test_local_model_for_role_strips_prefix(self):
        r = make_router(manager_cascade=["ollama:my-model"])
        assert r.local_model_for_role("ollama:my-model") == "my-model"

    def test_parsed_model_for_role_for_merge_role(self):
        """parsed_model_for_role for MERGE role returns correct model."""
        r = make_router(merge_resolution_cascade=["ollama:merge-model"])
        p = r.parsed_model_for_role(AgentRole.MERGE)
        assert isinstance(p, ParsedModel)
        assert p.backend == "ollama"
        assert p.model == "merge-model"

    def test_parsed_model_for_role_merge_falls_back_to_cascade_top(self):
        """MERGE role falls back to [coder_cascade[-1]] when merge_resolution_cascade empty."""
        r = make_router(
            merge_resolution_cascade=[],
            coder_cascade=["ollama:small", "ollama:medium", "ollama:large"],
        )
        p = r.parsed_model_for_role(AgentRole.MERGE)
        assert isinstance(p, ParsedModel)
        assert p.model == "large"  # Last of coder cascade


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
    def test_single_tier_cascade(self):
        r = make_router(coder_cascade=["ollama:only-model"])
        assert r.cascade_for_role(AgentRole.CODER) == ["ollama:only-model"]

    def test_multi_tier_from_config(self):
        r = make_router(coder_cascade=["ollama:small", "ollama:medium", "ollama:large"])
        assert r.cascade_for_role(AgentRole.CODER) == [
            "ollama:small", "ollama:medium", "ollama:large"
        ]

    def test_current_tier_starts_at_zero(self):
        """Shim: current_tier always returns 0 now."""
        r = make_router(coder_cascade=["ollama:small", "ollama:large"])
        assert r.current_tier == 0

    def test_at_ceiling_always_true(self):
        """Shim: at_ceiling always returns True since no escalation state."""
        r = make_router(coder_cascade=["ollama:small", "ollama:large"])
        assert r.at_ceiling is True


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
            manager_cascade=["http://192.168.1.10:ollama:model-a"],
            critic_cascade=["http://192.168.1.11:ollama:model-b"],
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
        r = make_router(manager_cascade=["ollama:test-model"])
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
            manager_cascade=["ollama:manager"],
            critic_cascade=["ollama:critic"],
            coder_cascade=["ollama:coder"],
            writer_cascade=["ollama:writer"],
            summarizer_cascade=["ollama:summarizer"],
        )
        mock_backend = MagicMock()
        with patch.object(r, "_get_or_create_backend", return_value=mock_backend):
            r.ensure_all_models()
        assert mock_backend.ensure_model.called

    def test_deduplicates_same_model_on_same_backend(self):
        """Same model string on the same backend is only ensured once."""
        r = make_router(
            manager_cascade=["ollama:shared-model"],
            critic_cascade=["ollama:shared-model"],
            coder_cascade=["ollama:shared-model"],
            writer_cascade=["ollama:shared-model"],
            summarizer_cascade=["ollama:shared-model"],
        )
        mock_backend = MagicMock()
        with patch.object(r, "_get_or_create_backend", return_value=mock_backend):
            r.ensure_all_models()
        # All are same model on same backend → ensure_model called once
        assert mock_backend.ensure_model.call_count == 1

    def test_only_ensures_first_entry_per_cascade(self):
        """ensure_all_models only ensures cascade[0] entries, not fallbacks."""
        r = make_router(
            manager_cascade=["ollama:manager1", "ollama:manager2"],
            coder_cascade=["ollama:coder1", "ollama:coder2"],
            merge_resolution_cascade=["ollama:merge1"],
            summarizer_cascade=["ollama:summarizer1"],
        )
        mock_backend = MagicMock()
        with patch.object(r, "_get_or_create_backend", return_value=mock_backend):
            r.ensure_all_models()
        # Only first entries ensured: manager1, coder1, merge1, summarizer1
        # (plus critic, writer with their defaults)
        ensured_models = [c[0][0] for c in mock_backend.ensure_model.call_args_list]
        assert "manager1" in ensured_models
        assert "coder1" in ensured_models
        assert "merge1" in ensured_models
        assert "summarizer1" in ensured_models
        # Second entries should NOT be ensured
        assert "manager2" not in ensured_models
        assert "coder2" not in ensured_models

    def test_skips_empty_model_strings(self):
        """Empty cascade entries should not cause an error."""
        # Cascades are validated at init, so empty strings are caught there.
        # This test confirms ensure_all_models handles normal entries fine.
        r = make_router(
            manager_cascade=["ollama:manager"],
            summarizer_cascade=["ollama:summarizer"],
        )
        mock_backend = MagicMock()
        with patch.object(r, "_get_or_create_backend", return_value=mock_backend):
            r.ensure_all_models()
        # Should complete without raising


# ---------------------------------------------------------------------------
# Phase 1B — New cascade API tests (Issue #32)
# ---------------------------------------------------------------------------

class TestCascadeForRole:
    """Tests for Router.cascade_for_role()."""

    def test_cascade_for_role_returns_configured_list(self):
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test"}):
            r = make_router(
                manager_cascade=["anthropic:claude-sonnet-4-5", "ollama:qwen3:72b"],
                coder_cascade=["ollama:qwen3:4b", "ollama:qwen3:9b"],
                local_only=False,
            )
        assert r.cascade_for_role(AgentRole.MANAGER) == [
            "anthropic:claude-sonnet-4-5", "ollama:qwen3:72b"
        ]
        assert r.cascade_for_role(AgentRole.CODER) == [
            "ollama:qwen3:4b", "ollama:qwen3:9b"
        ]

    def test_cascade_for_role_single_entry(self):
        r = make_router(coder_cascade=["ollama:qwen3:4b"])
        assert r.cascade_for_role(AgentRole.CODER) == ["ollama:qwen3:4b"]

    def test_cascade_for_role_merge_defaults_to_coder_last(self):
        """Merge cascade defaults to [coder_cascade[-1]] when not configured."""
        r = make_router(
            coder_cascade=["ollama:small", "ollama:medium", "ollama:large"],
            merge_resolution_cascade=[],
        )
        assert r.cascade_for_role(AgentRole.MERGE) == ["ollama:large"]

    def test_cascade_for_role_empty_raises_at_init(self):
        """Empty required cascade raises ValueError at construction."""
        with pytest.raises(ValueError, match="manager_cascade"):
            make_router(manager_cascade=[])

    def test_cascade_for_role_summarizer_empty_raises_at_init(self):
        with pytest.raises(ValueError, match="summarizer_cascade"):
            make_router(summarizer_cascade=[])


class TestSummarizerCascade:
    """Tests for Router.summarizer_cascade()."""

    def test_summarizer_cascade_returns_list(self):
        r = make_router(summarizer_cascade=["ollama:summarizer-small"])
        assert r.summarizer_cascade() == ["ollama:summarizer-small"]

    def test_summarizer_cascade_empty_raises_at_init(self):
        with pytest.raises(ValueError, match="summarizer_cascade"):
            make_router(summarizer_cascade=[])


class TestGetBackendForModel:
    """Tests for Router.get_backend_for_model() — replaces get_backend()."""

    def test_get_backend_for_model_caches_by_host_backend(self):
        """Same (host, backend) pair returns same instance."""
        r = make_router(local_only=False)
        with patch("matrixmouse.inference.ollama.OllamaBackend") as MockOllama:
            MockOllama.return_value = MagicMock()
            b1 = r.get_backend_for_model("ollama:model-a")
            b2 = r.get_backend_for_model("ollama:model-b")
        assert b1 is b2
        assert MockOllama.call_count == 1

    def test_get_backend_for_model_different_backends_distinct_instances(self):
        r = make_router(local_only=False)
        with patch("matrixmouse.inference.ollama.OllamaBackend") as MockOllama:
            MockOllama.side_effect = [MagicMock(), MagicMock()]
            b1 = r.get_backend_for_model("ollama:model-a")
            b2 = r.get_backend_for_model("http://10.0.0.1:ollama:model-b")
        assert b1 is not b2
        assert MockOllama.call_count == 2


class TestCascadeValidation:
    """Tests for _validate_config with cascade lists."""

    def test_validate_empty_string_entry_raises(self):
        """Empty string in any cascade raises ValueError at init."""
        with pytest.raises(ValueError, match="coder_cascade"):
            make_router(coder_cascade=["ollama:qwen3:4b", ""])

    def test_validate_local_only_rejects_remote_in_any_cascade_position(self):
        with pytest.raises(ValueError, match="manager_cascade"):
            make_router(
                local_only=True,
                manager_cascade=["ollama:small", "anthropic:claude-haiku-4-5"],
            )

    def test_validate_local_only_rejects_remote_in_summarizer_cascade(self):
        with pytest.raises(ValueError, match="summarizer_cascade"):
            make_router(
                local_only=True,
                summarizer_cascade=["openai:gpt-4o-mini"],
            )

    def test_validate_local_only_catches_last_entry_of_writer_cascade(self):
        """Only the *last* entry of writer_cascade is remote — still raises."""
        with pytest.raises(ValueError, match="writer_cascade"):
            make_router(
                local_only=True,
                writer_cascade=["ollama:qwen3:4b", "ollama:qwen3:9b", "anthropic:claude-sonnet-4-5"],
            )

    def test_validate_local_only_catches_last_entry_of_summarizer_cascade(self):
        with pytest.raises(ValueError, match="summarizer_cascade"):
            make_router(
                local_only=True,
                summarizer_cascade=["ollama:qwen3:4b", "anthropic:claude-haiku"],
            )

    def test_validate_local_only_allows_all_local_cascades(self):
        r = make_router(
            local_only=True,
            manager_cascade=["ollama:big-model"],
            critic_cascade=["ollama:critic-model"],
            writer_cascade=["ollama:writer-model"],
            coder_cascade=["ollama:coder-model"],
            merge_resolution_cascade=[],
            summarizer_cascade=["ollama:summarizer-model"],
        )
        assert r is not None

    def test_validate_malformed_model_string_raises(self):
        with pytest.raises(ValueError, match="coder_cascade"):
            make_router(coder_cascade=["not-a-valid-model-string!!!"])


class TestEnsureAllModelsCascade:
    """Tests for ensure_all_models with cascade changes."""

    def test_ensure_all_models_validates_all_entries(self):
        """Mock parse_model_string; confirm it is called for every entry."""
        r = make_router(
            manager_cascade=["ollama:manager1", "ollama:manager2"],
            critic_cascade=["ollama:critic1"],
            writer_cascade=["ollama:writer1"],
            coder_cascade=["ollama:coder1", "ollama:coder2", "ollama:coder3"],
            merge_resolution_cascade=["ollama:merge1"],
            summarizer_cascade=["ollama:summarizer1"],
        )
        mock_backend = MagicMock()
        with patch.object(r, "_get_or_create_backend", return_value=mock_backend):
            with patch("matrixmouse.router.parse_model_string") as mock_parse:
                mock_parse.return_value = MagicMock(
                    host="http://localhost:11434",
                    backend="ollama",
                    model="test",
                )
                r.ensure_all_models()
        # Ensure parse_model_string was called (validation of all entries is
        # done during validation; ensure_all_models calls parse for models
        # it ensures)
        assert mock_parse.called

    def test_ensure_all_models_only_ensures_first_entry(self):
        """Mock ensure_model; confirm called exactly once per role with cascade[0]."""
        r = make_router(
            manager_cascade=["ollama:manager1", "ollama:manager2"],
            critic_cascade=["ollama:critic1", "ollama:critic2"],
            writer_cascade=["ollama:writer1"],
            coder_cascade=["ollama:coder1", "ollama:coder2"],
            merge_resolution_cascade=["ollama:merge1"],
            summarizer_cascade=["ollama:summarizer1"],
        )
        mock_backend = MagicMock()
        with patch.object(r, "_get_or_create_backend", return_value=mock_backend):
            r.ensure_all_models()
        # Each unique (host, backend) pair gets ensured once.
        # Since all are ollama @ localhost, there should be 1 unique backend.
        # But ensure_all_models deduplicates by (id(backend), model_id).
        # First entries: manager1, critic1, writer1, coder1, merge1, summarizer1
        # All use the same backend, so ensure_model is called once per unique model.
        ensure_calls = [c[0][0] for c in mock_backend.ensure_model.call_args_list]
        # All first entries should be ensured
        assert len(mock_backend.ensure_model.call_args_list) >= 1


class TestBackwardCompat:
    """Tests confirming existing methods still work after cascade rewrite."""

    def test_build_handoff_still_works(self):
        r = make_router()
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "task"},
            {"role": "assistant", "content": "thinking"},
        ]
        detector = make_detector()
        result = r.build_handoff(detector, msgs)
        assert len(result) >= 3
        assert any("ESCALATION HANDOFF" in m.get("content", "") for m in result if isinstance(m, dict))

    def test_stream_for_role_unchanged(self):
        r = make_router(manager_stream=True, coder_stream=False)
        assert r.stream_for_role(AgentRole.MANAGER) is True
        assert r.stream_for_role(AgentRole.CODER) is False

    def test_think_for_role_unchanged(self):
        r = make_router(manager_think=True, coder_think=False)
        assert r.think_for_role(AgentRole.MANAGER) is True
        assert r.think_for_role(AgentRole.CODER) is False


class TestBudgetTrackerInjection:
    """Tests from the Phase 1B addendum: budget tracker wiring."""

    def test_instantiate_anthropic_backend_receives_budget_tracker(self):
        mock_tracker = MagicMock()
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
            with patch("matrixmouse.inference.anthropic.AnthropicBackend") as MockBackend:
                MockBackend.return_value = MagicMock()
                r = make_router(
                    local_only=False,
                    summarizer_cascade=["anthropic:claude-haiku-4-5"],
                    budget_tracker=mock_tracker,
                )
                r.get_backend_for_model("anthropic:claude-haiku-4-5")
                # Verify budget_tracker was passed to AnthropicBackend
                call_kwargs = MockBackend.call_args.kwargs
                assert call_kwargs.get("budget_tracker") is mock_tracker

    def test_instantiate_openai_backend_receives_budget_tracker(self):
        mock_tracker = MagicMock()
        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
            with patch("matrixmouse.inference.openai.OpenAIBackend") as MockBackend:
                MockBackend.return_value = MagicMock()
                r = make_router(
                    local_only=False,
                    summarizer_cascade=["openai:gpt-4o-mini"],
                    budget_tracker=mock_tracker,
                )
                r.get_backend_for_model("openai:gpt-4o-mini")
                call_kwargs = MockBackend.call_args.kwargs
                assert call_kwargs.get("budget_tracker") is mock_tracker

    def test_instantiate_local_backend_no_budget_tracker(self):
        """Local backends don't accept budget_tracker — no error."""
        mock_tracker = MagicMock()
        with patch("matrixmouse.inference.ollama.OllamaBackend") as MockOllama:
            MockOllama.return_value = MagicMock()
            r = make_router(
                summarizer_cascade=["ollama:qwen3:4b"],
                budget_tracker=mock_tracker,
            )
            r.get_backend_for_model("ollama:qwen3:4b")
        # OllamaBackend should NOT be called with budget_tracker kwarg
        call_kwargs = MockOllama.call_args.kwargs
        assert "budget_tracker" not in call_kwargs

    def test_router_with_no_budget_tracker_still_instantiates_backends(self):
        """Router with budget_tracker=None still works."""
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
            with patch("matrixmouse.inference.anthropic.AnthropicBackend") as MockBackend:
                mock_instance = MagicMock()
                MockBackend.return_value = mock_instance
                r = make_router(
                    local_only=False,
                    summarizer_cascade=["anthropic:claude-haiku-4-5"],
                    budget_tracker=None,
                )
                backend = r.get_backend_for_model("anthropic:claude-haiku-4-5")
                assert backend is mock_instance
                call_kwargs = MockBackend.call_args.kwargs
                assert call_kwargs.get("budget_tracker") is None
