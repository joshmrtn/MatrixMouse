# This file is a parse fixture, not executable Python.
# Imports are intentionally omitted. Do not add them.
"""Test fixture: deeply nested classes (3+ levels)."""


class Level1:
    """First level."""

    class Level2:
        """Second level."""

        class Level3:
            """Third level."""

            class Level4:
                """Fourth level."""

                def deepest_method(self):
                    """Method in deepest class."""
                    pass

            def level3_method(self):
                """Method in level 3."""
                pass

        def level2_method(self):
            """Method in level 2."""
            pass

    def level1_method(self):
        """Method in level 1."""
        pass


def module_func():
    """Module-level function."""
    pass
