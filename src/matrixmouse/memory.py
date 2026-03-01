"""
matrixmouse/memory.py

Manages the agent's persistent external memory, which survives context compression.

Responsibilities:
    - Reading and writing named sections of AGENT_NOTES.md
    - Maintaining a section index so agents can request only the relevant section
    - Writing exploration results before compression discards them

Structured sections (defined in KNOWN_SECTIONS):
    file_map          — what files exist and what they contain
    key_functions     — important functions discovered during exploration
    open_questions    — unresolved ambiguities needing human input
    completed_subtasks — append-only log of what has been done
    known_issues      — bugs or problems discovered but not yet fixed

Section format in AGENT_NOTES.md:
    ## section_name
    <content>
    ## next_section_name
    ...

Design documents in docs/design/ are treated as read-only by the implementer
agent. Only the designer agent and orchestrator may write or amend them.
That enforcement lives in the orchestrator's phase prompt, not here.

Do not add inference logic or tool dispatch here.
"""

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Known sections — defines the expected structure of AGENT_NOTES.md
# ---------------------------------------------------------------------------

KNOWN_SECTIONS: dict[str, str] = {
    "file_map":           "Maps files to their purpose. Updated during exploration.",
    "key_functions":      "Important functions and classes discovered during exploration.",
    "open_questions":     "Unresolved ambiguities. Items here may warrant human input.",
    "completed_subtasks": "Append-only log of completed work. Never overwrite.",
    "known_issues":       "Bugs or problems discovered but not yet resolved.",
    "context_compression_log": "Auto-generated summaries from context compression events.",
}

# Regex to find a section header and capture its name
_SECTION_RE = re.compile(r"^## ([a-z_]+)\s*$", re.MULTILINE)


# ---------------------------------------------------------------------------
# MemoryManager
# ---------------------------------------------------------------------------

class MemoryManager:
    """
    Reads and writes named sections of AGENT_NOTES.md.

    Instantiated by the orchestrator and passed to subsystems that need
    persistent memory. Can also be used directly by tool functions.

    All operations are atomic at the file level — the file is read,
    modified in memory, and written back in full. This is safe for a
    single-agent single-process system. For concurrent agents, a proper
    database would be needed.
    """

    def __init__(self, notes_path: Path):
        """
        Args:
            notes_path: Path to AGENT_NOTES.md. Created if it doesn't exist.
        """
        self.notes_path = notes_path
        self._ensure_file()

    # ------------------------------------------------------------------
    # Public interface — used as tool functions and by subsystems
    # ------------------------------------------------------------------

    def read_section(self, section: str) -> str:
        """
        Read and return the content of a named section.

        Args:
            section: Section name, e.g. 'file_map', 'open_questions'.

        Returns:
            Section content as a string, empty string if the section
            exists but is empty, or an error message if not found.
        """
        section = section.strip().lower()
        sections = self._parse_sections()

        if section not in sections:
            available = list(sections.keys())
            return (
                f"Section '{section}' not found in AGENT_NOTES.md. "
                f"Available sections: {available}. "
                f"Use write_section() to create it."
            )

        content = sections[section].strip()
        if not content:
            return f"(Section '{section}' exists but is empty.)"
        return content

    def write_section(self, section: str, content: str) -> str:
        """
        Replace the entire content of a named section.
        Creates the section if it doesn't exist.

        Use this for structured data that should be fully replaced on each
        update, such as file_map or key_functions.

        Args:
            section: Section name. Must be lowercase with underscores only.
            content: New content for the section.

        Returns:
            Confirmation message.
        """
        section = section.strip().lower()
        if not _valid_section_name(section):
            return (
                f"ERROR: Invalid section name '{section}'. "
                "Use lowercase letters and underscores only."
            )

        sections = self._parse_sections()
        sections[section] = f"\n{content.strip()}\n"
        self._write_sections(sections)

        logger.debug("Memory: wrote section '%s' (%d chars).", section, len(content))
        return f"OK: Section '{section}' updated in AGENT_NOTES.md."

    def append_to_section(self, section: str, content: str) -> str:
        """
        Append content to a named section without replacing existing content.
        Creates the section if it doesn't exist.

        Use this for log-style sections that grow over time, such as
        completed_subtasks or context_compression_log.

        Args:
            section: Section name.
            content: Content to append.

        Returns:
            Confirmation message.
        """
        section = section.strip().lower()
        if not _valid_section_name(section):
            return (
                f"ERROR: Invalid section name '{section}'. "
                "Use lowercase letters and underscores only."
            )

        sections = self._parse_sections()
        existing = sections.get(section, "").rstrip()
        separator = "\n\n" if existing else "\n"
        sections[section] = f"\n{existing}{separator}{content.strip()}\n"
        self._write_sections(sections)

        logger.debug("Memory: appended to section '%s'.", section)
        return f"OK: Content appended to section '{section}' in AGENT_NOTES.md."

    def list_sections(self) -> str:
        """
        List all sections currently in AGENT_NOTES.md with a brief
        description of each known section.

        Returns:
            Formatted list of section names and descriptions.
        """
        sections = self._parse_sections()
        if not sections:
            return "AGENT_NOTES.md exists but contains no sections yet."

        lines = ["Sections in AGENT_NOTES.md:"]
        for name in sections:
            description = KNOWN_SECTIONS.get(name, "custom section")
            content = sections[name].strip()
            size = f"{len(content)} chars" if content else "empty"
            lines.append(f"  {name:30s} — {description} ({size})")

        return "\n".join(lines)

    def clear_section(self, section: str) -> str:
        """
        Clear the content of a section without removing the header.
        Useful for resetting sections at the start of a new task.

        Args:
            section: Section name to clear.

        Returns:
            Confirmation message, or error if section not found.
        """
        section = section.strip().lower()
        sections = self._parse_sections()

        if section not in sections:
            return f"ERROR: Section '{section}' not found."

        sections[section] = "\n"
        self._write_sections(sections)
        logger.debug("Memory: cleared section '%s'.", section)
        return f"OK: Section '{section}' cleared."

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_file(self) -> None:
        """
        Create AGENT_NOTES.md with all known sections if it doesn't exist.
        If it exists but is missing sections, leaves it unchanged —
        we don't want to clobber content written by a previous session.
        """
        if self.notes_path.exists():
            return

        self.notes_path.parent.mkdir(parents=True, exist_ok=True)
        sections = {name: "\n" for name in KNOWN_SECTIONS}
        self._write_sections(sections)
        logger.info("Created AGENT_NOTES.md at %s", self.notes_path)

    def _parse_sections(self) -> dict[str, str]:
        """
        Parse AGENT_NOTES.md into a dict of {section_name: content}.
        Preserves order. Content includes everything between this header
        and the next, excluding the headers themselves.
        """
        try:
            raw = self.notes_path.read_text(encoding="utf-8")
        except Exception as e:
            logger.error("Failed to read AGENT_NOTES.md: %s", e)
            return {}

        sections: dict[str, str] = {}
        matches = list(_SECTION_RE.finditer(raw))

        for i, match in enumerate(matches):
            name = match.group(1).lower()
            start = match.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(raw)
            sections[name] = raw[start:end]

        return sections

    def _write_sections(self, sections: dict[str, str]) -> None:
        """
        Serialise a sections dict back to AGENT_NOTES.md.
        Writes the file header comment once, then each section.
        """
        lines = [
            "# MatrixMouse Agent Notes",
            "# This file is the agent's working memory.",
            "# It is volatile — do not version control.",
            "# Human-readable but primarily agent-maintained.",
            "",
        ]

        for name, content in sections.items():
            lines.append(f"## {name}")
            lines.append(content if content.endswith("\n") else content + "\n")

        try:
            self.notes_path.write_text("\n".join(lines), encoding="utf-8")
        except Exception as e:
            logger.error("Failed to write AGENT_NOTES.md: %s", e)


