# MatrixMouse Frontend Testing Infrastructure

## Overview

This directory contains the testing infrastructure for the MatrixMouse frontend, including:
- Mock LLM backend for deterministic testing
- Mock FastAPI server with test control endpoints
- Playwright E2E test fixtures and examples
- Comprehensive test suites for critical frontend functionality

## Architecture

```
tests/frontend/
├── __init__.py           # Package documentation
├── conftest.py           # Pytest fixtures
├── mock_llm.py           # Fake LLM backend
├── mock_server.py        # Mock FastAPI server
├── test_interjection_routing.py  # Interjection routing tests
├── test_status_dashboard.py      # Status dashboard tests
└── test_decision_modals.py       # Decision modal tests
```

## Current Status

### ✅ Completed
1. **Mock LLM Backend** (`mock_llm.py`)
   - `FakeLLMBackend` - Returns predefined responses
   - `FakeLLMBackendWithErrors` - Simulates API errors
   - Call history tracking for verification

2. **Mock Server** (`mock_server.py`)
   - Full MatrixMouse API endpoint mocks
   - Test control endpoints (`/test/*`)
   - WebSocket event emission
   - In-memory task repository

3. **Pytest Fixtures** (`conftest.py`)
   - Playwright browser/page fixtures
   - Mock server lifecycle management
   - Test data factories
   - WebSocket connection waiting

4. **Test Suites**
   - Interjection routing tests
   - Status dashboard tests
   - Decision modal tests

### ⚠️ Needs Configuration
The E2E tests currently need the actual frontend to be served. Options:

**Option A: Serve frontend from mock server**
```python
# In mock_server.py, add static file serving
from fastapi.staticfiles import StaticFiles
app.mount("/", StaticFiles(directory="src/matrixmouse/web", html=True), name="static")
```

**Option B: Test against real server**
```bash
# Start real server with mocked backend
uv run matrixmouse-service --mock-llm
# Run tests against localhost:8080
```

## Running Tests

### Prerequisites
```bash
# Install Playwright browsers
uv run playwright install chromium

# Install system dependencies (if needed)
sudo apt-get install libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libxkbcommon0 libatspi2.0-0 libxcomposite1 libxdamage1 \
    libxfixes3 libxrandr2 libgbm1 libasound2
```

### Run All Tests
```bash
uv run pytest tests/frontend/ -v
```

### Run Specific Test File
```bash
uv run pytest tests/frontend/test_interjection_routing.py -v
```

### Run with Headed Mode (for debugging)
```bash
uv run pytest tests/frontend/test_status_dashboard.py -v --headed
```

### Run with Tracing (for debugging)
```bash
uv run pytest tests/frontend/ -v --tracing=on
# After test fails, open trace:
uv run playwright show-trace trace.zip
```

## Writing New Tests

### Basic Test Structure
```python
import pytest
from playwright.sync_api import Page, expect
from .mock_server import MockMatrixMouseServer

def test_example(page_with_mock_server: Page, mock_server: MockMatrixMouseServer):
    page = page_with_mock_server
    
    # Arrange: Create test data
    task = mock_server.task_repo.add(Task(...))
    
    # Act: Interact with UI
    page.click("#some-button")
    page.fill("#input", "text")
    
    # Assert: Verify results
    expect(page.locator("#result")).to_contain_text("expected")
```

### Using Test Control Endpoints
```python
# Emit WebSocket event
mock_server._emit_event("clarification_request", {
    "question": "What is your approach?",
})

# Create task with specific properties
response = page.request.post("/test/create_task", data={
    "title": "Blocked Task",
    "status": "blocked_by_human",
    "blocking_reason": "Needs approval",
})

# Set orchestrator status
page.request.post("/test/set_status", data={
    "blocked": True,
    "task": "test-task",
})
```

### Testing WebSocket Events
```python
def test_websocket_event(page_with_mock_server: Page, wait_for_ws):
    page = page_with_mock_server
    
    # Wait for WebSocket connection
    wait_for_ws  # Fixture waits for green connection dot
    
    # Trigger event from server
    mock_server._emit_event("status_update", {"data": {"blocked": True}})
    
    # Verify UI updated
    expect(page.locator("#v-status")).to_have_text("BLOCKED")
```

## Mock Server API Reference

### Test Control Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/test/emit_event` | POST | Emit arbitrary WebSocket event |
| `/test/create_task` | POST | Create task with specific properties |
| `/test/set_status` | POST | Set orchestrator status |
| `/test/trigger_clarification` | POST | Trigger clarification request |
| `/test/trigger_decision` | POST | Trigger decision modal |
| `/test/reset` | POST | Reset all test state |

### Example Usage
```python
# Create a blocked task
page.request.post("/test/create_task", json={
    "title": "Needs Approval",
    "status": "blocked_by_human",
    "blocking_reason": "Choose approach A or B",
    "repo": ["test-repo"],
})

# Trigger decision modal
page.request.post("/test/trigger_decision", json={
    "task_id": "abc123",
    "decision_type": "pr_approval_required",
    "message": "Approve this PR?",
    "choices": [
        {"label": "Approve", "value": "approve"},
        {"label": "Reject", "value": "reject"},
    ],
})
```

## Next Steps

1. **Configure frontend serving** - Choose Option A or B above
2. **Add more test coverage**:
   - Task tree sidebar tests
   - Task conversation panel tests
   - Settings panel tests
   - Mobile responsive tests
3. **Add visual regression tests** with Playwright screenshots
4. **Add accessibility tests** with axe-core integration
5. **CI/CD integration** - Run tests on every PR

## Troubleshooting

### Tests timeout waiting for element
- Increase timeout: `page.set_default_timeout(30000)`
- Check if element exists: `page.locator("#id").count()`
- Use debug mode: `--headed --slowmo=1000`

### WebSocket not connecting
- Verify mock server is started
- Check `wait_for_ws` fixture is used
- Look for console errors: `page.on("console", lambda msg: print(msg.text))`

### Mock server port in use
- Change port: `MockMatrixMouseServer(port=8766)`
- Kill existing process: `lsof -ti:8765 | xargs kill`
