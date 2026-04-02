# This file is a parse fixture, not executable Python.
# Imports are intentionally omitted. Do not add them.
"""Test fixture: simple class with methods and docstrings."""


class Animal:
    """An animal."""

    def __init__(self, name: str) -> None:
        """Initialise."""
        self.name = name

    def speak(self) -> str:
        """Return the animal's sound."""
        return "..."


def standalone() -> None:
    """A module-level function."""
    pass
