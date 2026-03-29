"""
tests/inference/test_llamacpp_backend.py

Unit tests for LlamaCppBackend-specific functionality.

Tests:
    - get_context_length reads n_ctx from /props response
    - get_context_length returns fallback (32768) on error
    - is_model_available returns True when /health returns 200
    - ensure_model raises ModelNotAvailableError when /health fails
    - streaming path accumulates tool call deltas by index
    - _finalise_tool_calls parses JSON string arguments
    - _assemble_response builds correct LLMResponse
    - _parse_response handles OpenAI-compat response format
    - _chat_blocking makes correct POST request
    - _chat_streaming handles SSE format correctly
"""

import json
from unittest.mock import MagicMock, patch

import pytest
import requests

from matrixmouse.inference.base import (
    LLMResponse,
    TextBlock,
    ToolUseBlock,
    Tool,
    ModelNotAvailableError,
    BackendConnectionError,
    LLMBackendError,
)
from matrixmouse.inference.llamacpp import LlamaCppBackend, _translate_schema, _STOP_REASON_MAP
from matrixmouse.inference.openai_compat import finalise_tool_calls


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def llamacpp_backend():
    """Create a LlamaCppBackend instance."""
    return LlamaCppBackend(host="http://localhost:8080")


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


def make_llamacpp_response(
    content: str = "hello",
    tool_calls: list | None = None,
    finish_reason: str = "stop",
) -> dict:
    """Build a fake llama.cpp /v1/chat/completions response dict."""
    message = {
        "role": "assistant",
        "content": content,
    }
    if tool_calls:
        message["tool_calls"] = tool_calls  # type: ignore[assignment]

    choices = [{
        "index": 0,
        "message": message,
        "finish_reason": finish_reason,
    }]
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 1234567890,
        "model": "test-model",
        "choices": choices,
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
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
# get_context_length tests
# ---------------------------------------------------------------------------


