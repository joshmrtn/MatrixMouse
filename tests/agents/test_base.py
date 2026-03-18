"""
tests/agents/test_base.py

Tests for the BaseAgent contract — registry, allowed_tools, and
the concrete methods defined on BaseAgent that all subclasses inherit.

Does not test role-specific prompt content (see test_manager.py,
test_critic.py, test_coder.py, test_writer.py).

Coverage:
    agent_for_role registry:
        - Returns correct concrete class for each role
        - Raises KeyError for unknown role
        - Returns a new instance on each call

    allowed_tools contract:
        - Every agent exposes allowed_tools as a frozenset
        - No agent has an empty allowed_tools
        - allowed_tools matches tools_for_role for that agent's role

    build_initial_messages (BaseAgent concrete method):
        - Returns a list of at least two dicts
        - First message has role 'system'
        - Second message has role 'user'
        - System message content matches build_system_prompt output
        - User message contains task id
        - User message contains task title
        - User message contains task description
        - User message contains notes when set
        - User message contains target_files when set

    _task_instruction (BaseAgent concrete method):
        - Returns a non-empty string for any task
        - Contains task id
        - Contains task title
        - Contains task description

    __repr__:
        - Returns a string
        - Contains the role name
"""

import pytest
from matrixmouse.agents import agent_for_role
from matrixmouse.agents.manager import ManagerAgent
from matrixmouse.agents.coder import CoderAgent
from matrixmouse.agents.writer import WriterAgent
from matrixmouse.agents.critic import CriticAgent
from matrixmouse.task import AgentRole, Task
from matrixmouse.tools import tools_for_role


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_task(
    title: str = "Test task",
    description: str = "Do the thing carefully.",
    role: AgentRole = AgentRole.CODER,
    repo: list[str] | None = None,
    **kwargs,
) -> Task:
    return Task(
        title=title,
        description=description,
        role=role,
        repo=repo if repo is not None else ["repo"],
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class TestAgentForRole:
    def test_manager_role_returns_manager_agent(self):
        assert isinstance(agent_for_role(AgentRole.MANAGER), ManagerAgent)

    def test_coder_role_returns_coder_agent(self):
        assert isinstance(agent_for_role(AgentRole.CODER), CoderAgent)

    def test_writer_role_returns_writer_agent(self):
        assert isinstance(agent_for_role(AgentRole.WRITER), WriterAgent)

    def test_critic_role_returns_critic_agent(self):
        assert isinstance(agent_for_role(AgentRole.CRITIC), CriticAgent)

    def test_unknown_role_raises_key_error(self):
        with pytest.raises(KeyError):
            agent_for_role("nonexistent_role") # type: ignore[arg-type]

    def test_returns_new_instance_each_call(self):
        a1 = agent_for_role(AgentRole.CODER)
        a2 = agent_for_role(AgentRole.CODER)
        assert a1 is not a2


# ---------------------------------------------------------------------------
# allowed_tools contract
# ---------------------------------------------------------------------------

class TestAllowedToolsContract:
    def test_all_agents_expose_allowed_tools_as_frozenset(self):
        for role in AgentRole:
            agent = agent_for_role(role)
            assert isinstance(agent.allowed_tools, frozenset), \
                f"{role} allowed_tools is not a frozenset"

    def test_no_agent_has_empty_allowed_tools(self):
        for role in AgentRole:
            agent = agent_for_role(role)
            assert len(agent.allowed_tools) > 0, \
                f"{role} has empty allowed_tools"

    def test_allowed_tools_matches_tools_for_role(self):
        for role in AgentRole:
            agent = agent_for_role(role)
            assert agent.allowed_tools == tools_for_role(role), \
                f"{role} allowed_tools does not match tools_for_role"


# ---------------------------------------------------------------------------
# build_initial_messages
# ---------------------------------------------------------------------------

class TestBuildInitialMessages:
    def test_returns_list_for_all_roles(self):
        for role in AgentRole:
            agent = agent_for_role(role)
            task = make_task(role=role)
            msgs = agent.build_initial_messages(task)
            assert isinstance(msgs, list)

    def test_at_least_two_messages_for_all_roles(self):
        for role in AgentRole:
            agent = agent_for_role(role)
            task = make_task(role=role)
            msgs = agent.build_initial_messages(task)
            assert len(msgs) >= 2, \
                f"{role} returned fewer than 2 messages"

    def test_first_message_is_system(self):
        for role in AgentRole:
            agent = agent_for_role(role)
            msgs = agent.build_initial_messages(make_task(role=role))
            assert msgs[0]["role"] == "system"

    def test_second_message_is_user(self):
        for role in AgentRole:
            agent = agent_for_role(role)
            msgs = agent.build_initial_messages(make_task(role=role))
            assert msgs[1]["role"] == "user"

    def test_system_content_matches_build_system_prompt(self):
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

    def test_user_message_contains_title(self):
        agent = agent_for_role(AgentRole.CODER)
        task = make_task(title="Specific title here")
        msgs = agent.build_initial_messages(task)
        assert "Specific title here" in msgs[1]["content"]

    def test_user_message_contains_description(self):
        agent = agent_for_role(AgentRole.CODER)
        task = make_task(description="Very specific description.")
        msgs = agent.build_initial_messages(task)
        assert "Very specific description." in msgs[1]["content"]

    def test_user_message_contains_notes_when_set(self):
        agent = agent_for_role(AgentRole.CODER)
        task = make_task(notes="Previous attempt failed at line 42.")
        msgs = agent.build_initial_messages(task)
        assert "Previous attempt failed at line 42." in msgs[1]["content"]

    def test_user_message_contains_target_files_when_set(self):
        agent = agent_for_role(AgentRole.WRITER)
        task = make_task(
            role=AgentRole.WRITER,
            target_files=["docs/guide.md"],
        )
        msgs = agent.build_initial_messages(task)
        assert "docs/guide.md" in msgs[1]["content"]

    def test_all_messages_are_dicts_with_role_and_content(self):
        for role in AgentRole:
            agent = agent_for_role(role)
            msgs = agent.build_initial_messages(make_task(role=role))
            for msg in msgs:
                assert "role" in msg
                assert "content" in msg


# ---------------------------------------------------------------------------
# _task_instruction
# ---------------------------------------------------------------------------

class TestTaskInstruction:
    def test_returns_non_empty_string(self):
        for role in AgentRole:
            agent = agent_for_role(role)
            task = make_task(role=role)
            result = agent._task_instruction(task)
            assert isinstance(result, str)
            assert len(result) > 0

    def test_contains_task_id(self):
        agent = agent_for_role(AgentRole.CODER)
        task = make_task()
        assert task.id in agent._task_instruction(task)

    def test_contains_task_title(self):
        agent = agent_for_role(AgentRole.CODER)
        task = make_task(title="Unique title string")
        assert "Unique title string" in agent._task_instruction(task)

    def test_contains_description(self):
        agent = agent_for_role(AgentRole.CODER)
        task = make_task(description="Unique description string.")
        assert "Unique description string." in agent._task_instruction(task)


# ---------------------------------------------------------------------------
# __repr__
# ---------------------------------------------------------------------------

class TestRepr:
    def test_returns_string(self):
        for role in AgentRole:
            agent = agent_for_role(role)
            assert isinstance(repr(agent), str)

    def test_contains_role_name(self):
        for role in AgentRole:
            agent = agent_for_role(role)
            assert role.value in repr(agent).lower() or \
                   role.name.lower() in repr(agent).lower()
            