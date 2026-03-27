"""matrixmouse/inference/base.py

Abstract base class for LLM inference backends, shared response types, and
the Tool datatype consumed by the inference layer.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Callable


# ---------------------------------------------------------------------------
# Content block types
# ---------------------------------------------------------------------------


@dataclass
class TextBlock:
    """A plain-text content block returned by the model."""

    type: str = "text"
    text: str = ""


@dataclass
class ThinkingBlock:
    """An extended-thinking / chain-of-thought content block.

    Anthropic surfaces these natively; OpenAI o-series exposes them via
    ``reasoning_content``.  Adapters normalise both into this type.
    """

    type: str = "thinking"
    text: str = ""


@dataclass
class ToolUseBlock:
    """A tool-call request emitted by the model.

    Attributes:
        id: Opaque identifier assigned by the backend.  Must be echoed back
            in the corresponding ``tool_result`` message so the backend can
            correlate call and result.
        name: Name of the tool the model wants to invoke.
        input: Parsed argument dictionary for the tool call.
    """

    type: str = "tool_use"
    id: str = ""
    name: str = ""
    input: dict = field(default_factory=dict)


# Convenience alias used in type annotations throughout the inference package.
ContentBlock = TextBlock | ThinkingBlock | ToolUseBlock


# ---------------------------------------------------------------------------
# Unified response envelope
# ---------------------------------------------------------------------------


@dataclass
class LLMResponse:
    """Normalised response returned by every ``LLMBackend.chat()`` call.

    Streaming is an adapter-internal concern.  When ``stream=True`` is passed
    to ``chat()``, the adapter consumes the stream and assembles this object
    before returning.  Callers always receive a fully-populated ``LLMResponse``
    regardless of whether streaming was used.

    Attributes:
        content: Ordered list of content blocks produced by the model.  May
            contain a mix of ``TextBlock``, ``ThinkingBlock``, and
            ``ToolUseBlock`` entries.
        input_tokens: Tokens consumed from the prompt / context.
        output_tokens: Tokens produced in this response.
        model: The model identifier as reported by the backend.  May differ
            from the requested model string when a cascade or alias is
            resolved.
        stop_reason: The reason the model stopped generating.  Normalised
            values across all adapters:

            * ``"end_turn"``   — model finished naturally.
            * ``"tool_use"``   — model emitted one or more tool calls.
            * ``"max_tokens"`` — context or output token limit reached.
            * ``"stop"``       — explicit stop sequence matched.
    """

    content: list[ContentBlock]
    input_tokens: int
    output_tokens: int
    model: str
    stop_reason: str


# ---------------------------------------------------------------------------
# Tool descriptor
# ---------------------------------------------------------------------------


@dataclass
class Tool:
    """Pairs an agent-facing callable with its JSON schema descriptor.

    The schema uses Anthropic's ``input_schema`` convention (JSON Schema
    object under the ``input_schema`` key).  Adapters are responsible for
    translating this into whatever format their backend requires — e.g.
    OpenAI-compat backends use ``parameters`` instead of ``input_schema``.

    Attributes:
        fn: The Python callable invoked when the model requests this tool.
        schema: Tool descriptor dict with keys ``name``, ``description``,
            and ``input_schema``.  Example::

                {
                    "name": "read_file",
                    "description": "Read the contents of a file.",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "Path to the file."
                            }
                        },
                        "required": ["path"]
                    }
                }
    """

    fn: Callable
    schema: dict


# ---------------------------------------------------------------------------
# Backend exceptions
# ---------------------------------------------------------------------------


class LLMBackendError(Exception):
    """Base exception for all inference backend failures."""


class ModelNotAvailableError(LLMBackendError):
    """Raised when the requested model cannot be found or loaded."""


class BackendConnectionError(LLMBackendError):
    """Raised when the adapter cannot reach its backend."""


class TokenBudgetExceededError(LLMBackendError):
    """Raised when a remote provider's token budget is exhausted.

    Attributes:
        provider: Short provider name, e.g. ``"anthropic"``.
        period: ``"hour"`` or ``"day"``.
        limit: The configured token limit for the period.
        used: Tokens consumed so far in the rolling window.
    """

    def __init__(
        self,
        provider: str,
        period: str,
        limit: int,
        used: int,
    ) -> None:
        self.provider = provider
        self.period = period
        self.limit = limit
        self.used = used
        super().__init__(
            f"{provider} {period} token budget exhausted: {used}/{limit} tokens used"
        )


# ---------------------------------------------------------------------------
# Abstract backend
# ---------------------------------------------------------------------------


class LLMBackend(ABC):
    """Abstract base class that every inference adapter must implement.

    Concrete subclasses live in the same package:

    * ``OllamaBackend``     — local Ollama server
    * ``LlamaCppBackend``   — local or remote llama.cpp server
    * ``AnthropicBackend``  — Anthropic API
    * ``OpenAIBackend``     — OpenAI API (also used for OpenAI-compat endpoints)

    All adapters are expected to be instantiated once and cached by the
    router.  They must be safe to call from multiple threads once constructed
    (the router's cache is protected by a ``threading.Lock``; individual
    adapter instances should not require external locking for ``chat()``
    calls).
    """

    @abstractmethod
    def chat(
        self,
        model: str,
        messages: list,
        tools: list[Tool],
        stream: bool = False,
        think: bool = False,
        chunk_callback: Callable[[str], None] | None = None,
    ) -> LLMResponse:
        """Send a chat completion request and return a normalised response.

        Args:
            model: Backend-local model identifier (the portion of the
                full model string after the ``[host:]backend:`` prefix has
                been stripped by the router).
            messages: Conversation history in the standard
                ``[{"role": ..., "content": ...}]`` format.
            tools: Tool descriptors available to the model for this call.
                Pass an empty list to disable tool use.
            stream: If ``True``, the adapter may use streaming internally
                for efficiency.  The return value is always a fully
                assembled ``LLMResponse`` regardless of this flag.
            think: If ``True`` and the backend supports extended thinking /
                chain-of-thought, enable it.  Thinking tokens appear as
                ``ThinkingBlock`` entries in the response's ``content``
                list.
            chunk_callable: A callable that emits chunks as they stream, if 
                streaming is enabled. The adapter yields chunks to this 
                callback as they arrive.

        Returns:
            A fully populated ``LLMResponse``.

        Raises:
            ModelNotAvailableError: If the model is not available on this
                backend.
            BackendConnectionError: If the backend cannot be reached.
            LLMBackendError: For other backend-specific failures.
        """
        ...

    @abstractmethod
    def is_model_available(self, model: str) -> bool:
        """Check whether a model is currently available on this backend.

        Args:
            model: Backend-local model identifier.

        Returns:
            ``True`` if the model can be used without calling
            ``ensure_model`` first.
        """
        ...

    @abstractmethod
    def list_models(self) -> list[str]:
        """Return the list of model identifiers available on this backend.

        Returns:
            List of backend-local model identifier strings.
        """
        ...

    @abstractmethod
    def get_context_length(self, model: str) -> int:
        """Return the context window length in tokens for the given model.

        Implementations should query the backend where possible. Where the
        context length cannot be determined programmatically (e.g. remote
        APIs), return the known limit for the model from a lookup table,
        or a well-reasoned conservative floor for unrecognised models.

        The floor should be large enough for meaningful agentic work —
        32,768 tokens is a reasonable minimum for any modern model.

        Args:
            model: Backend-local model identifier.

        Returns:
            Context length in tokens.
        """
        ...

    @abstractmethod
    def ensure_model(self, model: str) -> None:
        """Best-effort: make the model available if it is not already.

        Behaviour varies by backend:

        * **Ollama** — attempts ``ollama pull``.
        * **llama.cpp** — verifies the model file exists; raises
          ``ModelNotAvailableError`` if it does not.
        * **Remote APIs** — no-op; model availability is the provider's
          concern.

        Args:
            model: Backend-local model identifier.

        Raises:
            ModelNotAvailableError: If the model cannot be made available.
        """
        ...
