"""
tests/codemap/test_registry.py

Tests for the codemap._registry module.

Covers:
    - Register an extractor with two extensions; look up both
    - Unknown extension returns None
    - Registering a second extractor with overlapping extension raises ValueError
    - Re-registering the same instance is a no-op
    - registered_extensions() returns sorted list
"""

import pytest
from typing import ClassVar

from matrixmouse.codemap._types import LanguageExtractor, ExtractionResult
from matrixmouse.codemap._registry import (
    _registry,
    register_extractor,
    get_extractor,
    registered_extensions,
)


class ExtractorA(LanguageExtractor):
    """Test extractor A for .a and .b files."""
    extensions: ClassVar[list[str]] = [".a", ".b"]

    def extract(self, filepath: str, source: str) -> ExtractionResult:
        return ExtractionResult()


class ExtractorB(LanguageExtractor):
    """Test extractor B for .c files."""
    extensions: ClassVar[list[str]] = [".c"]

    def extract(self, filepath: str, source: str) -> ExtractionResult:
        return ExtractionResult()


class ExtractorC(LanguageExtractor):
    """Test extractor C for .a files — conflicts with ExtractorA."""
    extensions: ClassVar[list[str]] = [".a"]

    def extract(self, filepath: str, source: str) -> ExtractionResult:
        return ExtractionResult()


@pytest.fixture(autouse=True)
def clear_registry() -> None:
    """Clear the registry before and after each test."""
    _registry.clear()
    yield
    _registry.clear()


class TestRegisterExtractor:
    """Tests for register_extractor()."""

    def test_register_extractor_with_two_extensions(self) -> None:
        """Register an extractor with two extensions; look up both."""
        extractor_a = ExtractorA()
        register_extractor(extractor_a)

        # Look up both extensions
        result_a = get_extractor("test.a")
        result_b = get_extractor("test.b")

        assert result_a is extractor_a
        assert result_b is extractor_a

    def test_unknown_extension_returns_none(self) -> None:
        """Unknown extension returns None."""
        # No extractors registered
        result = get_extractor("test.unknown")
        assert result is None

    def test_registering_second_extractor_overlapping_extension_raises(
        self,
    ) -> None:
        """Registering a second extractor with an overlapping extension raises ValueError."""
        extractor_a = ExtractorA()
        extractor_c = ExtractorC()

        register_extractor(extractor_a)

        with pytest.raises(ValueError, match=r"Extension '\.a' is already registered"):
            register_extractor(extractor_c)

    def test_re_registering_same_instance_is_noop(self) -> None:
        """Re-registering the same instance is a no-op."""
        extractor_a = ExtractorA()

        register_extractor(extractor_a)
        # Should not raise
        register_extractor(extractor_a)

        # Verify still registered correctly
        assert get_extractor("test.a") is extractor_a
        assert get_extractor("test.b") is extractor_a


class TestGetExtractor:
    """Tests for get_extractor()."""

    def test_lookup_by_extension(self) -> None:
        """Lookup is by file extension only."""
        extractor_b = ExtractorB()
        register_extractor(extractor_b)

        # Different filenames, same extension
        assert get_extractor("/path/to/file.c") is extractor_b
        assert get_extractor("/other/path/test.c") is extractor_b

    def test_case_sensitive_extension(self) -> None:
        """Extension lookup is case-sensitive."""
        extractor_b = ExtractorB()
        register_extractor(extractor_b)

        assert get_extractor("test.c") is extractor_b
        assert get_extractor("test.C") is None


class TestRegisteredExtensions:
    """Tests for registered_extensions()."""

    def test_returns_sorted_list(self) -> None:
        """registered_extensions() returns sorted list."""
        extractor_a = ExtractorA()
        extractor_b = ExtractorB()

        register_extractor(extractor_a)
        register_extractor(extractor_b)

        result = registered_extensions()

        assert result == [".a", ".b", ".c"]
        # Verify sorted
        assert result == sorted(result)

    def test_returns_empty_when_no_extractors(self) -> None:
        """Returns empty list when no extractors registered."""
        # Registry cleared by autouse fixture
        result = registered_extensions()
        assert result == []
