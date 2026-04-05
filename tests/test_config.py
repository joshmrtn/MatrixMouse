"""
tests/test_config.py

Tests for matrixmouse.config — MatrixMouseConfig field defaults and access.

Tests here verify that config keys exist, have the correct default values,
and are accessible as direct attributes. This catches typos in field names
and ensures defaults match documented behaviour.

New keys are added here whenever a config field is introduced.
"""

from pathlib import Path

import pytest

from matrixmouse.config import MatrixMouseConfig, MatrixMousePaths, load_config


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
    def test_writer_cascade_accessible(self):
        cfg = make_config()
        _ = cfg.writer_cascade

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
# Branch Management
# ---------------------------------------------------------------------------

class TestBranchManagement:
    def test_agent_branch_prefix_default(self):
        assert make_config().agent_branch_prefix == "mm"

    def test_protected_branches_default(self):
        config = make_config()
        assert "main" in config.protected_branches
        assert "master" in config.protected_branches

    def test_merge_conflict_max_turns_default(self):
        assert make_config().merge_conflict_max_turns == 5

    def test_merge_resolution_cascade_default_empty(self):
        assert make_config().merge_resolution_cascade == []

    def test_push_wip_to_remote_default_false(self):
        assert make_config().push_wip_to_remote is False

    def test_branch_protection_cache_ttl_default(self):
        assert make_config().branch_protection_cache_ttl_minutes == 60

    def test_pr_poll_interval_default(self):
        assert make_config().pr_poll_interval_minutes == 10

    def test_manager_planning_max_turns_default(self):
        assert make_config().manager_planning_max_turns == 10

    def test_agent_branch_prefix_configurable(self, tmp_path):
        config_file = tmp_path / ".matrixmouse" / "config.toml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text('agent_branch_prefix = "bot"\n')
        config = load_config(repo_root=None, workspace_root=tmp_path)
        assert config.agent_branch_prefix == "bot"

    def test_protected_branches_configurable(self, tmp_path):
        config_file = tmp_path / ".matrixmouse" / "config.toml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text('protected_branches = ["main", "production"]\n')
        config = load_config(repo_root=None, workspace_root=tmp_path)
        assert "production" in config.protected_branches
        assert config.protected_branches == ["main", "production"]

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


# ---------------------------------------------------------------------------
# Cascade config — Issue #32
# ---------------------------------------------------------------------------

class TestCascadeConfig:
    """All six role cascade fields exist and default to empty lists."""

    def test_cascade_fields_present(self):
        cfg = make_config()
        assert cfg.manager_cascade == []
        assert cfg.critic_cascade == []
        assert cfg.writer_cascade == []
        assert cfg.coder_cascade == []
        assert cfg.merge_resolution_cascade == []
        assert cfg.summarizer_cascade == []

    def test_cooldown_fields_present(self):
        cfg = make_config()
        assert cfg.backend_cooldown_initial_seconds == 30
        assert cfg.backend_cooldown_max_seconds == 600

    def test_legacy_model_keys_removed(self):
        """Old single-model keys should no longer be attributes."""
        cfg = make_config()
        for key in (
            "manager_model", "critic_model", "writer_model",
            "coder_model", "merge_resolution_model", "summarizer_model",
        ):
            with pytest.raises(AttributeError):
                getattr(cfg, key)

    def test_config_loads_cascade_from_toml(self, tmp_path):
        toml_content = (
            'manager_cascade = ["anthropic:claude-sonnet-4-5"]\n'
            'coder_cascade = ["ollama:qwen3:4b", "ollama:qwen3:9b"]\n'
            'summarizer_cascade = ["ollama:qwen3:4b"]\n'
            'backend_cooldown_initial_seconds = 60\n'
            'backend_cooldown_max_seconds = 300\n'
        )
        config_file = tmp_path / ".matrixmouse" / "config.toml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text(toml_content)
        cfg = load_config(repo_root=None, workspace_root=tmp_path)
        assert cfg.manager_cascade == ["anthropic:claude-sonnet-4-5"]
        assert cfg.coder_cascade == ["ollama:qwen3:4b", "ollama:qwen3:9b"]
        assert cfg.summarizer_cascade == ["ollama:qwen3:4b"]
        assert cfg.backend_cooldown_initial_seconds == 60
        assert cfg.backend_cooldown_max_seconds == 300
