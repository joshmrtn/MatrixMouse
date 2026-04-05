"""matrixmouse/inference/anthropic.py

LLM backend adapter for the Anthropic Messages API.

Authentication uses an API key loaded from the environment by _service.py::

    /etc/matrixmouse/secrets/anthropic_api_key → os.environ["ANTHROPIC_API_KEY"]

The Anthropic API uses its own message and tool schema format natively —
the canonical internal format (Anthropic-style content blocks) maps almost
directly to the wire format, so message translation is minimal compared to
the OpenAI-compat adapters.

Token budget tracking is injected via TokenBudgetTracker.
Usage is enforced — ``chat()`` raises ``TokenBudgetExceededError``
when the configured budget is exceeded.

Streaming is handled internally via the Anthropic streaming API. When
``stream=True`` and ``chunk_callback`` is provided, text tokens are
forwarded as they arrive. The return value is always a fully assembled
``LLMResponse``.
"""

from __future__ import annotations

from datetime import datetime
import logging
from typing import Callable

import requests

from matrixmouse.inference.base import (
    LLMBackend,
    LLMResponse,
    TextBlock,
    ThinkingBlock,
    TokenBudgetExceededError,
    ToolUseBlock,
    Tool,
    ModelNotAvailableError,
    BackendConnectionError,
    LLMBackendError,
)
from matrixmouse.inference.token_budget import TokenBudgetTracker

logger = logging.getLogger(__name__)

# Known context lengths for Anthropic models.
# Used by get_context_length() — the API does not expose this directly.
# Values in tokens. Updated as new models are released.
_CONTEXT_LENGTHS: dict[str, int] = {
    "claude-opus-4-6":          200_000,
    "claude-sonnet-4-6":        200_000,
    "claude-opus-4-5":          200_000,
    "claude-sonnet-4-5":        200_000,
    "claude-haiku-4-5":         200_000,
    "claude-3-5-sonnet-20241022": 200_000,
    "claude-3-5-haiku-20241022":  200_000,
    "claude-3-opus-20240229":   200_000,
    "claude-3-sonnet-20240229": 200_000,
    "claude-3-haiku-20240307":  200_000,
}

# Conservative floor for unrecognised Anthropic models.
# Anthropic's floor has been 200k for all recent models.
_DEFAULT_CONTEXT_LENGTH = 200_000

_STOP_REASON_MAP: dict[str, str] = {
    "end_turn":    "end_turn",
    "tool_use":    "tool_use",
    "max_tokens":  "max_tokens",
    "stop_sequence": "stop",
}

_API_BASE = "https://api.anthropic.com"
_API_VERSION = "2023-06-01"


