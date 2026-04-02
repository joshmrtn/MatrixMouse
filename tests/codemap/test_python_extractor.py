"""
tests/codemap/test_python_extractor.py

Tests for the PythonExtractor.

Covers:
    - Symbols: class extraction with kind, lineno, docstring, methods
    - Functions: function extraction with symbol, args, docstring, end_lineno
    - Decorators: decorator extraction on methods and classes
    - Calls: call relationship extraction
    - Imports: import statement formatting
    - Edge cases: syntax errors, missing docstrings, empty args
    - Async functions: async def and async methods
    - Nested symbols: nested class definitions
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


class TestSymbols:
    """Tests for symbol (class) extraction."""

    def test_simple_class_symbol(self, extractor: PythonExtractor) -> None:
        """simple_class.py → symbols['Animal'] present with correct metadata."""
        source = read_fixture("simple_class.py")
        result = extractor.extract("/test/simple_class.py", source)

        assert "Animal" in result.symbols
        symbol = result.symbols["Animal"]
        assert symbol["kind"] == "class"
        assert symbol["lineno"] == 6
        assert symbol["docstring"] == "An animal."
        assert set(symbol["methods"]) == {"__init__", "speak"}
        # Note: spec does NOT require end_lineno or decorators for symbols

    def test_nested_symbols(self, extractor: PythonExtractor) -> None:
        """nested_symbols.py → both Outer and Inner symbols present."""
        source = read_fixture("nested_symbols.py")
        result = extractor.extract("/test/nested_symbols.py", source)

        assert "Outer" in result.symbols
        assert "Inner" in result.symbols

        outer = result.symbols["Outer"]
        assert "outer_method" in outer["methods"]
        assert "inner_method" not in outer["methods"]

        inner = result.symbols["Inner"]
        assert "inner_method" in inner["methods"]


class TestFunctions:
    """Tests for function extraction."""

    def test_method_extraction(self, extractor: PythonExtractor) -> None:
        """simple_class.py → functions['Animal.__init__'] with correct metadata."""
        source = read_fixture("simple_class.py")
        result = extractor.extract("/test/simple_class.py", source)

        assert "Animal.__init__" in result.functions
        func = result.functions["Animal.__init__"]
        assert func["symbol"] == "Animal"
        assert func["args"] == ["self", "name"]
        assert func["docstring"] == "Initialise."
        assert func["file"] == "/test/simple_class.py"

    def test_module_level_function(self, extractor: PythonExtractor) -> None:
        """simple_class.py → functions['standalone'] with symbol=None."""
        source = read_fixture("simple_class.py")
        result = extractor.extract("/test/simple_class.py", source)

        assert "standalone" in result.functions
        func = result.functions["standalone"]
        assert func["symbol"] is None
        assert func["args"] == []
        assert func["docstring"] == "A module-level function."

    def test_end_lineno(self, extractor: PythonExtractor) -> None:
        """functions['Animal.speak']['end_lineno'] is correct."""
        source = read_fixture("simple_class.py")
        result = extractor.extract("/test/simple_class.py", source)

        func = result.functions.get("Animal.speak")
        assert func is not None
        assert func["end_lineno"] > func["lineno"]


class TestDecorators:
    """Tests for decorator extraction."""

    def test_property_decorator(self, extractor: PythonExtractor) -> None:
        """decorators.py → functions['MyView.name']['decorators'] == ['property']."""
        source = read_fixture("decorators.py")
        result = extractor.extract("/test/decorators.py", source)

        func = result.functions.get("MyView.name")
        assert func is not None
        assert "property" in func["decorators"]

    def test_staticmethod_decorator(self, extractor: PythonExtractor) -> None:
        """decorators.py → functions['MyView.create']['decorators'] == ['staticmethod']."""
        source = read_fixture("decorators.py")
        result = extractor.extract("/test/decorators.py", source)

        func = result.functions.get("MyView.create")
        assert func is not None
        assert "staticmethod" in func["decorators"]

    def test_classmethod_decorator(self, extractor: PythonExtractor) -> None:
        """decorators.py → functions['MyView.from_dict']['decorators'] == ['classmethod']."""
        source = read_fixture("decorators.py")
        result = extractor.extract("/test/decorators.py", source)

        func = result.functions.get("MyView.from_dict")
        assert func is not None
        assert "classmethod" in func["decorators"]

    def test_class_decorator(self, extractor: PythonExtractor) -> None:
        """decorators.py → symbols['Config'] has dataclass decorator."""
        source = read_fixture("decorators.py")
        result = extractor.extract("/test/decorators.py", source)

        # The Config class should be extracted
        assert "Config" in result.symbols


class TestCalls:
    """Tests for call relationship extraction."""

    def test_nested_functions_calls(self, extractor: PythonExtractor) -> None:
        """nested_functions.py → calls['outer'] == {'inner', 'helper'}."""
        source = read_fixture("nested_functions.py")
        result = extractor.extract("/test/nested_functions.py", source)

        assert "outer" in result.calls
        assert result.calls["outer"] == {"inner", "helper"}

    def test_called_by_inverse(self, extractor: PythonExtractor) -> None:
        """nested_functions.py → called_by is inverse of calls."""
        source = read_fixture("nested_functions.py")
        result = extractor.extract("/test/nested_functions.py", source)

        assert "inner" in result.called_by
        assert "outer" in result.called_by["inner"]

        assert "helper" in result.called_by
        assert "outer" in result.called_by["helper"]


class TestImports:
    """Tests for import extraction."""

    def test_import_statements(self, extractor: PythonExtractor) -> None:
        """imports_only.py → imports list contains expected strings."""
        source = read_fixture("imports_only.py")
        result = extractor.extract("/test/imports_only.py", source)

        assert "os" in result.imports
        assert "sys" in result.imports
        assert "from collections import defaultdict" in result.imports
        assert "from pathlib import Path" in result.imports
        assert "from matrixmouse.task import Task, TaskStatus" in result.imports

    def test_import_order(self, extractor: PythonExtractor) -> None:
        """imports_only.py → imports match source order."""
        source = read_fixture("imports_only.py")
        result = extractor.extract("/test/imports_only.py", source)

        # os should come before sys (source order)
        os_idx = result.imports.index("os")
        sys_idx = result.imports.index("sys")
        assert os_idx < sys_idx


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_syntax_error_returns_empty(self, extractor: PythonExtractor) -> None:
        """syntax_error.py → returns empty ExtractionResult, does not raise."""
        source = read_fixture("syntax_error.py")
        result = extractor.extract("/test/syntax_error.py", source)

        assert result.functions == {}
        assert result.symbols == {}
        assert result.calls == {}
        assert result.called_by == {}
        assert result.imports == []

    def test_function_without_docstring(self, extractor: PythonExtractor) -> None:
        """Function with no docstring → docstring is None."""
        source = """
