"""
matrixmouse/tools/code_tools.py

Tools for inspecting the project's code structure using the AST graph
built by graph.py.

All tools in this module are read-only. They query the graph and read
source files but never modify anything.

Call configure(graph) once at startup after analyze_project() returns,
before any tools are used.

Tools exposed:
    get_function_def    — full source of a function with surrounding context
    get_function_list   — all function/method names and line numbers in a file
    get_class_summary   — class docstring and method signatures without bodies
    get_dependencies    — what functions does this function call?
    get_call_sites      — what functions call this function?
    get_imports         — import block of a file

Do not add file writing, git, or navigation tools here.
"""

import logging
from pathlib import Path

from matrixmouse.graph import ProjectAnalyzer
from matrixmouse.tools._safety import project_root

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Module state — set once at startup via configure()
# ---------------------------------------------------------------------------

_graph: ProjectAnalyzer | None = None


def configure(graph: ProjectAnalyzer) -> None:
    """
    Initialise code tools with the project's AST graph.

    Must be called once at startup after analyze_project() returns.
    Safe to call again after the graph is updated (e.g. after a file write).

    Args:
        graph: A populated ProjectAnalyzer instance from graph.py.
    """
    global _graph
    _graph = graph
    logger.info(
        "Code tools configured. %d functions, %d classes available.",
        len(graph.functions), len(graph.classes)
    )


def _require_graph() -> ProjectAnalyzer | None:
    """Return the graph or log a clear error if not configured."""
    if _graph is None:
        logger.error("Code tools not configured. Call code_tools.configure(graph) at startup.")
    return _graph


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

def get_function_def(func_name: str) -> str:
    """
    Return the full source code of a function with 3 lines of context
    above and below. Line numbers are shown for reference.

    Use this before editing a function to see exactly what it currently
    contains, including surrounding context that might be affected.

    Args:
        func_name: The function or method name to look up. For methods,
                   use either 'method_name' or 'ClassName.method_name'.

    Returns:
        Line-numbered source with the function body marked with >>>,
        or an error if the function is not found.
    """
    graph = _require_graph()
    if graph is None:
        return "ERROR: Code tools not configured."

    # Try exact match first, then search for unqualified name
    info = graph.functions.get(func_name)
    if info is None:
        # Search for unqualified match e.g. "my_func" matching "MyClass.my_func"
        matches = [
            (name, data) for name, data in graph.functions.items()
            if name == func_name or name.endswith(f".{func_name}")
        ]
        if len(matches) == 0:
            available = sorted(graph.functions.keys())
            return (
                f"ERROR: Function '{func_name}' not found in the project graph. "
                f"Use get_function_list(filename) to see available functions. "
                f"Known functions: {available[:20]}{'...' if len(available) > 20 else ''}"
            )
        if len(matches) > 1:
            names = [m[0] for m in matches]
            return (
                f"ERROR: Ambiguous function name '{func_name}'. "
                f"Multiple matches: {names}. Use the qualified name."
            )
        func_name, info = matches[0]

    filepath = info["file"]
    start_line = info["lineno"]
    end_line = info["end_lineno"]

    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            all_lines = f.readlines()
    except Exception as e:
        return f"ERROR: Could not read {filepath}: {e}"

    # 3 lines of context above and below, clamped to file bounds
    context_start = max(0, start_line - 4)       # -4 because lines are 1-indexed
    context_end = min(len(all_lines), end_line + 3)

    result_lines = []
    result_lines.append(f"# {filepath}  (lines {start_line}–{end_line})\n")

    for i, line in enumerate(all_lines[context_start:context_end], start=context_start + 1):
        marker = ">>>" if start_line <= i <= end_line else "   "
        result_lines.append(f"{marker} {i:4d} | {line}")

    return "".join(result_lines)


def get_function_list(filename: str) -> str:
    """
    List all functions and methods defined in a file, with line numbers.

    Use this to get an overview of a file's contents before deciding
    which function to inspect or edit.

    Args:
        filename: Path to the Python file to inspect.

    Returns:
        A formatted list of function names and line numbers, grouped by
        class, or an error if the file is not found in the graph.
    """
    graph = _require_graph()
    if graph is None:
        return "ERROR: Code tools not configured."

    # Resolve to absolute path for consistent matching
    try:
        resolved = str(Path(filename).resolve())
    except Exception as e:
        return f"ERROR: Could not resolve path {filename}: {e}"

    # Find all functions in this file
    file_functions = {
        name: info for name, info in graph.functions.items()
        if info.get("file") == resolved
    }

    if not file_functions:
        # Try matching by basename in case the graph used a different root
        basename = Path(filename).name
        file_functions = {
            name: info for name, info in graph.functions.items()
            if Path(info.get("file", "")).name == basename
        }

    if not file_functions:
        return (
            f"ERROR: No functions found for '{filename}'. "
            "The file may not have been analyzed, or may contain no functions. "
            "Run analyze_project() to refresh the graph."
        )

    # Group by class, then module-level
    classes: dict[str, list] = {}
    module_level: list = []

    for name, info in sorted(file_functions.items(), key=lambda x: x[1]["lineno"]):
        cls = info.get("class")
        entry = f"  {'async ' if 'async' in name else ''}def {name.split('.')[-1]}({', '.join(info.get('args', []))})"
        entry += f"  # line {info['lineno']}"
        if info.get("docstring"):
            first_line = info["docstring"].split("\n")[0].strip()
            entry += f" — {first_line[:60]}{'...' if len(first_line) > 60 else ''}"

        if cls:
            classes.setdefault(cls, []).append(entry)
        else:
            module_level.append(entry)

    lines = [f"Functions in {filename}:\n"]

    if module_level:
        lines.append("Module level:")
        lines.extend(module_level)
        lines.append("")

    for cls_name, methods in classes.items():
        cls_info = graph.classes.get(cls_name, {})
        cls_line = cls_info.get("lineno", "?")
        lines.append(f"class {cls_name}:  # line {cls_line}")
        lines.extend(methods)
        lines.append("")

    return "\n".join(lines)


