# This file is a parse fixture, not executable Python.
# Imports are intentionally omitted. Do not add them.
"""Test fixture: decorators on methods and classes."""


class MyView:
    """A view class."""

    @property
    def name(self):
        """A property."""
        return self._name

    @staticmethod
    def create():
        """A static method."""
        pass

    @classmethod
    def from_dict(cls, data):
        """A classmethod."""
        pass


def dataclass(cls):
    """Fake dataclass decorator for testing."""
    return cls


@dataclass
class Config:
    """A decorated class."""
    value: int = 0