class TestGetContextLength:
    """Tests for LlamaCppBackend.get_context_length method."""

    def test_reads_n_ctx_from_props_response(self, llamacpp_backend):
        with patch("requests.get") as mock_get:
            mock_get.return_value = MagicMock(
                status_code=200,
                json=lambda: {
                    "default_generation_settings": {
                        "n_ctx": 8192
                    }
                },
            )
            mock_get.return_value.raise_for_status = lambda: None

            result = llamacpp_backend.get_context_length("test-model")

        assert result == 8192
        mock_get.assert_called_once_with(
            "http://localhost:8080/props",
            timeout=3600,
        )

    def test_returns_fallback_on_connection_error(self, llamacpp_backend):
        with patch("requests.get", side_effect=requests.ConnectionError()):
            result = llamacpp_backend.get_context_length("test-model")

        assert result == 32768

    def test_returns_fallback_on_timeout(self, llamacpp_backend):
        with patch("requests.get", side_effect=requests.Timeout()):
            result = llamacpp_backend.get_context_length("test-model")

        assert result == 32768

    def test_returns_fallback_on_http_error(self, llamacpp_backend):
        with patch("requests.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 500
            mock_get.return_value = mock_response
            mock_get.return_value.raise_for_status.side_effect = requests.HTTPError(response=mock_response)

            result = llamacpp_backend.get_context_length("test-model")

        assert result == 32768

    def test_returns_fallback_when_n_ctx_missing(self, llamacpp_backend):
        with patch("requests.get") as mock_get:
            mock_get.return_value = MagicMock(
                status_code=200,
                json=lambda: {"default_generation_settings": {}},
            )
            mock_get.return_value.raise_for_status = lambda: None

            result = llamacpp_backend.get_context_length("test-model")

        assert result == 32768

    def test_returns_fallback_when_default_generation_settings_missing(self, llamacpp_backend):
        with patch("requests.get") as mock_get:
            mock_get.return_value = MagicMock(
                status_code=200,
                json=lambda: {},
            )
            mock_get.return_value.raise_for_status = lambda: None

            result = llamacpp_backend.get_context_length("test-model")

        assert result == 32768

    def test_uses_configured_timeout(self):
        backend = LlamaCppBackend(host="http://localhost:8080", timeout=120)
        with patch("requests.get") as mock_get:
            mock_get.return_value = MagicMock(
                status_code=200,
                json=lambda: {"default_generation_settings": {"n_ctx": 4096}},
            )
            mock_get.return_value.raise_for_status = lambda: None

            backend.get_context_length("test-model")

            assert mock_get.call_args[1]["timeout"] == 120


# ---------------------------------------------------------------------------
# is_model_available tests
# ---------------------------------------------------------------------------


class TestIsModelAvailable:
    """Tests for LlamaCppBackend.is_model_available method."""

    def test_returns_true_when_health_returns_200(self, llamacpp_backend):
        with patch("requests.get") as mock_get:
            mock_get.return_value = MagicMock(status_code=200)

            result = llamacpp_backend.is_model_available("any-model")

        assert result is True
        mock_get.assert_called_once_with(
            "http://localhost:8080/health",
            timeout=10,
        )

    def test_returns_false_when_health_returns_non_200(self, llamacpp_backend):
        with patch("requests.get") as mock_get:
            mock_get.return_value = MagicMock(status_code=503)

            result = llamacpp_backend.is_model_available("any-model")

        assert result is False

    def test_returns_false_on_connection_error(self, llamacpp_backend):
        with patch("requests.get", side_effect=requests.ConnectionError()):
            result = llamacpp_backend.is_model_available("any-model")

        assert result is False

    def test_returns_false_on_timeout(self, llamacpp_backend):
        with patch("requests.get", side_effect=requests.Timeout()):
            result = llamacpp_backend.is_model_available("any-model")

        assert result is False


# ---------------------------------------------------------------------------
# ensure_model tests
# ---------------------------------------------------------------------------


class TestEnsureModel:
    """Tests for LlamaCppBackend.ensure_model method."""

    def test_succeeds_when_health_returns_200(self, llamacpp_backend):
        with patch("requests.get") as mock_get:
            mock_get.return_value = MagicMock(status_code=200)

            # Should not raise
            llamacpp_backend.ensure_model("any-model")

        mock_get.assert_called_once_with(
            "http://localhost:8080/health",
            timeout=10,
        )

    def test_raises_when_health_returns_non_200(self, llamacpp_backend):
        with patch("requests.get") as mock_get:
            mock_get.return_value = MagicMock(status_code=503)

            with pytest.raises(ModelNotAvailableError) as exc_info:
                llamacpp_backend.ensure_model("any-model")

            assert "HTTP 503" in str(exc_info.value)

    def test_raises_on_connection_error(self, llamacpp_backend):
        with patch("requests.get", side_effect=requests.ConnectionError()):
            with pytest.raises(ModelNotAvailableError) as exc_info:
                llamacpp_backend.ensure_model("any-model")

            assert "Could not reach llama.cpp server" in str(exc_info.value)


# ---------------------------------------------------------------------------
# list_models tests
# ---------------------------------------------------------------------------


class TestListModels:
    """Tests for LlamaCppBackend.list_models method."""

    def test_returns_model_ids_from_v1_models(self, llamacpp_backend):
        with patch("requests.get") as mock_get:
            mock_get.return_value = MagicMock(
                status_code=200,
                json=lambda: {
                    "data": [
                        {"id": "llama-3.2-1b"},
                        {"id": "qwen3:4b"},
                    ]
                },
            )
            mock_get.return_value.raise_for_status = lambda: None

            result = llamacpp_backend.list_models()

        assert result == ["llama-3.2-1b", "qwen3:4b"]

    def test_returns_empty_list_on_error(self, llamacpp_backend):
        with patch("requests.get", side_effect=requests.ConnectionError()):
            result = llamacpp_backend.list_models()

        assert result == []

    def test_returns_empty_list_when_data_missing(self, llamacpp_backend):
        with patch("requests.get") as mock_get:
            mock_get.return_value = MagicMock(
                status_code=200,
                json=lambda: {},
            )
            mock_get.return_value.raise_for_status = lambda: None

            result = llamacpp_backend.list_models()

        assert result == []


# ---------------------------------------------------------------------------
# _assemble_response tests
# ---------------------------------------------------------------------------


class TestAssembleResponse:
    """Tests for LlamaCppBackend._assemble_response method."""

    def test_assembles_text_content(self, llamacpp_backend):
        result = llamacpp_backend._assemble_response(
            accumulated_text="hello world",
            tool_calls=[],
            input_tokens=10,
            output_tokens=5,
            model="test-model",
            stop_reason="end_turn",
        )

        assert isinstance(result, LLMResponse)
        assert len(result.content) == 1
        assert isinstance(result.content[0], TextBlock)
        assert result.content[0].text == "hello world"
        assert result.input_tokens == 10
        assert result.output_tokens == 5
        assert result.model == "test-model"
        assert result.stop_reason == "end_turn"

    def test_assembles_tool_calls(self, llamacpp_backend):
        tool_call = {
            "id": "call_abc123",
            "name": "test_tool",
            "input": {"x": 42},
        }
        result = llamacpp_backend._assemble_response(
            accumulated_text="",
            tool_calls=[tool_call],
            input_tokens=10,
            output_tokens=5,
            model="test-model",
            stop_reason="end_turn",
        )

        assert len(result.content) == 1
        assert isinstance(result.content[0], ToolUseBlock)
        assert result.content[0].id == "call_abc123"
        assert result.content[0].name == "test_tool"
        assert result.content[0].input == {"x": 42}

    def test_overrides_stop_reason_to_tool_use_when_tool_calls_present(self, llamacpp_backend):
        tool_call = {
            "id": "call_abc",
            "name": "tool",
            "input": {},
        }
        result = llamacpp_backend._assemble_response(
            accumulated_text="",
            tool_calls=[tool_call],
            input_tokens=10,
            output_tokens=5,
            model="test-model",
            stop_reason="end_turn",
        )

        assert result.stop_reason == "tool_use"

    def test_handles_empty_text(self, llamacpp_backend):
        result = llamacpp_backend._assemble_response(
            accumulated_text="",
            tool_calls=[],
            input_tokens=0,
            output_tokens=0,
            model="test-model",
            stop_reason="end_turn",
        )

        assert result.content == []


# ---------------------------------------------------------------------------
# _parse_response tests
# ---------------------------------------------------------------------------


class TestParseResponse:
    """Tests for LlamaCppBackend._parse_response method."""

    def test_parses_standard_response(self, llamacpp_backend):
        data = make_llamacpp_response("hello world")
        result = llamacpp_backend._parse_response(data)

        assert isinstance(result, LLMResponse)
        assert result.model == "test-model"
        assert isinstance(result.content[0], TextBlock)
        assert result.content[0].text == "hello world"
        assert result.input_tokens == 10
        assert result.output_tokens == 5
        assert result.stop_reason == "end_turn"

    def test_parses_tool_calls(self, llamacpp_backend):
        tool_call = {
            "id": "call_abc",
            "function": {
                "name": "test_tool",
                "arguments": json.dumps({"x": 42}),
            },
        }
        data = make_llamacpp_response("", [tool_call], "tool_calls")
        result = llamacpp_backend._parse_response(data)

        assert isinstance(result.content[0], ToolUseBlock)
        assert result.content[0].name == "test_tool"
        assert result.content[0].input == {"x": 42}
        assert result.stop_reason == "tool_use"

    def test_maps_stop_reasons_correctly(self, llamacpp_backend):
        for llama_reason, expected_reason in _STOP_REASON_MAP.items():
            data = make_llamacpp_response("test", finish_reason=llama_reason)
            result = llamacpp_backend._parse_response(data)
            assert result.stop_reason == expected_reason, \
                f"Expected {expected_reason} for {llama_reason}"

    def test_handles_missing_fields_gracefully(self, llamacpp_backend):
        data = {}
        result = llamacpp_backend._parse_response(data)

        assert result.model == ""
        assert result.content == []
        assert result.input_tokens == 0
        assert result.output_tokens == 0
        assert result.stop_reason == "end_turn"


# ---------------------------------------------------------------------------
# _chat_blocking tests
# ---------------------------------------------------------------------------


class TestChatBlocking:
    """Tests for LlamaCppBackend._chat_blocking method."""

    def test_makes_post_request_to_v1_chat_completions(self, llamacpp_backend):
        payload = {"model": "test", "messages": []}
        with patch("requests.post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: make_llamacpp_response("test"),
            )
            mock_post.return_value.raise_for_status = lambda: None

            llamacpp_backend._chat_blocking(
                "http://localhost:8080/v1/chat/completions",
                payload,
            )

            mock_post.assert_called_once()
            call_args = mock_post.call_args
            assert call_args[0][0] == "http://localhost:8080/v1/chat/completions"
            assert call_args[1]["json"] == payload

    def test_uses_configured_timeout(self):
        backend = LlamaCppBackend(host="http://localhost:8080", timeout=600)
        with patch("requests.post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: make_llamacpp_response("test"),
            )
            mock_post.return_value.raise_for_status = lambda: None

            backend._chat_blocking("http://localhost:8080/v1/chat/completions", {})

            assert mock_post.call_args[1]["timeout"] == 600


# ---------------------------------------------------------------------------
# _chat_streaming tests - tool call accumulation
# ---------------------------------------------------------------------------


class TestChatStreaming:
    """Tests for LlamaCppBackend._chat_streaming method."""

    def test_calls_callback_for_each_text_chunk(self, llamacpp_backend):
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
            llamacpp_backend._chat_streaming(
                "http://localhost:8080/v1/chat/completions",
                {"model": "test", "messages": []},
                mock_callback,
            )

        assert mock_callback.call_count == 2
        mock_callback.assert_any_call("hello")
        mock_callback.assert_any_call(" world")

    def test_accumulates_tool_call_deltas_by_index(self, llamacpp_backend):
        """Streaming path accumulates tool call deltas by index."""
        mock_callback = MagicMock()
        # Build JSON with properly escaped arguments string
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
            result = llamacpp_backend._chat_streaming(
                "http://localhost:8080/v1/chat/completions",
                {"model": "test", "messages": []},
                mock_callback,
            )

        tool_blocks = [b for b in result.content if isinstance(b, ToolUseBlock)]
        assert len(tool_blocks) == 1
        assert tool_blocks[0].name == "test"
        assert tool_blocks[0].input == {"x": 42}

    def test_accumulates_multiple_tool_calls_by_index(self, llamacpp_backend):
        """Multiple tool calls are accumulated separately by index."""
        mock_callback = MagicMock()
        stream_lines = [
            # First tool call
            b'data: {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call_1", "function": {"name": "tool1", "arguments": "{}"}}]}}]}',
            # Second tool call
            b'data: {"choices": [{"delta": {"tool_calls": [{"index": 1, "id": "call_2", "function": {"name": "tool2", "arguments": "{}"}}]}}]}',
            # Final chunk
            b'data: {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}',
            b"data: [DONE]",
        ]

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.iter_lines.return_value = stream_lines
        mock_response.__enter__ = lambda self: self
        mock_response.__exit__ = lambda self, *args: None

        with patch("requests.post", return_value=mock_response):
            result = llamacpp_backend._chat_streaming(
                "http://localhost:8080/v1/chat/completions",
                {"model": "test", "messages": []},
                mock_callback,
            )

        tool_blocks = [b for b in result.content if isinstance(b, ToolUseBlock)]
        assert len(tool_blocks) == 2
        assert tool_blocks[0].name == "tool1"
        assert tool_blocks[1].name == "tool2"

    def test_extracts_usage_from_chunk(self, llamacpp_backend):
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
            result = llamacpp_backend._chat_streaming(
                "http://localhost:8080/v1/chat/completions",
                {"model": "test", "messages": []},
                mock_callback,
            )

        assert result.input_tokens == 20
        assert result.output_tokens == 10

    def test_extracts_model_from_chunk(self, llamacpp_backend):
        mock_callback = MagicMock()
        stream_lines = [
            b'data: {"choices": [{"delta": {"content": "test"}}]}',
            b'data: {"choices": [{"delta": {}}], "usage": {"prompt_tokens": 10, "completion_tokens": 5}, "model": "qwen3:72b"}',
            b"data: [DONE]",
        ]

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.iter_lines.return_value = stream_lines
        mock_response.__enter__ = lambda self: self
        mock_response.__exit__ = lambda self, *args: None

        with patch("requests.post", return_value=mock_response):
            result = llamacpp_backend._chat_streaming(
                "http://localhost:8080/v1/chat/completions",
                {"model": "test", "messages": []},
                mock_callback,
            )

        assert result.model == "qwen3:72b"

    def test_handles_data_prefix(self, llamacpp_backend):
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
            llamacpp_backend._chat_streaming(
                "http://localhost:8080/v1/chat/completions",
                {"model": "test", "messages": []},
                mock_callback,
            )

        mock_callback.assert_called_once_with("hello")

    def test_ignores_empty_lines(self, llamacpp_backend):
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
            llamacpp_backend._chat_streaming(
                "http://localhost:8080/v1/chat/completions",
                {"model": "test", "messages": []},
                mock_callback,
            )

        mock_callback.assert_called_once_with("hello")

    def test_ignores_malformed_json_lines(self, llamacpp_backend):
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
            llamacpp_backend._chat_streaming(
                "http://localhost:8080/v1/chat/completions",
                {"model": "test", "messages": []},
                mock_callback,
            )

        mock_callback.assert_called_once_with("hello")


# ---------------------------------------------------------------------------
# finalise_tool_calls tests
# ---------------------------------------------------------------------------


class TestFinaliseToolCalls:
    """Tests for the finalise_tool_calls helper from openai_compat."""

    def test_parses_json_string_arguments(self):
        """_finalise_tool_calls parses JSON string arguments."""
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
        """_finalise_tool_calls handles already-parsed dict arguments."""
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
        """_finalise_tool_calls generates fallback ID when id is empty."""
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
        assert len(result[0]["id"]) == 13  # "call_" + 8 hex chars

    def test_returns_empty_list_for_empty_input(self):
        """_finalise_tool_calls returns empty list for empty input."""
        result = finalise_tool_calls({})
        assert result == []

    def test_orders_by_index(self):
        """_finalise_tool_calls orders by index."""
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

    def test_handles_invalid_json_gracefully(self):
        """_finalise_tool_calls handles invalid JSON gracefully."""
        raw_tool_calls = {
            0: {
                "id": "call_abc",
                "name": "test_tool",
                "arguments": "not valid json{",
            },
        }
        result = finalise_tool_calls(raw_tool_calls)

        assert len(result) == 1
        assert result[0]["input"] == {}
