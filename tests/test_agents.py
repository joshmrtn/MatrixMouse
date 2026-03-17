"""
tests/test_agents.py

Tests for matrixmouse.agents — BaseAgent subclasses and agent_for_role registry.

Coverage:
    agent_for_role:
        - Returns correct concrete class for each role
        - Raises KeyError for unknown role
        - Returns a new instance on each call

    allowed_tools:
        - Each agent has a non-empty frozenset of allowed tools
        - Manager has task management tools
        - Manager does not have file-write tools
        - Coder has file and git tools
        - Coder does not have task management write tools
        - Writer has file tools but not code tools or test tools
        - Critic has approve and deny but not declare_complete
        - Critic does not have file-write tools

    build_system_prompt:
        - Returns a non-empty string for each role
        - Manager planning prompt contains key behavioural directives
        - Manager review prompt contains review checklist markers
        - Coder prompt contains scope and quality directives
        - Writer prompt contains prose quality directives
        - Critic prompt contains approve/deny guidance
        - Critic prompt contains prohibited shortcuts list
        - _is_review_task heuristic works correctly

    build_initial_messages:
        - Returns list with at least two messages
        - First message has role 'system'
        - Second message has role 'user'
        - System message content matches build_system_prompt output
        - User message contains task id, title, description
        - Critic user message contains review context markers

    _shared_constraints:
        - Coder and Writer include shared constraints in prompt
        - Critic overrides _shared_constraints to empty string
"""

import pytest
from unittest.mock import MagicMock

from matrixmouse.agents import agent_for_role
from matrixmouse.agents.manager import ManagerAgent, _is_review_task
from matrixmouse.agents.coder import CoderAgent
from matrixmouse.agents.writer import WriterAgent
from matrixmouse.agents.critic import CriticAgent
from matrixmouse.task import AgentRole, Task, TaskStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_task(**kwargs) -> Task:
    defaults = dict(
        title="Test task",
        description="Do the thing carefully.",
        role=AgentRole.CODER,
        repo=["my-repo"],
    )
    defaults.update(kwargs)
    return Task(**defaults)


def make_review_task(**kwargs) -> Task:
    return make_task(
        title="[Manager Review] Weekly review",
        role=AgentRole.MANAGER,
        description="Review completed and upcoming tasks.",
        **kwargs,
    )


def make_critic_task(reviews_task_id="abc123") -> Task:
    return make_task(
        title="[Critic Review] Implement foo",
        role=AgentRole.CRITIC,
        reviews_task_id=reviews_task_id,
        description=(
            "Reviewed task ID: abc123\n"
            "Title: Implement foo\n"
            "--- DEFINITION OF DONE ---\n"
            "Function foo must return an integer.\n"
            "--- END DEFINITION OF DONE ---\n"
            "--- GIT DIFF ---\n"
            "+def foo(): return 42\n"
            "--- END DIFF ---"
        ),
    )


# ---------------------------------------------------------------------------
# agent_for_role registry
# ---------------------------------------------------------------------------

class TestAgentForRole:
    def test_manager_role_returns_manager_agent(self):
        agent = agent_for_role(AgentRole.MANAGER)
        assert isinstance(agent, ManagerAgent)

    def test_coder_role_returns_coder_agent(self):
        agent = agent_for_role(AgentRole.CODER)
        assert isinstance(agent, CoderAgent)

    def test_writer_role_returns_writer_agent(self):
        agent = agent_for_role(AgentRole.WRITER)
        assert isinstance(agent, WriterAgent)

    def test_critic_role_returns_critic_agent(self):
        agent = agent_for_role(AgentRole.CRITIC)
        assert isinstance(agent, CriticAgent)

    def test_unknown_role_raises_key_error(self):
        with pytest.raises(KeyError):
            agent_for_role("nonexistent_role")

    def test_returns_new_instance_each_call(self):
        a1 = agent_for_role(AgentRole.CODER)
        a2 = agent_for_role(AgentRole.CODER)
        assert a1 is not a2


# ---------------------------------------------------------------------------
# allowed_tools
# ---------------------------------------------------------------------------

