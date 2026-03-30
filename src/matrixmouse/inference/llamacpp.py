"""matrixmouse/inference/llamacpp.py

LLM backend adapter for a llama.cpp HTTP server.

llama.cpp's server exposes an OpenAI-compatible chat endpoint at
``/v1/chat/completions``.  Tool schemas use the OpenAI convention
(``parameters`` key).  Message history translation follows the same pattern
as ``OllamaBackend`` — see ``openai_compat.py`` for details.

The server is typically started with::

    llama-server -m model.gguf --port 8080 -c 32768

Context length is queried via ``GET /props`` which returns
``default_generation_settings.n_ctx`` — the actual context size the server
was started with.

Streaming is handled internally: when ``stream=True`` and a
``chunk_callback`` is provided, text tokens are forwarded to the callback
via server-sent events.  The return value is always a fully assembled
``LLMResponse``.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Callable

import requests

from matrixmouse.inference.base import (
    LLMBackend,
    LLMResponse,
    TextBlock,
    ThinkingBlock,
    ToolUseBlock,
    Tool,
    ModelNotAvailableError,
    BackendConnectionError,
    LLMBackendError,
)
from matrixmouse.inference.openai_compat import to_openai_messages, finalise_tool_calls

logger = logging.getLogger(__name__)

_STOP_REASON_MAP: dict[str, str] = {
    "stop":         "end_turn",
    "tool_calls":   "tool_use",
    "length":       "max_tokens",
    "eos":          "end_turn",
}


def _translate_schema(tool: Tool) -> dict:
    """Translate a Tool's input_schema into OpenAI function-calling format.

    Args:
        tool: Tool descriptor with an Anthropic-convention schema.

    Returns:
        Tool dict in OpenAI format.
    """
    return {
        "type": "function",
        "function": {
            "name":        tool.schema["name"],
            "description": tool.schema.get("description", ""),
            "parameters":  tool.schema.get("input_schema", {}),
        },
    }


class LlamaCppBackend(LLMBackend):
    """LLM backend adapter for a llama.cpp HTTP server.

    Instantiated once by the router and reused across all inference calls
    that target the same llama.cpp host.  Thread-safe for concurrent
    ``chat()`` calls.

    The ``model`` parameter passed to ``chat()`` is informational only —
    llama.cpp serves a single model per server instance, loaded at startup.
    It is sent in the request payload for logging purposes but the server
    ignores it.

    Args:
        host: Base URL of the llama.cpp server, e.g.
            ``"http://localhost:8080"``.  Trailing slashes are stripped.
        timeout: HTTP timeout in seconds.
    """

    def __init__(
        self,
        host: str = "http://localhost:8080",
        timeout: int = 3600,
    ) -> None:
        self._host = host.rstrip("/")
        self._timeout = timeout
        logger.debug("LlamaCppBackend initialised: host=%s", self._host)

    # ------------------------------------------------------------------
    # LLMBackend interface
    # ------------------------------------------------------------------

    def chat(
        self,
        model: str,
        messages: list,
        tools: list[Tool],
        stream: bool = False,
        think: bool = False,
        chunk_callback: Callable[[str], None] | None = None,
    ) -> LLMResponse:
        """Send a chat completion request to the llama.cpp server.

        Args:
            model: Model identifier — informational, included in the
                payload but ignored by the server (it serves one model).
            messages: Conversation history in standard role/content format.
            tools: Tool descriptors available for this call.
            stream: If ``True`` and ``chunk_callback`` is provided, text
                tokens are forwarded to the callback as they arrive via SSE.
            think: Not natively supported by llama.cpp's HTTP server.
                Ignored — no ThinkingBlocks will be produced.
            chunk_callback: Called with each text chunk when streaming.
                Ignored if ``stream`` is ``False``.

        Returns:
            Fully assembled ``LLMResponse``.

        Raises:
            ModelNotAvailableError: If the server returns 404.
            BackendConnectionError: If the server cannot be reached.
            LLMBackendError: For other API errors.
        """
        payload: dict = {
            "model":    model,
            "messages": to_openai_messages(messages),
            "stream":   stream and chunk_callback is not None,
        }

        if tools:
            payload["tools"] = [_translate_schema(t) for t in tools]

        url = f"{self._host}/v1/chat/completions"

        try:
            if payload["stream"]:
                return self._chat_streaming(url, payload, chunk_callback)  # type: ignore[arg-type]
            else:
                return self._chat_blocking(url, payload)
        except requests.ConnectionError as e:
            raise BackendConnectionError(
                f"Could not connect to llama.cpp at {self._host}: {e}"
            ) from e
        except requests.Timeout as e:
            raise BackendConnectionError(
                f"llama.cpp request timed out at {self._host}: {e}"
            ) from e
        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else "?"
            if status == 404:
                raise ModelNotAvailableError(
                    f"llama.cpp server at {self._host} returned 404. "
                    "Verify the server is running and the endpoint is correct."
                ) from e
            raise LLMBackendError(
                f"llama.cpp API error {status}: {e}"
            ) from e

    def is_model_available(self, model: str) -> bool:
        """Check whether the llama.cpp server is reachable.

        llama.cpp serves a single model per server instance — if the
        server responds, the model is available.

        Args:
            model: Ignored — included for interface compatibility.

        Returns:
            ``True`` if the server is reachable.
        """
        try:
            resp = requests.get(
                f"{self._host}/health",
                timeout=10,
            )
            return resp.status_code == 200
        except (requests.ConnectionError, requests.Timeout):
            return False

    def list_models(self) -> list[str]:
        """Return the model loaded on this llama.cpp instance.

        Queries ``/v1/models`` if available; falls back to a single
        placeholder entry derived from the host.

        Returns:
            List containing the model identifier(s) reported by the server.
        """
        try:
            resp = requests.get(
                f"{self._host}/v1/models",
                timeout=self._timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            return [m["id"] for m in data.get("data", [])]
        except Exception:
            # llama.cpp may not expose /v1/models — not a fatal error
            return []

    def get_context_length(self, model: str) -> int:
        """Query the llama.cpp server for the loaded model's context length.

        Reads ``default_generation_settings.n_ctx`` from ``GET /props``,
        which reflects the ``-c`` / ``--ctx-size`` flag the server was
        started with.

        Falls back to 32768 if the value cannot be determined.

        Args:
            model: Ignored — the server knows its own context length.

        Returns:
            Context length in tokens.
        """
        fallback = 32768
        try:
            resp = requests.get(
                f"{self._host}/props",
                timeout=self._timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            n_ctx = (
                data
                .get("default_generation_settings", {})
                .get("n_ctx")
            )
            if n_ctx is not None:
                return int(n_ctx)
            logger.warning(
                "Could not find n_ctx in /props response from %s. "
                "Using fallback: %d",
                self._host, fallback,
            )
            return fallback
        except Exception as e:
            logger.warning(
                "Failed to query context length from llama.cpp at %s: %s. "
                "Using fallback: %d",
                self._host, e, fallback,
            )
            return fallback

    def ensure_model(self, model: str) -> None:
        """Verify the llama.cpp server is reachable and serving a model.

        llama.cpp loads its model at startup — there is nothing to pull.
        This method checks that the server responds to ``/health``.

        Args:
            model: Ignored — included for interface compatibility.

        Raises:
            ModelNotAvailableError: If the server is not reachable.
        """
        try:
            resp = requests.get(f"{self._host}/health", timeout=10)
            if resp.status_code != 200:
                raise ModelNotAvailableError(
                    f"llama.cpp server at {self._host} returned "
                    f"HTTP {resp.status_code} on /health."
                )
            logger.debug("llama.cpp server healthy at %s.", self._host)
        except requests.ConnectionError as e:
            raise ModelNotAvailableError(
                f"Could not reach llama.cpp server at {self._host}: {e}"
            ) from e

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _chat_blocking(self, url: str, payload: dict) -> LLMResponse:
        """Execute a non-streaming chat request.

        Args:
            url: Full endpoint URL.
            payload: Request body dict.

        Returns:
            Assembled ``LLMResponse``.
        """
        resp = requests.post(url, json=payload, timeout=self._timeout)
        resp.raise_for_status()
        return self._parse_response(resp.json())

    def _chat_streaming(
        self,
        url: str,
        payload: dict,
        chunk_callback: Callable[[str], None],
    ) -> LLMResponse:
        """Execute a streaming chat request via SSE.

        Args:
            url: Full endpoint URL.
            payload: Request body dict (must have ``stream: true``).
            chunk_callback: Called with each text token.

        Returns:
            Assembled ``LLMResponse``.
        """
        accumulated_text = ""
        tool_calls_raw: dict[int, dict] = {}  # index → partial call
        input_tokens = 0
        output_tokens = 0
        final_model = payload.get("model", "")
        stop_reason = "end_turn"

        with requests.post(
            url, json=payload, stream=True, timeout=self._timeout
        ) as resp:
            resp.raise_for_status()
            for raw_line in resp.iter_lines():
                if not raw_line:
                    continue
                line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
                if line.startswith("data: "):
                    line = line[6:]
                if line == "[DONE]":
                    break
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    continue

                choice = (chunk.get("choices") or [{}])[0]
                delta = choice.get("delta", {})

                text_delta = delta.get("content") or ""
                if text_delta:
                    accumulated_text += text_delta
                    chunk_callback(text_delta)

                # Tool call deltas accumulate by index
                for tc_delta in delta.get("tool_calls", []):
                    idx = tc_delta.get("index", 0)
                    if idx not in tool_calls_raw:
                        tool_calls_raw[idx] = {
                            "id": "", "name": "", "arguments": ""
                        }
                    fn = tc_delta.get("function", {})
                    tool_calls_raw[idx]["id"] = (
                        tc_delta.get("id") or tool_calls_raw[idx]["id"]
                    )
                    tool_calls_raw[idx]["name"] += fn.get("name", "")
                    tool_calls_raw[idx]["arguments"] += fn.get("arguments", "")

                finish = choice.get("finish_reason")
                if finish:
                    stop_reason = _STOP_REASON_MAP.get(finish, "end_turn")

                usage = chunk.get("usage", {})
                if usage:
                    input_tokens  = usage.get("prompt_tokens", input_tokens)
                    output_tokens = usage.get("completion_tokens", output_tokens)
                    final_model   = chunk.get("model", final_model)

        tool_calls = finalise_tool_calls(tool_calls_raw)
        return self._assemble_response(
            accumulated_text=accumulated_text,
            tool_calls=tool_calls,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model=final_model,
            stop_reason=stop_reason,
        )

    def _parse_response(self, data: dict) -> LLMResponse:
        """Parse a complete (non-streaming) OpenAI-compat response.

        Args:
            data: Parsed JSON response.

        Returns:
            Assembled ``LLMResponse``.
        """
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message", {})
        finish = choice.get("finish_reason", "stop")
        stop_reason = _STOP_REASON_MAP.get(finish, "end_turn")

        raw_tool_calls: dict[int, dict] = {}
        for i, tc in enumerate(msg.get("tool_calls", [])):
            fn = tc.get("function", {})
            raw_tool_calls[i] = {
                "id":        tc.get("id", ""),
                "name":      fn.get("name", ""),
                "arguments": fn.get("arguments", ""),
            }

        tool_calls = finalise_tool_calls(raw_tool_calls)
        usage = data.get("usage", {})

        return self._assemble_response(
            accumulated_text=msg.get("content") or "",
            tool_calls=tool_calls,
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            model=data.get("model", ""),
            stop_reason=stop_reason,
        )

    def _assemble_response(
        self,
        accumulated_text: str,
        tool_calls: list[dict],
        input_tokens: int,
        output_tokens: int,
        model: str,
        stop_reason: str,
    ) -> LLMResponse:
        """Build an ``LLMResponse`` from assembled response data.

        Args:
            accumulated_text: Full text content.
            tool_calls: List of finalised tool call dicts.
            input_tokens: Prompt token count.
            output_tokens: Completion token count.
            model: Model name as reported by the server.
            stop_reason: Normalised stop reason string.

        Returns:
            Assembled ``LLMResponse``.
        """
        content: list = []

        if accumulated_text:
            content.append(TextBlock(text=accumulated_text))

        for tc in tool_calls:
            content.append(ToolUseBlock(
                id=tc["id"],
                name=tc["name"],
                input=tc["input"],
            ))

        if any(isinstance(b, ToolUseBlock) for b in content):
            stop_reason = "tool_use"

        return LLMResponse(
            content=content,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model=model,
            stop_reason=stop_reason,
        )
    