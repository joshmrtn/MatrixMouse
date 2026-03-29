"""
tests/inference/test_anthropic_backend.py

Unit tests for AnthropicBackend-specific functionality.

Tests:
    - _split_system extracts system message, leaves conversation
    - _split_system concatenates multiple system messages
    - _to_anthropic_messages wraps tool results as user messages with tool_result block
    - chat() raises TokenBudgetExceededError on 429
    - chat() raises TokenBudgetExceededError on 529
    - chat() calls budget_tracker.check_budget before request
    - chat() calls budget_tracker.record after success
    - chat() does not call budget_tracker when tracker is None
    - get_context_length returns 200000 for known models
    - get_context_length returns default for unknown models
    - _parse_retry_after extracts Retry-After header as timedelta
    - _parse_retry_after returns None when no relevant headers
    - _assemble_response builds correct LLMResponse
    - _parse_response handles Anthropic response format
    - _chat_blocking makes correct POST request with headers
    - _chat_streaming handles SSE format correctly
"""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch, call

import pytest
import requests

from matrixmouse.inference.base import (
    LLMResponse,
    TextBlock,
    ThinkingBlock,
    ToolUseBlock,
    Tool,
    ModelNotAvailableError,
    BackendConnectionError,
    LLMBackendError,
    TokenBudgetExceededError,
)
from matrixmouse.inference.anthropic import (
    AnthropicBackend,
    _translate_schema,
    _parse_retry_after,
    _STOP_REASON_MAP,
    _CONTEXT_LENGTHS,
    _DEFAULT_CONTEXT_LENGTH,
)
from matrixmouse.inference.token_budget import TokenBudgetTracker


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def anthropic_backend():
    """Create an AnthropicBackend instance."""
    return AnthropicBackend(api_key="test-key")


@pytest.fixture
def anthropic_backend_with_budget():
    """Create an AnthropicBackend instance with a mock budget tracker."""
    mock_tracker = MagicMock(spec=TokenBudgetTracker)
    return AnthropicBackend(api_key="test-key", budget_tracker=mock_tracker)


def make_tool(name: str = "test_tool") -> Tool:
    """Create a simple test tool."""
    def dummy_fn(x: int) -> int:
        return x

    return Tool(
        fn=dummy_fn,
        schema={
            "name": name,
            "description": "A test tool",
            "input_schema": {
                "type": "object",
                "properties": {
                    "x": {"type": "integer", "description": "A number"}
                },
                "required": ["x"],
            },
        },
    )


def make_anthropic_response(
    content: str = "hello",
    tool_calls: list | None = None,
    thinking: str = "",
    input_tokens: int = 10,
    output_tokens: int = 5,
) -> dict:
    """Build a fake Anthropic /v1/messages response dict."""
    content_blocks = []
    if thinking:
        content_blocks.append({
            "type": "thinking",
            "thinking": thinking,
        })
    if content:
        content_blocks.append({
            "type": "text",
            "text": content,
        })
    if tool_calls:
        for tc in tool_calls:
            content_blocks.append({
                "type": "tool_use",
                "id": tc.get("id", "call_test"),
                "name": tc.get("name", "test_tool"),
                "input": tc.get("input", {}),
            })
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "content": content_blocks,
        "model": "claude-sonnet-4-5",
        "stop_reason": "tool_use" if tool_calls else "end_turn",
        "stop_sequence": None,
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        },
    }


# ---------------------------------------------------------------------------
# _translate_schema tests
# ---------------------------------------------------------------------------


class TestTranslateSchema:
    """Tests for the _translate_schema helper function."""

    def test_translates_schema_to_anthropic_format(self):
        tool = make_tool("read_file")
        result = _translate_schema(tool)

        assert result["name"] == "read_file"
        assert result["description"] == "A test tool"
        assert "input_schema" in result
        assert result["input_schema"]["type"] == "object"

    def test_handles_missing_description(self):
        tool = Tool(
            fn=lambda: None,
            schema={
                "name": "simple_tool",
                "input_schema": {"type": "object"},
            },
        )
        result = _translate_schema(tool)

        assert result["description"] == ""

    def test_handles_missing_input_schema(self):
        tool = Tool(
            fn=lambda: None,
            schema={
                "name": "bare_tool",
                "description": "No schema",
            },
        )
        result = _translate_schema(tool)

        assert result["input_schema"] == {}


# ---------------------------------------------------------------------------
# _split_system tests
# ---------------------------------------------------------------------------


