"""
tests/inference/test_openai_backend.py

Unit tests for OpenAIBackend-specific functionality.

Tests:
    - _to_openai_messages serialises tool_use input as JSON string
    - _to_openai_messages drops ThinkingBlock
    - chat() raises TokenBudgetExceededError on 429
    - chat() calls budget_tracker.check_budget before request
    - chat() calls budget_tracker.record after success
    - _parse_retry_after checks x-ratelimit-reset-tokens first
    - _parse_retry_after falls back to Retry-After seconds header
    - get_context_length returns correct value for gpt-4o (128k)
    - _assemble_response builds correct LLMResponse
    - _parse_response handles OpenAI response format
    - _chat_blocking makes correct POST request with headers
    - _chat_streaming handles SSE format correctly
"""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

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
from matrixmouse.inference.openai import (
    OpenAIBackend,
    _translate_schema,
    _parse_retry_after,
    _STOP_REASON_MAP,
    _CONTEXT_LENGTHS,
    _DEFAULT_CONTEXT_LENGTH,
)
from matrixmouse.inference.token_budget import TokenBudgetTracker
from matrixmouse.inference.openai_compat import to_openai_messages, finalise_tool_calls


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def openai_backend():
    """Create an OpenAIBackend instance."""
    return OpenAIBackend(api_key="test-key")


@pytest.fixture
def openai_backend_with_budget():
    """Create an OpenAIBackend instance with a mock budget tracker."""
    mock_tracker = MagicMock(spec=TokenBudgetTracker)
    return OpenAIBackend(api_key="test-key", budget_tracker=mock_tracker)


@pytest.fixture
def openai_backend_custom_base():
    """Create an OpenAIBackend instance with custom base URL."""
    return OpenAIBackend(api_key="test-key", base_url="https://custom.api.com")


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


def make_openai_response(
    content: str = "hello",
    tool_calls: list | None = None,
    finish_reason: str = "stop",
    input_tokens: int = 10,
    output_tokens: int = 5,
) -> dict:
    """Build a fake OpenAI /v1/chat/completions response dict."""
    message = {
        "role": "assistant",
        "content": content,
    }
    if tool_calls:
        message["tool_calls"] = tool_calls # type: ignore[assignment]

    choices = [{
        "index": 0,
        "message": message,
        "finish_reason": finish_reason,
    }]
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 1234567890,
        "model": "gpt-4o",
        "choices": choices,
        "usage": {
            "prompt_tokens": input_tokens,
            "completion_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        },
    }


# ---------------------------------------------------------------------------
# _translate_schema tests
# ---------------------------------------------------------------------------


class TestTranslateSchema:
    """Tests for the _translate_schema helper function."""

    def test_translates_schema_to_openai_format(self):
        tool = make_tool("read_file")
        result = _translate_schema(tool)

        assert result["type"] == "function"
        assert result["function"]["name"] == "read_file"
        assert result["function"]["description"] == "A test tool"
        assert "parameters" in result["function"]
        assert result["function"]["parameters"]["type"] == "object"

    def test_handles_missing_description(self):
        tool = Tool(
            fn=lambda: None,
            schema={
                "name": "simple_tool",
                "input_schema": {"type": "object"},
            },
        )
        result = _translate_schema(tool)

        assert result["function"]["description"] == ""

    def test_handles_missing_input_schema(self):
        tool = Tool(
            fn=lambda: None,
            schema={
                "name": "bare_tool",
                "description": "No schema",
            },
        )
        result = _translate_schema(tool)

        assert result["function"]["parameters"] == {}


# ---------------------------------------------------------------------------
# to_openai_messages tests (ThinkingBlock handling)
# ---------------------------------------------------------------------------


