"""
matrixmouse/tools/__init__.py

Aggregates all agent tools into a single importable package. 
Exposes TOOLS (list of functions for ollama.chat) and 
TOOL_REGISTRY (dict for dispatch).

To add a new tool:
    1. Define it in the appropriate submodule with type hints and a docstring.
    2. Import it here and add it to the TOOLS list.

Submodules:
    file_tools       - read, write, str_replace
    git_tools        - branch, commit, diff, log
    navigation_tools - directory structure, grep, find
    code_tools       - AST-based function and class inspection
    test_tools       - run pytest, parse results
    _safety.py       - path validation (internal, not a tool module)
"""

# agent/tools/__init__.py
# from .file_tools import read_file, str_replace, append_to_file
# from .git_tools import create_task_branch, commit_progress, get_git_diff, get_git_log
# from .navigation_tools import get_project_directory_structure, project_grep
# from .code_tools import get_function_def, get_function_list

# What gets passed to ollama.chat(tools=...)
TOOLS = [
            read_file,
            str_replace,
            append_to_file,
            create_task_branch,
            commit_progress,
            get_git_diff,
            get_git_log,
            get_project_directory_structure,
            project_grep,
            get_function_def,
            get_function_list,
]

# What gets used for dispatch — replaces globals()
TOOL_REGISTRY = {fn.__name__: fn for fn in TOOLS}
