"""
tests/test_web_ui.py

Tests for matrixmouse.web_ui.

build_html() returns a self-contained HTML string. These tests verify
structural correctness, presence of required elements, and that the
streaming token infrastructure is in place for future loop.py work.
"""

import pytest

from matrixmouse.web_ui import build_html


@pytest.fixture(scope="module")
def html():
    return build_html()


# ---------------------------------------------------------------------------
# Basic structure
# ---------------------------------------------------------------------------

class TestStructure:
    def test_returns_string(self, html):
        assert isinstance(html, str)
        assert len(html) > 1000

    def test_is_valid_html_document(self, html):
        assert "<!DOCTYPE html>" in html
        assert "<html" in html
        assert "</html>" in html

    def test_has_head_and_body(self, html):
        assert "<head>" in html
        assert "<body>" in html

    def test_title(self, html):
        assert "<title>MatrixMouse</title>" in html


# ---------------------------------------------------------------------------
# Header controls
# ---------------------------------------------------------------------------

class TestHeaderControls:
    def test_has_stop_button(self, html):
        assert 'id="btn-stop"' in html

    def test_has_kill_button(self, html):
        assert 'id="btn-kill"' in html

    def test_kill_button_labeled_estop(self, html):
        # E-STOP must be clearly labeled
        assert "E-STOP" in html

    def test_has_connection_indicator(self, html):
        assert 'id="conn-dot"' in html
        assert 'id="conn-label"' in html

    def test_status_fields_present(self, html):
        for field in ["v-task", "v-phase", "v-model", "v-turns", "v-status"]:
            assert f'id="{field}"' in html, f"Missing status field: {field}"


# ---------------------------------------------------------------------------
# E-STOP modal
# ---------------------------------------------------------------------------

class TestEstopModal:
    def test_modal_overlay_present(self, html):
        assert 'id="modal-overlay"' in html

    def test_modal_has_confirm_button(self, html):
        assert 'id="modal-confirm"' in html

    def test_modal_has_cancel_button(self, html):
        assert 'id="modal-cancel"' in html

    def test_modal_warns_about_inconsistent_state(self, html):
        assert "inconsistent" in html.lower() or "incomplete" in html.lower() \
            or "mid-task" in html.lower()

    def test_modal_mentions_systemctl(self, html):
        assert "systemctl" in html

    def test_confirm_calls_confirm_kill(self, html):
        assert "confirmKill()" in html


# ---------------------------------------------------------------------------
# Sidebar navigation
# ---------------------------------------------------------------------------

class TestSidebar:
    def test_sidebar_present(self, html):
        assert 'id="sidebar"' in html

    def test_workspace_channel_present(self, html):
        assert "workspace" in html.lower()

    def test_tasks_nav_item(self, html):
        assert "Tasks" in html

    def test_settings_nav_item(self, html):
        assert "Settings" in html

    def test_repo_injection_point(self, html):
        assert 'id="sb-repos"' in html


# ---------------------------------------------------------------------------
# Chat panel
# ---------------------------------------------------------------------------

class TestChatPanel:
    def test_log_element_present(self, html):
        assert 'id="log"' in html

    def test_clarification_banner_present(self, html):
        assert 'id="clarification"' in html

    def test_message_input_present(self, html):
        assert 'id="msg-input"' in html

    def test_send_button_present(self, html):
        assert 'id="send-btn"' in html


# ---------------------------------------------------------------------------
# Tasks panel
# ---------------------------------------------------------------------------

class TestTasksPanel:
    def test_tasks_panel_present(self, html):
        assert 'id="tasks-panel"' in html

    def test_tasks_list_element(self, html):
        assert 'id="tasks-list"' in html

    def test_add_task_form_present(self, html):
        assert 'id="add-task-form"' in html

    def test_add_task_button(self, html):
        assert 'id="btn-add-task"' in html

    def test_task_filter(self, html):
        assert 'id="task-filter-status"' in html


# ---------------------------------------------------------------------------
# Settings panel
# ---------------------------------------------------------------------------

class TestSettingsPanel:
    def test_settings_panel_present(self, html):
        assert 'id="settings-panel"' in html

    def test_settings_sidebar_present(self, html):
        assert 'id="settings-sidebar"' in html

    def test_model_settings_present(self, html):
        assert "coder_model" in html
        assert "planner_model" in html

    def test_thinking_controls_present(self, html):
        assert "coder_think" in html
        assert "planner_think" in html
        assert "judge_think" in html

    def test_repo_settings_injection_point(self, html):
        assert 'id="settings-repo-nav"' in html
        assert 'id="settings-repo-sections"' in html

    def test_save_bar_present(self, html):
        assert 'id="settings-save-bar"' in html


# ---------------------------------------------------------------------------
# Streaming prep — token event infrastructure
# ---------------------------------------------------------------------------

class TestStreamingPrep:
    def test_token_event_type_handled(self, html):
        """appendToken() function must exist for streaming support."""
        assert "appendToken" in html

    def test_token_css_class_present(self, html):
        """CSS class for token events must be defined."""
        assert ".ev.token" in html

    def test_token_event_in_websocket_handler(self, html):
        """WebSocket onmessage must branch on msg.type === 'token'."""
        assert "'token'" in html or '"token"' in html

    def test_streaming_row_accumulation(self, html):
        """streamingRow variable must exist for token accumulation."""
        assert "streamingRow" in html


# ---------------------------------------------------------------------------
# API integration — JS calls correct endpoints
# ---------------------------------------------------------------------------

class TestApiIntegration:
    def test_stop_posts_to_stop(self, html):
        assert "'/stop'" in html or '"/stop"' in html

    def test_kill_posts_to_kill(self, html):
        assert "'/kill'" in html or '"/kill"' in html

    def test_interject_posts_to_interject(self, html):
        assert "'/interject'" in html or '"/interject"' in html

    def test_tasks_fetches_tasks(self, html):
        assert "'/tasks'" in html or '"/tasks"' in html

    def test_config_fetches_config(self, html):
        assert "'/config'" in html or '"/config"' in html

    def test_websocket_uses_wss_for_https(self, html):
        assert "wss" in html
        assert "https:" in html