def get_class_summary(class_name: str) -> str:
    """
    Return a class's docstring and all method signatures without bodies.

    Use this to understand a class's interface before reading its
    implementation. Cheaper than reading the full file.

    Args:
        class_name: The class name to look up.

    Returns:
        Class docstring and method signatures, or an error if not found.
    """
    graph = _require_graph()
    if graph is None:
        return "ERROR: Code tools not configured."

    info = graph.classes.get(class_name)
    if info is None:
        available = sorted(graph.classes.keys())
        return (
            f"ERROR: Class '{class_name}' not found. "
            f"Known classes: {available}"
        )

    lines = [f"class {class_name}:  # {info.get('file', 'unknown file')}, line {info.get('lineno', '?')}"]

    if info.get("docstring"):
        lines.append(f'    """{info["docstring"]}"""')
        lines.append("")

    for method_name in info.get("methods", []):
        qualified = f"{class_name}.{method_name}"
        method_info = graph.functions.get(qualified, {})
        args = method_info.get("args", [])
        doc = method_info.get("docstring", "")
        first_line = doc.split("\n")[0].strip() if doc else ""
        line_no = method_info.get("lineno", "?")

        sig = f"    def {method_name}({', '.join(args)})"
        sig += f"  # line {line_no}"
        if first_line:
            sig += f" — {first_line[:60]}{'...' if len(first_line) > 60 else ''}"
        lines.append(sig)

    return "\n".join(lines)


def get_dependencies(func_name: str) -> str:
    """
    Show what functions this function calls.

    Use this before modifying a function to understand what it depends on,
    or when debugging to trace where a call originates.

    Args:
        func_name: The function or method name to inspect.

    Returns:
        A list of functions called by func_name, with their docstrings,
        or a message if no tracked calls are found.
    """
    graph = _require_graph()
    if graph is None:
        return "ERROR: Code tools not configured."

    deps = graph.calls.get(func_name, set())
    if not deps:
        return (
            f"'{func_name}' makes no tracked internal calls. "
            "(External library calls and dynamic dispatch are not tracked.)"
        )

    lines = [f"'{func_name}' calls:"]
    for dep in sorted(deps):
        info = graph.functions.get(dep, {})
        doc = info.get("docstring", "")
        first_line = doc.split("\n")[0].strip() if doc else "no docstring"
        file_ref = f" ({Path(info['file']).name})" if info.get("file") else ""
        lines.append(f"  {dep}(){file_ref} — {first_line[:80]}")

    return "\n".join(lines)


def get_call_sites(func_name: str) -> str:
    """
    Show what functions call this function.

    Use this before modifying a function's signature or behaviour to
    understand the blast radius — how many callers will be affected.

    Args:
        func_name: The function or method name to inspect.

    Returns:
        A list of functions that call func_name, or a message if none found.
    """
    graph = _require_graph()
    if graph is None:
        return "ERROR: Code tools not configured."

    callers = graph.called_by.get(func_name, set())
    if not callers:
        return (
            f"No tracked callers found for '{func_name}'. "
            "It may be an entry point, unused, or called dynamically."
        )

    lines = [f"'{func_name}' is called by:"]
    for caller in sorted(callers):
        info = graph.functions.get(caller, {})
        file_ref = f" ({Path(info['file']).name})" if info.get("file") else ""
        lines.append(f"  {caller}(){file_ref}")

    return "\n".join(lines)


def get_imports(filename: str) -> str:
    """
    Return the import statements from a file.

    Use this to quickly understand a file's external dependencies and
    internal imports without reading the full file.

    Args:
        filename: Path to the Python file to inspect.

    Returns:
        Import statements as a string, or an error if not found.
    """
    graph = _require_graph()
    if graph is None:
        return "ERROR: Code tools not configured."

    try:
        resolved = str(Path(filename).resolve())
    except Exception as e:
        return f"ERROR: Could not resolve path {filename}: {e}"

    imports = graph.imports.get(resolved)

    if imports is None:
        # Fallback: try by basename
        basename = Path(filename).name
        for path, imps in graph.imports.items():
            if Path(path).name == basename:
                imports = imps
                break

    if not imports:
        return f"No imports found for '{filename}'."

    return "\n".join(imports)
