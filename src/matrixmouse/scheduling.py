"""
matrixmouse/scheduling.py

Multi-level feedback queue scheduler for MatrixMouse.

Scheduling model
----------------
Tasks are distributed across three priority queues based on their
priority score (lower score == higher priority):

    P1  score < p1_threshold          highest priority, longest slice
    P2  p1_threshold <= score < p2_threshold
    P3  score >= p2_threshold         lowest priority, shortest slice

Within each queue, tasks are ordered by priority score (ascending).
The scheduler works through queues top-to-bottom, giving each queue
its full time slice before moving to the next. Once all queues have
had a turn, the cycle repeats from P1.

Preemption
----------
Certain high-urgency tasks (Manager review injections, interjection
handling) are flagged with preempt=True. When a preempting task is
present, the current task's time slice is marked expired and the
preempting task is inserted at the front of P1. Preemption never
interrupts inference — it takes effect at the next scheduling decision.

Time slice tracking
-------------------
time_slice_started is set to time.monotonic() when a task moves to
RUNNING. The orchestrator checks elapsed time after each inference call.
Slice expiry is a soft limit — if inference begins at 59m on a 60m
slice, it completes before the switch occurs.

Adaptive slices (optional, disabled by default)
------------------------------------------------
When scheduler_adaptive = true, the scheduler tracks context switch
time as an exponential moving average and adjusts slice lengths up or
down by scheduler_adaptive_step_minutes to keep switch overhead within
target bounds (scheduler_adaptive_min_pct / scheduler_adaptive_max_pct
of the slice length).

Priority score convention
-------------------------
Lower score == higher priority (0.0 = most urgent).
See task.py for the scoring formula.

Do not add inference logic or tool dispatch here.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Queue level constants
# ---------------------------------------------------------------------------

P1 = 1
P2 = 2
P3 = 3


# ---------------------------------------------------------------------------
# SchedulingDecision
# ---------------------------------------------------------------------------

@dataclass
class SchedulingDecision:
    """
    Result of a scheduling pass.

    Bundles the chosen task with diagnostic information so the orchestrator
    can log why a particular task was chosen (or why nothing was).
    """
    task: "Task | None"
    reason: str
    queue_level: int | None           # P1 / P2 / P3, or None if no task
    candidates_considered: int
    total_active: int
    preempted: bool = False           # True if a preempting task jumped the queue


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------

class Scheduler:
    """
    Multi-level feedback queue scheduler.

    Instantiated once by the orchestrator. Called after every inference
    call to check for time slice expiry and after every task completion
    to select the next task.

    State
    -----
    _current_queue_level    Which queue level is currently being served.
    _switch_ema             Exponential moving average of context switch
                            time in seconds. Used by the adaptive heuristic.
    _slice_overrides        Per-level slice minute overrides set by the
                            adaptive heuristic. Starts empty; config values
                            are used when no override is present.
    """

    _EMA_ALPHA = 0.2          # smoothing factor for switch time EMA
    _EMA_INITIAL = 30.0       # initial EMA value in seconds (conservative)

    def __init__(self, config: "MatrixMouseConfig"):
        self.config = config
        self._current_queue_level: int = P1
        self._switch_ema: float = self._EMA_INITIAL
        self._slice_overrides: dict[int, float] = {}  # level -> minutes
        self._last_served_level: int = P1 # TODO: persist across restarts via workspace state

    # -----------------------------------------------------------------------
    # Public interface
    # -----------------------------------------------------------------------

    def next(self, queue: "TaskQueue") -> SchedulingDecision:
        """
        Select the next task to run.

        Call order:
            1. Check for preempting tasks (Manager review, interjections).
               If found, return immediately regardless of current queue state.
            2. Check whether the current task's time slice has expired.
               If not expired, return task=None (keep running current task).
            3. Walk queue levels from P1 downward, returning the first
               non-empty level that has a ready task.

        Returns SchedulingDecision with task=None if nothing is ready.
        """
        from matrixmouse.task import TaskStatus

        all_active = queue.active_tasks()
        completed  = queue.completed_ids()

        ready = [
            t for t in all_active
            if t.status == TaskStatus.READY and t.is_ready(completed)
        ]

        if not ready:
            reason = (
                f"{len(all_active)} active task(s), none ready. "
                "All are running, blocked, or awaiting human input."
                if all_active else "Task queue is empty."
            )
            return SchedulingDecision(
                task=None,
                reason=reason,
                queue_level=None,
                candidates_considered=0,
                total_active=len(all_active),
            )

        # --- Preemption check ---
        preempting = [t for t in ready if getattr(t, "preempt", False)]
        if preempting:
            chosen = min(preempting, key=lambda t: t.priority_score(
                **self._scoring_kwargs()
            ))
            reason = (
                f"Preemption: [{chosen.id}] '{chosen.title}' "
                f"jumped the queue."
            )
            logger.info("Scheduler: %s", reason)
            return SchedulingDecision(
                task=chosen,
                reason=reason,
                queue_level=P1,
                candidates_considered=len(ready),
                total_active=len(all_active),
                preempted=True,
            )

        # --- Time slice check for currently RUNNING task ---
        running = [t for t in all_active if t.status == TaskStatus.RUNNING]
        if running:
            current = running[0]
            level   = self._queue_level(current)
            elapsed = self._elapsed_minutes(current)
            limit   = self._slice_minutes(level)
            if elapsed < limit:
                # Slice has not expired — keep running
                return SchedulingDecision(
                    task=current,
                    reason=(
                        f"Time slice active: [{current.id}] "
                        f"{elapsed:.1f}/{limit:.0f} min elapsed (P{level})."
                    ),
                    queue_level=level,
                    candidates_considered=len(ready),
                    total_active=len(all_active),
                )
            else:
                logger.info(
                    "Scheduler: time slice expired for [%s] "
                    "(%.1f min, limit %.0f min, P%d).",
                    current.id, elapsed, limit, level,
                )
                # Slice expired — fall through to select next task.
                # Orchestrator is responsible for calling queue.mark_ready()
                # on the current task before the next mark_running() call.

        # --- Select next task from queue levels ---
        chosen, level = self._select_from_queues(ready)
        self._last_served_level = level

        if chosen is None:
            return SchedulingDecision(
                task=None,
                reason="No ready tasks found across all queue levels.",
                queue_level=None,
                candidates_considered=len(ready),
                total_active=len(all_active),
            )

        kwargs = self._scoring_kwargs()
        score  = chosen.priority_score(**kwargs)
        reason = (
            f"Selected [{chosen.id}] '{chosen.title}' "
            f"(score: {score:.3f}, importance: {chosen.importance}, "
            f"urgency: {chosen.urgency}, P{level}) "
            f"from {len(ready)} ready task(s)."
        )
        logger.info("Scheduler: %s", reason)

        return SchedulingDecision(
            task=chosen,
            reason=reason,
            queue_level=level,
            candidates_considered=len(ready),
            total_active=len(all_active),
        )

    def record_switch_time(self, seconds: float) -> None:
        """
        Record a context switch duration for the adaptive heuristic.
        Call this after every context switch completes.
        No-op if adaptive scheduling is disabled.
        """
        if not getattr(self.config, "scheduler_adaptive", False):
            return
        self._switch_ema = (
            self._EMA_ALPHA * seconds
            + (1.0 - self._EMA_ALPHA) * self._switch_ema
        )
        self._maybe_adjust_slices()

    def time_slice_expired(self, task: "Task") -> bool:
        """
        Return True if the task's time slice has expired.
        Convenience method for the orchestrator to call after each
        inference without rerunning the full scheduling pass.
        """
        if task.time_slice_started is None:
            return False
        level   = self._queue_level(task)
        elapsed = self._elapsed_minutes(task)
        limit   = self._slice_minutes(level)
        return elapsed >= limit

    def report_blocked(self, queue: "TaskQueue") -> str:
        """
        Return a human-readable summary of all blocked tasks.
        Used by GET /status and the web UI.
        """
        from matrixmouse.task import TaskStatus

        blocked_by_task = [
            t for t in queue.active_tasks()
            if t.status == TaskStatus.BLOCKED_BY_TASK
        ]
        blocked_by_human = [
            t for t in queue.active_tasks()
            if t.status == TaskStatus.BLOCKED_BY_HUMAN
        ]

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

    # -----------------------------------------------------------------------
    # Queue level assignment
    # -----------------------------------------------------------------------

    def _queue_level(self, task: "Task") -> int:
        """Assign a task to P1, P2, or P3 based on its priority score."""
        kwargs = self._scoring_kwargs()
        score  = task.priority_score(**kwargs)
        p1_thresh = getattr(self.config, "scheduler_p1_threshold", 0.35)
        p2_thresh = getattr(self.config, "scheduler_p2_threshold", 0.65)
        if score < p1_thresh:
            return P1
        if score < p2_thresh:
            return P2
        return P3

    def _select_from_queues(
        self, ready: "list[Task]"
    ) -> "tuple[Task | None, int | None]":
        """
        Walk P1 → P2 → P3. Return the highest-priority task from the
        first non-empty level, and the level it came from.

        Round-robin within each level is approximated by sorting on
        priority score — tasks with equal scores get served in FIFO
        order via Python's stable sort.

        TODO: Implement true round-robin cycling using _last_served_level so 
        higher queues don't perpetually starve lower ones when P1 always has 
        tasks. Current greedy approach is acceptable when task volume is low
        """
        kwargs = self._scoring_kwargs()

        for level in (P1, P2, P3):
            candidates = [t for t in ready if self._queue_level(t) == level]
            if candidates:
                chosen = min(candidates, key=lambda t: t.priority_score(**kwargs))
                return chosen, level

        return None, None

    # -----------------------------------------------------------------------
    # Time slice helpers
    # -----------------------------------------------------------------------

    def _slice_minutes(self, level: int) -> float:
        """Return the effective time slice for a queue level in minutes."""
        if level in self._slice_overrides:
            return self._slice_overrides[level]
        defaults = {
            P1: getattr(self.config, "scheduler_p1_slice_minutes", 120.0),
            P2: getattr(self.config, "scheduler_p2_slice_minutes", 90.0),
            P3: getattr(self.config, "scheduler_p3_slice_minutes", 60.0),
        }
        return defaults.get(level, 60.0)

    @staticmethod
    def _elapsed_minutes(task: "Task") -> float:
        """Minutes elapsed since the task's time slice started."""
        if task.time_slice_started is None:
            return 0.0
        return (time.monotonic() - task.time_slice_started) / 60.0

    # -----------------------------------------------------------------------
    # Adaptive heuristic
    # -----------------------------------------------------------------------

    def _maybe_adjust_slices(self) -> None:
        """
        Adjust slice lengths based on observed switch overhead.

        If switch time > max_pct of the current slice, increase all slices
        by one step (switch overhead is too large a fraction of useful work).
        If switch time < min_pct, decrease all slices by one step (we can
        afford finer-grained scheduling without meaningful overhead).

        Floor: scheduler_adaptive_min_slice_minutes (default 30).
        """
        step     = getattr(self.config, "scheduler_adaptive_step_minutes", 10.0)
        min_pct  = getattr(self.config, "scheduler_adaptive_min_pct",  0.05)
        max_pct  = getattr(self.config, "scheduler_adaptive_max_pct",  0.15)
        floor    = getattr(self.config, "scheduler_adaptive_min_slice_minutes", 30.0)

        switch_minutes = self._switch_ema / 60.0

        for level in (P1, P2, P3):
            current_slice = self._slice_minutes(level)
            ratio = switch_minutes / current_slice if current_slice > 0 else 0

            if ratio > max_pct:
                new_slice = current_slice + step
                self._slice_overrides[level] = new_slice
                logger.info(
                    "Adaptive scheduler: P%d slice increased to %.0f min "
                    "(switch overhead %.1f%% > %.0f%% target).",
                    level, new_slice, ratio * 100, max_pct * 100,
                )
            elif ratio < min_pct:
                new_slice = max(floor, current_slice - step)
                self._slice_overrides[level] = new_slice
                logger.info(
                    "Adaptive scheduler: P%d slice decreased to %.0f min "
                    "(switch overhead %.1f%% < %.0f%% target).",
                    level, new_slice, ratio * 100, min_pct * 100,
                )

    # -----------------------------------------------------------------------
    # Shared scoring kwargs
    # -----------------------------------------------------------------------

    def _scoring_kwargs(self) -> dict:
        """
        Build keyword args for Task.priority_score() from config.
        Returns hardcoded defaults if config keys are absent.
        """
        return {
            "aging_rate":         getattr(self.config, "priority_aging_rate",        0.01),
            "max_aging_bonus":    getattr(self.config, "priority_max_aging_bonus",    0.3),
            "importance_weight":  getattr(self.config, "priority_importance_weight",  0.6),
            "urgency_weight":     getattr(self.config, "priority_urgency_weight",     0.4),
        }