# ---------------------------------------------------------------------------
# Validation helper
# ---------------------------------------------------------------------------

def _valid_section_name(name: str) -> bool:
    """Return True if name contains only lowercase letters and underscores."""
    return bool(re.match(r"^[a-z][a-z_]*$", name))


# ---------------------------------------------------------------------------
# Tool wrappers — these are what get registered in tools/__init__.py
# These require a MemoryManager instance, so they are thin wrappers
# that delegate to a module-level instance configured at startup.
# ---------------------------------------------------------------------------

_manager: MemoryManager | None = None


def configure(notes_path: Path) -> None:
    """
    Initialise the module-level MemoryManager.
    Call once at startup after paths are resolved.

    Args:
        notes_path: Path to AGENT_NOTES.md.
    """
    global _manager
    _manager = MemoryManager(notes_path)
    logger.info("Memory manager configured. Notes: %s", notes_path)


def _require_manager() -> MemoryManager | None:
    if _manager is None:
        logger.error(
            "Memory not configured. Call memory.configure(notes_path) at startup."
        )
    return _manager


def read_agent_notes(section: str) -> str:
    """
    Read one named section of the agent's persistent notes.

    Use this to recall what was discovered in earlier turns or previous
    sessions that may have been compressed out of context.

    Sections: file_map, key_functions, open_questions,
              completed_subtasks, known_issues.

    Args:
        section: The section name to read.

    Returns:
        Section content, or a message if the section is empty or missing.
    """
    m = _require_manager()
    if m is None:
        return "ERROR: Memory not configured."
    return m.read_section(section)


def update_agent_notes(section: str, content: str) -> str:
    """
    Write or replace a named section of the agent's persistent notes.

    Use this to record discoveries, file maps, or key findings that
    should survive context compression. For log-style sections like
    completed_subtasks, use append_agent_notes instead.

    Args:
        section: Section name (lowercase, underscores only).
        content: New content for the section. Replaces existing content.

    Returns:
        Confirmation message or error.
    """
    m = _require_manager()
    if m is None:
        return "ERROR: Memory not configured."
    return m.write_section(section, content)


def append_agent_notes(section: str, content: str) -> str:
    """
    Append content to a named section without replacing existing content.

    Use this for log-style sections that grow over time, such as
    completed_subtasks or known_issues.

    Args:
        section: Section name (lowercase, underscores only).
        content: Content to append to the section.

    Returns:
        Confirmation message or error.
    """
    m = _require_manager()
    if m is None:
        return "ERROR: Memory not configured."
    return m.append_to_section(section, content)


def list_agent_notes() -> str:
    """
    List all sections in the agent's notes file with their sizes.

    Use this at the start of a task to see what information has been
    recorded from previous sessions or earlier in this session.

    Returns:
        Formatted list of section names and content sizes.
    """
    m = _require_manager()
    if m is None:
        return "ERROR: Memory not configured."
    return m.list_sections()
