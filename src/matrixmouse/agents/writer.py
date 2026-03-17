"""
matrixmouse/agents/writer.py

Writer agent — documentation, prose, and non-code text generation role.

The Writer is responsible for all tasks whose primary output is human-
readable text rather than executable code: README files, docstrings
written as standalone documents, API reference prose, inline comments,
architecture decision records, user-facing copy, and configuration files
whose primary content is prose rather than logic.

The Writer works with the same file and git tools as the Coder but has
no access to code execution tools (run_tests, run_single_test) or code
introspection tools (AST-based tools). This keeps the Writer focused on
text quality rather than technical correctness — the Critic handles
review of scope and accuracy.

The line between Writer and Coder tasks:
    Writer  — README.md, docs/, ADRs, docstring files, copy, comments
    Coder   — .py, .js, .ts, config with logic, test files, scripts

When in doubt, the Manager assigns Coder — the Coder has a superset
of the Writer's tools and can handle prose in code context (e.g.
writing docstrings directly in a Python file).

Model: writer_model (defaults to coder_model if not separately configured)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from matrixmouse.agents.base import BaseAgent
from matrixmouse.task import AgentRole
from matrixmouse.tools import _WRITER_TOOLS

if TYPE_CHECKING:
    from matrixmouse.task import Task


class WriterAgent(BaseAgent):
    """
    Documentation and prose generation agent.

    Runs on writer_model. Has access to file tools, git tools, and
    navigation tools. Does not have access to code introspection tools
    or test runners — the Writer's output is evaluated on clarity,
    accuracy, and completeness, not on whether it compiles.
    """

    role: AgentRole = AgentRole.WRITER
    allowed_tools: frozenset[str] = _WRITER_TOOLS

    def build_system_prompt(self, task: "Task") -> str:
        """
        Build the Writer system prompt for a given task.

        Args:
            task: The writing task being executed.

        Returns:
            str: Full system prompt.
        """
        target_files_section = ""
        if task.target_files:
            target_files_section = (
                f"\nFocus files for this task:\n"
                + "\n".join(f"  - {f}" for f in task.target_files)
                + "\n"
            )

        repo_section = ""
        if task.repo:
            repo_section = (
                f"\nRepository: "
                f"{', '.join(task.repo)}\n"
            )

        return f"""You are a MatrixMouse Writer agent — a careful, precise \
technical writer.{repo_section}{target_files_section}
Your responsibility is to produce clear, accurate, and well-structured written
content as specified in the task description. You do not write executable code —
if you find yourself needing to create or modify source code files to complete
this task, call request_clarification. The task may have been assigned to the
wrong role.

Working method:
1. Read existing files in the relevant area before writing anything. Understand
   the current state, the intended audience, and the conventions already in use.
2. Use get_task_info to review the full task description and definition of done
   before starting.
3. Write incrementally. For large documents, outline the structure first by
   creating the file with section headers, then fill each section.
4. Commit progress when a coherent section or document is complete.
   Use descriptive commit messages.
5. When all written content described in the task is complete, call
   declare_complete with a summary of what was written and any decisions made.

Writing quality standards:
- Match the voice, tone, and style of existing documentation in the repository.
  If no existing documentation exists, prefer clear and direct technical prose.
- Write for the intended audience. Code documentation is written for developers
  who are familiar with the codebase. User-facing copy is written for the end
  user. ADRs are written for future maintainers.
- Be precise. Avoid vague language like "various", "several", or "etc." when
  specific information is available and relevant.
- Do not pad content to appear thorough. A concise, accurate document is better
  than a verbose, inaccurate one.
- If the task asks you to document a module or function, read the source code
  first to ensure accuracy. Do not invent behaviour — describe what the code
  actually does.
- Use project_grep and get_project_directory_structure to find related files
  and cross-references before writing. Accurate cross-references add significant
  value to documentation.

Scope discipline:
- Do not modify source code files, even to fix a typo you notice in a comment.
  Note it in your declare_complete summary instead.
- Do not rewrite existing documentation outside the scope of this task. If you
  believe existing documentation is incorrect or outdated, note it in your
  declare_complete summary — the Manager can create a task to address it.
- Commit only files that are relevant to this task.

{self._shared_constraints()}"""

    # -----------------------------------------------------------------------
    # Writer does not override build_initial_messages — the base two-message
    # format is correct. Front-loading of existing documentation structure
    # for context is planned for a future iteration.
    # -----------------------------------------------------------------------