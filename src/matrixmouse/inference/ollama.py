"""matrixmouse/inference/ollama.py

LLM backend adapter for a local Ollama server.

Ollama exposes an OpenAI-compatible chat API at /api/chat.  Tool schemas
use the OpenAI convention (``parameters`` key with JSON Schema) rather than
the Anthropic convention (``input_schema``).  This adapter translates between
the two at call time.

Streaming is handled internally: when ``stream=True`` and a
``chunk_callback`` is provided, each text token is forwarded to the callback
as it arrives.  The return value is always a fully assembled ``LLMResponse``.
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

logger = logging.getLogger(__name__)

# Ollama stop reasons → normalised stop_reason values
_STOP_REASON_MAP: dict[str, str] = {
    "stop":       "end_turn",
    "tool_calls": "tool_use",
    "length":     "max_tokens",
}


def _translate_schema(tool: Tool) -> dict:
    """Translate a Tool's input_schema into Ollama's expected format.

    Ollama follows the OpenAI convention: the top-level key is ``parameters``
    rather than ``input_schema``.

    Args:
        tool: Tool descriptor with an Anthropic-convention schema.

    Returns:
        Tool dict ready to pass to the Ollama API.
    """
    return {
        "type": "function",
        "function": {
            "name":        tool.schema["name"],
            "description": tool.schema.get("description", ""),
            "parameters":  tool.schema.get("input_schema", {}),
        },
    }


class OllamaBackend(LLMBackend):
    """LLM backend adapter for a local (or remote) Ollama server.

    Instantiated once by the router and reused across all inference calls
    that target the same Ollama host.  Thread-safe for concurrent ``chat()``
    calls — each call creates its own ``requests.Session``.

    Args:
        host: Base URL of the Ollama server, e.g. ``"http://localhost:11434"``.
            Trailing slashes are stripped.
        timeout: HTTP timeout in seconds for non-streaming requests.
            Streaming requests use this as the read timeout per chunk.
    """

    def __init__(
        self,
        host: str = "http://localhost:11434",
        timeout: int = 3600,
    ) -> None:
        self._host = host.rstrip("/")
        self._timeout = timeout
        logger.debug("OllamaBackend initialised: host=%s", self._host)

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
        """Send a chat completion request to Ollama.

        Args:
            model: Ollama model identifier, e.g. ``"qwen3:4b"``.
            messages: Conversation history in standard role/content format.
            tools: Tool descriptors available for this call.
            stream: If ``True`` and ``chunk_callback`` is provided, text
                tokens are forwarded to the callback as they arrive.
            think: If ``True``, enables Ollama's experimental thinking
                mode where supported. Thinking content is returned as
                ``ThinkingBlock`` entries.
            chunk_callback: Called with each text chunk when streaming.
                Ignored if ``stream`` is ``False``.

        Returns:
            Fully assembled ``LLMResponse``.

        Raises:
            ModelNotAvailableError: If Ollama reports the model is not found.
            BackendConnectionError: If the Ollama server cannot be reached.
            LLMBackendError: For other Ollama API errors.
        """
        payload: dict = {
            "model":    model,
            "messages": self._to_ollama_messages(messages),
            "stream":   stream and chunk_callback is not None,
        }

        if tools:
            payload["tools"] = [_translate_schema(t) for t in tools]

        if think:
            payload["think"] = True

        url = f"{self._host}/api/chat"

        try:
            if payload["stream"]:
                return self._chat_streaming(url, payload, chunk_callback)  # type: ignore[arg-type]
            else:
                return self._chat_blocking(url, payload)
        except requests.ConnectionError as e:
            raise BackendConnectionError(
                f"Could not connect to Ollama at {self._host}: {e}"
            ) from e
        except requests.Timeout as e:
            raise BackendConnectionError(
                f"Ollama request timed out at {self._host}: {e}"
            ) from e
        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else "?"
            if status == 404:
                raise ModelNotAvailableError(
                    f"Model '{model}' not found on Ollama at {self._host}. "
                    "Run ensure_model() to pull it."
                ) from e
            raise LLMBackendError(
                f"Ollama API error {status}: {e}"
            ) from e

    def is_model_available(self, model: str) -> bool:
        """Check whether a model is available on this Ollama instance.

        Args:
            model: Ollama model identifier.

        Returns:
            ``True`` if the model is listed in ``/api/tags``.
        """
        try:
            available = self.list_models()
            # Ollama model names may include a tag — match on base name too
            return any(
                m == model or m.split(":")[0] == model.split(":")[0]
                for m in available
            )
        except (BackendConnectionError, LLMBackendError):
            return False

    def list_models(self) -> list[str]:
        """Return the list of models available on this Ollama instance.

        Returns:
            List of model name strings as reported by ``/api/tags``.

        Raises:
            BackendConnectionError: If the server cannot be reached.
            LLMBackendError: For unexpected API errors.
        """
        url = f"{self._host}/api/tags"
        try:
            resp = requests.get(url, timeout=self._timeout)
            resp.raise_for_status()
            data = resp.json()
            return [m["name"] for m in data.get("models", [])]
        except requests.ConnectionError as e:
            raise BackendConnectionError(
                f"Could not connect to Ollama at {self._host}: {e}"
            ) from e
        except requests.HTTPError as e:
            raise LLMBackendError(
                f"Ollama /api/tags returned {e.response.status_code}"
            ) from e

    def get_context_length(self, model: str) -> int:
        """Query Ollama for the context window length of a model.

        Falls back to 32768 if the value cannot be determined rather than
        raising — a wrong limit is recoverable, a crash at startup is not.

        Args:
            model: Ollama model identifier.

        Returns:
            Context length in tokens.
        """
        fallback = 32768
        try:
            import requests as _req
            resp = _req.post(
                f"{self._host}/api/show",
                json={"name": model},
                timeout=self._timeout,
            )
            resp.raise_for_status()
            model_info = resp.json().get("modelinfo", {}) or {}

            for key in ("general.context_length", "context_length"):
                if key in model_info:
                    return int(model_info[key])

            for key, value in model_info.items():
                if "context_length" in key:
                    return int(value)

            logger.warning(
                "Could not find context_length for '%s'. Using fallback: %d",
                model, fallback,
            )
            return fallback

        except Exception as e:
            logger.warning(
                "Failed to query context length for '%s': %s. Using fallback: %d",
                model, e, fallback,
            )
            return fallback

    def ensure_model(self, model: str) -> None:
        """Attempt to pull a model if it is not already available.

        Performs a blocking pull via ``/api/pull``.  Progress is logged
        at DEBUG level.  If the model is already present, this is a no-op.

        Args:
            model: Ollama model identifier.

        Raises:
            ModelNotAvailableError: If the pull fails.
            BackendConnectionError: If the server cannot be reached.
        """
        if self.is_model_available(model):
            logger.debug("ensure_model: '%s' already available.", model)
            return

        logger.info("Pulling Ollama model '%s' from %s ...", model, self._host)
        url = f"{self._host}/api/pull"
        try:
            # Pull streams progress lines; we consume them to completion
            with requests.post(
                url,
                json={"name": model},
                stream=True,
                timeout=self._timeout,
            ) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if line:
                        try:
                            progress = json.loads(line)
                            logger.debug("pull %s: %s", model, progress.get("status", ""))
                            if progress.get("error"):
                                raise ModelNotAvailableError(
                                    f"Ollama pull error for '{model}': {progress['error']}"
                                )
                        except json.JSONDecodeError:
                            pass
        except requests.ConnectionError as e:
            raise BackendConnectionError(
                f"Could not connect to Ollama at {self._host}: {e}"
            ) from e
        except requests.HTTPError as e:
            raise ModelNotAvailableError(
                f"Failed to pull '{model}' from Ollama: HTTP {e.response.status_code}"
            ) from e

        logger.info("Model '%s' pulled successfully.", model)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _to_ollama_messages(self, messages: list) -> list:
        """Translate canonical message history to Ollama's OpenAI-compat format.

        The canonical format (produced by ``loop._response_to_message``) uses
        Anthropic-style structured content blocks for assistant messages::

            {'role': 'assistant', 'content': [
                {'type': 'thinking', 'thinking': '...'},
                {'type': 'tool_use', 'id': '...', 'name': '...', 'input': {...}},
            ]}

        Ollama expects the OpenAI convention instead::

            {'role': 'assistant', 'content': '...', 'tool_calls': [
                {'id': '...', 'type': 'function',
                 'function': {'name': '...', 'arguments': {...}}}
            ]}

        Tool result messages also differ: the canonical format uses
        ``tool_use_id``; Ollama uses ``tool_call_id``.

        Non-assistant messages with plain string content are passed through
        unchanged.

        Args:
            messages: Canonical message history from loop.py.

        Returns:
            Message list in Ollama's expected format.
        """
        translated = []
        for msg in messages:
            role = msg.get("role", "")

            if role == "assistant":
                content = msg.get("content", "")
                if not isinstance(content, list):
                    # Plain string — pass through unchanged
                    translated.append(msg)
                    continue

                # Structured content blocks — split into text and tool calls
                text_parts: list[str] = []
                tool_calls: list[dict] = []

                for block in content:
                    btype = block.get("type", "")
                    if btype == "text":
                        text_parts.append(block.get("text", ""))
                    elif btype == "thinking":
                        # Thinking blocks are not forwarded to Ollama —
                        # they are internal reasoning and not part of the
                        # conversation history Ollama expects.
                        pass
                    elif btype == "tool_use":
                        tool_calls.append({
                            "id":   block.get("id", ""),
                            "type": "function",
                            "function": {
                                "name":      block.get("name", ""),
                                "arguments": block.get("input", {}),
                            },
                        })

                ollama_msg: dict = {
                    "role":    "assistant",
                    "content": " ".join(text_parts),
                }
                if tool_calls:
                    ollama_msg["tool_calls"] = tool_calls
                translated.append(ollama_msg)

            elif role == "tool":
                # Canonical: tool_use_id. Ollama: tool_call_id.
                translated.append({
                    "role":         "tool",
                    "tool_call_id": msg.get("tool_use_id", msg.get("tool_call_id", "")),
                    "name":         msg.get("name", ""),
                    "content":      msg.get("content", ""),
                })

            else:
                # system, user — pass through unchanged
                translated.append(msg)

        return translated

    def _chat_blocking(self, url: str, payload: dict) -> LLMResponse:
        """Execute a non-streaming chat request.

        Args:
            url: Full Ollama chat endpoint URL.
            payload: Request body dict.

        Returns:
            Assembled ``LLMResponse``.
        """
        resp = requests.post(url, json=payload, timeout=self._timeout)
        resp.raise_for_status()
        data = resp.json()
        return self._parse_response(data)

    def _chat_streaming(
        self,
        url: str,
        payload: dict,
        chunk_callback: Callable[[str], None],
    ) -> LLMResponse:
        """Execute a streaming chat request, forwarding text chunks to callback.

        Assembles the full response from the stream and returns it as a
        complete ``LLMResponse`` once the stream closes.

        Args:
            url: Full Ollama chat endpoint URL.
            payload: Request body dict (must have ``stream: true``).
            chunk_callback: Called with each text token as it arrives.

        Returns:
            Assembled ``LLMResponse``.
        """
        accumulated_text = ""
        accumulated_thinking = ""
        tool_calls: list[dict] = []
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
                try:
                    chunk = json.loads(raw_line)
                except json.JSONDecodeError:
                    logger.warning("OllamaBackend: could not parse stream line: %r", raw_line)
                    continue

                msg = chunk.get("message", {})

                # Text content
                text_delta = msg.get("content", "")
                if text_delta:
                    accumulated_text += text_delta
                    chunk_callback(text_delta)

                # Thinking content (Ollama experimental)
                thinking_delta = msg.get("thinking", "")
                if thinking_delta:
                    accumulated_thinking += thinking_delta

                # Tool calls accumulate across chunks
                for tc in msg.get("tool_calls", []):
                    tool_calls.append(tc)

                # Final chunk carries usage and stop reason
                if chunk.get("done"):
                    final_model = chunk.get("model", final_model)
                    stop_reason = _STOP_REASON_MAP.get(
                        chunk.get("done_reason", "stop"), "end_turn"
                    )
                    prompt_eval = chunk.get("prompt_eval_count", 0)
                    eval_count  = chunk.get("eval_count", 0)
                    input_tokens  = prompt_eval
                    output_tokens = eval_count

        return self._assemble_response(
            accumulated_text=accumulated_text,
            accumulated_thinking=accumulated_thinking,
            tool_calls=tool_calls,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model=final_model,
            stop_reason=stop_reason,
        )

    def _parse_response(self, data: dict) -> LLMResponse:
        """Parse a complete (non-streaming) Ollama response dict.

        Args:
            data: Parsed JSON response from Ollama.

        Returns:
            Assembled ``LLMResponse``.
        """
        msg = data.get("message", {})
        stop_reason = _STOP_REASON_MAP.get(
            data.get("done_reason", "stop"), "end_turn"
        )
        return self._assemble_response(
            accumulated_text=msg.get("content", ""),
            accumulated_thinking=msg.get("thinking", ""),
            tool_calls=msg.get("tool_calls", []),
            input_tokens=data.get("prompt_eval_count", 0),
            output_tokens=data.get("eval_count", 0),
            model=data.get("model", ""),
            stop_reason=stop_reason,
        )

    def _assemble_response(
        self,
        accumulated_text: str,
        accumulated_thinking: str,
        tool_calls: list[dict],
        input_tokens: int,
        output_tokens: int,
        model: str,
        stop_reason: str,
    ) -> LLMResponse:
        """Build an ``LLMResponse`` from assembled stream or blocking data.

        Content block ordering: ThinkingBlock (if any) → TextBlock (if any)
        → ToolUseBlocks.  This mirrors Anthropic's native ordering convention
        and keeps the response shape consistent across adapters.

        Args:
            accumulated_text: Full text content.
            accumulated_thinking: Full thinking/reasoning content.
            tool_calls: List of raw Ollama tool call dicts.
            input_tokens: Prompt token count.
            output_tokens: Completion token count.
            model: Model name as reported by Ollama.
            stop_reason: Normalised stop reason string.

        Returns:
            Assembled ``LLMResponse``.
        """
        content: list = []

        if accumulated_thinking:
            content.append(ThinkingBlock(text=accumulated_thinking))

        if accumulated_text:
            content.append(TextBlock(text=accumulated_text))

        for tc in tool_calls:
            fn = tc.get("function", {})
            raw_args = fn.get("arguments", {})
            # Ollama may return arguments as a JSON string or already parsed
            if isinstance(raw_args, str):
                try:
                    raw_args = json.loads(raw_args)
                except json.JSONDecodeError:
                    logger.warning(
                        "OllamaBackend: could not parse tool arguments as JSON: %r",
                        raw_args,
                    )
                    raw_args = {}

            content.append(ToolUseBlock(
                id=tc.get("id") or f"call_{uuid.uuid4().hex[:8]}",
                name=fn.get("name", ""),
                input=raw_args,
            ))

        # If stop_reason isn't already tool_use, set it based on content
        if any(isinstance(b, ToolUseBlock) for b in content):
            stop_reason = "tool_use"

        return LLMResponse(
            content=content,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model=model,
            stop_reason=stop_reason,
        )