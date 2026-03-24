"""
tests/tools/test_merge_tools.py

Tests for matrixmouse.tools.merge_tools.

Coverage:
    configure:
        - Sets cwd, conflicted_files, task_id, queue
        - Resets resolved_files on each configure call

    show_conflict:
        - Returns error when file not found
        - Returns error when no conflict markers present
        - Returns ours and theirs sections for conflicted file
        - Handles diff3 style with base section

    resolve_conflict:
        - Rejects invalid resolution
        - Rejects manual without content
        - Returns error when file not found
        - Applies 'ours' resolution
        - Applies 'theirs' resolution
        - Applies 'manual' resolution with content
        - Persists decision to task
        - Reports remaining conflicts after resolution
        - Auto-finalises when all conflicts resolved
        - Does not finalise when conflicts remain

    get_conflicted_files:
        - Returns empty list when no conflicts
        - Returns list of conflicted files
"""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from matrixmouse.tools import merge_tools
from matrixmouse.tools.merge_tools import (
    show_conflict,
    resolve_conflict,
    get_conflicted_files,
)
from matrixmouse.task import AgentRole, Task, TaskStatus
from matrixmouse.repository.memory_task_repository import InMemoryTaskRepository


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_task(**kwargs) -> Task:
    defaults = dict(
        title="merge task",
        description="resolve conflicts",
        role=AgentRole.MERGE,
        repo=["repo"],
    )
    defaults.update(kwargs)
    return Task(**defaults)


def make_conflicted_file(path: Path, ours: str, theirs: str) -> None:
    """Write a file with standard git conflict markers."""
    path.write_text(
        f"<<<<<<< HEAD\n{ours}\n=======\n{theirs}\n>>>>>>> branch\n",
        encoding="utf-8",
    )


def setup_merge_tools(
    tmp_path: Path,
    conflicted_files: list[str] | None = None,
    task: Task | None = None,
    queue=None,
) -> tuple[Task, InMemoryTaskRepository]:
    q = queue or InMemoryTaskRepository()
    t = task or make_task()
    q.add(t)
    merge_tools.configure(
        cwd=tmp_path,
        conflicted_files=conflicted_files or [],
        task_id=t.id,
        queue=q,
    )
    return t, q


# ---------------------------------------------------------------------------
# configure
# ---------------------------------------------------------------------------

class TestConfigure:
    def test_sets_cwd(self, tmp_path):
        setup_merge_tools(tmp_path)
        assert merge_tools._cwd == tmp_path

    def test_sets_conflicted_files(self, tmp_path):
        setup_merge_tools(tmp_path, conflicted_files=["foo.py", "bar.py"])
        assert merge_tools._conflicted_files == ["foo.py", "bar.py"]

    def test_resets_resolved_files(self, tmp_path):
        setup_merge_tools(tmp_path, conflicted_files=["foo.py"])
        merge_tools._resolved_files.add("foo.py")
        setup_merge_tools(tmp_path, conflicted_files=["bar.py"])
        assert merge_tools._resolved_files == set()

    def test_sets_task_id(self, tmp_path):
        t, _ = setup_merge_tools(tmp_path)
        assert merge_tools._active_task_id == t.id


# ---------------------------------------------------------------------------
# show_conflict
# ---------------------------------------------------------------------------

class TestShowConflict:
    def test_returns_error_when_file_not_found(self, tmp_path):
        setup_merge_tools(tmp_path)
        result = show_conflict("nonexistent.py")
        assert "ERROR" in result

    def test_returns_error_when_no_conflict_markers(self, tmp_path):
        setup_merge_tools(tmp_path)
        (tmp_path / "clean.py").write_text("no conflicts here")
        result = show_conflict("clean.py")
        assert "No conflict markers" in result

    def test_returns_ours_and_theirs_sections(self, tmp_path):
        setup_merge_tools(tmp_path, conflicted_files=["foo.py"])
        make_conflicted_file(
            tmp_path / "foo.py",
            ours="def foo(): return 1",
            theirs="def foo(): return 2",
        )
        result = show_conflict("foo.py")
        assert "OURS" in result
        assert "THEIRS" in result
        assert "def foo(): return 1" in result
        assert "def foo(): return 2" in result

    def test_handles_diff3_style_with_base(self, tmp_path):
        setup_merge_tools(tmp_path, conflicted_files=["foo.py"])
        (tmp_path / "foo.py").write_text(
            "<<<<<<< HEAD\nours\n||||||| base\nbase\n=======\ntheirs\n>>>>>>> branch\n"
        )
        result = show_conflict("foo.py")
        assert "BASE" in result
        assert "base" in result

    def test_includes_filename_in_output(self, tmp_path):
        setup_merge_tools(tmp_path, conflicted_files=["foo.py"])
        make_conflicted_file(tmp_path / "foo.py", "a", "b")
        result = show_conflict("foo.py")
        assert "foo.py" in result


