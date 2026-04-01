"""tests/conftest.py

Root pytest configuration and fixtures for MatrixMouse tests.
"""

import pytest
import logging

# Configure logging for tests
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


@pytest.fixture(autouse=True)
def reset_logging():
    """Reset logging state between tests."""
    # Clear any handlers that might have been added
    logging.getLogger().handlers = []
    yield
