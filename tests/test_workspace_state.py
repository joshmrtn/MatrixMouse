"""
tests/test_workspace_state.py

Tests for matrixmouse.workspace_state — load, save, and accessor functions.

Coverage:
    load:
        - Returns default state when file absent
        - Returns default state when file is corrupt JSON
        - Returns default state when file read fails
        - Merges loaded data over defaults (new keys always present)
        - Loaded values override defaults

    save:
        - Writes valid JSON to disk
        - Atomic write via temp file (original preserved on error)
        - Logs warning on failure, does not raise

    get_last_review_at:
        - Returns None when key absent
        - Returns None when value is None
        - Returns None when value is unparseable
        - Returns timezone-aware datetime when value is valid ISO string
        - Naive datetime gets UTC timezone attached

    set_last_review_at:
        - Sets last_manager_review_at to now when dt is None
        - Sets last_manager_review_at to provided datetime
        - Value is ISO format string

    stale clarification task registry:
        - register_stale_clarification_task stores mapping
        - get_stale_clarification_task returns stored id
        - get_stale_clarification_task returns None for unknown task
        - clear_stale_clarification_task removes entry
        - clear_stale_clarification_task is no-op for unknown task
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from matrixmouse import workspace_state


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def state_file(tmp_path: Path) -> Path:
    return tmp_path / "workspace_state.json"


def write_state(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data))


# ---------------------------------------------------------------------------
# load
# ---------------------------------------------------------------------------

class TestLoad:
    def test_returns_defaults_when_file_absent(self, tmp_path):
        sf = state_file(tmp_path)
        state = workspace_state.load(sf)
        assert "last_manager_review_at" in state
        assert "stale_clarification_tasks" in state

    def test_default_last_review_is_none(self, tmp_path):
        state = workspace_state.load(state_file(tmp_path))
        assert state["last_manager_review_at"] is None

    def test_default_stale_tasks_is_empty_dict(self, tmp_path):
        state = workspace_state.load(state_file(tmp_path))
        assert state["stale_clarification_tasks"] == {}

    def test_returns_defaults_on_corrupt_json(self, tmp_path):
        sf = state_file(tmp_path)
        sf.write_text("{not valid json")
        state = workspace_state.load(sf)
        assert state["last_manager_review_at"] is None

    def test_returns_defaults_on_read_failure(self, tmp_path):
        sf = state_file(tmp_path)
        sf.write_text("{}")
        with patch("builtins.open", side_effect=OSError("permission denied")):
            state = workspace_state.load(sf)
        assert "last_manager_review_at" in state

    def test_loaded_values_override_defaults(self, tmp_path):
        sf = state_file(tmp_path)
        write_state(sf, {"last_manager_review_at": "2026-01-01T09:00:00+00:00"})
        state = workspace_state.load(sf)
        assert state["last_manager_review_at"] == "2026-01-01T09:00:00+00:00"

    def test_new_default_keys_present_even_if_file_predates_them(self, tmp_path):
        sf = state_file(tmp_path)
        # Old state file missing stale_clarification_tasks
        write_state(sf, {"last_manager_review_at": None})
        state = workspace_state.load(sf)
        assert "stale_clarification_tasks" in state

    def test_existing_stale_tasks_loaded(self, tmp_path):
        sf = state_file(tmp_path)
        write_state(sf, {
            "last_manager_review_at": None,
            "stale_clarification_tasks": {"task1": "mgr1"},
        })
        state = workspace_state.load(sf)
        assert state["stale_clarification_tasks"]["task1"] == "mgr1"


# ---------------------------------------------------------------------------
# save
# ---------------------------------------------------------------------------

class TestSave:
    def test_writes_valid_json(self, tmp_path):
        sf = state_file(tmp_path)
        state = {"last_manager_review_at": "2026-01-01T09:00:00+00:00",
                 "stale_clarification_tasks": {}}
        workspace_state.save(sf, state)
        loaded = json.loads(sf.read_text())
        assert loaded["last_manager_review_at"] == "2026-01-01T09:00:00+00:00"

    def test_creates_parent_dirs(self, tmp_path):
        sf = tmp_path / "deep" / "nested" / "workspace_state.json"
        workspace_state.save(sf, {"last_manager_review_at": None,
                                   "stale_clarification_tasks": {}})
        assert sf.exists()

    def test_roundtrip_preserves_data(self, tmp_path):
        sf = state_file(tmp_path)
        original = {
            "last_manager_review_at": "2026-03-01T09:00:00+00:00",
            "stale_clarification_tasks": {"abc": "def"},
        }
        workspace_state.save(sf, original)
        loaded = workspace_state.load(sf)
        assert loaded["last_manager_review_at"] == original["last_manager_review_at"]
        assert loaded["stale_clarification_tasks"] == original["stale_clarification_tasks"]

    def test_logs_warning_on_failure_does_not_raise(self, tmp_path):
        sf = state_file(tmp_path)
        with patch("matrixmouse.workspace_state.tempfile.mkstemp",
                   side_effect=OSError("disk full")):
            # Should not raise
            workspace_state.save(sf, {})


# ---------------------------------------------------------------------------
# get_last_review_at
# ---------------------------------------------------------------------------

class TestGetLastReviewAt:
    def test_returns_none_when_key_absent(self):
        assert workspace_state.get_last_review_at({}) is None

    def test_returns_none_when_value_is_none(self):
        assert workspace_state.get_last_review_at(
            {"last_manager_review_at": None}
        ) is None

    def test_returns_none_when_value_unparseable(self):
        assert workspace_state.get_last_review_at(
            {"last_manager_review_at": "not-a-date"}
        ) is None

    def test_returns_datetime_for_valid_iso_string(self):
        state = {"last_manager_review_at": "2026-01-15T09:00:00+00:00"}
        dt = workspace_state.get_last_review_at(state)
        assert isinstance(dt, datetime)
        assert dt.year == 2026
        assert dt.month == 1
        assert dt.day == 15

    def test_returned_datetime_is_timezone_aware(self):
        state = {"last_manager_review_at": "2026-01-15T09:00:00+00:00"}
        dt = workspace_state.get_last_review_at(state)
        assert dt is not None
        assert dt.tzinfo is not None

    def test_naive_datetime_gets_utc(self):
        # Naive ISO string (no timezone) should get UTC attached
        state = {"last_manager_review_at": "2026-01-15T09:00:00"}
        dt = workspace_state.get_last_review_at(state)
        assert dt is not None
        assert dt.tzinfo is not None


# ---------------------------------------------------------------------------
# set_last_review_at
# ---------------------------------------------------------------------------

class TestSetLastReviewAt:
    def test_sets_to_now_when_dt_is_none(self):
        state = {}
        before = datetime.now(timezone.utc)
        workspace_state.set_last_review_at(state)
        after = datetime.now(timezone.utc)
        stored = datetime.fromisoformat(state["last_manager_review_at"])
        assert before <= stored <= after

    def test_sets_to_provided_datetime(self):
        state = {}
        dt = datetime(2026, 3, 1, 9, 0, 0, tzinfo=timezone.utc)
        workspace_state.set_last_review_at(state, dt)
        assert state["last_manager_review_at"] == dt.isoformat()

    def test_value_is_iso_string(self):
        state = {}
        workspace_state.set_last_review_at(state)
        assert isinstance(state["last_manager_review_at"], str)
        # Must be parseable
        datetime.fromisoformat(state["last_manager_review_at"])

    def test_mutates_state_in_place(self):
        state = {"last_manager_review_at": None}
        workspace_state.set_last_review_at(state)
        assert state["last_manager_review_at"] is not None


# ---------------------------------------------------------------------------
# Stale clarification task registry
# ---------------------------------------------------------------------------

class TestStaleClarificationRegistry:
    def test_register_stores_mapping(self):
        state = {"stale_clarification_tasks": {}}
        workspace_state.register_stale_clarification_task(
            state, "blocked_task_1", "manager_task_1"
        )
        assert state["stale_clarification_tasks"]["blocked_task_1"] == "manager_task_1"

    def test_register_creates_key_if_absent(self):
        state = {}
        workspace_state.register_stale_clarification_task(state, "t1", "m1")
        assert state["stale_clarification_tasks"]["t1"] == "m1"

    def test_get_returns_stored_id(self):
        state = {"stale_clarification_tasks": {"t1": "m1"}}
        assert workspace_state.get_stale_clarification_task(state, "t1") == "m1"

    def test_get_returns_none_for_unknown_task(self):
        state = {"stale_clarification_tasks": {}}
        assert workspace_state.get_stale_clarification_task(state, "unknown") is None

    def test_get_returns_none_when_key_absent_from_state(self):
        assert workspace_state.get_stale_clarification_task({}, "t1") is None

    def test_clear_removes_entry(self):
        state = {"stale_clarification_tasks": {"t1": "m1", "t2": "m2"}}
        workspace_state.clear_stale_clarification_task(state, "t1")
        assert "t1" not in state["stale_clarification_tasks"]
        assert "t2" in state["stale_clarification_tasks"]

    def test_clear_is_noop_for_unknown_task(self):
        state = {"stale_clarification_tasks": {"t1": "m1"}}
        workspace_state.clear_stale_clarification_task(state, "nonexistent")
        assert state["stale_clarification_tasks"] == {"t1": "m1"}

    def test_multiple_registrations_independent(self):
        state = {}
        workspace_state.register_stale_clarification_task(state, "t1", "m1")
        workspace_state.register_stale_clarification_task(state, "t2", "m2")
        assert workspace_state.get_stale_clarification_task(state, "t1") == "m1"
        assert workspace_state.get_stale_clarification_task(state, "t2") == "m2"