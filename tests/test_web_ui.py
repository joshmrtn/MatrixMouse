"""
tests/test_web_ui.py

Tests for matrixmouse.web_ui and the web/ asset files.

The build is now file-based: web_ui.build_html() reads web/ui.html,
web/ui.css, and web/ui.js and inlines them. Tests verify the build
pipeline and the resulting SPA's structure.
"""

import pytest
from matrixmouse.web_ui import build_html, invalidate_cache


@pytest.fixture(autouse=True)
def clear_cache():
    """Ensure each test gets a fresh build."""
    invalidate_cache()
    yield
    invalidate_cache()


@pytest.fixture(scope="module")
def html():
    return build_html()


# ---------------------------------------------------------------------------
# Build pipeline
# ---------------------------------------------------------------------------

class TestBuildPipeline:
    def test_returns_string(self, html):
        assert isinstance(html, str) and len(html) > 5000

    def test_css_inlined(self, html):
        """The <!-- CSS --> marker should be replaced by actual CSS."""
        assert "<!-- CSS -->" not in html
        assert ":root" in html  # CSS variables present

    def test_js_inlined(self, html):
        """The <!-- JS --> marker should be replaced by actual JS."""
        assert "<!-- JS -->" not in html
        assert "function connect()" in html

    def test_cached(self):
        """Second call returns same object (cache hit)."""
        a = build_html()
        b = build_html()
        assert a is b

    def test_invalidate_cache(self):
        """invalidate_cache() causes a fresh build on next call."""
        a = build_html()
        invalidate_cache()
        b = build_html()
        assert a == b  # content identical, but was rebuilt


# ---------------------------------------------------------------------------
# HTML structure
# ---------------------------------------------------------------------------

class TestStructure:
    def test_doctype(self, html): assert "<!DOCTYPE html>" in html
    def test_viewport_meta(self, html): assert "viewport" in html
    def test_dvh(self, html): assert "100dvh" in html  # mobile fix
    def test_safe_area_inset(self, html): assert "safe-area-inset-bottom" in html
    def test_title(self, html): assert "<title>MatrixMouse</title>" in html
    def test_font_link(self, html): assert "fonts.googleapis.com" in html


# ---------------------------------------------------------------------------
# Header controls
# ---------------------------------------------------------------------------

class TestHeaderControls:
    def test_stop_button(self, html): assert 'id="btn-stop"' in html
    def test_kill_button(self, html): assert 'id="btn-kill"' in html
    def test_estop_label(self, html): assert "E-STOP" in html
    def test_conn_indicator(self, html):
        assert 'id="conn-dot"' in html and 'id="conn-label"' in html
    def test_status_fields(self, html):
        for fid in ["v-status", "v-task", "v-phase", "v-model", "v-turns"]:
            assert f'id="{fid}"' in html
    def test_hamburger_button(self, html):
        assert 'id="sidebar-toggle"' in html


# ---------------------------------------------------------------------------
# Mobile / responsive
# ---------------------------------------------------------------------------

class TestMobile:
    def test_responsive_breakpoint(self, html): assert "@media (max-width: 600px)" in html
    def test_sidebar_drawer(self, html): assert "sidebar-backdrop" in html
    def test_toggle_sidebar_fn(self, html): assert "toggleSidebar()" in html
    def test_close_sidebar_fn(self, html): assert "closeSidebar()" in html
    def test_ios_font_size(self, html):
        # Input must be >= 16px to prevent iOS zoom
        assert "font-size: 16px" in html


# ---------------------------------------------------------------------------
# Inference spinner
# ---------------------------------------------------------------------------

class TestInferenceBar:
    def test_inference_bar_present(self, html): assert 'id="inference-bar"' in html
    def test_set_inferring_fn(self, html): assert "setInferring(" in html
    def test_sidebar_spinner_class(self, html): assert "sb-spinner" in html
    def test_inferring_class(self, html): assert "inferring" in html


