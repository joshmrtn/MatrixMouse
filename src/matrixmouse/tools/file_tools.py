"""
matrixmouse/tools/file_tools.py

Tools for reading and writing files within the project.
All functions enforce path safety via _safety.py before any filesystem access.

Tools exposed:
    read_file      — full file contents as a string
    str_replace    — replace a unique string in a file
    append_to_file — append content to the end of a file

Do not add navigation, git, or AST tools here.
"""

import logging
from matrixmouse.tools._safety import is_safe_path

from matrixmouse.tools import code_tools
from matrixmouse.codemap import ProjectAnalyzer

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Module state — set via configure() at task start
# ---------------------------------------------------------------------------

_graph: ProjectAnalyzer | None = None


def configure(graph: ProjectAnalyzer) -> None:
    """
    Initialise file tools with the task's ProjectAnalyzer.

    Called at task start by the orchestrator with the task's graph.
    Safe to call again after the graph is updated.

    Args:
        graph: A populated ProjectAnalyzer instance from codemap.
    """
    global _graph
    # Break potential reference cycles in old graph before setting new one
    if _graph is not None:
        _graph.calls.clear()
        _graph.called_by.clear()
    _graph = graph
    logger.debug("File tools configured with ProjectAnalyzer.")


def read_file(filename: str) -> str:
    """
    Read and return the entire contents of a file.
    Use this to inspect a file before editing it.

    Args:
        filename: Path to the file to read. Must be within the project root.

    Returns:
        File contents as a string, or an error message if the file cannot
        be read or the path is not permitted.
    """
    allowed, result = is_safe_path(filename, write=False)
    if not allowed:
        logger.warning("read_file blocked: %s — %s", filename, result)
        return f"ERROR: Access denied — {result}"

    try:
        with open(result, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except FileNotFoundError:
        return f"ERROR: File not found: {filename}"
    except Exception as e:
        return f"ERROR reading {filename}: {e}"


def str_replace(filename: str, old_str: str, new_str: str) -> str:
    """
    Replace a unique string in a file with new content.

    The old_str must appear exactly once in the file — this prevents
    accidental edits when the same string appears in multiple places.
    If it appears zero or more than once, no changes are made.

    Use read_file first to confirm the exact string to replace.

    Args:
        filename: Path to the file to edit. Must be within the project root.
        old_str:  The exact string to find and replace. Must be unique in the file.
        new_str:  The string to replace old_str with.

    Returns:
        Success message, or an error describing why the replacement failed.
    """
    allowed, result = is_safe_path(filename, write=True)
    if not allowed:
        logger.warning("str_replace blocked: %s — %s", filename, result)
        return f"ERROR: Access denied — {result}"

    try:
        with open(result, "r", encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        return f"ERROR: File not found: {filename}"
    except Exception as e:
        return f"ERROR reading {filename}: {e}"

    count = content.count(old_str)
    if count == 0:
        return (
            f"ERROR: The string was not found in {filename}. No changes made. "
            "Check that the string matches exactly, including whitespace and indentation."
        )
    if count > 1:
        return (
            f"ERROR: The string appears {count} times in {filename}. "
            "No changes made. Provide more surrounding context to make it unambiguous."
        )

    updated = content.replace(old_str, new_str, 1)

    try:
        with open(result, "w", encoding="utf-8") as f:
            f.write(updated)
    except Exception as e:
        return f"ERROR writing {filename}: {e}"

    # Update graph for this file
    if _graph is not None:
        _graph.update_file(result)

    logger.info("str_replace: %s — replaced 1 occurrence.", filename)
    return "OK: Replacement made successfully."


def append_to_file(filename: str, content: str) -> str:
    """
    Append content to the end of a file. Creates the file if it does not exist.
    Adds a newline after the content.

    Use this for adding new functions, classes, or sections to an existing file.
    For modifying existing content, use str_replace instead.

    Args:
        filename: Path to the file to append to. Must be within the project root.
        content:  The content to append. Use triple-quoted strings for multiline content.

    Returns:
        Success message, or an error describing why the append failed.
    """
    allowed, result = is_safe_path(filename, write=True)
    if not allowed:
        logger.warning("append_to_file blocked: %s — %s", filename, result)
        return f"ERROR: Access denied — {result}"

    try:
        with open(result, "a", encoding="utf-8") as f:
            f.write(content)
            if not content.endswith("\n"):
                f.write("\n")
    except Exception as e:
        return f"ERROR appending to {filename}: {e}"

    # Update graph for this file
    if _graph is not None:
        _graph.update_file(result)

    logger.info("append_to_file: %s", filename)
    return f"OK: Content appended to {filename} successfully."


READ_FILE_SCHEMA = {
    "name": "read_file",
    "description": (
        "Read and return the entire contents of a file. "
        "Use this to inspect a file before editing it."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "filename": {
                "type": "string",
                "description": "Path to the file to read. Must be within the project root.",
            },
        },
        "required": ["filename"],
    },
}

STR_REPLACE_SCHEMA = {
    "name": "str_replace",
    "description": (
        "Replace a unique string in a file with new content. "
        "old_str must appear exactly once — if it appears zero or more than once, "
        "no changes are made. Use read_file first to confirm the exact string, "
        "including whitespace and indentation."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "filename": {
                "type": "string",
                "description": "Path to the file to edit. Must be within the project root.",
            },
            "old_str": {
                "type": "string",
                "description": (
                    "The exact string to find and replace. "
                    "Must appear exactly once in the file. "
                    "Include enough surrounding context to make it unambiguous."
                ),
            },
            "new_str": {
                "type": "string",
                "description": "The string to replace old_str with.",
            },
        },
        "required": ["filename", "old_str", "new_str"],
    },
}

APPEND_TO_FILE_SCHEMA = {
    "name": "append_to_file",
    "description": (
        "Append content to the end of a file. Creates the file if it does not exist. "
        "Use this for adding new functions, classes, or sections. "
        "For modifying existing content, use str_replace instead."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "filename": {
                "type": "string",
                "description": "Path to the file to append to. Must be within the project root.",
            },
            "content": {
                "type": "string",
                "description": "The content to append.",
            },
        },
        "required": ["filename", "content"],
    },
}