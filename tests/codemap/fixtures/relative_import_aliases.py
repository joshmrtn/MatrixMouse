# This file is a parse fixture, not executable Python.
# Imports are intentionally omitted. Do not add them.
"""Test fixture: relative imports with aliases."""

from . import sibling as sib
from .utils import helper as hlp
from ..parent import something as smth
from ...grandparent import other as othr
from ..module import name as alias_name
from . import (
    func1 as f1,
    func2 as f2,
)