class TestToOpenaiMessages:
    """Tests for to_openai_messages from openai_compat (used by OpenAIBackend)."""

    def test_serialises_tool_use_input_as_json_string(self):
        """_to_openai_messages serialises tool_use input as JSON string."""
        messages = [
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "call_abc",
                        "name": "test_tool",
                        "input": {"x": 42, "y": "hello"},
                    }
                ],
            }
        ]
        result = to_openai_messages(messages)

        # Tool calls should be in the message
        assert len(result) == 1
        tool_call = result[0]["tool_calls"][0]
        assert tool_call["function"]["name"] == "test_tool"
        # Input should be JSON string
        assert isinstance(tool_call["function"]["arguments"], str)
        assert json.loads(tool_call["function"]["arguments"]) == {"x": 42, "y": "hello"}

    def test_drops_thinking_block(self):
        """_to_openai_messages drops ThinkingBlock."""
        messages = [
            {
                "role": "assistant",
                "content": [
                    {"type": "thinking", "text": "let me think..."},
                    {"type": "text", "text": "answer"},
                ],
            }
        ]
        result = to_openai_messages(messages)

        # Thinking block should be dropped, only text remains
        assert len(result) == 1
        assert result[0]["content"] == "answer"

    def test_passes_through_system_messages_unchanged(self):
        messages = [
            {"role": "system", "content": "You are helpful."},
        ]
        result = to_openai_messages(messages)
        assert result == messages

    def test_passes_through_user_messages_unchanged(self):
        messages = [
            {"role": "user", "content": "Hello"},
        ]
        result = to_openai_messages(messages)
        assert result == messages

    def test_handles_plain_string_assistant_content(self):
        messages = [
            {"role": "assistant", "content": "Hello there!"},
        ]
        result = to_openai_messages(messages)
        assert result == messages

    def test_translates_tool_use_id_to_tool_call_id(self):
        """_to_openai_messages translates tool_use_id → tool_call_id."""
        messages = [
            {
                "role": "tool",
                "tool_use_id": "call_abc123",
                "content": "Result here",
            }
        ]
        result = to_openai_messages(messages)

        assert len(result) == 1
        assert result[0]["role"] == "tool"
        assert result[0]["tool_call_id"] == "call_abc123"


# ---------------------------------------------------------------------------
# get_context_length tests
# ---------------------------------------------------------------------------


class TestGetContextLength:
    """Tests for OpenAIBackend.get_context_length method."""

    def test_returns_correct_value_for_gpt_4o(self, openai_backend):
        """get_context_length returns correct value for gpt-4o (128k)."""
        result = openai_backend.get_context_length("gpt-4o")
        assert result == 128_000

    def test_returns_128k_for_gpt_4o_mini(self, openai_backend):
        result = openai_backend.get_context_length("gpt-4o-mini")
        assert result == 128_000

    def test_returns_128k_for_gpt_4_turbo(self, openai_backend):
        result = openai_backend.get_context_length("gpt-4-turbo")
        assert result == 128_000

    def test_returns_8192_for_gpt_4(self, openai_backend):
        result = openai_backend.get_context_length("gpt-4")
        assert result == 8_192

    def test_returns_32768_for_gpt_4_32k(self, openai_backend):
        result = openai_backend.get_context_length("gpt-4-32k")
        assert result == 32_768

    def test_returns_200k_for_o1(self, openai_backend):
        result = openai_backend.get_context_length("o1")
        assert result == 200_000

    def test_returns_200k_for_o3_mini(self, openai_backend):
        result = openai_backend.get_context_length("o3-mini")
        assert result == 200_000

    def test_returns_default_for_unknown_models(self, openai_backend):
        result = openai_backend.get_context_length("unknown-model")
        assert result == _DEFAULT_CONTEXT_LENGTH

    def test_prefix_match_for_versioned_strings(self, openai_backend):
        result = openai_backend.get_context_length("gpt-4o-2024-05-13")
        assert result == 128_000


# ---------------------------------------------------------------------------
# _parse_retry_after tests
# ---------------------------------------------------------------------------


