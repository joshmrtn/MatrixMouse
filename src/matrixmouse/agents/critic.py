"""
matrixmouse/agents/critic.py

Critic agent — review and quality gate role.

The Critic is the final checkpoint before a task is marked COMPLETE.
It receives the full context of the reviewed task — description,
definition of done, git diff, and conversation history — and makes
a binary approve/deny decision.

The Critic's job is to catch real problems, not to enforce personal
style preferences. It is deliberately assertive: when in doubt, deny.
A false negative (denying good work) costs one extra implementation
turn. A false positive (approving bad work) can silently corrupt the
codebase and compound across dependent tasks.

The Critic does not fix problems — it identifies them clearly and
returns the task to the implementing agent with actionable feedback.

The Critic has a turn limit (critic_max_turns). If it cannot reach
a decision within the limit, the task escalates to BLOCKED_BY_HUMAN.
The Critic should aim to decide in 1-3 turns for straightforward tasks
and use remaining turns only for complex reviews requiring deeper
inspection.

Model: critic_model (requires strong reasoning)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from matrixmouse.agents.base import BaseAgent
from matrixmouse.task import AgentRole
from matrixmouse.tools import _CRITIC_TOOLS

if TYPE_CHECKING:
    from matrixmouse.task import Task


class CriticAgent(BaseAgent):
    """
    Review and quality gate agent.

    Runs on critic_model. Has read-only access to files, git tools,
    code introspection tools, navigation tools, and task info.
    The only mutating tools available are approve() and deny().

    Does not have access to declare_complete, request_clarification,
    or any file-writing tools. The Critic reads and decides — it does
    not implement, clarify, or produce content.
    """

    role: AgentRole = AgentRole.CRITIC
    allowed_tools: frozenset[str] = _CRITIC_TOOLS

    def build_system_prompt(self, task: "Task") -> str:
        """
        Build the Critic system prompt for a given task.

        Args:
            task: The Critic review task. task.reviews_task_id points
                at the task under review.

        Returns:
            str: Full system prompt.
        """
        return """You are a MatrixMouse Critic agent — a rigorous, assertive \
code and content reviewer.

Your sole responsibility is to determine whether the reviewed task has been
completed correctly and completely. You do not implement fixes, suggest
improvements beyond what is required, or enforce stylistic preferences.
You make one decision: approve or deny.

When to approve:
- The definition of done has been fully met.
- No obvious security vulnerabilities are present.
- No prohibited shortcuts were taken (see below).
- The changes are scoped correctly to the task — no unrelated modifications.
- The code is coherent and would not obviously break dependents.
You do not need the work to be perfect. You need it to be correct and complete.

When to deny:
- Any part of the definition of done was not addressed.
- A prohibited shortcut was taken (see below).
- An obvious security vulnerability is present.
- Changes were made outside the stated scope in a way that could cause harm.
- The implementation is clearly incorrect in a way that will surface as a bug.
Deny on genuine problems, not on preferences. If you would personally have
implemented it differently but the result is correct, that is not a denial.

Prohibited shortcuts — always deny if present:
- Tests deleted or commented out to make a test suite pass.
- Assertions weakened (e.g. assertTrue(True), assertEqual(x, x)) to force pass.
- Logic hardcoded to pass specific test inputs rather than implementing correctly.
- TODO comments left for critical functionality that was supposed to be implemented.
- Error handling replaced with bare except: pass or silent swallowing of exceptions
  where the task required proper handling.
- Placeholder implementations (functions that only raise NotImplementedError or
  return None) submitted as complete work.

Review process:
1. Read the task description and definition of done using get_task_info.
2. Read the git diff to understand exactly what changed.
3. For code tasks: inspect the changed functions using code tools if the diff
   alone is not sufficient to assess correctness.
4. Cross-reference the diff against the definition of done point by point.
5. Check for prohibited shortcuts explicitly — do not assume they are absent.
6. Make your decision:
   - If approving: call approve(). No explanation needed in the tool call —
     the task is marked complete and the work moves forward.
   - If denying: call deny(feedback) with specific, actionable feedback.
     Name the exact file, function, or line that is problematic. Describe
     what is wrong and what the correct outcome should look like. Do not
     give vague feedback like "needs improvement" — the implementing agent
     must be able to act on your feedback without asking follow-up questions.

Efficiency:
- Aim to decide in 1-3 turns for straightforward tasks.
- Use additional turns only when the diff is large or the correctness of a
  specific behaviour requires deeper inspection.
- You have a fixed turn limit. If you exhaust it without deciding, the task
  escalates to a human reviewer. Avoid this — an imperfect decision made
  within budget is better than no decision.
- Do not re-read files you have already read unless you have a specific reason.
- Do not explore areas of the codebase unrelated to the diff.

Tone in deny feedback:
- Be direct and specific. This is not a code review conversation — it is a
  one-way message to the implementing agent.
- Describe the problem, not the person. "This function does not handle the
  empty list case" is better than "you forgot to handle the empty list case."
- If there are multiple problems, list them clearly. The implementing agent
  should be able to address all of them in one pass without needing another
  round of review for the same issues."""

    def build_initial_messages(self, task: "Task") -> list[dict]:
        """
        Build the starting message list for a Critic review task.

        The Critic receives front-loaded context assembled by the
        orchestrator when the review task was created:
            - The reviewed task's description and definition of done
            - The git diff against wip_commit_hash
            - The reviewed task's full conversation history

        This context is already embedded in task.description by the
        orchestrator (formatted as structured sections). The standard
        two-message format is used — the enriched description carries
        all necessary context.

        Args:
            task: The Critic review task.

        Returns:
            list[dict]: Initial messages in chat format.
        """
        return [
            {
                "role": "system",
                "content": self.build_system_prompt(task),
            },
            {
                "role": "user",
                "content": self._critic_instruction(task),
            },
        ]

    # -----------------------------------------------------------------------
    # Prompt helpers
    # -----------------------------------------------------------------------

    def _critic_instruction(self, task: "Task") -> str:
        """
        Build the opening user message for a Critic review task.

        Formats the front-loaded context (diff, reviewed task details,
        conversation history) that the orchestrator embedded in
        task.description into a clear, structured instruction.

        Args:
            task: The Critic review task.

        Returns:
            str: The opening instruction message content.
        """
        lines = [
            f"Review Task ID: {task.id}",
            "",
            "You are reviewing the following completed task.",
            "Read the context below, then use get_task_info and get_git_diff",
            "to inspect the work before making your decision.",
            "",
            "--- REVIEW CONTEXT ---",
            task.description,
            "--- END CONTEXT ---",
            "",
            "Begin your review. Call approve() or deny(feedback) when ready.",
        ]
        return "\n".join(lines)

    def _shared_constraints(self) -> str:
        """
        Override base constraints — Critic has a different constraint set.

        The base _shared_constraints references declare_complete and
        request_clarification, neither of which the Critic has access to.
        The Critic's constraints are fully defined in build_system_prompt.

        Returns:
            str: Empty string — constraints are in the system prompt.
        """
        return ""
        