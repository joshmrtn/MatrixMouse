"""
tests/test_main.py

Tests for the MatrixMouse CLI (main.py).

These tests verify that CLI commands parse arguments correctly and attempt
to call the expected API endpoints. HTTP requests are mocked to avoid
actual network calls.
"""

import json
import sys
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from matrixmouse.main import (
    build_parser,
    cmd_add_repo,
    cmd_repos_list,
    cmd_repos_remove,
    cmd_tasks_list,
    cmd_tasks_show,
    cmd_tasks_add,
    cmd_tasks_edit,
    cmd_tasks_cancel,
    cmd_tasks_answer,
    cmd_tasks_decision,
    cmd_interject_workspace,
    cmd_interject_repo,
    cmd_interject_task,
    cmd_answer,
    cmd_status,
    cmd_stop,
    cmd_kill,
    cmd_estop_status,
    cmd_estop_reset,
    cmd_pause,
    cmd_resume,
    cmd_blocked,
    cmd_token_usage,
    cmd_context,
    cmd_health,
    cmd_config_get,
    cmd_config_set,
    cmd_decisions_list,
    DECISION_TYPES,
)


class TestArgumentParser(unittest.TestCase):
    """Test that the argument parser accepts all documented commands."""

    def setUp(self):
        self.parser = build_parser()

    def test_no_command_shows_help(self):
        """Running without arguments should print help."""
        args = self.parser.parse_args([])
        self.assertIsNone(args.command)

    def test_add_repo_command(self):
        """Test add-repo command parsing."""
        args = self.parser.parse_args(["add-repo", "https://github.com/user/repo.git"])
        self.assertEqual(args.command, "add-repo")
        self.assertEqual(args.remote, "https://github.com/user/repo.git")
        self.assertIsNone(args.name)

    def test_add_repo_with_name(self):
        """Test add-repo with custom name."""
        args = self.parser.parse_args([
            "add-repo", "https://github.com/user/repo.git",
            "--name", "my-repo"
        ])
        self.assertEqual(args.name, "my-repo")

    def test_repos_list_command(self):
        """Test repos list command parsing."""
        args = self.parser.parse_args(["repos", "list"])
        self.assertEqual(args.command, "repos")
        self.assertEqual(args.repos_command, "list")

    def test_repos_list_with_format(self):
        """Test repos list with format option."""
        args = self.parser.parse_args(["repos", "list", "--format", "json"])
        self.assertEqual(args.format, "json")

    def test_repos_remove_command(self):
        """Test repos remove command parsing."""
        args = self.parser.parse_args(["repos", "remove", "my-repo"])
        self.assertEqual(args.command, "repos")
        self.assertEqual(args.repos_command, "remove")
        self.assertEqual(args.name, "my-repo")
        self.assertFalse(args.yes)

    def test_repos_remove_with_yes_flag(self):
        """Test repos remove with --yes flag."""
        args = self.parser.parse_args(["repos", "remove", "my-repo", "--yes"])
        self.assertTrue(args.yes)

    def test_tasks_list_command(self):
        """Test tasks list command parsing."""
        args = self.parser.parse_args(["tasks", "list"])
        self.assertEqual(args.command, "tasks")
        self.assertEqual(args.tasks_subcmd, "list")

    def test_tasks_list_with_filters(self):
        """Test tasks list with filters."""
        args = self.parser.parse_args([
            "tasks", "list",
            "--status", "blocked",
            "--repo", "my-repo",
            "--all"
        ])
        self.assertEqual(args.status, "blocked")
        self.assertEqual(args.repo, "my-repo")
        self.assertTrue(args.all)

    def test_tasks_list_with_format(self):
        """Test tasks list with format option."""
        args = self.parser.parse_args(["tasks", "list", "--format", "json"])
        self.assertEqual(args.format, "json")

    def test_tasks_show_command(self):
        """Test tasks show command parsing."""
        args = self.parser.parse_args(["tasks", "show", "abc123"])
        self.assertEqual(args.tasks_subcmd, "show")
        self.assertEqual(args.id, "abc123")

    def test_tasks_add_non_interactive(self):
        """Test tasks add with non-interactive flags."""
        args = self.parser.parse_args([
            "tasks", "add",
            "--title", "Fix bug",
            "--description", "Description here",
            "--repo", "my-repo",
            "--importance", "0.8",
            "--urgency", "0.6"
        ])
        self.assertEqual(args.tasks_subcmd, "add")
        self.assertEqual(args.title, "Fix bug")
        self.assertEqual(args.description, "Description here")
        self.assertEqual(args.repo, "my-repo")
        self.assertEqual(args.importance, 0.8)
        self.assertEqual(args.urgency, 0.6)

    def test_tasks_add_with_target_files(self):
        """Test tasks add with target files."""
        args = self.parser.parse_args([
            "tasks", "add",
            "--title", "Update API",
            "--target-files", "file1.py,file2.py"
        ])
        self.assertEqual(args.target_files, "file1.py,file2.py")

    def test_tasks_add_description_from_stdin(self):
        """Test tasks add with @- for stdin description."""
        args = self.parser.parse_args([
            "tasks", "add",
            "--title", "Test",
            "--description", "@-"
        ])
        self.assertEqual(args.description, "@-")

    def test_tasks_add_description_from_file(self):
        """Test tasks add with @file for file description."""
        args = self.parser.parse_args([
            "tasks", "add",
            "--title", "Test",
            "--description", "@/path/to/file.txt"
        ])
        self.assertEqual(args.description, "@/path/to/file.txt")

    def test_tasks_edit_command(self):
        """Test tasks edit command parsing."""
        args = self.parser.parse_args(["tasks", "edit", "abc123"])
        self.assertEqual(args.tasks_subcmd, "edit")
        self.assertEqual(args.id, "abc123")

    def test_tasks_edit_with_flags(self):
        """Test tasks edit with non-interactive flags."""
        args = self.parser.parse_args([
            "tasks", "edit", "abc123",
            "--title", "New title",
            "--importance", "0.9"
        ])
        self.assertEqual(args.title, "New title")
        self.assertEqual(args.importance, 0.9)

    def test_tasks_edit_with_description_from_stdin(self):
        """Test tasks edit with @- for stdin description."""
        args = self.parser.parse_args([
            "tasks", "edit", "abc123",
            "--description", "@-"
        ])
        self.assertEqual(args.description, "@-")

    def test_tasks_cancel_command(self):
        """Test tasks cancel command parsing."""
        args = self.parser.parse_args(["tasks", "cancel", "abc123"])
        self.assertEqual(args.tasks_subcmd, "cancel")
        self.assertEqual(args.id, "abc123")
        self.assertFalse(args.yes)

    def test_tasks_cancel_with_yes(self):
        """Test tasks cancel with --yes flag."""
        args = self.parser.parse_args(["tasks", "cancel", "abc123", "--yes"])
        self.assertTrue(args.yes)

    def test_tasks_answer_command(self):
        """Test tasks answer command parsing."""
        args = self.parser.parse_args(["tasks", "answer", "abc123"])
        self.assertEqual(args.tasks_subcmd, "answer")
        self.assertEqual(args.task_id, "abc123")
        self.assertIsNone(args.message)

    def test_tasks_answer_with_message(self):
        """Test tasks answer with non-interactive message."""
        args = self.parser.parse_args([
            "tasks", "answer", "abc123",
            "--message", "Use the staging database"
        ])
        self.assertEqual(args.message, "Use the staging database")

    def test_tasks_decision_command(self):
        """Test tasks decision command parsing."""
        args = self.parser.parse_args([
            "tasks", "decision", "abc123",
            "pr_approval_required", "approve"
        ])
        self.assertEqual(args.tasks_subcmd, "decision")
        self.assertEqual(args.task_id, "abc123")
        self.assertEqual(args.decision_type, "pr_approval_required")
        self.assertEqual(args.choice, "approve")

    def test_tasks_decision_with_note(self):
        """Test tasks decision with note."""
        args = self.parser.parse_args([
            "tasks", "decision", "abc123",
            "pr_approval_required", "approve",
            "--note", "Looks good"
        ])
        self.assertEqual(args.note, "Looks good")

    def test_tasks_decision_with_extend_by(self):
        """Test tasks decision with extend-by for turn_limit_reached."""
        args = self.parser.parse_args([
            "tasks", "decision", "abc123",
            "turn_limit_reached", "extend",
            "--extend-by", "20"
        ])
        self.assertEqual(args.extend_by, 20)

    def test_decisions_list_command(self):
        """Test decisions list command parsing."""
        args = self.parser.parse_args(["decisions", "list"])
        self.assertEqual(args.command, "decisions")
        self.assertEqual(args.decisions_command, "list")

    def test_decisions_list_with_format(self):
        """Test decisions list with format option."""
        args = self.parser.parse_args(["decisions", "list", "--format", "json"])
        self.assertEqual(args.format, "json")

    def test_interject_workspace_command(self):
        """Test interject workspace command parsing."""
        args = self.parser.parse_args([
            "interject", "workspace", "Please prioritize security"
        ])
        self.assertEqual(args.command, "interject")
        self.assertEqual(args.interject_command, "workspace")
        self.assertEqual(args.message, "Please prioritize security")

    def test_interject_repo_command(self):
        """Test interject repo command parsing."""
        args = self.parser.parse_args([
            "interject", "repo", "my-repo", "Focus on auth module"
        ])
        self.assertEqual(args.interject_command, "repo")
        self.assertEqual(args.repo, "my-repo")
        self.assertEqual(args.message, "Focus on auth module")

    def test_interject_task_command(self):
        """Test interject task command parsing."""
        args = self.parser.parse_args([
            "interject", "task", "abc123", "Consider caching"
        ])
        self.assertEqual(args.interject_command, "task")
        self.assertEqual(args.task_id, "abc123")
        self.assertEqual(args.message, "Consider caching")

    def test_answer_legacy_command(self):
        """Test legacy answer command parsing."""
        args = self.parser.parse_args(["answer"])
        self.assertEqual(args.command, "answer")
        self.assertIsNone(args.message)

    def test_answer_legacy_with_message(self):
        """Test legacy answer with non-interactive message."""
        args = self.parser.parse_args([
            "answer", "--message", "Proceed with refactoring"
        ])
        self.assertEqual(args.message, "Proceed with refactoring")

    def test_status_command(self):
        """Test status command parsing."""
        args = self.parser.parse_args(["status"])
        self.assertEqual(args.command, "status")

    def test_stop_command(self):
        """Test stop command parsing."""
        args = self.parser.parse_args(["stop"])
        self.assertEqual(args.command, "stop")

    def test_kill_command(self):
        """Test kill command parsing."""
        args = self.parser.parse_args(["kill"])
        self.assertEqual(args.command, "kill")
        self.assertFalse(args.yes)

    def test_kill_with_yes(self):
        """Test kill with --yes flag."""
        args = self.parser.parse_args(["kill", "--yes"])
        self.assertTrue(args.yes)

    def test_estop_status_command(self):
        """Test estop status command parsing."""
        args = self.parser.parse_args(["estop", "status"])
        self.assertEqual(args.command, "estop")
        self.assertEqual(args.estop_subcmd, "status")

    def test_estop_reset_command(self):
        """Test estop reset command parsing."""
        args = self.parser.parse_args(["estop", "reset"])
        self.assertEqual(args.command, "estop")
        self.assertEqual(args.estop_subcmd, "reset")

    def test_pause_command(self):
        """Test pause command parsing."""
        args = self.parser.parse_args(["pause"])
        self.assertEqual(args.command, "pause")

    def test_resume_command(self):
        """Test resume command parsing."""
        args = self.parser.parse_args(["resume"])
        self.assertEqual(args.command, "resume")

    def test_blocked_command(self):
        """Test blocked command parsing."""
        args = self.parser.parse_args(["blocked"])
        self.assertEqual(args.command, "blocked")

    def test_blocked_with_format(self):
        """Test blocked with format option."""
        args = self.parser.parse_args(["blocked", "--format", "json"])
        self.assertEqual(args.format, "json")

    def test_token_usage_command(self):
        """Test token-usage command parsing."""
        args = self.parser.parse_args(["token-usage"])
        self.assertEqual(args.command, "token-usage")

    def test_token_usage_with_format(self):
        """Test token-usage with format option."""
        args = self.parser.parse_args(["token-usage", "--format", "json"])
        self.assertEqual(args.format, "json")

    def test_tasks_context_command(self):
        """Test tasks context command parsing."""
        args = self.parser.parse_args(["tasks", "context", "abc123"])
        self.assertEqual(args.tasks_subcmd, "context")
        self.assertEqual(args.id, "abc123")

    def test_tasks_context_with_last(self):
        """Test tasks context with --last option."""
        args = self.parser.parse_args(["tasks", "context", "abc123", "--last", "20"])
        self.assertEqual(args.last, 20)

    def test_tasks_context_with_all(self):
        """Test tasks context with --all option."""
        args = self.parser.parse_args(["tasks", "context", "abc123", "--all"])
        self.assertTrue(args.all)

    def test_tasks_context_with_format(self):
        """Test tasks context with format option."""
        args = self.parser.parse_args(["tasks", "context", "abc123", "--format", "json"])
        self.assertEqual(args.format, "json")

    def test_health_command(self):
        """Test health command parsing."""
        args = self.parser.parse_args(["health"])
        self.assertEqual(args.command, "health")

    def test_config_get_command(self):
        """Test config get command parsing."""
        args = self.parser.parse_args(["config", "get"])
        self.assertEqual(args.command, "config")
        self.assertEqual(args.config_subcmd, "get")

    def test_config_get_specific_key(self):
        """Test config get with specific key."""
        args = self.parser.parse_args(["config", "get", "coder_model"])
        self.assertEqual(args.key, "coder_model")

    def test_config_get_with_repo(self):
        """Test config get with repo scope."""
        args = self.parser.parse_args(["config", "get", "--repo", "my-repo"])
        self.assertEqual(args.repo, "my-repo")

    def test_config_set_command(self):
        """Test config set command parsing."""
        args = self.parser.parse_args([
            "config", "set", "coder_model", "ollama:qwen3.5:9b"
        ])
        self.assertEqual(args.command, "config")
        self.assertEqual(args.config_subcmd, "set")
        self.assertEqual(args.key, "coder_model")
        self.assertEqual(args.value, "ollama:qwen3.5:9b")

    def test_config_set_with_repo(self):
        """Test config set with repo scope."""
        args = self.parser.parse_args([
            "config", "set", "coder_model", "ollama:qwen3.5:9b",
            "--repo", "my-repo"
        ])
        self.assertEqual(args.repo, "my-repo")

    def test_config_set_with_commit(self):
        """Test config set with --commit flag."""
        args = self.parser.parse_args([
            "config", "set", "coder_model", "ollama:qwen3.5:9b",
            "--repo", "my-repo", "--commit"
        ])
        self.assertTrue(args.commit)


