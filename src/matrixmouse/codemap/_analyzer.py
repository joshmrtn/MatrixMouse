"""
matrixmouse/codemap/_analyzer.py

ProjectAnalyzer — owns I/O and graph state for the codemap package.

One instance per task workspace. Create via analyze_project(root_dir).
Rebuild at task start/resume. Discard on context switch.

Not thread-safe. Do not share instances across workers or tasks.

Classes:
    ProjectAnalyzer: Maintains a static call graph of a project codebase.

Functions:
    analyze_project: Walk a directory and analyze all files.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from matrixmouse.codemap._types import ExtractionResult, LanguageExtractor
from matrixmouse.codemap._registry import get_extractor

logger = logging.getLogger(__name__)


class ProjectAnalyzer:
    """
    Maintains a static call graph of a project codebase.

    One instance per task workspace. Create via analyze_project(root_dir).
    Rebuild at task start/resume. Discard on context switch.

    Not thread-safe. Do not share instances across workers or tasks.

    Attributes:
        functions: Dict of qualified_name -> function metadata.
        symbols: Dict of name -> symbol metadata.
        calls: Dict of caller -> set of callees.
        called_by: Dict of callee -> set of callers.
        imports: Dict of filepath -> list of import strings.
    """

    def __init__(self) -> None:
        """
        Initialize an empty ProjectAnalyzer.

        All graph containers start empty. Call analyze_file() or
        analyze_project() to populate.
        """
        self.functions: dict[str, dict] = {}
        self.symbols: dict[str, dict] = {}
        self.calls: dict[str, set[str]] = {}
        self.called_by: dict[str, set[str]] = {}
        self.imports: dict[str, list[str]] = {}

    def analyze_file(self, filepath: str) -> None:
        """
        Parse a single file and merge its data into the graph.

        Removes stale entries for this filepath first — safe to call
        on update. Silently skips files with no registered extractor.
        Silently skips unreadable files (logs warning).

        Args:
            filepath: Absolute path to the file to analyze.
        """
        # Look up extractor — silently skip if none registered
        extractor = get_extractor(filepath)
        if extractor is None:
            logger.debug("No extractor for %s — skipping.", filepath)
            return

        # Read source — log warning and return if unreadable
        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                source = f.read()
        except Exception as e:
            logger.warning("Failed to read %s: %s — skipping.", filepath, e)
            return

        # Remove stale entries for this file
        self._remove_file_contributions(filepath)

        # Extract — wrap in try/except as defence in depth
        try:
            result = extractor.extract(filepath, source)
        except Exception as e:
            logger.warning(
                "Extractor failed for %s: %s — skipping.", filepath, e
            )
            return

        # Merge into graph
        self._merge(filepath, result)

    def update_file(self, filepath: str) -> None:
        """
        Re-analyze a file after it has been written.

        Named alias for analyze_file() — exists to make call sites
        self-documenting.

        Args:
            filepath: Absolute path to the file to update.
        """
        logger.debug("Updating graph for %s", filepath)
        self.analyze_file(filepath)

    def _remove_file_contributions(self, filepath: str) -> None:
        """
        Remove all graph entries originating from filepath.

        Cleans functions, symbols, calls, called_by, imports.
        called_by reverse index is cleaned by iterating each affected
        callee set.

        Args:
            filepath: The file whose contributions should be removed.
        """
        # Remove functions from this file
        stale_funcs = [
            name for name, info in self.functions.items()
            if info.get("file") == filepath
        ]
        for name in stale_funcs:
            self.functions.pop(name, None)
            # Remove from called_by (as callee) — iterate only affected callee sets
            # Must do this BEFORE removing from calls
            for callee in self.calls.get(name, set()):
                self.called_by.get(callee, set()).discard(name)
            # Remove from calls (as caller)
            self.calls.pop(name, None)

        # Remove symbols from this file
        stale_symbols = [
            name for name, info in self.symbols.items()
            if info.get("file") == filepath
        ]
        for name in stale_symbols:
            self.symbols.pop(name, None)

        # Remove imports from this file
        self.imports.pop(filepath, None)

    def _merge(self, filepath: str, result: ExtractionResult) -> None:
        """
        Merge an ExtractionResult into the graph's dicts.

        Always called after _remove_file_contributions.

        Args:
            filepath: Absolute path to the analyzed file.
            result: ExtractionResult from the language extractor.
        """
        # Merge functions — shallow copy to prevent extractor dict reuse issues
        for name, info in result.functions.items():
            self.functions[name] = info.copy()

        # Merge symbols — shallow copy to prevent extractor dict reuse issues
        for name, info in result.symbols.items():
            self.symbols[name] = info.copy()

        # Merge calls
        for caller, callees in result.calls.items():
            if caller not in self.calls:
                self.calls[caller] = set()
            self.calls[caller].update(callees)

        # Merge called_by
        for callee, callers in result.called_by.items():
            if callee not in self.called_by:
                self.called_by[callee] = set()
            self.called_by[callee].update(callers)

        # Merge imports
        if result.imports:
            self.imports[filepath] = result.imports


def analyze_project(root_dir: str) -> ProjectAnalyzer:
    """
    Walk root_dir recursively, analyze all files with registered extractors.

    Skips: .git, __pycache__, .venv, venv, node_modules, .mypy_cache
    Logs summary: files analyzed, functions found, symbols found.

    Args:
        root_dir: Absolute path to the workspace root for this task.

    Returns:
        Populated ProjectAnalyzer instance.
    """
    SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules", ".mypy_cache"}

    analyzer = ProjectAnalyzer()
    file_count = 0

    for dirpath, dirnames, filenames in os.walk(root_dir):
        # Prune skip dirs in-place so os.walk doesn't descend into them
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]

        for filename in filenames:
            filepath = os.path.join(dirpath, filename)
            # analyze_file() silently skips files with no registered extractor
            analyzer.analyze_file(filepath)
            file_count += 1

    logger.info(
        "Analyzed %d files. Found %d functions, %d symbols.",
        file_count, len(analyzer.functions), len(analyzer.symbols)
    )
    return analyzer