class TestSplitSystem:
    """Tests for AnthropicBackend._split_system static method."""

    def test_extracts_system_message(self):
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello"},
        ]
        system, conversation = AnthropicBackend._split_system(messages)

        assert system == "You are helpful."
        assert len(conversation) == 1
        assert conversation[0]["role"] == "user"

    def test_leaves_conversation_intact(self):
        messages = [
            {"role": "system", "content": "Be helpful."},
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello!"},
        ]
        _, conversation = AnthropicBackend._split_system(messages)

        assert len(conversation) == 2
        assert conversation[0]["role"] == "user"
        assert conversation[1]["role"] == "assistant"

    def test_concatenates_multiple_system_messages(self):
        messages = [
            {"role": "system", "content": "First instruction."},
            {"role": "system", "content": "Second instruction."},
            {"role": "user", "content": "Hi"},
        ]
        system, conversation = AnthropicBackend._split_system(messages)

        assert system == "First instruction.\n\nSecond instruction."
        assert len(conversation) == 1

    def test_handles_missing_system_message(self):
        messages = [
            {"role": "user", "content": "Hello"},
        ]
        system, conversation = AnthropicBackend._split_system(messages)

        assert system == ""
        assert len(conversation) == 1

    def test_handles_empty_messages(self):
        system, conversation = AnthropicBackend._split_system([])

        assert system == ""
        assert conversation == []

    def test_handles_non_string_system_content(self):
        messages = [
            {"role": "system", "content": ["block1", "block2"]},
            {"role": "user", "content": "Hi"},
        ]
        system, conversation = AnthropicBackend._split_system(messages)

        # Non-string content is skipped
        assert system == ""
        assert len(conversation) == 1


# ---------------------------------------------------------------------------
# _to_anthropic_messages tests
# ---------------------------------------------------------------------------


class TestToAnthropicMessages:
    """Tests for AnthropicBackend._to_anthropic_messages static method."""

    def test_passes_through_user_messages_unchanged(self):
        messages = [
            {"role": "user", "content": "Hello"},
        ]
        result = AnthropicBackend._to_anthropic_messages(messages)

        assert result == messages

    def test_passes_through_assistant_messages_unchanged(self):
        messages = [
            {"role": "assistant", "content": "Hi there!"},
        ]
        result = AnthropicBackend._to_anthropic_messages(messages)

        assert result == messages

    def test_wraps_tool_results_as_user_message_with_tool_result_block(self):
        messages = [
            {
                "role": "tool",
                "tool_use_id": "call_abc123",
                "content": "File contents here",
            },
        ]
        result = AnthropicBackend._to_anthropic_messages(messages)

        assert len(result) == 1
        assert result[0]["role"] == "user"
        assert isinstance(result[0]["content"], list)
        assert result[0]["content"][0]["type"] == "tool_result"
        assert result[0]["content"][0]["tool_use_id"] == "call_abc123"
        assert result[0]["content"][0]["content"] == "File contents here"

    def test_handles_missing_tool_use_id(self):
        messages = [
            {"role": "tool", "content": "Result"},
        ]
        result = AnthropicBackend._to_anthropic_messages(messages)

        assert result[0]["content"][0]["tool_use_id"] == ""

    def test_handles_missing_tool_content(self):
        messages = [
            {"role": "tool", "tool_use_id": "call_abc"},
        ]
        result = AnthropicBackend._to_anthropic_messages(messages)

        assert result[0]["content"][0]["content"] == ""

    def test_handles_mixed_message_types(self):
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi!"},
            {"role": "tool", "tool_use_id": "call_1", "content": "result"},
            {"role": "user", "content": "Thanks"},
        ]
        result = AnthropicBackend._to_anthropic_messages(messages)

        assert len(result) == 4
        assert result[0]["role"] == "user"
        assert result[1]["role"] == "assistant"
        assert result[2]["role"] == "user"  # tool result wrapped
        assert result[3]["role"] == "user"


# ---------------------------------------------------------------------------
# get_context_length tests
# ---------------------------------------------------------------------------