class TestParseRetryAfter:
    """Tests for the _parse_retry_after helper function."""

    def test_checks_x_ratelimit_reset_tokens_first(self):
        """_parse_retry_after checks x-ratelimit-reset-tokens first."""
        future_time = datetime.now(timezone.utc) + timedelta(minutes=5)
        mock_response = MagicMock()
        mock_response.headers = {"x-ratelimit-reset-tokens": future_time.isoformat()}

        result = _parse_retry_after(mock_response)

        assert result is not None
        assert abs((result - future_time).total_seconds()) < 1

    def test_checks_x_ratelimit_reset_requests(self):
        future_time = datetime.now(timezone.utc) + timedelta(minutes=5)
        mock_response = MagicMock()
        mock_response.headers = {"x-ratelimit-reset-requests": future_time.isoformat()}

        result = _parse_retry_after(mock_response)

        assert result is not None
        assert abs((result - future_time).total_seconds()) < 1

    def test_falls_back_to_retry_after_seconds_header(self):
        """_parse_retry_after falls back to Retry-After seconds header."""
        mock_response = MagicMock()
        mock_response.headers = {"Retry-After": "60"}

        result = _parse_retry_after(mock_response)

        assert result is not None
        expected_min = datetime.now(timezone.utc) + timedelta(seconds=59)
        expected_max = datetime.now(timezone.utc) + timedelta(seconds=61)
        assert expected_min <= result <= expected_max

    def test_x_ratelimit_headers_take_priority_over_retry_after(self):
        future_time = datetime.now(timezone.utc) + timedelta(minutes=5)
        mock_response = MagicMock()
        mock_response.headers = {
            "x-ratelimit-reset-tokens": future_time.isoformat(),
            "Retry-After": "3600",  # 1 hour
        }

        result = _parse_retry_after(mock_response)

        assert result is not None
        # Should use x-ratelimit-reset-tokens (5 min), not Retry-After (1 hour)
        assert abs((result - future_time).total_seconds()) < 1

    def test_returns_none_when_no_relevant_headers(self):
        mock_response = MagicMock()
        mock_response.headers = {"Content-Type": "application/json"}

        result = _parse_retry_after(mock_response)

        assert result is None

    def test_returns_none_when_response_is_none(self):
        result = _parse_retry_after(None)
        assert result is None


# ---------------------------------------------------------------------------
# chat() budget tracker tests
# ---------------------------------------------------------------------------


class TestChatBudgetTracker:
    """Tests for OpenAIBackend.chat() budget tracker integration."""

    def test_calls_check_budget_before_request(self, openai_backend_with_budget):
        with patch("requests.post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: make_openai_response("hello"),
            )
            mock_post.return_value.raise_for_status = lambda: None

            openai_backend_with_budget.chat(
                model="gpt-4o",
                messages=[{"role": "user", "content": "Hi"}],
                tools=[],
                stream=False,
            )

        budget_tracker = openai_backend_with_budget._budget_tracker
        budget_tracker.check_budget.assert_called_once_with(
            provider="openai",
            model="gpt-4o",
        )

    def test_calls_record_after_success(self, openai_backend_with_budget):
        with patch("requests.post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: make_openai_response(
                    "hello", input_tokens=100, output_tokens=50
                ),
            )
            mock_post.return_value.raise_for_status = lambda: None

            openai_backend_with_budget.chat(
                model="gpt-4o",
                messages=[{"role": "user", "content": "Hi"}],
                tools=[],
                stream=False,
            )

        budget_tracker = openai_backend_with_budget._budget_tracker
        budget_tracker.record.assert_called_once_with(
            provider="openai",
            model="gpt-4o",
            input_tokens=100,
            output_tokens=50,
        )

    def test_raises_token_budget_exceeded_error_on_429(self, openai_backend):
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.headers = {}

        with patch("requests.post") as mock_post:
            mock_post.return_value = mock_response
            mock_post.return_value.raise_for_status.side_effect = requests.HTTPError(response=mock_response)

            with pytest.raises(TokenBudgetExceededError) as exc_info:
                openai_backend.chat(
                    model="gpt-4o",
                    messages=[],
                    tools=[],
                    stream=False,
                )

        assert exc_info.value.provider == "openai"
        assert exc_info.value.period == "hour"


# ---------------------------------------------------------------------------
# _assemble_response tests
# ---------------------------------------------------------------------------


