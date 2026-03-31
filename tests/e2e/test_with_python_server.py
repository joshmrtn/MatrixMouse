"""tests/e2e/test_with_python_server.py

Run Playwright E2E tests with the Python test server.

This module provides pytest wrappers that:
1. Start the MatrixMouseTestServer with frontend build
2. Run Playwright tests against it
3. Clean up the server

Usage:
    uv run pytest tests/e2e/test_with_python_server.py -v
"""

import pytest
import subprocess
from pathlib import Path


def run_playwright_tests(e2e_base_url: str, test_file: str = None) -> int:
    """
    Run Playwright tests against the test server.
    
    Args:
        e2e_base_url: Base URL of the test server
        test_file: Specific test file to run (optional)
    
    Returns:
        Exit code from Playwright
    """
    frontend_root = Path(__file__).parent.parent.parent / "frontend"
    
    cmd = [
        "npx", "playwright", "test",
        "--reporter=list",
        "--config=playwright.config.ts",
    ]
    
    if test_file:
        # Test file is relative to tests/e2e directory
        cmd.append(f"tests/e2e/{test_file}")
    
    env = dict(**subprocess.os.environ)
    env["PLAYWRIGHT_BASE_URL"] = e2e_base_url
    
    result = subprocess.run(
        cmd,
        cwd=frontend_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    
    print(result.stdout)
    if result.stderr:
        print(result.stderr)
    
    return result.returncode


@pytest.mark.e2e
def test_status_dashboard_with_server(e2e_test_server, setup_blocked_tasks):
    """Test status dashboard with Python test server."""
    base_url = f"http://{e2e_test_server.config.host}:{e2e_test_server.config.port}"
    exit_code = run_playwright_tests(base_url, "test_status_dashboard.spec.ts")
    assert exit_code == 0, "Status dashboard E2E tests failed"


@pytest.mark.e2e
def test_tasks_page_with_server(e2e_test_server, setup_test_data):
    """Test tasks page with Python test server."""
    base_url = f"http://{e2e_test_server.config.host}:{e2e_test_server.config.port}"
    exit_code = run_playwright_tests(base_url, "test_tasks_page.spec.ts")
    assert exit_code == 0, "Tasks page E2E tests failed"


@pytest.mark.e2e
def test_settings_page_with_server(e2e_test_server, setup_settings_data):
    """Test settings page with Python test server."""
    base_url = f"http://{e2e_test_server.config.host}:{e2e_test_server.config.port}"
    exit_code = run_playwright_tests(base_url, "test_settings_page.spec.ts")
    assert exit_code == 0, "Settings page E2E tests failed"


@pytest.mark.e2e
def test_channel_page_with_server(e2e_test_server, setup_channel_data):
    """Test channel page with Python test server."""
    base_url = f"http://{e2e_test_server.config.host}:{e2e_test_server.config.port}"
    exit_code = run_playwright_tests(base_url, "test_channel_page.spec.ts")
    assert exit_code == 0, "Channel page E2E tests failed"


@pytest.mark.e2e
def test_integration_flows_with_server(e2e_test_server, setup_test_data):
    """Test integration flows with Python test server."""
    base_url = f"http://{e2e_test_server.config.host}:{e2e_test_server.config.port}"
    exit_code = run_playwright_tests(base_url, "test_integration_flows.spec.ts")
    assert exit_code == 0, "Integration flows E2E tests failed"
