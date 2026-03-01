"""
matrixmouse/tools/navigation_tools.py

Tools for exploring the project's layout and searching its contents.
All tools are read-only — they never modify files.

Tools exposed:
    get_project_directory_structure — tree-style directory listing
    get_file_summary                — top-level docstring, class names,
                                      and function signatures only
    project_grep                    — regex search across all project files
    project_find                    — find files by name pattern

Do not add file editing, git, or AST tools here.
"""

import logging
import os
import re
from fnmatch import fnmatch
from pathlib import Path

from matrixmouse.tools._safety import project_root

logger = logging.getLogger(__name__)

# Directories that are never useful to show or search
_SKIP_DIRS = {
    ".git", "__pycache__", ".venv", "venv", ".env",
    "node_modules", ".mypy_cache", ".pytest_cache",
    ".ruff_cache", "dist", "build", "*.egg-info",
}


def _should_skip_dir(name: str) -> bool:
    """Return True if a directory should be excluded from all navigation tools."""
    return name in _SKIP_DIRS or any(fnmatch(name, pat) for pat in _SKIP_DIRS)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

def get_project_directory_structure(max_depth: int = 3) -> str:
    """
    Return a tree-style listing of the project directory structure.

    Skips noise directories (.git, __pycache__, .venv, node_modules, etc).
    Use this first to orient yourself in an unfamiliar project before
    deciding which files to read.

    Args:
        max_depth: How many directory levels to show. Defaults to 3.
                   Use a lower value for large projects to reduce output.

    Returns:
        A formatted directory tree as a string.
    """
    root = project_root()
    lines = [f"{root.name}/"]

    def _walk(path: Path, prefix: str, depth: int) -> None:
        if depth > max_depth:
            return

        try:
            entries = sorted(path.iterdir(), key=lambda e: (e.is_file(), e.name.lower()))
        except PermissionError:
            return

        # Separate dirs and files, filter skip dirs
        dirs = [e for e in entries if e.is_dir() and not _should_skip_dir(e.name)]
        files = [e for e in entries if e.is_file()]
        visible = dirs + files

        for i, entry in enumerate(visible):
            is_last = i == len(visible) - 1
            connector = "└── " if is_last else "├── "
            extension = "    " if is_last else "│   "

            if entry.is_dir():
                lines.append(f"{prefix}{connector}{entry.name}/")
                if depth < max_depth:
                    _walk(entry, prefix + extension, depth + 1)
                else:
                    # Indicate there is content below the depth limit
                    try:
                        child_count = sum(1 for _ in entry.iterdir())
                        if child_count:
                            lines.append(f"{prefix}{extension}└── ... ({child_count} items)")
                    except PermissionError:
                        pass
            else:
                lines.append(f"{prefix}{connector}{entry.name}")

    _walk(root, "", 1)
    return "\n".join(lines)


