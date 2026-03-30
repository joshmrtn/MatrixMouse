"""
matrixmouse/web/build_frontend.py

Build script for the MatrixMouse frontend.
Bundles TypeScript into a single HTML file.
"""

import subprocess
import sys
from pathlib import Path


def main():
    """Build the frontend from TypeScript sources."""
    frontend_dir = Path(__file__).parent.parent.parent / "frontend"
    
    if not frontend_dir.exists():
        print(f"Error: Frontend directory not found at {frontend_dir}")
        sys.exit(1)
    
    # Run esbuild via npx
    build_script = frontend_dir / "build.ts"
    
    try:
        # Install dependencies if needed
        print("Installing frontend build dependencies...")
        subprocess.run(
            ["uv", "run", "--with", "esbuild", "npx", "esbuild", "--version"],
            cwd=frontend_dir,
            check=True,
            capture_output=True,
        )
        
        # Run the build
        print("Building frontend...")
        result = subprocess.run(
            ["uv", "run", "--with", "esbuild", "npx", "ts-node", str(build_script)],
            cwd=frontend_dir,
            check=True,
            capture_output=True,
            text=True,
        )
        
        print(result.stdout)
        if result.stderr:
            print(result.stderr, file=sys.stderr)
        
        print("✓ Frontend build complete!")
        
    except subprocess.CalledProcessError as e:
        print(f"Build failed: {e}", file=sys.stderr)
        if e.stderr:
            print(e.stderr.decode() if isinstance(e.stderr, bytes) else e.stderr, file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError:
        print("Error: esbuild or ts-node not found. Install with: uv add --dev esbuild", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
