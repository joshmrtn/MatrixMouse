"""
matrixmouse/agents/merge.py

MergeAgent — resolves git merge conflicts on behalf of a task.

Activated when a task's merge-up-to-parent produces conflicts. The
original task's role is mutated to MERGE and it re-enters the queue.
The MergeAgent runs with a restricted tool set (show_conflict,
resolve_conflict) using the highest available model.

The agent is non-preemptable — once started it runs to completion
or turn limit. Time slices do not apply.

Tools:
    show_conflict    — inspect conflict details for a file
    resolve_conflict — apply a resolution (ours/theirs/manual)
                       auto-continues the merge when all conflicts resolved
"""

from __future__ import annotations

from matrixmouse.agents.base import BaseAgent
from matrixmouse.task import AgentRole, Task
from matrixmouse.tools import _MERGE_TOOLS


class MergeAgent(BaseAgent):
    """
    Agent for resolving git merge conflicts.

    Receives a task whose branch has a merge conflict against its
    parent branch. Uses show_conflict and resolve_conflict to resolve
    each conflicted file. The merge is finalised automatically when all
    conflicts are resolved.
    """
    role: AgentRole = AgentRole.MERGE
    allowed_tools: frozenset[str] = _MERGE_TOOLS

    def build_system_prompt(self, task: Task) -> str:
        repo_str = (
            f" in {', '.join(task.repo)}" if task.repo else ""
        )
        return (
            f"You are a Merge Conflict Resolution Agent{repo_str}.\n\n"
            "A git merge has produced conflicts that require your judgment "
            "to resolve. Your role is to examine each conflicted file and "
            "decide which changes to keep.\n\n"
            "Available tools:\n"
            "  show_conflict(file)  — shows the conflicting versions side by "
            "side: ours (current branch), theirs (branch being merged), "
            "and the common base.\n"
            "  resolve_conflict(file, resolution, content=None) — apply your "
            "decision. resolution must be one of:\n"
            "    'ours'   — keep the current branch version\n"
            "    'theirs' — keep the merging branch version\n"
            "    'manual' — provide a merged version via the content parameter\n\n"
            "The merge is finalised automatically once all conflicts are "
            "resolved. You do not need to call any additional tool to complete "
            "the merge.\n\n"
            "Resolution principles:\n"
            "  - Prefer 'ours' when the merging branch made unrelated changes "
            "to a file you modified intentionally.\n"
            "  - Prefer 'theirs' when the merging branch has a clearly better "
            "or more complete version.\n"
            "  - Use 'manual' when both sides have valuable changes that should "
            "be combined. Provide the complete merged file content.\n"
            "  - When in doubt, prefer correctness over completeness — a "
            "working subset is better than a broken whole.\n\n"
            "Be systematic: use show_conflict on each file before resolving it. "
            "Never resolve a file without first inspecting both versions."
        )

    def _shared_constraints(self) -> str:
        """
        Merge agent has no shared constraints — it operates with a
        minimal, focused tool set and does not need general coding rules.
        """
        return ""

    def build_initial_messages(self, task: Task) -> list:
        """
        Build the initial message list for a merge resolution session.

        The system prompt is followed by the conflict notification that
        was appended to context_messages when the role was mutated, so
        the agent immediately knows which files are in conflict.
        """
        messages = [
            {
                "role": "system",
                "content": self.build_system_prompt(task),
            }
        ]
        # Include existing context messages — the conflict notification
        # is already there from the role transition
        messages.extend(task.context_messages)
        return messages
    
    