class TestGetContextLength:
    """Tests for AnthropicBackend.get_context_length method."""

    def test_returns_200000_for_known_models(self, anthropic_backend):
        for model in _CONTEXT_LENGTHS.keys():
            result = anthropic_backend.get_context_length(model)
            assert result == 200_000, f"Expected 200000 for {model}"

    def test_returns_200000_for_claude_sonnet_4_5(self, anthropic_backend):
        result = anthropic_backend.get_context_length("claude-sonnet-4-5")
        assert result == 200_000

    def test_returns_200000_for_claude_opus_4_5(self, anthropic_backend):
        result = anthropic_backend.get_context_length("claude-opus-4-5")
        assert result == 200_000

    def test_returns_default_for_unknown_models(self, anthropic_backend):
        result = anthropic_backend.get_context_length("unknown-model")
        assert result == _DEFAULT_CONTEXT_LENGTH

    def test_prefix_match_for_versioned_strings(self, anthropic_backend):
        # Model with suffix that starts with known model
        result = anthropic_backend.get_context_length("claude-sonnet-4-5-20241022")
        assert result == 200_000

    def test_reverse_prefix_match(self, anthropic_backend):
        # Known model that starts with the query
        result = anthropic_backend.get_context_length("claude-3")
        # Should match claude-3-* models
        assert result == 200_000


# ---------------------------------------------------------------------------
# _parse_retry_after tests
# ---------------------------------------------------------------------------


class TestParseRetryAfter:
    """Tests for the _parse_retry_after helper function."""

    def test_extracts_retry_after_seconds_as_timedelta(self):
        mock_response = MagicMock()
        mock_response.headers = {"Retry-After": "60"}

        result = _parse_retry_after(mock_response)

        assert result is not None
        # Should be approximately 60 seconds from now
        expected_min = datetime.now(timezone.utc) + timedelta(seconds=59)
        expected_max = datetime.now(timezone.utc) + timedelta(seconds=61)
        assert expected_min <= result <= expected_max

    def test_extracts_iso_timestamp_from_x_ratelimit_reset_tokens(self):
        future_time = datetime.now(timezone.utc) + timedelta(minutes=5)
        mock_response = MagicMock()
        mock_response.headers = {"x-ratelimit-reset-tokens": future_time.isoformat()}

        result = _parse_retry_after(mock_response)

        assert result is not None
        # Should be close to the specified time
        assert abs((result - future_time).total_seconds()) < 1

    def test_extracts_iso_timestamp_from_x_ratelimit_reset_requests(self):
        future_time = datetime.now(timezone.utc) + timedelta(minutes=5)
        mock_response = MagicMock()
        mock_response.headers = {"x-ratelimit-reset-requests": future_time.isoformat()}

        result = _parse_retry_after(mock_response)

        assert result is not None
        assert abs((result - future_time).total_seconds()) < 1

    def test_x_ratelimit_headers_take_priority_over_retry_after(self):
        future_time = datetime.now(timezone.utc) + timedelta(minutes=5)
        mock_response = MagicMock()
        mock_response.headers = {
            "x-ratelimit-reset-tokens": future_time.isoformat(),
            "Retry-After": "3600",  # 1 hour
        }

        result = _parse_retry_after(mock_response)

        # Should use the x-ratelimit-reset-tokens value (5 min), not Retry-After (1 hour)
        assert result is not None
        assert abs((result - future_time).total_seconds()) < 1

    def test_returns_none_when_no_relevant_headers(self):
        mock_response = MagicMock()
        mock_response.headers = {"Content-Type": "application/json"}

        result = _parse_retry_after(mock_response)

        assert result is None

    def test_returns_none_when_response_is_none(self):
        result = _parse_retry_after(None)
        assert result is None

    def test_returns_none_on_invalid_iso_timestamp(self):
        mock_response = MagicMock()
        mock_response.headers = {"x-ratelimit-reset-tokens": "not-a-date"}

        result = _parse_retry_after(mock_response)

        assert result is None

    def test_returns_none_on_invalid_retry_after_value(self):
        mock_response = MagicMock()
        mock_response.headers = {"Retry-After": "not-a-number"}

        result = _parse_retry_after(mock_response)

        assert result is None

    def test_adds_utc_timezone_if_missing(self):
        # ISO timestamp without timezone
        mock_response = MagicMock()
        mock_response.headers = {"x-ratelimit-reset-tokens": "2026-04-01T12:00:00"}

        result = _parse_retry_after(mock_response)

        assert result is not None
        assert result.tzinfo is not None


# ---------------------------------------------------------------------------
# chat() budget tracker tests
# ---------------------------------------------------------------------------


