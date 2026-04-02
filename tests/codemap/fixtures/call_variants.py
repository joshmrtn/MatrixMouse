# This file is a parse fixture, not executable Python.
# Imports are intentionally omitted. Do not add them.
"""Test fixture: call resolution variants."""


class C:
    """A class with various call patterns."""

    def method_a(self):
        """Calls various methods."""
        self.method_b()
        obj.method()
        module.func()
        a.b.c.d()

    def method_b(self):
        """Another method."""
        pass


def standalone():
    """Standalone function with calls."""
    helper()
    self.method()
    obj.attr.method()
