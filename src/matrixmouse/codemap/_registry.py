"""
matrixmouse/codemap/_registry.py

Extractor registry for the codemap package.

Module-level, process-wide registry. One registry per process, shared
across all ProjectAnalyzer instances. Safe because extractor instances
are stateless.

Functions:
    register_extractor: Register a LanguageExtractor for its extensions.
    get_extractor: Look up extractor by file extension.
    registered_extensions: Return sorted list of registered extensions.
"""

from __future__ import annotations

from matrixmouse.codemap._types import LanguageExtractor


_registry: dict[str, LanguageExtractor] = {}
"""Maps file extension (including dot) to extractor instance."""


def register_extractor(extractor: LanguageExtractor) -> None:
    """
    Register a language extractor for its declared extensions.

    Raises ValueError if any of the extractor's extensions is already
    registered by a different extractor instance. Re-registering the
    same instance is a no-op (safe for module reimport scenarios).

    Called at module import time for built-in extractors.
    Called at plugin load time for third-party extractors.

    Args:
        extractor: The LanguageExtractor instance to register.

    Raises:
        ValueError: If an extension is already claimed by a different
                    extractor instance.
    """
    for ext in extractor.extensions:
        existing = _registry.get(ext)
        if existing is not None and existing is not extractor:
            raise ValueError(
                f"Extension '{ext}' is already registered by "
                f"{type(existing).__name__}. "
                f"Cannot register {type(extractor).__name__}."
            )
        _registry[ext] = extractor


def get_extractor(filepath: str) -> LanguageExtractor | None:
    """
    Return the registered extractor for filepath's extension, or None.

    Lookup is by file extension only — no content sniffing.

    Args:
        filepath: Absolute path to the file.

    Returns:
        The registered LanguageExtractor, or None if no extractor
        is registered for this extension.
    """
    ext = _get_extension(filepath)
    return _registry.get(ext)


def registered_extensions() -> list[str]:
    """
    Return sorted list of all currently registered extensions.

    Returns:
        Sorted list of extension strings (e.g. [".js", ".py", ".ts"]).
    """
    return sorted(_registry.keys())


def _get_extension(filepath: str) -> str:
    """
    Extract the file extension from a filepath, including the dot.

    Handles compound extensions like .tar.gz by returning only the
    final extension.

    Args:
        filepath: The file path string.

    Returns:
        The extension including the dot, or empty string if none.
    """
    from pathlib import Path
    return Path(filepath).suffix
