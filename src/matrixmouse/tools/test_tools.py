"""
matrixmouse/tools/test_tools.py

Tools for running the project's test suite and interpreting results.

Test execution is delegated to a locked-down temporary container via a 
FIFO pipe pair. The agent has no knowledge of this — it calls run_tests() 
and gets a result string back.

The FIFO protocol:
    Request:  "<8-hex-token> <optional-test-path>\n"
    Response: "<8-hex-token> <exit-code>\n<output>\n"

The token is generated per-call and verified on response to prevent
stale results from a previous crashed session being injected into a
new one.

Tools exposed:
    run_tests       — run the full suite or a specific file/directory
    run_single_test — run one specific test by pytest node ID

Do not add file editing, git, or navigation tools here.
"""

import logging
import os
import secrets
import subprocess
import sys
from pathlib import Path

from matrixmouse.tools._safety import project_root

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# FIFO configuration — must match docker-compose volume mount
# ---------------------------------------------------------------------------

_FIFO_DIR = Path(os.environ.get("MM_FIFO_DIR", "/run/matrixmouse-pipes"))
_REQUEST_FIFO = _FIFO_DIR / "request.fifo"
_RESULT_FIFO = _FIFO_DIR / "result.fifo"

# How long to wait for a test result before giving up (seconds)
_RESULT_TIMEOUT = int(os.environ.get("MM_TEST_TIMEOUT", "360"))

# Maximum number of stale results to discard before giving up
_MAX_STALE_READS = 3


# ---------------------------------------------------------------------------
# FIFO availability check
# ---------------------------------------------------------------------------

def _fifo_available() -> bool:
    """Return True if the FIFO pipes exist and are usable."""
    return _REQUEST_FIFO.is_fifo() and _RESULT_FIFO.is_fifo()


# ---------------------------------------------------------------------------
# FIFO-based execution 
# ---------------------------------------------------------------------------

def _run_via_fifo(test_path: str) -> str:
    """
    Send a test request through the FIFO pair and return the result.

    Generates a fresh token per call. Discards stale results from
    previous sessions to handle crash-restart scenarios cleanly.

    Args:
        test_path: Relative path to test file or directory, e.g. "tests/"
                   or "tests/test_config.py::test_load_defaults".

    Returns:
        Test output string with pass/fail summary appended.
    """
    token = secrets.token_hex(4)  # 8 hex chars
    request_line = f"{token} {test_path}".strip()

    logger.info("Sending test request via FIFO. Token: %s Path: %s", token, test_path)

    # Write request — open in write mode (blocks until host reads it)
    try:
        with open(_REQUEST_FIFO, "w") as req:
            req.write(request_line + "\n")
            req.flush()
    except Exception as e:
        return f"ERROR: Failed to write to request FIFO: {e}"

    # Read result — discard stale results from previous sessions
    for attempt in range(_MAX_STALE_READS + 1):
        try:
            result = _read_result_fifo(timeout=_RESULT_TIMEOUT)
        except TimeoutError:
            return (
                f"ERROR: Test runner did not respond within {_RESULT_TIMEOUT}s. "
                "The host-side test_runner.sh may not be running, or the tests "
                "are taking longer than expected."
            )
        except Exception as e:
            return f"ERROR: Failed to read from result FIFO: {e}"

        # Parse first line: "<token> <exit_code>"
        lines = result.split("\n", 1)
        header = lines[0].strip()
        output = lines[1] if len(lines) > 1 else ""

        parts = header.split(" ", 1)
        if len(parts) != 2:
            logger.warning("Malformed result header: %s", header)
            continue

        result_token, exit_code_str = parts[0], parts[1]

        if result_token != token:
            logger.warning(
                "Stale result discarded. Expected token %s got %s (attempt %d/%d).",
                token, result_token, attempt + 1, _MAX_STALE_READS
            )
            if attempt >= _MAX_STALE_READS:
                return (
                    "ERROR: Received too many stale results. "
                    "The test runner may be in an inconsistent state. "
                    "Restart test_runner.sh on the host."
                )
            continue

        # Token matches — this is our result
        try:
            exit_code = int(exit_code_str)
        except ValueError:
            exit_code = 1

        status = "PASSED" if exit_code == 0 else "FAILED"
        logger.info("Test result received. Token: %s Status: %s", token, status)
        return f"{output.rstrip()}\n\n--- {status} (exit code {exit_code}) ---"

    return "ERROR: Unexpected state in FIFO result handling."