class TestDecisionsList(unittest.TestCase):
    """Test the DECISION_TYPES constant and cmd_decisions_list."""

    def test_decision_types_defined(self):
        """Test that all expected decision types are defined."""
        expected_types = [
            "pr_approval_required",
            "pr_rejection",
            "turn_limit_reached",
            "critic_turn_limit_reached",
            "merge_conflict_resolution_turn_limit_reached",
            "planning_turn_limit_reached",
            "decomposition_confirmation_required",
        ]
        for dtype in expected_types:
            self.assertIn(dtype, DECISION_TYPES)

    def test_pr_approval_required_choices(self):
        """Test pr_approval_required has correct choices."""
        self.assertEqual(DECISION_TYPES["pr_approval_required"], ["approve", "reject"])

    def test_turn_limit_reached_choices(self):
        """Test turn_limit_reached has correct choices."""
        self.assertEqual(DECISION_TYPES["turn_limit_reached"], ["extend", "respec", "cancel"])

    def test_decisions_list_output(self):
        """Test cmd_decisions_list prints all decision types."""
        args = MagicMock(format="table")
        captured = StringIO()
        with patch("sys.stdout", captured):
            cmd_decisions_list(args)
        output = captured.getvalue()
        for dtype in DECISION_TYPES:
            self.assertIn(dtype, output)

    def test_decisions_list_json_output(self):
        """Test cmd_decisions_list with JSON format."""
        args = MagicMock(format="json")
        captured = StringIO()
        with patch("sys.stdout", captured):
            cmd_decisions_list(args)
        output = captured.getvalue()
        data = json.loads(output)
        self.assertEqual(set(data.keys()), set(DECISION_TYPES.keys()))


