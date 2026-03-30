"""
matrixmouse/context.py

Responsible for keeping the message history within a safe working limit.

Responsibilities:
    - Estimating token usage from current message history
    - Triggering summarisation when usage exceeds a configurable soft limit
      (default: 60% of model context length, capped at ~32k tokens regardless
      of model maximum)
    - Performing summarisation using a small, fast model (separate from the
      working model) via config.summarizer_model
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
    pass

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
            coder_model=router.parsed_model_for_role(AgentRole.CODER).model,
            coder_backend=router.backend_for_role(AgentRole.CODER),
            summarizer_backend=router.get_backend(config.summarizer_model),
            summarizer_model=router.local_model_for_role(config.summarizer_model),
        )
        loop = AgentLoop(..., context_manager=context_manager)

    The loop calls ``context_manager(messages, config)`` before each inference.

    Args:
        config: MatrixMouseConfig instance.
        paths: Resolved paths for this workspace.
        coder_model: Backend-local model identifier for the working agent
            (the portion after ``backend:`` in the full model string).
            Used only to query the context length via coder_backend.
        coder_backend: LLMBackend for the working agent — provides
            get_context_length().
        summarizer_backend: LLMBackend for the summarizer model.
        summarizer_model: Backend-local model identifier for the summarizer.
    """

    def __init__(
        self,
        config: MatrixMouseConfig,
        paths: MatrixMousePaths | RepoPaths,
        coder_model: str,
        coder_backend: LLMBackend,
        summarizer_backend: LLMBackend,
        summarizer_model: str,
    ) -> None:
        self.config = config
        self.paths = paths
        self._summarizer_backend = summarizer_backend
        self._summarizer_model = summarizer_model

        raw_limit = coder_backend.get_context_length(coder_model)
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

    def _summarise(self, messages: list) -> str:
        """Use the summarizer backend to produce a concise summary.

        Args:
            messages: The middle slice to summarise.

        Returns:
            Summary text as a string.
        """
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

        try:
            response = self._summarizer_backend.chat(
                model=self._summarizer_model,
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

        except Exception as e:
            logger.warning("Summarisation failed: %s. Using fallback summary.", e)
            return (
                f"(Summarisation failed: {e}. "
                f"{len(messages)} messages were compressed without summary.)"
            )

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
    coder_model: str,
    coder_backend: LLMBackend,
    summarizer_backend: LLMBackend,
    summarizer_model: str,
) -> list:
    """Functional interface for context checking — creates a ContextManager
    and calls it in one step.

    Useful for one-off checks. For repeated use, instantiate ContextManager
    directly so the context length is only queried once.

    Args:
        messages: Current message history.
        config: Active MatrixMouseConfig.
        paths: Resolved MatrixMousePaths.
        coder_model: Backend-local model identifier for the working agent.
        coder_backend: LLMBackend for the working agent.
        summarizer_backend: LLMBackend for the summarizer model.
        summarizer_model: Backend-local model identifier for the summarizer.

    Returns:
        The message list, compressed if necessary.
    """
    manager = ContextManager(
        config=config,
        paths=paths,
        coder_model=coder_model,
        coder_backend=coder_backend,
        summarizer_backend=summarizer_backend,
        summarizer_model=summarizer_model,
    )
    return manager(messages, config)