def _read_result_fifo(timeout: int) -> str:
    """
    Read the full result from result.fifo with a timeout.
    Uses a subprocess cat with timeout rather than a raw open() call,
    which would block indefinitely if the host script crashes mid-write.

    Args:
        timeout: Seconds to wait before raising TimeoutError.

    Returns:
        Raw result string from the host script.

    Raises:
        TimeoutError: If no result arrives within timeout seconds.
        Exception:    On other read failures.
    """
    try:
        result = subprocess.run(
            ["cat", str(_RESULT_FIFO)],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.stdout
    except subprocess.TimeoutExpired:
        raise TimeoutError(f"No result after {timeout}s")


# ---------------------------------------------------------------------------
# Path validation
# ---------------------------------------------------------------------------

def _validate_test_path(path: str) -> tuple[bool, str]:
    """
    Validate that a test path is safe to pass to the test runner.
    Must be under the tests/ directory and contain no traversal.

    Returns:
        (valid, reason) where reason is empty if valid.
    """
    if not path or path == "tests" or path.startswith("tests/"):
        if ".." in path:
            return False, "Path contains '..'"
        return True, ""
    return False, f"Test path must start with 'tests/' — got '{path}'"


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

def run_tests(path: str = "tests") -> str:
    """
    Run the test suite and return the full output.

    Run this after making changes to verify nothing is broken. The output
    includes individual test results and a final pass/fail summary.

    Args:
        path: Path to a test file or directory. Defaults to 'tests/',
              which runs the full suite. Must be under the tests/ directory.

    Returns:
        Full test output with pass/fail summary, or an error message.
    """
    valid, reason = _validate_test_path(path)
    if not valid:
        return f"ERROR: {reason}"

    if not _fifo_available():
        return "ERROR: Test runner not available. Is matrixmouse-test-runner.service running?"
        
    logger.info("Using FIFO test runner.")
    return _run_via_fifo(path)


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
                 Must start with 'tests/'.

    Returns:
        Test output with pass/fail result, or an error message.
    """
    valid, reason = _validate_test_path(test_id.split("::")[0])
    if not valid:
        return f"ERROR: {reason}"

    if not _fifo_available():
        return "ERROR: Test runner not available. Is matrixmouse-test-runner.service running?"
        
    logger.info("Using FIFO test runner.")
    return _run_via_fifo(test_id)

RUN_TESTS_SCHEMA = {
    "name": "run_tests",
    "description": (
        "Run the test suite and return the full output with pass/fail summary. "
        "Run this after making changes to verify nothing is broken. "
        "Defaults to the full suite; pass a specific file or directory to narrow scope."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "Path to a test file or directory. Defaults to 'tests/' for the full suite. "
                    "Must be under the tests/ directory."
                ),
            },
        },
        "required": [],
    },
}

RUN_SINGLE_TEST_SCHEMA = {
    "name": "run_single_test",
    "description": (
        "Run a single test by its pytest node ID. "
        "Use this to re-run a specific failing test or verify a fix "
        "without waiting for the full suite."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "test_id": {
                "type": "string",
                "description": (
                    "Full pytest node ID, e.g. "
                    "'tests/test_config.py::test_load_defaults' or "
                    "'tests/test_config.py::TestClass::test_method'. "
                    "Must start with 'tests/'."
                ),
            },
        },
        "required": ["test_id"],
    },
}