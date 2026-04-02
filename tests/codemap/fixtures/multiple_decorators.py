# This file is a parse fixture, not executable Python.
# Imports are intentionally omitted. Do not add them.
"""Test fixture: multiple decorators on same function."""


def decorator1(func):
    """First decorator."""
    return func


def decorator2(func):
    """Second decorator."""
    return func


def decorator3(arg):
    """Decorator factory."""
    def wrapper(func):
        return func
    return wrapper


class MyClass:
    """A class with multiply-decorated methods."""

    @property
    @decorator1
    def multi_decorated_prop(self):
        """Property with multiple decorators."""
        return self._value

    @staticmethod
    @decorator1
    @decorator2
    def static_multi():
        """Static method with multiple decorators."""
        pass

    @classmethod
    @decorator3("arg")
    def classmethod_multi(cls):
        """Classmethod with multiple decorators."""
        pass

    @decorator1
    @decorator2
    @decorator3("x")
    def method_many_decorators(self):
        """Method with many decorators."""
        pass


@decorator1
@decorator2
@decorator3("y")
def module_func_multi():
    """Module function with multiple decorators."""
    pass