class TestAllowedTools:
    def test_all_agents_have_non_empty_tool_sets(self):
        for role in AgentRole:
            agent = agent_for_role(role)
            assert len(agent.allowed_tools) > 0, \
                f"{role} has empty allowed_tools"

    def test_manager_has_task_management_tools(self):
        agent = agent_for_role(AgentRole.MANAGER)
        for tool in ("create_task", "split_task", "update_task",
                     "get_task_info", "list_tasks"):
            assert tool in agent.allowed_tools, \
                f"Manager missing tool: {tool}"

    def test_manager_does_not_have_file_write_tools(self):
        agent = agent_for_role(AgentRole.MANAGER)
        for tool in ("str_replace", "append_to_file"):
            assert tool not in agent.allowed_tools, \
                f"Manager should not have write tool: {tool}"

    def test_manager_does_not_have_approve_deny(self):
        agent = agent_for_role(AgentRole.MANAGER)
        assert "approve" not in agent.allowed_tools
        assert "deny" not in agent.allowed_tools

    def test_coder_has_file_and_git_tools(self):
        agent = agent_for_role(AgentRole.CODER)
        for tool in ("read_file", "str_replace", "append_to_file",
                     "get_git_diff", "get_git_log", "commit_progress"):
            assert tool in agent.allowed_tools, \
                f"Coder missing tool: {tool}"

    def test_coder_has_test_tools(self):
        agent = agent_for_role(AgentRole.CODER)
        assert "run_tests" in agent.allowed_tools
        assert "run_single_test" in agent.allowed_tools

    def test_coder_does_not_have_task_write_tools(self):
        agent = agent_for_role(AgentRole.CODER)
        for tool in ("create_task", "split_task", "update_task"):
            assert tool not in agent.allowed_tools, \
                f"Coder should not have task write tool: {tool}"

    def test_coder_does_not_have_approve_deny(self):
        agent = agent_for_role(AgentRole.CODER)
        assert "approve" not in agent.allowed_tools
        assert "deny" not in agent.allowed_tools

    def test_writer_has_file_tools(self):
        agent = agent_for_role(AgentRole.WRITER)
        for tool in ("read_file", "str_replace", "append_to_file"):
            assert tool in agent.allowed_tools, \
                f"Writer missing tool: {tool}"

    def test_writer_does_not_have_code_tools(self):
        agent = agent_for_role(AgentRole.WRITER)
        for tool in ("get_function_def", "get_function_list",
                     "get_class_summary"):
            assert tool not in agent.allowed_tools, \
                f"Writer should not have code tool: {tool}"

    def test_writer_does_not_have_test_tools(self):
        agent = agent_for_role(AgentRole.WRITER)
        assert "run_tests" not in agent.allowed_tools
        assert "run_single_test" not in agent.allowed_tools

    def test_writer_does_not_have_approve_deny(self):
        agent = agent_for_role(AgentRole.WRITER)
        assert "approve" not in agent.allowed_tools
        assert "deny" not in agent.allowed_tools

    def test_critic_has_approve_and_deny(self):
        agent = agent_for_role(AgentRole.CRITIC)
        assert "approve" in agent.allowed_tools
        assert "deny" in agent.allowed_tools

    def test_critic_does_not_have_declare_complete(self):
        agent = agent_for_role(AgentRole.CRITIC)
        assert "declare_complete" not in agent.allowed_tools

    def test_critic_does_not_have_file_write_tools(self):
        agent = agent_for_role(AgentRole.CRITIC)
        for tool in ("str_replace", "append_to_file", "commit_progress"):
            assert tool not in agent.allowed_tools, \
                f"Critic should not have write tool: {tool}"

    def test_critic_does_not_have_task_write_tools(self):
        agent = agent_for_role(AgentRole.CRITIC)
        for tool in ("create_task", "split_task", "update_task"):
            assert tool not in agent.allowed_tools, \
                f"Critic should not have task write tool: {tool}"

    def test_critic_does_not_have_request_clarification(self):
        agent = agent_for_role(AgentRole.CRITIC)
        assert "request_clarification" not in agent.allowed_tools


# ---------------------------------------------------------------------------
# build_system_prompt
# ---------------------------------------------------------------------------

