"""
tests/test_context.py

Tests for matrixmouse.context — ContextManager and summarizer cascade (Issue #32).

Coverage:
    - Summarizer cascade walks entries, skips cooldown backends
    - Raises SummarizationUnavailableError when all entries exhausted
    - Does NOT modify message list when summarizer unavailable
    - Single entry cascade works
    - No availability cache → uses first entry directly
    - ContextManager construction with router/working_model/working_backend
    - Compression preserves system and instruction messages
    - SummarizationUnavailableError propagates through __call__
    - Working model used for context length (not hardcoded Coder model)
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from matrixmouse.config import MatrixMouseConfig, RepoPaths
from matrixmouse.context import ContextManager, estimate_tokens
from matrixmouse.inference.availability import BackendAvailabilityCache
from matrixmouse.inference.base import (
    LLMBackend, LLMResponse, SummarizationUnavailableError, TextBlock,
)
from matrixmouse.router import Router
from matrixmouse.repository.memory_workspace_state_repository import (
    InMemoryWorkspaceStateRepository,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_config(**kwargs) -> MatrixMouseConfig:
    return MatrixMouseConfig(**kwargs)


def make_response(text: str) -> LLMResponse:
    return LLMResponse(
        content=[TextBlock(text=text)],
        input_tokens=10,
        output_tokens=5,
        model="test-model",
        stop_reason="end_turn",
    )


def make_backend(**kwargs) -> MagicMock:
    """Create a mock LLMBackend."""
    backend = MagicMock(spec=LLMBackend)
    backend.get_context_length.return_value = kwargs.get("context_length", 32768)
    backend.chat.return_value = make_response(kwargs.get("chat_response", "summary text"))
    return backend


def make_router_for_context(
    summarizer_cascade: list[str],
    working_model_str: str = "ollama:working-model",
) -> MagicMock:
    """Create a mock Router with summarizer_cascade support."""
    router = MagicMock(spec=Router)
    router.summarizer_cascade.return_value = summarizer_cascade

    def get_backend_for_model(model_str):
        return make_backend()

    router.get_backend_for_model.side_effect = get_backend_for_model

    def parse_model_string(model_str):
        pm = MagicMock()
        parts = model_str.split(":")
        pm.backend = parts[0] if parts else "ollama"
        pm.model = parts[-1] if len(parts) > 1 else model_str
        pm.is_remote = pm.backend in ("anthropic", "openai")
        return pm

    router.parse_model_string = parse_model_string
    return router


def make_context_manager(
    working_model: str = "working-model",
    working_backend: LLMBackend | None = None,
    router: MagicMock | None = None,
    availability_cache: BackendAvailabilityCache | None = None,
    context_length: int = 32768,
) -> ContextManager:
    """Create a ContextManager with test-friendly defaults."""
    config = make_config(
        summarizer_cascade=["ollama:summarizer1"],
        coder_cascade=["ollama:coder1"],
        manager_cascade=["ollama:manager1"],
        critic_cascade=["ollama:critic1"],
        writer_cascade=["ollama:writer1"],
        merge_resolution_cascade=["ollama:merge1"],
        context_soft_limit=20000,
        compress_threshold=0.60,
        keep_last_n_turns=6,
    )
    paths = MagicMock()
    paths.mm_dir = Path("/tmp/test_mm")

    wb = working_backend or make_backend(context_length=context_length)
    r = router or make_router_for_context(["ollama:summarizer1"])

    return ContextManager(
        config=config,
        paths=paths,
        working_model=working_model,
        working_backend=wb,
        router=r,
        availability_cache=availability_cache,
    )


def make_messages(count: int = 10) -> list:
    """Create a list of messages for context testing."""
    msgs = [
        {"role": "system", "content": "You are an agent."},
        {"role": "user", "content": "Do the task."},
    ]
    for i in range(count):
        msgs.append({"role": "assistant", "content": f"Step {i}"})
        msgs.append({"role": "tool", "content": f"Result {i}"})
    return msgs


# ---------------------------------------------------------------------------
# Summarizer cascade
# ---------------------------------------------------------------------------

class TestSummarizerCascade:
    """Tests for summarizer cascade walking."""

    def test_summarizer_uses_first_available_entry(self):
        """First entry in summarizer_cascade is used when available."""
        router = make_router_for_context([
            "ollama:summarizer1", "ollama:summarizer2"
        ])
        ctx_mgr = make_context_manager(router=router)

        messages = make_messages(10)
        # Force compression by setting compress_at low
        ctx_mgr.compress_at = 1

        # Mock _save_discoveries_to_notes to avoid side effects
        with patch.object(ctx_mgr, "_save_discoveries_to_notes"):
            result = ctx_mgr._compress(messages)

        # Verify the first summarizer was used
        router.get_backend_for_model.assert_any_call("ollama:summarizer1")
        assert len(result) < len(messages)  # Was compressed

    def test_summarizer_skips_cooldown_backend(self):
        """First entry's backend in cooldown → second entry used."""
        ws_state_repo = InMemoryWorkspaceStateRepository()
        cache = BackendAvailabilityCache(ws_state_repo)
        cache.record_failure("anthropic")  # First summarizer's backend in cooldown

        router = make_router_for_context([
            "anthropic:claude-haiku", "ollama:summarizer2"
        ])
        ctx_mgr = make_context_manager(
            router=router,
            availability_cache=cache,
        )

        messages = make_messages(10)
        ctx_mgr.compress_at = 1

        with patch.object(ctx_mgr, "_save_discoveries_to_notes"):
            result = ctx_mgr._compress(messages)

        # First entry skipped, second entry used
        router.get_backend_for_model.assert_any_call("ollama:summarizer2")
        assert len(result) < len(messages)

    def test_summarizer_all_exhausted_raises_summarization_unavailable(self):
        """All entries in cooldown → SummarizationUnavailableError raised;
        NOT caught inside ContextManager."""
        ws_state_repo = InMemoryWorkspaceStateRepository()
        cache = BackendAvailabilityCache(ws_state_repo)
        cache.record_failure("ollama")  # All entries use ollama

        router = make_router_for_context([
            "ollama:summarizer1", "ollama:summarizer2"
        ])
        ctx_mgr = make_context_manager(
            router=router,
            availability_cache=cache,
        )

        messages = make_messages(10)
        ctx_mgr.compress_at = 1

        with patch.object(ctx_mgr, "_save_discoveries_to_notes"):
            with pytest.raises(SummarizationUnavailableError):
                ctx_mgr._compress(messages)

    def test_summarizer_all_exhausted_does_not_modify_messages(self):
        """Same scenario — message list is identical before and after
        (no partial compression, no appended strings, no mutation)."""
        ws_state_repo = InMemoryWorkspaceStateRepository()
        cache = BackendAvailabilityCache(ws_state_repo)
        cache.record_failure("ollama")

        router = make_router_for_context([
            "ollama:summarizer1", "ollama:summarizer2"
        ])
        ctx_mgr = make_context_manager(
            router=router,
            availability_cache=cache,
        )

        messages = make_messages(10)
        original_messages = [dict(m) for m in messages]  # Deep copy
        ctx_mgr.compress_at = 1

        with patch.object(ctx_mgr, "_save_discoveries_to_notes"):
            with pytest.raises(SummarizationUnavailableError):
                ctx_mgr._compress(messages)

        assert messages == original_messages

    def test_summarizer_single_entry_works(self):
        """Single entry cascade — works normally."""
        router = make_router_for_context(["ollama:summarizer1"])
        ctx_mgr = make_context_manager(router=router)

        messages = make_messages(10)
        ctx_mgr.compress_at = 1

        with patch.object(ctx_mgr, "_save_discoveries_to_notes"):
            result = ctx_mgr._compress(messages)

        router.get_backend_for_model.assert_called_with("ollama:summarizer1")
        assert len(result) < len(messages)

    def test_summarizer_no_cache_uses_first_entry(self):
        """No availability_cache → first entry used directly
        (no is_available check)."""
        router = make_router_for_context(["ollama:summarizer1"])
        ctx_mgr = make_context_manager(
            router=router,
            availability_cache=None,
        )

        messages = make_messages(10)
        ctx_mgr.compress_at = 1

        with patch.object(ctx_mgr, "_save_discoveries_to_notes"):
            result = ctx_mgr._compress(messages)

        router.get_backend_for_model.assert_called_with("ollama:summarizer1")
        assert len(result) < len(messages)


