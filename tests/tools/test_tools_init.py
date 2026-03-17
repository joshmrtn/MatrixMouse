"""
tests/tools/test_tools_init.py

Tests for matrixmouse.tools.__init__ — tool registry and role filtering.

Coverage:
    TOOLS list:
        - No duplicate tool names
        - All tools are callable

    TOOL_REGISTRY:
        - Keys match function names in TOOLS
        - All values are callable
        - Registry covers all tools in TOOLS list

    tools_for_role:
        - Returns frozenset for each valid role
        - Returns non-empty set for all roles
        - Returns empty frozenset with warning for unknown role
        - Manager set contains task management tools
        - Manager set does not contain file write tools
        - Coder set contains file and code tools
        - Writer set does not contain code tools or test tools
        - Critic set contains approve and deny
        - Critic set does not contain declare_complete

    tools_for_role_list:
        - Returns list of callables
        - All returned functions are in TOOL_REGISTRY
        - Length matches tools_for_role frozenset size
        - Manager list does not contain str_replace
        - Critic list contains approve and deny functions
"""

import pytest
from unittest.mock import patch
import logging

from matrixmouse.tools import (
    TOOLS,
    TOOL_REGISTRY,
    tools_for_role,
    tools_for_role_list,
)
from matrixmouse.task import AgentRole


# ---------------------------------------------------------------------------
# TOOLS list
# ---------------------------------------------------------------------------

class TestToolsList:
    def test_no_duplicate_tool_names(self):
        names = [fn.__name__ for fn in TOOLS]
        assert len(names) == len(set(names)), \
            f"Duplicate tools: {[n for n in names if names.count(n) > 1]}"

    def test_all_tools_are_callable(self):
        for fn in TOOLS:
            assert callable(fn), f"Tool {fn} is not callable"


# ---------------------------------------------------------------------------
# TOOL_REGISTRY
# ---------------------------------------------------------------------------

class TestToolRegistry:
    def test_keys_match_function_names(self):
        for name, fn in TOOL_REGISTRY.items():
            assert fn.__name__ == name

    def test_all_values_are_callable(self):
        for fn in TOOL_REGISTRY.values():
            assert callable(fn)

    def test_registry_covers_all_tools(self):
        for fn in TOOLS:
            assert fn.__name__ in TOOL_REGISTRY

    def test_registry_size_matches_tools(self):
        assert len(TOOL_REGISTRY) == len(TOOLS)


# ---------------------------------------------------------------------------
# tools_for_role
# ---------------------------------------------------------------------------

class TestToolsForRole:
    def test_returns_frozenset_for_each_role(self):
        for role in AgentRole:
            result = tools_for_role(role)
            assert isinstance(result, frozenset), \
                f"tools_for_role({role}) did not return frozenset"

    def test_returns_non_empty_set_for_all_roles(self):
        for role in AgentRole:
            assert len(tools_for_role(role)) > 0, \
                f"tools_for_role({role}) returned empty set"

    def test_unknown_role_returns_empty_frozenset(self):
        with patch("matrixmouse.tools.logger") as mock_logger:
            result = tools_for_role("nonexistent_role")
        assert result == frozenset()

    def test_unknown_role_logs_warning(self):
        with patch("matrixmouse.tools.logger") as mock_logger:
            tools_for_role("nonexistent_role")
        mock_logger.warning.assert_called_once()

    def test_manager_has_task_management_tools(self):
        tools = tools_for_role(AgentRole.MANAGER)
        for name in ("create_task", "split_task", "update_task",
                     "get_task_info", "list_tasks"):
            assert name in tools

    def test_manager_lacks_file_write_tools(self):
        tools = tools_for_role(AgentRole.MANAGER)
        assert "str_replace" not in tools
        assert "append_to_file" not in tools

    def test_manager_lacks_approve_deny(self):
        tools = tools_for_role(AgentRole.MANAGER)
        assert "approve" not in tools
        assert "deny" not in tools

    def test_coder_has_file_and_code_tools(self):
        tools = tools_for_role(AgentRole.CODER)
        for name in ("read_file", "str_replace", "get_function_def",
                     "run_tests", "get_git_diff"):
            assert name in tools

    def test_coder_lacks_task_write_tools(self):
        tools = tools_for_role(AgentRole.CODER)
        assert "create_task" not in tools
        assert "split_task" not in tools

    def test_writer_lacks_code_tools(self):
        tools = tools_for_role(AgentRole.WRITER)
        for name in ("get_function_def", "get_function_list",
                     "get_class_summary", "run_tests"):
            assert name not in tools

    def test_critic_has_approve_and_deny(self):
        tools = tools_for_role(AgentRole.CRITIC)
        assert "approve" in tools
        assert "deny" in tools

    def test_critic_lacks_declare_complete(self):
        tools = tools_for_role(AgentRole.CRITIC)
        assert "declare_complete" not in tools

    def test_all_role_tool_names_exist_in_registry(self):
        """Every tool name in every role set must be in TOOL_REGISTRY."""
        for role in AgentRole:
            for name in tools_for_role(role):
                assert name in TOOL_REGISTRY, \
                    f"Role {role}: tool '{name}' not in TOOL_REGISTRY"


# ---------------------------------------------------------------------------
# tools_for_role_list
# ---------------------------------------------------------------------------

class TestToolsForRoleList:
    def test_returns_list(self):
        for role in AgentRole:
            assert isinstance(tools_for_role_list(role), list)

    def test_all_returned_items_are_callable(self):
        for role in AgentRole:
            for fn in tools_for_role_list(role):
                assert callable(fn)

    def test_length_matches_frozenset(self):
        for role in AgentRole:
            assert len(tools_for_role_list(role)) == len(tools_for_role(role))

    def test_all_functions_in_tool_registry(self):
        for role in AgentRole:
            for fn in tools_for_role_list(role):
                assert fn.__name__ in TOOL_REGISTRY

    def test_manager_list_excludes_str_replace(self):
        fns = tools_for_role_list(AgentRole.MANAGER)
        names = [fn.__name__ for fn in fns]
        assert "str_replace" not in names

    def test_critic_list_includes_approve_and_deny(self):
        fns = tools_for_role_list(AgentRole.CRITIC)
        names = [fn.__name__ for fn in fns]
        assert "approve" in names
        assert "deny" in names