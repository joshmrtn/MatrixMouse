"""
matrixmouse/graph.py

Builds and maintains a static call graph of the project using Python's
ast module. Rebuilt at startup and updated incrementally after each
file write (per-file update, not full rebuild).

Provides data for code inspection tools.

Responsible for tracking:
    - Function and method definitions (name, file, line number, docstring, args)
    - Class definitions (name, file, methods, docstring)
    - Call relationships (what each function calls; what calls each function)
    - Import relationships per file

Limitations: static analysis only. Dynamic dispatch, `getattr`, and
heavily decorated code may be incomplete or invisible to the analyzer.

Do not add tool definitions here. This module is pure analysis.
Tool wrappers that expose this data to the agent live in tools/code_tools.py.
"""

import ast
import logging
import os
from collections import defaultdict
from pathlib import Path

logger = logging.getLogger(__name__)


class ProjectAnalyzer(ast.NodeVisitor):
    """
    Walks a Python project's AST and builds a static call graph.

    Usage:
        analyzer = ProjectAnalyzer()
        analyzer.analyze_file("path/to/file.py")
        # or use the module-level helper:
        analyzer = analyze_project("/path/to/project")

    After analysis, query via:
        analyzer.functions     — dict of qualified_name -> metadata
        analyzer.classes       — dict of class_name -> metadata
        analyzer.calls         — dict of func -> set of funcs it calls
        analyzer.called_by     — dict of func -> set of funcs that call it
        analyzer.imports       — dict of filepath -> list of import strings
    """

    def __init__(self):
        self.functions: dict = {}
        self.classes: dict = {}
        self.calls: dict = defaultdict(set)
        self.called_by: dict = defaultdict(set)
        self.imports: dict = defaultdict(list)

        # Internal state during AST traversal
        self._current_file: str = ""
        self._current_class: str | None = None
        self._current_function: str | None = None

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def analyze_file(self, filepath: str) -> None:
        """
        Parse a single Python file and merge its data into the graph.
        Safe to call multiple times on the same file — removes stale
        entries before re-adding updated ones.
        """
        self._remove_file_contributions(filepath)
        self._current_file = filepath

        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                source = f.read()
            tree = ast.parse(source, filename=filepath)
            self.visit(tree)
        except SyntaxError as e:
            logger.debug("Skipping %s — syntax error: %s", filepath, e)
        except Exception as e:
            logger.warning("Failed to analyze %s: %s", filepath, e)

    def update_file(self, filepath: str) -> None:
        """
        Re-analyze a single file after it has been modified.
        More efficient than rebuilding the full graph.
        """
        logger.debug("Updating graph for %s", filepath)
        self.analyze_file(filepath)

    # ------------------------------------------------------------------
    # AST visitor methods
    # ------------------------------------------------------------------

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        prev_class = self._current_class
        self._current_class = node.name

        self.classes[node.name] = {
            "file": self._current_file,
            "lineno": node.lineno,
            "docstring": ast.get_docstring(node),
            "methods": [],
        }

        self.generic_visit(node)
        self._current_class = prev_class

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        prev_function = self._current_function
        self._current_function = node.name

        qualified = self._qualified_name(node.name)
        self.functions[qualified] = {
            "file": self._current_file,
            "lineno": node.lineno,
            "end_lineno": node.end_lineno,
            "docstring": ast.get_docstring(node),
            "args": [arg.arg for arg in node.args.args],
            "class": self._current_class,
        }

        if self._current_class and node.name not in \
                self.classes.get(self._current_class, {}).get("methods", []):
            self.classes.setdefault(self._current_class, {"methods": []})
            self.classes[self._current_class]["methods"].append(node.name)

        self.generic_visit(node)
        self._current_function = prev_function

    # Async functions are treated identically to sync ones
    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Call(self, node: ast.Call) -> None:
        if self._current_function:
            caller = self._qualified_name(self._current_function)
            callee = self._resolve_callee(node.func)
            if callee:
                self.calls[caller].add(callee)
                self.called_by[callee].add(caller)
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.imports[self._current_file].append(alias.name)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module:
            names = ", ".join(a.name for a in node.names)
            self.imports[self._current_file].append(
                f"from {node.module} import {names}"
            )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _qualified_name(self, func_name: str) -> str:
        """Return ClassName.method_name or just func_name."""
        if self._current_class:
            return f"{self._current_class}.{func_name}"
        return func_name

    def _resolve_callee(self, func_node) -> str | None:
        """Extract the callee name from a Call node's func attribute."""
        if isinstance(func_node, ast.Name):
            return func_node.id
        if isinstance(func_node, ast.Attribute):
            return func_node.attr
        return None

    def _remove_file_contributions(self, filepath: str) -> None:
        """Remove all graph entries that originated from a given file."""
        # Remove functions from this file
        stale_funcs = [
            name for name, info in self.functions.items()
            if info.get("file") == filepath
        ]
        for name in stale_funcs:
            self.functions.pop(name, None)
            self.calls.pop(name, None)
            for callers in self.called_by.values():
                callers.discard(name)

        # Remove classes from this file
        stale_classes = [
            name for name, info in self.classes.items()
            if info.get("file") == filepath
        ]
        for name in stale_classes:
            self.classes.pop(name, None)

        # Remove imports from this file
        self.imports.pop(filepath, None)


# ---------------------------------------------------------------------------
# Module-level helper
# ---------------------------------------------------------------------------

def analyze_project(root_dir: str) -> ProjectAnalyzer:
    """
    Walk a directory recursively and analyze all Python files.

    Skips common non-source directories (.git, __pycache__, .venv, etc).
    Returns a populated ProjectAnalyzer ready for queries.

    Args:
        root_dir: Absolute path to the project root.

    Returns:
        A ProjectAnalyzer with the full project graph built.
    """
    SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules", ".mypy_cache"}

    analyzer = ProjectAnalyzer()
    file_count = 0

    for dirpath, dirnames, filenames in os.walk(root_dir):
        # Prune skip dirs in-place so os.walk doesn't descend into them
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]

        for filename in filenames:
            if filename.endswith(".py"):
                filepath = os.path.join(dirpath, filename)
                analyzer.analyze_file(filepath)
                file_count += 1

    logger.info(
        "Analyzed %d files. Found %d functions, %d classes.",
        file_count, len(analyzer.functions), len(analyzer.classes)
    )
    return analyzer
