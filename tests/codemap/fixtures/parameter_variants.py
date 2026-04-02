# This file is a parse fixture, not executable Python.
# Imports are intentionally omitted. Do not add them.
"""Test fixture: parameter extraction variants."""


def positional_only(a, b, /, c):
    """Function with positional-only parameters."""
    pass


def varargs(*args):
    """Function with *args."""
    pass


def kwargs(**kwargs):
    """Function with **kwargs."""
    pass


def typed_default(x: int = 5, y: str = "hello"):
    """Function with typed parameters with defaults."""
    pass


def complex_params(a: int, *args, b: str = "x", **kwargs):
    """Function with complex parameter mix."""
    pass


def all_variants(a, b=2, /, c: int = 3, *args, d: str = "d", **kwargs):
    """Function with all parameter types."""
    pass
