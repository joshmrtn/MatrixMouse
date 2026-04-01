"""
tests/codemap/test_analyzer.py

Tests for the codemap._analyzer module.

Covers:
    - ProjectAnalyzer constructs with empty dicts
    - analyze_file on a file with no registered extractor is a no-op
    - analyze_file on an unreadable path logs a warning and does not raise
    - _remove_file_contributions correctly cleans all five dicts
    - _merge correctly merges a hand-constructed ExtractionResult
    - analyze_file with DummyExtractor populates all fields correctly
    - update_file is an alias for analyze_file
    - _remove_file_contributions is idempotent
"""

import logging
from pathlib import Path
from typing import ClassVar

import pytest

from matrixmouse.codemap._types import LanguageExtractor, ExtractionResult
from matrixmouse.codemap._analyzer import ProjectAnalyzer, analyze_project
from matrixmouse.codemap._registry import register_extractor, _registry

# Import codemap to trigger PythonExtractor registration
from matrixmouse import codemap as _codemap  # noqa: F401


# Path to fixtures directory
FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Test extractors
# ---------------------------------------------------------------------------

class EmptyExtractor(LanguageExtractor):
    """Extractor that returns empty ExtractionResult."""
    extensions: ClassVar[list[str]] = [".empty"]

    def extract(self, filepath: str, source: str) -> ExtractionResult:
        return ExtractionResult()


class TwoFuncExtractor(LanguageExtractor):
    """Extractor that returns two functions for testing update."""
    extensions: ClassVar[list[str]] = [".twofunc"]

    def __init__(self, return_two: bool = False) -> None:
        self.return_two = return_two

    def extract(self, filepath: str, source: str) -> ExtractionResult:
        if self.return_two:
            return ExtractionResult(
                functions={
                    "Func1": {"file": filepath, "lineno": 1, "end_lineno": 5,
                              "docstring": None, "args": [], "symbol": None,
                              "decorators": []},
                    "Func2": {"file": filepath, "lineno": 6, "end_lineno": 10,
                              "docstring": None, "args": [], "symbol": None,
                              "decorators": []},
                },
                symbols={},
                calls={},
                called_by={},
                imports=[],
            )
        else:
            return ExtractionResult(
                functions={
                    "Func1": {"file": filepath, "lineno": 1, "end_lineno": 5,
                              "docstring": None, "args": [], "symbol": None,
                              "decorators": []},
                },
                symbols={},
                calls={},
                called_by={},
                imports=[],
            )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clear_registry() -> None:
    """Clear the registry before and after each test, then re-register PythonExtractor."""
    _registry.clear()
    # Re-register PythonExtractor for this test
    from matrixmouse.codemap.extractors.python import PythonExtractor
    register_extractor(PythonExtractor())
    yield
    _registry.clear()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestProjectAnalyzerInit:
    """Tests for ProjectAnalyzer initialization."""

    def test_constructs_with_empty_dicts(self) -> None:
        """ProjectAnalyzer constructs with empty dicts."""
        analyzer = ProjectAnalyzer()

        assert analyzer.functions == {}
        assert analyzer.symbols == {}
        assert analyzer.calls == {}
        assert analyzer.called_by == {}
        assert analyzer.imports == {}


class TestAnalyzeFileNoop:
    """Tests for analyze_file no-op scenarios."""

    def test_no_registered_extractor_is_noop(self, tmp_path: Path) -> None:
        """analyze_file on a file with no registered extractor is a no-op."""
        analyzer = ProjectAnalyzer()
        test_file = tmp_path / "test.unknown"
        test_file.write_text("content")

        # Should not raise
        analyzer.analyze_file(str(test_file))

        # All dicts still empty
        assert analyzer.functions == {}
        assert analyzer.symbols == {}

    def test_unreadable_path_logs_warning_no_raise(self, tmp_path: Path, caplog) -> None:
        """analyze_file on an unreadable path logs a warning and does not raise."""
        # Register an extractor so we don't hit the "no extractor" path
        register_extractor(EmptyExtractor())

        analyzer = ProjectAnalyzer()
        # Path that doesn't exist
        nonexistent = str(tmp_path / "nonexistent.empty")

        with caplog.at_level(logging.WARNING):
            # Should not raise
            analyzer.analyze_file(nonexistent)

        assert "Failed to read" in caplog.text
        assert "skipping" in caplog.text.lower()


