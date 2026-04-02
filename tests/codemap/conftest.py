"""
tests/codemap/conftest.py

Pytest fixtures for codemap tests.

Provides:
    DummyExtractor — a test extractor for .dummy files that returns
                     a fixed, non-empty ExtractionResult.
"""

import pytest
from pathlib import Path

from matrixmouse.codemap._types import LanguageExtractor, ExtractionResult


class DummyExtractor(LanguageExtractor):
    """
    A test extractor for .dummy files.

    Returns a fixed, non-empty ExtractionResult to exercise the full
    analyze_file → _remove_file_contributions → _merge pipeline.
    """

    extensions = [".dummy"]

    def extract(self, filepath: str, source: str) -> ExtractionResult:
        """
        Return a fixed ExtractionResult with concrete data.

        The filepath is used in the "file" metadata fields so tests
        can verify the analyzer correctly tracks file origins.
        """
        return ExtractionResult(
            functions={
                "MyClass.my_func": {
                    "file": filepath,
                    "lineno": 1,
                    "end_lineno": 5,
                    "docstring": "Does a thing.",
                    "args": ["self"],
                    "symbol": "MyClass",
                    "decorators": [],
                }
            },
            symbols={
                "MyClass": {
                    "file": filepath,
                    "lineno": 1,
                    "docstring": None,
                    "kind": "class",
                    "methods": ["my_func"],
                }
            },
            calls={"MyClass.my_func": {"helper"}},
            called_by={"helper": {"MyClass.my_func"}},
            imports=["import os"],
        )


@pytest.fixture
def dummy_extractor() -> DummyExtractor:
    """Return a fresh DummyExtractor instance."""
    return DummyExtractor()


@pytest.fixture
def temp_dummy_file(tmp_path: Path) -> Path:
    """
    Create a temporary .dummy file for testing.

    Returns:
        Path to the temporary file.
    """
    dummy_file = tmp_path / "test.dummy"
    dummy_file.write_text("# Dummy file content\n")
    return dummy_file