class TestChatBudgetTracker:
    """Tests for AnthropicBackend.chat() budget tracker integration."""

    def test_calls_check_budget_before_request(self, anthropic_backend_with_budget):
        with patch("requests.post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: make_anthropic_response("hello"),
            )
            mock_post.return_value.raise_for_status = lambda: None

            anthropic_backend_with_budget.chat(
                model="claude-sonnet-4-5",
                messages=[{"role": "user", "content": "Hi"}],
                tools=[],
                stream=False,
            )

        budget_tracker = anthropic_backend_with_budget._budget_tracker
        budget_tracker.check_budget.assert_called_once_with(
            provider="anthropic",
            model="claude-sonnet-4-5",
        )

    def test_calls_record_after_success(self, anthropic_backend_with_budget):
        with patch("requests.post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: make_anthropic_response(
                    "hello", input_tokens=100, output_tokens=50
                ),
            )
            mock_post.return_value.raise_for_status = lambda: None

            anthropic_backend_with_budget.chat(
                model="claude-sonnet-4-5",
                messages=[{"role": "user", "content": "Hi"}],
                tools=[],
                stream=False,
            )

        budget_tracker = anthropic_backend_with_budget._budget_tracker
        budget_tracker.record.assert_called_once_with(
            provider="anthropic",
            model="claude-sonnet-4-5",
            input_tokens=100,
            output_tokens=50,
        )

    def test_does_not_call_budget_tracker_when_tracker_is_none(self, anthropic_backend):
        with patch("requests.post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: make_anthropic_response("hello"),
            )
            mock_post.return_value.raise_for_status = lambda: None

            anthropic_backend.chat(
                model="claude-sonnet-4-5",
                messages=[{"role": "user", "content": "Hi"}],
                tools=[],
                stream=False,
            )

        # No budget tracker, so no calls should be made
        assert True  # Test passes if no exception

    def test_raises_token_budget_exceeded_error_on_429(self, anthropic_backend):
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.headers = {}
        
        with patch("requests.post") as mock_post:
            mock_post.return_value = mock_response
            mock_post.return_value.raise_for_status.side_effect = requests.HTTPError(response=mock_response)

            with pytest.raises(TokenBudgetExceededError) as exc_info:
                anthropic_backend.chat(
                    model="claude-sonnet-4-5",
                    messages=[],
                    tools=[],
                    stream=False,
                )

        assert exc_info.value.provider == "anthropic"
        assert exc_info.value.period == "hour"

    def test_raises_token_budget_exceeded_error_on_529(self, anthropic_backend):
        mock_response = MagicMock()
        mock_response.status_code = 529
        mock_response.headers = {}
        
        with patch("requests.post") as mock_post:
            mock_post.return_value = mock_response
            mock_post.return_value.raise_for_status.side_effect = requests.HTTPError(response=mock_response)

            with pytest.raises(TokenBudgetExceededError) as exc_info:
                anthropic_backend.chat(
                    model="claude-sonnet-4-5",
                    messages=[],
                    tools=[],
                    stream=False,
                )

        assert exc_info.value.provider == "anthropic"


# ---------------------------------------------------------------------------
# _assemble_response tests
# ---------------------------------------------------------------------------