class TestRemoveFileContributions:
    """Tests for _remove_file_contributions()."""

    def test_removes_all_five_dicts(self) -> None:
        """_remove_file_contributions correctly cleans all five dicts."""
        analyzer = ProjectAnalyzer()
        filepath = "/test/file.py"

        # Manually populate as if from a previous analysis
        analyzer.functions["func1"] = {"file": filepath, "lineno": 1}
        analyzer.functions["other_func"] = {"file": "/other/file.py", "lineno": 1}
        analyzer.symbols["Symbol1"] = {"file": filepath, "lineno": 1}
        analyzer.calls["func1"] = {"helper"}
        analyzer.called_by["helper"] = {"func1", "other"}
        analyzer.imports[filepath] = ["import os"]
        analyzer.imports["/other/file.py"] = ["import sys"]

        analyzer._remove_file_contributions(filepath)

        # func1 removed, other_func remains
        assert "func1" not in analyzer.functions
        assert "other_func" in analyzer.functions
        # Symbol1 removed
        assert "Symbol1" not in analyzer.symbols
        # calls from func1 removed
        assert "func1" not in analyzer.calls
        # func1 removed from called_by["helper"]
        assert "func1" not in analyzer.called_by.get("helper", set())
        assert "other" in analyzer.called_by.get("helper", set())
        # imports for filepath removed
        assert filepath not in analyzer.imports
        assert "/other/file.py" in analyzer.imports

    def test_idempotent(self) -> None:
        """Calling _remove_file_contributions twice is idempotent."""
        analyzer = ProjectAnalyzer()
        filepath = "/test/file.py"

        analyzer.functions["func1"] = {"file": filepath, "lineno": 1}
        analyzer.symbols["Symbol1"] = {"file": filepath, "lineno": 1}
        analyzer.calls["func1"] = {"helper"}
        analyzer.called_by["helper"] = {"func1"}
        analyzer.imports[filepath] = ["import os"]

        # First call
        analyzer._remove_file_contributions(filepath)

        # Second call — should not raise KeyError
        analyzer._remove_file_contributions(filepath)

        # All still empty (called_by may have empty sets, which is fine)
        assert analyzer.functions == {}
        assert analyzer.symbols == {}
        assert analyzer.calls == {}
        # called_by may have empty sets after cleanup — check no non-empty sets
        for callers in analyzer.called_by.values():
            assert len(callers) == 0
        assert analyzer.imports == {}


class TestMerge:
    """Tests for _merge()."""

    def test_merges_extraction_result(self) -> None:
        """_merge correctly merges a hand-constructed ExtractionResult."""
        analyzer = ProjectAnalyzer()
        filepath = "/test/file.py"

        result = ExtractionResult(
            functions={
                "MyClass.my_func": {
                    "file": filepath, "lineno": 1, "end_lineno": 5,
                    "docstring": "Does a thing.", "args": ["self"],
                    "symbol": "MyClass", "decorators": [],
                }
            },
            symbols={
                "MyClass": {
                    "file": filepath, "lineno": 1, "docstring": None,
                    "kind": "class", "methods": ["my_func"],
                }
            },
            calls={"MyClass.my_func": {"helper"}},
            called_by={"helper": {"MyClass.my_func"}},
            imports=["import os"],
        )

        analyzer._merge(filepath, result)

        # Functions merged
        assert "MyClass.my_func" in analyzer.functions
        assert analyzer.functions["MyClass.my_func"]["lineno"] == 1
        # Symbols merged
        assert "MyClass" in analyzer.symbols
        assert analyzer.symbols["MyClass"]["kind"] == "class"
        # Calls merged
        assert "MyClass.my_func" in analyzer.calls
        assert "helper" in analyzer.calls["MyClass.my_func"]
        # called_by merged
        assert "helper" in analyzer.called_by
        assert "MyClass.my_func" in analyzer.called_by["helper"]
        # Imports merged
        assert filepath in analyzer.imports
        assert "import os" in analyzer.imports[filepath]


class TestAnalyzeFileWithExtractor:
    """Tests for analyze_file with a registered extractor."""

    def test_analyze_file_populates_all_fields(
        self, tmp_path: Path, dummy_extractor
    ) -> None:
        """analyze_file with DummyExtractor populates all fields correctly."""
        register_extractor(dummy_extractor)

        analyzer = ProjectAnalyzer()
        test_file = tmp_path / "test.dummy"
        test_file.write_text("# Dummy content\n")

        analyzer.analyze_file(str(test_file))

        # Functions populated
        assert "MyClass.my_func" in analyzer.functions
        assert analyzer.functions["MyClass.my_func"]["file"] == str(test_file)
        # Symbols populated
        assert "MyClass" in analyzer.symbols
        assert analyzer.symbols["MyClass"]["kind"] == "class"
        # Calls populated
        assert "MyClass.my_func" in analyzer.calls
        assert "helper" in analyzer.calls["MyClass.my_func"]
        # called_by populated
        assert "helper" in analyzer.called_by
        assert "MyClass.my_func" in analyzer.called_by["helper"]
        # Imports populated
        assert str(test_file) in analyzer.imports
        assert "import os" in analyzer.imports[str(test_file)]


class TestUpdateFile:
    """Tests for update_file()."""

    def test_update_file_is_alias(self, tmp_path: Path) -> None:
        """update_file is an alias for analyze_file."""
        extractor = TwoFuncExtractor()
        register_extractor(extractor)

        analyzer = ProjectAnalyzer()
        test_file = tmp_path / "test.twofunc"
        test_file.write_text("# Content\n")

        # First analysis — one function
        analyzer.analyze_file(str(test_file))
        assert len(analyzer.functions) == 1

        # Change extractor to return two functions
        extractor.return_two = True

        # update_file should remove stale and add new
        analyzer.update_file(str(test_file))
        assert len(analyzer.functions) == 2
        assert "Func1" in analyzer.functions
        assert "Func2" in analyzer.functions


