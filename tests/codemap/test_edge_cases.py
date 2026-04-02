"""
tests/codemap/test_edge_cases.py

Extended edge case tests for PythonExtractor.

Covers:
    - Aliased imports (import x as y)
    - Relative imports (from . import x)
    - Wildcard imports (from x import *)
    - Call resolution (self.method(), obj.method())
    - Parameter variants (*args, **kwargs, typed defaults)
    - Async function calls
    - Deeply nested calls
    - Multiple decorators
    - Empty class bodies
"""

import pytest
from pathlib import Path

from matrixmouse.codemap.extractors.python import PythonExtractor


FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def extractor() -> PythonExtractor:
    """Return a fresh PythonExtractor instance."""
    return PythonExtractor()


def read_fixture(name: str) -> str:
    """Read a fixture file by name."""
    return (FIXTURES_DIR / name).read_text()


class TestAliasedImports:
    """Tests for aliased import handling."""

    def test_simple_aliased_import(self, extractor: PythonExtractor) -> None:
        """aliased_imports.py → 'import numpy as np' formats correctly."""
        source = read_fixture("aliased_imports.py")
        result = extractor.extract("/test/aliased_imports.py", source)

        assert "numpy as np" in result.imports
        assert "pandas as pd" in result.imports

    def test_aliased_from_import(self, extractor: PythonExtractor) -> None:
        """aliased_imports.py → 'from typing import Dict as D' formats correctly."""
        source = read_fixture("aliased_imports.py")
        result = extractor.extract("/test/aliased_imports.py", source)

        # Aliased imports in from statements preserve full alias format
        assert "from typing import Dict as D, List as L" in result.imports
        assert "from matrixmouse.task import Task as T" in result.imports
        # Collections import uses alias
        assert "from collections import OrderedDict as OD" in result.imports


class TestRelativeImports:
    """Tests for relative import handling."""

    def test_relative_import_dots_only(self, extractor: PythonExtractor) -> None:
        """relative_imports.py → 'from . import sibling' preserves dots."""
        source = read_fixture("relative_imports.py")
        result = extractor.extract("/test/relative_imports.py", source)

        assert "from . import sibling" in result.imports

    def test_relative_import_with_module(self, extractor: PythonExtractor) -> None:
        """relative_imports.py → 'from .sibling import func' works."""
        source = read_fixture("relative_imports.py")
        result = extractor.extract("/test/relative_imports.py", source)

        assert "from .sibling import func" in result.imports

    def test_relative_import_parent_dots(self, extractor: PythonExtractor) -> None:
        """relative_imports.py → 'from ..parent import something' preserves dots."""
        source = read_fixture("relative_imports.py")
        result = extractor.extract("/test/relative_imports.py", source)

        assert "from ..parent import something" in result.imports
        assert "from ...grandparent import other" in result.imports

    def test_relative_import_with_alias(self, extractor: PythonExtractor) -> None:
        """relative_imports.py → 'from ..module import name as alias' works."""
        source = read_fixture("relative_imports.py")
        result = extractor.extract("/test/relative_imports.py", source)

        # Aliased imports preserve full alias format
        assert "from ..module import name as alias" in result.imports


class TestWildcardImports:
    """Tests for wildcard import handling."""

    def test_wildcard_import(self, extractor: PythonExtractor) -> None:
        """wildcard_import.py → 'from module import *' formats correctly."""
        source = read_fixture("wildcard_import.py")
        result = extractor.extract("/test/wildcard_import.py", source)

        assert "from module import *" in result.imports
        assert "from typing import *" in result.imports


class TestCallResolution:
    """Tests for call resolution edge cases."""

    def test_self_method_call(self, extractor: PythonExtractor) -> None:
        """call_variants.py → 'self.method_b()' resolves to 'method_b'."""
        source = read_fixture("call_variants.py")
        result = extractor.extract("/test/call_variants.py", source)

        # C.method_a should call method_b (not "self")
        assert "C.method_a" in result.calls
        assert "method_b" in result.calls["C.method_a"]

    def test_object_method_call(self, extractor: PythonExtractor) -> None:
        """call_variants.py → 'obj.method()' resolves to 'method'."""
        source = read_fixture("call_variants.py")
        result = extractor.extract("/test/call_variants.py", source)

        # C.method_a should call method (not "obj")
        assert "method" in result.calls["C.method_a"]

    def test_module_function_call(self, extractor: PythonExtractor) -> None:
        """call_variants.py → 'module.func()' resolves to 'func'."""
        source = read_fixture("call_variants.py")
        result = extractor.extract("/test/call_variants.py", source)

        # C.method_a should call func
        assert "func" in result.calls["C.method_a"]

    def test_chained_attribute_call(self, extractor: PythonExtractor) -> None:
        """call_variants.py → 'a.b.c.d()' resolves to 'd' (rightmost)."""
        source = read_fixture("call_variants.py")
        result = extractor.extract("/test/call_variants.py", source)

        # C.method_a should call d (the rightmost identifier)
        assert "d" in result.calls["C.method_a"]

    def test_standalone_function_calls(self, extractor: PythonExtractor) -> None:
        """call_variants.py → standalone function calls resolve correctly."""
        source = read_fixture("call_variants.py")
        result = extractor.extract("/test/call_variants.py", source)

        # standalone should call helper
        assert "standalone" in result.calls
        assert "helper" in result.calls["standalone"]


