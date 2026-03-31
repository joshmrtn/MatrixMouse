"""
matrixmouse/router.py

Manages model selection for each agent role, backend instantiation, and
cascade escalation.

Responsibilities:
    - Parsing ``[host:]backend:model`` model strings from config
    - Instantiating and caching ``LLMBackend`` instances (one per host+backend)
    - Enforcing the ``local_only`` safety flag at startup
    - Assigning models to roles based on config
    - Maintaining the cascade ladder for Coder escalation
    - Escalating to the next model tier when stuck.py signals a stuck state
    - Constructing a clean handoff context when escalating
    - Gradually de-escalating after successful cycles

Role-to-model mapping:
    MANAGER  → config.manager_model  (largest, most capable)
    CODER    → config.coder_cascade  (escalating ladder)
    WRITER   → config.writer_model
    CRITIC   → config.critic_model   (strong reasoning)
    MERGE    → config.merge_resolution_model (defaults to top of coder_cascade)
    internal summarization → config.summarizer_model (not agent-facing)

Cascade ladder:
    Defined by config.coder_cascade (list, smallest to largest).
    Applies to CODER role only. All other roles use a fixed model
    with no escalation — if Manager or Critic is stuck, the task
    escalates to BLOCKED_BY_HUMAN rather than a larger model.

Model string format:
    [host:]backend:model

    host     — optional; http:// or https:// URL of a remote backend server.
               If absent, the backend is assumed to be local (localhost).
    backend  — one of: ollama, llamacpp, anthropic, openai
    model    — backend-local model identifier (everything after the second colon,
               allowing colons in model names e.g. ``ollama:qwen3:4b``)

    Examples:
        ollama:qwen3:4b
        llamacpp:qwen3.5-4B.Q4_K_M.gguf
        https://192.168.1.42:llamacpp:qwen3.5-27B.Q4_K_M.gguf
        https://192.168.1.43:ollama:qwen3.5:72b
        anthropic:claude-sonnet-4-5
        openai:gpt-4o

Backend instances are cached by (host, backend) key — one connection per
endpoint, not one per model. The cache is protected by a threading.Lock
so it is safe for concurrent access from multiple worker threads (#15).

Do not add inference logic or tool dispatch here.
"""

import logging
import threading
from dataclasses import dataclass

from matrixmouse.config import MatrixMouseConfig
from matrixmouse.inference.base import LLMBackend, Tool
from matrixmouse.stuck import StuckDetector
from matrixmouse.task import AgentRole

logger = logging.getLogger(__name__)

# Backend identifiers that require remote API keys and are blocked by local_only.
_REMOTE_BACKENDS = frozenset({"anthropic", "openai"})

# Backend identifiers that are always local (no network egress outside LAN).
_LOCAL_BACKENDS = frozenset({"ollama", "llamacpp"})

# Fake backend for testing (treated as local).
_FAKE_BACKENDS = frozenset({"fake"})

# All known backend identifiers.
_KNOWN_BACKENDS = _REMOTE_BACKENDS | _LOCAL_BACKENDS | _FAKE_BACKENDS


# ---------------------------------------------------------------------------
# Model string parsing
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ParsedModel:
    """Result of parsing a ``[host:]backend:model`` model string.

    Attributes:
        host: Backend server URL, e.g. ``"http://localhost:11434"``.
            Always set — local backends default to their standard localhost URL.
        backend: Backend identifier string, e.g. ``"ollama"``.
        model: Backend-local model identifier passed to ``LLMBackend.chat()``.
        is_remote: True if the backend requires external API access.
        raw: The original unparsed model string.
    """
    host: str
    backend: str
    model: str
    is_remote: bool
    raw: str


