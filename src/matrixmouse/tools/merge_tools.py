"""
matrixmouse/tools/merge_tools.py

Tools for resolving git merge conflicts.

These tools are only available to the MergeAgent during a MERGE_RESOLUTION
session. They are not part of the normal tool schema for any other role.

Tools:
    show_conflict    — inspect conflict details for a file
    resolve_conflict — apply a resolution and auto-continue when done

configure(cwd) must be called before any tool is used.
"""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Module-level state — set by configure()
# ---------------------------------------------------------------------------

_cwd: Optional[Path] = None
_conflicted_files: list[str] = []
_resolved_files: set[str] = set()
_active_task_id: Optional[str] = None
_queue = None  # TaskRepository — for persisting decisions


def configure(
    conflicted_files: list[str],
    task_id: str,
    queue,
    cwd: Path | None = None,
) -> None:
    """
    Configure merge tools for a conflict resolution session.

    Called by the orchestrator before the MergeAgent loop starts.

    Args:
        cwd:              Repository root where the merge is in progress.
        conflicted_files: List of files with conflicts at session start.
        task_id:          ID of the task being merged.
        queue:            TaskRepository — for persisting resolution decisions.
    """
    global _cwd, _conflicted_files, _resolved_files, _active_task_id, _queue
    _cwd = cwd
    _conflicted_files = list(conflicted_files)
    _resolved_files = set()
    _active_task_id = task_id
    _queue = queue
    logger.debug(
        "merge_tools configured. task=%s cwd=%s conflicts=%s",
        task_id, cwd, conflicted_files,
    )


def _require_cwd() -> Path:
    if _cwd is None:
        raise RuntimeError(
            "merge_tools not configured. "
            "Call merge_tools.configure() before using merge tools."
        )
    return _cwd


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

def show_conflict(file: str) -> str:
    """
    Show the conflict details for a file.

    Returns the three versions of the conflicting region side by side:
    ours (current branch), theirs (branch being merged), and the common
    base ancestor. Use this before calling resolve_conflict so you
    understand what each side changed.

    Args:
        file (str): Path to the conflicted file, relative to the repo root.

    Returns:
        str: Structured conflict information showing ours, theirs, and base.
    """
    cwd = _require_cwd()
    file_path = cwd / file

    if not file_path.exists():
        return f"ERROR: File '{file}' not found."

    # Read the raw conflict markers from the file
    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return f"ERROR: Could not read '{file}': {e}"

    if "<<<<<<<" not in content:
        return (
            f"No conflict markers found in '{file}'. "
            f"This file may already be resolved or may not be conflicted."
        )

    # Extract ours, base, and theirs from conflict markers
    # Standard format:
    # <<<<<<< HEAD
    # (ours)
    # ||||||| base  (only with merge.conflictstyle=diff3)
    # (base)
    # =======
    # (theirs)
    # >>>>>>> branch
    sections = _parse_conflict_markers(content)

    lines = [f"Conflict in: {file}", ""]
    for i, section in enumerate(sections, 1):
        lines.append(f"--- Conflict hunk {i} ---")
        lines.append(f"[OURS (current branch)]:\n{section['ours']}")
        if section.get("base"):
            lines.append(f"[BASE (common ancestor)]:\n{section['base']}")
        lines.append(f"[THEIRS (merging branch)]:\n{section['theirs']}")
        lines.append("")

    # Also show file-level diff stats
    result = subprocess.run(
        ["git", "diff", "--stat", "HEAD", "--", file],
        cwd=cwd, capture_output=True, text=True,
    )
    if result.returncode == 0 and result.stdout.strip():
        lines.append(f"Diff stats: {result.stdout.strip()}")

    return "\n".join(lines)


SHOW_CONFLICT_SCHEMA = {
    "name": "show_conflict",
    "description": (
        "Inspect the conflict markers in a file. Shows ours (current branch), "
        "theirs (merging branch), and base (common ancestor) for each hunk. "
        "Call this before resolve_conflict to understand what each side changed."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "file": {
                "type": "string",
                "description": "Path to the conflicted file, relative to the repo root.",
            },
        },
        "required": ["file"],
    },
}