class TestParameterVariants:
    """Tests for parameter extraction edge cases."""

    def test_positional_only_parameters(self, extractor: PythonExtractor) -> None:
        """parameter_variants.py → positional-only params extract identifiers."""
        source = read_fixture("parameter_variants.py")
        result = extractor.extract("/test/parameter_variants.py", source)

        func = result.functions.get("positional_only")
        assert func is not None
        # Should extract a, b, c (skip the / marker)
        assert "a" in func["args"]
        assert "b" in func["args"]
        assert "c" in func["args"]

    def test_varargs_parameters_skipped(self, extractor: PythonExtractor) -> None:
        """parameter_variants.py → *args is skipped."""
        source = read_fixture("parameter_variants.py")
        result = extractor.extract("/test/parameter_variants.py", source)

        func = result.functions.get("varargs")
        assert func is not None
        # *args should NOT be in args
        assert func["args"] == []

    def test_kwargs_parameters_skipped(self, extractor: PythonExtractor) -> None:
        """parameter_variants.py → **kwargs is skipped."""
        source = read_fixture("parameter_variants.py")
        result = extractor.extract("/test/parameter_variants.py", source)

        func = result.functions.get("kwargs")
        assert func is not None
        # **kwargs should NOT be in args
        assert func["args"] == []

    def test_typed_default_parameters(self, extractor: PythonExtractor) -> None:
        """parameter_variants.py → typed defaults extract identifiers."""
        source = read_fixture("parameter_variants.py")
        result = extractor.extract("/test/parameter_variants.py", source)

        func = result.functions.get("typed_default")
        assert func is not None
        # Should extract x and y
        assert "x" in func["args"]
        assert "y" in func["args"]

    def test_complex_parameter_mix(self, extractor: PythonExtractor) -> None:
        """parameter_variants.py → complex param mix extracts correctly."""
        source = read_fixture("parameter_variants.py")
        result = extractor.extract("/test/parameter_variants.py", source)

        func = result.functions.get("complex_params")
        assert func is not None
        # Should extract a and b (b is keyword-only arg after *args)
        # Skip *args and **kwargs
        assert "a" in func["args"]
        assert "b" in func["args"]  # keyword-only args ARE extracted
        assert "args" not in func["args"]
        assert "kwargs" not in func["args"]

    def test_all_parameter_variants(self, extractor: PythonExtractor) -> None:
        """parameter_variants.py → all parameter types in one function."""
        source = read_fixture("parameter_variants.py")
        result = extractor.extract("/test/parameter_variants.py", source)

        func = result.functions.get("all_variants")
        assert func is not None
        # Should extract a, b, c, d (skip /, *args, **kwargs markers)
        assert "a" in func["args"]
        assert "b" in func["args"]
        assert "c" in func["args"]
        assert "d" in func["args"]
        # Should NOT include args or kwargs
        assert "args" not in func["args"]
        assert "kwargs" not in func["args"]


class TestAsyncCalls:
    """Tests for call tracking in async functions."""

    def test_async_function_calls(self, extractor: PythonExtractor) -> None:
        """async_calls.py → calls from async functions are tracked."""
        source = read_fixture("async_calls.py")
        result = extractor.extract("/test/async_calls.py", source)

        # AsyncClient.get should call AsyncClient.fetch
        assert "AsyncClient.get" in result.calls
        assert "fetch" in result.calls["AsyncClient.get"]

        # AsyncClient.post should call AsyncClient.get and helper
        assert "AsyncClient.post" in result.calls
        assert "get" in result.calls["AsyncClient.post"]
        assert "helper" in result.calls["AsyncClient.post"]

        # Module-level async function should call helper
        assert "fetch_data" in result.calls
        assert "helper" in result.calls["fetch_data"]

    def test_async_method_symbol(self, extractor: PythonExtractor) -> None:
        """async_calls.py → async methods have correct symbol."""
        source = read_fixture("async_calls.py")
        result = extractor.extract("/test/async_calls.py", source)

        assert "AsyncClient.get" in result.functions
        func = result.functions["AsyncClient.get"]
        assert func["symbol"] == "AsyncClient"