def _translate_schema(tool: Tool) -> dict:
    """Translate a Tool into Anthropic's native tool format.

    Anthropic uses ``input_schema`` natively — this is the canonical
    internal format, so translation is a passthrough.

    Args:
        tool: Tool descriptor.

    Returns:
        Tool dict in Anthropic format.
    """
    return {
        "name":         tool.schema["name"],
        "description":  tool.schema.get("description", ""),
        "input_schema": tool.schema.get("input_schema", {}),
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


class AnthropicBackend(LLMBackend):
    """LLM backend adapter for the Anthropic Messages API.

    Instantiated once by the router and cached. Thread-safe for concurrent
    ``chat()`` calls.

    Args:
        api_key: Anthropic API key. Loaded from the environment by the
            router — do not pass directly from config.
        max_tokens: Maximum tokens to generate per response. Anthropic
            requires this field; defaults to 8192.
    """

    def __init__(
        self,
        api_key: str,
        max_tokens: int = 8192,
        budget_tracker: TokenBudgetTracker | None = None,
    ) -> None:
        self._api_key = api_key
        self._max_tokens = max_tokens
        self._base_url = _API_BASE
        self._budget_tracker = budget_tracker
        logger.debug("AnthropicBackend initialised.")

    def _headers(self) -> dict:
        return {
            "x-api-key":         self._api_key,
            "anthropic-version": _API_VERSION,
            "content-type":      "application/json",
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
        """Send a request to the Anthropic Messages API.

        Args:
            model: Anthropic model identifier, e.g. ``"claude-sonnet-4-5"``.
            messages: Conversation history. The system message must be the
                first entry with ``role: "system"`` — it is extracted and
                sent as the top-level ``system`` parameter.
            tools: Tool descriptors for this call.
            stream: If ``True`` and ``chunk_callback`` is provided, text
                tokens are forwarded as they arrive.
            think: If ``True``, enables extended thinking via Anthropic's
                beta thinking feature. Thinking tokens appear as
                ``ThinkingBlock`` entries in the response.
            chunk_callback: Called with each text chunk when streaming.

        Returns:
            Fully assembled ``LLMResponse``.

        Raises:
            TokenBudgetExceededError: If the Anthropic token budget is exhausted.
            ModelNotAvailableError: On 404.
            BackendConnectionError: If the API cannot be reached.
            LLMBackendError: For other API errors.
        """
        # --- Upfront budget check ---
        if self._budget_tracker is not None:
            self._budget_tracker.check_budget(provider="anthropic", model=model)

        system, conversation = self._split_system(messages)

        payload: dict = {
            "model":      model,
            "max_tokens": self._max_tokens,
            "messages":   self._to_anthropic_messages(conversation),
        }

        if system:
            payload["system"] = system

        if tools:
            payload["tools"] = [_translate_schema(t) for t in tools]

        if think:
            payload["thinking"] = {
                "type":          "enabled",
                "budget_tokens": min(self._max_tokens // 2, 4096),
            }

        if stream and chunk_callback is not None:
            payload["stream"] = True

        url = f"{self._base_url}/v1/messages"

        try:
            if payload.get("stream"):
                response = self._chat_streaming(url, payload, chunk_callback)  # type: ignore[arg-type]
            else:
                response = self._chat_blocking(url, payload)

            # --- Record usage after success ---
            if self._budget_tracker is not None:
                self._budget_tracker.record(
                    provider="anthropic",
                    model=model,
                    input_tokens=response.input_tokens,
                    output_tokens=response.output_tokens,
                )
            return response

        except requests.ConnectionError as e:
            raise BackendConnectionError(
                f"Could not connect to Anthropic API: {e}"
            ) from e
        except requests.Timeout as e:
            raise BackendConnectionError(
                f"Anthropic API request timed out: {e}"
            ) from e
        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else "?"
            if status in (401, 403):
                raise LLMBackendError(
                    f"Anthropic authentication failed (HTTP {status}). "
                    "Check ANTHROPIC_API_KEY."
                ) from e
            if status == 404:
                raise ModelNotAvailableError(
                    f"Anthropic model \'{model}\' not found (HTTP 404)."
                ) from e
            if status in (429, 529):
                # Extract Retry-After if present; use it as the floor for wait_until
                retry_after = _parse_retry_after(e.response)
                if self._budget_tracker is not None:
                    wait_until = self._budget_tracker.calculate_wait_until_for_provider(
                        provider="anthropic",
                        api_retry_after=retry_after,
                    )
                else:
                    wait_until = retry_after
                raise TokenBudgetExceededError(
                    provider="anthropic",
                    period="hour",
                    limit=0,
                    used=0,
                    retry_after=wait_until,
                ) from e
            raise LLMBackendError(
                f"Anthropic API error {status}: {e}"
            ) from e

    def is_model_available(self, model: str) -> bool:
        """Check whether the model name is in the known context length table.

        The Anthropic API does not provide a model listing endpoint.
        Returns ``True`` for any non-empty model string — the API will
        return a 404 at inference time if the model does not exist.

        Args:
            model: Anthropic model identifier.

        Returns:
            ``True`` if the model string is non-empty.
        """
        return bool(model)

    def list_models(self) -> list[str]:
        """Return the list of known Anthropic model identifiers.

        Returns the keys of the internal context length lookup table.
        This list may lag behind newly released models.

        Returns:
            List of known model identifier strings.
        """
        return list(_CONTEXT_LENGTHS.keys())

    def get_context_length(self, model: str) -> int:
        """Return the context length for an Anthropic model.

        Uses a hardcoded lookup table — the Anthropic API does not expose
        this value programmatically. Defaults to 200k for unrecognised
        models, which is Anthropic's floor for all recent releases.

        Args:
            model: Anthropic model identifier.

        Returns:
            Context length in tokens.
        """
        # Try exact match first, then prefix match for versioned strings
        if model in _CONTEXT_LENGTHS:
            return _CONTEXT_LENGTHS[model]
        for known, length in _CONTEXT_LENGTHS.items():
            if model.startswith(known) or known.startswith(model):
                return length
        logger.warning(
            "Unknown Anthropic model '%s'. Using default context length: %d",
            model, _DEFAULT_CONTEXT_LENGTH,
        )
        return _DEFAULT_CONTEXT_LENGTH

    def ensure_model(self, model: str) -> None:
        """No-op — model availability is Anthropic's concern.

        Args:
            model: Ignored.
        """
        logger.debug(
            "AnthropicBackend.ensure_model('%s'): no-op for remote API.",
            model,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _split_system(messages: list) -> tuple[str, list]:
        """Extract the system message from the conversation history.

        Anthropic's API requires the system prompt as a separate top-level
        parameter, not as a message in the conversation array.

        Args:
            messages: Full message history including system message.

        Returns:
            ``(system_text, remaining_messages)`` where ``system_text`` is
            the concatenated content of all system-role messages (usually
            just one), and ``remaining_messages`` excludes them.
        """
        system_parts: list[str] = []
        conversation: list = []
        for msg in messages:
            if msg.get("role") == "system":
                content = msg.get("content", "")
                if isinstance(content, str):
                    system_parts.append(content)
            else:
                conversation.append(msg)
        return "\n\n".join(system_parts), conversation

    @staticmethod
    def _to_anthropic_messages(messages: list) -> list:
        """Translate canonical messages to Anthropic wire format.

        The canonical format is already Anthropic-style, so most messages
        pass through unchanged. Tool result messages need ``tool_use_id``
        wrapped in the Anthropic content block structure.

        Args:
            messages: Canonical conversation history (system excluded).

        Returns:
            Messages in Anthropic wire format.
        """
        translated = []
        for msg in messages:
            role = msg.get("role", "")

            if role == "tool":
                # Anthropic expects tool results as a user message containing
                # a tool_result content block.
                translated.append({
                    "role": "user",
                    "content": [{
                        "type":        "tool_result",
                        "tool_use_id": msg.get("tool_use_id", ""),
                        "content":     msg.get("content", ""),
                    }],
                })
            else:
                translated.append(msg)

        return translated

    def _chat_blocking(self, url: str, payload: dict) -> LLMResponse:
        """Execute a non-streaming Anthropic API request.

        Args:
            url: Messages API endpoint URL.
            payload: Request body.

        Returns:
            Assembled ``LLMResponse``.
        """
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
        """Execute a streaming Anthropic API request via SSE.

        Args:
            url: Messages API endpoint URL.
            payload: Request body.
            chunk_callback: Called with each text delta.

        Returns:
            Assembled ``LLMResponse``.
        """
        import json as _json

        accumulated_text = ""
        accumulated_thinking = ""
        tool_calls: list[dict] = []
        current_tool: dict | None = None
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
                try:
                    event = _json.loads(line)
                except _json.JSONDecodeError:
                    continue

                etype = event.get("type", "")

                if etype == "content_block_start":
                    block = event.get("content_block", {})
                    if block.get("type") == "tool_use":
                        current_tool = {
                            "id":    block.get("id", ""),
                            "name":  block.get("name", ""),
                            "input": "",
                        }

                elif etype == "content_block_delta":
                    delta = event.get("delta", {})
                    dtype = delta.get("type", "")
                    if dtype == "text_delta":
                        text = delta.get("text", "")
                        accumulated_text += text
                        chunk_callback(text)
                    elif dtype == "thinking_delta":
                        accumulated_thinking += delta.get("thinking", "")
                    elif dtype == "input_json_delta" and current_tool is not None:
                        current_tool["input"] += delta.get("partial_json", "")

                elif etype == "content_block_stop":
                    if current_tool is not None:
                        tool_calls.append(current_tool)
                        current_tool = None

                elif etype == "message_delta":
                    delta = event.get("delta", {})
                    stop_reason = _STOP_REASON_MAP.get(
                        delta.get("stop_reason", "end_turn"), "end_turn"
                    )
                    usage = event.get("usage", {})
                    output_tokens = usage.get("output_tokens", output_tokens)

                elif etype == "message_start":
                    msg = event.get("message", {})
                    final_model = msg.get("model", final_model)
                    usage = msg.get("usage", {})
                    input_tokens = usage.get("input_tokens", input_tokens)

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
        """Parse a complete Anthropic API response.

        Args:
            data: Parsed JSON response from the Anthropic API.

        Returns:
            Assembled ``LLMResponse``.
        """
        import json as _json

        stop_reason = _STOP_REASON_MAP.get(
            data.get("stop_reason", "end_turn"), "end_turn"
        )
        usage = data.get("usage", {})

        accumulated_text = ""
        accumulated_thinking = ""
        tool_calls: list[dict] = []

        for block in data.get("content", []):
            btype = block.get("type", "")
            if btype == "text":
                accumulated_text += block.get("text", "")
            elif btype == "thinking":
                accumulated_thinking += block.get("thinking", "")
            elif btype == "tool_use":
                raw_input = block.get("input", {})
                if isinstance(raw_input, str):
                    try:
                        raw_input = _json.loads(raw_input)
                    except _json.JSONDecodeError:
                        raw_input = {}
                tool_calls.append({
                    "id":    block.get("id", ""),
                    "name":  block.get("name", ""),
                    "input": raw_input,
                })

        return self._assemble_response(
            accumulated_text=accumulated_text,
            accumulated_thinking=accumulated_thinking,
            tool_calls=tool_calls,
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
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
        """Build an ``LLMResponse`` from assembled response data.

        Args:
            accumulated_text: Full text content.
            accumulated_thinking: Full thinking content.
            tool_calls: List of tool call dicts with id, name, input.
            input_tokens: Prompt token count.
            output_tokens: Completion token count.
            model: Model identifier as reported by the API.
            stop_reason: Normalised stop reason.

        Returns:
            Assembled ``LLMResponse``.
        """
        content: list = []

        if accumulated_thinking:
            content.append(ThinkingBlock(text=accumulated_thinking))
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
            "AnthropicBackend response: model=%s input=%d output=%d stop=%s",
            model, input_tokens, output_tokens, stop_reason,
        )

        return LLMResponse(
            content=content,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model=model,
            stop_reason=stop_reason,
        )
    