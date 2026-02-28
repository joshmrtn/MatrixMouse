"""
/tools/_safety.py

Provides path validation for safe tool calling. This is not a tool module, it is 
an internal helper.
"""


import os
from pathlib import Path
from fnmatch import fnmatch

PROJECT_ROOT = Path(os.path.abspath(".")).resolve()

# Patterns relative to project root. Supports wildcards.
BLACKLISTED_PATTERNS = [
            ".env",
            ".env.*",
            "**/.env",
            "**/.env.*",
            "**/secrets.*",
            "**/*.pem",
            "**/*.key",
            # Add agent's own core files if you don't want it self-modifying certain things
            # "agent/orchestrator.py",
]

def is_safe_path(filepath: str, write: bool = False) -> tuple[bool, str]:
        """
        Returns (True, resolved_path_str) if the path is allowed,
        or (False, reason_str) if it should be rejected.
        """
        try:
            resolved = Path(filepath).resolve()
        except Exception as e:
            return False, f"Could not resolve path: {e}"
        
        # Must be inside project root
        try:
            relative = resolved.relative_to(PROJECT_ROOT)
        except ValueError:
            return False, f"Path is outside project root: {resolved}"
            
        # Check blacklist
        for pattern in BLACKLISTED_PATTERNS:
            if fnmatch(str(relative), pattern) or fnmatch(resolved.name, pattern):
                return False, f"Path matches blacklisted pattern '{pattern}'"
            
        return True, str(resolved)
