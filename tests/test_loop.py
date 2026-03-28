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
from matrixmouse.inference.base import (
    LLMResponse, TextBlock, ThinkingBlock, ToolUseBlock, Tool,
)
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

def make_backend(response: "LLMResponse | None" = None) -> "MagicMock":
    """Return a mock LLMBackend whose chat() returns the given response.
 
    If no response is provided, returns a default single-TextBlock response
    so loops don't crash on missing content.
    """
    from matrixmouse.inference.base import LLMResponse, TextBlock
    backend = MagicMock()
    backend.chat.return_value = response or LLMResponse(
        content=[TextBlock(text="default response")],
        input_tokens=10,
        output_tokens=5,
        model="test-model",
        stop_reason="end_turn",
    )
    return backend
 
 
def make_response(
    text: str = "",
    thinking: str = "",
    tool_calls: "list[ToolUseBlock] | None" = None,
    stop_reason: str = "end_turn",
) -> "LLMResponse":
    """Build a fake LLMResponse for use in tests.
 
    Replaces both make_chunk() and make_batch_response() — the loop no
    longer distinguishes between streaming and batch at the return type level.
 
    Args:
        text: Text content for the response.
        thinking: Thinking content (produces a ThinkingBlock).
        tool_calls: List of ToolUseBlock entries.
        stop_reason: Normalised stop reason string.
 
    Returns:
        LLMResponse with the appropriate content blocks.
    """
    from matrixmouse.inference.base import (
        LLMResponse, TextBlock, ThinkingBlock, ToolUseBlock,
    )
    content = []
    if thinking:
        content.append(ThinkingBlock(text=thinking))
    if text:
        content.append(TextBlock(text=text))
    if tool_calls:
        content.extend(tool_calls)
    if not content:
        content.append(TextBlock(text=""))
    effective_stop = "tool_use" if tool_calls else stop_reason
    return LLMResponse(
        content=content,
        input_tokens=10,
        output_tokens=5,
        model="test-model",
        stop_reason=effective_stop,
    )
 
 
def make_tool_use_block(
    name: str,
    arguments: dict,
    id: str = "call_test",
) -> "ToolUseBlock":
    """Build a ToolUseBlock for use in test responses.
 
    Replaces make_declare_complete_call() and any ad-hoc MagicMock tool
    call construction that accessed .function.name / .function.arguments.
 
    Args:
        name: Tool name.
        arguments: Tool input dict.
        id: Tool call ID (defaults to a stable test value).
 
    Returns:
        ToolUseBlock.
    """
    from matrixmouse.inference.base import ToolUseBlock
    return ToolUseBlock(id=id, name=name, input=arguments)
 
 
def make_declare_complete_call() -> "ToolUseBlock":
    """ToolUseBlock that triggers declare_complete."""
    return make_tool_use_block(
        name="declare_complete",
        arguments={"summary": "all done"},
        id="call_declare",
    )
 
 
def make_loop(
    stream: bool = True,
    think: bool = False,
    emit=None,
    messages=None,
    backend=None,
) -> "AgentLoop":
    """Construct an AgentLoop with minimal dependencies for unit testing."""
    return AgentLoop(
        backend=backend or make_backend(),
        model="test-model",
        messages=messages or [{"role": "user", "content": "do something"}],
        config=make_config(),
        paths=MagicMock(),
        emit=emit,
        stream=stream,
        think=think,
    )
 
 
