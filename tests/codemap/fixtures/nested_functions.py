# This file is a parse fixture, not executable Python.
# Imports are intentionally omitted. Do not add them.
"""Test fixture: nested functions with call relationships."""


def outer():
    """Calls inner."""
    inner()
    helper()


def inner():
    """Called by outer."""
    pass


def helper():
    """Also called by outer."""
    pass