def get_file_summary(filename: str) -> str:
    """
    Return a high-level summary of a Python file: module docstring,
    class names, and function signatures only — no implementation bodies.

    Use this to understand what a file contains without reading the full
    source. Cheaper than read_file for orientation purposes.

    Args:
        filename: Path to the Python file to summarise.

    Returns:
        Formatted summary with docstring, classes, and function signatures.
    """
    import ast as _ast

    root = project_root()

    try:
        resolved = Path(filename).resolve()
        resolved.relative_to(root)  # ensure within project
    except ValueError:
        return f"ERROR: Path is outside project root: {filename}"
    except Exception as e:
        return f"ERROR: Could not resolve path {filename}: {e}"

    if not resolved.exists():
        return f"ERROR: File not found: {filename}"

    try:
        source = resolved.read_text(encoding="utf-8", errors="ignore")
        tree = _ast.parse(source)
    except SyntaxError as e:
        return f"ERROR: Syntax error in {filename}: {e}"
    except Exception as e:
        return f"ERROR: Could not parse {filename}: {e}"

    lines = [f"# {resolved.name}"]

    # Module docstring
    module_doc = _ast.get_docstring(tree)
    if module_doc:
        first_para = module_doc.strip().split("\n\n")[0].strip()
        lines.append(f'"""{first_para}"""')
        lines.append("")

    # Top-level classes and functions
    for node in tree.body:
        if isinstance(node, _ast.ClassDef):
            doc = _ast.get_docstring(node)
            doc_line = f'  """{doc.split(chr(10))[0]}"""' if doc else ""
            lines.append(f"class {node.name}:")
            if doc_line:
                lines.append(doc_line)
            # Method signatures only
            for item in node.body:
                if isinstance(item, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
                    args = [a.arg for a in item.args.args]
                    prefix = "async " if isinstance(item, _ast.AsyncFunctionDef) else ""
                    lines.append(f"    {prefix}def {item.name}({', '.join(args)})")
            lines.append("")

        elif isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
            args = [a.arg for a in node.args.args]
            doc = _ast.get_docstring(node)
            prefix = "async " if isinstance(node, _ast.AsyncFunctionDef) else ""
            lines.append(f"{prefix}def {node.name}({', '.join(args)}):")
            if doc:
                first_line = doc.strip().split("\n")[0]
                lines.append(f'    """{first_line}"""')
            lines.append("")

    return "\n".join(lines)


def project_grep(pattern: str, file_pattern: str = "*.py") -> str:
    """
    Search all project files for lines matching a regular expression.

    Use this to locate where a variable, function, or string is defined
    or used across the project. Faster than reading files one by one.

    Args:
        pattern:      Regular expression to search for.
        file_pattern: Glob pattern to filter which files are searched.
                      Defaults to '*.py'. Use '*' to search all files.

    Returns:
        Matching lines with file paths and line numbers, or a message
        if no matches are found. Output is capped at 100 matches to
        prevent context overflow.
    """
    root = project_root()

    try:
        regex = re.compile(pattern)
    except re.error as e:
        return f"ERROR: Invalid regular expression '{pattern}': {e}"

    matches = []
    searched = 0
    MAX_MATCHES = 100

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not _should_skip_dir(d)]

        for filename in filenames:
            if not fnmatch(filename, file_pattern):
                continue

            filepath = Path(dirpath) / filename
            searched += 1

            try:
                lines = filepath.read_text(
                    encoding="utf-8", errors="ignore"
                ).splitlines()
            except Exception:
                continue

            for lineno, line in enumerate(lines, start=1):
                if regex.search(line):
                    rel = filepath.relative_to(root)
                    matches.append(f"{rel}:{lineno}: {line.rstrip()}")
                    if len(matches) >= MAX_MATCHES:
                        matches.append(
                            f"\n... output capped at {MAX_MATCHES} matches "
                            f"({searched} files searched). "
                            "Refine your pattern to narrow results."
                        )
                        return "\n".join(matches)

    if not matches:
        return (
            f"No matches for '{pattern}' in {file_pattern} files "
            f"({searched} files searched)."
        )

    return "\n".join(matches) + f"\n\n({len(matches)} matches in {searched} files)"


def project_find(name_pattern: str) -> str:
    """
    Find files in the project matching a name pattern.

    Use this to locate a file when you know its name or part of its name
    but not its full path.

    Args:
        name_pattern: Glob pattern to match against file names,
                      e.g. 'config.py', '*.toml', 'test_*.py'.

    Returns:
        Relative paths of matching files, or a message if none found.
    """
    root = project_root()
    matches = []

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not _should_skip_dir(d)]

        for filename in filenames:
            if fnmatch(filename, name_pattern):
                filepath = Path(dirpath) / filename
                matches.append(str(filepath.relative_to(root)))

    if not matches:
        return f"No files matching '{name_pattern}' found in project."

    return "\n".join(sorted(matches)) + f"\n\n({len(matches)} files found)"
