"""
matrixmouse/router.py

Manages model selection for each agent role, backend instantiation, and
cascade escalation.

Responsibilities:
    - Parsing ``[host:]backend:model`` model strings from config
    - Instantiating and caching ``LLMBackend`` instances (one per host+backend)
    - Enforcing the ``local_only`` safety flag at startup
    - Providing cascade lists for every role via ``cascade_for_role()``
    - Providing the summarizer cascade via ``summarizer_cascade()``
    - Vending backend instances via ``get_backend_for_model()``
    - Validating all cascade entries at init time
    - Ensuring only first (most-preferred) entries at startup
    - Constructing a clean handoff context when escalating
    - Injecting ``TokenBudgetTracker`` into remote backends

Cascade lists:
    Defined by config per-role (manager_cascade, critic_cascade, writer_cascade,
    coder_cascade, merge_resolution_cascade, summarizer_cascade).  All roles
    share the same cascade semantics — ordered preference, most-preferred first.

Role-to-model mapping (via cascade):
    MANAGER  → config.manager_cascade
    CRITIC   → config.critic_cascade
    WRITER   → config.writer_cascade
    CODER    → config.coder_cascade
    MERGE    → config.merge_resolution_cascade (defaults to [coder_cascade[-1]])
    summarizer → config.summarizer_cascade

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

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING

from matrixmouse.config import MatrixMouseConfig
from matrixmouse.inference.base import LLMBackend, Tool
from matrixmouse.stuck import StuckDetector
from matrixmouse.task import AgentRole

if TYPE_CHECKING:
    from matrixmouse.inference.token_budget import TokenBudgetTracker

logger = logging.getLogger(__name__)

# Backend identifiers that require remote API keys and are blocked by local_only.
_REMOTE_BACKENDS = frozenset({"anthropic", "openai"})

# Backend identifiers that are always local (no network egress outside LAN).
_LOCAL_BACKENDS = frozenset({"ollama", "llamacpp"})

# All known backend identifiers.
_KNOWN_BACKENDS = _REMOTE_BACKENDS | _LOCAL_BACKENDS


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
# Router
# ---------------------------------------------------------------------------

class Router:
    """Selects models and backends for each agent role; manages cascade resolution.

    Instantiated once by the orchestrator at startup. Backend instances are
    created lazily on first use and cached for the lifetime of the router.
    The cache is protected by a ``threading.Lock`` — safe for concurrent
    access from multiple worker threads.

    ``local_only`` enforcement happens at construction time: if any
    configured model string resolves to a remote backend while
    ``config.local_only`` is ``True``, ``ValueError`` is raised immediately
    so the misconfiguration is caught at startup rather than at first
    inference call.
    """

    def __init__(
        self,
        config: MatrixMouseConfig,
        budget_tracker: TokenBudgetTracker | None = None,
    ) -> None:
        self.config = config
        self._budget_tracker = budget_tracker
        self._backend_cache: dict[tuple[str, str], LLMBackend] = {}
        self._cache_lock = threading.Lock()

        # Build and cache all role cascades at init time
        self._role_cascades: dict[str, list[str]] = {}
        for role in AgentRole:
            self._role_cascades[role.value] = self._build_cascade_for_role(role)

        # Build summarizer cascade separately (not an AgentRole)
        self._role_cascades["_summarizer"] = self._build_summarizer_cascade()

        # Validate all cascade entries and enforce local_only
        self._validate_config()

        logger.info(
            "Router initialised. local_only=%s, budget_tracker=%s.",
            config.local_only,
            budget_tracker is not None,
        )

    # -----------------------------------------------------------------------
    # Cascade accessors
    # -----------------------------------------------------------------------

    def cascade_for_role(self, role: AgentRole) -> list[str]:
        """Return the ordered cascade list for the given role.

        Always returns at least one entry. Raises ValueError at init time
        if a required cascade is empty or missing.

        Args:
            role: The AgentRole to get the cascade for.

        Returns:
            Ordered list of model strings, most-preferred first.
        """
        return list(self._role_cascades[role.value])

    def summarizer_cascade(self) -> list[str]:
        """Return the ordered cascade list for the summarizer.

        Named separately from cascade_for_role to keep AgentRole clean.

        Returns:
            Ordered list of model strings, most-preferred first.
        """
        return list(self._role_cascades["_summarizer"])

    def get_backend_for_model(self, model_string: str) -> LLMBackend:
        """Return the cached LLMBackend for an arbitrary model string.

        Single entry point for all backend access after cascade resolution.
        Backends are instantiated with budget_tracker if one is configured —
        token usage is recorded automatically by the adapter on every
        successful chat() call, regardless of caller.

        Args:
            model_string: Full model string, e.g. ``"ollama:qwen3:4b"``.

        Returns:
            Cached ``LLMBackend`` instance.
        """
        parsed = parse_model_string(model_string)
        return self._get_or_create_backend(parsed)

    # -----------------------------------------------------------------------
    # Model selection (backward-compat shims — removed in Phase 1C)
    # -----------------------------------------------------------------------

    def model_for_role(self, role: AgentRole) -> str:
        """Return the full model string for a given agent role.

        Shim: returns the first entry of the cascade list for the role.
        This preserves backward compatibility during the transition.
        """
        # Handle non-AgentRole values (e.g. string from legacy call sites)
        if not isinstance(role, AgentRole):
            coder_cascade = self._role_cascades.get(AgentRole.CODER.value, [])
            if coder_cascade:
                return coder_cascade[0]
            logger.warning(
                "model_for_role called with non-AgentRole %r — no cascade found.",
                role,
            )
            return ""

        cascade = self._role_cascades.get(role.value, [])
        if cascade:
            return cascade[0]

        # Fallback for unknown roles
        coder_cascade = self._role_cascades.get(AgentRole.CODER.value, [])
        if coder_cascade:
            return coder_cascade[0]

        logger.warning(
            "model_for_role called with unknown role %r — no cascade found.",
            role,
        )
        return ""

    def parsed_model_for_role(self, role: AgentRole) -> ParsedModel:
        """Return the parsed model descriptor for a given agent role."""
        return parse_model_string(self.model_for_role(role))

    def backend_for_role(self, role: AgentRole) -> LLMBackend:
        """Return the cached ``LLMBackend`` instance for a given agent role."""
        model_string = self.model_for_role(role)
        return self.get_backend_for_model(model_string)

    def local_model_for_role(self, model_string: str) -> str:
        """Extract the backend-local model identifier from a full model string."""
        return parse_model_string(model_string).model

    def get_backend(self, model_string: str) -> LLMBackend:
        """Return the cached backend for an arbitrary model string.

        Shim: alias for ``get_backend_for_model``.
        """
        return self.get_backend_for_model(model_string)

    @property
    def current_tier(self) -> int:
        """Current position in the Coder cascade (0 = first entry).

        Shim: always returns 0 since the router no longer tracks tier state.
        Callers should use ``cascade_for_role`` directly instead.
        """
        return 0

    @property
    def at_ceiling(self) -> bool:
        """True if the Coder is at the top of the cascade.

        Shim: always returns True since there is no escalation state anymore.
        """
        return True

    # -----------------------------------------------------------------------
    # Role-derived flags (unchanged from pre-#32)
    # -----------------------------------------------------------------------

    def stream_for_role(self, role: AgentRole) -> bool:
        """Return whether to stream model output for a given role."""
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
        """Return whether to enable extended thinking for a given role."""
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
        """Verify the first (most-preferred) entry in each cascade is available.

        Calls ``backend.ensure_model()`` for cascade[0] of every role
        plus cascade[0] of summarizer, deduplicating by (backend_instance,
        model_id).

        Raises:
            ModelNotAvailableError: If a model cannot be made available.
            BackendConnectionError: If a backend cannot be reached.
        """
        model_strings: list[str] = []
        for cascade in self._role_cascades.values():
            if cascade:
                model_strings.append(cascade[0])

        seen: set[tuple[int, str]] = set()
        for model_string in model_strings:
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

    # -----------------------------------------------------------------------
    # Handoff construction (kept unchanged)
    # -----------------------------------------------------------------------

    def build_handoff(
        self,
        detector: StuckDetector,
        messages: list,
        keep_recent: int = 6,
    ) -> list:
        """Build a clean starting message history for the escalated model."""
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

    # -----------------------------------------------------------------------
    # Backward-compat: escalate / record_success (no-ops, removed in 1C)
    # -----------------------------------------------------------------------

    def escalate(self, detector: StuckDetector) -> tuple[bool, str | None]:
        """Shim: no longer escalates. Returns (False, None).

        The actual escalation logic has moved to the orchestrator which
        walks the cascade directly. This shim prevents crashes during
        the transition.
        """
        logger.warning(
            "Router.escalate() is deprecated — escalation now handled by "
            "the orchestrator's cascade walk.",
        )
        return False, None

    def record_success(self) -> None:
        """Shim: no-op. De-escalation state has been removed."""

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    def _get_or_create_backend(self, parsed: ParsedModel) -> LLMBackend:
        """Return a cached backend or instantiate a new one.

        Cache key is ``(host, backend)`` — one instance per endpoint.
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
        """Construct a new ``LLMBackend`` instance for the given parsed model."""
        backend = parsed.backend

        if backend == "ollama":
            from matrixmouse.inference.ollama import OllamaBackend
            return OllamaBackend(host=parsed.host)

        if backend == "llamacpp":
            from matrixmouse.inference.llamacpp import LlamaCppBackend
            return LlamaCppBackend(host=parsed.host)

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
            return AnthropicBackend(
                api_key=api_key,
                budget_tracker=self._budget_tracker,
            )

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
            return OpenAIBackend(
                api_key=api_key,
                base_url=parsed.host,
                budget_tracker=self._budget_tracker,
            )

        raise ValueError(
            f"Unknown backend '{backend}'. "
            f"Known backends: {sorted(_KNOWN_BACKENDS)}"
        )

    def _build_cascade_for_role(self, role: AgentRole) -> list[str]:
        """Build the ordered cascade list for a role from config.

        Merge role defaults to [coder_cascade[-1]] if unconfigured.
        Raises ValueError if a required cascade is empty.

        Args:
            role: The AgentRole to build the cascade for.

        Returns:
            Non-empty list of model strings.

        Raises:
            ValueError: If the cascade is empty after resolving defaults.
        """
        role_to_config_key: dict[AgentRole, str] = {
            AgentRole.MANAGER:  "manager_cascade",
            AgentRole.CRITIC:   "critic_cascade",
            AgentRole.WRITER:   "writer_cascade",
            AgentRole.CODER:    "coder_cascade",
            AgentRole.MERGE:    "merge_resolution_cascade",
        }

        config_key = role_to_config_key.get(role)
        if config_key is None:
            raise ValueError(f"Unknown role: {role}")

        cascade = list(getattr(self.config, config_key, []))

        # Default: merge_resolution_cascade falls back to [coder_cascade[-1]]
        if role == AgentRole.MERGE and not cascade:
            coder_cascade = list(self.config.coder_cascade or [])
            if coder_cascade:
                cascade = [coder_cascade[-1]]

        if not cascade:
            raise ValueError(
                f"Required cascade '{config_key}' is empty. "
                f"Configure it in config.toml."
            )

        logger.info("%s cascade: %s", config_key, cascade)
        return cascade

    def _build_summarizer_cascade(self) -> list[str]:
        """Build the summarizer cascade from config.

        Summarizer is not an AgentRole, so it's handled separately.

        Returns:
            Non-empty list of model strings.

        Raises:
            ValueError: If summarizer_cascade is empty.
        """
        cascade = list(self.config.summarizer_cascade or [])
        if not cascade:
            raise ValueError(
                "Required cascade 'summarizer_cascade' is empty. "
                "Configure it in config.toml."
            )
        logger.info("summarizer_cascade: %s", cascade)
        return cascade

    def _validate_config(self) -> None:
        """Parse all cascade entries and enforce local_only.

        Called once at construction time. Raises immediately if any entry
        is malformed, empty, or if a remote backend is configured while
        ``local_only`` is ``True``.

        Raises:
            ValueError: On any malformed/empty entry or local_only violation.
        """
        # Map internal cascade keys to their config key names for error messages
        key_map: dict[str, str] = {
            AgentRole.MANAGER.value:  "manager_cascade",
            AgentRole.CRITIC.value:   "critic_cascade",
            AgentRole.WRITER.value:   "writer_cascade",
            AgentRole.CODER.value:    "coder_cascade",
            AgentRole.MERGE.value:    "merge_resolution_cascade",
            "_summarizer":             "summarizer_cascade",
        }

        # Collect all cascade entries with their config key names
        all_entries: list[tuple[str, str]] = []  # (config_key, model_string)

        for cascade_key, cascade in self._role_cascades.items():
            config_key_base = key_map.get(cascade_key, cascade_key)
            for i, model_string in enumerate(cascade):
                all_entries.append((f"{config_key_base}[{i}]", model_string))

        remote_violations: list[str] = []

        for config_key, model_string in all_entries:
            if not model_string:
                raise ValueError(
                    f"Empty model string at {config_key}. "
                    f"Every cascade entry must be a valid model string."
                )
            try:
                parsed = parse_model_string(model_string)
            except ValueError as e:
                raise ValueError(
                    f"Invalid model string at {config_key}: {e}"
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
    