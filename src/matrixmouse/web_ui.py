"""
matrixmouse/web_ui.py

Serves the MatrixMouse web UI.

The new TypeScript-based frontend is built from the frontend/ directory.
Run `npm run build` in frontend/ to generate built assets in frontend/dist/.

The built assets are copied to src/matrixmouse/web/ for serving.
"""

from pathlib import Path

_WEB_DIR = Path(__file__).parent / "web"
_CACHE: str | None = None


def build_html() -> str:
    """
    Return the complete single-page application as an HTML string.
    
    Reads the built index.html from the web directory.
    """
    global _CACHE
    if _CACHE is not None:
        return _CACHE

    index_file = _WEB_DIR / "index.html"
    if not index_file.exists():
        # Return placeholder if build hasn't been run
        return _placeholder_html()

    _CACHE = index_file.read_text(encoding="utf-8")
    return _CACHE


def _placeholder_html() -> str:
    """Return placeholder HTML while frontend is being built."""
    return """
    <!DOCTYPE html>
    <html>
    <head><title>MatrixMouse - Frontend Under Construction</title></head>
    <body style="background:#0a0a0a;color:#c8c8c8;font-family:monospace;padding:40px;">
        <h1>🐭 MatrixMouse</h1>
        <p>New TypeScript frontend is under construction.</p>
        <p>Run <code>npm run build</code> in the <code>frontend/</code> directory.</p>
    </body>
    </html>
    """


def invalidate_cache() -> None:
    """Clear the cached HTML."""
    global _CACHE
    _CACHE = None
