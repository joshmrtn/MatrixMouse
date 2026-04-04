"""
matrixmouse/context.py

Responsible for keeping the message history within a safe working limit.

Responsibilities:
    - Estimating token usage from current message history
    - Triggering summarisation when usage exceeds a configurable soft limit
      (default: 60% of model context length, capped at ~32k tokens regardless
      of model maximum)
    - Performing summarisation using a small, fast model from the
      summarizer cascade — walks the cascade and raises
      SummarizationUnavailableError if all entries are unavailable
    - Preserving: system prompt, original task instruction, last N turns
      (default: 6)
    - Replacing middle history with a compressed summary message marked
      [CONTEXT SUMMARY]
    - Writing any key discoveries to AGENT_NOTES.md before they are
      compressed away

Context limits are queried from the backend via LLMBackend.get_context_length(),
not hardcoded. Backends that cannot introspect model metadata return a
conservative fallback.

Do not add inference logic or tool dispatch here.
"""

import logging
from typing import TYPE_CHECKING

from matrixmouse.config import MatrixMouseConfig, MatrixMousePaths, RepoPaths
from matrixmouse.inference.base import LLMBackend, TextBlock

if TYPE_CHECKING:
    from matrixmouse.router import Router
    from matrixmouse.inference.availability import BackendAvailabilityCache
    from matrixmouse.inference.base import SummarizationUnavailableError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Token estimation
# ---------------------------------------------------------------------------

def estimate_tokens(messages: list) -> int:
    """Estimate the total token count of a message history.

    Uses a character-based heuristic (~4 chars per token) which is
    intentionally conservative — it's better to compress slightly early
    than to let the context overflow. Accurate enough for triggering
    compression; not suitable for billing or precise model limits.

    Args:
        messages: List of message dicts.

    Returns:
        Estimated token count as an integer.
    """
    total_chars = 0
    for message in messages:
        content = message.get("content") or "" if isinstance(message, dict) else ""
        if isinstance(content, list):
            # Structured content blocks — extract text from each
            for block in content:
                if isinstance(block, dict):
                    total_chars += len(block.get("text", "") or block.get("thinking", ""))
        else:
            total_chars += len(content)
    return total_chars // 4


# ---------------------------------------------------------------------------
# Context manager — the callable passed into AgentLoop
# ---------------------------------------------------------------------------

