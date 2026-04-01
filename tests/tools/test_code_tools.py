"""
tests/tools/test_code_tools.py

Tests for matrixmouse.tools.code_tools.

Covers:
    - get_function_list with basename ambiguity returns warning
    - get_function_list with unambiguous basename returns results
    - get_imports with basename ambiguity returns warning
    - get_imports with unambiguous basename returns results
"""

from pathlib import Path

import pytest

from matrixmouse.tools import code_tools
from matrixmouse.codemap import ProjectAnalyzer


@pytest.fixture(autouse=True)
def reset_graph() -> None:
    """Reset the graph before and after each test."""
    code_tools._graph = None
    yield
    code_tools._graph = None


class TestGetFunctionListAmbiguity:
    """Tests for basename ambiguity in get_function_list."""

    def test_ambiguous_basename_returns_warning(self, tmp_path: Path) -> None:
        """get_function_list with two files sharing a basename returns warning."""
        # Create two directories with files sharing a basename
        dir1 = tmp_path / "backend"
        dir2 = tmp_path / "frontend"
        dir1.mkdir()
        dir2.mkdir()

        (dir1 / "user.py").write_text("def get_user(): pass\n")
        (dir2 / "user.py").write_text("function getUser() {}\n")  # Won't be analyzed but file exists

        graph = ProjectAnalyzer()
        graph.analyze_file(str(dir1 / "user.py"))
        # Add a second entry manually to simulate polyglot scenario
        graph.functions["getUser"] = {
            "file": str(dir2 / "user.py"),
            "lineno": 1,
            "end_lineno": 2,
            "docstring": None,
            "args": [],
            "symbol": None,
            "decorators": [],
        }

        code_tools.configure(graph)

        result = code_tools.get_function_list("user.py")

        assert "WARNING" in result
        assert "matched multiple files" in result
        assert "backend" in result or "frontend" in result

    def test_unambiguous_basename_returns_results(self, tmp_path: Path) -> None:
        """get_function_list with unambiguous basename returns results as before."""
        test_file = tmp_path / "unique_name.py"
        test_file.write_text("def my_func(): pass\n")

        graph = ProjectAnalyzer()
        graph.analyze_file(str(test_file))
        code_tools.configure(graph)

        result = code_tools.get_function_list("unique_name.py")

        assert "my_func" in result
        assert "WARNING" not in result

    def test_absolute_path_match_takes_precedence(self, tmp_path: Path) -> None:
        """get_function_list with absolute path match returns results immediately."""
        test_file = tmp_path / "test.py"
        test_file.write_text("def func1(): pass\n")

        # Add another file with same basename in different location
        other_dir = tmp_path / "other"
        other_dir.mkdir()
        (other_dir / "test.py").write_text("def func2(): pass\n")

        graph = ProjectAnalyzer()
        graph.analyze_file(str(test_file))
        graph.analyze_file(str(other_dir / "test.py"))
        code_tools.configure(graph)

        # Use absolute path - should match exactly
        result = code_tools.get_function_list(str(test_file))

        assert "func1" in result
        assert "func2" not in result
        assert "WARNING" not in result


class TestGetImportsAmbiguity:
    """Tests for basename ambiguity in get_imports."""

    def test_ambiguous_basename_returns_warning(self, tmp_path: Path) -> None:
        """get_imports with two files sharing a basename returns warning."""
        dir1 = tmp_path / "backend"
        dir2 = tmp_path / "frontend"
        dir1.mkdir()
        dir2.mkdir()

        file1 = dir1 / "config.py"
        file2 = dir2 / "config.py"
        file1.write_text("import os\n")
        file2.write_text("import sys\n")

        graph = ProjectAnalyzer()
        graph.analyze_file(str(file1))
        graph.analyze_file(str(file2))
        code_tools.configure(graph)

        result = code_tools.get_imports("config.py")

        assert "WARNING" in result
        assert "matched multiple files" in result

    def test_unambiguous_basename_returns_results(self, tmp_path: Path) -> None:
        """get_imports with unambiguous basename returns results as before."""
        test_file = tmp_path / "unique.py"
        test_file.write_text("import os\nimport sys\n")

        graph = ProjectAnalyzer()
        graph.analyze_file(str(test_file))
        code_tools.configure(graph)

        result = code_tools.get_imports("unique.py")

        assert "os" in result
        assert "sys" in result
        assert "WARNING" not in result

    def test_absolute_path_match_takes_precedence(self, tmp_path: Path) -> None:
        """get_imports with absolute path match returns results immediately."""
        test_file = tmp_path / "main.py"
        test_file.write_text("import json\n")

        other_dir = tmp_path / "other"
        other_dir.mkdir()
        (other_dir / "main.py").write_text("import re\n")

        graph = ProjectAnalyzer()
        graph.analyze_file(str(test_file))
        graph.analyze_file(str(other_dir / "main.py"))
        code_tools.configure(graph)

        result = code_tools.get_imports(str(test_file))

        assert "json" in result
        assert "re" not in result
        assert "WARNING" not in result