class TestAssembleResponse:
    """Tests for AnthropicBackend._assemble_response method."""

    def test_assembles_text_content(self, anthropic_backend):
        result = anthropic_backend._assemble_response(
            accumulated_text="hello world",
            accumulated_thinking="",
            tool_calls=[],
            input_tokens=10,
            output_tokens=5,
            model="claude-sonnet-4-5",
            stop_reason="end_turn",
        )

        assert isinstance(result, LLMResponse)
        assert len(result.content) == 1
        assert isinstance(result.content[0], TextBlock)
        assert result.content[0].text == "hello world"
        assert result.input_tokens == 10
        assert result.output_tokens == 5
        assert result.model == "claude-sonnet-4-5"
        assert result.stop_reason == "end_turn"

    def test_assembles_thinking_content(self, anthropic_backend):
        result = anthropic_backend._assemble_response(
            accumulated_text="answer",
            accumulated_thinking="let me think about this...",
            tool_calls=[],
            input_tokens=10,
            output_tokens=5,
            model="claude-sonnet-4-5",
            stop_reason="end_turn",
        )

        assert len(result.content) == 2
        assert isinstance(result.content[0], ThinkingBlock)
        assert result.content[0].text == "let me think about this..."
        assert isinstance(result.content[1], TextBlock)

    def test_assembles_tool_calls(self, anthropic_backend):
        tool_call = {
            "id": "call_abc123",
            "name": "test_tool",
            "input": {"x": 42},
        }
        result = anthropic_backend._assemble_response(
            accumulated_text="",
            accumulated_thinking="",
            tool_calls=[tool_call],
            input_tokens=10,
            output_tokens=5,
            model="claude-sonnet-4-5",
            stop_reason="end_turn",
        )

        assert len(result.content) == 1
        assert isinstance(result.content[0], ToolUseBlock)
        assert result.content[0].id == "call_abc123"
        assert result.content[0].name == "test_tool"
        assert result.content[0].input == {"x": 42}

    def test_overrides_stop_reason_to_tool_use_when_tool_calls_present(self, anthropic_backend):
        tool_call = {
            "id": "call_abc",
            "name": "tool",
            "input": {},
        }
        result = anthropic_backend._assemble_response(
            accumulated_text="",
            accumulated_thinking="",
            tool_calls=[tool_call],
            input_tokens=10,
            output_tokens=5,
            model="claude-sonnet-4-5",
            stop_reason="end_turn",
        )

        assert result.stop_reason == "tool_use"

    def test_orders_content_thinking_text_tools(self, anthropic_backend):
        tool_call = {"id": "call_1", "name": "tool", "input": {}}
        result = anthropic_backend._assemble_response(
            accumulated_text="answer",
            accumulated_thinking="thinking...",
            tool_calls=[tool_call],
            input_tokens=10,
            output_tokens=5,
            model="claude-sonnet-4-5",
            stop_reason="end_turn",
        )

        assert isinstance(result.content[0], ThinkingBlock)
        assert isinstance(result.content[1], TextBlock)
        assert isinstance(result.content[2], ToolUseBlock)


# ---------------------------------------------------------------------------
# _parse_response tests
# ---------------------------------------------------------------------------


class TestParseResponse:
    """Tests for AnthropicBackend._parse_response method."""

    def test_parses_standard_response(self, anthropic_backend):
        data = make_anthropic_response("hello world")
        result = anthropic_backend._parse_response(data)

        assert isinstance(result, LLMResponse)
        assert result.model == "claude-sonnet-4-5"
        assert isinstance(result.content[0], TextBlock)
        assert result.content[0].text == "hello world"
        assert result.input_tokens == 10
        assert result.output_tokens == 5
        assert result.stop_reason == "end_turn"

    def test_parses_thinking_content(self, anthropic_backend):
        data = make_anthropic_response("answer", thinking="let me think...")
        result = anthropic_backend._parse_response(data)

        assert len(result.content) == 2
        assert isinstance(result.content[0], ThinkingBlock)
        assert result.content[0].text == "let me think..."

    def test_parses_tool_calls(self, anthropic_backend):
        tool_call = {
            "id": "call_abc",
            "name": "test_tool",
            "input": {"x": 42},
        }
        data = make_anthropic_response("", [tool_call])
        result = anthropic_backend._parse_response(data)

        assert isinstance(result.content[0], ToolUseBlock)
        assert result.content[0].name == "test_tool"
        assert result.content[0].input == {"x": 42}
        assert result.stop_reason == "tool_use"

    def test_parses_string_input_as_json(self, anthropic_backend):
        tool_call = {
            "id": "call_abc",
            "name": "test_tool",
            "input": '{"x": 42}',  # String instead of dict
        }
        data = make_anthropic_response("", [tool_call])
        result = anthropic_backend._parse_response(data)

        assert result.content[0].input == {"x": 42}

    def test_handles_invalid_json_input_gracefully(self, anthropic_backend):
        tool_call = {
            "id": "call_abc",
            "name": "test_tool",
            "input": "not valid json{",
        }
        data = make_anthropic_response("", [tool_call])
        result = anthropic_backend._parse_response(data)

        assert result.content[0].input == {}

    def test_maps_stop_reasons_correctly(self, anthropic_backend):
        for anthropic_reason, expected_reason in _STOP_REASON_MAP.items():
            data = make_anthropic_response("test")
            data["stop_reason"] = anthropic_reason
            result = anthropic_backend._parse_response(data)
            assert result.stop_reason == expected_reason, \
                f"Expected {expected_reason} for {anthropic_reason}"

    def test_handles_missing_fields_gracefully(self, anthropic_backend):
        data = {}
        result = anthropic_backend._parse_response(data)

        assert result.model == ""
        assert result.content == []
        assert result.input_tokens == 0
        assert result.output_tokens == 0
        assert result.stop_reason == "end_turn"