# ---------------------------------------------------------------------------
# ContextManager construction
# ---------------------------------------------------------------------------

class TestContextManagerConstruction:
    """Tests for ContextManager.__init__ with new parameters."""

    def test_context_manager_construction_with_router(self):
        """Construct with router; confirm token limit and compress_at set
        correctly using working_model/working_backend."""
        working_backend = make_backend(context_length=8192)
        router = make_router_for_context(["ollama:summarizer1"])
        ctx_mgr = make_context_manager(
            working_model="qwen3:4b",
            working_backend=working_backend,
            router=router,
        )

        # Token limit should be min(context_length, context_soft_limit)
        # context_length=8192, context_soft_limit=20000 → 8192
        assert ctx_mgr.token_limit == 8192
        assert ctx_mgr.compress_at == int(8192 * 0.60)

    def test_compress_preserves_system_and_instruction_messages(self):
        """Regression: shape of compressed output unchanged when
        summarisation succeeds."""
        ctx_mgr = make_context_manager()
        messages = make_messages(10)
        ctx_mgr.compress_at = 1

        with patch.object(ctx_mgr, "_save_discoveries_to_notes"):
            result = ctx_mgr._compress(messages)

        # System and instruction messages should be preserved
        assert result[0] == messages[0]  # system
        assert result[1] == messages[1]  # instruction
        # Summary message should be third
        assert "[CONTEXT SUMMARY" in result[2]["content"]


# ---------------------------------------------------------------------------
# SummarizationUnavailableError propagation
# ---------------------------------------------------------------------------

class TestSummarizationUnavailablePropagation:
    """Tests confirming SummarizationUnavailableError propagates
    through the full call chain."""

    def test_summarization_unavailable_propagates_through_call(self):
        """Mock all summarizer backends to be in cooldown, call
        ContextManager.__call__() on an oversized context, confirm
        SummarizationUnavailableError propagates out of __call__."""
        ws_state_repo = InMemoryWorkspaceStateRepository()
        cache = BackendAvailabilityCache(ws_state_repo)
        cache.record_failure("ollama")

        router = make_router_for_context(["ollama:summarizer1"])
        ctx_mgr = make_context_manager(
            router=router,
            availability_cache=cache,
        )

        messages = make_messages(10)
        ctx_mgr.compress_at = 1

        with patch.object(ctx_mgr, "_save_discoveries_to_notes"):
            with pytest.raises(SummarizationUnavailableError):
                ctx_mgr(messages, make_config())

    def test_working_model_used_for_context_length(self):
        """Construct with a Manager-sized model; confirm
        get_context_length is called with that model's identifier,
        not a Coder's."""
        working_backend = make_backend(context_length=128000)
        router = make_router_for_context(["ollama:summarizer1"])
        ctx_mgr = make_context_manager(
            working_model="claude-sonnet-4-5",
            working_backend=working_backend,
            router=router,
        )

        # get_context_length should have been called during construction
        working_backend.get_context_length.assert_called_with("claude-sonnet-4-5")
