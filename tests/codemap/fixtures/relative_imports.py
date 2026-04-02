# This file is a parse fixture, not executable Python.
# Imports are intentionally omitted. Do not add them.
"""Test fixture: relative imports."""

from . import sibling
from .sibling import func
from ..parent import something
from ...grandparent import other
from ..module import name as alias
