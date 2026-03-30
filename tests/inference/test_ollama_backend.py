"""
tests/inference/test_ollama_backend.py

Unit tests for OllamaBackend-specific functionality.

Tests:
    - _translate_schema translates tool schema to Ollama format
    - _assemble_response produces correct stop_reason for tool calls
    - _assemble_response overrides stop_reason to tool_use when ToolUseBlock present
    - get_context_length returns fallback on connection error
    - get_context_length parses context_length from modelinfo
    - ensure_model is no-op when model already available
    - ensure_model raises ModelNotAvailableError on pull failure
    - _parse_response handles Ollama response format correctly
    - Streaming response assembly with thinking blocks
"""

import json
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
)
from matrixmouse.inference.ollama import OllamaBackend, _translate_schema, _STOP_REASON_MAP


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def ollama_backend():
    """Create an OllamaBackend instance."""
    return OllamaBackend(host="http://localhost:11434")


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


# ---------------------------------------------------------------------------
# _translate_schema tests
# ---------------------------------------------------------------------------


class TestTranslateSchema:
    """Tests for the _translate_schema helper function."""

    def test_translates_schema_to_ollama_format(self):
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
# _assemble_response tests
# ---------------------------------------------------------------------------


class TestAssembleResponse:
    """Tests for OllamaBackend._assemble_response method."""

    def test_assembles_text_content(self, ollama_backend):
        result = ollama_backend._assemble_response(
            accumulated_text="hello world",
            accumulated_thinking="",
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

    def test_assembles_thinking_content(self, ollama_backend):
        result = ollama_backend._assemble_response(
            accumulated_text="answer",
            accumulated_thinking="let me think about this...",
            tool_calls=[],
            input_tokens=10,
            output_tokens=5,
            model="test-model",
            stop_reason="end_turn",
        )

        assert len(result.content) == 2
        assert isinstance(result.content[0], ThinkingBlock)
        assert result.content[0].text == "let me think about this..."
        assert isinstance(result.content[1], TextBlock)

    def test_assembles_tool_calls(self, ollama_backend):
        tool_call = {
            "id": "call_abc123",
            "function": {
                "name": "test_tool",
                "arguments": {"x": 42},
            },
        }
        result = ollama_backend._assemble_response(
            accumulated_text="",
            accumulated_thinking="",
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

    def test_overrides_stop_reason_to_tool_use_when_tool_calls_present(self, ollama_backend):
        tool_call = {
            "id": "call_abc",
            "function": {"name": "tool", "arguments": {}},
        }
        result = ollama_backend._assemble_response(
            accumulated_text="",
            accumulated_thinking="",
            tool_calls=[tool_call],
            input_tokens=10,
            output_tokens=5,
            model="test-model",
            stop_reason="end_turn",  # Initial stop reason
        )

        # Should be overridden to tool_use
        assert result.stop_reason == "tool_use"

    def test_generates_fallback_tool_call_id_when_missing(self, ollama_backend):
        tool_call = {
            "function": {"name": "tool", "arguments": {}},
        }
        result = ollama_backend._assemble_response(
            accumulated_text="",
            accumulated_thinking="",
            tool_calls=[tool_call],
            input_tokens=10,
            output_tokens=5,
            model="test-model",
            stop_reason="end_turn",
        )

        # ID format is "call_{uuid.hex[:8]}" = 5 + 8 = 13 chars
        assert len(result.content[0].id) == 13
        assert result.content[0].id.startswith("call_")

    def test_parses_json_string_arguments(self, ollama_backend):
        tool_call = {
            "id": "call_abc",
            "function": {
                "name": "test_tool",
                "arguments": '{"x": 42, "y": "hello"}',
            },
        }
        result = ollama_backend._assemble_response(
            accumulated_text="",
            accumulated_thinking="",
            tool_calls=[tool_call],
            input_tokens=10,
            output_tokens=5,
            model="test-model",
            stop_reason="end_turn",
        )

        assert result.content[0].input == {"x": 42, "y": "hello"}

    def test_handles_invalid_json_arguments_gracefully(self, ollama_backend):
        tool_call = {
            "id": "call_abc",
            "function": {
                "name": "test_tool",
                "arguments": "not valid json{",
            },
        }
        result = ollama_backend._assemble_response(
            accumulated_text="",
            accumulated_thinking="",
            tool_calls=[tool_call],
            input_tokens=10,
            output_tokens=5,
            model="test-model",
            stop_reason="end_turn",
        )

        assert result.content[0].input == {}

    def test_orders_content_blocks_thinking_text_tools(self, ollama_backend):
        tool_call = {
            "id": "call_abc",
            "function": {"name": "tool", "arguments": {}},
        }
        result = ollama_backend._assemble_response(
            accumulated_text="answer",
            accumulated_thinking="thinking...",
            tool_calls=[tool_call],
            input_tokens=10,
            output_tokens=5,
            model="test-model",
            stop_reason="end_turn",
        )

        assert isinstance(result.content[0], ThinkingBlock)
        assert isinstance(result.content[1], TextBlock)
        assert isinstance(result.content[2], ToolUseBlock)


# ---------------------------------------------------------------------------
# _parse_response tests
# ---------------------------------------------------------------------------


class TestParseResponse:
    """Tests for OllamaBackend._parse_response method."""

    def test_parses_standard_response(self, ollama_backend):
        data = {
            "model": "qwen3:4b",
            "message": {
                "content": "hello world",
                "tool_calls": [],
            },
            "done": True,
            "done_reason": "stop",
            "prompt_eval_count": 10,
            "eval_count": 5,
        }
        result = ollama_backend._parse_response(data)

        assert isinstance(result, LLMResponse)
        assert result.model == "qwen3:4b"
        assert isinstance(result.content[0], TextBlock)
        assert result.content[0].text == "hello world"
        assert result.input_tokens == 10
        assert result.output_tokens == 5
        assert result.stop_reason == "end_turn"

    def test_parses_thinking_content(self, ollama_backend):
        data = {
            "model": "qwen3:4b",
            "message": {
                "content": "answer",
                "thinking": "let me think...",
                "tool_calls": [],
            },
            "done": True,
            "done_reason": "stop",
            "prompt_eval_count": 10,
            "eval_count": 5,
        }
        result = ollama_backend._parse_response(data)

        assert len(result.content) == 2
        assert isinstance(result.content[0], ThinkingBlock)
        assert result.content[0].text == "let me think..."

    def test_parses_tool_calls(self, ollama_backend):
        data = {
            "model": "qwen3:4b",
            "message": {
                "content": "",
                "tool_calls": [{
                    "id": "call_abc",
                    "function": {
                        "name": "test_tool",
                        "arguments": {"x": 42},
                    },
                }],
            },
            "done": True,
            "done_reason": "tool_calls",
            "prompt_eval_count": 10,
            "eval_count": 5,
        }
        result = ollama_backend._parse_response(data)

        assert isinstance(result.content[0], ToolUseBlock)
        assert result.stop_reason == "tool_use"

    def test_maps_stop_reasons_correctly(self, ollama_backend):
        for ollama_reason, expected_reason in _STOP_REASON_MAP.items():
            data = {
                "model": "qwen3:4b",
                "message": {"content": "test", "tool_calls": []},
                "done": True,
                "done_reason": ollama_reason,
                "prompt_eval_count": 0,
                "eval_count": 0,
            }
            result = ollama_backend._parse_response(data)
            assert result.stop_reason == expected_reason, \
                f"Expected {expected_reason} for {ollama_reason}"

    def test_handles_missing_fields_gracefully(self, ollama_backend):
        data = {}
        result = ollama_backend._parse_response(data)

        assert result.model == ""
        assert result.content == []
        assert result.input_tokens == 0
        assert result.output_tokens == 0
        assert result.stop_reason == "end_turn"


# ---------------------------------------------------------------------------
# get_context_length tests
# ---------------------------------------------------------------------------


class TestGetContextLength:
    """Tests for OllamaBackend.get_context_length method."""

    def test_parses_context_length_from_modelinfo(self, ollama_backend):
        with patch("requests.post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: {"modelinfo": {"general.context_length": 8192}},
            )
            mock_post.return_value.raise_for_status = lambda: None

            result = ollama_backend.get_context_length("test-model")

        assert result == 8192

    def test_parses_context_length_alternative_key(self, ollama_backend):
        with patch("requests.post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: {"modelinfo": {"context_length": 4096}},
            )
            mock_post.return_value.raise_for_status = lambda: None

            result = ollama_backend.get_context_length("test-model")

        assert result == 4096

    def test_parses_context_length_from_any_key_containing_context_length(self, ollama_backend):
        with patch("requests.post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: {"modelinfo": {"ollama.context_length": 16384}},
            )
            mock_post.return_value.raise_for_status = lambda: None

            result = ollama_backend.get_context_length("test-model")

        assert result == 16384

    def test_returns_fallback_on_connection_error(self, ollama_backend):
        with patch("requests.post", side_effect=requests.ConnectionError()):
            result = ollama_backend.get_context_length("test-model")

        assert result == 32768  # Default fallback

    def test_returns_fallback_on_timeout(self, ollama_backend):
        with patch("requests.post", side_effect=requests.Timeout()):
            result = ollama_backend.get_context_length("test-model")

        assert result == 32768

    def test_returns_fallback_when_context_length_missing(self, ollama_backend):
        with patch("requests.post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: {"modelinfo": {}},
            )
            mock_post.return_value.raise_for_status = lambda: None

            result = ollama_backend.get_context_length("test-model")

        assert result == 32768

    def test_returns_fallback_on_http_error(self, ollama_backend):
        with patch("requests.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 500
            mock_post.return_value = mock_response
            mock_post.return_value.raise_for_status.side_effect = requests.HTTPError(response=mock_response)

            result = ollama_backend.get_context_length("test-model")

        assert result == 32768


# ---------------------------------------------------------------------------
# ensure_model tests
# ---------------------------------------------------------------------------


class TestEnsureModel:
    """Tests for OllamaBackend.ensure_model method."""

    def test_is_no_op_when_model_already_available(self, ollama_backend):
        with patch.object(ollama_backend, "is_model_available", return_value=True):
            with patch("requests.post") as mock_post:
                ollama_backend.ensure_model("existing-model")
                # Should not call pull if model is available
                mock_post.assert_not_called()

    def test_pulls_model_when_not_available(self, ollama_backend):
        with patch.object(ollama_backend, "is_model_available", return_value=False):
            with patch("requests.post") as mock_post:
                mock_response = MagicMock()
                mock_response.status_code = 200
                mock_response.iter_lines.return_value = [
                    b'{"status": "pulling manifest"}',
                    b'{"status": "downloading"}',
                    b'{"status": "success"}',
                ]
                mock_response.__enter__ = lambda self: self
                mock_response.__exit__ = lambda self, *args: None
                mock_post.return_value = mock_response

                ollama_backend.ensure_model("new-model")

                # Should have called /api/pull
                call_args = mock_post.call_args
                assert "/api/pull" in call_args[0][0]
                assert call_args[1]["json"]["name"] == "new-model"

    def test_raises_on_pull_failure(self, ollama_backend):
        with patch.object(ollama_backend, "is_model_available", return_value=False):
            with patch("requests.post") as mock_post:
                mock_response = MagicMock()
                mock_response.status_code = 200
                mock_response.iter_lines.return_value = [
                    b'{"status": "pulling manifest", "error": "model not found"}',
                ]
                mock_response.__enter__ = lambda self: self
                mock_response.__exit__ = lambda self, *args: None
                mock_post.return_value = mock_response

                with pytest.raises(ModelNotAvailableError) as exc_info:
                    ollama_backend.ensure_model("nonexistent-model")

                assert "model not found" in str(exc_info.value)

    def test_raises_on_connection_error(self, ollama_backend):
        with patch.object(ollama_backend, "is_model_available", return_value=False):
            with patch("requests.post", side_effect=requests.ConnectionError()):
                with pytest.raises(BackendConnectionError):
                    ollama_backend.ensure_model("unreachable-model")

    def test_raises_on_http_error(self, ollama_backend):
        with patch.object(ollama_backend, "is_model_available", return_value=False):
            with patch("requests.post") as mock_post:
                mock_response = MagicMock()
                mock_response.status_code = 404
                mock_response.__enter__ = lambda self: self
                mock_response.__exit__ = lambda self, *args: None
                mock_response.raise_for_status.side_effect = requests.HTTPError(response=mock_response)
                mock_post.return_value = mock_response

                with pytest.raises(ModelNotAvailableError):
                    ollama_backend.ensure_model("missing-model")


# ---------------------------------------------------------------------------
# _chat_blocking tests
# ---------------------------------------------------------------------------


class TestChatBlocking:
    """Tests for OllamaBackend._chat_blocking method."""

    def test_makes_post_request_to_api_chat(self, ollama_backend):
        payload = {"model": "test", "messages": []}
        with patch("requests.post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: make_ollama_response_data("test"),
            )
            mock_post.return_value.raise_for_status = lambda: None

            ollama_backend._chat_blocking("http://localhost:11434/api/chat", payload)

            mock_post.assert_called_once()
            call_args = mock_post.call_args
            assert call_args[0][0] == "http://localhost:11434/api/chat"
            assert call_args[1]["json"] == payload

    def test_uses_configured_timeout(self):
        backend = OllamaBackend(host="http://localhost:11434", timeout=600)
        with patch("requests.post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: make_ollama_response_data("test"),
            )
            mock_post.return_value.raise_for_status = lambda: None

            backend._chat_blocking("http://localhost:11434/api/chat", {})

            assert mock_post.call_args[1]["timeout"] == 600


# ---------------------------------------------------------------------------
# _chat_streaming tests
# ---------------------------------------------------------------------------


class TestChatStreaming:
    """Tests for OllamaBackend._chat_streaming method."""

    def test_calls_callback_for_each_text_chunk(self, ollama_backend):
        mock_callback = MagicMock()
        stream_lines = [
            b'{"message": {"content": "hello"}, "done": false}',
            b'{"message": {"content": " world"}, "done": false}',
            b'{"message": {"content": ""}, "done": true, "done_reason": "stop"}',
        ]

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.iter_lines.return_value = stream_lines
        mock_response.__enter__ = lambda self: self
        mock_response.__exit__ = lambda self, *args: None

        with patch("requests.post", return_value=mock_response):
            ollama_backend._chat_streaming(
                "http://localhost:11434/api/chat",
                {"model": "test", "messages": []},
                mock_callback,
            )

        assert mock_callback.call_count == 2
        mock_callback.assert_any_call("hello")
        mock_callback.assert_any_call(" world")

    def test_accumulates_thinking_content(self, ollama_backend):
        mock_callback = MagicMock()
        stream_lines = [
            b'{"message": {"thinking": "let me ", "content": ""}, "done": false}',
            b'{"message": {"thinking": "think...", "content": ""}, "done": false}',
            b'{"message": {"content": "answer"}, "done": true}',
        ]

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.iter_lines.return_value = stream_lines
        mock_response.__enter__ = lambda self: self
        mock_response.__exit__ = lambda self, *args: None

        with patch("requests.post", return_value=mock_response):
            result = ollama_backend._chat_streaming(
                "http://localhost:11434/api/chat",
                {"model": "test", "messages": []},
                mock_callback,
            )

        thinking_block = next((b for b in result.content if isinstance(b, ThinkingBlock)), None)
        assert thinking_block is not None
        assert thinking_block.text == "let me think..."

    def test_accumulates_tool_calls_across_chunks(self, ollama_backend):
        mock_callback = MagicMock()
        stream_lines = [
            b'{"message": {"tool_calls": [{"id": "call_1", "function": {"name": "tool", "arguments": {"x": 1}}}]}, "done": false}',
            b'{"message": {"tool_calls": [{"id": "call_2", "function": {"name": "tool2", "arguments": {"y": 2}}}]}, "done": false}',
            b'{"message": {}, "done": true}',
        ]

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.iter_lines.return_value = stream_lines
        mock_response.__enter__ = lambda self: self
        mock_response.__exit__ = lambda self, *args: None

        with patch("requests.post", return_value=mock_response):
            result = ollama_backend._chat_streaming(
                "http://localhost:11434/api/chat",
                {"model": "test", "messages": []},
                mock_callback,
            )

        tool_blocks = [b for b in result.content if isinstance(b, ToolUseBlock)]
        assert len(tool_blocks) == 2

    def test_extracts_usage_from_final_chunk(self, ollama_backend):
        mock_callback = MagicMock()
        stream_lines = [
            b'{"message": {"content": "test"}, "done": false}',
            b'{"message": {}, "done": true, "prompt_eval_count": 20, "eval_count": 10}',
        ]

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.iter_lines.return_value = stream_lines
        mock_response.__enter__ = lambda self: self
        mock_response.__exit__ = lambda self, *args: None

        with patch("requests.post", return_value=mock_response):
            result = ollama_backend._chat_streaming(
                "http://localhost:11434/api/chat",
                {"model": "test", "messages": []},
                mock_callback,
            )

        assert result.input_tokens == 20
        assert result.output_tokens == 10

    def test_extracts_model_from_final_chunk(self, ollama_backend):
        mock_callback = MagicMock()
        stream_lines = [
            b'{"message": {"content": "test"}, "done": false}',
            b'{"message": {}, "done": true, "model": "qwen3:72b"}',
        ]

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.iter_lines.return_value = stream_lines
        mock_response.__enter__ = lambda self: self
        mock_response.__exit__ = lambda self, *args: None

        with patch("requests.post", return_value=mock_response):
            result = ollama_backend._chat_streaming(
                "http://localhost:11434/api/chat",
                {"model": "test", "messages": []},
                mock_callback,
            )

        assert result.model == "qwen3:72b"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_ollama_response_data(content: str = "test") -> dict:
    """Helper to create a valid Ollama response dict."""
    return {
        "model": "test-model",
        "message": {"content": content, "tool_calls": []},
        "done": True,
        "done_reason": "stop",
        "prompt_eval_count": 10,
        "eval_count": 5,
    }
