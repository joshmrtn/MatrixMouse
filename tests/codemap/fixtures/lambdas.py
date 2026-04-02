# This file is a parse fixture, not executable Python.
# Imports are intentionally omitted. Do not add them.
"""Test fixture: lambda functions (should be ignored)."""


def regular_func():
    """A regular function."""
    callback = lambda x: x + 1
    return callback


class MyClass:
    """A class with lambdas."""

    def method_with_lambda(self):
        """Method containing a lambda."""
        handler = lambda event: event.type
        return handler