def parse_model_string(model_string: str) -> ParsedModel:
    """Parse a ``[host:]backend:model`` model string into its components.

    The first component is treated as a host if it begins with ``http://``
    or ``https://``. The next component is the backend identifier. Everything
    after the backend is the model identifier (allowing colons in model names).

    Args:
        model_string: Raw model string from config, e.g.
            ``"ollama:qwen3:4b"`` or
            ``"https://192.168.1.43:ollama:qwen3.5:72b"``.

    Returns:
        Parsed ``ParsedModel`` with host, backend, model, and is_remote.

    Raises:
        ValueError: If the string is empty, the backend is unknown, or
            the model identifier is missing.
    """
    if not model_string or not model_string.strip():
        raise ValueError("Model string cannot be empty.")

    parts = model_string.split(":")

    # Detect optional host prefix (http:// or https://)
    host: str | None = None
    if parts[0].lower() in ("http", "https"):
        # Reconstruct the full URL — it spans "http", "//hostname", possibly port
        # e.g. ["https", "//192.168.1.43", "llamacpp", "model.gguf"]
        # The URL ends before the backend identifier.
        # Find first part that is a known backend identifier
        url_parts = []
        remaining = list(parts)
        while remaining and remaining[0].lower() not in _KNOWN_BACKENDS:
            url_parts.append(remaining.pop(0))
        host = ":".join(url_parts)
        parts = remaining

    if not parts:
        raise ValueError(
            f"Model string '{model_string}' has no backend identifier. "
            f"Expected format: [host:]backend:model"
        )

    backend = parts[0].lower()
    model_parts = parts[1:]

    if backend not in _KNOWN_BACKENDS:
        raise ValueError(
            f"Unknown backend '{backend}' in model string '{model_string}'. "
            f"Known backends: {sorted(_KNOWN_BACKENDS)}"
        )

    model_id = ":".join(model_parts)

    if not model_id:
        raise ValueError(
            f"Model string '{model_string}' has no model identifier after backend '{backend}'."
        )

    # Resolve host to the backend's default localhost URL if not specified
    if host is None:
        host = _default_host(backend)

    is_remote = backend in _REMOTE_BACKENDS
    return ParsedModel(
        host=host,
        backend=backend,
        model=model_id,
        is_remote=is_remote,
        raw=model_string,
    )


def _default_host(backend: str) -> str:
    """Return the default localhost URL for a given backend.

    Args:
        backend: Backend identifier string.

    Returns:
        Default host URL string.
    """
    defaults = {
        "ollama":    "http://localhost:11434",
        "llamacpp":  "http://localhost:8080",
        "anthropic": "https://api.anthropic.com",
        "openai":    "https://api.openai.com",
    }
    return defaults.get(backend, "http://localhost")


# ---------------------------------------------------------------------------
# Handoff context
# ---------------------------------------------------------------------------

@dataclass
class EscalationHandoff:
    """Context passed to the larger model when escalating within the cascade.

    Summarises what the smaller model tried and why it failed so the
    larger model does not repeat the same mistakes.
    """
    from_model: str
    to_model: str
    stuck_summary: dict
    recent_messages: list
    original_messages: list


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