# ---------------------------------------------------------------------------
# _chat_blocking tests
# ---------------------------------------------------------------------------


class TestChatBlocking:
    """Tests for AnthropicBackend._chat_blocking method."""

    def test_makes_post_request_to_v1_messages(self, anthropic_backend):
        payload = {"model": "claude-sonnet-4-5", "messages": []}
        with patch("requests.post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: make_anthropic_response("test"),
            )
            mock_post.return_value.raise_for_status = lambda: None

            anthropic_backend._chat_blocking(
                "https://api.anthropic.com/v1/messages",
                payload,
            )

            mock_post.assert_called_once()
            call_args = mock_post.call_args
            assert call_args[0][0] == "https://api.anthropic.com/v1/messages"
            assert call_args[1]["json"] == payload

    def test_includes_auth_headers(self, anthropic_backend):
        payload = {"model": "claude-sonnet-4-5", "messages": []}
        with patch("requests.post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: make_anthropic_response("test"),
            )
            mock_post.return_value.raise_for_status = lambda: None

            anthropic_backend._chat_blocking(
                "https://api.anthropic.com/v1/messages",
                payload,
            )

            headers = mock_post.call_args[1]["headers"]
            assert headers["x-api-key"] == "test-key"
            assert headers["anthropic-version"] == "2023-06-01"
            assert headers["content-type"] == "application/json"

    def test_uses_120_second_timeout(self, anthropic_backend):
        payload = {"model": "claude-sonnet-4-5", "messages": []}
        with patch("requests.post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: make_anthropic_response("test"),
            )
            mock_post.return_value.raise_for_status = lambda: None

            anthropic_backend._chat_blocking(
                "https://api.anthropic.com/v1/messages",
                payload,
            )

            assert mock_post.call_args[1]["timeout"] == 120


# ---------------------------------------------------------------------------
# _chat_streaming tests
# ---------------------------------------------------------------------------


