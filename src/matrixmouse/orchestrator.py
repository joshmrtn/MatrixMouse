"""
matrixmouse/orchestrator.py

Persistent control loop and task execution manager.

Responsible for:
    - Maintaining a persistent loop that waits for tasks via a condition
      variable and processes them as they arrive
    - Fetching the highest-priority unblocked task from the scheduler
    - Scoping each task: configuring path safety, loading relevant context
    - Instantiating the correct agent for each task's role
    - Intercepting declare_complete for Coder/Writer tasks to trigger
      Critic review before marking COMPLETE
    - Routing escalated or blocked tasks to the human via comms
    - Maintaining live status for the API to serve
    - Time slice tracking: checking for slice expiry and preemption after
      each inference call, yielding control back to the scheduler when due
    - Daily Manager review injection based on configured schedule
    - Stale clarification detection via scheduler callback

Do not add inference logic here. That belongs to loop.py.
Do not add model selection logic here. That belongs to router.py.
Do not add agent prompting logic here. That belongs to agents/.
"""

from __future__ import annotations

import functools
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from matrixmouse.agents import agent_for_role
from matrixmouse.config import MatrixMouseConfig, MatrixMousePaths, RepoPaths
from matrixmouse.context import ContextManager
from matrixmouse.loop import AgentLoop, LoopExitReason, LoopResult
from matrixmouse.router import Router
from matrixmouse.scheduling import Scheduler
from matrixmouse.stuck import StuckDetector
from matrixmouse.task import AgentRole, Task, TaskStatus, TaskQueue
from matrixmouse.tools._safety import reconfigure_for_task
from matrixmouse import workspace_state

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# RunResult
# ---------------------------------------------------------------------------

@dataclass
class RunResult:
    """Bundles loop outcome with stuck diagnostics for _run_task."""
    loop_result: LoopResult
    detector: StuckDetector


# ---------------------------------------------------------------------------
# Critic task description builder
# ---------------------------------------------------------------------------

def _build_critic_description(
    reviewed_task: Task,
    diff: str,
) -> str:
    """
    Build the front-loaded description for a Critic review task.

    Embeds the reviewed task's details, git diff, and conversation
    history into a structured block that the Critic's system prompt
    instructs it to read at the start of its review.

    Args:
        reviewed_task: The task that has been declared complete and
            is awaiting Critic review.
        diff: Git diff string against wip_commit_hash. Empty string
            if no diff is available (e.g. wip_commit_hash not set).

    Returns:
        str: Structured description for the Critic task.
    """
    history_text = ""
    if reviewed_task.context_messages:
        # Include the conversation history so the Critic can see what
        # the implementing agent tried, not just what it produced.
        history_lines = []
        for msg in reviewed_task.context_messages:
            if not isinstance(msg, dict):
                continue
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if isinstance(content, str) and content.strip():
                # Truncate very long messages to avoid overwhelming the Critic
                preview = content[:800] + "..." if len(content) > 800 else content
                history_lines.append(f"[{role}]: {preview}")
        if history_lines:
            history_text = (
                "\n\n--- IMPLEMENTATION HISTORY ---\n"
                + "\n\n".join(history_lines)
                + "\n--- END HISTORY ---"
            )

    diff_text = (
        f"\n\n--- GIT DIFF ---\n{diff}\n--- END DIFF ---"
        if diff.strip() else
        "\n\n(No git diff available — wip_commit_hash not set on reviewed task.)"
    )

    return (
        f"Reviewed task ID: {reviewed_task.id}\n"
        f"Title: {reviewed_task.title}\n"
        f"Role: {reviewed_task.role.value}\n"
        f"Repo: {', '.join(reviewed_task.repo) if reviewed_task.repo else '(none)'}\n"
        f"\n--- DEFINITION OF DONE ---\n"
        f"{reviewed_task.description}\n"
        f"--- END DEFINITION OF DONE ---"
        f"{diff_text}"
        f"{history_text}"
    )