class TestAssembleResponse:
    """Tests for OpenAIBackend._assemble_response method."""

    def test_assembles_text_content(self, openai_backend):
        result = openai_backend._assemble_response(
            accumulated_text="hello world",
            tool_calls=[],
            input_tokens=10,
            output_tokens=5,
            model="gpt-4o",
            stop_reason="end_turn",
        )

        assert isinstance(result, LLMResponse)
        assert len(result.content) == 1
        assert isinstance(result.content[0], TextBlock)
        assert result.content[0].text == "hello world"
        assert result.input_tokens == 10
        assert result.output_tokens == 5
        assert result.model == "gpt-4o"
        assert result.stop_reason == "end_turn"

    def test_assembles_tool_calls(self, openai_backend):
        tool_call = {
            "id": "call_abc123",
            "name": "test_tool",
            "input": {"x": 42},
        }
        result = openai_backend._assemble_response(
            accumulated_text="",
            tool_calls=[tool_call],
            input_tokens=10,
            output_tokens=5,
            model="gpt-4o",
            stop_reason="end_turn",
        )

        assert len(result.content) == 1
        assert isinstance(result.content[0], ToolUseBlock)
        assert result.content[0].id == "call_abc123"
        assert result.content[0].name == "test_tool"
        assert result.content[0].input == {"x": 42}

    def test_overrides_stop_reason_to_tool_use_when_tool_calls_present(self, openai_backend):
        tool_call = {
            "id": "call_abc",
            "name": "tool",
            "input": {},
        }
        result = openai_backend._assemble_response(
            accumulated_text="",
            tool_calls=[tool_call],
            input_tokens=10,
            output_tokens=5,
            model="gpt-4o",
            stop_reason="end_turn",
        )

        assert result.stop_reason == "tool_use"

    def test_handles_empty_text(self, openai_backend):
        result = openai_backend._assemble_response(
            accumulated_text="",
            tool_calls=[],
            input_tokens=0,
            output_tokens=0,
            model="gpt-4o",
            stop_reason="end_turn",
        )

        assert result.content == []


# ---------------------------------------------------------------------------
# _parse_response tests
# ---------------------------------------------------------------------------


class TestParseResponse:
    """Tests for OpenAIBackend._parse_response method."""

    def test_parses_standard_response(self, openai_backend):
        data = make_openai_response("hello world")
        result = openai_backend._parse_response(data)

        assert isinstance(result, LLMResponse)
        assert result.model == "gpt-4o"
        assert isinstance(result.content[0], TextBlock)
        assert result.content[0].text == "hello world"
        assert result.input_tokens == 10
        assert result.output_tokens == 5
        assert result.stop_reason == "end_turn"

    def test_parses_tool_calls(self, openai_backend):
        tool_call = {
            "id": "call_abc",
            "function": {
                "name": "test_tool",
                "arguments": json.dumps({"x": 42}),
            },
        }
        data = make_openai_response("", [tool_call], "tool_calls")
        result = openai_backend._parse_response(data)

        assert isinstance(result.content[0], ToolUseBlock)
        assert result.content[0].name == "test_tool"
        assert result.content[0].input == {"x": 42}
        assert result.stop_reason == "tool_use"

    def test_maps_stop_reasons_correctly(self, openai_backend):
        for openai_reason, expected_reason in _STOP_REASON_MAP.items():
            data = make_openai_response("test", finish_reason=openai_reason)
            result = openai_backend._parse_response(data)
            assert result.stop_reason == expected_reason, \
                f"Expected {expected_reason} for {openai_reason}"

    def test_handles_missing_fields_gracefully(self, openai_backend):
        data = {}
        result = openai_backend._parse_response(data)

        assert result.model == ""
        assert result.content == []
        assert result.input_tokens == 0
        assert result.output_tokens == 0
        assert result.stop_reason == "end_turn"


# ---------------------------------------------------------------------------
# _chat_blocking tests
# ---------------------------------------------------------------------------


