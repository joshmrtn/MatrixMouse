"""
tests/tools/test_file_tools.py

Tests for matrixmouse.tools.file_tools.

Covers:
    - configure() sets the graph
    - str_replace calls update_file after successful write
    - append_to_file calls update_file after successful write
    - If _graph is None, writes succeed without error
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from matrixmouse.tools import file_tools
from matrixmouse.codemap import ProjectAnalyzer
from matrixmouse.tools._safety import configure as safety_configure


@pytest.fixture(autouse=True)
def reset_graph() -> None:
    """Reset the graph before and after each test."""
    file_tools._graph = None
    yield
    file_tools._graph = None


@pytest.fixture(autouse=True)
def configure_safety(tmp_path: Path) -> None:
    """Configure path safety for all tests."""
    safety_configure(allowed_roots=[tmp_path], workspace_root=tmp_path)


class TestConfigure:
    """Tests for file_tools.configure()."""

    def test_configure_sets_graph(self, tmp_path: Path) -> None:
        """configure() sets the _graph attribute."""
        graph = ProjectAnalyzer()
        file_tools.configure(graph)

        assert file_tools._graph is graph

    def test_configure_with_none(self) -> None:
        """configure() can be called with None (though not recommended)."""
        file_tools.configure(None)  # type: ignore[arg-type]

        assert file_tools._graph is None


class TestStrReplaceUpdatesGraph:
    """Tests for str_replace calling update_file."""

    def test_str_replace_calls_update_file(self, tmp_path: Path) -> None:
        """After a successful str_replace, update_file is called."""
        test_file = tmp_path / "test.py"
        test_file.write_text("def old_func(): pass\n")

        graph = ProjectAnalyzer()
        graph.analyze_file(str(test_file))
        file_tools.configure(graph)

        # Mock update_file to track calls
        with patch.object(graph, "update_file", wraps=graph.update_file) as mock_update:
            result = file_tools.str_replace(str(test_file), "def old_func(): pass", "def new_func(): pass")

            assert "OK:" in result
            mock_update.assert_called_once()
            called_path = mock_update.call_args[0][0]
            assert Path(called_path).resolve() == test_file.resolve()

    def test_str_replace_no_graph_update(self, tmp_path: Path) -> None:
        """If _graph is None, str_replace still succeeds without error."""
        test_file = tmp_path / "test.py"
        test_file.write_text("def old_func(): pass\n")

        # Don't configure graph
        file_tools._graph = None

        result = file_tools.str_replace(str(test_file), "def old_func(): pass", "def new_func(): pass")

        assert "OK:" in result
        # Should not raise


class TestAppendToFileUpdatesGraph:
    """Tests for append_to_file calling update_file."""

    def test_append_to_file_calls_update_file(self, tmp_path: Path) -> None:
        """After a successful append_to_file, update_file is called."""
        test_file = tmp_path / "test.py"
        test_file.write_text("# Initial content\n")

        graph = ProjectAnalyzer()
        file_tools.configure(graph)

        with patch.object(graph, "update_file", wraps=graph.update_file) as mock_update:
            result = file_tools.append_to_file(str(test_file), "# Appended content\n")

            assert "OK:" in result
            mock_update.assert_called_once()
            called_path = mock_update.call_args[0][0]
            assert Path(called_path).resolve() == test_file.resolve()

    def test_append_to_file_no_graph_update(self, tmp_path: Path) -> None:
        """If _graph is None, append_to_file still succeeds without error."""
        test_file = tmp_path / "test.py"

        # Don't configure graph
        file_tools._graph = None

        result = file_tools.append_to_file(str(test_file), "# Appended content\n")

        assert "OK:" in result
        # Should not raise
