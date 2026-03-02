"""
matrixmouse/scheduling.py

Determines which task the agent should work on next.

Responsibilities:
    - Filtering tasks to those that are ready (unblocked, non-terminal)
    - Scoring tasks by priority (Eisenhower matrix + aging bonus)
    - Returning the highest-priority ready task

Current implementation: simple priority queue.

TODO (future):
    - Round-robin repo time allocation
      e.g., if 3 repos have active tasks, spend equal time on each
    - Time-boxing: max hours per repo per day/week
    - Weighted repo priority (some repos more important than others)
    - Cross-repo task awareness (tasks spanning multiple repos)
    - Re-scoring based on external signals (new GitHub issue, human urgency bump)

Do not add inference logic or tool dispatch here.
"""

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Scheduling result
# ---------------------------------------------------------------------------

@dataclass
class SchedulingDecision:
    """
    The result of a scheduling pass.
    Bundles the chosen task with diagnostic information so the orchestrator
    can log why a particular task was chosen.
    """
    task: "Task | None"
    reason: str
    candidates_considered: int
    total_active: int


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------

class Scheduler:
    """
    Selects the next task to work on from the task queue.

    Instantiated by the session orchestrator and called at the start
    of each scheduling cycle.

    Usage:
        scheduler = Scheduler(config)
        decision = scheduler.next(queue)
        if decision.task:
            orchestrator.run_task(decision.task)
    """

    def __init__(self, config: "MatrixMouseConfig"):
        """
        Args:
            config: Active config. Used for priority weights and aging rate.
        """
        self.config = config

    def next(self, queue: "TaskQueue") -> SchedulingDecision:
        """
        Select the highest-priority unblocked task from the queue.

        A task is eligible if:
            - Its status is PENDING (not active, blocked, or terminal)
            - All tasks in its blocked_by list are complete

        Args:
            queue: The workspace-level TaskQueue.

        Returns:
            SchedulingDecision with the chosen task (or None if nothing
            is ready to work on).
        """
        from matrixmouse.orchestrator import TaskStatus

        all_active = queue.active_tasks()
        completed = queue.completed_ids()

        # Filter to tasks that are actually ready to start
        candidates = [
            t for t in all_active
            if t.status == TaskStatus.PENDING and t.is_ready(completed)
        ]

        if not candidates:
            if all_active:
                # Tasks exist but none are ready — all blocked
                reason = (
                    f"{len(all_active)} active task(s) exist but none are "
                    f"ready to schedule. All are blocked or awaiting human input."
                )
            else:
                reason = "Task queue is empty."

            logger.info("Scheduler: no task selected. %s", reason)
            return SchedulingDecision(
                task=None,
                reason=reason,
                candidates_considered=0,
                total_active=len(all_active),
            )

        # Score and sort — highest priority first
        aging_rate = getattr(self.config, "priority_aging_rate", 0.01)
        max_aging  = getattr(self.config, "priority_max_aging_bonus", 0.3)

        scored = sorted(
            candidates,
            key=lambda t: t.priority_score(aging_rate, max_aging),
            reverse=True,
        )

        chosen = scored[0]
        score = chosen.priority_score(aging_rate, max_aging)

        reason = (
            f"Selected task {chosen.id} '{chosen.title}' "
            f"(score: {score:.3f}, importance: {chosen.importance}, "
            f"urgency: {chosen.urgency}) "
            f"from {len(candidates)} candidate(s)."
        )
        logger.info("Scheduler: %s", reason)

        return SchedulingDecision(
            task=chosen,
            reason=reason,
            candidates_considered=len(candidates),
            total_active=len(all_active),
        )

    def report_blocked(self, queue: "TaskQueue") -> str:
        """
        Return a human-readable summary of blocked tasks.
        Useful for the web UI and CLI status commands.

        Args:
            queue: The workspace-level TaskQueue.

        Returns:
            Formatted string describing all blocked tasks and why.
        """
        from matrixmouse.orchestrator import TaskStatus

        blocked_by_task  = [t for t in queue.active_tasks()
                            if t.status == TaskStatus.BLOCKED_BY_TASK]
        blocked_by_human = [t for t in queue.active_tasks()
                            if t.status == TaskStatus.BLOCKED_BY_HUMAN]

        if not blocked_by_task and not blocked_by_human:
            return "No blocked tasks."

        lines = []

        if blocked_by_human:
            lines.append(f"Blocked by human ({len(blocked_by_human)}):")
            for t in blocked_by_human:
                lines.append(f"  [{t.id}] {t.title}")
                if t.notes:
                    lines.append(f"        {t.notes.splitlines()[-1]}")

        if blocked_by_task:
            lines.append(f"Blocked by dependencies ({len(blocked_by_task)}):")
            for t in blocked_by_task:
                lines.append(
                    f"  [{t.id}] {t.title} — waiting on: "
                    f"{', '.join(t.blocked_by)}"
                )

        return "\n".join(lines)
