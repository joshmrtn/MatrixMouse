"""
/tools/file_tools.py

Tools for reading and writing files within the project.
All functions in this module enforce path safety via _safety.py

Tools exposed:
    read_file      - full file contents as a string
    str_replace    - replace a unique string in a file
    append_to_file - append content to the end of a file

Do not add navigation, git, or AST tools here.
"""

def read_file(filename):
    """Read entire file content"""
    if filename not in ALLOWED_FILES:
        return "Error: File access denied"
    try:
        with open(filename, 'r') as f:
            return f.read()
    except Exception as e:
        return f"Error reading {filename}: {e}"

# TODO: Implement the remaining tools for this module
