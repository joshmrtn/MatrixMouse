# This file is a parse fixture, not executable Python.
# Imports are intentionally omitted. Do not add them.
"""Test fixture: nested class definitions."""


class Outer:
    """Outer class."""

    class Inner:
        """Inner class."""

        def inner_method(self):
            """Method on inner class."""
            pass

    def outer_method(self):
        """Method on outer class."""
        pass