class TestChatBlocking:
    """Tests for OpenAIBackend._chat_blocking method."""

    def test_makes_post_request_to_v1_chat_completions(self, openai_backend):
        payload = {"model": "gpt-4o", "messages": []}
        with patch("requests.post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: make_openai_response("test"),
            )
            mock_post.return_value.raise_for_status = lambda: None

            openai_backend._chat_blocking(
                "https://api.openai.com/v1/chat/completions",
                payload,
            )

            mock_post.assert_called_once()
            call_args = mock_post.call_args
            assert call_args[0][0] == "https://api.openai.com/v1/chat/completions"
            assert call_args[1]["json"] == payload

    def test_includes_auth_headers(self, openai_backend):
        payload = {"model": "gpt-4o", "messages": []}
        with patch("requests.post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: make_openai_response("test"),
            )
            mock_post.return_value.raise_for_status = lambda: None

            openai_backend._chat_blocking(
                "https://api.openai.com/v1/chat/completions",
                payload,
            )

            headers = mock_post.call_args[1]["headers"]
            assert headers["Authorization"] == "Bearer test-key"
            assert headers["Content-Type"] == "application/json"

    def test_uses_120_second_timeout(self, openai_backend):
        payload = {"model": "gpt-4o", "messages": []}
        with patch("requests.post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: make_openai_response("test"),
            )
            mock_post.return_value.raise_for_status = lambda: None

            openai_backend._chat_blocking(
                "https://api.openai.com/v1/chat/completions",
                payload,
            )

            assert mock_post.call_args[1]["timeout"] == 120

    def test_uses_custom_base_url(self, openai_backend_custom_base):
        payload = {"model": "custom-model", "messages": []}
        with patch("requests.post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: make_openai_response("test"),
            )
            mock_post.return_value.raise_for_status = lambda: None

            openai_backend_custom_base._chat_blocking(
                "https://custom.api.com/v1/chat/completions",
                payload,
            )

            headers = mock_post.call_args[1]["headers"]
            assert headers["Authorization"] == "Bearer test-key"


# ---------------------------------------------------------------------------
# _chat_streaming tests
# ---------------------------------------------------------------------------