def _fetch_diff_for_task(task: Task) -> str:
    """
    Fetch the git diff for a task against its wip_commit_hash.

    Returns an empty string if the diff cannot be retrieved.

    Args:
        task: The task to fetch a diff for.

    Returns:
        str: Git diff text, or empty string on failure.
    """
    if not task.wip_commit_hash or not task.repo:
        return ""
    try:
        from matrixmouse.tools.git_tools import get_git_diff
        return get_git_diff(base=task.wip_commit_hash)
    except Exception as e:
        logger.warning(
            "Failed to fetch diff for task [%s]: %s", task.id, e
        )
        return ""


# ---------------------------------------------------------------------------
# Manager review schedule helpers
# ---------------------------------------------------------------------------

def _review_is_due(
    schedule: str,
    last_review_at: Optional[datetime],
) -> bool:
    """
    Return True if a Manager review is due based on the cron schedule
    and the last review timestamp.

    Uses a simple cron evaluation: parses the schedule string and checks
    whether enough time has passed since the last review. Falls back to
    True (always due) if the schedule cannot be parsed, ensuring reviews
    are not silently skipped on misconfiguration.

    Args:
        schedule:       Cron expression string (e.g. "0 9 * * *").
        last_review_at: UTC datetime of the last completed review, or
                        None if no review has been run yet.

    Returns:
        bool: True if a review should be injected now.
    """
    if last_review_at is None:
        # No review has ever run — schedule one immediately
        return True

    try:
        from croniter import croniter
        now = datetime.now(timezone.utc)
        cron = croniter(schedule, last_review_at)
        next_due = cron.get_next(datetime)
        return now >= next_due
    except Exception as e:
        logger.warning(
            "Failed to parse manager_review_schedule %r: %s. "
            "Treating review as due.",
            schedule, e,
        )
        return True


def _build_review_task(
    queue: TaskQueue,
    state: dict,
    config: MatrixMouseConfig,
) -> Task:
    """
    Build a Manager review task with front-loaded context.

    The task description includes:
        - Tasks completed since the last review (summaries)
        - All currently BLOCKED tasks with their blocking reasons
        - Up to N READY tasks by priority (upcoming work)
        - The summary from the previous review cycle

    Args:
        queue:  The workspace TaskQueue.
        state:  Loaded workspace state dict.
        config: Active config (used for upcoming task count limit).

    Returns:
        Task: A READY Manager task with preempt=True.
    """
    now = datetime.now(timezone.utc)
    last_review_at = workspace_state.get_last_review_at(state)

    all_tasks = queue.all_tasks()
    completed = queue.completed_ids()

    # Recently completed tasks
    recently_completed = []
    for t in all_tasks:
        if t.status != TaskStatus.COMPLETE:
            continue
        if last_review_at and t.completed_at:
            try:
                completed_dt = datetime.fromisoformat(t.completed_at)
                if completed_dt.tzinfo is None:
                    completed_dt = completed_dt.replace(tzinfo=timezone.utc)
                if completed_dt < last_review_at:
                    continue
            except (ValueError, TypeError):
                pass
        recently_completed.append(t)

    # Blocked tasks
    blocked_tasks = [
        t for t in all_tasks if t.status.is_blocked
    ]

    # Upcoming READY tasks — top N by priority
    upcoming_limit = config.manager_review_upcoming_tasks
    ready_tasks = sorted(
        [t for t in all_tasks
         if t.status == TaskStatus.READY and t.is_ready(completed)],
        key=lambda t: t.priority_score(),
    )[:upcoming_limit]

    # Previous review summary
    prev_summary = state.get("last_review_summary", "")

    # Build description
    sections = [
        "You are conducting a scheduled Manager review.",
        "",
    ]

    if prev_summary:
        sections += [
            "--- PREVIOUS REVIEW SUMMARY ---",
            prev_summary,
            "--- END PREVIOUS REVIEW SUMMARY ---",
            "",
        ]

    sections += [
        f"--- RECENTLY COMPLETED TASKS ({len(recently_completed)}) ---",
    ]
    for t in recently_completed:
        sections.append(
            f"[{t.id}] {t.title} | completed: {t.completed_at or 'unknown'}"
        )
        if t.last_review_summary:
            sections.append(f"  Summary: {t.last_review_summary[:200]}")
    if not recently_completed:
        sections.append("  (none)")
    sections.append("")

    sections += [
        f"--- BLOCKED TASKS ({len(blocked_tasks)}) ---",
    ]
    for t in blocked_tasks:
        sections.append(
            f"[{t.id}] {t.title} | status: {t.status.value}"
        )
        if t.pending_question:
            sections.append(f"  Pending question: {t.pending_question}")
        if t.notes:
            last_note = t.notes.splitlines()[-1]
            sections.append(f"  Notes: {last_note}")
    if not blocked_tasks:
        sections.append("  (none)")
    sections.append("")

    sections += [
        f"--- UPCOMING READY TASKS (top {len(ready_tasks)}) ---",
    ]
    for t in ready_tasks:
        sections.append(
            f"[{t.id}] ({t.role.value}) {t.title} | "
            f"score: {t.priority_score():.3f}"
        )
    if not ready_tasks:
        sections.append("  (none)")
    sections.append("")

    sections.append(
        "Use get_task_info, list_tasks, update_task, split_task as needed. "
        "Call declare_complete with a detailed summary when your review is done."
    )

    description = "\n".join(sections)

    task = Task(
        title="[Manager Review] Scheduled review",
        description=description,
        role=AgentRole.MANAGER,
        repo=[],
        importance=0.2,   # low score = high priority (P1)
        urgency=0.2,
    )
    task.preempt = True
    return task


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

