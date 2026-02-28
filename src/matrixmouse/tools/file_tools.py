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


def str_replace(filename: str, old_str: str, new_str: str) -> str:
    """
    Replaces the first occurrence of old_str in filename with new_str.
    Returns an error if old_str is not found, or if it matches more than once.
    """
    with open(filename, 'r') as f:
        content = f.read()

    count = content.count(old_str)
    if count == 0:
        return f"ERROR: The string was not found in {filename}. No changes made."
    if count > 1:
        return f"ERROR: The string appears {count} times in {filename}. Provide more context to make it unambiguous."

    with open(filename, 'w') as f:
        f.write(content.replace(old_str, new_str, 1))

    return f"OK: Replacement made successfully."


def append_to_file(filename: str, content: str) -> str:
    """
    Appends a given string to a new or existing file, where filename is the 
    name of the file to write to, and content is the content to add to the 
    file. Use triple quotes for multi-line content.

    Args:
        filename (str): The filename to append content to.
        content (str): The content which will be appended to the file.
    """
    try:
        if (filename not in PERMITTED_FILES):
            raise PermissionError("Permission denied. Cannot open file for writing.")
        with open(filename, 'a') as f:
            f.write(content)
            f.write("\n")
            return f"Append to {filename} was successful."

    except Exception as e:
        return f"ERROR: {e}"
