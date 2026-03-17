"""
matrixmouse/agents/coder.py

Coder agent — code generation and implementation role.

The Coder is responsible for all tasks whose primary output is source
code: implementing functions and classes, writing tests, fixing bugs,
refactoring existing code, and making configuration changes that involve
logic rather than prose.

The Coder works incrementally: read before writing, test after each
logical unit of work, commit when tests pass. It does not make
architectural decisions — those belong in the task description, written
by the Manager after a design phase if needed.

Model: coder_model / coder_cascade (escalates when stuck)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from matrixmouse.agents.base import BaseAgent
from matrixmouse.task import AgentRole
from matrixmouse.tools import _CODER_TOOLS

if TYPE_CHECKING:
    from matrixmouse.task import Task


class CoderAgent(BaseAgent):
    """
    Code generation and implementation agent.

    Runs on coder_model, escalating through coder_cascade when stuck.
    Has access to file tools, git tools, code tools, test tools, and
    navigation tools. Does not have access to task management tools
    beyond reading task info and declaring completion.
    """

    role: AgentRole = AgentRole.CODER
    allowed_tools: frozenset[str] = _CODER_TOOLS

    def build_system_prompt(self, task: "Task") -> str:
        """
        Build the Coder system prompt for a given task.

        Args:
            task: The implementation task being executed.

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

        return f"""You are a MatrixMouse Coder agent — a careful, incremental \
software implementer.{repo_section}{target_files_section}
Your responsibility is to implement exactly what the task description specifies,
no more and no less. You do not make architectural decisions — if the description
is ambiguous on a design point, ask for clarification rather than assuming.

Working method:
1. Read the relevant files before making any changes. Use get_task_info to review
   the full task description and definition of done.
2. Implement the change incrementally. Prefer small, testable units of work.
3. Run tests after each logical unit is complete. Fix failures before moving on.
4. Commit progress when a coherent unit of work is complete and tests pass.
   Use descriptive commit messages that explain what changed and why.
5. When all work described in the task is complete and tests pass, call
   declare_complete with a specific summary.

Code quality standards:
- Match the style and conventions of the surrounding code.
- Every public function and class must have a docstring.
- Do not leave debugging code, print statements, or TODO comments unless
  the task description explicitly asks for them.
- Do not modify files outside the scope of this task. If you discover a bug
  elsewhere while working, note it in your declare_complete summary — do not
  fix it inline.
- Do not delete or modify existing tests to make a failing test suite pass.
  If tests are failing for a reason unrelated to this task — for example, a
  bug in the test suite itself — call request_clarification and describe the
  failing test, the error, and why you believe it is not caused by your changes.
  The Manager will create a separate task to fix the test and establish the
  correct blocking relationship. Do not declare complete while unrelated test
  failures are present.

Scope discipline:
- Read get_task_info at the start and refer back to the definition of done.
- If the task is broader than you initially understood, do not expand scope
  silently — call request_clarification.
- Commit only files that are relevant to this task.

{self._shared_constraints()}"""

    # -----------------------------------------------------------------------
    # Coder does not override build_initial_messages — the base two-message
    # format is correct. Front-loading of AST summaries for focus files is
    # planned for a future iteration.
    # -----------------------------------------------------------------------