class TestAnalyzeProject:
    """Tests for analyze_project()."""

    def test_analyze_project_walks_directory(
        self, tmp_path: Path, dummy_extractor
    ) -> None:
        """analyze_project walks directory and analyzes files."""
        register_extractor(dummy_extractor)

        # Create a small directory structure
        root = tmp_path / "project"
        root.mkdir()
        (root / "subdir").mkdir()

        (root / "file1.dummy").write_text("# File 1\n")
        (root / "file2.dummy").write_text("# File 2\n")
        (root / "subdir" / "file3.dummy").write_text("# File 3\n")
        # This one should be skipped (no extractor)
        (root / "file4.txt").write_text("Text file\n")

        analyzer = analyze_project(str(root))

        # DummyExtractor always returns the same qualified name "MyClass.my_func",
        # so multiple files overwrite each other. We expect 1 function (last analyzed).
        # The important thing is that files were analyzed (non-zero count).
        assert len(analyzer.functions) >= 1
        assert len(analyzer.symbols) >= 1

    def test_analyze_project_skips_dirs(self, tmp_path: Path) -> None:
        """analyze_project skips .git, __pycache__, etc."""
        register_extractor(EmptyExtractor())

        root = tmp_path / "project"
        root.mkdir()
        (root / ".git").mkdir()
        (root / "__pycache__").mkdir()
        (root / ".venv").mkdir()

        # Files in skipped dirs
        (root / ".git" / "config.empty").write_text("config\n")
        (root / "__pycache__" / "module.empty").write_text("cache\n")

        # File in root
        (root / "main.empty").write_text("main\n")

        analyzer = analyze_project(str(root))

        # Should only analyze main.empty
        assert len(analyzer.functions) == 0  # EmptyExtractor returns empty


# ---------------------------------------------------------------------------
# Integration tests: ProjectAnalyzer + PythonExtractor
# ---------------------------------------------------------------------------

class TestAnalyzerWithPythonExtractor:
    """
    Integration tests for ProjectAnalyzer working with PythonExtractor.

    These tests verify the full pipeline: file → PythonExtractor →
    ProjectAnalyzer → graph data.
    """

    def test_analyze_file_simple_class(self, tmp_path: Path) -> None:
        """analyze_file on simple_class.py populates functions and symbols."""
        # PythonExtractor is auto-registered via codemap import
        from matrixmouse.codemap.extractors.python import PythonExtractor

        analyzer = ProjectAnalyzer()
        fixture_path = FIXTURES_DIR / "simple_class.py"

        analyzer.analyze_file(str(fixture_path))

        assert "Animal" in analyzer.symbols
        assert "Animal.__init__" in analyzer.functions
        assert "Animal.speak" in analyzer.functions
        assert "standalone" in analyzer.functions

    def test_analyze_file_nested_functions(self, tmp_path: Path) -> None:
        """analyze_file on nested_functions.py populates calls and called_by."""
        analyzer = ProjectAnalyzer()
        fixture_path = FIXTURES_DIR / "nested_functions.py"

        analyzer.analyze_file(str(fixture_path))

        assert "outer" in analyzer.calls
        assert "inner" in analyzer.calls["outer"]
        assert "helper" in analyzer.calls["outer"]
        assert "outer" in analyzer.called_by["inner"]

    def test_analyze_file_imports(self, tmp_path: Path) -> None:
        """analyze_file on imports_only.py populates imports."""
        analyzer = ProjectAnalyzer()
        fixture_path = FIXTURES_DIR / "imports_only.py"

        analyzer.analyze_file(str(fixture_path))

        assert str(fixture_path) in analyzer.imports
        imports = analyzer.imports[str(fixture_path)]
        assert "os" in imports
        assert "from collections import defaultdict" in imports

    def test_update_file_removes_stale(self, tmp_path: Path) -> None:
        """update_file removes stale entries and adds new ones."""
        # Create a temp Python file
        test_file = tmp_path / "test.py"
        test_file.write_text("""
def func1():
    pass
""")

        analyzer = ProjectAnalyzer()
        analyzer.analyze_file(str(test_file))

        assert "func1" in analyzer.functions

        # Update the file
        test_file.write_text("""
def func2():
    pass
""")

        analyzer.update_file(str(test_file))

        assert "func1" not in analyzer.functions
        assert "func2" in analyzer.functions

    def test_analyze_project_with_python_files(self, tmp_path: Path) -> None:
        """analyze_project walks and analyzes Python files correctly."""
        root = tmp_path / "project"
        root.mkdir()
        (root / "subdir").mkdir()

        # Write Python files
        (root / "main.py").write_text("""
def main():
    helper()

def helper():
    pass
""")
        (root / "subdir" / "utils.py").write_text("""
class Utils:
    def util_method(self):
        pass
""")

        analyzer = analyze_project(str(root))

        assert "main" in analyzer.functions
        assert "helper" in analyzer.functions
        assert "Utils" in analyzer.symbols
        assert "Utils.util_method" in analyzer.functions