class TestBuildSystemPrompt:
    def test_all_agents_return_non_empty_string(self):
        for role in AgentRole:
            agent = agent_for_role(role)
            task = make_task(role=role)
            prompt = agent.build_system_prompt(task)
            assert isinstance(prompt, str)
            assert len(prompt) > 100, \
                f"{role} system prompt is suspiciously short"

    def test_manager_planning_prompt_contains_directives(self):
        agent = agent_for_role(AgentRole.MANAGER)
        task = make_task(role=AgentRole.MANAGER)
        prompt = agent.build_system_prompt(task)
        # Check for stable structural concepts rather than specific words
        assert "decompose" in prompt.lower() or "subtask" in prompt.lower()
        assert "role" in prompt.lower()
        assert "declare_complete" in prompt.lower()
        assert "coder" in prompt.lower() or "writer" in prompt.lower()

    def test_manager_review_prompt_contains_review_markers(self):
        agent = agent_for_role(AgentRole.MANAGER)
        task = make_review_task()
        prompt = agent.build_system_prompt(task)
        for phrase in ("review", "blocked", "priority", "declare_complete"):
            assert phrase.lower() in prompt.lower(), \
                f"Manager review prompt missing: {phrase}"

    def test_manager_planning_and_review_prompts_differ(self):
        agent = agent_for_role(AgentRole.MANAGER)
        planning_prompt = agent.build_system_prompt(make_task(role=AgentRole.MANAGER))
        review_prompt   = agent.build_system_prompt(make_review_task())
        assert planning_prompt != review_prompt

    def test_coder_prompt_contains_scope_directives(self):
        agent = agent_for_role(AgentRole.CODER)
        task = make_task()
        prompt = agent.build_system_prompt(task)
        for phrase in ("scope", "test", "commit", "declare_complete"):
            assert phrase.lower() in prompt.lower(), \
                f"Coder prompt missing: {phrase}"

    def test_coder_prompt_contains_prohibited_shortcut_warning(self):
        agent = agent_for_role(AgentRole.CODER)
        prompt = agent.build_system_prompt(make_task())
        assert "delete" in prompt.lower() or "deleting" in prompt.lower()
        assert "test" in prompt.lower()

    def test_writer_prompt_contains_prose_directives(self):
        agent = agent_for_role(AgentRole.WRITER)
        task = make_task(role=AgentRole.WRITER)
        prompt = agent.build_system_prompt(task)
        for phrase in ("audience", "accurate", "scope", "declare_complete"):
            assert phrase.lower() in prompt.lower(), \
                f"Writer prompt missing: {phrase}"

    def test_writer_prompt_warns_against_source_code_modification(self):
        agent = agent_for_role(AgentRole.WRITER)
        prompt = agent.build_system_prompt(make_task(role=AgentRole.WRITER))
        assert "source code" in prompt.lower() or "code file" in prompt.lower()

    def test_critic_prompt_contains_approve_deny_guidance(self):
        agent = agent_for_role(AgentRole.CRITIC)
        task = make_critic_task()
        prompt = agent.build_system_prompt(task)
        for phrase in ("approve", "deny", "feedback"):
            assert phrase.lower() in prompt.lower(), \
                f"Critic prompt missing: {phrase}"

    def test_critic_prompt_contains_prohibited_shortcuts(self):
        agent = agent_for_role(AgentRole.CRITIC)
        prompt = agent.build_system_prompt(make_critic_task())
        # Check the prohibited shortcuts section exists with key concepts
        assert "test" in prompt.lower()      # test deletion is the most critical shortcut
        assert "deny" in prompt.lower()      # deny is the tool used to flag shortcuts
        assert "approve" in prompt.lower()   # approve is the positive path

    def test_coder_prompt_includes_repo_when_set(self):
        agent = agent_for_role(AgentRole.CODER)
        task = make_task(repo=["special-repo"])
        prompt = agent.build_system_prompt(task)
        assert "special-repo" in prompt

    def test_coder_prompt_includes_target_files_when_set(self):
        agent = agent_for_role(AgentRole.CODER)
        task = make_task(target_files=["src/foo.py", "src/bar.py"])
        prompt = agent.build_system_prompt(task)
        assert "src/foo.py" in prompt


# ---------------------------------------------------------------------------
# build_initial_messages
# ---------------------------------------------------------------------------

