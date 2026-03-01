"""
matrixmouse/tools/test_tools.py

Tools for running the project's test suite and interpreting results.

Pytest is the default and preferred runner. If pytest is not installed,
falls back to Python's built-in unittest discovery.

Tools exposed:
    run_tests       — run the full suite or a specific file/directory
    run_single_test — run one specific test by node ID

Do not add file editing, git, or navigation tools here.

Dependencies:
    pytest          — strongly recommended, install via: pip install pytest
    pytest-mock     — optional, for mocking support: pip install pytest-mock
"""

import logging
import shutil
import subprocess
import sys
from pathlib import Path

from matrixmouse.tools._safety import project_root

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Runner detection
# ---------------------------------------------------------------------------

def _has_pytest() -> bool:
    """Return True if pytest is available in the current environment."""
    return shutil.which("pytest") is not None or _module_available("pytest")


def _module_available(name: str) -> bool:
    """Return True if a Python module can be imported."""
    import importlib.util
    return importlib.util.find_spec(name) is not None


def _detect_runner() -> str:
    """Return 'pytest' or 'unittest' based on what's available."""
    if _has_pytest():
        return "pytest"
    logger.warning(
        "pytest not found. Falling back to unittest. "
        "Install pytest for better output: pip install pytest"
    )
    return "unittest"


# ---------------------------------------------------------------------------
# Internal runner
# ---------------------------------------------------------------------------

def _run(cmd: list[str], cwd: Path) -> str:
    """
    Execute a subprocess command and return formatted output.

    Captures both stdout and stderr, combines them in order, and
    returns the full output with a pass/fail summary appended.
    """
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=300,  # 5 minute ceiling — long tests shouldn't block forever
        )
        output = result.stdout
        if result.stderr:
            output += "\n--- stderr ---\n" + result.stderr

        status = "PASSED" if result.returncode == 0 else "FAILED"
        output += f"\n--- {status} (exit code {result.returncode}) ---"

        logger.info("Test run %s. Command: %s", status, " ".join(cmd))
        return output.strip()

    except subprocess.TimeoutExpired:
        return "ERROR: Test run timed out after 5 minutes."
    except FileNotFoundError as e:
        return f"ERROR: Could not find test runner — {e}"
    except Exception as e:
        return f"ERROR: Unexpected error running tests: {e}"


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

def run_tests(path: str = "tests") -> str:
    """
    Run the test suite using pytest (preferred) or unittest (fallback).

    Run after making changes to verify nothing is broken. The output
    includes individual test results and a final pass/fail summary.

    Args:
        path: Path to a test file or directory to run. Defaults to
              'tests/', which runs the full suite. Accepts pytest node
              IDs like 'tests/test_config.py' or a directory like 'tests/'.

    Returns:
        Full test output including pass/fail summary, or an error message.
    """
    root = project_root()
    runner = _detect_runner()

    # Validate the path is within the project
    try:
        resolved = (root / path).resolve()
        resolved.relative_to(root)
    except ValueError:
        return f"ERROR: Path '{path}' is outside the project root."

    if not resolved.exists():
        return (
            f"ERROR: Test path '{path}' does not exist. "
            f"Check the path relative to the project root ({root})."
        )

    if runner == "pytest":
        cmd = [
            sys.executable, "-m", "pytest",
            str(resolved),
            "-v",               # verbose: show individual test names
            "--tb=short",       # short tracebacks — enough to diagnose, not overwhelming
            "--no-header",      # skip the pytest header to save context space
            "-q",               # quiet summary line
        ]
    else:
        # unittest discover requires a directory, not a file
        if resolved.is_file():
            # Run a single file with unittest
            cmd = [sys.executable, "-m", "unittest", str(resolved)]
        else:
            cmd = [
                sys.executable, "-m", "unittest",
                "discover",
                "-s", str(resolved),
                "-p", "test_*.py",
                "-v",
            ]

    return _run(cmd, root)


def run_single_test(test_id: str) -> str:
    """
    Run a single test by its pytest node ID.

    Use this to re-run a specific failing test without running the full
    suite, or to verify a fix without waiting for all tests to complete.

    Pytest node ID format:
        tests/test_config.py::test_load_defaults
        tests/test_config.py::TestClass::test_method

    Args:
        test_id: Full pytest node ID of the test to run.

    Returns:
        Test output with pass/fail result, or an error message.
    """
    root = project_root()

    if not _has_pytest():
        return (
            "ERROR: run_single_test requires pytest. "
            "Install it with: pip install pytest"
        )

    # Validate the file portion of the node ID is within the project
    file_part = test_id.split("::")[0]
    try:
        resolved_file = (root / file_part).resolve()
        resolved_file.relative_to(root)
    except ValueError:
        return f"ERROR: Test file '{file_part}' is outside the project root."

    cmd = [
        sys.executable, "-m", "pytest",
        test_id,
        "-v",
        "--tb=long",    # full tracebacks for single test runs — more useful for debugging
        "--no-header",
    ]

    return _run(cmd, root)