def make_loop_full(
    stream: bool = True,
    think: bool = False,
    emit=None,
    messages=None,
    persist=None,
    should_yield=None,
    backend=None,
) -> "AgentLoop":
    """Construct an AgentLoop with all callables injectable."""
    return AgentLoop(
        backend=backend or make_backend(),
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


def make_loop_with_limit(task_turn_limit=0, agent_max_turns=50, **kwargs):
    """Construct an AgentLoop with turn limit configuration for testing."""
    cfg = MatrixMouseConfig(agent_max_turns=agent_max_turns)
    backend = kwargs.pop("backend", MagicMock())
    messages = kwargs.pop("messages", [{"role": "user", "content": "do something"}])
    return AgentLoop(
        backend=backend,
        model="test-model",
        messages=messages,
        config=cfg,
        paths=MagicMock(),
        stream=False,
        task_turn_limit=task_turn_limit,
        **kwargs,
    )

# ---------------------------------------------------------------------------
# Chat Completion
# ---------------------------------------------------------------------------


class TestChatCompletion:
    """Tests for the unified _chat_completion() path."""
 
    def test_non_streaming_calls_backend_with_stream_false(self):
        """When stream=False, backend.chat is called with stream=False."""
        response = make_response(text="result")
        backend = make_backend(response)
        loop = make_loop(stream=False, backend=backend)
 
        result = loop._chat_completion()
 
        backend.chat.assert_called_once()
        _, kwargs = backend.chat.call_args
        assert kwargs["stream"] is False
        assert kwargs["think"] is False
 
    def test_streaming_calls_backend_with_stream_true(self):
        """When stream=True, backend.chat is called with stream=True."""
        response = make_response(text="result")
        backend = make_backend(response)
        loop = make_loop(stream=True, backend=backend)
 
        loop._chat_completion()
 
        _, kwargs = backend.chat.call_args
        assert kwargs["stream"] is True
 
    def test_streaming_wires_chunk_callback(self):
        """When stream=True, a chunk_callback is passed to backend.chat."""
        response = make_response(text="hello")
        backend = make_backend(response)
        loop = make_loop(stream=True, backend=backend)
 
        loop._chat_completion()
 
        _, kwargs = backend.chat.call_args
        assert kwargs["chunk_callback"] is not None
        assert callable(kwargs["chunk_callback"])
 
    def test_non_streaming_passes_no_chunk_callback(self):
        """When stream=False, chunk_callback is None."""
        response = make_response(text="result")
        backend = make_backend(response)
        loop = make_loop(stream=False, backend=backend)
 
        loop._chat_completion()
 
        _, kwargs = backend.chat.call_args
        assert kwargs["chunk_callback"] is None
 
    def test_chunk_callback_emits_token_events(self):
        """chunk_callback forwards text to self._emit as 'token' events."""
        emitted = []
 
        def fake_emit(event_type, data):
            emitted.append((event_type, data))
 
        response = make_response(text="hi")
        backend = make_backend(response)
        loop = make_loop(stream=True, emit=fake_emit, backend=backend)
 
        # Capture the callback and invoke it manually
        loop._chat_completion()
        _, kwargs = backend.chat.call_args
        cb = kwargs["chunk_callback"]
        cb("token_text")
 
        assert ("token", {"text": "token_text"}) in emitted
 
    def test_think_flag_forwarded_to_backend(self):
        """think=True is passed through to backend.chat."""
        response = make_response(text="thoughts")
        backend = make_backend(response)
        loop = make_loop(stream=False, think=True, backend=backend)
 
        loop._chat_completion()
 
        _, kwargs = backend.chat.call_args
        assert kwargs["think"] is True
 
    def test_returns_llm_response(self):
        """_chat_completion returns the LLMResponse from backend.chat."""
        from matrixmouse.inference.base import LLMResponse
        response = make_response(text="result")
        backend = make_backend(response)
        loop = make_loop(stream=False, backend=backend)
 
        result = loop._chat_completion()
 
        assert isinstance(result, LLMResponse)
 
    def test_tools_passed_to_backend(self):
        """The loop's tool list is forwarded to backend.chat."""
        from matrixmouse.inference.base import Tool
        fake_tool = Tool(fn=lambda: None, schema={"name": "fake", "input_schema": {}})
        response = make_response(text="ok")
        backend = make_backend(response)
        loop = make_loop(stream=False, backend=backend)
        loop._tools = [fake_tool]
 
        loop._chat_completion()
 
        _, kwargs = backend.chat.call_args
        assert kwargs["tools"] == [fake_tool]
 
    def test_response_with_tool_use_block(self):
        """A response containing a ToolUseBlock is returned correctly."""
        from matrixmouse.inference.base import ToolUseBlock
        tool_block = make_tool_use_block("read_file", {"filename": "foo.py"})
        response = make_response(tool_calls=[tool_block])
        backend = make_backend(response)
        loop = make_loop(stream=False, backend=backend)
 
        result = loop._chat_completion()
 
        tool_blocks = [b for b in result.content if isinstance(b, ToolUseBlock)]
        assert len(tool_blocks) == 1
        assert tool_blocks[0].name == "read_file"
 
    def test_response_with_thinking_block(self):
        """A response containing a ThinkingBlock is returned correctly."""
        from matrixmouse.inference.base import ThinkingBlock
        response = make_response(thinking="let me think", text="answer")
        backend = make_backend(response)
        loop = make_loop(stream=False, think=True, backend=backend)
 
        result = loop._chat_completion()
 
        thinking_blocks = [b for b in result.content if isinstance(b, ThinkingBlock)]
        assert len(thinking_blocks) == 1
        assert thinking_blocks[0].text == "let me think"


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
    def test_persist_called_after_inference(self):
        persist = MagicMock()
        backend = MagicMock()
        backend.chat.return_value = make_response(
            tool_calls=[make_declare_complete_call()]
        )
        loop = make_loop_full(persist=persist, stream=False, backend=backend)
 
        loop.run()
 
        assert persist.called
        first_call_messages = persist.call_args_list[0][0][0]
        assert isinstance(first_call_messages, list)
 
    def test_persist_called_after_tool_result(self):
        persist = MagicMock()
        backend = MagicMock()
 
        read_file_call = make_tool_use_block(
            "read_file", {"filename": "foo.py"}, id="call_read"
        )
        backend.chat.side_effect = [
            make_response(tool_calls=[read_file_call]),
            make_response(tool_calls=[make_declare_complete_call()]),
        ]
 
        loop = make_loop_full(persist=persist, stream=False, backend=backend)
 
        from matrixmouse.inference.base import Tool
        fake_tool = Tool(fn=lambda filename: "file content", schema={"name": "read_file", "input_schema": {}})
        with patch.dict("matrixmouse.tools.TOOL_REGISTRY", {"read_file": fake_tool}):
            loop.run()
 
        # persist called at least twice: after model response, after tool result
        assert persist.call_count >= 2
 
    def test_persist_stored_when_provided(self):
        persist = MagicMock()
        loop = make_loop_full(persist=persist)
        assert loop._persist is persist

    def test_persist_defaults_to_noop(self):
        loop = make_loop_full(persist=None)
        assert loop._persist is _noop_persist

    def test_noop_persist_accepts_any_messages(self):
        _noop_persist([])
        _noop_persist([{"role": "user", "content": "hi"}])

    def test_noop_persist_returns_none(self):
        assert _noop_persist([]) is None


# ---------------------------------------------------------------------------
# should_yield callable
# ---------------------------------------------------------------------------


class TestShouldYieldCallable:
    def test_yield_signal_causes_yield_exit(self):
        call_count = 0
 
        def yield_after_one():
            nonlocal call_count
            call_count += 1
            return call_count >= 1
 
        backend = MagicMock()
        backend.chat.return_value = make_response(text="thinking...")
        loop = make_loop_full(
            stream=False,
            should_yield=yield_after_one,
            backend=backend,
        )
 
        result = loop.run()
 
        assert result.exit_reason == LoopExitReason.YIELD
 
    def test_yield_result_contains_messages(self):
        backend = MagicMock()
        backend.chat.return_value = make_response(text="hi")
        loop = make_loop_full(
            stream=False,
            should_yield=lambda: True,
            backend=backend,
        )
 
        result = loop.run()
 
        assert isinstance(result.messages, list)
        assert len(result.messages) > 0
 
    def test_yield_result_contains_turns_taken(self):
        backend = MagicMock()
        backend.chat.return_value = make_response(text="hi")
        loop = make_loop_full(
            stream=False,
            should_yield=lambda: True,
            backend=backend,
        )
 
        result = loop.run()
 
        assert result.turns_taken == 1
 
    def test_no_yield_when_should_yield_false(self):
        backend = MagicMock()
        backend.chat.return_value = make_response(
            tool_calls=[make_declare_complete_call()]
        )
        loop = make_loop_full(
            stream=False,
            should_yield=lambda: False,
            backend=backend,
        )
 
        result = loop.run()
 
        assert result.exit_reason == LoopExitReason.COMPLETE
 
    def test_yield_checked_after_tool_dispatch(self):
        """Yield should not fire before tools are executed."""
        dispatched = []
 
        def my_tool(**kwargs):
            dispatched.append(True)
            return "ok"
 
        my_tool_call = make_tool_use_block("my_tool", {}, id="call_my_tool")
 
        backend = MagicMock()
        backend.chat.return_value = make_response(tool_calls=[my_tool_call])
 
        loop = make_loop_full(
            stream=False,
            should_yield=lambda: True,
            backend=backend,
        )
 
        from matrixmouse.inference.base import Tool
        fake_tool = Tool(fn=my_tool, schema={"name": "my_tool", "input_schema": {}})
        with patch.dict("matrixmouse.tools.TOOL_REGISTRY", {"my_tool": fake_tool}):
            result = loop.run()
 
        assert dispatched, "Tool should have been dispatched before yield"
        assert result.exit_reason == LoopExitReason.YIELD
 
 
    def test_should_yield_stored_when_provided(self):
        should_yield = MagicMock(return_value=False)
        loop = make_loop_full(should_yield=should_yield)
        assert loop._should_yield is should_yield

    def test_should_yield_defaults_to_noop(self):
        loop = make_loop_full(should_yield=None)
        assert loop._should_yield is _noop_should_yield

    def test_noop_should_yield_returns_false(self):
        assert _noop_should_yield() is False


# ---------------------------------------------------------------------------
# turn_limit_reached
# ---------------------------------------------------------------------------


class TestTurnLimit:
    def test_task_turn_limit_stored(self):
        loop = make_loop_with_limit(task_turn_limit=25)
        assert loop._task_turn_limit == 25
 
    def test_uses_task_turn_limit_when_set(self):
        """When task_turn_limit > 0 it overrides config.agent_max_turns."""
        backend = MagicMock()
        backend.chat.return_value = make_response(text="thinking")
        loop = make_loop_with_limit(
            task_turn_limit=2, agent_max_turns=50, backend=backend,
        )
 
        result = loop.run()
 
        assert result.exit_reason == LoopExitReason.DECISION
        assert result.turns_taken == 2
 
    def test_falls_back_to_config_when_task_limit_is_zero(self):
        """When task_turn_limit == 0, config.agent_max_turns is used."""
        backend = MagicMock()
        backend.chat.return_value = make_response(text="thinking")
        loop = make_loop_with_limit(
            task_turn_limit=0, agent_max_turns=2, backend=backend,
        )
 
        result = loop.run()
 
        assert result.exit_reason == LoopExitReason.DECISION
        assert result.turns_taken == 2
 
    def test_turn_limit_reached_exit_reason(self):
        backend = MagicMock()
        backend.chat.return_value = make_response(text="thinking")
        loop = make_loop_with_limit(task_turn_limit=1, backend=backend)
 
        result = loop.run()
 
        assert result.exit_reason == LoopExitReason.DECISION
 
    def test_turn_limit_result_contains_messages(self):
        backend = MagicMock()
        backend.chat.return_value = make_response(text="thinking")
        loop = make_loop_with_limit(task_turn_limit=1, backend=backend)
 
        result = loop.run()
 
        assert isinstance(result.messages, list)
        assert len(result.messages) > 0
 
    def test_does_not_trigger_before_limit(self):
        """Task completes normally before hitting the limit."""
        backend = MagicMock()
        backend.chat.return_value = make_response(
            tool_calls=[make_declare_complete_call()]
        )
        loop = make_loop_with_limit(task_turn_limit=10, backend=backend)
 
        result = loop.run()
 
        assert result.exit_reason == LoopExitReason.COMPLETE
 
    def test_turn_limit_decision_payload(self):
        """turn_limit_reached decision payload contains turns_taken and turn_limit."""
        backend = MagicMock()
        backend.chat.return_value = make_response(text="thinking")
        loop = make_loop_with_limit(task_turn_limit=3, backend=backend)
 
        result = loop.run()
 
        assert result.decision_type == "turn_limit_reached"
        assert result.decision_payload["turns_taken"] == 3
        assert result.decision_payload["turn_limit"] == 3

    def test_default_task_turn_limit_is_zero(self):
        loop = make_loop_full()
        assert loop._task_turn_limit == 0

    def test_allowed_tools_parameter_stored(self):
        """allowed_tools frozenset is accepted without error."""
        loop = AgentLoop(
            backend=make_backend(),
            model="test-model",
            messages=[{"role": "user", "content": "go"}],
            config=make_config(),
            paths=MagicMock(),
            allowed_tools=frozenset({"read_file", "declare_complete"}),
            stream=False,
        )
        assert loop._allowed_tools == frozenset({"read_file", "declare_complete"})

    def test_disallowed_tool_returns_error_not_exception(self):
        backend = MagicMock()
        loop = AgentLoop(
            backend=backend,
            model="test-model",
            messages=[{"role": "user", "content": "go"}],
            config=make_config(),
            paths=MagicMock(),
            allowed_tools=frozenset({"declare_complete"}),
            stream=False,
        )
        disallowed = make_tool_use_block("read_file", {"path": "foo.py"})
        response1 = make_response(tool_calls=[disallowed])
        response2 = make_response(tool_calls=[make_declare_complete_call()])
        backend.chat.side_effect = [response1, response2]
        result = loop.run()
    
        assert result.exit_reason == LoopExitReason.COMPLETE
        tool_messages = [
            m for m in result.messages
            if isinstance(m, dict) and m.get("role") == "tool"
        ]
        assert any(
            "not permitted" in m.get("content", "").lower()
            or "allowed_tools" in m.get("content", "").lower()
            for m in tool_messages
        )