class TestDeepCalls:
    """Tests for deeply nested call chains."""

    def test_deeply_nested_function_calls(self, extractor: PythonExtractor) -> None:
        """deep_calls.py → calls across 4 levels are tracked."""
        source = read_fixture("deep_calls.py")
        result = extractor.extract("/test/deep_calls.py", source)

        # level1 -> level2 -> level3 -> level4
        assert "level1" in result.calls
        assert "level2" in result.calls["level1"]
        assert "level2" in result.calls
        assert "level3" in result.calls["level2"]
        assert "level3" in result.calls
        assert "level4" in result.calls["level3"]

    def test_deeply_nested_method_calls(self, extractor: PythonExtractor) -> None:
        """deep_calls.py → calls across nested classes are tracked."""
        source = read_fixture("deep_calls.py")
        result = extractor.extract("/test/deep_calls.py", source)

        # Outer.method1 -> Outer.method2 -> Inner.inner_method -> Deep.deep_method
        assert "Outer.method1" in result.calls
        assert "method2" in result.calls["Outer.method1"]

        assert "Outer.method2" in result.calls
        assert "inner_method" in result.calls["Outer.method2"]

        assert "Inner.inner_method" in result.calls
        assert "deep_method" in result.calls["Inner.inner_method"]

        assert "Deep.deep_method" in result.calls
        assert "level1" in result.calls["Deep.deep_method"]


class TestRelativeImportAliases:
    """Tests for relative imports with aliases."""

    def test_relative_import_with_alias(self, extractor: PythonExtractor) -> None:
        """relative_import_aliases.py → relative imports with aliases format correctly."""
        source = read_fixture("relative_import_aliases.py")
        result = extractor.extract("/test/relative_import_aliases.py", source)

        assert "from . import sibling as sib" in result.imports
        assert "from .utils import helper as hlp" in result.imports
        assert "from ..parent import something as smth" in result.imports
        assert "from ...grandparent import other as othr" in result.imports
        assert "from ..module import name as alias_name" in result.imports

    def test_relative_import_multi_line_alias(self, extractor: PythonExtractor) -> None:
        """relative_import_aliases.py → multi-line relative imports with aliases."""
        source = read_fixture("relative_import_aliases.py")
        result = extractor.extract("/test/relative_import_aliases.py", source)

        # Multi-line import with aliases is captured as a single import string
        assert "from . import func1 as f1, func2 as f2" in result.imports
        # Check that aliases are captured
        assert "f1" in str(result.imports)
        assert "f2" in str(result.imports)


class TestMultipleDecorators:
    """Tests for functions/methods with multiple decorators."""

    def test_method_with_multiple_decorators(self, extractor: PythonExtractor) -> None:
        """multiple_decorators.py → methods with multiple decorators have all decorators."""
        source = read_fixture("multiple_decorators.py")
        result = extractor.extract("/test/multiple_decorators.py", source)

        # Method with many decorators
        assert "MyClass.method_many_decorators" in result.functions
        func = result.functions["MyClass.method_many_decorators"]
        assert "decorator1" in func["decorators"]
        assert "decorator2" in func["decorators"]
        assert 'decorator3("x")' in func["decorators"]

    def test_staticmethod_multiple_decorators(self, extractor: PythonExtractor) -> None:
        """multiple_decorators.py → staticmethod with multiple decorators."""
        source = read_fixture("multiple_decorators.py")
        result = extractor.extract("/test/multiple_decorators.py", source)

        assert "MyClass.static_multi" in result.functions
        func = result.functions["MyClass.static_multi"]
        assert "staticmethod" in func["decorators"]
        assert "decorator1" in func["decorators"]
        assert "decorator2" in func["decorators"]

    def test_property_multiple_decorators(self, extractor: PythonExtractor) -> None:
        """multiple_decorators.py → property with multiple decorators."""
        source = read_fixture("multiple_decorators.py")
        result = extractor.extract("/test/multiple_decorators.py", source)

        assert "MyClass.multi_decorated_prop" in result.functions
        func = result.functions["MyClass.multi_decorated_prop"]
        assert "property" in func["decorators"]
        assert "decorator1" in func["decorators"]

    def test_module_function_multiple_decorators(self, extractor: PythonExtractor) -> None:
        """multiple_decorators.py → module function with multiple decorators."""
        source = read_fixture("multiple_decorators.py")
        result = extractor.extract("/test/multiple_decorators.py", source)

        assert "module_func_multi" in result.functions
        func = result.functions["module_func_multi"]
        assert "decorator1" in func["decorators"]
        assert "decorator2" in func["decorators"]
        assert 'decorator3("y")' in func["decorators"]


