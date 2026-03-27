"""
tests/agents/test_merge.py

Tests for MergeAgent — prompt structure and tool set.
"""

import pytest
from matrixmouse.agents.merge import MergeAgent
from matrixmouse.task import AgentRole, Task, TaskStatus


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


class TestMergeAgentPrompt:
    def test_build_system_prompt_non_empty(self):
        agent = MergeAgent()
        assert len(agent.build_system_prompt(make_task())) > 100

    def test_prompt_mentions_show_conflict(self):
        agent = MergeAgent()
        prompt = agent.build_system_prompt(make_task())
        assert "show_conflict" in prompt

    def test_prompt_mentions_resolve_conflict(self):
        agent = MergeAgent()
        prompt = agent.build_system_prompt(make_task())
        assert "resolve_conflict" in prompt

    def test_prompt_mentions_ours_theirs_manual(self):
        agent = MergeAgent()
        prompt = agent.build_system_prompt(make_task())
        assert "ours" in prompt
        assert "theirs" in prompt
        assert "manual" in prompt

    def test_prompt_includes_repo(self):
        agent = MergeAgent()
        prompt = agent.build_system_prompt(make_task(repo=["special-repo"]))
        assert "special-repo" in prompt

    def test_shared_constraints_empty(self):
        agent = MergeAgent()
        assert agent._shared_constraints() == ""

    def test_does_not_mention_declare_complete_in_prompt(self):
        """Merge agent should not be told to call declare_complete manually."""
        agent = MergeAgent()
        prompt = agent.build_system_prompt(make_task())
        # The prompt says merge is finalised automatically
        assert "automatically" in prompt

    def test_allowed_tools_contains_only_merge_tools(self):
        agent = MergeAgent()
        assert agent.allowed_tools == frozenset({
            "show_conflict",
            "resolve_conflict",
        })

    def test_allowed_tools_does_not_contain_task_tools(self):
        agent = MergeAgent()
        assert "split_task" not in agent.allowed_tools
        assert "create_task" not in agent.allowed_tools
        assert "get_git_diff" not in agent.allowed_tools

    def test_build_initial_messages_includes_system_prompt(self):
        agent = MergeAgent()
        task = make_task()
        messages = agent.build_initial_messages(task)
        assert messages[0]["role"] == "system"
        assert len(messages[0]["content"]) > 100

    def test_build_initial_messages_includes_context_messages(self):
        agent = MergeAgent()
        task = make_task()
        task.context_messages = [
            {"role": "user", "content": "[Merge Conflict Detected] foo.py"}
        ]
        messages = agent.build_initial_messages(task)
        assert any(
            "Merge Conflict Detected" in m.get("content", "")
            for m in messages
        )