class TestChatStreaming:
    """Tests for OpenAIBackend._chat_streaming method."""

    def test_calls_callback_for_each_text_chunk(self, openai_backend):
        mock_callback = MagicMock()
        stream_lines = [
            b'data: {"choices": [{"delta": {"content": "hello"}}]}',
            b'data: {"choices": [{"delta": {"content": " world"}}]}',
            b'data: {"choices": [{"delta": {}, "finish_reason": "stop"}]}',
            b"data: [DONE]",
        ]

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.iter_lines.return_value = stream_lines
        mock_response.__enter__ = lambda self: self
        mock_response.__exit__ = lambda self, *args: None

        with patch("requests.post", return_value=mock_response):
            openai_backend._chat_streaming(
                "https://api.openai.com/v1/chat/completions",
                {"model": "gpt-4o", "messages": []},
                mock_callback,
            )

        assert mock_callback.call_count == 2
        mock_callback.assert_any_call("hello")
        mock_callback.assert_any_call(" world")

    def test_accumulates_tool_call_deltas_by_index(self, openai_backend):
        """Streaming path accumulates tool call deltas by index."""
        mock_callback = MagicMock()
        chunk1 = json.dumps({
            "choices": [{
                "delta": {
                    "tool_calls": [{
                        "index": 0,
                        "id": "call_abc",
                        "function": {"name": "test", "arguments": '{"x":'},
                    }]
                }
            }]
        }).encode()
        chunk2 = json.dumps({
            "choices": [{
                "delta": {
                    "tool_calls": [{
                        "index": 0,
                        "function": {"arguments": '42}'},
                    }]
                }
            }]
        }).encode()
        stream_lines = [
            b'data: ' + chunk1,
            b'data: ' + chunk2,
            b'data: {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}',
            b"data: [DONE]",
        ]

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.iter_lines.return_value = stream_lines
        mock_response.__enter__ = lambda self: self
        mock_response.__exit__ = lambda self, *args: None

        with patch("requests.post", return_value=mock_response):
            result = openai_backend._chat_streaming(
                "https://api.openai.com/v1/chat/completions",
                {"model": "gpt-4o", "messages": []},
                mock_callback,
            )

        tool_blocks = [b for b in result.content if isinstance(b, ToolUseBlock)]
        assert len(tool_blocks) == 1
        assert tool_blocks[0].name == "test"
        assert tool_blocks[0].input == {"x": 42}

    def test_accumulates_multiple_tool_calls_by_index(self, openai_backend):
        """Multiple tool calls are accumulated separately by index."""
        mock_callback = MagicMock()
        stream_lines = [
            b'data: {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call_1", "function": {"name": "tool1", "arguments": "{}"}}]}}]}',
            b'data: {"choices": [{"delta": {"tool_calls": [{"index": 1, "id": "call_2", "function": {"name": "tool2", "arguments": "{}"}}]}}]}',
            b'data: {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}',
            b"data: [DONE]",
        ]

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.iter_lines.return_value = stream_lines
        mock_response.__enter__ = lambda self: self
        mock_response.__exit__ = lambda self, *args: None

        with patch("requests.post", return_value=mock_response):
            result = openai_backend._chat_streaming(
                "https://api.openai.com/v1/chat/completions",
                {"model": "gpt-4o", "messages": []},
                mock_callback,
            )

        tool_blocks = [b for b in result.content if isinstance(b, ToolUseBlock)]
        assert len(tool_blocks) == 2
        assert tool_blocks[0].name == "tool1"
        assert tool_blocks[1].name == "tool2"

    def test_extracts_usage_from_chunk(self, openai_backend):
        mock_callback = MagicMock()
        stream_lines = [
            b'data: {"choices": [{"delta": {"content": "test"}}]}',
            b'data: {"choices": [{"delta": {}}], "usage": {"prompt_tokens": 20, "completion_tokens": 10}}',
            b"data: [DONE]",
        ]

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.iter_lines.return_value = stream_lines
        mock_response.__enter__ = lambda self: self
        mock_response.__exit__ = lambda self, *args: None

        with patch("requests.post", return_value=mock_response):
            result = openai_backend._chat_streaming(
                "https://api.openai.com/v1/chat/completions",
                {"model": "gpt-4o", "messages": []},
                mock_callback,
            )

        assert result.input_tokens == 20
        assert result.output_tokens == 10

    def test_extracts_model_from_chunk(self, openai_backend):
        mock_callback = MagicMock()
        stream_lines = [
            b'data: {"choices": [{"delta": {"content": "test"}}]}',
            b'data: {"choices": [{"delta": {}}], "usage": {"prompt_tokens": 10, "completion_tokens": 5}, "model": "gpt-4-turbo"}',
            b"data: [DONE]",
        ]

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.iter_lines.return_value = stream_lines
        mock_response.__enter__ = lambda self: self
        mock_response.__exit__ = lambda self, *args: None

        with patch("requests.post", return_value=mock_response):
            result = openai_backend._chat_streaming(
                "https://api.openai.com/v1/chat/completions",
                {"model": "gpt-4o", "messages": []},
                mock_callback,
            )

        assert result.model == "gpt-4-turbo"

    def test_handles_data_prefix(self, openai_backend):
        """Lines starting with 'data: ' have the prefix stripped."""
        mock_callback = MagicMock()
        stream_lines = [
            b'data: {"choices": [{"delta": {"content": "hello"}}]}',
            b'data: [DONE]',
        ]

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.iter_lines.return_value = stream_lines
        mock_response.__enter__ = lambda self: self
        mock_response.__exit__ = lambda self, *args: None

        with patch("requests.post", return_value=mock_response):
            openai_backend._chat_streaming(
                "https://api.openai.com/v1/chat/completions",
                {"model": "gpt-4o", "messages": []},
                mock_callback,
            )

        mock_callback.assert_called_once_with("hello")

    def test_ignores_empty_lines(self, openai_backend):
        mock_callback = MagicMock()
        stream_lines = [
            b'data: {"choices": [{"delta": {"content": "hello"}}]}',
            b'',
            b'data: [DONE]',
        ]

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.iter_lines.return_value = stream_lines
        mock_response.__enter__ = lambda self: self
        mock_response.__exit__ = lambda self, *args: None

        with patch("requests.post", return_value=mock_response):
            openai_backend._chat_streaming(
                "https://api.openai.com/v1/chat/completions",
                {"model": "gpt-4o", "messages": []},
                mock_callback,
            )

        mock_callback.assert_called_once_with("hello")

    def test_ignores_malformed_json_lines(self, openai_backend):
        mock_callback = MagicMock()
        stream_lines = [
            b'data: {"choices": [{"delta": {"content": "hello"}}]}',
            b'data: not valid json{',
            b'data: [DONE]',
        ]

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.iter_lines.return_value = stream_lines
        mock_response.__enter__ = lambda self: self
        mock_response.__exit__ = lambda self, *args: None

        with patch("requests.post", return_value=mock_response):
            openai_backend._chat_streaming(
                "https://api.openai.com/v1/chat/completions",
                {"model": "gpt-4o", "messages": []},
                mock_callback,
            )

        mock_callback.assert_called_once_with("hello")


