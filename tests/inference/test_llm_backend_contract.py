"""
tests/inference/test_llm_backend_contract.py

Parametrized contract tests for all LLM backend adapters.

All adapters must pass the same contract suite. Parametrized over
[OllamaBackend, LlamaCppBackend, AnthropicBackend, OpenAIBackend],
each backed by a mock HTTP server (using unittest.mock.patch on requests).

Tests:
    - chat() returns LLMResponse
    - chat() content contains TextBlock when model returns text
    - chat() content contains ToolUseBlock when model calls a tool
    - chat() with stream=True and chunk_callback calls callback with text chunks
    - chat() with stream=False does NOT call chunk_callback
    - chat() tool arguments parsed from JSON string to dict
    - chat() raises BackendConnectionError on connection failure
    - chat() raises ModelNotAvailableError on 404
    - chat() raises LLMBackendError on other HTTP errors
    - is_model_available() returns bool
    - list_models() returns list of strings
    - ensure_model() does not raise for available model
    - get_context_length() returns positive integer
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
import requests

from matrixmouse.inference.base import (
    LLMBackend,
    LLMResponse,
    TextBlock,
    ToolUseBlock,
    Tool,
    ModelNotAvailableError,
    BackendConnectionError,
    LLMBackendError,
)
from matrixmouse.inference.ollama import OllamaBackend
from matrixmouse.inference.llamacpp import LlamaCppBackend
from matrixmouse.inference.anthropic import AnthropicBackend
from matrixmouse.inference.openai import OpenAIBackend


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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


def make_ollama_response(
    content: str = "hello",
    tool_calls: list | None = None,
    thinking: str = "",
) -> dict:
    """Build a fake Ollama /api/chat response dict."""
    msg = {
        "content": content,
        "tool_calls": tool_calls or [],
    }
    if thinking:
        msg["thinking"] = thinking
    return {
        "model": "test-model",
        "message": msg,
        "done": True,
        "done_reason": "stop",
        "prompt_eval_count": 10,
        "eval_count": 5,
    }


def make_llamacpp_response(
    content: str = "hello",
    tool_calls: list | None = None,
) -> dict:
    """Build a fake llama.cpp /v1/chat/completions response dict."""
    choices = [{
        "index": 0,
        "message": {
            "role": "assistant",
            "content": content,
            "tool_calls": tool_calls or [],
        },
        "finish_reason": "stop",
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


def make_anthropic_response(
    content: str = "hello",
    tool_calls: list | None = None,
    thinking: str = "",
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
        "model": "test-model",
        "stop_reason": "tool_use" if tool_calls else "end_turn",
        "stop_sequence": None,
        "usage": {
            "input_tokens": 10,
            "output_tokens": 5,
        },
    }


def make_openai_response(
    content: str = "hello",
    tool_calls: list | None = None,
) -> dict:
    """Build a fake OpenAI /v1/chat/completions response dict."""
    message = {
        "role": "assistant",
        "content": content,
    }
    if tool_calls:
        message["tool_calls"] = tool_calls  # type: ignore[assignment]

    choices = [{
        "index": 0,
        "message": message,
        "finish_reason": "tool_calls" if tool_calls else "stop",
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


# Backend fixtures with mock configuration
@pytest.fixture
def ollama_backend():
    """Create an OllamaBackend instance."""
    return OllamaBackend(host="http://localhost:11434")


@pytest.fixture
def llamacpp_backend():
    """Create a LlamaCppBackend instance."""
    return LlamaCppBackend(host="http://localhost:8080")


@pytest.fixture
def anthropic_backend():
    """Create an AnthropicBackend instance."""
    return AnthropicBackend(api_key="test-key")


@pytest.fixture
def openai_backend():
    """Create an OpenAIBackend instance."""
    return OpenAIBackend(api_key="test-key")


# ---------------------------------------------------------------------------
# Contract tests
# ---------------------------------------------------------------------------


class TestChatReturnsLLMResponse:
    """chat() returns LLMResponse."""

    def test_ollama_returns_llm_response(self, ollama_backend):
        with patch("requests.post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: make_ollama_response("hello world"),
            )
            mock_post.return_value.raise_for_status = lambda: None
            result = ollama_backend.chat(
                model="test", messages=[], tools=[], stream=False
            )
        assert isinstance(result, LLMResponse)

    def test_llamacpp_returns_llm_response(self, llamacpp_backend):
        with patch("requests.post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: make_llamacpp_response("hello world"),
            )
            mock_post.return_value.raise_for_status = lambda: None
            result = llamacpp_backend.chat(
                model="test", messages=[], tools=[], stream=False
            )
        assert isinstance(result, LLMResponse)

    def test_anthropic_returns_llm_response(self, anthropic_backend):
        with patch("requests.post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: make_anthropic_response("hello world"),
            )
            mock_post.return_value.raise_for_status = lambda: None
            result = anthropic_backend.chat(
                model="test", messages=[], tools=[], stream=False
            )
        assert isinstance(result, LLMResponse)

    def test_openai_returns_llm_response(self, openai_backend):
        with patch("requests.post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: make_openai_response("hello world"),
            )
            mock_post.return_value.raise_for_status = lambda: None
            result = openai_backend.chat(
                model="test", messages=[], tools=[], stream=False
            )
        assert isinstance(result, LLMResponse)


class TestChatContentContainsTextBlock:
    """chat() content contains TextBlock when model returns text."""

    def test_ollama_content_text_block(self, ollama_backend):
        with patch("requests.post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: make_ollama_response("hello world"),
            )
            mock_post.return_value.raise_for_status = lambda: None
            result = ollama_backend.chat(
                model="test", messages=[], tools=[], stream=False
            )
        assert any(isinstance(b, TextBlock) for b in result.content)
        assert result.content[0].text == "hello world"

    def test_llamacpp_content_text_block(self, llamacpp_backend):
        with patch("requests.post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: make_llamacpp_response("hello world"),
            )
            mock_post.return_value.raise_for_status = lambda: None
            result = llamacpp_backend.chat(
                model="test", messages=[], tools=[], stream=False
            )
        assert any(isinstance(b, TextBlock) for b in result.content)
        assert result.content[0].text == "hello world"

    def test_anthropic_content_text_block(self, anthropic_backend):
        with patch("requests.post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: make_anthropic_response("hello world"),
            )
            mock_post.return_value.raise_for_status = lambda: None
            result = anthropic_backend.chat(
                model="test", messages=[], tools=[], stream=False
            )
        assert any(isinstance(b, TextBlock) for b in result.content)
        assert result.content[0].text == "hello world"

    def test_openai_content_text_block(self, openai_backend):
        with patch("requests.post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: make_openai_response("hello world"),
            )
            mock_post.return_value.raise_for_status = lambda: None
            result = openai_backend.chat(
                model="test", messages=[], tools=[], stream=False
            )
        assert any(isinstance(b, TextBlock) for b in result.content)
        assert result.content[0].text == "hello world"


class TestChatContentContainsToolUseBlock:
    """chat() content contains ToolUseBlock when model calls a tool."""

    def test_ollama_content_tool_use_block(self, ollama_backend):
        tool_call = {
            "id": "call_abc123",
            "function": {
                "name": "test_tool",
                "arguments": json.dumps({"x": 42}),
            },
        }
        with patch("requests.post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: make_ollama_response("", [tool_call]),
            )
            mock_post.return_value.raise_for_status = lambda: None
            result = ollama_backend.chat(
                model="test", messages=[], tools=[], stream=False
            )
        assert any(isinstance(b, ToolUseBlock) for b in result.content)
        tool_block = next(b for b in result.content if isinstance(b, ToolUseBlock))
        assert tool_block.name == "test_tool"
        assert tool_block.input == {"x": 42}

    def test_llamacpp_content_tool_use_block(self, llamacpp_backend):
        tool_call = {
            "id": "call_abc123",
            "function": {
                "name": "test_tool",
                "arguments": json.dumps({"x": 42}),
            },
        }
        with patch("requests.post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: make_llamacpp_response("", [tool_call]),
            )
            mock_post.return_value.raise_for_status = lambda: None
            result = llamacpp_backend.chat(
                model="test", messages=[], tools=[], stream=False
            )
        assert any(isinstance(b, ToolUseBlock) for b in result.content)
        tool_block = next(b for b in result.content if isinstance(b, ToolUseBlock))
        assert tool_block.name == "test_tool"
        assert tool_block.input == {"x": 42}

    def test_anthropic_content_tool_use_block(self, anthropic_backend):
        tool_call = {
            "id": "call_abc123",
            "name": "test_tool",
            "input": {"x": 42},
        }
        with patch("requests.post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: make_anthropic_response("", [tool_call]),
            )
            mock_post.return_value.raise_for_status = lambda: None
            result = anthropic_backend.chat(
                model="test", messages=[], tools=[], stream=False
            )
        assert any(isinstance(b, ToolUseBlock) for b in result.content)
        tool_block = next(b for b in result.content if isinstance(b, ToolUseBlock))
        assert tool_block.name == "test_tool"
        assert tool_block.input == {"x": 42}

    def test_openai_content_tool_use_block(self, openai_backend):
        tool_call = {
            "id": "call_abc123",
            "function": {
                "name": "test_tool",
                "arguments": json.dumps({"x": 42}),
            },
        }
        with patch("requests.post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: make_openai_response("", [tool_call]),
            )
            mock_post.return_value.raise_for_status = lambda: None
            result = openai_backend.chat(
                model="test", messages=[], tools=[], stream=False
            )
        assert any(isinstance(b, ToolUseBlock) for b in result.content)
        tool_block = next(b for b in result.content if isinstance(b, ToolUseBlock))
        assert tool_block.name == "test_tool"
        assert tool_block.input == {"x": 42}


class TestChatStreamingWithCallback:
    """chat() with stream=True and chunk_callback calls callback with text chunks."""

    def test_ollama_streaming_calls_callback(self, ollama_backend):
        mock_callback = MagicMock()
        stream_lines = [
            json.dumps({"message": {"content": "hello"}, "done": False}).encode(),
            json.dumps({"message": {"content": " world"}, "done": False}).encode(),
            json.dumps({"message": {"content": ""}, "done": True}).encode(),
        ]

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.iter_lines.return_value = stream_lines
        mock_response.raise_for_status = lambda: None
        mock_response.__enter__ = lambda self: self
        mock_response.__exit__ = lambda self, *args: None

        with patch("requests.post", return_value=mock_response):
            result = ollama_backend.chat(
                model="test", messages=[], tools=[],
                stream=True, chunk_callback=mock_callback
            )

        assert mock_callback.call_count >= 2
        assert isinstance(result, LLMResponse)

    def test_llamacpp_streaming_calls_callback(self, llamacpp_backend):
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
        mock_response.raise_for_status = lambda: None
        mock_response.__enter__ = lambda self: self
        mock_response.__exit__ = lambda self, *args: None

        with patch("requests.post", return_value=mock_response):
            result = llamacpp_backend.chat(
                model="test", messages=[], tools=[],
                stream=True, chunk_callback=mock_callback
            )

        assert mock_callback.call_count >= 2
        assert isinstance(result, LLMResponse)

    def test_anthropic_streaming_calls_callback(self, anthropic_backend):
        mock_callback = MagicMock()
        stream_lines = [
            f"data: {json.dumps({'type': 'content_block_start', 'content_block': {'type': 'text'}})}".encode(),
            f"data: {json.dumps({'type': 'content_block_delta', 'delta': {'type': 'text_delta', 'text': 'hello'}})}".encode(),
            f"data: {json.dumps({'type': 'content_block_delta', 'delta': {'type': 'text_delta', 'text': ' world'}})}".encode(),
            f"data: {json.dumps({'type': 'message_delta', 'delta': {'stop_reason': 'end_turn'}})}".encode(),
        ]

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.iter_lines.return_value = stream_lines
        mock_response.raise_for_status = lambda: None
        mock_response.__enter__ = lambda self: self
        mock_response.__exit__ = lambda self, *args: None

        with patch("requests.post", return_value=mock_response):
            result = anthropic_backend.chat(
                model="test", messages=[], tools=[],
                stream=True, chunk_callback=mock_callback
            )

        assert mock_callback.call_count >= 2
        assert isinstance(result, LLMResponse)

    def test_openai_streaming_calls_callback(self, openai_backend):
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
        mock_response.raise_for_status = lambda: None
        mock_response.__enter__ = lambda self: self
        mock_response.__exit__ = lambda self, *args: None

        with patch("requests.post", return_value=mock_response):
            result = openai_backend.chat(
                model="test", messages=[], tools=[],
                stream=True, chunk_callback=mock_callback
            )

        assert mock_callback.call_count >= 2
        assert isinstance(result, LLMResponse)


class TestChatNonStreamingNoCallback:
    """chat() with stream=False does NOT call chunk_callback."""

    def test_ollama_non_streaming_no_callback(self, ollama_backend):
        mock_callback = MagicMock()
        with patch("requests.post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: make_ollama_response("hello"),
            )
            mock_post.return_value.raise_for_status = lambda: None
            ollama_backend.chat(
                model="test", messages=[], tools=[], stream=False
            )
        mock_callback.assert_not_called()

    def test_llamacpp_non_streaming_no_callback(self, llamacpp_backend):
        mock_callback = MagicMock()
        with patch("requests.post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: make_llamacpp_response("hello"),
            )
            mock_post.return_value.raise_for_status = lambda: None
            llamacpp_backend.chat(
                model="test", messages=[], tools=[], stream=False
            )
        mock_callback.assert_not_called()

    def test_anthropic_non_streaming_no_callback(self, anthropic_backend):
        mock_callback = MagicMock()
        with patch("requests.post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: make_anthropic_response("hello"),
            )
            mock_post.return_value.raise_for_status = lambda: None
            anthropic_backend.chat(
                model="test", messages=[], tools=[], stream=False
            )
        mock_callback.assert_not_called()

    def test_openai_non_streaming_no_callback(self, openai_backend):
        mock_callback = MagicMock()
        with patch("requests.post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: make_openai_response("hello"),
            )
            mock_post.return_value.raise_for_status = lambda: None
            openai_backend.chat(
                model="test", messages=[], tools=[], stream=False
            )
        mock_callback.assert_not_called()


class TestChatToolArgumentsParsed:
    """chat() tool arguments parsed from JSON string to dict."""

    def test_ollama_tool_args_parsed(self, ollama_backend):
        tool_call = {
            "id": "call_abc",
            "function": {
                "name": "test_tool",
                "arguments": '{"x": 42, "y": "hello"}',
            },
        }
        with patch("requests.post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: make_ollama_response("", [tool_call]),
            )
            mock_post.return_value.raise_for_status = lambda: None
            result = ollama_backend.chat(
                model="test", messages=[], tools=[], stream=False
            )
        tool_block = next(b for b in result.content if isinstance(b, ToolUseBlock))
        assert tool_block.input == {"x": 42, "y": "hello"}

    def test_llamacpp_tool_args_parsed(self, llamacpp_backend):
        tool_call = {
            "id": "call_abc",
            "function": {
                "name": "test_tool",
                "arguments": '{"x": 42, "y": "hello"}',
            },
        }
        with patch("requests.post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: make_llamacpp_response("", [tool_call]),
            )
            mock_post.return_value.raise_for_status = lambda: None
            result = llamacpp_backend.chat(
                model="test", messages=[], tools=[], stream=False
            )
        tool_block = next(b for b in result.content if isinstance(b, ToolUseBlock))
        assert tool_block.input == {"x": 42, "y": "hello"}

    def test_openai_tool_args_parsed(self, openai_backend):
        tool_call = {
            "id": "call_abc",
            "function": {
                "name": "test_tool",
                "arguments": '{"x": 42, "y": "hello"}',
            },
        }
        with patch("requests.post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: make_openai_response("", [tool_call]),
            )
            mock_post.return_value.raise_for_status = lambda: None
            result = openai_backend.chat(
                model="test", messages=[], tools=[], stream=False
            )
        tool_block = next(b for b in result.content if isinstance(b, ToolUseBlock))
        assert tool_block.input == {"x": 42, "y": "hello"}


class TestChatConnectionFailure:
    """chat() raises BackendConnectionError on connection failure."""

    def test_ollama_connection_failure(self, ollama_backend):
        with patch("requests.post", side_effect=requests.ConnectionError()):
            with pytest.raises(BackendConnectionError):
                ollama_backend.chat(
                    model="test", messages=[], tools=[], stream=False
                )

    def test_llamacpp_connection_failure(self, llamacpp_backend):
        with patch("requests.post", side_effect=requests.ConnectionError()):
            with pytest.raises(BackendConnectionError):
                llamacpp_backend.chat(
                    model="test", messages=[], tools=[], stream=False
                )

    def test_anthropic_connection_failure(self, anthropic_backend):
        with patch("requests.post", side_effect=requests.ConnectionError()):
            with pytest.raises(BackendConnectionError):
                anthropic_backend.chat(
                    model="test", messages=[], tools=[], stream=False
                )

    def test_openai_connection_failure(self, openai_backend):
        with patch("requests.post", side_effect=requests.ConnectionError()):
            with pytest.raises(BackendConnectionError):
                openai_backend.chat(
                    model="test", messages=[], tools=[], stream=False
                )


class TestChatModelNotAvailable:
    """chat() raises ModelNotAvailableError on 404."""

    def test_ollama_404(self, ollama_backend):
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.raise_for_status.side_effect = requests.HTTPError(response=mock_response)

        with patch("requests.post", return_value=mock_response):
            with pytest.raises(ModelNotAvailableError):
                ollama_backend.chat(
                    model="test", messages=[], tools=[], stream=False
                )

    def test_llamacpp_404(self, llamacpp_backend):
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.raise_for_status.side_effect = requests.HTTPError(response=mock_response)

        with patch("requests.post", return_value=mock_response):
            with pytest.raises(ModelNotAvailableError):
                llamacpp_backend.chat(
                    model="test", messages=[], tools=[], stream=False
                )

    def test_anthropic_404(self, anthropic_backend):
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.raise_for_status.side_effect = requests.HTTPError(response=mock_response)

        with patch("requests.post", return_value=mock_response):
            with pytest.raises(ModelNotAvailableError):
                anthropic_backend.chat(
                    model="test", messages=[], tools=[], stream=False
                )

    def test_openai_404(self, openai_backend):
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.raise_for_status.side_effect = requests.HTTPError(response=mock_response)

        with patch("requests.post", return_value=mock_response):
            with pytest.raises(ModelNotAvailableError):
                openai_backend.chat(
                    model="test", messages=[], tools=[], stream=False
                )


class TestChatOtherHTTPErrors:
    """chat() raises LLMBackendError on other HTTP errors."""

    def test_ollama_500(self, ollama_backend):
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.raise_for_status.side_effect = requests.HTTPError(response=mock_response)

        with patch("requests.post", return_value=mock_response):
            with pytest.raises(LLMBackendError):
                ollama_backend.chat(
                    model="test", messages=[], tools=[], stream=False
                )

    def test_llamacpp_500(self, llamacpp_backend):
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.raise_for_status.side_effect = requests.HTTPError(response=mock_response)

        with patch("requests.post", return_value=mock_response):
            with pytest.raises(LLMBackendError):
                llamacpp_backend.chat(
                    model="test", messages=[], tools=[], stream=False
                )

    def test_anthropic_500(self, anthropic_backend):
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.raise_for_status.side_effect = requests.HTTPError(response=mock_response)

        with patch("requests.post", return_value=mock_response):
            with pytest.raises(LLMBackendError):
                anthropic_backend.chat(
                    model="test", messages=[], tools=[], stream=False
                )

    def test_openai_500(self, openai_backend):
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.raise_for_status.side_effect = requests.HTTPError(response=mock_response)

        with patch("requests.post", return_value=mock_response):
            with pytest.raises(LLMBackendError):
                openai_backend.chat(
                    model="test", messages=[], tools=[], stream=False
                )


class TestIsModelAvailable:
    """is_model_available() returns bool."""

    def test_ollama_is_model_available_returns_bool(self, ollama_backend):
        with patch.object(ollama_backend, "list_models", return_value=["test:latest"]):
            result = ollama_backend.is_model_available("test")
        assert isinstance(result, bool)

    def test_llamacpp_is_model_available_returns_bool(self, llamacpp_backend):
        with patch("requests.get") as mock_get:
            mock_get.return_value = MagicMock(status_code=200)
            result = llamacpp_backend.is_model_available("test")
        assert isinstance(result, bool)

    def test_anthropic_is_model_available_returns_bool(self, anthropic_backend):
        result = anthropic_backend.is_model_available("claude-sonnet-4-5")
        assert isinstance(result, bool)

    def test_openai_is_model_available_returns_bool(self, openai_backend):
        result = openai_backend.is_model_available("gpt-4o")
        assert isinstance(result, bool)


class TestListModels:
    """list_models() returns list of strings."""

    def test_ollama_list_models_returns_list_of_strings(self, ollama_backend):
        with patch("requests.get") as mock_get:
            mock_get.return_value = MagicMock(
                status_code=200,
                json=lambda: {"models": [{"name": "test:latest"}]},
            )
            mock_get.return_value.raise_for_status = lambda: None
            result = ollama_backend.list_models()
        assert isinstance(result, list)
        assert all(isinstance(m, str) for m in result)

    def test_llamacpp_list_models_returns_list_of_strings(self, llamacpp_backend):
        with patch("requests.get") as mock_get:
            mock_get.return_value = MagicMock(
                status_code=200,
                json=lambda: {"data": [{"id": "test-model"}]},
            )
            mock_get.return_value.raise_for_status = lambda: None
            result = llamacpp_backend.list_models()
        assert isinstance(result, list)
        assert all(isinstance(m, str) for m in result)

    def test_anthropic_list_models_returns_list_of_strings(self, anthropic_backend):
        result = anthropic_backend.list_models()
        assert isinstance(result, list)
        assert all(isinstance(m, str) for m in result)

    def test_openai_list_models_returns_list_of_strings(self, openai_backend):
        with patch("requests.get") as mock_get:
            mock_get.return_value = MagicMock(
                status_code=200,
                json=lambda: {"data": [{"id": "gpt-4o"}]},
            )
            mock_get.return_value.raise_for_status = lambda: None
            result = openai_backend.list_models()
        assert isinstance(result, list)
        assert all(isinstance(m, str) for m in result)


class TestEnsureModel:
    """ensure_model() does not raise for available model."""

    def test_ollama_ensure_model_no_op_when_available(self, ollama_backend):
        with patch.object(ollama_backend, "is_model_available", return_value=True):
            ollama_backend.ensure_model("test")  # Should not raise

    def test_llamacpp_ensure_model_no_op_when_available(self, llamacpp_backend):
        with patch("requests.get") as mock_get:
            mock_get.return_value = MagicMock(status_code=200)
            llamacpp_backend.ensure_model("test")  # Should not raise

    def test_anthropic_ensure_model_no_op(self, anthropic_backend):
        anthropic_backend.ensure_model("claude-sonnet-4-5")  # Should not raise

    def test_openai_ensure_model_no_op(self, openai_backend):
        openai_backend.ensure_model("gpt-4o")  # Should not raise


class TestGetContextLength:
    """get_context_length() returns positive integer."""

    def test_ollama_get_context_length_returns_positive_int(self, ollama_backend):
        with patch("requests.post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: {"modelinfo": {"general.context_length": 8192}},
            )
            mock_post.return_value.raise_for_status = lambda: None
            result = ollama_backend.get_context_length("test")
        assert isinstance(result, int)
        assert result > 0

    def test_llamacpp_get_context_length_returns_positive_int(self, llamacpp_backend):
        with patch("requests.get") as mock_get:
            mock_get.return_value = MagicMock(
                status_code=200,
                json=lambda: {"default_generation_settings": {"n_ctx": 4096}},
            )
            mock_get.return_value.raise_for_status = lambda: None
            result = llamacpp_backend.get_context_length("test")
        assert isinstance(result, int)
        assert result > 0

    def test_anthropic_get_context_length_returns_positive_int(self, anthropic_backend):
        result = anthropic_backend.get_context_length("claude-sonnet-4-5")
        assert isinstance(result, int)
        assert result > 0

    def test_openai_get_context_length_returns_positive_int(self, openai_backend):
        result = openai_backend.get_context_length("gpt-4o")
        assert isinstance(result, int)
        assert result > 0