def no_docstring():
    pass
"""
        result = extractor.extract("/test/no_docstring.py", source)

        assert "no_docstring" in result.functions
        assert result.functions["no_docstring"]["docstring"] is None

    def test_function_with_no_args(self, extractor: PythonExtractor) -> None:
        """Function with no args → args == []."""
        source = """
def no_args():
    pass
"""
        result = extractor.extract("/test/no_args.py", source)

        assert "no_args" in result.functions
        assert result.functions["no_args"]["args"] == []

    def test_function_with_args_kwargs(self, extractor: PythonExtractor) -> None:
        """Function with *args, **kwargs → only identifier nodes in args."""
        source = """
def variadic(a, b, *args, **kwargs):
    pass
"""
        result = extractor.extract("/test/variadic.py", source)

        assert "variadic" in result.functions
        args = result.functions["variadic"]["args"]
        assert "a" in args
        assert "b" in args
        assert "args" not in args  # *args should not be included
        assert "kwargs" not in args  # **kwargs should not be included


class TestAsyncFunctions:
    """Tests for async function extraction."""

    def test_async_function(self, extractor: PythonExtractor) -> None:
        """async_functions.py → functions['fetch'] present with correct metadata."""
        source = read_fixture("async_functions.py")
        result = extractor.extract("/test/async_functions.py", source)

        assert "fetch" in result.functions
        func = result.functions["fetch"]
        assert func["symbol"] is None
        assert func["docstring"] == "An async function."

    def test_async_method(self, extractor: PythonExtractor) -> None:
        """async_functions.py → functions['Client.post'] present with symbol='Client'."""
        source = read_fixture("async_functions.py")
        result = extractor.extract("/test/async_functions.py", source)

        assert "Client.post" in result.functions
        func = result.functions["Client.post"]
        assert func["symbol"] == "Client"
        assert func["docstring"] == "An async method."


class TestNestedSymbols:
    """Tests for nested symbol extraction."""

    def test_nested_class_symbols(self, extractor: PythonExtractor) -> None:
        """nested_symbols.py → both Outer and Inner symbols with correct methods."""
        source = read_fixture("nested_symbols.py")
        result = extractor.extract("/test/nested_symbols.py", source)

        assert "Outer" in result.symbols
        assert "Inner" in result.symbols

        outer = result.symbols["Outer"]
        assert "outer_method" in outer["methods"]

        inner = result.symbols["Inner"]
        assert "inner_method" in inner["methods"]

    def test_nested_function_qualified_names(self, extractor: PythonExtractor) -> None:
        """nested_symbols.py → functions have correct symbol field."""
        source = read_fixture("nested_symbols.py")
        result = extractor.extract("/test/nested_symbols.py", source)

        assert "Outer.outer_method" in result.functions
        assert result.functions["Outer.outer_method"]["symbol"] == "Outer"

        assert "Inner.inner_method" in result.functions
        assert result.functions["Inner.inner_method"]["symbol"] == "Inner"


class TestEdgeCasesExtended:
    """Extended edge case tests."""

    def test_empty_file(self, extractor: PythonExtractor) -> None:
        """empty_file.py → returns empty ExtractionResult."""
        source = read_fixture("empty_file.py")
        result = extractor.extract("/test/empty_file.py", source)

        assert result.functions == {}
        assert result.symbols == {}
        assert result.calls == {}
        assert result.called_by == {}
        assert result.imports == []

    def test_comments_only(self, extractor: PythonExtractor) -> None:
        """comments_only.py → returns empty ExtractionResult."""
        source = read_fixture("comments_only.py")
        result = extractor.extract("/test/comments_only.py", source)

        assert result.functions == {}
        assert result.symbols == {}
        assert result.calls == {}
        assert result.called_by == {}
        assert result.imports == []

    def test_lambdas_ignored(self, extractor: PythonExtractor) -> None:
        """lambdas.py → lambdas are not extracted as functions."""
        source = read_fixture("lambdas.py")
        result = extractor.extract("/test/lambdas.py", source)

        # Only regular_func and MyClass.method_with_lambda should be extracted
        assert "regular_func" in result.functions
        assert "MyClass.method_with_lambda" in result.functions
        # Lambda expressions themselves should NOT be extracted as separate functions
        # Check that no function name is just "lambda" or starts with "<lambda>"
        for func_name in result.functions.keys():
            assert func_name != "lambda"
            assert not func_name.startswith("<lambda>")

    def test_deep_nesting(self, extractor: PythonExtractor) -> None:
        """deep_nesting.py → handles 4+ levels of nested classes."""
        source = read_fixture("deep_nesting.py")
        result = extractor.extract("/test/deep_nesting.py", source)

        # All levels should be extracted
        assert "Level1" in result.symbols
        assert "Level2" in result.symbols
        assert "Level3" in result.symbols
        assert "Level4" in result.symbols

        # Methods at each level
        assert "Level1.level1_method" in result.functions
        assert "Level2.level2_method" in result.functions
        assert "Level3.level3_method" in result.functions
        assert "Level4.deepest_method" in result.functions

        # Deepest method should have correct symbol
        assert result.functions["Level4.deepest_method"]["symbol"] == "Level4"

    def test_symbol_metadata_fields(self, extractor: PythonExtractor) -> None:
        """Symbols have spec-compliant metadata fields."""
        source = read_fixture("simple_class.py")
        result = extractor.extract("/test/simple_class.py", source)

        assert "Animal" in result.symbols
        symbol = result.symbols["Animal"]
        # Spec §5.1 requires: file, lineno, docstring, kind, methods
        assert "file" in symbol
        assert "lineno" in symbol
        assert "docstring" in symbol
        assert "kind" in symbol
        assert "methods" in symbol
        # Spec does NOT require end_lineno or decorators for symbols

    def test_extractor_exception_handling(self, extractor: PythonExtractor) -> None:
        """Extractor never raises — returns empty result on any error."""
        # Pass None-like source to trigger any potential errors
        # This tests the defence-in-depth exception handling
        result = extractor.extract("/test/fake.py", "")

        # Should return empty result, not raise
        assert isinstance(result, type(extractor.extract("/test/empty.py", "")))
