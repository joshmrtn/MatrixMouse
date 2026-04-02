"""
matrixmouse/codemap/extractors/python.py

Python language extractor using tree-sitter-python.

Extracts functions, symbols, calls, and imports from Python source files.
Uses a cursor walk to traverse the AST, with targeted queries for sub-node
extraction.

Registration:
    Importing this module triggers automatic registration of PythonExtractor
    for .py files via register_extractor() at module bottom.
"""

from __future__ import annotations

from typing import ClassVar

import tree_sitter_python
from tree_sitter import Language, Parser, TreeCursor

from matrixmouse.codemap._types import LanguageExtractor, ExtractionResult
from matrixmouse.codemap._registry import register_extractor


class PythonExtractor(LanguageExtractor):
    """
    Extracts code graph data from Python source files.

    Uses tree-sitter-python grammar with a cursor-based walk to traverse
    the AST. Extracts functions, symbols, calls, called_by, and imports.

    Class Attributes:
        extensions: [".py"] — handles Python files only.
    """

    extensions: ClassVar[list[str]] = [".py"]

    def __init__(self) -> None:
        """
        Initialize the PythonExtractor with a cached parser.

        The parser is created once and reused for all extract() calls.
        Thread-safe because extract() does not mutate shared state.
        """
        self._language = Language(tree_sitter_python.language())
        self._parser = Parser(self._language)

    def extract(self, filepath: str, source: str) -> ExtractionResult:
        """
        Parse Python source and return all extracted graph data.

        Args:
            filepath: Absolute path to the file (for metadata only).
            source: Full source text of the file.

        Returns:
            ExtractionResult with functions, symbols, calls, called_by, imports.
            Returns empty ExtractionResult on parse error (never raises).
        """
        try:
            tree = self._parser.parse(bytes(source, "utf-8"))
        except Exception:
            return ExtractionResult()

        if tree.root_node is None or tree.root_node.is_error:
            return ExtractionResult()

        # Check for any ERROR nodes in the tree
        if self._has_error_nodes(tree.root_node):
            return ExtractionResult()

        result = ExtractionResult()

        # Walk the AST using TreeCursor with explicit nesting stacks
        self._walk(tree.root_node, filepath, result)

        return result

    def _has_error_nodes(self, node) -> bool:
        """
        Check if the tree contains any ERROR nodes.

        Uses iterative DFS to avoid stack overflow on deeply nested ASTs.

        Args:
            node: Root node to check.

        Returns:
            True if any ERROR nodes found, False otherwise.
        """
        stack = [node]
        while stack:
            current = stack.pop()
            if current.is_error or current.type == "ERROR":
                return True
            stack.extend(current.children)
        return False

    def _walk(
        self,
        root_node,
        filepath: str,
        result: ExtractionResult,
    ) -> None:
        """
        Walk the AST using TreeCursor, maintaining nesting state.

        Uses the Tree-sitter cursor API to traverse the AST in document order,
        maintaining explicit stacks for current_symbol and current_function as
        it descends and ascends.

        Args:
            root_node: Root tree-sitter node to start traversal from.
            filepath: File path for metadata.
            result: ExtractionResult being populated.
        """
        cursor = root_node.walk()

        # Explicit stacks for tracking nesting context
        # Start with (None, None) for module-level
        symbol_stack: list[str | None] = [None]
        function_stack: list[str | None] = [None]

        # Standard TreeCursor iterative traversal
        while True:
            node_type = cursor.node.type

            # Push context when we encounter a class/function definition (before processing)
            if node_type == "class_definition":
                class_name = self._get_identifier(cursor.node)
                if class_name:
                    symbol_stack.append(class_name)
                    function_stack.append(None)
            elif node_type == "decorated_definition":
                # Peek at child to determine what's being decorated
                if cursor.goto_first_child():
                    child_type = cursor.node.type
                    cursor.goto_parent()
                    if child_type == "class_definition":
                        class_name = self._get_identifier(cursor.node)
                        if class_name:
                            symbol_stack.append(class_name)
                            function_stack.append(None)
                    elif child_type in ("function_definition", "async_function_definition"):
                        func_name = self._get_identifier(cursor.node)
                        if func_name:
                            current_symbol = symbol_stack[-1]
                            qualified = self._qualified_name(func_name, current_symbol)
                            symbol_stack.append(current_symbol)
                            function_stack.append(qualified)
            elif node_type in ("function_definition", "async_function_definition"):
                func_name = self._get_identifier(cursor.node)
                if func_name:
                    qualified = self._qualified_name(func_name, symbol_stack[-1])
                    symbol_stack.append(symbol_stack[-1])
                    function_stack.append(qualified)

            # Process current node with current context
            current_symbol = symbol_stack[-1]
            current_function = function_stack[-1]
            children_processed = self._process_node_at_cursor(
                cursor, filepath, result, current_symbol, current_function
            )

            # Skip descending if children were already processed (e.g., decorated_definition)
            if children_processed:
                # Move to next sibling or ascend
                while not cursor.goto_next_sibling():
                    if not cursor.goto_parent():
                        return
                    # Pop context when leaving class/function/async_function definitions
                    node_type = cursor.node.type
                    if node_type in ("class_definition", "function_definition", "async_function_definition"):
                        if len(symbol_stack) > 1:
                            symbol_stack.pop()
                        if len(function_stack) > 1:
                            function_stack.pop()
                    # Also pop for decorated_definition that contained class/function
                    elif node_type == "decorated_definition":
                        if cursor.goto_first_child():
                            child_type = cursor.node.type
                            cursor.goto_parent()
                            if child_type in ("class_definition", "function_definition", "async_function_definition"):
                                if len(symbol_stack) > 1:
                                    symbol_stack.pop()
                                if len(function_stack) > 1:
                                    function_stack.pop()
                continue

            # Descend into children
            if cursor.goto_first_child():
                continue

            # No children, try siblings
            while not cursor.goto_next_sibling():
                # No more siblings, ascend
                if not cursor.goto_parent():
                    # Reached root, done
                    return
                # Pop context only when leaving a class or function definition
                node_type = cursor.node.type
                if node_type in ("class_definition", "function_definition", "async_function_definition"):
                    if len(symbol_stack) > 1:
                        symbol_stack.pop()
                    if len(function_stack) > 1:
                        function_stack.pop()
            # Now at next sibling - continue loop to process it

    def _process_node_at_cursor(
        self,
        cursor: TreeCursor,
        filepath: str,
        result: ExtractionResult,
        current_symbol: str | None,
        current_function: str | None,
    ) -> bool:
        """
        Process the node at the current cursor position.

        Handles decorated_definition, class_definition, function_definition,
        call nodes, and import statements.

        Args:
            cursor: TreeCursor positioned at the node to process.
            filepath: File path for metadata.
            result: ExtractionResult being populated.
            current_symbol: Current enclosing class/symbol name.
            current_function: Current enclosing function name.

        Returns:
            True if children were already processed and should be skipped,
            False if the main loop should descend into children.
        """
        node = cursor.node
        node_type = node.type

        # Handle decorated_definition — extract decorators and process child directly
        if node_type == "decorated_definition":
            # Find the decorator nodes and the child definition
            decorators = []
            child_node = None
            if cursor.goto_first_child():
                while True:
                    child = cursor.node
                    if child.type == "decorator":
                        dec_text = self._extract_decorator_text(child)
                        if dec_text:
                            decorators.append(dec_text)
                    elif child.type in ("function_definition", "async_function_definition", "class_definition"):
                        child_node = child
                    if not cursor.goto_next_sibling():
                        break
                cursor.goto_parent()

            # Process the child with decorators
            if child_node is not None:
                self._process_definition(
                    child_node, filepath, result, current_symbol, current_function, decorators
                )
            return True  # Children already processed

        # Handle class_definition
        if node_type == "class_definition":
            self._process_class_definition(node, filepath, result, current_symbol)
            return False

        # Handle function_definition / async_function_definition
        if node_type in ("function_definition", "async_function_definition"):
            self._process_function_definition(
                node, filepath, result, current_symbol, current_function, []
            )
            return False

        # Handle call nodes — record call relationship
        if node_type == "call" and current_function is not None:
            callee = self._resolve_callee(node)
            if callee:
                # current_function is already qualified (e.g., "C.method_a")
                caller_key = current_function
                if caller_key not in result.calls:
                    result.calls[caller_key] = set()
                result.calls[caller_key].add(callee)
                if callee not in result.called_by:
                    result.called_by[callee] = set()
                result.called_by[callee].add(caller_key)

        # Handle import statements
        if node_type == "import_statement":
            import_str = self._format_import(node)
            if import_str:
                result.imports.append(import_str)
            return False

        if node_type == "import_from_statement":
            import_str = self._format_import_from(node)
            if import_str:
                result.imports.append(import_str)
            return False

        return False  # Default: main loop should descend into children

    def _process_definition(
        self,
        node,
        filepath: str,
        result: ExtractionResult,
        current_symbol: str | None,
        current_function: str | None,
        decorators: list[str],
    ) -> None:
        """
        Process a function or class definition node.

        Delegates to _process_class_definition or _process_function_definition
        based on node type.

        Args:
            node: class_definition or function_definition node.
            filepath: File path for metadata.
            result: ExtractionResult being populated.
            current_symbol: Current enclosing class/symbol name.
            current_function: Current enclosing function name.
            decorators: List of decorator strings.
        """
        if node.type == "class_definition":
            self._process_class_definition(node, filepath, result, current_symbol, decorators)
        elif node.type in ("function_definition", "async_function_definition"):
            self._process_function_definition(
                node, filepath, result, current_symbol, current_function, decorators
            )

    def _process_class_definition(
        self,
        node,
        filepath: str,
        result: ExtractionResult,
        parent_symbol: str | None,
        decorators: list[str] | None = None,
    ) -> None:
        """
        Process a class_definition node.

        Records the symbol and extracts method names. The main _walk loop
        handles traversal into the class body.

        Args:
            node: class_definition node.
            filepath: File path for metadata.
            result: ExtractionResult being populated.
            parent_symbol: Enclosing symbol name.
            decorators: Optional list of decorator strings.
        """
        class_name = self._get_identifier(node)
        if not class_name:
            return

        qualified_name = self._qualified_name(class_name, parent_symbol)
        lineno = node.start_point[0] + 1  # 1-indexed

        # Extract docstring from body
        docstring = self._extract_docstring(node)

        # Find methods by scanning body (not recursive traversal)
        methods = []
        body = self._get_child_by_type(node, "block")
        if body:
            for child in body.children:
                if child.type in ("function_definition", "async_function_definition", "decorated_definition"):
                    method_name = self._get_identifier(child)
                    if method_name:
                        methods.append(method_name)

        result.symbols[class_name] = {
            "file": filepath,
            "lineno": lineno,
            "docstring": docstring,
            "kind": "class",
            "methods": methods,
        }
        # Main _walk loop handles traversal into class body

    def _process_function_definition(
        self,
        node,
        filepath: str,
        result: ExtractionResult,
        current_symbol: str | None,
        current_function: str | None,
        decorators: list[str],
    ) -> None:
        """
        Process a function_definition or async_function_definition node.

        Records the function and recurses into its body to find calls.
        """
        func_name = self._get_identifier(node)
        if not func_name:
            return

        qualified_name = self._qualified_name(func_name, current_symbol)
        lineno = node.start_point[0] + 1  # 1-indexed
        end_lineno = node.end_point[0] + 1

        # Extract docstring
        docstring = self._extract_docstring(node)

        # Extract args
        args = self._extract_args(node)

        result.functions[qualified_name] = {
            "file": filepath,
            "lineno": lineno,
            "end_lineno": end_lineno,
            "docstring": docstring,
            "args": args,
            "symbol": current_symbol,
            "decorators": decorators,
        }
        # Main _walk loop handles traversal into function body

    def _extract_decorator_text(self, decorator_node) -> str | None:
        """
        Extract the text of a decorator without the leading @.

        Args:
            decorator_node: tree-sitter decorator node.

        Returns:
            Decorator text (e.g. "property", "router.get('/users')"), or None.
        """
        # decorator node has @ followed by the actual decorator expression
        for child in decorator_node.children:
            if child.type != "@":
                return child.text.decode("utf-8")
        return None

    def _extract_docstring(self, node) -> str | None:
        """
        Extract the docstring from a function or class node.

        Looks for the first expression_statement containing a string
        in the body block.

        Args:
            node: function_definition or class_definition node.

        Returns:
            Docstring text with quotes stripped, or None if absent.
        """
        body = self._get_child_by_type(node, "block")
        if not body:
            return None

        for child in body.children:
            if child.type == "expression_statement":
                # Look for string child
                for grandchild in child.children:
                    if grandchild.type in ("string", "string_content"):
                        text = grandchild.text.decode("utf-8")
                        return self._strip_string_quotes(text)
            elif child.type in ("string", "string_content"):
                text = child.text.decode("utf-8")
                return self._strip_string_quotes(text)

        return None

    def _strip_string_quotes(self, text: str) -> str:
        """
        Strip quotes from a string literal.

        Handles single, double, and triple-quoted strings.

        Args:
            text: The string text including quotes.

        Returns:
            String with quotes removed.
        """
        # Triple-quoted strings
        if text.startswith('"""') and text.endswith('"""'):
            return text[3:-3].strip()
        if text.startswith("'''") and text.endswith("'''"):
            return text[3:-3].strip()
        # Single-quoted strings
        if text.startswith('"') and text.endswith('"'):
            return text[1:-1]
        if text.startswith("'") and text.endswith("'"):
            return text[1:-1]
        return text

    def _extract_args(self, node) -> list[str]:
        """
        Extract argument names from a function definition.

        Only includes identifier nodes — skips *, **, /, and defaults.

        Args:
            node: function_definition or async_function_definition node.

        Returns:
            List of argument names (e.g. ["self", "x", "y"]).
        """
        args = []
        parameters = self._get_child_by_type(node, "parameters")
        if not parameters:
            return args

        for child in parameters.children:
            if child.type == "identifier":
                args.append(child.text.decode("utf-8"))
            elif child.type == "typed_parameter":
                # Handle typed parameters like "x: int"
                for grandchild in child.children:
                    if grandchild.type == "identifier":
                        args.append(grandchild.text.decode("utf-8"))
            elif child.type == "typed_default_parameter":
                # Handle typed parameters with defaults like "x: int = 5"
                for grandchild in child.children:
                    if grandchild.type == "identifier":
                        args.append(grandchild.text.decode("utf-8"))
            elif child.type == "default_parameter":
                # Handle parameters with defaults like "x = 5"
                for grandchild in child.children:
                    if grandchild.type == "identifier":
                        args.append(grandchild.text.decode("utf-8"))
            # Skip: *, **, /, type annotations (already handled above)

        return args

    def _resolve_callee(self, call_node) -> str | None:
        """
        Resolve the callee name from a call node.

        For identifier nodes, returns the bare name.
        For attribute nodes (foo.bar()), returns only the attribute name.

        Args:
            call_node: tree-sitter call node.

        Returns:
            Callee name string, or None if unresolvable.
        """
        # First child is the callable
        for child in call_node.children:
            if child.type == "identifier":
                return child.text.decode("utf-8")
            elif child.type == "attribute":
                # For attribute nodes like self.method(), we want the RIGHTMOST identifier
                # (the method name), not the leftmost (the object).
                # Iterate in reverse to find the last identifier.
                identifiers = []
                for grandchild in child.children:
                    if grandchild.type == "identifier":
                        identifiers.append(grandchild.text.decode("utf-8"))
                if identifiers:
                    return identifiers[-1]  # Return the rightmost (method name)
            elif child.type not in ("(", ")", "[", "]"):
                # Try to find identifier in other node types
                return self._find_identifier_in_node(child)

        return None

    def _find_identifier_in_node(self, node) -> str | None:
        """
        Find an identifier in a node by scanning children.

        Uses iterative DFS to avoid stack overflow on deeply nested ASTs.

        Args:
            node: tree-sitter node to search.

        Returns:
            Identifier text if found, None otherwise.
        """
        stack = [node]
        while stack:
            current = stack.pop()
            for child in current.children:
                if child.type == "identifier":
                    return child.text.decode("utf-8")
                stack.append(child)
        return None

    def _format_import(self, node) -> str | None:
        """
        Format an import_statement as a human-readable string.

        Args:
            node: import_statement node.

        Returns:
            Import string (e.g. "os, sys"), or None.
        """
        names = []
        for child in node.children:
            if child.type == "dotted_name":
                names.append(child.text.decode("utf-8"))
            elif child.type == "identifier":
                names.append(child.text.decode("utf-8"))
            elif child.type == "aliased_import":
                # Handle "import numpy as np" format
                aliased = []
                for grandchild in child.children:
                    if grandchild.type in ("dotted_name", "identifier"):
                        aliased.append(grandchild.text.decode("utf-8"))
                if len(aliased) == 2:
                    names.append(f"{aliased[0]} as {aliased[1]}")
                elif aliased:
                    names.append(aliased[0])

        if names:
            return ", ".join(names)
        return None

    def _format_import_from(self, node) -> str | None:
        """
        Format an import_from_statement as a human-readable string.

        Args:
            node: import_from_statement node.

        Returns:
            Import string (e.g. "from collections import defaultdict"), or None.
        """
        module = None
        names = []
        seen_import_keyword = False

        for child in node.children:
            if child.type == "dotted_name":
                if not seen_import_keyword:
                    # First dotted_name is the module
                    module = child.text.decode("utf-8")
                else:
                    # After 'import' keyword, these are the imported names
                    names.append(child.text.decode("utf-8"))
            elif child.type == "relative_import":
                # Handle "from . import x" or "from ..module import x"
                # Count dots in import_prefix nodes
                dots = 0
                module_name = None
                for c in child.children:
                    if c.type == "import_prefix":
                        # Count dots in the prefix (text is bytes)
                        dots = c.text.decode("utf-8").count(".")
                    elif c.type == "dotted_name":
                        module_name = c.text.decode("utf-8")

                if module_name:
                    module = "." * dots + module_name
                else:
                    module = "." * dots
            elif child.type == "import" and child.text.decode("utf-8") == "import":
                seen_import_keyword = True
            elif child.type == "wildcard_import":
                names.append("*")
            elif child.type == "identifier":
                # Standalone identifiers after 'import' are names
                if seen_import_keyword:
                    names.append(child.text.decode("utf-8"))
            elif child.type == "aliased_import":
                # Handle "from x import y as z" format
                aliased = []
                for grandchild in child.children:
                    if grandchild.type in ("dotted_name", "identifier"):
                        aliased.append(grandchild.text.decode("utf-8"))
                if len(aliased) == 2:
                    names.append(f"{aliased[0]} as {aliased[1]}")
                elif aliased:
                    names.append(aliased[0])

        # Handle "from X import Y, Z" format
        if module is not None and names:
            return f"from {module} import {', '.join(names)}"
        elif module is not None:
            return f"from {module}"
        return None

    def _get_identifier(self, node) -> str | None:
        """
        Get the identifier name from a definition node.

        Args:
            node: class_definition or function_definition node.

        Returns:
            Identifier text, or None if not found.
        """
        for child in node.children:
            if child.type == "identifier":
                return child.text.decode("utf-8")
            elif child.type == "type":
                # In class_definition, the name might be in a type node
                for grandchild in child.children:
                    if grandchild.type == "identifier":
                        return grandchild.text.decode("utf-8")
        return None

    def _get_child_by_type(self, node, target_type: str):
        """
        Get the first child of a given type.

        Args:
            node: Parent node to search.
            target_type: The tree-sitter node type to find.

        Returns:
            The child node, or None if not found.
        """
        for child in node.children:
            if child.type == target_type:
                return child
        return None

    def _qualified_name(self, name: str, parent_symbol: str | None) -> str:
        """
        Build a qualified name for a function or class.

        Args:
            name: The bare name of the function/class.
            parent_symbol: The enclosing class/symbol name, or None.

        Returns:
            "ClassName.method_name" if inside a symbol, else bare "function_name".
        """
        if parent_symbol:
            return f"{parent_symbol}.{name}"
        return name


# Register the PythonExtractor at module import time
register_extractor(PythonExtractor())