# ---------------------------------------------------------------------------
# E-STOP modal
# ---------------------------------------------------------------------------

class TestEstopModal:
    def test_modal_overlay(self, html): assert 'id="modal-overlay"' in html
    def test_confirm_button(self, html): assert 'id="modal-confirm"' in html
    def test_cancel_button(self, html): assert 'id="modal-cancel"' in html
    def test_inconsistent_state_warning(self, html):
        assert "inconsistent" in html.lower() or "mid-task" in html.lower()
    def test_systemctl_mentioned(self, html): assert "systemctl" in html
    def test_confirm_calls_js(self, html): assert "confirmKill()" in html


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

class TestSidebar:
    def test_sidebar_present(self, html): assert 'id="sidebar"' in html
    def test_channel_list(self, html): assert 'id="sb-channels"' in html
    def test_bottom_nav(self, html): assert 'id="sb-bottom"' in html
    def test_repo_injection(self, html): assert 'id="sb-repos"' in html
    def test_tasks_item(self, html): assert "Tasks" in html
    def test_settings_item(self, html): assert "Settings" in html


# ---------------------------------------------------------------------------
# Chat panel
# ---------------------------------------------------------------------------

class TestChatPanel:
    def test_log(self, html): assert 'id="log"' in html
    def test_clarification(self, html): assert 'id="clarification"' in html
    def test_msg_input(self, html): assert 'id="msg-input"' in html
    def test_send_btn(self, html): assert 'id="send-btn"' in html
    def test_enterkeyhint(self, html): assert 'enterkeyhint="send"' in html


# ---------------------------------------------------------------------------
# Context history
# ---------------------------------------------------------------------------

class TestContextHistory:
    def test_load_context_fn(self, html): assert "loadContext(" in html
    def test_historical_css_class(self, html): assert "historical" in html
    def test_context_summary_class(self, html): assert "context-summary" in html
    def test_context_separator(self, html): assert "live events follow" in html.lower()


# ---------------------------------------------------------------------------
# Tasks panel
# ---------------------------------------------------------------------------

class TestTasksPanel:
    def test_panel(self, html): assert 'id="tasks-panel"' in html
    def test_list(self, html): assert 'id="tasks-list"' in html
    def test_add_form(self, html): assert 'id="add-task-form"' in html
    def test_filter(self, html): assert 'id="task-filter-status"' in html


# ---------------------------------------------------------------------------
# Settings panel
# ---------------------------------------------------------------------------

class TestSettingsPanel:
    def test_panel(self, html): assert 'id="settings-panel"' in html
    def test_settings_sidebar(self, html): assert 'id="settings-sidebar"' in html
    def test_model_keys(self, html):
        assert "coder_model" in html and "manager_model" in html
    def test_thinking_keys(self, html):
        for key in ["coder_think", "manager_think", "critic_think"]:
            assert key in html
    def test_repo_nav_injection(self, html): assert 'id="settings-repo-nav"' in html
    def test_save_bar(self, html): assert 'id="settings-save-bar"' in html


# ---------------------------------------------------------------------------
# Streaming prep
# ---------------------------------------------------------------------------

class TestStreamingPrep:
    def test_append_token_fn(self, html): assert "appendToken(" in html
    def test_token_css(self, html): assert ".ev.token" in html
    def test_token_branch(self, html): assert "'token'" in html or '"token"' in html
    def test_streaming_row_var(self, html): assert "streamingRow" in html


# ---------------------------------------------------------------------------
# API integration
# ---------------------------------------------------------------------------

class TestApiIntegration:
    def test_stop_endpoint(self, html): assert "'/stop'" in html or '"/stop"' in html
    def test_kill_endpoint(self, html): assert "'/kill'" in html or '"/kill"' in html
    def test_interject_endpoint(self, html): assert "'/interject'" in html or '"/interject"' in html
    def test_context_endpoint(self, html): assert "'/context'" in html or '"/context"' in html
    def test_wss_for_https(self, html): assert "wss" in html and "https:" in html
