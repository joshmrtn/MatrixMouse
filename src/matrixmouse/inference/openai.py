"""matrixmouse/inference/openai.py

LLM backend adapter for the OpenAI Chat Completions API.

Also usable with any OpenAI-compatible endpoint (e.g. a self-hosted
vLLM or llama.cpp server with OpenAI-compat mode) by overriding
``base_url``.

Authentication uses an API key loaded from the environment by _service.py::

    /etc/matrixmouse/secrets/openai_api_key → os.environ["OPENAI_API_KEY"]

Message history uses the OpenAI convention — structured Anthropic-style
content blocks are translated by ``openai_compat.to_openai_messages`` 
before sending. 

Thinking blocks are dropped (OpenAI does not consume them in history).

Streaming is handled internally via SSE. When ``stream=True`` and a
``chunk_callback`` is provided, text tokens are forwarded as they arrive.
The return value is always a fully assembled ``LLMResponse``.
"""

from __future__ import annotations

from datetime import datetime
import json
import logging
import uuid
from typing import Callable

import requests

from matrixmouse.inference.base import (
    LLMBackend,
    LLMResponse,
    TextBlock,
    TokenBudgetExceededError,
    ToolUseBlock,
    Tool,
    ModelNotAvailableError,
    BackendConnectionError,
    LLMBackendError,
)
from matrixmouse.inference.openai_compat import to_openai_messages, finalise_tool_calls
from matrixmouse.inference.token_budget import TokenBudgetTracker

logger = logging.getLogger(__name__)

# Known context lengths for OpenAI models.
_CONTEXT_LENGTHS: dict[str, int] = {
    "gpt-4o":               128_000,
    "gpt-4o-mini":          128_000,
    "gpt-4-turbo":          128_000,
    "gpt-4-turbo-preview":  128_000,
    "gpt-4":                  8_192,
    "gpt-4-32k":             32_768,
    "gpt-3.5-turbo":         16_385,
    "o1":                   200_000,
    "o1-mini":              128_000,
    "o1-preview":           128_000,
    "o3-mini":              200_000,
}

_DEFAULT_CONTEXT_LENGTH = 128_000

_STOP_REASON_MAP: dict[str, str] = {
    "stop":         "end_turn",
    "tool_calls":   "tool_use",
    "length":       "max_tokens",
    "content_filter": "stop",
}