class TestEmptyClass:
    """Tests for empty class bodies."""

    def test_empty_class_has_no_methods(self, extractor: PythonExtractor) -> None:
        """empty_class.py → class with only pass has empty methods list."""
        source = read_fixture("empty_class.py")
        result = extractor.extract("/test/empty_class.py", source)

        assert "EmptyClass" in result.symbols
        assert result.symbols["EmptyClass"]["methods"] == []

    def test_empty_class_with_docstring(self, extractor: PythonExtractor) -> None:
        """empty_class.py → class with docstring but no methods."""
        source = read_fixture("empty_class.py")
        result = extractor.extract("/test/empty_class.py", source)

        assert "EmptyWithDocstring" in result.symbols
        symbol = result.symbols["EmptyWithDocstring"]
        assert symbol["docstring"] == "A class with docstring but no methods."
        assert symbol["methods"] == []

    def test_nested_empty_class(self, extractor: PythonExtractor) -> None:
        """empty_class.py → nested class with only pass."""
        source = read_fixture("empty_class.py")
        result = extractor.extract("/test/empty_class.py", source)

        assert "NestedEmpty" in result.symbols
        assert "Inner" in result.symbols
        assert result.symbols["Inner"]["methods"] == []

        # Outer class should have one method
        assert "outer_method" in result.symbols["NestedEmpty"]["methods"]


class TestDecoratedFunctionCalls:
    """Tests for call tracking inside decorated functions."""

    def test_decorated_function_extracted(self, extractor: PythonExtractor) -> None:
        """multiple_decorators.py → decorated functions are extracted with correct symbol."""
        source = read_fixture("multiple_decorators.py")
        result = extractor.extract("/test/multiple_decorators.py", source)

        # Method with many decorators should be extracted with correct symbol
        assert "MyClass.method_many_decorators" in result.functions
        func = result.functions["MyClass.method_many_decorators"]
        assert func["symbol"] == "MyClass"
        assert func["decorators"] == ["decorator1", "decorator2", "decorator3(\"x\")"]


class TestChainedCalls:
    """Tests for chained call expressions."""

    def test_chained_call_expression(self, extractor: PythonExtractor) -> None:
        """call_variants.py → chained attribute calls resolve to rightmost identifier."""
        source = read_fixture("call_variants.py")
        result = extractor.extract("/test/call_variants.py", source)

        # a.b.c.d() should resolve to "d"
        assert "C.method_a" in result.calls
        assert "d" in result.calls["C.method_a"]


class TestGetExtensionEdgeCases:
    """Tests for _get_extension edge cases."""

    def test_compound_extension(self) -> None:
        """_get_extension handles compound extensions like .tar.gz."""
        from matrixmouse.codemap._registry import _get_extension

        # Should return only the final extension
        assert _get_extension("file.tar.gz") == ".gz"
        assert _get_extension("archive.tar.bz2") == ".bz2"

    def test_no_extension(self) -> None:
        """_get_extension returns empty string for files without extension."""
        from matrixmouse.codemap._registry import _get_extension

        assert _get_extension("Makefile") == ""
        assert _get_extension("README") == ""
        assert _get_extension("file") == ""

    def test_hidden_file(self) -> None:
        """_get_extension handles hidden files correctly."""
        from matrixmouse.codemap._registry import _get_extension

        assert _get_extension(".gitignore") == ""
        assert _get_extension(".env") == ""


class TestCallerQualification:
    """Tests for caller qualification in call tracking."""

    def test_method_caller_is_qualified(self, extractor: PythonExtractor) -> None:
        """call_variants.py → method callers are qualified with class name."""
        source = read_fixture("call_variants.py")
        result = extractor.extract("/test/call_variants.py", source)

        # C.method_a should be the qualified caller key
        assert "C.method_a" in result.calls
        assert "method_b" in result.calls["C.method_a"]
        assert "method" in result.calls["C.method_a"]
        assert "func" in result.calls["C.method_a"]
        assert "d" in result.calls["C.method_a"]

    def test_standalone_function_caller(self, extractor: PythonExtractor) -> None:
        """call_variants.py → standalone function callers are not qualified."""
        source = read_fixture("call_variants.py")
        result = extractor.extract("/test/call_variants.py", source)

        # standalone should be the caller key (not qualified)
        assert "standalone" in result.calls
        assert "method" in result.calls["standalone"]
        assert "helper" in result.calls["standalone"]