# ---------------------------------------------------------------------------
# resolve_conflict
# ---------------------------------------------------------------------------

class TestResolveConflict:
    def test_rejects_invalid_resolution(self, tmp_path):
        setup_merge_tools(tmp_path, conflicted_files=["foo.py"])
        make_conflicted_file(tmp_path / "foo.py", "a", "b")
        result = resolve_conflict("foo.py", "invalid")
        assert "ERROR" in result

    def test_rejects_manual_without_content(self, tmp_path):
        setup_merge_tools(tmp_path, conflicted_files=["foo.py"])
        make_conflicted_file(tmp_path / "foo.py", "a", "b")
        result = resolve_conflict("foo.py", "manual")
        assert "ERROR" in result
        assert "content" in result

    def test_returns_error_when_file_not_found(self, tmp_path):
        setup_merge_tools(tmp_path, conflicted_files=["missing.py"])
        result = resolve_conflict("missing.py", "ours")
        assert "ERROR" in result

    def test_applies_manual_resolution(self, tmp_path):
        setup_merge_tools(tmp_path, conflicted_files=["foo.py"])
        make_conflicted_file(tmp_path / "foo.py", "a", "b")
        merged = "def foo(): return 42"
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            result = resolve_conflict("foo.py", "manual", content=merged)
        assert "ERROR" not in result
        assert (tmp_path / "foo.py").read_text() == merged

    def test_persists_decision_to_task(self, tmp_path):
        t, q = setup_merge_tools(tmp_path, conflicted_files=["foo.py"])
        make_conflicted_file(tmp_path / "foo.py", "a", "b")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            resolve_conflict("foo.py", "ours")
        updated = q.get(t.id)
        assert updated is not None
        assert len(updated.merge_resolution_decisions) == 1
        assert updated.merge_resolution_decisions[0]["file"] == "foo.py"
        assert updated.merge_resolution_decisions[0]["resolution"] == "ours"

    def test_reports_remaining_conflicts(self, tmp_path):
        setup_merge_tools(
            tmp_path, conflicted_files=["foo.py", "bar.py"]
        )
        make_conflicted_file(tmp_path / "foo.py", "a", "b")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            result = resolve_conflict("foo.py", "ours")
        assert "1 conflict(s) remaining" in result
        assert "bar.py" in result

    def test_auto_finalises_when_all_resolved(self, tmp_path):
        setup_merge_tools(tmp_path, conflicted_files=["foo.py"])
        make_conflicted_file(tmp_path / "foo.py", "a", "b")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout="merge complete", stderr=""
            )
            result = resolve_conflict("foo.py", "ours")
        assert "finalised" in result.lower() or "complete" in result.lower()

    def test_does_not_finalise_when_conflicts_remain(self, tmp_path):
        setup_merge_tools(
            tmp_path, conflicted_files=["foo.py", "bar.py"]
        )
        make_conflicted_file(tmp_path / "foo.py", "a", "b")
        finalise_called = []
        original_finalise = merge_tools._finalise_merge

        def mock_finalise():
            finalise_called.append(True)
            return original_finalise()

        with patch("subprocess.run") as mock_run, \
             patch("matrixmouse.tools.merge_tools._finalise_merge",
                   side_effect=mock_finalise):
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            resolve_conflict("foo.py", "ours")

        assert len(finalise_called) == 0


# ---------------------------------------------------------------------------
# get_conflicted_files
# ---------------------------------------------------------------------------

class TestGetConflictedFiles:
    def test_returns_empty_list_when_no_conflicts(self, tmp_path):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout="", stderr=""
            )
            result = get_conflicted_files(tmp_path)
        assert result == []

    def test_returns_conflicted_files(self, tmp_path):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="foo.py\nbar.py\n",
                stderr="",
            )
            result = get_conflicted_files(tmp_path)
        assert result == ["foo.py", "bar.py"]

    def test_returns_empty_on_git_error(self, tmp_path):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=128, stdout="", stderr="not a git repo"
            )
            result = get_conflicted_files(tmp_path)
        assert result == []
        