def _translate_schema(tool: Tool) -> dict:
    """Translate a Tool's input_schema into OpenAI function-calling format.

    Args:
        tool: Tool descriptor with Anthropic-convention schema.

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


def _parse_retry_after(response: requests.Response | None) -> datetime | None:
    """Extract a retry-after datetime from an HTTP error response.
 
    Checks headers in priority order:
        1. ``x-ratelimit-reset-tokens`` (OpenAI, ISO timestamp)
        2. ``x-ratelimit-reset-requests`` (OpenAI, ISO timestamp)
        3. ``Retry-After`` (standard HTTP, seconds as integer)
 
    Args:
        response: The HTTP error response, or None.
 
    Returns:
        UTC-aware datetime of the earliest suggested retry, or None if
        no parseable retry hint is present.
    """
    from datetime import datetime, timezone, timedelta
    if response is None:
        return None
 
    # OpenAI-style ISO timestamp headers (most precise)
    for header in ("x-ratelimit-reset-tokens", "x-ratelimit-reset-requests"):
        raw = response.headers.get(header)
        if raw:
            try:
                dt = datetime.fromisoformat(raw)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except (ValueError, TypeError):
                pass
 
    # Standard Retry-After: integer seconds
    retry_after_raw = response.headers.get("Retry-After")
    if retry_after_raw:
        try:
            seconds = int(retry_after_raw)
            return datetime.now(timezone.utc) + timedelta(seconds=seconds)
        except (ValueError, TypeError):
            pass
 
    return None


class OpenAIBackend(LLMBackend):
    """LLM backend adapter for the OpenAI Chat Completions API.

    Also compatible with any OpenAI-compat endpoint — pass a custom
    ``base_url`` to point at vLLM, a local proxy, or another provider.

    Instantiated once by the router and cached. Thread-safe for concurrent
    ``chat()`` calls.

    Args:
        api_key: OpenAI API key.
        base_url: API base URL. Defaults to ``"https://api.openai.com"``.
        max_tokens: Maximum tokens to generate. Defaults to 4096.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.openai.com",
        max_tokens: int = 4096,
         budget_tracker: TokenBudgetTracker | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._max_tokens = max_tokens
        self._budget_tracker = budget_tracker
        logger.debug("OpenAIBackend initialised: base_url=%s", self._base_url)

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type":  "application/json",
        }

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
        """Send a request to the OpenAI Chat Completions API.

        Args:
            model: OpenAI model identifier, e.g. ``"gpt-4o"``.
            messages: Conversation history in standard role/content format.
            tools: Tool descriptors for this call.
            stream: If ``True`` and ``chunk_callback`` is provided, text
                tokens are forwarded via SSE as they arrive.
            think: Not supported by the standard OpenAI API.
                For o-series models, reasoning is automatic and not
                controlled by this flag.
            chunk_callback: Called with each text chunk when streaming.

        Returns:
            Fully assembled ``LLMResponse``.

        Raises:
            TokenBudgetExceededError: If the OpenAI token budget is exhausted.
            ModelNotAvailableError: On 404.
            BackendConnectionError: If the API cannot be reached.
            LLMBackendError: For other API errors.
        """
        # --- Upfront budget check ---
        if self._budget_tracker is not None:
            self._budget_tracker.check_budget(provider="openai", model=model)

        payload: dict = {
            "model":      model,
            "max_tokens": self._max_tokens,
            "messages":   to_openai_messages(messages),
        }

        if tools:
            payload["tools"] = [_translate_schema(t) for t in tools]

        url = f"{self._base_url}/v1/chat/completions"
        do_stream = stream and chunk_callback is not None

        try:
            if do_stream:
                payload["stream"] = True
                payload["stream_options"] = {"include_usage": True}
                response = self._chat_streaming(url, payload, chunk_callback)  # type: ignore[arg-type]
            else:
                response = self._chat_blocking(url, payload)

            # --- Record usage after success ---
            if self._budget_tracker is not None:
                self._budget_tracker.record(
                    provider="openai",
                    model=model,
                    input_tokens=response.input_tokens,
                    output_tokens=response.output_tokens,
                )
            return response

        except requests.ConnectionError as e:
            raise BackendConnectionError(
                f"Could not connect to OpenAI API at {self._base_url}: {e}"
            ) from e
        except requests.Timeout as e:
            raise BackendConnectionError(
                f"OpenAI API request timed out: {e}"
            ) from e
        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else "?"
            if status in (401, 403):
                raise LLMBackendError(
                    f"OpenAI authentication failed (HTTP {status}). "
                    "Check OPENAI_API_KEY."
                ) from e
            if status == 404:
                raise ModelNotAvailableError(
                    f"OpenAI model \'{model}\' not found (HTTP 404)."
                ) from e
            if status == 429:
                # OpenAI provides Retry-After header and x-ratelimit-reset-* headers
                retry_after = _parse_retry_after(e.response)
                if self._budget_tracker is not None:
                    wait_until = self._budget_tracker.calculate_wait_until_for_provider(
                        provider="openai",
                        api_retry_after=retry_after,
                    )
                else:
                    wait_until = retry_after
                raise TokenBudgetExceededError(
                    provider="openai",
                    period="hour",
                    limit=0,
                    used=0,
                    retry_after=wait_until,
                ) from e
            raise LLMBackendError(
                f"OpenAI API error {status}: {e}"
            ) from e

    def is_model_available(self, model: str) -> bool:
        """Check whether a model identifier is non-empty.

        The OpenAI API does not provide a reliable availability check
        without making an inference call. Returns True for any non-empty
        model string.

        Args:
            model: OpenAI model identifier.

        Returns:
            ``True`` if the model string is non-empty.
        """
        return bool(model)

    def list_models(self) -> list[str]:
        """Return the list of known OpenAI model identifiers.

        Attempts to query ``/v1/models``; falls back to the hardcoded
        context length table keys on error.

        Returns:
            List of model identifier strings.
        """
        try:
            resp = requests.get(
                f"{self._base_url}/v1/models",
                headers=self._headers(),
                timeout=30,
            )
            resp.raise_for_status()
            return [m["id"] for m in resp.json().get("data", [])]
        except Exception:
            return list(_CONTEXT_LENGTHS.keys())

    def get_context_length(self, model: str) -> int:
        """Return the context length for an OpenAI model.

        Uses a hardcoded lookup table with prefix matching for versioned
        model strings. Defaults to 128k for unrecognised models.

        Args:
            model: OpenAI model identifier.

        Returns:
            Context length in tokens.
        """
        if model in _CONTEXT_LENGTHS:
            return _CONTEXT_LENGTHS[model]
        for known, length in _CONTEXT_LENGTHS.items():
            if model.startswith(known):
                return length
        logger.warning(
            "Unknown OpenAI model '%s'. Using default context length: %d",
            model, _DEFAULT_CONTEXT_LENGTH,
        )
        return _DEFAULT_CONTEXT_LENGTH

    def ensure_model(self, model: str) -> None:
        """No-op — model availability is OpenAI's concern.

        Args:
            model: Ignored.
        """
        logger.debug(
            "OpenAIBackend.ensure_model('%s'): no-op for remote API.",
            model,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _chat_blocking(self, url: str, payload: dict) -> LLMResponse:
        resp = requests.post(
            url, json=payload, headers=self._headers(), timeout=120,
        )
        resp.raise_for_status()
        return self._parse_response(resp.json())

    def _chat_streaming(
        self,
        url: str,
        payload: dict,
        chunk_callback: Callable[[str], None],
    ) -> LLMResponse:
        accumulated_text = ""
        tool_calls_raw: dict[int, dict] = {}
        input_tokens = 0
        output_tokens = 0
        final_model = payload.get("model", "")
        stop_reason = "end_turn"

        with requests.post(
            url, json=payload, headers=self._headers(),
            stream=True, timeout=120,
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

                for tc_delta in delta.get("tool_calls", []):
                    idx = tc_delta.get("index", 0)
                    if idx not in tool_calls_raw:
                        tool_calls_raw[idx] = {"id": "", "name": "", "arguments": ""}
                    fn = tc_delta.get("function", {})
                    tool_calls_raw[idx]["id"] = (
                        tc_delta.get("id") or tool_calls_raw[idx]["id"]
                    )
                    tool_calls_raw[idx]["name"]      += fn.get("name", "")
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

        logger.debug(
            "OpenAIBackend response: model=%s input=%d output=%d stop=%s",
            model, input_tokens, output_tokens, stop_reason,
        )
        return LLMResponse(
            content=content,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model=model,
            stop_reason=stop_reason,
        )
    