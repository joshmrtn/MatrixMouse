"""
matrixmouse/codemap/_types.py

Core type definitions for the codemap package.

Defines the data structures returned by language extractors and the
abstract base class that all language extractors must implement.

Zero heavy dependencies — only stdlib types and abc.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import ClassVar


@dataclass
class ExtractionResult:
    """
    All graph data extracted from a single source file.

    Returned by every LanguageExtractor.extract() call. All fields
    are populated — empty dicts/lists, never None.

    Attributes:
        functions: Dict of qualified_name -> function metadata.
                   Key is "ClassName.method_name" for methods,
                   bare "function_name" for module-level functions.
        symbols: Dict of name -> symbol metadata. Tracks classes,
                 structs, enums, traits, interfaces, etc.
        calls: Dict of caller_qualified_name -> set of callee names.
               Tracks which functions call which other functions.
        called_by: Dict of callee_name -> set of caller_qualified_names.
                   Reverse index of calls.
        imports: List of human-readable import strings for the file.
    """

    functions: dict[str, dict] = field(default_factory=dict)
    symbols: dict[str, dict] = field(default_factory=dict)
    calls: dict[str, set[str]] = field(default_factory=dict)
    called_by: dict[str, set[str]] = field(default_factory=dict)
    imports: list[str] = field(default_factory=list)


class LanguageExtractor(ABC):
    """
    Abstract base class for language-specific code extractors.

    A LanguageExtractor receives source text and returns an ExtractionResult.
    No I/O, no shared state, no side effects. All file I/O is owned by
    ProjectAnalyzer.

    Class Attributes:
        extensions: List of file extensions this extractor handles,
                    including the dot. e.g. [".py"] or [".js", ".ts"].
                    ClassVar so the registry can inspect without instantiation.

    Example implementation:
        class PythonExtractor(LanguageExtractor):
            extensions = [".py"]

            def extract(self, filepath: str, source: str) -> ExtractionResult:
                # Parse source and return ExtractionResult
                ...
    """

    extensions: ClassVar[list[str]]
    """File extensions this extractor handles, including the dot."""

    @abstractmethod
    def extract(self, filepath: str, source: str) -> ExtractionResult:
        """
        Parse source and return all extracted graph data for this file.

        Implementations MUST:
            - Never raise — catch all parse errors, return empty ExtractionResult
            - Never perform I/O — source is provided by the caller
            - Never mutate shared state — treat self as read-only after __init__
            - Return an ExtractionResult with all fields populated
              (empty dicts/lists, never None)

        Args:
            filepath: Absolute path to the file. Used for "file" metadata
                      fields only. The extractor must not open this path.
            source: Full source text of the file, already read by the caller.

        Returns:
            Populated ExtractionResult.
        """
        pass