class Router:
    """Selects models and backends for each agent role; manages escalation.

    Instantiated once by the orchestrator at startup. Backend instances are
    created lazily on first use and cached for the lifetime of the router.
    The cache is protected by a ``threading.Lock`` — safe for concurrent
    access from multiple worker threads.

    ``local_only`` enforcement happens at construction time: if any
    configured model string resolves to a remote backend while
    ``config.local_only`` is ``True``, ``ValueError`` is raised immediately
    so the misconfiguration is caught at startup rather than at first
    inference call.

    Escalation applies to CODER only. Manager and Critic use fixed models;
    if they cannot complete their work within the turn limit the task moves
    to BLOCKED_BY_HUMAN.
    """

    # Number of successful Coder cycles before stepping down one cascade tier.
    DEESCALATE_AFTER = 2

    def __init__(self, config: MatrixMouseConfig) -> None:
        self.config = config
        self._backend_cache: dict[tuple[str, str], LLMBackend] = {}
        self._cache_lock = threading.Lock()

        self._cascade = self._build_cascade()
        self._current_tier = 0
        self._successful_cycles = 0

        # Validate all configured model strings and enforce local_only.
        self._validate_config()

        logger.info(
            "Router initialised. Cascade: %s. Manager: %s. "
            "Critic: %s. Writer: %s. Summarizer: %s. local_only: %s.",
            self._cascade,
            config.manager_model,
            config.critic_model,
            config.writer_model,
            config.summarizer_model,
            config.local_only,
        )

    # -----------------------------------------------------------------------
    # Model selection
    # -----------------------------------------------------------------------

    def model_for_role(self, role: AgentRole) -> str:
        """Return the full model string for a given agent role.

        The returned string is the raw config value — use
        ``parsed_model_for_role`` or ``backend_for_role`` when you need
        to pass it to an inference backend.

        Args:
            role: The AgentRole of the running agent.

        Returns:
            Model string, e.g. ``"ollama:qwen3:4b"``.
        """
        if role == AgentRole.MANAGER:
            return self.config.manager_model
        if role == AgentRole.CRITIC:
            return self.config.critic_model
        if role == AgentRole.CODER:
            return self._current_model()
        if role == AgentRole.WRITER:
            return self.config.writer_model
        if role == AgentRole.MERGE:
            return self._merge_model()

        logger.warning(
            "model_for_role called with unknown role %r — "
            "falling back to coder_model.",
            role,
        )
        return self.config.coder_model

    def parsed_model_for_role(self, role: AgentRole) -> ParsedModel:
        """Return the parsed model descriptor for a given agent role.

        Args:
            role: The AgentRole of the running agent.

        Returns:
            ``ParsedModel`` with host, backend, and model identifier.
        """
        return parse_model_string(self.model_for_role(role))

    def backend_for_role(self, role: AgentRole) -> LLMBackend:
        """Return the cached ``LLMBackend`` instance for a given agent role.

        Instantiates the backend on first call for this (host, backend) pair.
        Subsequent calls return the cached instance.

        Args:
            role: The AgentRole of the running agent.

        Returns:
            ``LLMBackend`` ready for ``chat()`` calls.

        Raises:
            ValueError: If the backend identifier is not recognised.
        """
        parsed = self.parsed_model_for_role(role)
        return self._get_or_create_backend(parsed)

    def local_model_for_role(self, model_string: str) -> str:
        """Extract the backend-local model identifier from a full model string.

        This is the portion passed to ``LLMBackend.chat(model=...)``.

        Args:
            model_string: Full model string, e.g. ``"ollama:qwen3:4b"``.

        Returns:
            Backend-local model identifier, e.g. ``"qwen3:4b"``.
        """
        return parse_model_string(model_string).model

    def stream_for_role(self, role: AgentRole) -> bool:
        """Return whether to stream model output for a given role.

        Args:
            role: The AgentRole of the running agent.

        Returns:
            ``True`` if streaming should be enabled.
        """
        if role == AgentRole.MANAGER:
            return self.config.manager_stream
        if role == AgentRole.CRITIC:
            return self.config.critic_stream
        if role == AgentRole.CODER:
            return self.config.coder_stream
        if role == AgentRole.WRITER:
            return self.config.writer_stream
        return True

    def think_for_role(self, role: AgentRole) -> bool:
        """Return whether to enable extended thinking for a given role.

        Args:
            role: The AgentRole of the running agent.

        Returns:
            ``True`` if extended thinking should be enabled.
        """
        if role == AgentRole.MANAGER:
            return self.config.manager_think
        if role == AgentRole.CRITIC:
            return self.config.critic_think
        if role == AgentRole.CODER:
            return self.config.coder_think
        if role == AgentRole.WRITER:
            return self.config.writer_think
        return False

    # -----------------------------------------------------------------------
    # Backend access
    # -----------------------------------------------------------------------

    def ensure_all_models(self) -> None:
        """Verify all configured models are available on their backends.

        Calls ``backend.ensure_model()`` for every configured model string,
        deduplicating by (backend_instance, model_id) so the same model
        served by the same backend is only checked once.

        Called once during the service startup sequence in ``_service.py``,
        after the Router is constructed and ``_validate_config()`` has
        already confirmed all model strings are well-formed.

        Raises:
            ModelNotAvailableError: If a model cannot be made available.
            BackendConnectionError: If a backend cannot be reached.
        """
        all_model_strings = [
            self.config.manager_model,
            self.config.critic_model,
            self.config.writer_model,
            self.config.summarizer_model,
            self._merge_model(),
        ] + list(self._cascade)

        seen: set[tuple[int, str]] = set()
        for model_string in all_model_strings:
            if not model_string:
                continue
            parsed = parse_model_string(model_string)
            backend = self._get_or_create_backend(parsed)
            key = (id(backend), parsed.model)
            if key in seen:
                continue
            seen.add(key)
            logger.info(
                "Ensuring model '%s' on %s @ %s ...",
                parsed.model, parsed.backend, parsed.host,
            )
            backend.ensure_model(parsed.model)

    def get_backend(self, model_string: str) -> LLMBackend:
        """Return the cached backend for an arbitrary model string.

        Useful for the summarizer model and other non-role inference calls.

        Args:
            model_string: Full model string, e.g. ``"ollama:qwen3:4b"``.

        Returns:
            Cached ``LLMBackend`` instance.
        """
        parsed = parse_model_string(model_string)
        return self._get_or_create_backend(parsed)

    def _get_or_create_backend(self, parsed: ParsedModel) -> LLMBackend:
        """Return a cached backend or instantiate a new one.

        Cache key is ``(host, backend)`` — one instance per endpoint,
        regardless of which model is requested from it.

        Args:
            parsed: Parsed model descriptor.

        Returns:
            ``LLMBackend`` instance.
        """
        cache_key = (parsed.host, parsed.backend)
        with self._cache_lock:
            if cache_key in self._backend_cache:
                return self._backend_cache[cache_key]
            backend = self._instantiate_backend(parsed)
            self._backend_cache[cache_key] = backend
            logger.debug(
                "Backend instantiated and cached: %s @ %s",
                parsed.backend, parsed.host,
            )
            return backend

    def _instantiate_backend(self, parsed: ParsedModel) -> LLMBackend:
        """Construct a new ``LLMBackend`` instance for the given parsed model.

        Args:
            parsed: Parsed model descriptor.

        Returns:
            New ``LLMBackend`` instance.

        Raises:
            ValueError: If the backend identifier is not recognised or
                the required API key is missing.
        """
        backend = parsed.backend

        if backend == "ollama":
            from matrixmouse.inference.ollama import OllamaBackend
            return OllamaBackend(host=parsed.host)

        if backend == "llamacpp":
            from matrixmouse.inference.llamacpp import LlamaCppBackend
            return LlamaCppBackend(host=parsed.host)

        if backend == "fake":
            from matrixmouse.inference.fake import FakeBackend
            return FakeBackend()

        if backend == "anthropic":
            import os
            api_key = os.environ.get("ANTHROPIC_API_KEY", "")
            if not api_key:
                raise ValueError(
                    "ANTHROPIC_API_KEY is not set. "
                    "Place the key in /etc/matrixmouse/secrets/anthropic_api_key "
                    "and ensure _service.py loads it into the environment."
                )
            from matrixmouse.inference.anthropic import AnthropicBackend
            return AnthropicBackend(api_key=api_key)

        if backend == "openai":
            import os
            api_key = os.environ.get("OPENAI_API_KEY", "")
            if not api_key:
                raise ValueError(
                    "OPENAI_API_KEY is not set. "
                    "Place the key in /etc/matrixmouse/secrets/openai_api_key "
                    "and ensure _service.py loads it into the environment."
                )
            from matrixmouse.inference.openai import OpenAIBackend
            return OpenAIBackend(api_key=api_key, base_url=parsed.host)

        raise ValueError(
            f"Unknown backend '{backend}'. "
            f"Known backends: {sorted(_KNOWN_BACKENDS)}"
        )

    # -----------------------------------------------------------------------
    # Cascade escalation (Coder only)
    # -----------------------------------------------------------------------

    def escalate(self, detector: StuckDetector) -> tuple[bool, str | None]:
        """Attempt to escalate the Coder to the next cascade tier.

        Only applies to the Coder role. Manager and Critic do not
        escalate — they move to BLOCKED_BY_HUMAN at their turn limit.

        Args:
            detector: StuckDetector from the failed loop run.

        Returns:
            ``(escalated, new_model_string)`` — ``escalated`` is False if
            already at the top of the cascade.
        """
        if self._current_tier >= len(self._cascade) - 1:
            logger.warning(
                "Escalation requested but already at top of cascade (%s). "
                "Human intervention required.",
                self._current_model(),
            )
            return False, None

        old_model = self._current_model()
        self._current_tier += 1
        new_model = self._current_model()
        self._successful_cycles = 0

        logger.info(
            "Escalating Coder: %s → %s. Stuck reason: %s",
            old_model, new_model, detector.last_reason,
        )
        return True, new_model

    def record_success(self) -> None:
        """Record a successful Coder cycle toward de-escalation.

        After ``DEESCALATE_AFTER`` consecutive successes, step down one
        cascade tier. Call this from the orchestrator when a Coder task
        completes cleanly.
        """
        if self._current_tier == 0:
            return

        self._successful_cycles += 1
        logger.debug(
            "Successful Coder cycle recorded (%d/%d toward de-escalation).",
            self._successful_cycles, self.DEESCALATE_AFTER,
        )

        if self._successful_cycles >= self.DEESCALATE_AFTER:
            old_model = self._current_model()
            self._current_tier = max(0, self._current_tier - 1)
            new_model = self._current_model()
            self._successful_cycles = 0
            logger.info(
                "De-escalating Coder after %d successful cycles: %s → %s.",
                self.DEESCALATE_AFTER, old_model, new_model,
            )

    def build_handoff(
        self,
        detector: StuckDetector,
        messages: list,
        keep_recent: int = 6,
    ) -> list:
        """Build a clean starting message history for the escalated model.

        Args:
            detector: StuckDetector with diagnostics from the failed run.
            messages: Full message history from the failed run.
            keep_recent: Number of recent messages to include verbatim.

        Returns:
            Trimmed message list ready to pass to AgentLoop.
        """
        if len(messages) < 2:
            return messages

        system_msg      = messages[0]
        instruction_msg = messages[1]
        recent = (
            messages[-keep_recent:]
            if len(messages) > keep_recent + 2
            else messages[2:]
        )

        summary = detector.summary
        handoff_msg = {
            "role": "system",
            "content": (
                "[ESCALATION HANDOFF]\n"
                f"A smaller model was unable to make progress and has "
                f"escalated to you.\n\n"
                f"Stuck reason: {summary.get('reason', 'unknown')}\n"
                f"Role: {summary.get('role', 'unknown')}\n"
                f"Turns taken: {summary.get('total_calls', 0)}\n"
                f"Consecutive errors: {summary.get('consecutive_errors', 0)}\n"
                f"Turns without a write: "
                f"{summary.get('turns_without_write', 0)}\n\n"
                "Please review the recent context below and continue the "
                "task, avoiding the same approaches that caused the smaller "
                "model to stall.\n"
                "[END HANDOFF]"
            ),
        }

        return [system_msg, instruction_msg, handoff_msg] + list(recent)

    @property
    def current_tier(self) -> int:
        """Current position in the Coder cascade (0 = smallest model)."""
        return self._current_tier

    @property
    def at_ceiling(self) -> bool:
        """True if the Coder is already at the top of the cascade."""
        return self._current_tier >= len(self._cascade) - 1

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    def _validate_config(self) -> None:
        """Parse all configured model strings and enforce local_only.

        Called once at construction time. Raises immediately if any model
        string is malformed or if a remote backend is configured while
        ``local_only`` is ``True``.

        Raises:
            ValueError: On any malformed model string or local_only violation.
        """
        all_model_strings = [
            ("manager_model",    self.config.manager_model),
            ("critic_model",     self.config.critic_model),
            ("writer_model",     self.config.writer_model),
            ("summarizer_model", self.config.summarizer_model),
        ]
        for i, model_string in enumerate(self._cascade):
            all_model_strings.append((f"coder_cascade[{i}]", model_string))

        merge_model = self._merge_model()
        all_model_strings.append(("merge_resolution_model", merge_model))

        remote_violations: list[str] = []

        for config_key, model_string in all_model_strings:
            if not model_string:
                continue
            try:
                parsed = parse_model_string(model_string)
            except ValueError as e:
                raise ValueError(
                    f"Invalid model string for {config_key}: {e}"
                ) from e

            if self.config.local_only and parsed.is_remote:
                remote_violations.append(
                    f"  {config_key} = '{model_string}' "
                    f"(backend: {parsed.backend})"
                )

        if remote_violations:
            raise ValueError(
                "local_only = true but remote backends are configured:\n"
                + "\n".join(remote_violations)
                + "\n\nEither set local_only = false or use only local "
                "backends (ollama, llamacpp)."
            )

    def _build_cascade(self) -> list[str]:
        """Build the ordered Coder cascade ladder from config.

        If ``config.coder_cascade`` is set, use it directly. Otherwise
        fall back to a single-tier ladder containing only
        ``config.coder_model`` — escalation is effectively disabled.
        """
        if self.config.coder_cascade:
            cascade = list(self.config.coder_cascade)
            logger.info("Coder cascade ladder: %s", cascade)
            return cascade

        logger.info(
            "No coder_cascade configured. Single-tier Coder ladder: [%s]. "
            "Set coder_cascade in config.toml to enable escalation.",
            self.config.coder_model,
        )
        return [self.config.coder_model]

    def _current_model(self) -> str:
        """Return the full model string at the current Coder cascade tier."""
        return self._cascade[self._current_tier]

    def _merge_model(self) -> str:
        """Return the model string for the Merge role.

        Defaults to the top of the Coder cascade if not explicitly configured.
        """
        if self.config.merge_resolution_model:
            return self.config.merge_resolution_model
        return self._cascade[-1] if self._cascade else self.config.coder_model
    