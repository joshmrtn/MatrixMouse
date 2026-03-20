"""
tests/test_config.py

Tests for matrixmouse.config — MatrixMouseConfig field defaults and access.

Tests here verify that config keys exist, have the correct default values,
and are accessible as direct attributes. This catches typos in field names
and ensures defaults match documented behaviour.

New keys are added here whenever a config field is introduced.
"""

from matrixmouse.config import MatrixMouseConfig, MatrixMousePaths
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_config(**kwargs) -> MatrixMouseConfig:
    return MatrixMouseConfig(**kwargs)


# ---------------------------------------------------------------------------
# Clarification
# ---------------------------------------------------------------------------

class TestClarificationConfig:
    def test_clarification_grace_period_default(self):
        assert make_config().clarification_grace_period_minutes == 10

    def test_clarification_grace_period_accessible(self):
        cfg = make_config()
        _ = cfg.clarification_grace_period_minutes

    def test_clarification_timeout_minutes_default(self):
        assert make_config().clarification_timeout_minutes == 60

    def test_clarification_timeout_minutes_accessible(self):
        cfg = make_config()
        _ = cfg.clarification_timeout_minutes


# ---------------------------------------------------------------------------
# Manager review schedule
# ---------------------------------------------------------------------------

class TestManagerReviewConfig:
    def test_manager_review_schedule_default(self):
        assert make_config().manager_review_schedule == "0 9 * * *"

    def test_manager_review_schedule_accessible(self):
        cfg = make_config()
        _ = cfg.manager_review_schedule

    def test_manager_review_upcoming_tasks_default(self):
        assert make_config().manager_review_upcoming_tasks == 20

    def test_manager_review_upcoming_tasks_accessible(self):
        cfg = make_config()
        _ = cfg.manager_review_upcoming_tasks


# ---------------------------------------------------------------------------
# Agent turn limits
# ---------------------------------------------------------------------------

class TestTurnLimitConfig:
    def test_agent_max_turns_default(self):
        assert make_config().agent_max_turns == 50

    def test_agent_max_turns_accessible(self):
        cfg = make_config()
        _ = cfg.agent_max_turns

    def test_critic_max_turns_default(self):
        assert make_config().critic_max_turns == 5

    def test_critic_max_turns_accessible(self):
        cfg = make_config()
        _ = cfg.critic_max_turns


# ---------------------------------------------------------------------------
# Writer model
# ---------------------------------------------------------------------------

class TestWriterModelConfig:
    def test_writer_model_accessible(self):
        cfg = make_config()
        _ = cfg.writer_model

    def test_writer_stream_accessible(self):
        cfg = make_config()
        _ = cfg.writer_stream

    def test_writer_think_accessible(self):
        cfg = make_config()
        _ = cfg.writer_think


# ---------------------------------------------------------------------------
# Priority scoring
# ---------------------------------------------------------------------------

class TestPriorityConfig:
    def test_aging_rate_accessible(self):
        cfg = make_config()
        _ = cfg.priority_aging_rate

    def test_max_aging_bonus_accessible(self):
        cfg = make_config()
        _ = cfg.priority_max_aging_bonus

    def test_importance_weight_accessible(self):
        cfg = make_config()
        _ = cfg.priority_importance_weight

    def test_urgency_weight_accessible(self):
        cfg = make_config()
        _ = cfg.priority_urgency_weight


# ---------------------------------------------------------------------------
# MatrixMousePaths
# ---------------------------------------------------------------------------

class TestMatrixMousePaths:
    def test_db_file_property(self, tmp_path):
        paths = MatrixMousePaths(workspace_root=tmp_path)
        expected = tmp_path / ".matrixmouse" / "matrixmouse.db"
        assert paths.db_file == expected
        
    def test_db_file_is_path(self, tmp_path):
        paths = MatrixMousePaths(workspace_root=tmp_path)
        assert isinstance(paths.db_file, Path)

    def test_mm_dir_property(self, tmp_path):
        paths = MatrixMousePaths(workspace_root=tmp_path)
        assert paths.mm_dir == tmp_path / ".matrixmouse"