class TestBuildInitialMessages:
    def test_returns_list_with_at_least_two_messages(self):
        for role in AgentRole:
            agent = agent_for_role(role)
            task = make_task(role=role)
            msgs = agent.build_initial_messages(task)
            assert len(msgs) >= 2, \
                f"{role} build_initial_messages returned fewer than 2 messages"

    def test_first_message_is_system(self):
        for role in AgentRole:
            agent = agent_for_role(role)
            task = make_task(role=role)
            msgs = agent.build_initial_messages(task)
            assert msgs[0]["role"] == "system"

    def test_second_message_is_user(self):
        for role in AgentRole:
            agent = agent_for_role(role)
            task = make_task(role=role)
            msgs = agent.build_initial_messages(task)
            assert msgs[1]["role"] == "user"

    def test_system_message_matches_build_system_prompt(self):
        for role in AgentRole:
            agent = agent_for_role(role)
            task = make_task(role=role)
            msgs = agent.build_initial_messages(task)
            assert msgs[0]["content"] == agent.build_system_prompt(task)

    def test_user_message_contains_task_id(self):
        agent = agent_for_role(AgentRole.CODER)
        task = make_task()
        msgs = agent.build_initial_messages(task)
        assert task.id in msgs[1]["content"]

    def test_user_message_contains_task_title(self):
        agent = agent_for_role(AgentRole.CODER)
        task = make_task(title="My specific task title")
        msgs = agent.build_initial_messages(task)
        assert "My specific task title" in msgs[1]["content"]

    def test_user_message_contains_description(self):
        agent = agent_for_role(AgentRole.CODER)
        task = make_task(description="Do this specific thing with that module.")
        msgs = agent.build_initial_messages(task)
        assert "Do this specific thing with that module." in msgs[1]["content"]

    def test_critic_user_message_contains_review_context_markers(self):
        agent = agent_for_role(AgentRole.CRITIC)
        task = make_critic_task()
        msgs = agent.build_initial_messages(task)
        user_content = msgs[1]["content"]
        assert "DEFINITION OF DONE" in user_content or \
               "GIT DIFF" in user_content or \
               "review context" in user_content.lower()

    def test_user_message_contains_notes_when_set(self):
        agent = agent_for_role(AgentRole.CODER)
        task = make_task(notes="Previous attempt failed at step 3.")
        msgs = agent.build_initial_messages(task)
        assert "Previous attempt failed at step 3." in msgs[1]["content"]

    def test_user_message_contains_target_files_when_set(self):
        agent = agent_for_role(AgentRole.WRITER)
        task = make_task(
            role=AgentRole.WRITER,
            target_files=["docs/README.md"],
        )
        msgs = agent.build_initial_messages(task)
        assert "docs/README.md" in msgs[1]["content"]


# ---------------------------------------------------------------------------
# _shared_constraints
# ---------------------------------------------------------------------------

class TestSharedConstraints:
    def test_coder_includes_shared_constraints(self):
        agent = agent_for_role(AgentRole.CODER)
        task = make_task()
        prompt = agent.build_system_prompt(task)
        # shared constraints include these directives
        assert "incrementally" in prompt.lower()
        assert "guess" in prompt.lower() or "read" in prompt.lower()

    def test_writer_includes_shared_constraints(self):
        agent = agent_for_role(AgentRole.WRITER)
        task = make_task(role=AgentRole.WRITER)
        prompt = agent.build_system_prompt(task)
        assert "incrementally" in prompt.lower()

    def test_critic_shared_constraints_returns_empty(self):
        agent = agent_for_role(AgentRole.CRITIC)
        assert agent._shared_constraints() == ""


# ---------------------------------------------------------------------------
# _is_review_task heuristic
# ---------------------------------------------------------------------------

class TestIsReviewTask:
    def test_review_task_detected_by_title_prefix(self):
        task = make_review_task()
        assert _is_review_task(task) is True

    def test_non_review_task_not_detected(self):
        task = make_task(title="Refactor the foo module")
        assert _is_review_task(task) is False

    def test_partial_prefix_not_detected(self):
        task = make_task(title="Manager Review of something")
        assert _is_review_task(task) is False

    def test_empty_title_not_detected(self):
        task = make_task(title="")
        assert _is_review_task(task) is False