class TestChatStreaming:
    """Tests for AnthropicBackend._chat_streaming method."""

    def test_calls_callback_for_each_text_delta(self, anthropic_backend):
        mock_callback = MagicMock()
        stream_lines = [
            b'data: {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "hello"}}',
            b'data: {"type": "content_block_delta", "delta": {"type": "text_delta", "text": " world"}}',
            b'data: {"type": "message_delta", "delta": {"stop_reason": "end_turn"}}',
        ]

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.iter_lines.return_value = stream_lines
        mock_response.__enter__ = lambda self: self
        mock_response.__exit__ = lambda self, *args: None

        with patch("requests.post", return_value=mock_response):
            anthropic_backend._chat_streaming(
                "https://api.anthropic.com/v1/messages",
                {"model": "claude-sonnet-4-5", "messages": []},
                mock_callback,
            )

        assert mock_callback.call_count == 2
        mock_callback.assert_any_call("hello")
        mock_callback.assert_any_call(" world")

    def test_accumulates_thinking_content(self, anthropic_backend):
        mock_callback = MagicMock()
        stream_lines = [
            b'data: {"type": "content_block_delta", "delta": {"type": "thinking_delta", "thinking": "let me "}}',
            b'data: {"type": "content_block_delta", "delta": {"type": "thinking_delta", "thinking": "think..."}}',
            b'data: {"type": "message_delta", "delta": {"stop_reason": "end_turn"}}',
        ]

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.iter_lines.return_value = stream_lines
        mock_response.__enter__ = lambda self: self
        mock_response.__exit__ = lambda self, *args: None

        with patch("requests.post", return_value=mock_response):
            result = anthropic_backend._chat_streaming(
                "https://api.anthropic.com/v1/messages",
                {"model": "claude-sonnet-4-5", "messages": []},
                mock_callback,
            )

        thinking_block = next((b for b in result.content if isinstance(b, ThinkingBlock)), None)
        assert thinking_block is not None
        assert thinking_block.text == "let me think..."

    def test_accumulates_tool_call_input_json_deltas(self, anthropic_backend):
        """Streaming path accumulates tool call input_json_delta strings."""
        mock_callback = MagicMock()
        # Build proper JSON event strings
        chunk1 = json.dumps({
            "type": "content_block_start",
            "content_block": {"type": "tool_use", "id": "call_1", "name": "test_tool"},
        }).encode()
        chunk2 = json.dumps({
            "type": "content_block_delta",
            "delta": {"type": "input_json_delta", "partial_json": '{"x":'},
        }).encode()
        chunk3 = json.dumps({
            "type": "content_block_delta",
            "delta": {"type": "input_json_delta", "partial_json": '42}'},
        }).encode()
        chunk4 = json.dumps({"type": "content_block_stop"}).encode()
        chunk5 = json.dumps({"type": "message_delta", "delta": {"stop_reason": "tool_use"}}).encode()
        
        stream_lines = [
            b'data: ' + chunk1,
            b'data: ' + chunk2,
            b'data: ' + chunk3,
            b'data: ' + chunk4,
            b'data: ' + chunk5,
        ]

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.iter_lines.return_value = stream_lines
        mock_response.__enter__ = lambda self: self
        mock_response.__exit__ = lambda self, *args: None

        with patch("requests.post", return_value=mock_response):
            result = anthropic_backend._chat_streaming(
                "https://api.anthropic.com/v1/messages",
                {"model": "claude-sonnet-4-5", "messages": []},
                mock_callback,
            )

        tool_blocks = [b for b in result.content if isinstance(b, ToolUseBlock)]
        assert len(tool_blocks) == 1
        assert tool_blocks[0].name == "test_tool"
        # Note: streaming path accumulates partial_json as string (not parsed)
        assert tool_blocks[0].input == '{"x":42}'

    def test_extracts_usage_from_message_delta(self, anthropic_backend):
        mock_callback = MagicMock()
        stream_lines = [
            b'data: {"type": "message_start", "message": {"model": "claude-sonnet-4-5", "usage": {"input_tokens": 100}}}',
            b'data: {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "test"}}',
            b'data: {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 50}}',
        ]

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.iter_lines.return_value = stream_lines
        mock_response.__enter__ = lambda self: self
        mock_response.__exit__ = lambda self, *args: None

        with patch("requests.post", return_value=mock_response):
            result = anthropic_backend._chat_streaming(
                "https://api.anthropic.com/v1/messages",
                {"model": "claude-sonnet-4-5", "messages": []},
                mock_callback,
            )

        assert result.input_tokens == 100
        assert result.output_tokens == 50

    def test_extracts_model_from_message_start(self, anthropic_backend):
        mock_callback = MagicMock()
        stream_lines = [
            b'data: {"type": "message_start", "message": {"model": "claude-opus-4-5", "usage": {}}}',
            b'data: {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "test"}}',
            b'data: {"type": "message_delta", "delta": {"stop_reason": "end_turn"}}',
        ]

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.iter_lines.return_value = stream_lines
        mock_response.__enter__ = lambda self: self
        mock_response.__exit__ = lambda self, *args: None

        with patch("requests.post", return_value=mock_response):
            result = anthropic_backend._chat_streaming(
                "https://api.anthropic.com/v1/messages",
                {"model": "claude-sonnet-4-5", "messages": []},
                mock_callback,
            )

        assert result.model == "claude-opus-4-5"


# ---------------------------------------------------------------------------
# is_model_available tests
# ---------------------------------------------------------------------------


class TestIsModelAvailable:
    """Tests for AnthropicBackend.is_model_available method."""

    def test_returns_true_for_non_empty_model_string(self, anthropic_backend):
        assert anthropic_backend.is_model_available("claude-sonnet-4-5") is True
        assert anthropic_backend.is_model_available("any-model") is True

    def test_returns_false_for_empty_model_string(self, anthropic_backend):
        assert anthropic_backend.is_model_available("") is False


# ---------------------------------------------------------------------------
# list_models tests
# ---------------------------------------------------------------------------


class TestListModels:
    """Tests for AnthropicBackend.list_models method."""

    def test_returns_context_length_keys(self, anthropic_backend):
        result = anthropic_backend.list_models()

        assert isinstance(result, list)
        assert len(result) == len(_CONTEXT_LENGTHS)
        assert set(result) == set(_CONTEXT_LENGTHS.keys())


# ---------------------------------------------------------------------------
# ensure_model tests
# ---------------------------------------------------------------------------


class TestEnsureModel:
    """Tests for AnthropicBackend.ensure_model method."""

    def test_is_no_op(self, anthropic_backend):
        # Should not raise
        anthropic_backend.ensure_model("claude-sonnet-4-5")
        anthropic_backend.ensure_model("any-model")
