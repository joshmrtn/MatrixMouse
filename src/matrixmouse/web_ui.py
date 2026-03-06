"""
matrixmouse/web_ui.py

Builds and returns the self-contained single-page web UI as an HTML string.

The UI assets live in the web/ subpackage as plain files:
    web/ui.html   — HTML skeleton with <!-- CSS --> and <!-- JS --> markers
    web/ui.css    — all styles
    web/ui.js     — all application JavaScript

build_html() reads these files at startup (once), inlines the CSS and JS
into the HTML, and returns the complete SPA. The result is cached so
subsequent requests serve the pre-built string directly.

To edit the UI:
    - Styles      → src/matrixmouse/web/ui.css
    - Behaviour   → src/matrixmouse/web/ui.js
    - Structure   → src/matrixmouse/web/ui.html

Do not add agent logic or Python state here.
"""

from pathlib import Path

_WEB_DIR = Path(__file__).parent / "web"
_CACHE: str | None = None


def build_html() -> str:
    """
    Return the complete single-page application as an HTML string.

    Reads web/ui.html, web/ui.css, and web/ui.js, inlines CSS and JS
    into the HTML template, and caches the result for the lifetime of
    the process.

    Returns:
        A complete, self-contained HTML document as a string.

    Raises:
        FileNotFoundError: If any of the required asset files are missing.
    """
    global _CACHE
    if _CACHE is not None:
        return _CACHE

    html = (_WEB_DIR / "ui.html").read_text(encoding="utf-8")
    css  = (_WEB_DIR / "ui.css" ).read_text(encoding="utf-8")
    js   = (_WEB_DIR / "ui.js"  ).read_text(encoding="utf-8")

    # Inline CSS and JS into the HTML template.
    # The markers are HTML comments inside <style> and <script> tags
    # so the template is valid HTML even before inlining.
    html = html.replace("<!-- CSS -->", css, 1)
    html = html.replace("<!-- JS -->",  js,  1)

    _CACHE = html
    return _CACHE


def invalidate_cache() -> None:
    """
    Clear the cached HTML so the next call to build_html() re-reads
    the asset files from disk.

    Useful in development when editing UI files without restarting the
    service. Not needed in production — assets don't change at runtime.
    """
    global _CACHE
    _CACHE = None
