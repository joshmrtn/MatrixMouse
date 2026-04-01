"""
matrixmouse/codemap/__init__.py

Public API surface for the codemap package.

Exports:
    LanguageExtractor, ExtractionResult — from _types
    register_extractor, registered_extensions — from _registry
    ProjectAnalyzer, analyze_project — from _analyzer
"""

from matrixmouse.codemap._types import LanguageExtractor, ExtractionResult
from matrixmouse.codemap._registry import (
    register_extractor,
    registered_extensions,
)
from matrixmouse.codemap._analyzer import ProjectAnalyzer, analyze_project

__all__ = [
    "LanguageExtractor",
    "ExtractionResult",
    "register_extractor",
    "registered_extensions",
    "ProjectAnalyzer",
    "analyze_project",
]
