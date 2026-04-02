# This file is a parse fixture, not executable Python.
# Imports are intentionally omitted. Do not add them.
"""Test fixture: class body with only pass."""


class EmptyClass:
    """A class with only pass."""
    pass


class EmptyWithDocstring:
    """A class with docstring but no methods."""
    pass


class NestedEmpty:
    """Outer class with empty inner class."""

    class Inner:
        """Inner class with only pass."""
        pass

    def outer_method(self):
        """Outer method."""
        pass