class TestAPICalls(unittest.TestCase):
    """Test that CLI commands call the correct API endpoints."""

    def setUp(self):
        """Set up mocks for API calls."""
        self.port_patcher = patch("matrixmouse.main._resolve_port", return_value=8080)
        self.port_mock = self.port_patcher.start()
        self.addCleanup(self.port_patcher.stop)

    def test_add_repo_calls_api(self):
        """Test that add-repo calls POST /repos."""
        args = MagicMock()
        args.remote = "https://github.com/user/repo.git"
        args.name = None
        
        with patch("matrixmouse.main._agent_post") as mock_post:
            mock_post.return_value = {
                "ok": True,
                "repo": {"name": "repo", "local_path": "/path/to/repo"}
            }
            with patch("matrixmouse.main._post_add_instructions"):
                with patch("sys.stdout", StringIO()):
                    cmd_add_repo(args)
            
            mock_post.assert_called_once_with(
                "/repos",
                {"remote": "https://github.com/user/repo.git", "name": None},
                8080
            )

    def test_repos_list_calls_api(self):
        """Test that repos list calls GET /repos."""
        args = MagicMock(format="table")
        
        with patch("matrixmouse.main._agent_get") as mock_get:
            mock_get.return_value = {"repos": []}
            with patch("sys.stdout", StringIO()):
                cmd_repos_list(args)
            
            mock_get.assert_called_once_with("/repos", 8080)

    def test_repos_remove_calls_api(self):
        """Test that repos remove calls DELETE /repos/{name}."""
        args = MagicMock()
        args.name = "my-repo"
        args.yes = True
        
        with patch("matrixmouse.main._agent_delete") as mock_delete:
            mock_delete.return_value = {"ok": True}
            with patch("sys.stdout", StringIO()):
                cmd_repos_remove(args)
            
            mock_delete.assert_called_once_with("/repos/my-repo", 8080)

    def test_tasks_list_calls_api(self):
        """Test that tasks list calls GET /tasks."""
        args = MagicMock(status=None, repo=None, all=False, format="table")
        
        with patch("matrixmouse.main._agent_get") as mock_get:
            mock_get.return_value = {"tasks": [], "count": 0}
            with patch("sys.stdout", StringIO()):
                cmd_tasks_list(args)
            
            mock_get.assert_called_once_with("/tasks", 8080)

    def test_tasks_list_with_filters_calls_api(self):
        """Test that tasks list with filters calls GET /tasks with query params."""
        args = MagicMock(status="blocked", repo="my-repo", all=False, format="table")
        
        with patch("matrixmouse.main._agent_get") as mock_get:
            mock_get.return_value = {"tasks": [], "count": 0}
            with patch("sys.stdout", StringIO()):
                cmd_tasks_list(args)
            
            mock_get.assert_called_once_with("/tasks?status=blocked&repo=my-repo", 8080)

    def test_tasks_show_calls_api(self):
        """Test that tasks show calls GET /tasks/{id}."""
        args = MagicMock(id="abc123")
        
        with patch("matrixmouse.main._agent_get") as mock_get:
            mock_get.return_value = {"id": "abc123", "title": "Test"}
            with patch("sys.stdout", StringIO()):
                cmd_tasks_show(args)
            
            mock_get.assert_called_once_with("/tasks/abc123", 8080)

    def test_tasks_cancel_calls_api(self):
        """Test that tasks cancel calls DELETE /tasks/{id}."""
        args = MagicMock(id="abc123", yes=True)
        
        with patch("matrixmouse.main._agent_get") as mock_get:
            mock_get.return_value = {"id": "abc123", "title": "Test"}
            with patch("matrixmouse.main._agent_delete") as mock_delete:
                mock_delete.return_value = {"ok": True}
                with patch("sys.stdout", StringIO()):
                    cmd_tasks_cancel(args)
                
                mock_delete.assert_called_once_with("/tasks/abc123", 8080)

    def test_tasks_answer_calls_api(self):
        """Test that tasks answer calls POST /tasks/{id}/answer."""
        args = MagicMock(task_id="abc123", message="Use staging database")
        
        with patch("matrixmouse.main._agent_post") as mock_post:
            mock_post.return_value = {"ok": True, "unblocked": False}
            with patch("sys.stdout", StringIO()):
                cmd_tasks_answer(args)
            
            mock_post.assert_called_once_with(
                "/tasks/abc123/answer",
                {"message": "Use staging database"},
                8080
            )

    def test_tasks_decision_calls_api(self):
        """Test that tasks decision calls POST /tasks/{id}/decision."""
        args = MagicMock(
            task_id="abc123",
            decision_type="pr_approval_required",
            choice="approve",
            note=""
        )
        
        with patch("matrixmouse.main._agent_post") as mock_post:
            mock_post.return_value = {"ok": True, "action": "approve"}
            with patch("sys.stdout", StringIO()):
                cmd_tasks_decision(args)
            
            mock_post.assert_called_once_with(
                "/tasks/abc123/decision",
                {"decision_type": "pr_approval_required", "choice": "approve"},
                8080
            )

    def test_tasks_decision_with_note_calls_api(self):
        """Test that tasks decision with note includes note in payload."""
        args = MagicMock(
            task_id="abc123",
            decision_type="pr_approval_required",
            choice="approve",
            note="Looks good"
        )
        
        with patch("matrixmouse.main._agent_post") as mock_post:
            mock_post.return_value = {"ok": True, "action": "approve"}
            with patch("sys.stdout", StringIO()):
                cmd_tasks_decision(args)
            
            call_args = mock_post.call_args[0][1]
            self.assertEqual(call_args["note"], "Looks good")

    def test_interject_workspace_calls_api(self):
        """Test that interject workspace calls POST /interject/workspace."""
        args = MagicMock(message="Please prioritize security")
        
        with patch("matrixmouse.main._agent_post") as mock_post:
            mock_post.return_value = {"ok": True, "manager_task_id": "xyz789"}
            with patch("sys.stdout", StringIO()):
                cmd_interject_workspace(args)
            
            mock_post.assert_called_once_with(
                "/interject/workspace",
                {"message": "Please prioritize security"},
                8080
            )

    def test_interject_repo_calls_api(self):
        """Test that interject repo calls POST /interject/repo/{repo}."""
        args = MagicMock(repo="my-repo", message="Focus on auth module")
        
        with patch("matrixmouse.main._agent_post") as mock_post:
            mock_post.return_value = {"ok": True, "manager_task_id": "xyz789"}
            with patch("sys.stdout", StringIO()):
                cmd_interject_repo(args)
            
            mock_post.assert_called_once_with(
                "/interject/repo/my-repo",
                {"message": "Focus on auth module"},
                8080
            )

    def test_interject_task_calls_api(self):
        """Test that interject task calls POST /tasks/{id}/interject."""
        args = MagicMock(task_id="abc123", message="Consider caching")
        
        with patch("matrixmouse.main._agent_post") as mock_post:
            mock_post.return_value = {"ok": True}
            with patch("sys.stdout", StringIO()):
                cmd_interject_task(args)
            
            mock_post.assert_called_once_with(
                "/tasks/abc123/interject",
                {"message": "Consider caching"},
                8080
            )

    def test_status_calls_api(self):
        """Test that status calls GET /orchestrator/status."""
        args = MagicMock()
        
        with patch("matrixmouse.main._agent_get") as mock_get:
            mock_get.return_value = {
                "status": {"task": "Test", "role": "coder"},
                "paused": False,
                "stopped": False
            }
            with patch("sys.stdout", StringIO()):
                cmd_status(args)
            
            mock_get.assert_called_once_with("/orchestrator/status", 8080)

    def test_stop_calls_api(self):
        """Test that stop calls POST /stop."""
        args = MagicMock()
        
        with patch("matrixmouse.main._agent_post") as mock_post:
            mock_post.return_value = {"ok": True}
            with patch("sys.stdout", StringIO()):
                cmd_stop(args)
            
            mock_post.assert_called_once_with("/stop", {}, 8080)

    def test_kill_calls_api(self):
        """Test that kill calls POST /kill."""
        args = MagicMock(yes=True)
        
        with patch("matrixmouse.main._agent_post") as mock_post:
            mock_post.return_value = {"ok": True}
            with patch("sys.stdout", StringIO()):
                cmd_kill(args)
            
            mock_post.assert_called_once_with("/kill", {}, 8080)

    def test_pause_calls_api(self):
        """Test that pause calls POST /orchestrator/pause."""
        args = MagicMock()
        
        with patch("matrixmouse.main._agent_post") as mock_post:
            mock_post.return_value = {"message": "Orchestrator paused."}
            with patch("sys.stdout", StringIO()):
                cmd_pause(args)
            
            mock_post.assert_called_once_with("/orchestrator/pause", {}, 8080)

    def test_resume_calls_api(self):
        """Test that resume calls POST /orchestrator/resume."""
        args = MagicMock()
        
        with patch("matrixmouse.main._agent_post") as mock_post:
            mock_post.return_value = {"message": "Orchestrator resumed."}
            with patch("sys.stdout", StringIO()):
                cmd_resume(args)
            
            mock_post.assert_called_once_with("/orchestrator/resume", {}, 8080)

    def test_blocked_calls_api(self):
        """Test that blocked calls GET /blocked."""
        args = MagicMock(format="table")
        
        with patch("matrixmouse.main._agent_get") as mock_get:
            mock_get.return_value = {"report": []}
            with patch("sys.stdout", StringIO()):
                cmd_blocked(args)
            
            mock_get.assert_called_once_with("/blocked", 8080)

    def test_token_usage_calls_api(self):
        """Test that token-usage calls GET /token_usage."""
        args = MagicMock(format="table")
        
        with patch("matrixmouse.main._agent_get") as mock_get:
            mock_get.return_value = {"anthropic": {"hour": 0, "day": 0}}
            with patch("sys.stdout", StringIO()):
                cmd_token_usage(args)
            
            mock_get.assert_called_once_with("/token_usage", 8080)

    def test_context_calls_api(self):
        """Test that context calls GET /tasks/{id}."""
        args = MagicMock(id="abc123", last=None, all=False, format="table")
        
        with patch("matrixmouse.main._agent_get") as mock_get:
            mock_get.return_value = {
                "id": "abc123",
                "title": "Test task",
                "context_messages": []
            }
            with patch("sys.stdout", StringIO()):
                cmd_context(args)
            
            mock_get.assert_called_once_with("/tasks/abc123", 8080)

    def test_context_with_last_calls_api(self):
        """Test that context with --last limits messages."""
        args = MagicMock(id="abc123", last=10, all=False, format="table")
        
        with patch("matrixmouse.main._agent_get") as mock_get:
            mock_get.return_value = {
                "id": "abc123",
                "title": "Test task",
                "context_messages": [{"role": "user", "content": "msg"}] * 50
            }
            captured = StringIO()
            with patch("sys.stdout", captured):
                cmd_context(args)
            
            # Verify output mentions limited messages
            output = captured.getvalue()
            self.assertIn("10 messages", output)

    def test_context_with_all_flag(self):
        """Test that context with --all shows all messages."""
        args = MagicMock(id="abc123", last=None, all=True, format="table")
        
        with patch("matrixmouse.main._agent_get") as mock_get:
            mock_get.return_value = {
                "id": "abc123",
                "title": "Test task",
                "context_messages": [{"role": "user", "content": "msg"}] * 100
            }
            captured = StringIO()
            with patch("sys.stdout", captured):
                cmd_context(args)
            
            # Verify output shows all 100 messages (no truncation message)
            output = captured.getvalue()
            self.assertIn("100 messages", output)
            self.assertNotIn("Use --all", output)

    def test_context_default_limit_applied(self):
        """Test that context applies default limit when messages exceed DEFAULT_MESSAGE_LIMIT."""
        from matrixmouse.main import DEFAULT_MESSAGE_LIMIT
        
        args = MagicMock(id="abc123", last=None, all=False, format="table")
        
        with patch("matrixmouse.main._agent_get") as mock_get:
            mock_get.return_value = {
                "id": "abc123",
                "title": "Test task",
                "context_messages": [{"role": "user", "content": "msg"}] * 100
            }
            captured = StringIO()
            with patch("sys.stdout", captured):
                cmd_context(args)
            
            # Verify output mentions default limit
            output = captured.getvalue()
            self.assertIn(f"Showing last {DEFAULT_MESSAGE_LIMIT}", output)

    def test_context_task_not_found(self):
        """Test that context handles non-existent task."""
        args = MagicMock(id="nonexistent", last=None, all=False, format="table")
        
        with patch("matrixmouse.main._agent_get") as mock_get:
            mock_get.return_value = {}  # Empty response = task not found
            captured = StringIO()
            with patch("sys.stdout", captured):
                with self.assertRaises(SystemExit):
                    cmd_context(args)
            
            output = captured.getvalue()
            self.assertIn("ERROR", output)
            self.assertIn("not found", output)

    def test_context_with_format_json(self):
        """Test context with JSON format output."""
        args = MagicMock(id="abc123", last=None, all=False, format="json")
        
        with patch("matrixmouse.main._agent_get") as mock_get:
            mock_get.return_value = {
                "id": "abc123",
                "title": "Test",
                "context_messages": [{"role": "user", "content": "msg"}]
            }
            captured = StringIO()
            with patch("sys.stdout", captured):
                cmd_context(args)
            
            output = captured.getvalue()
            data = json.loads(output)
            self.assertEqual(data["task_id"], "abc123")
            self.assertIn("messages", data)
            self.assertEqual(data["count"], 1)

    def test_context_with_block_content(self):
        """Test context displays block-based content correctly."""
        args = MagicMock(id="abc123", last=None, all=False, format="table")
        
        with patch("matrixmouse.main._agent_get") as mock_get:
            mock_get.return_value = {
                "id": "abc123",
                "title": "Test task",
                "context_messages": [{
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "Hello"},
                        {"type": "tool_use", "name": "read_file", "input": {"path": "test.py"}}
                    ]
                }]
            }
            captured = StringIO()
            with patch("sys.stdout", captured):
                cmd_context(args)
            
            output = captured.getvalue()
            self.assertIn("tool_use:read_file", output)

    def test_context_invalid_last_parameter(self):
        """Test that context rejects zero or negative --last values."""
        for last_val in [0, -1, -10]:
            args = MagicMock(id="abc123", last=last_val, all=False, format="table")
            
            with patch("matrixmouse.main._agent_get"):
                captured = StringIO()
                with patch("sys.stdout", captured):
                    with self.assertRaises(SystemExit):
                        cmd_context(args)
                self.assertIn("ERROR", captured.getvalue())

    def test_health_calls_api(self):
        """Test that health calls GET /health."""
        args = MagicMock()
        
        with patch("matrixmouse.main._agent_get") as mock_get:
            mock_get.return_value = {"ok": True, "timestamp": "2024-01-01T00:00:00Z"}
            with patch("sys.stdout", StringIO()):
                cmd_health(args)
            
            mock_get.assert_called_once_with("/health", 8080)

    def test_config_get_calls_api(self):
        """Test that config get calls GET /config."""
        args = MagicMock(key=None, repo=None)
        
        with patch("matrixmouse.main._agent_get") as mock_get:
            mock_get.return_value = {"coder_model": "ollama:qwen3.5:9b"}
            with patch("sys.stdout", StringIO()):
                cmd_config_get(args)
            
            mock_get.assert_called_once_with("/config", 8080)

    def test_config_get_with_repo_calls_api(self):
        """Test that config get with repo calls GET /config/repos/{repo}."""
        args = MagicMock(key=None, repo="my-repo")
        
        with patch("matrixmouse.main._agent_get") as mock_get:
            mock_get.return_value = {"coder_model": "ollama:qwen3.5:9b"}
            with patch("sys.stdout", StringIO()):
                cmd_config_get(args)
            
            mock_get.assert_called_once_with("/config/repos/my-repo", 8080)

    def test_config_set_calls_api(self):
        """Test that config set calls PATCH /config."""
        args = MagicMock(
            key="coder_model",
            value="ollama:qwen3.5:9b",
            repo=None,
            commit=False
        )
        
        with patch("matrixmouse.main._agent_patch") as mock_patch:
            mock_patch.return_value = {"ok": True}
            with patch("sys.stdout", StringIO()):
                cmd_config_set(args)
            
            mock_patch.assert_called_once_with(
                "/config",
                {"values": {"coder_model": "ollama:qwen3.5:9b"}},
                8080
            )

    def test_config_set_with_repo_calls_api(self):
        """Test that config set with repo calls PATCH /config/repos/{repo}."""
        args = MagicMock(
            key="coder_model",
            value="ollama:qwen3.5:9b",
            repo="my-repo",
            commit=False
        )
        
        with patch("matrixmouse.main._agent_patch") as mock_patch:
            mock_patch.return_value = {"ok": True}
            with patch("sys.stdout", StringIO()):
                cmd_config_set(args)
            
            mock_patch.assert_called_once_with(
                "/config/repos/my-repo",
                {"values": {"coder_model": "ollama:qwen3.5:9b"}},
                8080
            )

    def test_config_set_with_commit_calls_api(self):
        """Test that config set with --commit calls PATCH with ?commit=true."""
        args = MagicMock(
            key="coder_model",
            value="ollama:qwen3.5:9b",
            repo="my-repo",
            commit=True
        )
        
        with patch("matrixmouse.main._agent_patch") as mock_patch:
            mock_patch.return_value = {"ok": True}
            with patch("sys.stdout", StringIO()):
                cmd_config_set(args)
            
            mock_patch.assert_called_once_with(
                "/config/repos/my-repo?commit=true",
                {"values": {"coder_model": "ollama:qwen3.5:9b"}},
                8080
            )


if __name__ == "__main__":
    unittest.main()