class ContextManager:
    """Monitors message history size and compresses when approaching the limit.

    Designed to be passed into AgentLoop as the context_manager callable::

        context_manager = ContextManager(
            config=config,
            paths=paths,
            working_model=working_parsed.model,
            working_backend=working_backend,
            router=router,
            availability_cache=availability_cache,
        )
        loop = AgentLoop(..., context_manager=context_manager)

    The loop calls ``context_manager(messages, config)`` before each inference.

    Args:
        config: MatrixMouseConfig instance.
        paths: Resolved paths for this workspace.
        working_model: Backend-local model identifier for the working agent
            (the portion after ``backend:`` in the full model string).
            Used to query the context length via working_backend.
        working_backend: LLMBackend for the working agent — provides
            get_context_length().
        router: Router instance — used to access summarizer_cascade and
            get_backend_for_model.
        availability_cache: Optional BackendAvailabilityCache for checking
            summarizer backend availability.
    """

    def __init__(
        self,
        config: MatrixMouseConfig,
        paths: MatrixMousePaths | RepoPaths,
        working_model: str,
        working_backend: LLMBackend,
        router: "Router",
        availability_cache: "BackendAvailabilityCache | None" = None,
    ) -> None:
        self.config = config
        self.paths = paths
        self._router = router
        self._availability_cache = availability_cache

        raw_limit = working_backend.get_context_length(working_model)
        self.token_limit = min(raw_limit, config.context_soft_limit)
        self.compress_at = int(self.token_limit * config.compress_threshold)

        logger.info(
            "ContextManager ready. Model limit: %d, soft limit: %d, "
            "compress threshold: %d tokens.",
            raw_limit, self.token_limit, self.compress_at,
        )

    def __call__(self, messages: list, config: MatrixMouseConfig) -> list:
        """Check token usage and compress history if needed.

        This is the interface AgentLoop expects.

        Args:
            messages: Current message history.
            config: Active config (passed by the loop, may differ from init).

        Returns:
            The message list, compressed if necessary.
        """
        estimated = estimate_tokens(messages)

        if estimated < self.compress_at:
            logger.debug(
                "Context OK: ~%d tokens (limit %d).", estimated, self.compress_at,
            )
            return messages

        logger.info(
            "Context near limit (~%d tokens, threshold %d). Compressing...",
            estimated, self.compress_at,
        )
        return self._compress(messages)

    def _compress(self, messages: list) -> list:
        """Summarise the middle of the message history.

        Preserves the system prompt, original user instruction, and the
        last N turns. Writes a brief record of discoveries to AGENT_NOTES.md
        before compressing so nothing important is silently discarded.

        Args:
            messages: Full message history to compress.

        Returns:
            Compressed message list.
        """
        keep = self.config.keep_last_n_turns

        if len(messages) <= keep + 2:
            logger.debug("History too short to compress (%d messages).", len(messages))
            return messages

        system_msg      = messages[0]
        instruction_msg = messages[1]
        middle          = messages[2 : len(messages) - keep]
        recent          = messages[len(messages) - keep :]

        if not middle:
            return messages

        self._save_discoveries_to_notes(middle)
        summary_text = self._summarise(middle)

        summary_msg = {
            "role": "system",
            "content": (
                "[CONTEXT SUMMARY — earlier conversation compressed to save space]\n"
                f"{summary_text}\n"
                "[End of summary. Recent conversation follows.]"
            ),
        }

        compressed = [system_msg, instruction_msg, summary_msg] + recent

        logger.info(
            "Compression complete. %d messages → %d messages. "
            "~%d tokens → ~%d tokens.",
            len(messages), len(compressed),
            estimate_tokens(messages), estimate_tokens(compressed),
        )
        return compressed

    def _resolve_summarizer(self) -> tuple[LLMBackend, str]:
        """Return the first available (backend, model_id) from summarizer_cascade.

        Walks the summarizer cascade and checks each entry's backend
        availability via the availability_cache. Returns the first
        available backend and model identifier.

        Raises:
            SummarizationUnavailableError: If all entries are in cooldown or
                the cascade is exhausted. This is a hard failure — callers must
                not catch and swallow it. A task that cannot summarise will
                become permanently stuck as its context window fills.
        """
        from matrixmouse.router import parse_model_string
        from matrixmouse.inference.base import SummarizationUnavailableError

        for model_str in self._router.summarizer_cascade():
            parsed = parse_model_string(model_str)
            if self._availability_cache is not None:
                if not self._availability_cache.is_available(parsed.backend):
                    logger.debug(
                        "Summarizer backend '%s' in cooldown, skipping.",
                        parsed.backend,
                    )
                    continue
            backend = self._router.get_backend_for_model(model_str)
            return backend, parsed.model

        raise SummarizationUnavailableError(
            "All summarizer cascade entries are unavailable."
        )

    def _summarise(self, messages: list) -> str:
        """Use the summarizer backend to produce a concise summary.

        Args:
            messages: The middle slice to summarise.

        Returns:
            Summary text as a string.

        Raises:
            SummarizationUnavailableError: If no summarizer backend is
                available. This exception propagates to the orchestrator
                and must NOT be caught here.
        """
        # Resolve the summarizer backend — raises SummarizationUnavailableError
        # if all cascade entries are exhausted.
        backend, model_id = self._resolve_summarizer()

        transcript_parts = []
        for m in messages:
            role = m.get("role", "unknown") if isinstance(m, dict) else "unknown"
            content = m.get("content", "") if isinstance(m, dict) else ""
            if isinstance(content, list):
                # Flatten structured content blocks to plain text
                text = " ".join(
                    b.get("text", "") or b.get("thinking", "")
                    for b in content
                    if isinstance(b, dict)
                )
            else:
                text = content or ""
            if text.strip():
                transcript_parts.append(f"{role.upper()}: {text.strip()}")

        transcript = "\n\n".join(transcript_parts)
        if not transcript:
            return "(No content to summarise.)"

        prompt = (
            "You are summarising a coding agent's work log. "
            "Be terse and factual. Focus on: what tools were called, "
            "what files were read or modified, what was discovered or "
            "accomplished, and any errors encountered. "
            "Omit pleasantries, repetition, and meta-commentary.\n\n"
            f"Work log to summarise:\n\n{transcript}"
        )

        response = backend.chat(
            model=model_id,
            messages=[{"role": "user", "content": prompt}],
            tools=[],
            stream=False,
        )
        # Extract text from the response content blocks
        text_parts = [
            b.text for b in response.content
            if isinstance(b, TextBlock) and b.text
        ]
        return "\n".join(text_parts) or "(Empty summary returned.)"

    def _save_discoveries_to_notes(self, messages: list) -> None:
        """Extract and append notable discoveries to AGENT_NOTES.md.

        Best-effort — failures are logged but do not block compression.

        Args:
            messages: The middle slice about to be compressed.
        """
        try:
            from matrixmouse import memory
            from datetime import datetime

            if not memory.is_configured():
                logger.debug("Memory not configured — skipping discovery save.")
                return

            summary = self._summarise(messages)
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
            entry = f"### {timestamp}\n{summary}"

            if memory._manager is not None:
                memory._manager.append_to_section("context_compression_log", entry)
            logger.debug("Discoveries written to context_compression_log before compression.")

        except Exception as e:
            logger.warning("Failed to write discoveries to notes: %s", e)


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------

def check_and_compress(
    messages: list,
    config: MatrixMouseConfig,
    paths: MatrixMousePaths | RepoPaths,
    working_model: str,
    working_backend: LLMBackend,
    router: "Router",
    availability_cache: "BackendAvailabilityCache | None" = None,
) -> list:
    """Functional interface for context checking — creates a ContextManager
    and calls it in one step.

    Useful for one-off checks. For repeated use, instantiate ContextManager
    directly so the context length is only queried once.

    Args:
        messages: Current message history.
        config: Active MatrixMouseConfig.
        paths: Resolved MatrixMousePaths.
        working_model: Backend-local model identifier for the working agent.
        working_backend: LLMBackend for the working agent.
        router: Router instance for summarizer cascade resolution.
        availability_cache: Optional availability cache for summarizer checks.

    Returns:
        The message list, compressed if necessary.
    """
    manager = ContextManager(
        config=config,
        paths=paths,
        working_model=working_model,
        working_backend=working_backend,
        router=router,
        availability_cache=availability_cache,
    )
    return manager(messages, config)