"""
matrixmouse/codemap/__init__.py

Public API surface for the codemap package.

Exports:
    LanguageExtractor, ExtractionResult — from _types
    register_extractor, get_extractor, registered_extensions — from _registry
    ProjectAnalyzer, analyze_project — from _analyzer

Note: Importing this module triggers registration of the PythonExtractor
for .py files.
"""

from matrixmouse.codemap._types import LanguageExtractor, ExtractionResult
from matrixmouse.codemap._registry import (
    register_extractor,
    get_extractor,
    registered_extensions,
)
from matrixmouse.codemap._analyzer import ProjectAnalyzer, analyze_project

# Import PythonExtractor to trigger registration at module import time
from matrixmouse.codemap.extractors import python as _python_extractor  # noqa: F401

__all__ = [
    "LanguageExtractor",
    "ExtractionResult",
    "register_extractor",
    "get_extractor",
    "registered_extensions",
    "ProjectAnalyzer",
    "analyze_project",
]
