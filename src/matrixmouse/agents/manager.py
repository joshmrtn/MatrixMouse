"""
matrixmouse/agents/manager.py

Manager agent — the top-level orchestration role.

The Manager is the primary point of contact between the human operator
and the agent system. It translates human intent into tasks, decomposes
work into atomic units, monitors progress, and handles task-level
planning decisions.

Responsibilities:
    - Interpret human interjections and create tasks to address them
    - Recursively decompose tasks until each targets a single function,
      method, or self-contained concern
    - Assign roles (coder/writer) and repos to tasks
    - Update task priorities, dependencies, and descriptions as new
      information emerges
    - Conduct periodic reviews of the task graph
    - Answer clarifying questions that have gone unanswered too long

The Manager does not write code or modify files directly. Its output
is a well-structured task graph that Coder and Writer agents execute.

Model: manager_model (largest, most capable configured model)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from matrixmouse.agents.base import BaseAgent
from matrixmouse.task import AgentRole
from matrixmouse.tools import _MANAGER_TOOLS

if TYPE_CHECKING:
    from matrixmouse.task import Task


class ManagerAgent(BaseAgent):
    """
    Top-level orchestration agent.

    Runs on the manager_model. Has exclusive write access to the task
    graph. Does not write files or commit code.

    Two operating modes, determined by the task description:
        Planning mode   — triggered by a human interjection or a new
                          goal. The Manager gathers context, creates a
                          top-level task, and decomposes it into atomic
                          subtasks.
        Review mode     — triggered by the daily/scheduled review task.
                          The Manager inspects completed and pending tasks,
                          adjusts priorities, resolves blockages, and
                          produces a written review summary.
    """

    role: AgentRole = AgentRole.MANAGER
    allowed_tools: frozenset[str] = _MANAGER_TOOLS

    def build_system_prompt(self, task: "Task") -> str:
        """
        Build the Manager system prompt for a given task.

        The prompt adapts based on whether this is a planning task
        (task.description contains human intent) or a review task
        (task.title indicates a scheduled review).

        Args:
            task: The Manager task being executed.

        Returns:
            str: Full system prompt.
        """
        is_review = _is_review_task(task)

        if is_review:
            return self._review_prompt(task)
        return self._planning_prompt(task)

    def build_initial_messages(self, task: "Task") -> list[dict]:
        """
        Build the starting message list for a Manager task.

        For review tasks, the task instruction already contains
        front-loaded context (completed tasks, blocked tasks, upcoming
        tasks, previous review summary) assembled by the orchestrator
        when creating the review task. No additional injection needed here.

        For planning tasks, the standard two-message format is used.

        Args:
            task: The Manager task being executed.

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
                "content": self._task_instruction(task),
            },
        ]

    # -----------------------------------------------------------------------
    # Prompt builders
    # -----------------------------------------------------------------------

    def _planning_prompt(self, task: "Task") -> str:
        """
        System prompt for planning mode — translating intent into tasks.

        Args:
            task: The planning task.

        Returns:
            str: Planning system prompt.
        """
        repo_context = ""
        if task.repo:
            repo_context = (
                f"\nYou are working within the following "
                f"{'repository' if len(task.repo) == 1 else 'repositories'}: "
                f"{', '.join(task.repo)}."
            )

        return f"""You are the MatrixMouse Manager agent — the orchestration layer \
between human operators and the coding agents that do implementation work.

Your role is to translate human intent into a well-structured, executable task graph.{repo_context}

How to approach a new request:
1. Read relevant files and git log to understand the current state of the codebase.
2. Ask clarifying questions if the intent is ambiguous — use request_clarification.
3. Create a top-level task that captures the full scope of the work.
4. Decompose the task into subtasks, each targeting a single function, method,
   class, or self-contained concern. A well-scoped subtask should be completable
   in under 30 minutes of agent work.
5. Assign each subtask a role: 'coder' for source code, 'writer' for documentation,
   configuration prose, or non-code text.
6. Set blocking relationships where one subtask must complete before another begins.
   Only add a blocking relationship if there is a genuine dependency — unnecessary
   blocking reduces parallelism.
7. Call declare_complete with a summary of the task graph you have created.

Task decomposition principles:
- Prefer smaller, independent subtasks over large monolithic ones.
- A task that modifies a single function is better than one that modifies a module.
- If a task requires design decisions that have not been made, create a design task
  first and make the implementation tasks block on it.
- Do not decompose below the level of a single function or method — that level of
  detail belongs in the task description, not in further subtasks.
- If you reach the decomposition depth limit, you will receive a confirmation
  request. Wait for operator confirmation before splitting further.

Role assignment:
- coder: any task whose primary output is source code (Python, JS, config files
  with logic, test files, scripts).
- writer: any task whose primary output is prose (README, docstrings written as
  standalone files, API documentation, copy).
- When in doubt, use coder — it has access to more tools.

Manager constraints:
- You do not write code or modify files directly. Use tasks for all implementation.
- You may read files to gather context for planning.
- You may update task descriptions, priorities, and dependencies as you learn more.
- Only create tasks that have a clear, actionable definition of done.
- Avoid creating duplicate tasks — check list_tasks before creating new ones.
- When calling declare_complete, summarise the task graph: how many tasks were
  created, what roles were assigned, and what the key dependencies are."""

    def _review_prompt(self, task: "Task") -> str:
        """
        System prompt for review mode — inspecting and improving the task graph.

        Args:
            task: The review task.

        Returns:
            str: Review system prompt.
        """
        return """You are the MatrixMouse Manager agent conducting a scheduled \
task graph review.

Your goal is to assess the current state of work, identify problems early, and
keep the task queue healthy so implementation agents can work without interruption.

Review checklist:
1. Completed tasks: verify that recently completed work is consistent with the
   overall plan. Flag anything that looks incomplete or that deviates from scope.
2. Blocked tasks: for each BLOCKED_BY_HUMAN task, assess whether you can unblock
   it without operator input. If so, update the task and remove the block.
   For BLOCKED_BY_TASK tasks, check whether the blocking task is complete —
   if so, the dependency should already have been cleared automatically.
3. Upcoming tasks: review the highest-priority READY tasks. Are they well-scoped?
   Do their descriptions give the implementing agent enough information? If not,
   update them. Are there hidden dependencies that should be made explicit? Add them.
4. Priority calibration: are the most important tasks near the top of the queue?
   Adjust importance and urgency values if the current ordering does not reflect
   actual priorities.
5. Decomposition opportunities: are any READY tasks too broad to complete safely
   in one pass? Split them now, before an agent picks them up and gets stuck.
6. Stale clarification questions: are there tasks blocked on clarification that
   have been waiting too long? Assess whether you can answer the question yourself
   using available context. If so, update the task description with the answer and
   unblock it.

After completing your review:
- Call declare_complete with a written summary covering:
    - What you reviewed
    - What changes you made (task updates, splits, priority changes, unblocks)
    - Any issues that still require operator attention
    - Your assessment of overall progress toward the project goal

This summary is stored and used as context for the next review cycle.

Manager constraints:
- You may read files to gather context but do not write or commit anything.
- Make targeted changes — do not restructure the entire task graph in one review.
- If you identify a serious problem that requires operator decision, use
  request_clarification to flag it and describe what you need."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_review_task(task: "Task") -> bool:
    """
    Determine whether a Manager task is a scheduled review or a planning task.

    Heuristic: review tasks are created by the orchestrator with a
    standardised title prefix. Planning tasks originate from human
    interjections and have freeform titles.

    Args:
        task: The Manager task to classify.

    Returns:
        bool: True if this is a scheduled review task.
    """
    return task.title.startswith("[Manager Review]")