def resolve_conflict(
    file: str,
    resolution: str,
    content: Optional[str] = None,
) -> str:
    """
    Apply a resolution to a conflicted file.

    After resolving all conflicted files, the merge is finalised
    automatically — you do not need to call any additional tool.

    Args:
        file (str): Path to the conflicted file, relative to the repo root.
        resolution (str): One of:
            'ours'   — keep the current branch (HEAD) version entirely.
            'theirs' — keep the merging branch version entirely.
            'manual' — provide a fully merged version via the content parameter.
        content (str, optional): Required when resolution is 'manual'.
            The complete merged file content, with all conflicts resolved.

    Returns:
        str: Confirmation, or an error message.
    """
    cwd = _require_cwd()

    if resolution not in ("ours", "theirs", "manual"):
        return (
            f"ERROR: Invalid resolution '{resolution}'. "
            f"Must be one of: 'ours', 'theirs', 'manual'."
        )

    if resolution == "manual" and not content:
        return (
            "ERROR: resolution='manual' requires content parameter. "
            "Provide the complete merged file content."
        )

    file_path = cwd / file
    if not file_path.exists():
        return f"ERROR: File '{file}' not found."

    try:
        if resolution == "ours":
            result = subprocess.run(
                ["git", "checkout", "--ours", "--", file],
                cwd=cwd, capture_output=True, text=True,
            )
            if result.returncode != 0:
                return f"ERROR: git checkout --ours failed: {result.stderr.strip()}"

        elif resolution == "theirs":
            result = subprocess.run(
                ["git", "checkout", "--theirs", "--", file],
                cwd=cwd, capture_output=True, text=True,
            )
            if result.returncode != 0:
                return (
                    f"ERROR: git checkout --theirs failed: {result.stderr.strip()}"
                )

        elif resolution == "manual":
            if not content:
                return (
                    f"ERROR: content must not be empty if resolution is manual"
                )
            file_path.write_text(content, encoding="utf-8")

        # Stage the resolved file
        result = subprocess.run(
            ["git", "add", "--", file],
            cwd=cwd, capture_output=True, text=True,
        )
        if result.returncode != 0:
            return f"ERROR: git add failed after resolution: {result.stderr.strip()}"

    except Exception as e:
        return f"ERROR: Failed to apply resolution for '{file}': {e}"

    _resolved_files.add(file)

    # Persist the decision to the task for replay on resume
    _persist_decision(file, resolution, content)

    logger.info(
        "Conflict resolved: '%s' via '%s' (task %s)",
        file, resolution, _active_task_id,
    )

    # Check if all conflicts are now resolved
    remaining = [f for f in _conflicted_files if f not in _resolved_files]
    if not remaining:
        return _finalise_merge()

    return (
        f"OK: '{file}' resolved using '{resolution}'. "
        f"{len(remaining)} conflict(s) remaining: {', '.join(remaining)}"
    )


RESOLVE_CONFLICT_SCHEMA = {
    "name": "resolve_conflict",
    "description": (
        "Apply a resolution to a conflicted file and stage it. "
        "When the last conflict is resolved the merge is finalised automatically."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "file": {
                "type": "string",
                "description": "Path to the conflicted file, relative to the repo root.",
            },
            "resolution": {
                "type": "string",
                "enum": ["ours", "theirs", "manual"],
                "description": (
                    "'ours' — keep the current branch (HEAD) version entirely. "
                    "'theirs' — keep the merging branch version entirely. "
                    "'manual' — provide a fully merged file via the content parameter."
                ),
            },
            "content": {
                "type": "string",
                "description": (
                    "Complete merged file content with all conflict markers removed. "
                    "Required when resolution is 'manual', ignored otherwise."
                ),
            },
        },
        "required": ["file", "resolution"],
    },
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_conflict_markers(content: str) -> list[dict]:
    """
    Parse conflict marker sections from file content.

    Returns a list of dicts with keys: ours, base (optional), theirs.
    """
    sections = []
    lines = content.splitlines(keepends=True)

    i = 0
    while i < len(lines):
        if lines[i].startswith("<<<<<<<"):
            ours_lines = []
            base_lines = []
            theirs_lines = []
            mode = "ours"
            i += 1
            while i < len(lines):
                line = lines[i]
                if line.startswith("|||||||"):
                    mode = "base"
                    i += 1
                    continue
                elif line.startswith("======="):
                    mode = "theirs"
                    i += 1
                    continue
                elif line.startswith(">>>>>>>"):
                    i += 1
                    break
                if mode == "ours":
                    ours_lines.append(line)
                elif mode == "base":
                    base_lines.append(line)
                elif mode == "theirs":
                    theirs_lines.append(line)
                i += 1
            sections.append({
                "ours":  "".join(ours_lines).rstrip(),
                "base":  "".join(base_lines).rstrip() if base_lines else None,
                "theirs": "".join(theirs_lines).rstrip(),
            })
        else:
            i += 1

    return sections


def _persist_decision(
    file: str,
    resolution: str,
    content: Optional[str],
) -> None:
    """Persist a resolution decision to the task for replay on resume."""
    if _queue is None or _active_task_id is None:
        return
    try:
        task = _queue.get(_active_task_id)
        if task is None:
            return
        task.merge_resolution_decisions.append({
            "file":       file,
            "resolution": resolution,
            "content":    content,
        })
        _queue.update(task)
    except Exception as e:
        logger.warning(
            "Failed to persist merge decision for task [%s]: %s",
            _active_task_id, e,
        )


def _finalise_merge() -> str:
    """
    All conflicts resolved — run git merge --continue.

    Called automatically by resolve_conflict when the last conflict
    is resolved. The agent does not need to call this explicitly.
    """
    cwd = _require_cwd()
    try:
        result = subprocess.run(
            ["git", "merge", "--continue", "--no-edit"],
            cwd=cwd, capture_output=True, text=True,
            env={**os.environ, "GIT_EDITOR": "true"},
        )
        if result.returncode != 0:
            return (
                f"ERROR: git merge --continue failed: {result.stderr.strip()}. "
                f"There may be additional issues to resolve."
            )
        logger.info(
            "Merge finalised for task [%s]. Output: %s",
            _active_task_id, result.stdout.strip()[:120],
        )
        return (
            "OK: All conflicts resolved. Merge finalised successfully.\n"
            "Call declare_complete to mark this task as done."
        )
    except Exception as e:
        return f"ERROR: Failed to finalise merge: {e}"


def get_conflicted_files(cwd: Path) -> list[str]:
    """
    Return the list of files currently in conflict.

    Used by the orchestrator to populate the conflict notification
    message and configure merge_tools.

    Args:
        cwd: Repository root.

    Returns:
        List of file paths with conflict markers.
    """
    result = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=U"],
        cwd=cwd, capture_output=True, text=True,
    )
    if result.returncode != 0:
        return []
    return [f.strip() for f in result.stdout.splitlines() if f.strip()]
