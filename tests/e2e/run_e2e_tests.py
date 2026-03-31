#!/usr/bin/env python3
"""
Run E2E tests with the Python test server.

This script:
1. Builds the frontend (if needed)
2. Starts the MatrixMouseTestServer
3. Runs Playwright tests against it
4. Cleans up

Usage:
    uv run python tests/e2e/run_e2e_tests.py
    uv run python tests/e2e/run_e2e_tests.py --test test_tasks_page.spec.ts
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from matrixmouse.test_server import MatrixMouseTestServer, MatrixMouseTestServerConfig


def build_frontend():
    """Build the frontend if dist doesn't exist."""
    frontend_root = Path(__file__).parent.parent.parent / "frontend"
    dist_dir = frontend_root / "dist"
    
    if not dist_dir.exists():
        print("Building frontend...")
        result = subprocess.run(
            ["npm", "run", "build"],
            cwd=frontend_root,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print(f"Frontend build failed:\n{result.stderr}")
            return False
        print("Frontend built successfully.")
    else:
        print("Frontend build already exists.")
    
    return True


def run_playwright_tests(base_url: str, test_file: str = None) -> int:
    """Run Playwright tests against the test server."""
    frontend_root = Path(__file__).parent.parent.parent / "frontend"
    
    cmd = [
        "npx", "playwright", "test",
        "--reporter=list",
        "--config=playwright.config.ts",
    ]
    
    if test_file:
        cmd.append(f"tests/e2e/{test_file}")
    
    env = dict(**subprocess.os.environ)
    env["PLAYWRIGHT_BASE_URL"] = base_url
    
    print(f"\nRunning Playwright tests against {base_url}")
    if test_file:
        print(f"Test file: {test_file}")
    print()
    
    result = subprocess.run(
        cmd,
        cwd=frontend_root,
        env=env,
        timeout=300,
    )
    
    return result.returncode


def main():
    parser = argparse.ArgumentParser(description="Run E2E tests with Python test server")
    parser.add_argument(
        "--test",
        help="Specific test file to run (e.g., test_tasks_page.spec.ts)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Port to run the test server on (default: 8765)",
    )
    parser.add_argument(
        "--no-build",
        action="store_true",
        help="Skip frontend build",
    )
    parser.add_argument(
        "--setup-data",
        action="store_true",
        help="Set up test data (repos, tasks)",
        default=True,
    )
    
    args = parser.parse_args()
    
    # Build frontend
    if not args.no_build and not build_frontend():
        sys.exit(1)
    
    # Create and start test server
    config = MatrixMouseTestServerConfig(
        port=args.port,
        host="127.0.0.1",
        llm_mode="echo",
    )
    
    server = MatrixMouseTestServer(config)
    
    try:
        print(f"\nStarting test server on port {args.port}...")
        server.start()
        print(f"Test server running at http://127.0.0.1:{args.port}")
        
        # Set up test data if requested
        if args.setup_data:
            print("\nSetting up test data...")
            setup_test_data(server)
            print("Test data ready.")
        
        print()
        
        # Run Playwright tests
        base_url = f"http://127.0.0.1:{args.port}"
        exit_code = run_playwright_tests(base_url, args.test)
        
        if exit_code == 0:
            print("\n✅ All E2E tests passed!")
        else:
            print(f"\n❌ E2E tests failed with exit code {exit_code}")
        
        sys.exit(exit_code)
        
    except KeyboardInterrupt:
        print("\n\nInterrupted by user.")
        sys.exit(130)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        print("\nStopping test server...")
        server.stop()
        print("Done.")


def setup_test_data(server):
    """Set up test data for E2E tests."""
    from matrixmouse.task import TaskStatus, AgentRole
    
    # Add test repos
    server.add_repo(
        name="main-repo",
        remote="https://github.com/test/main.git",
    )
    server.add_repo(
        name="test-repo",
        remote="https://github.com/test/test.git",
    )
    
    # Add test tasks
    server.add_task(
        title="High Priority Task",
        description="This is urgent",
        repo=["main-repo"],
        role=AgentRole.CODER,
        status=TaskStatus.READY,
        importance=0.9,
        urgency=0.9,
    )
    
    server.add_task(
        title="Running Task",
        description="Currently executing",
        repo=["main-repo"],
        role=AgentRole.CODER,
        status=TaskStatus.RUNNING,
    )
    
    server.add_task(
        title="Blocked by Human",
        description="Waiting for review",
        repo=["test-repo"],
        role=AgentRole.CRITIC,
        status=TaskStatus.BLOCKED_BY_HUMAN,
        notes="[BLOCKED] Awaiting review",
    )
    
    server.add_task(
        title="Completed Task",
        description="Already done",
        repo=["main-repo"],
        role=AgentRole.MANAGER,
        status=TaskStatus.COMPLETE,
    )
    
    server.add_task(
        title="Workspace Task",
        description="No repo assigned",
        repo=[],
        role=AgentRole.WRITER,
        status=TaskStatus.READY,
    )


if __name__ == "__main__":
    main()
