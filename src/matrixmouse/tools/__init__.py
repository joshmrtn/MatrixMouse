"""
matrixmouse/tools/__init__.py

Aggregates all agent tools into a single importable package.
Exposes TOOLS (list of functions for ollama.chat) and
TOOL_REGISTRY (dict for dispatch).

To add a new tool:
    1. Define it in the appropriate submodule with type hints and a docstring.
    2. Import it here and add it to the TOOLS list.
    3. TOOL_REGISTRY is built automatically from TOOLS — no separate update needed.

Submodules:
    file_tools       — read, write, str_replace
    git_tools        — branch, commit, diff, log
    navigation_tools — directory structure, grep, find
    code_tools       — AST-based function and class inspection
    test_tools       — run pytest, parse results
    _safety.py       — path validation (internal, not a tool module)
"""

from matrixmouse.tools.file_tools import read_file, str_replace, append_to_file
from matrixmouse.tools.system_tools import declare_complete

# TODO: uncomment as each tool module is implemented
# from matrixmouse.tools.git_tools import (
#     create_task_branch, commit_progress, get_git_diff, get_git_log
# )
# from matrixmouse.tools.navigation_tools import (
#     get_project_directory_structure, project_grep, project_find
# )
# from matrixmouse.tools.code_tools import (
#     get_function_def, get_function_list, get_class_summary
# )
# from matrixmouse.tools.test_tools import run_tests

TOOLS = [
    read_file,
    str_replace,
    append_to_file,
    declare_complete,
    # TODO: add tools here as modules are implemented
]

# Built automatically — never update this manually
TOOL_REGISTRY = {fn.__name__: fn for fn in TOOLS}
