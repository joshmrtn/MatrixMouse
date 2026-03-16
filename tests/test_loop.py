"""
tests/test_loop.py

Tests for matrixmouse.loop — focusing on the streaming and batch inference
paths added in feature/streaming.

Coverage:
    - _chat_completion dispatches correctly based on self.stream
    - _chat_completion_batch passes correct arguments to ollama.chat
    - _chat_completion_stream accumulates content, thinking, tool_calls
    - _chat_completion_stream emits token and thinking events for respective chunk types
    - _chat_completion_stream returns correct response shape
    - _chat_completion_stream returns tool_calls=None when none present
    - think flag passed through in both batch and stream paths
    - _noop_emit is used when no emit callable is provided
    - Full loop run emits tokens and completes correctly (integration)
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch, call

import pytest

from matrixmouse.loop import (
    AgentLoop,
    LoopExitReason,
    LoopResult,
    _noop_emit,
    _noop_persist,
    _noop_should_yield,
)
from matrixmouse.config import MatrixMouseConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_config(**kwargs):
    """Return a MatrixMouseConfig with test-friendly defaults."""
    return MatrixMouseConfig(**kwargs)


def make_loop(stream=True, think=False, emit=None, messages=None):
    """Construct an AgentLoop with minimal dependencies for unit testing."""
    return AgentLoop(
        model="test-model",
        messages=messages or [{"role": "user", "content": "do something"}],
        config=make_config(),
        paths=MagicMock(),
        emit=emit,
        stream=stream,
        think=think,
    )


def make_chunk(content="", thinking="", tool_calls=None):
    """Build a fake ollama streaming chunk."""
    msg = SimpleNamespace(
        content=content,
        thinking=thinking,
        tool_calls=tool_calls,
    )
    return SimpleNamespace(message=msg)


def make_batch_response(content="", thinking="", tool_calls=None):
    """Build a fake ollama non-streaming response."""
    msg = SimpleNamespace(
        content=content,
        thinking=thinking,
        tool_calls=tool_calls,
    )
    return SimpleNamespace(message=msg)


def make_loop_full(
    stream=True, think=False, emit=None, messages=None, persist=None, should_yield=None
):
    """Construct an AgentLoop with all Phase A callables injectable."""
    return AgentLoop(
        model="test-model",
        messages=messages or [{"role": "user", "content": "do something"}],
        config=make_config(),
        paths=MagicMock(),
        emit=emit,
        persist=persist,
        should_yield=should_yield,
        stream=stream,
        think=think,
    )


def make_declare_complete_call():
    """Fake tool call that triggers declare_complete."""
    call = MagicMock()
    call.function.name = "declare_complete"
    call.function.arguments = {"summary": "all done"}
    return call


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


class TestDispatch:
    def test_stream_true_calls_stream_path(self):
        loop = make_loop(stream=True)
        with (
            patch.object(loop, "_chat_completion_stream") as mock_stream,
            patch.object(loop, "_chat_completion_batch") as mock_batch,
        ):
            mock_stream.return_value = make_batch_response("hi")
            loop._chat_completion()
            mock_stream.assert_called_once()
            mock_batch.assert_not_called()

    def test_stream_false_calls_batch_path(self):
        loop = make_loop(stream=False)
        with (
            patch.object(loop, "_chat_completion_stream") as mock_stream,
            patch.object(loop, "_chat_completion_batch") as mock_batch,
        ):
            mock_batch.return_value = make_batch_response("hi")
            loop._chat_completion()
            mock_batch.assert_called_once()
            mock_stream.assert_not_called()


# ---------------------------------------------------------------------------
# Batch path
# ---------------------------------------------------------------------------


class TestBatchCompletion:
    def test_calls_ollama_with_stream_false(self):
        loop = make_loop(stream=False, think=False)
        with patch("matrixmouse.loop.ollama.chat") as mock_chat:
            mock_chat.return_value = make_batch_response("result")
            loop._chat_completion_batch()
        _, kwargs = mock_chat.call_args
        assert kwargs["stream"] is False

    def test_passes_think_false(self):
        loop = make_loop(stream=False, think=False)
        with patch("matrixmouse.loop.ollama.chat") as mock_chat:
            mock_chat.return_value = make_batch_response()
            loop._chat_completion_batch()
        _, kwargs = mock_chat.call_args
        assert kwargs["think"] is False

    def test_passes_think_true(self):
        loop = make_loop(stream=False, think=True)
        with patch("matrixmouse.loop.ollama.chat") as mock_chat:
            mock_chat.return_value = make_batch_response()
            loop._chat_completion_batch()
        _, kwargs = mock_chat.call_args
        assert kwargs["think"] is True

    def test_passes_model(self):
        loop = make_loop(stream=False)
        with patch("matrixmouse.loop.ollama.chat") as mock_chat:
            mock_chat.return_value = make_batch_response()
            loop._chat_completion_batch()
        _, kwargs = mock_chat.call_args
        assert kwargs["model"] == "test-model"

    def test_returns_response_directly(self):
        loop = make_loop(stream=False)
        expected = make_batch_response("hello")
        with patch("matrixmouse.loop.ollama.chat", return_value=expected):
            result = loop._chat_completion_batch()
        assert result is expected


# ---------------------------------------------------------------------------
# Stream path — accumulation
# ---------------------------------------------------------------------------


class TestStreamAccumulation:
    def test_accumulates_content_across_chunks(self):
        loop = make_loop(stream=True)
        chunks = [
            make_chunk(content="Hello"),
            make_chunk(content=", "),
            make_chunk(content="world"),
        ]
        with patch("matrixmouse.loop.ollama.chat", return_value=iter(chunks)):
            result = loop._chat_completion_stream()
        assert result.message.content == "Hello, world"

    def test_accumulates_thinking_across_chunks(self):
        loop = make_loop(stream=True, think=True)
        chunks = [
            make_chunk(thinking="step one "),
            make_chunk(thinking="step two"),
            make_chunk(content="answer"),
        ]
        with patch("matrixmouse.loop.ollama.chat", return_value=iter(chunks)):
            result = loop._chat_completion_stream()
        assert result.message.thinking == "step one step two"

    def test_accumulates_tool_calls_across_chunks(self):
        loop = make_loop(stream=True)
        call1 = MagicMock()
        call2 = MagicMock()
        chunks = [
            make_chunk(tool_calls=[call1]),
            make_chunk(content="some text"),
            make_chunk(tool_calls=[call2]),
        ]
        with patch("matrixmouse.loop.ollama.chat", return_value=iter(chunks)):
            result = loop._chat_completion_stream()
        assert result.message.tool_calls == [call1, call2]

    def test_tool_calls_none_when_absent(self):
        loop = make_loop(stream=True)
        chunks = [make_chunk(content="no tools here")]
        with patch("matrixmouse.loop.ollama.chat", return_value=iter(chunks)):
            result = loop._chat_completion_stream()
        assert result.message.tool_calls is None

    def test_empty_stream_returns_empty_fields(self):
        loop = make_loop(stream=True)
        with patch("matrixmouse.loop.ollama.chat", return_value=iter([])):
            result = loop._chat_completion_stream()
        assert result.message.content == ""
        assert result.message.thinking == ""
        assert result.message.tool_calls is None


# ---------------------------------------------------------------------------
# Stream path — response shape
# ---------------------------------------------------------------------------


class TestStreamResponseShape:
    def test_response_has_message_attribute(self):
        loop = make_loop(stream=True)
        chunks = [make_chunk(content="hi")]
        with patch("matrixmouse.loop.ollama.chat", return_value=iter(chunks)):
            result = loop._chat_completion_stream()
        assert hasattr(result, "message")

    def test_message_has_content(self):
        loop = make_loop(stream=True)
        chunks = [make_chunk(content="hello")]
        with patch("matrixmouse.loop.ollama.chat", return_value=iter(chunks)):
            result = loop._chat_completion_stream()
        assert hasattr(result.message, "content")
        assert result.message.content == "hello"

    def test_message_has_thinking(self):
        loop = make_loop(stream=True)
        chunks = [make_chunk(thinking="reasoning")]
        with patch("matrixmouse.loop.ollama.chat", return_value=iter(chunks)):
            result = loop._chat_completion_stream()
        assert hasattr(result.message, "thinking")

    def test_message_has_tool_calls(self):
        loop = make_loop(stream=True)
        chunks = [make_chunk(content="done")]
        with patch("matrixmouse.loop.ollama.chat", return_value=iter(chunks)):
            result = loop._chat_completion_stream()
        assert hasattr(result.message, "tool_calls")


# ---------------------------------------------------------------------------
# Stream path — token emission
# ---------------------------------------------------------------------------


class TestTokenEmission:
    def test_emits_token_for_each_content_chunk(self):
        emitted = []
        loop = make_loop(stream=True, emit=lambda t, d: emitted.append((t, d)))
        chunks = [
            make_chunk(content="foo"),
            make_chunk(content="bar"),
            make_chunk(content="baz"),
        ]
        with patch("matrixmouse.loop.ollama.chat", return_value=iter(chunks)):
            loop._chat_completion_stream()
        assert len(emitted) == 3
        assert all(t == "token" for t, _ in emitted)
        assert [d["text"] for _, d in emitted] == ["foo", "bar", "baz"]

    def test_emits_thinking_event_for_thinking_chunks(self):
        emitted = []
        loop = make_loop(stream=True, emit=lambda t, d: emitted.append((t, d)))
        chunks = [
            make_chunk(thinking="internal reasoning"),
            make_chunk(content="final answer"),
        ]
        with patch("matrixmouse.loop.ollama.chat", return_value=iter(chunks)):
            loop._chat_completion_stream()
        thinking_events = [(t, d) for t, d in emitted if t == "thinking"]
        token_events = [(t, d) for t, d in emitted if t == "token"]
        assert len(thinking_events) == 1
        assert thinking_events[0] == ("thinking", {"text": "internal reasoning"})
        assert len(token_events) == 1
        assert token_events[0] == ("token", {"text": "final answer"})

    def test_does_not_emit_for_tool_call_chunks(self):
        emitted = []
        loop = make_loop(stream=True, emit=lambda t, d: emitted.append((t, d)))
        tool_call = MagicMock()
        chunks = [
            make_chunk(tool_calls=[tool_call]),
        ]
        with patch("matrixmouse.loop.ollama.chat", return_value=iter(chunks)):
            loop._chat_completion_stream()
        assert len(emitted) == 0

    def test_no_emit_when_no_callable_provided(self):
        """Loop uses _noop_emit when emit=None — no error raised."""
        loop = make_loop(stream=True, emit=None)
        chunks = [make_chunk(content="hello")]
        with patch("matrixmouse.loop.ollama.chat", return_value=iter(chunks)):
            result = loop._chat_completion_stream()
        assert result.message.content == "hello"

    def test_emit_callable_stored_as_noop_when_none(self):
        loop = make_loop(emit=None)
        assert loop._emit is _noop_emit

    def test_emit_callable_stored_when_provided(self):
        my_emit = lambda t, d: None
        loop = make_loop(emit=my_emit)
        assert loop._emit is my_emit


# ---------------------------------------------------------------------------
# Think flag passthrough
# ---------------------------------------------------------------------------


class TestThinkFlag:
    def test_stream_passes_think_true(self):
        loop = make_loop(stream=True, think=True)
        chunks = [make_chunk(content="done")]
        with patch(
            "matrixmouse.loop.ollama.chat", return_value=iter(chunks)
        ) as mock_chat:
            loop._chat_completion_stream()
        _, kwargs = mock_chat.call_args
        assert kwargs["think"] is True

    def test_stream_passes_think_false(self):
        loop = make_loop(stream=True, think=False)
        chunks = [make_chunk(content="done")]
        with patch(
            "matrixmouse.loop.ollama.chat", return_value=iter(chunks)
        ) as mock_chat:
            loop._chat_completion_stream()
        _, kwargs = mock_chat.call_args
        assert kwargs["think"] is False


# ---------------------------------------------------------------------------
# _noop_emit
# ---------------------------------------------------------------------------


class TestNoopEmit:
    def test_accepts_any_args(self):
        """_noop_emit must not raise regardless of input."""
        _noop_emit("token", {"text": "hello"})
        _noop_emit("status_update", {})
        _noop_emit("unknown_type", {"arbitrary": "data"})

    def test_returns_none(self):
        assert _noop_emit("token", {}) is None


# ---------------------------------------------------------------------------
# persist callable
# ---------------------------------------------------------------------------


class TestPersistCallable:
    def test_persist_stored_when_provided(self):
        persist = MagicMock()
        loop = make_loop_full(persist=persist)
        assert loop._persist is persist

    def test_persist_defaults_to_noop(self):
        loop = make_loop_full(persist=None)
        assert loop._persist is _noop_persist

    def test_persist_called_after_inference(self):
        persist = MagicMock()
        loop = make_loop_full(persist=persist, stream=False)

        response = make_batch_response(tool_calls=[make_declare_complete_call()])
        with patch("matrixmouse.loop.ollama.chat", return_value=response):
            loop.run()

        assert persist.called
        # First call is after appending model response
        first_call_messages = persist.call_args_list[0][0][0]
        assert isinstance(first_call_messages, list)

    def test_persist_called_after_tool_result(self):
        persist = MagicMock()

        # First turn: model calls a real tool, second turn: declare_complete
        tool_call = MagicMock()
        tool_call.function.name = "read_file"
        tool_call.function.arguments = {"path": "foo.py"}

        response1 = make_batch_response(tool_calls=[tool_call])
        response2 = make_batch_response(tool_calls=[make_declare_complete_call()])

        loop = make_loop_full(persist=persist, stream=False)

        with (
            patch("matrixmouse.loop.ollama.chat", side_effect=[response1, response2]),
            patch.dict(
                "matrixmouse.loop.TOOL_REGISTRY",
                {"read_file": lambda path: "file content"},
            ),
        ):
            loop.run()

        # persist should have been called at least twice:
        # once after model response, once after tool result
        assert persist.call_count >= 2

    def test_noop_persist_accepts_any_messages(self):
        _noop_persist([])
        _noop_persist([{"role": "user", "content": "hi"}])

    def test_noop_persist_returns_none(self):
        assert _noop_persist([]) is None


# ---------------------------------------------------------------------------
# should_yield callable
# ---------------------------------------------------------------------------


class TestShouldYieldCallable:
    def test_should_yield_stored_when_provided(self):
        should_yield = MagicMock(return_value=False)
        loop = make_loop_full(should_yield=should_yield)
        assert loop._should_yield is should_yield

    def test_should_yield_defaults_to_noop(self):
        loop = make_loop_full(should_yield=None)
        assert loop._should_yield is _noop_should_yield

    def test_yield_signal_causes_yield_exit(self):
        # should_yield returns True after first turn
        call_count = 0

        def yield_after_one():
            nonlocal call_count
            call_count += 1
            return call_count >= 1

        loop = make_loop_full(
            stream=False,
            should_yield=yield_after_one,
        )
        response = make_batch_response(content="thinking...")
        with patch("matrixmouse.loop.ollama.chat", return_value=response):
            result = loop.run()

        assert result.exit_reason == LoopExitReason.YIELD

    def test_yield_result_contains_messages(self):
        loop = make_loop_full(
            stream=False,
            should_yield=lambda: True,
        )
        response = make_batch_response(content="hi")
        with patch("matrixmouse.loop.ollama.chat", return_value=response):
            result = loop.run()

        assert isinstance(result.messages, list)
        assert len(result.messages) > 0

    def test_yield_result_contains_turns_taken(self):
        loop = make_loop_full(
            stream=False,
            should_yield=lambda: True,
        )
        response = make_batch_response(content="hi")
        with patch("matrixmouse.loop.ollama.chat", return_value=response):
            result = loop.run()

        assert result.turns_taken == 1

    def test_no_yield_when_should_yield_false(self):
        loop = make_loop_full(
            stream=False,
            should_yield=lambda: False,
        )
        response = make_batch_response(tool_calls=[make_declare_complete_call()])
        with patch("matrixmouse.loop.ollama.chat", return_value=response):
            result = loop.run()

        assert result.exit_reason == LoopExitReason.COMPLETE

    def test_yield_checked_after_tool_dispatch(self):
        """Yield should not fire before tools are executed."""
        dispatched = []

        def my_tool(**kwargs):
            dispatched.append(True)
            return "ok"

        tool_call = MagicMock()
        tool_call.function.name = "my_tool"
        tool_call.function.arguments = {}

        # yield on first check — but tool should still have run
        loop = make_loop_full(
            stream=False,
            should_yield=lambda: True,
        )
        response = make_batch_response(tool_calls=[tool_call])
        with (
            patch("matrixmouse.loop.ollama.chat", return_value=response),
            patch.dict("matrixmouse.loop.TOOL_REGISTRY", {"my_tool": my_tool}),
        ):
            result = loop.run()

        assert dispatched, "Tool should have been dispatched before yield"
        assert result.exit_reason == LoopExitReason.YIELD

    def test_noop_should_yield_returns_false(self):
        assert _noop_should_yield() is False
