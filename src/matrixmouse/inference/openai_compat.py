"""matrixmouse/inference/openai_compat.py

Shared message translation utilities for OpenAI-compatible backends.

All three local/remote backends that speak the OpenAI Chat Completions
convention (OllamaBackend, LlamaCppBackend, OpenAIBackend) need identical
logic to:

    - Translate canonical Anthropic-style assistant messages (structured
      content block lists) into OpenAI's ``tool_calls`` format.
    - Translate canonical ``role: "tool"`` result messages to use
      ``tool_call_id`` rather than ``tool_use_id``.
    - Finalise accumulated tool call fragments from streaming responses
      into clean dicts with parsed ``input`` dicts.

Centralising here prevents the three adapters from diverging silently.
AnthropicBackend is intentionally excluded — its wire format is different
and its translation lives in anthropic.py.
"""

from __future__ import annotations

import json
import logging
import uuid

logger = logging.getLogger(__name__)


def to_openai_messages(messages: list) -> list:
    """Translate canonical message history to OpenAI Chat Completions format.

    The canonical internal format (produced by ``loop._response_to_message``)
    uses Anthropic-style structured content blocks for assistant messages::

        {'role': 'assistant', 'content': [
            {'type': 'thinking', 'thinking': '...'},
            {'type': 'tool_use', 'id': '...', 'name': '...', 'input': {...}},
        ]}

    OpenAI expects::

        {'role': 'assistant', 'content': '...', 'tool_calls': [
            {'id': '...', 'type': 'function',
             'function': {'name': '...', 'arguments': '{...}'}}
        ]}

    Tool result messages use ``tool_use_id`` in the canonical format and
    ``tool_call_id`` in OpenAI format — this is translated here.

    Thinking blocks are dropped — OpenAI-compat backends do not consume
    prior thinking content in conversation history.

    Non-assistant, non-tool messages with plain string content pass through
    unchanged.

    Args:
        messages: Canonical message history from loop.py.

    Returns:
        Message list ready to send to any OpenAI-compat endpoint.
    """
    translated = []
    for msg in messages:
        role = msg.get("role", "")

        if role == "assistant":
            content = msg.get("content", "")
            if not isinstance(content, list):
                # Plain string content — pass through unchanged
                translated.append(msg)
                continue

            text_parts: list[str] = []
            tool_calls: list[dict] = []

            for block in content:
                btype = block.get("type", "")
                if btype == "text":
                    text_parts.append(block.get("text", ""))
                elif btype == "thinking":
                    # Dropped — not part of OpenAI conversation history
                    pass
                elif btype == "tool_use":
                    # OpenAI requires arguments as a JSON string, not a dict
                    raw_input = block.get("input", {})
                    arguments = (
                        json.dumps(raw_input)
                        if isinstance(raw_input, dict)
                        else str(raw_input)
                    )
                    tool_calls.append({
                        "id":   block.get("id", ""),
                        "type": "function",
                        "function": {
                            "name":      block.get("name", ""),
                            "arguments": arguments,
                        },
                    })

            openai_msg: dict = {
                "role":    "assistant",
                "content": " ".join(text_parts),
            }
            if tool_calls:
                openai_msg["tool_calls"] = tool_calls
            translated.append(openai_msg)

        elif role == "tool":
            # Canonical uses tool_use_id; OpenAI uses tool_call_id
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


def finalise_tool_calls(raw: dict[int, dict]) -> list[dict]:
    """Parse accumulated tool call fragments into clean call dicts.

    Used by both streaming and blocking response paths to normalise the
    index-keyed accumulation dict into a flat list with parsed ``input``
    dicts.

    Args:
        raw: Index-keyed dict of accumulated call fragments.  Each entry
            has ``id`` (str), ``name`` (str), and ``arguments`` (str —
            accumulated JSON string from stream deltas, or the complete
            arguments string from a blocking response).

    Returns:
        List of dicts with ``id``, ``name``, and ``input`` (parsed dict),
        ordered by index.  Missing or malformed ``arguments`` produce an
        empty dict for ``input`` rather than raising.
    """
    result = []
    for idx in sorted(raw):
        entry = raw[idx]
        raw_args = entry.get("arguments", "")
        if isinstance(raw_args, dict):
            # Already parsed (non-streaming path may provide a dict directly)
            parsed_args = raw_args
        elif raw_args:
            try:
                parsed_args = json.loads(raw_args)
            except json.JSONDecodeError:
                logger.warning(
                    "openai_compat: could not parse tool arguments at index %d: %r",
                    idx, raw_args,
                )
                parsed_args = {}
        else:
            parsed_args = {}

        result.append({
            "id":    entry.get("id") or f"call_{uuid.uuid4().hex[:8]}",
            "name":  entry.get("name", ""),
            "input": parsed_args,
        })
    return result
