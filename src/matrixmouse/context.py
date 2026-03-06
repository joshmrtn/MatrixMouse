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

Context limits are set per model at startup via ollama.show(), not hardcoded.

Do not add inference logic or tool dispatch here.
"""

import logging
from pathlib import Path
from typing import Any

import ollama

from matrixmouse.config import MatrixMouseConfig, MatrixMousePaths, RepoPaths

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Token estimation
# ---------------------------------------------------------------------------

def estimate_tokens(messages: list) -> int:
    """
    Estimate the total token count of a message history.

    Uses a character-based heuristic (~4 chars per token) which is
    intentionally conservative — it's better to compress slightly early
    than to let the context overflow. Accurate enough for triggering
    compression; not suitable for billing or precise model limits.

    Args:
        messages: List of message dicts or ollama message objects.

    Returns:
        Estimated token count as an integer.
    """
    total_chars = 0
    for message in messages:
        # Handle both dict messages and ollama Message objects
        if isinstance(message, dict):
            content = message.get("content") or ""
        else:
            content = getattr(message, "content", "") or ""
        total_chars += len(content)
    return total_chars // 4


def get_model_context_length(model_name: str) -> int:
    """
    Query Ollama for the context length of a given model.

    Falls back to a conservative default if the value cannot be
    determined, rather than raising — a wrong limit is recoverable,
    a crash at startup is not.

    Args:
        model_name: The Ollama model identifier.

    Returns:
        Context length in tokens.
    """
    fallback = 8192
    try:
        info = ollama.show(model_name)
        model_info = getattr(info, "modelinfo", {}) or {}

        # Key name varies by model family — try common variants
        for key in ("general.context_length", "context_length"):
            if key in model_info:
                return int(model_info[key])

        # Some models expose it under a family-prefixed key
        # e.g. "llama.context_length", "qwen2.context_length"
        for key, value in model_info.items():
            if "context_length" in key:
                return int(value)

        logger.warning(
            "Could not find context_length for %s. Using fallback: %d",
            model_name, fallback
        )
        return fallback

    except Exception as e:
        logger.warning(
            "Failed to query context length for %s: %s. Using fallback: %d",
            model_name, e, fallback
        )
        return fallback


# ---------------------------------------------------------------------------
# Context manager — the callable passed into AgentLoop
# ---------------------------------------------------------------------------

class ContextManager:
    """
    Monitors message history size and compresses when approaching the limit.

    Designed to be passed into AgentLoop as the context_manager callable:

        context_manager = ContextManager(config, paths, model="qwen2.5-coder:7b")
        loop = AgentLoop(..., context_manager=context_manager)

    The loop calls context_manager(messages, config) before each inference.
    """

    def __init__(
        self,
        config: MatrixMouseConfig,
        paths: MatrixMousePaths | RepoPaths,
        coder_model: str,
    ):
        self.config = config
        self.paths = paths
        self.coder_model = coder_model

        # Determine the effective token limit for this model
        raw_limit = get_model_context_length(coder_model)
        self.token_limit = min(raw_limit, config.context_soft_limit)
        self.compress_at = int(self.token_limit * config.compress_threshold)

        logger.info(
            "ContextManager ready. Model limit: %d, soft limit: %d, "
            "compress threshold: %d tokens.",
            raw_limit, self.token_limit, self.compress_at
        )

    def __call__(self, messages: list, config: MatrixMouseConfig) -> list:
        """
        Check token usage and compress history if needed.
        This is the interface AgentLoop expects.

        Args:
            messages: Current message history.
            config:   Active config (passed by the loop, may differ from init).

        Returns:
            The message list, compressed if necessary.
        """
        estimated = estimate_tokens(messages)

        if estimated < self.compress_at:
            logger.debug(
                "Context OK: ~%d tokens (limit %d).", estimated, self.compress_at
            )
            return messages

        logger.info(
            "Context near limit (~%d tokens, threshold %d). Compressing...",
            estimated, self.compress_at
        )
        return self._compress(messages)

    def _compress(self, messages: list) -> list:
        """
        Summarise the middle of the message history, preserving the
        system prompt, original user instruction, and last N turns.

        Writes a brief record of discoveries to AGENT_NOTES.md before
        compressing so nothing important is silently discarded.

        Args:
            messages: Full message history to compress.

        Returns:
            Compressed message list.
        """
        keep = self.config.keep_last_n_turns

        # Need at least system + instruction + something to compress + recent
        if len(messages) <= keep + 2:
            logger.debug("History too short to compress (%d messages).", len(messages))
            return messages

        system_msg = messages[0]
        instruction_msg = messages[1]
        middle = messages[2 : len(messages) - keep]
        recent = messages[len(messages) - keep :]

        if not middle:
            return messages

        # Write discoveries to notes before compressing
        self._save_discoveries_to_notes(middle)

        # Summarise the middle
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
        original_tokens = estimate_tokens(messages)
        compressed_tokens = estimate_tokens(compressed)

        logger.info(
            "Compression complete. %d messages → %d messages. "
            "~%d tokens → ~%d tokens.",
            len(messages), len(compressed),
            original_tokens, compressed_tokens
        )
        return compressed

    def _summarise(self, messages: list) -> str:
        """
        Use the summarizer model to produce a concise summary of a
        slice of message history.

        Args:
            messages: The middle slice to summarise.

        Returns:
            Summary text as a string.
        """
        # Build a plain transcript from the messages to summarise
        transcript_parts = []
        for m in messages:
            if isinstance(m, dict):
                role = m.get("role", "unknown")
                content = m.get("content") or ""
            else:
                role = getattr(m, "role", "unknown")
                content = getattr(m, "content", "") or ""

            if content.strip():
                transcript_parts.append(f"{role.upper()}: {content.strip()}")

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
            response = ollama.chat(
                model=self.config.summarizer_model,
                messages=[{"role": "user", "content": prompt}],
                stream=False,
                keep_alive="30m",
            )
            return response.message.content or "(Empty summary returned.)"

        except Exception as e:
            logger.warning("Summarisation failed: %s. Using fallback summary.", e)
            return (
                f"(Summarisation failed: {e}. "
                f"{len(messages)} messages were compressed without summary.)"
            )


    def _save_discoveries_to_notes(self, messages: list) -> None:
        """
        Extract and append any notable discoveries from the messages
        being compressed to AGENT_NOTES.md, so they survive compression.
    
        This is a best-effort operation — failures are logged but do not
        block compression.
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
    
            memory._manager.append_to_section("context_compression_log", entry)
            logger.debug("Discoveries written to context_compression_log before compression.")

        except Exception as e:
            logger.warning("Failed to write discoveries to notes: %s", e)

# ---------------------------------------------------------------------------
# Convenience function for use before ContextManager is wired into the loop
# ---------------------------------------------------------------------------

def check_and_compress(
    messages: list,
    config: MatrixMouseConfig,
    paths: MatrixMousePaths | RepoPaths,
    coder_model: str,
) -> list:
    """
    Functional interface for context checking — creates a ContextManager
    and calls it in one step.

    Useful for one-off checks or before the full ContextManager is wired
    into AgentLoop. For repeated use, instantiate ContextManager directly
    so the token limit is only queried from Ollama once.

    Args:
        messages:    Current message history.
        config:      Active MatrixMouseConfig.
        paths:       Resolved MatrixMousePaths.
        coder_model: The model whose context limit to respect.

    Returns:
        The message list, compressed if necessary.
    """
    manager = ContextManager(config=config, paths=paths, coder_model=coder_model)
    return manager(messages, config)
