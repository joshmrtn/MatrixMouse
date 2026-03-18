"""
tests/agents/test_writer.py

Tests for WriterAgent — prompt structure and tool contract.

Coverage:
    build_system_prompt:
        - Returns non-empty string
        - Mentions declare_complete
        - Warns against modifying source code
        - Mentions audience or accuracy (prose quality)
        - Includes repo name when set on task
        - Includes target_files when set on task
        - Includes shared constraints

    allowed_tools:
        - Has file read/write tools
        - Does not have code analysis tools
        - Does not have test tools
        - Does not have git commit tools
        - Does not have task write tools
        - Does not have approve or deny
"""

from matrixmouse.agents.writer import WriterAgent
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


class TestWriterBuildSystemPrompt:
    def test_returns_non_empty_string(self):
        agent = WriterAgent()
        assert len(agent.build_system_prompt(make_task())) > 100

    def test_mentions_declare_complete(self):
        agent = WriterAgent()
        assert "declare_complete" in agent.build_system_prompt(make_task())

    def test_warns_against_source_code_modification(self):
        agent = WriterAgent()
        prompt = agent.build_system_prompt(make_task())
        assert "source code" in prompt.lower() or "code file" in prompt.lower()

    def test_mentions_prose_quality_concept(self):
        agent = WriterAgent()
        prompt = agent.build_system_prompt(make_task())
        assert "audience" in prompt.lower() or "accurate" in prompt.lower()

    def test_includes_repo_when_set(self):
        agent = WriterAgent()
        task = make_task(repo=["docs-repo"])
        assert "docs-repo" in agent.build_system_prompt(task)

    def test_includes_target_files_when_set(self):
        agent = WriterAgent()
        task = make_task(target_files=["docs/guide.md"])
        assert "docs/guide.md" in agent.build_system_prompt(task)

    def test_includes_shared_constraints(self):
        agent = WriterAgent()
        prompt = agent.build_system_prompt(make_task())
        assert agent._shared_constraints() in prompt
        assert agent._shared_constraints() != ""


class TestWriterAllowedTools:
    def test_has_file_read_tool(self):
        assert "read_file" in WriterAgent().allowed_tools

    def test_has_file_write_tools(self):
        for tool in ("str_replace", "append_to_file"):
            assert tool in WriterAgent().allowed_tools

    def test_no_code_analysis_tools(self):
        for tool in ("get_function_def", "get_function_list", "get_class_summary"):
            assert tool not in WriterAgent().allowed_tools

    def test_no_test_tools(self):
        assert "run_tests" not in WriterAgent().allowed_tools
        assert "run_single_test" not in WriterAgent().allowed_tools

    def test_no_task_write_tools(self):
        for tool in ("create_task", "split_task", "update_task"):
            assert tool not in WriterAgent().allowed_tools

    def test_no_approve_deny(self):
        assert "approve" not in WriterAgent().allowed_tools
        assert "deny" not in WriterAgent().allowed_tools