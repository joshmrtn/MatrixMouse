"""
tests/agents/test_coder.py

Tests for CoderAgent — prompt structure and tool contract.

Prompt tests check structure and behavioural contracts only.

Coverage:
    build_system_prompt:
        - Returns non-empty string
        - Mentions declare_complete
        - Mentions testing (Coder must run tests before completing)
        - Mentions committing work
        - Includes repo name when set on task
        - Includes target_files when set on task
        - Includes shared constraints

    allowed_tools:
        - Has file read/write tools
        - Has git tools
        - Has test tools
        - Does not have task write tools (create_task, split_task, update_task)
        - Does not have approve or deny
        - Does not have request_clarification (Coder uses comms tool directly)
"""

from matrixmouse.agents.coder import CoderAgent
from matrixmouse.task import AgentRole, Task


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


class TestCoderBuildSystemPrompt:
    def test_returns_non_empty_string(self):
        agent = CoderAgent()
        assert len(agent.build_system_prompt(make_task())) > 100

    def test_mentions_declare_complete(self):
        agent = CoderAgent()
        assert "declare_complete" in agent.build_system_prompt(make_task())

    def test_mentions_testing(self):
        agent = CoderAgent()
        prompt = agent.build_system_prompt(make_task())
        assert "test" in prompt.lower()

    def test_mentions_commit(self):
        agent = CoderAgent()
        prompt = agent.build_system_prompt(make_task())
        assert "commit" in prompt.lower()

    def test_includes_repo_when_set(self):
        agent = CoderAgent()
        task = make_task(repo=["special-repo"])
        assert "special-repo" in agent.build_system_prompt(task)

    def test_includes_target_files_when_set(self):
        agent = CoderAgent()
        task = make_task(target_files=["src/foo.py"])
        assert "src/foo.py" in agent.build_system_prompt(task)

    def test_includes_shared_constraints(self):
        agent = CoderAgent()
        prompt = agent.build_system_prompt(make_task())
        assert agent._shared_constraints() in prompt
        assert agent._shared_constraints() != ""


class TestCoderAllowedTools:
    def test_has_file_read_tool(self):
        assert "read_file" in CoderAgent().allowed_tools

    def test_has_file_write_tools(self):
        for tool in ("str_replace", "append_to_file"):
            assert tool in CoderAgent().allowed_tools

    def test_has_git_tools(self):
        for tool in ("get_git_diff", "get_git_log", "git_commit"):
            assert tool in CoderAgent().allowed_tools

    def test_has_test_tools(self):
        for tool in ("run_tests", "run_single_test"):
            assert tool in CoderAgent().allowed_tools

    def test_no_task_write_tools(self):
        for tool in ("create_task", "split_task", "update_task"):
            assert tool not in CoderAgent().allowed_tools

    def test_no_approve_deny(self):
        assert "approve" not in CoderAgent().allowed_tools
        assert "deny" not in CoderAgent().allowed_tools
        