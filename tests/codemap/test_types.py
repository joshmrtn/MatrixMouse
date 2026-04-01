"""
tests/codemap/test_types.py

Tests for the codemap._types module.

Covers:
    - ExtractionResult dataclass construction and field validation
    - LanguageExtractor ABC cannot be instantiated without implementing extract
    - LanguageExtractor.extensions is accessible as a class attribute
    - Concrete subclass can be instantiated
"""

import pytest
from typing import ClassVar

from matrixmouse.codemap._types import ExtractionResult, LanguageExtractor


class TestExtractionResult:
    """Tests for the ExtractionResult dataclass."""

    def test_constructs_with_empty_fields(self) -> None:
        """ExtractionResult can be constructed with all default empty fields."""
        result = ExtractionResult()

        assert result.functions == {}
        assert result.symbols == {}
        assert result.calls == {}
        assert result.called_by == {}
        assert result.imports == []

    def test_all_fields_present(self) -> None:
        """ExtractionResult can be constructed with all fields populated."""
        result = ExtractionResult(
            functions={"func": {"file": "test.py", "lineno": 1}},
            symbols={"Symbol": {"file": "test.py", "lineno": 1}},
            calls={"func": {"other"}},
            called_by={"other": {"func"}},
            imports=["import os"],
        )

        assert result.functions == {"func": {"file": "test.py", "lineno": 1}}
        assert result.symbols == {"Symbol": {"file": "test.py", "lineno": 1}}
        assert result.calls == {"func": {"other"}}
        assert result.called_by == {"other": {"func"}}
        assert result.imports == ["import os"]

    def test_none_fields_are_not_none(self) -> None:
        """No field is None when constructed with defaults."""
        result = ExtractionResult()

        assert result.functions is not None
        assert result.symbols is not None
        assert result.calls is not None
        assert result.called_by is not None
        assert result.imports is not None


class TestLanguageExtractor:
    """Tests for the LanguageExtractor abstract base class."""

    def test_cannot_instantiate_abc(self) -> None:
        """LanguageExtractor cannot be instantiated without implementing extract."""
        with pytest.raises(TypeError, match="abstract method"):
            LanguageExtractor()  # type: ignore[abstract]

    def test_extensions_is_classvar(self) -> None:
        """
        LanguageExtractor.extensions is accessible as a class attribute
        without instantiation.
        """
        # Define a concrete subclass
        class TestExtractor(LanguageExtractor):
            extensions: ClassVar[list[str]] = [".test"]

            def extract(self, filepath: str, source: str) -> ExtractionResult:
                return ExtractionResult()

        # Access without instantiation
        assert TestExtractor.extensions == [".test"]

    def test_concrete_subclass_can_be_instantiated(self) -> None:
        """A concrete subclass with extensions and extract() can be instantiated."""

        class ConcreteExtractor(LanguageExtractor):
            extensions: ClassVar[list[str]] = [".dummy"]

            def extract(self, filepath: str, source: str) -> ExtractionResult:
                return ExtractionResult()

        extractor = ConcreteExtractor()
        assert extractor is not None
        assert isinstance(extractor, LanguageExtractor)
