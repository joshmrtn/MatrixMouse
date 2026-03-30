"""
tests/frontend/conftest.py

Pytest fixtures for frontend E2E testing with Playwright.
Uses real MatrixMouse API with mocked backend components.
"""

import pytest
from playwright.sync_api import Browser, BrowserContext, Page, Playwright
from playwright.sync_api import sync_playwright

from .test_server import TestMatrixMouseServer


# ---------------------------------------------------------------------------
# Playwright Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def playwright_instance() -> Playwright:
    """Create Playwright instance."""
    pw = sync_playwright().start()
    yield pw
    pw.stop()


@pytest.fixture(scope="session")
def browser(playwright_instance: Playwright) -> Browser:
    """Create browser instance (Chromium)."""
    browser = playwright_instance.chromium.launch(
        headless=True,
        args=["--no-sandbox", "--disable-setuid-sandbox"],
    )
    yield browser
    browser.close()


@pytest.fixture
def context(browser: Browser) -> BrowserContext:
    """Create browser context with isolated storage."""
    context = browser.new_context(
        viewport={"width": 1280, "height": 720},
    )
    yield context
    context.close()


@pytest.fixture
def page(context: BrowserContext) -> Page:
    """Create new page in context."""
    page = context.new_page()
    # Slower actions for more reliable testing
    page.set_default_timeout(10000)
    yield page


# ---------------------------------------------------------------------------
# Test Server Fixtures (Real API + Mocked Backend)
# ---------------------------------------------------------------------------

@pytest.fixture
def test_server() -> TestMatrixMouseServer:
    """Create and start a test server with mocked backend."""
    from .test_server import TestMatrixMouseServer
    import random
    
    # Use random port to avoid conflicts when running tests in parallel
    port = random.randint(8765, 9999)
    server = TestMatrixMouseServer(port=port)
    server.start()
    yield server
    server.stop()


@pytest.fixture
def server_url(test_server: TestMatrixMouseServer) -> str:
    """Return the test server URL."""
    return f"http://127.0.0.1:{test_server.port}"


@pytest.fixture
def page_with_test_server(page: Page, server_url: str) -> Page:
    """Navigate to the test server's UI."""
    page.goto(server_url)
    # Wait for app to load
    page.wait_for_selector("#app", timeout=5000)
    yield page


@pytest.fixture
def reset_server(test_server: TestMatrixMouseServer):
    """Reset server state before each test."""
    test_server.reset()
    yield test_server


# ---------------------------------------------------------------------------
# Helper Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def wait_for_ws(page: Page):
    """Wait for WebSocket connection to be established."""
    page.wait_for_function("""
        () => {
            const connDot = document.getElementById('conn-dot');
            return connDot && connDot.classList.contains('live');
        }
    """, timeout=10000)
    yield


@pytest.fixture
def create_test_task(test_server: TestMatrixMouseServer):
    """Factory fixture for creating test tasks via the real API."""
    def _create_task(
        title: str = "Test Task",
        description: str = "",
        repo: list[str] = None,
        status: str = "ready",
        **kwargs,
    ) -> dict:
        return test_server.create_task(
            title=title,
            description=description,
            repo=repo or [],
            status=status,
            **kwargs,
        )
    
    return _create_task


# ---------------------------------------------------------------------------
# Test Data Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_task_data() -> dict:
    """Sample task data for testing."""
    return {
        "id": "test123",
        "title": "Test Task",
        "description": "This is a test task",
        "repo": ["test-repo"],
        "role": "coder",
        "status": "ready",
        "branch": "mm/test-task",
        "importance": 0.5,
        "urgency": 0.5,
        "priority_score": 0.5,
        "context_messages": [],
    }


@pytest.fixture
def sample_blocked_task_data() -> dict:
    """Sample blocked task data for testing."""
    return {
        "id": "blocked123",
        "title": "Blocked Task",
        "description": "This task is blocked",
        "repo": ["test-repo"],
        "role": "coder",
        "status": "blocked_by_human",
        "notes": "Needs human approval",
        "importance": 0.5,
        "urgency": 0.5,
        "priority_score": 0.5,
        "context_messages": [],
    }


@pytest.fixture
def sample_repos() -> list[dict]:
    """Sample repository data for testing."""
    return [
        {"name": "test-repo", "remote": "https://github.com/test/test-repo.git"},
        {"name": "another-repo", "remote": "https://github.com/test/another-repo.git"},
    ]