# ---------------------------------------------------------------------------
# is_model_available tests
# ---------------------------------------------------------------------------


class TestIsModelAvailable:
    """Tests for OpenAIBackend.is_model_available method."""

    def test_returns_true_for_non_empty_model_string(self, openai_backend):
        assert openai_backend.is_model_available("gpt-4o") is True
        assert openai_backend.is_model_available("any-model") is True

    def test_returns_false_for_empty_model_string(self, openai_backend):
        assert openai_backend.is_model_available("") is False


# ---------------------------------------------------------------------------
# list_models tests
# ---------------------------------------------------------------------------


class TestListModels:
    """Tests for OpenAIBackend.list_models method."""

    def test_returns_model_ids_from_v1_models(self, openai_backend):
        with patch("requests.get") as mock_get:
            mock_get.return_value = MagicMock(
                status_code=200,
                json=lambda: {
                    "data": [
                        {"id": "gpt-4o"},
                        {"id": "gpt-4-turbo"},
                    ]
                },
            )
            mock_get.return_value.raise_for_status = lambda: None

            result = openai_backend.list_models()

        assert result == ["gpt-4o", "gpt-4-turbo"]

    def test_returns_context_length_keys_on_error(self, openai_backend):
        with patch("requests.get", side_effect=requests.ConnectionError()):
            result = openai_backend.list_models()

        assert result == list(_CONTEXT_LENGTHS.keys())


# ---------------------------------------------------------------------------
# ensure_model tests
# ---------------------------------------------------------------------------


class TestEnsureModel:
    """Tests for OpenAIBackend.ensure_model method."""

    def test_is_no_op(self, openai_backend):
        # Should not raise
        openai_backend.ensure_model("gpt-4o")
        openai_backend.ensure_model("any-model")


# ---------------------------------------------------------------------------
# finalise_tool_calls tests
# ---------------------------------------------------------------------------


class TestFinaliseToolCalls:
    """Tests for finalise_tool_calls from openai_compat."""

    def test_parses_json_string_arguments(self):
        """finalise_tool_calls parses JSON string arguments."""
        raw_tool_calls = {
            0: {
                "id": "call_abc",
                "name": "test_tool",
                "arguments": '{"x": 42, "y": "hello"}',
            },
        }
        result = finalise_tool_calls(raw_tool_calls)

        assert len(result) == 1
        assert result[0]["id"] == "call_abc"
        assert result[0]["name"] == "test_tool"
        assert result[0]["input"] == {"x": 42, "y": "hello"}

    def test_handles_already_parsed_dict_arguments(self):
        """finalise_tool_calls handles already-parsed dict arguments."""
        raw_tool_calls = {
            0: {
                "id": "call_abc",
                "name": "test_tool",
                "arguments": {"x": 42, "y": "hello"},
            },
        }
        result = finalise_tool_calls(raw_tool_calls)

        assert len(result) == 1
        assert result[0]["input"] == {"x": 42, "y": "hello"}

    def test_generates_fallback_id_when_empty(self):
        """finalise_tool_calls generates fallback ID when id is empty."""
        raw_tool_calls = {
            0: {
                "id": "",
                "name": "test_tool",
                "arguments": {},
            },
        }
        result = finalise_tool_calls(raw_tool_calls)

        assert len(result) == 1
        assert result[0]["id"].startswith("call_")

    def test_returns_empty_list_for_empty_input(self):
        """finalise_tool_calls returns empty list for empty input."""
        result = finalise_tool_calls({})
        assert result == []

    def test_orders_by_index(self):
        """finalise_tool_calls orders by index."""
        raw_tool_calls = {
            2: {"id": "call_2", "name": "tool2", "arguments": {}},
            0: {"id": "call_0", "name": "tool0", "arguments": {}},
            1: {"id": "call_1", "name": "tool1", "arguments": {}},
        }
        result = finalise_tool_calls(raw_tool_calls)

        assert len(result) == 3
        assert result[0]["id"] == "call_0"
        assert result[1]["id"] == "call_1"
        assert result[2]["id"] == "call_2"