class Orchestrator:
    """
    Persistent control loop. Waits for tasks via a condition variable,
    instantiates the correct agent for each task's role, drives the
    agent loop, then waits again.

    Instantiated once at service startup. Never exits unless the process
    is killed or an unrecoverable error occurs.

    Time slice management
    ---------------------
    After each inference call the loop checks whether the current task's
    time slice has expired or a preempting task is waiting. If so, the
    task is returned to READY and control passes back to the scheduling
    loop. context_messages are persisted after every inference call so
    no work is lost across a context switch.

    Critic interception
    -------------------
    When a Coder or Writer task calls declare_complete, the loop exits
    with LoopExitReason.COMPLETE. The orchestrator intercepts this,
    creates a Critic review task, and blocks the original task on it.
    The task is only marked COMPLETE after the Critic calls approve().
    Manager tasks skip Critic review and go directly to COMPLETE.

    Daily review injection
    ----------------------
    At the top of each scheduling cycle the orchestrator checks whether
    a Manager review is due (based on manager_review_schedule cron string
    and last_manager_review_at in workspace state). If due, a review task
    is created and injected with preempt=True so it takes priority.

    Stale clarification handling
    ----------------------------
    The scheduler calls _handle_stale_clarification() when it detects a
    BLOCKED_BY_HUMAN task with an unanswered pending_question older than
    clarification_timeout_minutes. The orchestrator creates a low-priority
    Manager task and records it in workspace state to prevent duplicates.
    """

    _IDLE_TIMEOUT = 300  # 5 minutes

    def __init__(
        self,
        config: MatrixMouseConfig,
        paths: MatrixMousePaths,
        graph=None,
    ):
        self.config = config
        self.paths = paths
        self.graph = graph

        self.queue = TaskQueue(paths.tasks_file)
        self._router = Router(config)

        # Load workspace state before constructing the scheduler so the
        # stale clarification callback has access to it immediately.
        self._ws_state = workspace_state.load(paths.workspace_state_file)

        self._scheduler = Scheduler(
            config,
            stale_clarification_callback=self._handle_stale_clarification,
        )

        self._status: dict = {
            "task":             None,
            "role":             None,
            "model":            None,
            "turns":            0,
            "blocked":          False,
            "idle":             True,
            "context_messages": [],
        }

    # -----------------------------------------------------------------------
    # API wiring
    # -----------------------------------------------------------------------

    def configure_api(self) -> None:
        """
        Inject live state into api.py so the API can serve status,
        accept tasks, and notify the orchestrator of new work.
        Called once after __init__ and before start_server().
        """
        import matrixmouse.api as api_module
        api_module.configure(
            queue=self.queue,
            status=self._status,
            workspace_root=self.paths.workspace_root,
            config=self.config,
        )

    # -----------------------------------------------------------------------
    # Main loop
    # -----------------------------------------------------------------------

    def run(self) -> None:
        """
        Persistent main loop. Runs until the process is killed.

        Each iteration:
            1. Reload tasks from disk (picks up API-created tasks)
            2. Check whether a Manager review is due — inject if so
            3. Ask the scheduler for the next task
            4. If a task is ready — run it
            5. If nothing is ready — wait on the condition variable
        """
        import matrixmouse.api as api_module
        condition = api_module.get_task_condition()

        logger.info(
            "Orchestrator running. Workspace: %s", self.paths.workspace_root
        )
        self._update_status(idle=True)

        while True:
            try:
                self.queue.reload()
            except Exception as e:
                logger.error("Failed to reload task queue: %s", e)
                self._wait_on_condition(condition)
                continue

            # --- Daily review injection ---
            self._maybe_inject_manager_review()

            decision = self._scheduler.next(self.queue)

            if decision.task is None:
                logger.debug("Scheduler: no task ready. %s", decision.reason)
                self._update_status(idle=True, task=None, role=None)
                self._wait_on_condition(condition)
                continue

            task = decision.task
            logger.info(
                "Scheduler selected task [%s] %s (score: %.3f, P%s, role: %s)",
                task.id, task.title,
                task.priority_score(**self._scoring_kwargs()),
                decision.queue_level,
                task.role.value,
            )

            if task.status == TaskStatus.RUNNING:
                logger.debug(
                    "Scheduler returned already-RUNNING task [%s] — "
                    "skipping re-entry.", task.id,
                )
                self._wait_on_condition(condition)
                continue

            self._update_status(idle=False, task=task.id)
            self.queue.mark_running(task.id)

            switch_start = time.monotonic()
            try:
                self._run_task(task)
            except Exception as e:
                logger.exception(
                    "Unhandled exception processing task [%s]: %s",
                    task.id, e,
                )
                self._request_human_intervention(
                    task, None, reason=f"Unhandled exception: {e}"
                )
            finally:
                switch_duration = time.monotonic() - switch_start
                self._scheduler.record_switch_time(switch_duration)

            self._update_status(idle=True, task=None, role=None)

    # -----------------------------------------------------------------------
    # Daily review injection
    # -----------------------------------------------------------------------

    def _maybe_inject_manager_review(self) -> None:
        """
        Inject a Manager review task if the schedule says one is due.

        Checks workspace state for last_manager_review_at and evaluates
        the manager_review_schedule cron expression. If due and no review
        task is already pending, creates a preempting Manager review task.

        No-op if manager_review_schedule is empty or unset.
        """
        schedule = self.config.manager_review_schedule
        if not schedule:
            return

        last_review_at = workspace_state.get_last_review_at(self._ws_state)

        if not _review_is_due(schedule, last_review_at):
            return

        # Check if a review task is already pending or running to avoid
        # injecting duplicates if the previous review hasn't completed yet.
        existing_review = next(
            (
                t for t in self.queue.active_tasks()
                if t.role == AgentRole.MANAGER
                and t.title.startswith("[Manager Review]")
                and not t.status.is_terminal
            ),
            None,
        )
        if existing_review:
            logger.debug(
                "Manager review already active [%s] — skipping injection.",
                existing_review.id,
            )
            return

        try:
            review_task = _build_review_task(
                self.queue, self._ws_state, self.config
            )
            self.queue.add(review_task)
            logger.info(
                "Manager review task [%s] injected (schedule: %s).",
                review_task.id, schedule,
            )
        except Exception as e:
            logger.error("Failed to inject Manager review task: %s", e)

    def _on_manager_review_complete(self, task: Task, summary: str) -> None:
        """
        Update workspace state when a Manager review task completes.

        Records the completion timestamp and the review summary so the
        next review cycle can front-load it as context.

        Args:
            task:    The completed Manager review task.
            summary: The completion summary from declare_complete.
        """
        workspace_state.set_last_review_at(self._ws_state)
        self._ws_state["last_review_summary"] = summary
        workspace_state.save(self.paths.workspace_state_file, self._ws_state)
        logger.info(
            "Manager review complete. last_manager_review_at updated."
        )

    # -----------------------------------------------------------------------
    # Stale clarification handling
    # -----------------------------------------------------------------------

    def _handle_stale_clarification(
        self,
        task_id: str,
        question: str,
        blocked_since: str,
    ) -> None:
        """
        Scheduler callback: create a Manager task to handle a stale
        clarification question.

        Checks workspace state to avoid creating duplicate Manager tasks
        for the same blocked task. Records the created task ID in
        workspace state.

        Args:
            task_id:       ID of the BLOCKED_BY_HUMAN task.
            question:      The unanswered clarification question.
            blocked_since: ISO timestamp when the task was blocked.
        """
        # Check for existing stale clarification task in workspace state
        existing_manager_task_id = workspace_state.get_stale_clarification_task(
            self._ws_state, task_id
        )
        if existing_manager_task_id:
            # Verify the task still exists and is non-terminal
            existing = self.queue.get(existing_manager_task_id)
            if existing and not existing.status.is_terminal:
                logger.debug(
                    "Stale clarification Manager task [%s] already exists "
                    "for task [%s] — skipping.",
                    existing_manager_task_id, task_id,
                )
                return
            # Task completed or was cancelled — clear the record
            workspace_state.clear_stale_clarification_task(
                self._ws_state, task_id
            )
            workspace_state.save(self.paths.workspace_state_file, self._ws_state)

        blocked_task = self.queue.get(task_id)
        if blocked_task is None:
            logger.warning(
                "Stale clarification: task [%s] not found in queue.", task_id
            )
            return

        description = (
            f"A task has been waiting for a clarification answer for too long.\n\n"
            f"Blocked task ID: {task_id}\n"
            f"Blocked task title: {blocked_task.title}\n"
            f"Blocked since: {blocked_since}\n"
            f"Repo: {', '.join(blocked_task.repo) if blocked_task.repo else '(none)'}\n"
            f"\nUnanswered question:\n{question}\n\n"
            f"If you can answer this question from available context (git log, "
            f"files, task descriptions), update the blocked task's description "
            f"with the answer using update_task, then unblock it by removing the "
            f"clarification block via update_task(remove_blocked_by=[]). "
            f"If you cannot answer it, flag it for the human operator using "
            f"request_clarification with a summary of what you tried."
        )

        manager_task = Task(
            title=f"[Stale Clarification] Answer question for task {task_id}",
            description=description,
            role=AgentRole.MANAGER,
            repo=blocked_task.repo,
            importance=0.6,   # lower priority than reviews but above normal work
            urgency=0.5,
        )

        try:
            self.queue.add(manager_task)
            workspace_state.register_stale_clarification_task(
                self._ws_state, task_id, manager_task.id
            )
            workspace_state.save(self.paths.workspace_state_file, self._ws_state)
            logger.info(
                "Stale clarification Manager task [%s] created for "
                "blocked task [%s].",
                manager_task.id, task_id,
            )
        except Exception as e:
            logger.error(
                "Failed to create stale clarification Manager task "
                "for task [%s]: %s", task_id, e,
            )

    # -----------------------------------------------------------------------
    # Task execution
    # -----------------------------------------------------------------------

    def _run_task(self, task: Task) -> None:
        """
        Run a single task to completion, yield, or block.

        Instantiates the agent for the task's role, loads or resumes
        context messages, runs the agent loop, and handles the outcome.

        Returns normally in all cases — the caller (run()) decides what
        to do next based on task status after return.
        """
        agent = agent_for_role(task.role)
        messages = self._load_or_build_messages(task, agent)

        self._update_status(
            role=task.role.value,
            model=self._router.model_for_role(task.role),
            turns=0,
            context_messages=messages,
        )

        reconfigure_for_task(task.repo, self.paths.workspace_root)

        run_result = self._run_agent(task, agent, messages)
        result   = run_result.loop_result
        detector = run_result.detector

        # --- Yield (time slice expired or preemption) ---
        if result.exit_reason == LoopExitReason.YIELD:
            logger.info("Task [%s] yielding. Returning to READY.", task.id)
            self.queue.mark_ready(task.id)
            return

        # --- Complete ---
        if result.exit_reason == LoopExitReason.COMPLETE:
            self._handle_complete(task, result)
            return

        # --- Escalate (Coder cascade) ---
        # TODO: make iterative for concurrency when multi-threaded model is applied
        if result.exit_reason == LoopExitReason.ESCALATE:
            if task.role == AgentRole.CODER:
                escalated, new_model = self._router.escalate(detector)
                if escalated:
                    logger.info(
                        "Task [%s] escalating to %s.", task.id, new_model,
                    )
                    handoff_messages = self._router.build_handoff(
                        detector, result.messages
                    )
                    task.context_messages = handoff_messages
                    self.queue.update(task)
                    self._run_task(task)
                    return
            logger.warning(
                "Task [%s] at cascade ceiling or non-escalatable role — "
                "human needed.", task.id,
            )
            self._request_human_intervention(
                task, result,
                reason="At top of model cascade, still stuck.",
            )
            return

        # --- Turn limit ---
        if result.exit_reason == LoopExitReason.TURN_LIMIT_REACHED:
            self._handle_turn_limit(task, result)
            return

        # --- Error ---
        if result.exit_reason == LoopExitReason.ERROR:
            self._request_human_intervention(
                task, result, reason="Unrecoverable loop error."
            )
            return

    def _run_agent(
        self, task: Task, agent, messages: list
    ) -> RunResult:
        """
        Construct and run the AgentLoop for a task.
        """
        from matrixmouse.tools import task_tools, tools_for_role_list
        from matrixmouse.tools import comms_tools
        from matrixmouse.comms import poll_interjection, get_manager
        from matrixmouse import memory

        task_tools.configure(self.queue, task.id, self.config)
        comms_tools.configure(self.config)

        def _persist_messages(messages: list) -> None:
            """
            Write context_messages back to the task and flush to disk.

            TODO: Give each task its own dedicated file to avoid the
            write bottleneck when many tasks are active concurrently.
            """
            task.context_messages = list(messages)
            try:
                self.queue.update(task)
            except Exception as e:
                logger.warning(
                    "Failed to persist context_messages for task [%s]: %s",
                    task.id, e,
                )

        def _should_yield_now() -> bool:
            return self._should_yield(task)

        current_repo = task.repo[0] if task.repo else None
        scoped_comms = functools.partial(
            poll_interjection, current_repo=current_repo
        )

        if current_repo:
            repo_paths: RepoPaths = self.paths.repo_paths(current_repo)
            memory.configure(repo_paths.agent_notes)
        else:
            memory.configure(self.paths.agent_notes)
            repo_paths = None

        detector = StuckDetector(role=task.role)
        context_manager = ContextManager(
            config=self.config,
            paths=repo_paths or self.paths,
            coder_model=self._router.model_for_role(task.role),
        )
        comms_manager = get_manager()

        loop = AgentLoop(
            model=self._router.model_for_role(task.role),
            messages=messages,
            tools=tools_for_role_list(task.role),
            allowed_tools=agent.allowed_tools,
            config=self.config,
            paths=repo_paths or self.paths,
            context_manager=context_manager,
            stuck_detector=detector,
            comms=scoped_comms,
            emit=comms_manager.emit if comms_manager else lambda t, d: None,
            persist=_persist_messages,
            should_yield=_should_yield_now,
            stream=self._router.stream_for_role(task.role),
            think=self._router.think_for_role(task.role),
            current_repo=current_repo,
            task_turn_limit=task.turn_limit,
        )

        result = loop.run()
        self._update_status(turns=result.turns_taken)

        if result.exit_reason == LoopExitReason.ESCALATE:
            logger.warning("Stuck summary: %s", detector.summary)

        return RunResult(loop_result=result, detector=detector)

    # -----------------------------------------------------------------------
    # Completion and Critic interception
    # -----------------------------------------------------------------------

    def _handle_complete(self, task: Task, result: LoopResult) -> None:
        """
        Handle a COMPLETE exit from the agent loop.

        For Coder and Writer tasks: intercept and create a Critic review
        task that blocks the original task.

        For Manager tasks: mark COMPLETE directly. If this is a scheduled
        review task, update workspace state with the completion timestamp
        and summary.

        For Critic tasks: approve()/deny() in task_tools already updated
        all task states — nothing further to do here.
        """
        if task.role in (AgentRole.CODER, AgentRole.WRITER):
            self._create_critic_review(task, result)
            return

        if task.role == AgentRole.MANAGER:
            if result.completion_summary:
                task.last_review_summary = result.completion_summary
                try:
                    self.queue.update(task)
                except Exception as e:
                    logger.warning(
                        "Failed to store review summary for task [%s]: %s",
                        task.id, e,
                    )
            self.queue.mark_complete(task.id)
            self._notify_task_complete(task)

            # If this was a scheduled review task, update workspace state
            if task.title.startswith("[Manager Review]"):
                self._on_manager_review_complete(
                    task, result.completion_summary or ""
                )
            logger.info("Manager task [%s] complete.", task.id)
            return

        if task.role == AgentRole.CRITIC:
            logger.info("Critic task [%s] complete.", task.id)
            return

        logger.warning(
            "Task [%s] has unknown role %r — marking complete directly.",
            task.id, task.role,
        )
        self.queue.mark_complete(task.id)
        self._notify_task_complete(task)

    def _create_critic_review(self, task: Task, result: LoopResult) -> None:
        """
        Create a Critic review task for a completed Coder or Writer task.
        """
        diff = _fetch_diff_for_task(task)
        critic_description = _build_critic_description(task, diff)

        critic_task = Task(
            title=f"[Critic Review] {task.title}",
            description=critic_description,
            role=AgentRole.CRITIC,
            repo=task.repo,
            reviews_task_id=task.id,
            importance=task.importance,
            urgency=task.urgency,
        )

        try:
            self.queue.add(critic_task)
        except Exception as e:
            logger.error(
                "Failed to create Critic review task for [%s]: %s. "
                "Marking task complete directly.",
                task.id, e,
            )
            self.queue.mark_complete(task.id)
            self._notify_task_complete(task)
            return

        task.blocked_by.append(critic_task.id)
        task.status = TaskStatus.BLOCKED_BY_TASK
        try:
            self.queue.update(task)
        except Exception as e:
            logger.error(
                "Failed to block task [%s] on Critic task [%s]: %s",
                task.id, critic_task.id, e,
            )

        logger.info(
            "Critic review task [%s] created for task [%s] '%s'.",
            critic_task.id, task.id, task.title,
        )

        try:
            from matrixmouse import comms as comms_module
            m = comms_module.get_manager()
            if m:
                m.emit("critic_review_created", {
                    "task_id":        task.id,
                    "critic_task_id": critic_task.id,
                    "task_title":     task.title,
                })
        except Exception as e:
            logger.warning("Failed to emit critic_review_created event: %s", e)

    # -----------------------------------------------------------------------
    # Turn limit handling
    # -----------------------------------------------------------------------

    def _handle_turn_limit(self, task: Task, result: LoopResult) -> None:
        """
        Handle a task that has reached its turn limit.

        For Critic tasks, emits a Critic-specific event with the three-option
        modal data (approve task / give Critic more turns / block task).

        For all other roles, emits the standard turn_limit_reached event
        with extend/respec/cancel options.
        """
        self.queue.mark_blocked_by_human(
            task.id,
            reason=f"Turn limit reached ({result.turns_taken} turns).",
        )
        self._update_status(blocked=True)

        logger.warning(
            "Turn limit reached — Task [%s] %s | %d turns | Role: %s",
            task.id, task.title, result.turns_taken, task.role.value,
        )

        try:
            from matrixmouse import comms as comms_module
            m = comms_module.get_manager()
            if m:
                m.notify_blocked(
                    f"Task [{task.id}] hit turn limit "
                    f"({result.turns_taken} turns): {task.title}"
                )

                if task.role == AgentRole.CRITIC:
                    # Critic-specific modal: three options
                    # 1. Approve the reviewed task (skip further Critic review)
                    # 2. Give the Critic more turns
                    # 3. Block the reviewed task for human resolution
                    reviewed_task_id = task.reviews_task_id or ""
                    m.emit("critic_turn_limit_reached", {
                        "critic_task_id":   task.id,
                        "critic_task_title": task.title,
                        "reviewed_task_id": reviewed_task_id,
                        "turns_taken":      result.turns_taken,
                        "critic_max_turns": self.config.critic_max_turns,
                        "choices": [
                            {
                                "value": "approve_task",
                                "label": "Approve task",
                                "description": (
                                    "Mark the reviewed task as complete. "
                                    "No further Critic review."
                                ),
                            },
                            {
                                "value": "extend_critic",
                                "label": "Give Critic more turns",
                                "description": (
                                    f"Allow the Critic another "
                                    f"{self.config.critic_max_turns} "
                                    f"turns to complete its review."
                                ),
                            },
                            {
                                "value": "block_task",
                                "label": "Block for human review",
                                "description": (
                                    "Cancel the Critic review and move the "
                                    "task to BLOCKED_BY_HUMAN for manual resolution."
                                ),
                            },
                        ],
                    })
                else:
                    m.emit("turn_limit_reached", {
                        "task_id":     task.id,
                        "task_title":  task.title,
                        "role":        task.role.value,
                        "turns_taken": result.turns_taken,
                        "turn_limit":  task.turn_limit or self.config.agent_max_turns,
                    })
        except Exception as e:
            logger.warning("Failed to send turn limit notification: %s", e)

    # -----------------------------------------------------------------------
    # Time slice and preemption
    # -----------------------------------------------------------------------

    def _should_yield(self, task: Task) -> bool:
        """
        Return True if the orchestrator should yield this task back to
        the scheduler after the current inference boundary.
        """
        if self._scheduler.time_slice_expired(task):
            logger.debug("Time slice expired for task [%s].", task.id)
            return True

        preempting = [
            t for t in self.queue.active_tasks()
            if getattr(t, "preempt", False)
            and t.status == TaskStatus.READY
            and t.id != task.id
        ]
        if preempting:
            logger.info(
                "Preempting task(s) waiting: %s. Yielding [%s].",
                [t.id for t in preempting], task.id,
            )
            return True

        return False

    # -----------------------------------------------------------------------
    # Message management
    # -----------------------------------------------------------------------

    def _load_or_build_messages(self, task: Task, agent) -> list:
        """
        Load persisted context_messages for a resuming task, or build
        fresh initial messages via the agent for a new task.
        """
        if task.context_messages:
            logger.debug(
                "Resuming task [%s] with %d persisted messages.",
                task.id, len(task.context_messages),
            )
            return list(task.context_messages)

        return agent.build_initial_messages(task)

    # -----------------------------------------------------------------------
    # Human intervention and notifications
    # -----------------------------------------------------------------------

    def _request_human_intervention(
        self,
        task: Task,
        result: Optional[LoopResult],
        reason: str = "",
    ) -> None:
        """
        Mark the task as blocked by human, send a notification,
        and update the live status so the web UI shows the block.
        """
        self.queue.mark_blocked_by_human(task.id, reason)
        self._update_status(blocked=True)

        logger.warning(
            "HUMAN INTERVENTION NEEDED — Task [%s] %s | Role: %s | %s",
            task.id, task.title, task.role.value, reason,
        )

        try:
            from matrixmouse import comms as comms_module
            m = comms_module.get_manager()
            if m:
                m.notify_blocked(
                    f"Task [{task.id}] needs attention: {reason}"
                )
                m.emit("blocked_human", {
                    "task_id":    task.id,
                    "task_title": task.title,
                    "role":       task.role.value,
                    "reason":     reason,
                    "turns":      result.turns_taken if result else 0,
                })
        except Exception as e:
            logger.warning("Failed to send block notification: %s", e)

    def _notify_task_complete(self, task: Task) -> None:
        try:
            from matrixmouse import comms as comms_module
            m = comms_module.get_manager()
            if m:
                m.notify(f"Task complete: {task.title}")
                m.emit("complete", {
                    "task_id":    task.id,
                    "task_title": task.title,
                })
        except Exception as e:
            logger.warning("Failed to send completion notification: %s", e)

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    def _update_status(self, **kwargs) -> None:
        self._status.update(kwargs)

    def _wait_on_condition(self, condition) -> None:
        with condition:
            condition.wait(timeout=self._IDLE_TIMEOUT)

    def _scoring_kwargs(self) -> dict:
        return {
            "aging_rate":        getattr(self.config, "priority_aging_rate",       0.01),
            "max_aging_bonus":   getattr(self.config, "priority_max_aging_bonus",   0.3),
            "importance_weight": getattr(self.config, "priority_importance_weight", 0.6),
            "urgency_weight":    getattr(self.config, "priority_urgency_weight",    0.4),
        }