"""
tests/frontend/

Playwright E2E tests for the MatrixMouse frontend.

## Running Tests

```bash
# Install Playwright browsers
uv run playwright install chromium

# Run all frontend tests
uv run pytest tests/frontend/ -v

# Run specific test file
uv run pytest tests/frontend/test_interjection_routing.py -v

# Run with UI (headed mode for debugging)
uv run pytest tests/frontend/test_interjection_routing.py -v -s --headed

# Run with slow motion (for debugging)
uv run pytest tests/frontend/ -v --tracing=on
```

## Test Structure

- `mock_llm.py` - Fake LLM backend for deterministic testing
- `mock_server.py` - Mock FastAPI server with test control endpoints
- `conftest.py` - Pytest fixtures for Playwright and mock server
- `test_*.py` - Test files organized by feature

## Mock Server Test Endpoints

The mock server provides special `/test/*` endpoints for controlling test state:

- `POST /test/emit_event` - Emit arbitrary WebSocket event
- `POST /test/create_task` - Create task with specific properties
- `POST /test/set_status` - Set orchestrator status
- `POST /test/trigger_clarification` - Trigger clarification request
- `POST /test/trigger_decision` - Trigger decision modal
- `POST /test/reset` - Reset all test state

## Writing Tests

```python
from playwright.sync_api import Page, expect

def test_example(page_with_mock_server: Page, mock_server):
    page = page_with_mock_server
    
    # Create test data
    task = mock_server.task_repo.add(...)
    
    # Interact with UI
    page.click("#some-button")
    page.fill("#input", "text")
    
    # Assert
    expect(page.locator("#result")).to_contain_text("expected")
```

## Fixtures

- `page` - Playwright page instance
- `page_with_mock_server` - Page navigated to mock server
- `mock_server` - MockMatrixMouseServer instance
- `server_url` - Base URL of mock server
- `wait_for_ws` - Wait for WebSocket connection
- `sample_task_data` - Sample task dict
- `sample_blocked_task_data` - Sample blocked task dict
"""
