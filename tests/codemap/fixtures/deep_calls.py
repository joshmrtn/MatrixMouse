# This file is a parse fixture, not executable Python.
# Imports are intentionally omitted. Do not add them.
"""Test fixture: deeply nested function calls (3+ levels)."""


def level1():
    """Top level function."""
    level2()


def level2():
    """Second level."""
    level3()


def level3():
    """Third level."""
    level4()


def level4():
    """Fourth level."""
    pass


class Outer:
    """Outer class."""

    def method1(self):
        """Outer method 1."""
        self.method2()

    def method2(self):
        """Outer method 2."""
        Inner().inner_method()


class Inner:
    """Inner class."""

    def inner_method(self):
        """Inner method."""
        Deep().deep_method()


class Deep:
    """Deep class."""

    def deep_method(self):
        """Deep method."""
        level1()
