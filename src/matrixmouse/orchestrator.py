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
from pathlib import Path
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from matrixmouse.agents import agent_for_role
from matrixmouse.config import MatrixMouseConfig, MatrixMousePaths, RepoPaths
from matrixmouse.context import ContextManager
from matrixmouse.inference.base import TokenBudgetExceededError
from matrixmouse.inference.ollama import OllamaBackend
from matrixmouse.inference.token_budget import TokenBudgetTracker
from matrixmouse.loop import AgentLoop, LoopExitReason, LoopResult
from matrixmouse.repository.task_repository import TaskRepository
from matrixmouse.repository.workspace_state_repository import (
    WorkspaceStateRepository,
    SessionContext,
    SessionMode,
    BRANCH_SETUP_TOOLS,
    PLANNING_TOOLS,
)
from matrixmouse.router import Router, parse_model_string
from matrixmouse.scheduling import Scheduler
from matrixmouse.stuck import StuckDetector
from matrixmouse.task import AgentRole, Task, TaskStatus
from matrixmouse.tools import tools_for_names
from matrixmouse.tools.git_tools import ensure_branch_from_mirror, MIRROR_REMOTE, _git
from matrixmouse.tools._safety import reconfigure_for_task
from matrixmouse.repository import SQLiteTaskRepository, SQLiteWorkspaceStateRepository
from matrixmouse.task import PRState
from matrixmouse.codemap import analyze_project, ProjectAnalyzer

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
# TaskRunContext
# ---------------------------------------------------------------------------

@dataclass
class TaskRunContext:
    """
    Runtime context for a single task execution.

    Created fresh on every task start and resume. Not stored on Task,
    not persisted to SQLite, and not referenced after _run_task() returns.

    Attributes:
        task: The Task being executed.
        graph: ProjectAnalyzer instance for the task's workspace.
    """
    task: Task
    graph: "ProjectAnalyzer"


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
    queue: TaskRepository,
    ws_state_repo: WorkspaceStateRepository,
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
        queue:  The workspace TaskRepository.
        ws_state_repo:  WorkspaceStateRepository for review timestamps and summaries.
        config: Active config (used for upcoming task count limit).

    Returns:
        Task: A READY Manager task with preempt=True.
    """
    now = datetime.now(timezone.utc)
    last_review_at = ws_state_repo.get_last_review_at()

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
        if t.status == TaskStatus.READY and queue.is_ready(t.id)],
        key=lambda t: t.priority_score(),
    )[:upcoming_limit]

    # Previous review summary
    prev_summary = ws_state_repo.get_last_review_summary()

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

def _build_set_branch_task(
    task: Task,
    queue: TaskRepository
) -> None:
    """
    Build a Manager task to set a branch name.

    Blocks the task that is passed in and sets this task as its dependent.

    Args:
        task: The Task object that the Manager needs to assign a branch to.

    Returns:
        Task: A READY Manager task with preempt=True.
    """

    # Build description
    sections = [
        "You are deciding what to name a task's git branch.",
        "Below is the task ID and description:",
        ""
    ]
    sections.append(
        f"[{task.id}]: {task.title}\n\n"
        f"Description:\n\n{task.description}"
    )
    sections.append("")
    sections.append(
        "\nUse set_branch to create a branch name for this task."
    )

    description = "\n".join(sections)

    mgr_task = Task(
        title="[Branch Setup] Choose an appropriate branch name",
        description=description,
        role=AgentRole.MANAGER,
        repo=[],
        importance=0.2,   # low score = high priority (P1)
        urgency=0.2,
    )
    mgr_task.preempt = True

    # Make mgr_task a blocker of task
    queue.add(mgr_task)
    queue.add_dependency(mgr_task.id, task.id)


# ---------------------------------------------------------------------------
# Git remote provider helpers
# ---------------------------------------------------------------------------
 
 
def _parse_owner_repo(remote_url: str) -> str:
    """
    Extract the "owner/repo" identifier from a git remote URL.
 
    Handles HTTPS and SSH remote formats:
        https://github.com/owner/repo.git  ->  owner/repo
        git@github.com:owner/repo.git      ->  owner/repo
 
    Args:
        remote_url: The remote URL string from repo_metadata.
 
    Returns:
        "owner/repo" string, or "" if the URL cannot be parsed.
    """
    if not remote_url:
        return ""
    url = remote_url.rstrip("/")
    if url.endswith(".git"):
        url = url[:-4]
    # SSH format: git@github.com:owner/repo
    if "@" in url and ":" in url:
        path_part = url.split(":", 1)[-1]
        return path_part
    # HTTPS format: https://github.com/owner/repo
    parts = url.split("/")
    if len(parts) >= 2:
        return "/".join(parts[-2:])
    return ""
 

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
        queue: TaskRepository,
        ws_state_repo: WorkspaceStateRepository,
        graph=None,
        budget_tracker: TokenBudgetTracker | None = None,
    ):
        self.config = config
        self.paths = paths
        self.graph = graph

        self.queue = queue
        self._ws_state_repo = ws_state_repo
        self._router = Router(config)
        self._budget_tracker = budget_tracker

        self._exhausted_backends: set[str] = set()
        self._exhausted_backends_lock = threading.Lock()

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
            scheduler=self._scheduler,
            status=self._status,
            workspace_root=self.paths.workspace_root,
            config=self.config,
            ws_state_repo=self._ws_state_repo,
            budget_tracker=self._budget_tracker,
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
            # --- Daily review injection ---
            self._maybe_inject_manager_review()
 
            # --- PR polling ---
            self._poll_pr_tasks()

            
            # Promote any WAITING tasks whose time condition has cleared
            promoted = self._maybe_promote_waiting_tasks()
            if promoted:
                logger.info("Promoted %d WAITING task(s) to READY.", promoted)

            # Get backends that hit budget limits last cycle (and clear for next)
            exhausted_this_cycle = self._get_and_clear_exhausted_backends()

            # Then pass exhausted_this_cycle to the scheduler's next() call so it can
            # skip tasks on exhausted backends
            # Where exhausted_task_ids is built from the queue:
            exhausted_task_ids = {
                t.id for t in self.queue.all_tasks()
                if t.status == TaskStatus.READY
                and t.wait_reason.startswith("budget:")
                and t.wait_reason.split(":", 1)[1] in exhausted_this_cycle
            } if exhausted_this_cycle else set()

            decision = self._scheduler.next(self.queue, exclude=exhausted_task_ids)


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
            try:
                self.queue.mark_running(task.id)
            except Exception as e:
                logger.warning(f"Could not mark task as running: [{task.id}]: {task.title} \n\n{e}")
                # TODO: This should be an error and cause an exception, but I loosened it 
                # since this was crashing the system before the Manager task to assign a 
                # branch was being reached. 
                # Top-level tasks should be able to be started in the BRANCH_SETUP session mode,
                # and probably also have a PENDING status that is ignored by this check 
                # but for the immediate term, I created a _build_create_branch_task method that 
                # builds a Manager task to create a branch name and blocks the top-level task. 

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

        last_review_at = self._ws_state_repo.get_last_review_at()

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
                self.queue, self._ws_state_repo, self.config
            )
            self.queue.add(review_task)
            logger.info(
                "Manager review task [%s] injected (schedule: %s).",
                review_task.id, schedule,
            )
        except Exception as e:
            logger.error("Failed to inject Manager review task: %s", e)

    def _on_manager_review_complete(self, summary: str) -> None:
        """
        Update workspace state when a Manager review task completes.

        Records the completion timestamp and the review summary so the
        next review cycle can front-load it as context.

        Args:
            task:    The completed Manager review task.
            summary: The completion summary from declare_complete.
        """
        self._ws_state_repo.set_last_review_at()
        self._ws_state_repo.set_last_review_summary(summary)
        logger.info("Manager review complete. last_manager_review_at updated.")

    
    # -----------------------------------------------------------------------
    # PR polling
    # -----------------------------------------------------------------------
 
    def _poll_pr_tasks(self) -> None:
        """
        Poll open PRs and transition tasks based on current PR state.
 
        Called at the top of each scheduling cycle. Iterates all tasks with
        pr_state == PRState.OPEN and pr_poll_next_at <= now, calls the
        provider for the current state, and routes to the appropriate handler.
 
        Errors from the provider are logged and do not crash the loop —
        the task stays OPEN and will be retried at the next poll interval.
        """
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
 
        for task in self.queue.active_tasks():
            if task.pr_state != PRState.OPEN:
                continue
            if task.pr_poll_next_at and task.pr_poll_next_at > now:
                continue
            if not task.pr_url:
                continue
 
            repo_name = task.repo[0] if task.repo else ""
            provider = self._get_provider(repo_name)
            if provider is None:
                continue
 
            try:
                metadata = self._ws_state_repo.get_repo_metadata(repo_name)
                owner_repo = _parse_owner_repo(
                    metadata.get("remote_url", "") if metadata else ""
                )
                if not owner_repo:
                    continue
 
                state_str = provider.get_pr_state(owner_repo, task.pr_url)
                new_state = PRState(state_str) if state_str else PRState.OPEN
 
                if new_state == PRState.MERGED:
                    self._handle_pr_merged(task)
                elif new_state == PRState.CLOSED:
                    self._handle_pr_closed(task, provider, owner_repo)
                else:
                    # Still open — schedule next poll
                    from datetime import timedelta
                    next_poll = (
                        datetime.now(timezone.utc)
                        + timedelta(minutes=self.config.pr_poll_interval_minutes)
                    ).isoformat()
                    task.pr_poll_next_at = next_poll
                    try:
                        self.queue.update(task)
                    except Exception as e:
                        logger.warning(
                            "Failed to update pr_poll_next_at for task [%s]: %s",
                            task.id, e,
                        )
 
            except Exception as e:
                logger.warning(
                    "PR poll failed for task [%s] (%s): %s — will retry next cycle.",
                    task.id, task.pr_url, e,
                )
 
    def _handle_pr_merged(self, task) -> None:
        """
        Handle a PR that has been merged on the remote.
 
        Updates pr_state to MERGED, clears the poll timestamp, and marks
        the task COMPLETE.
 
        Args:
            task: The task whose PR was merged.
        """
        logger.info("PR merged for task [%s] — marking COMPLETE.", task.id)
        task.pr_state = PRState.MERGED
        task.pr_poll_next_at = ""
        try:
            self.queue.update(task)
        except Exception as e:
            logger.warning(
                "Failed to update PR state for task [%s]: %s", task.id, e,
            )
 
        self.queue.mark_complete(task.id)
        self._notify_task_complete(task)
 
        try:
            from matrixmouse import comms as comms_module
            m = comms_module.get_manager()
            if m:
                m.emit("pr_merged", {
                    "task_id":    task.id,
                    "task_title": task.title,
                    "pr_url":     task.pr_url,
                })
        except Exception as e:
            logger.warning("Failed to emit pr_merged: %s", e)
 
    def _handle_pr_closed(self, task, provider, owner_repo: str) -> None:
        """
        Handle a PR that was closed without merging (changes requested).
 
        Fetches review feedback from the provider, injects it into the task's
        context_messages, updates pr_state to CLOSED, and emits a
        pr_rejection decision modal so the human can choose whether to let
        the agent rework the task or keep it blocked for manual resolution.
 
        Args:
            task:       The task whose PR was closed.
            provider:   GitRemoteProvider for the repo.
            owner_repo: "owner/repo" string for API calls.
        """
        logger.info(
            "PR closed without merge for task [%s] — fetching feedback.",
            task.id,
        )
 
        feedback = ""
        try:
            feedback = provider.get_pr_feedback(owner_repo, task.pr_url)
        except Exception as e:
            logger.warning(
                "Failed to fetch PR feedback for task [%s]: %s", task.id, e,
            )
 
        task.pr_state = PRState.CLOSED
        task.pr_poll_next_at = ""
 
        if feedback:
            task.context_messages.append({
                "role": "user",
                "content": (
                    "[Pull Request Closed — Changes Requested]\n\n"
                    "Your pull request was closed without merging. "
                    "The following feedback was left by reviewers:\n\n"
                    f"{feedback}\n\n"
                    "Address the feedback above and call declare_complete "
                    "when the changes are ready for another review."
                ),
            })
 
        try:
            self.queue.update(task)
        except Exception as e:
            logger.warning(
                "Failed to update task [%s] after PR closed: %s", task.id, e,
            )
 
        try:
            from matrixmouse import comms as comms_module
            m = comms_module.get_manager()
            if m:
                m.emit("pr_rejection", {
                    "task_id":      task.id,
                    "task_title":   task.title,
                    "pr_url":       task.pr_url,
                    "has_feedback": bool(feedback),
                    "choices": [
                        {
                            "value": "rework",
                            "label": "Let agent rework",
                            "description": (
                                "Unblock the task with the PR feedback injected "
                                "into context. The agent will address the review "
                                "comments and request a new PR when ready."
                            ),
                        },
                        {
                            "value": "manual",
                            "label": "Resolve manually",
                            "description": (
                                "Keep the task blocked. No agent action will be "
                                "taken. Resolve and re-submit the PR manually."
                            ),
                        },
                    ],
                })
        except Exception as e:
            logger.warning("Failed to emit pr_rejection: %s", e)
 
    def _push_branch_and_create_pr(
        self, task, parent_branch: str, repo_root
    ) -> tuple[bool, str]:
        """
        Push task.branch to origin and open a PR via the provider.
 
        Called when the human approves a PR via the decision endpoint.
        Pushes the branch, creates the PR, and stores the resulting
        URL + state on the task.
 
        Args:
            task:          The task whose branch is being pushed.
            parent_branch: The protected base branch for the PR.
            repo_root:     Repository root Path.
 
        Returns:
            (True, pr_url) on success, (False, error_message) on failure.
        """
        from matrixmouse.tools.git_tools import push_to_remote
 
        repo_name = task.repo[0] if task.repo else ""
        provider = self._get_provider(repo_name)
        if provider is None:
            return False, "No provider configured for this repo."
 
        try:
            metadata = self._ws_state_repo.get_repo_metadata(repo_name)
            owner_repo = _parse_owner_repo(
                metadata.get("remote_url", "") if metadata else ""
            )
            if not owner_repo:
                return False, (
                    f"Cannot parse owner/repo from remote_url for '{repo_name}'."
                )
        except Exception as e:
            return False, f"Failed to read repo metadata: {e}"
 
        # Push branch to origin (the real remote, not just the local mirror)
        ok, err = push_to_remote(task.branch, "origin", repo_root)
        if not ok:
            return False, f"git push failed: {err}"
 
        try:
            pr_url = provider.create_pull_request(
                repo=owner_repo,
                head=task.branch,
                base=parent_branch,
                title=task.title,
                body=task.description[:2000] if task.description else "",
            )
        except Exception as e:
            return False, f"PR creation failed: {e}"
 
        # Persist PR tracking state on the task
        from datetime import datetime, timedelta, timezone
        next_poll = (
            datetime.now(timezone.utc)
            + timedelta(minutes=self.config.pr_poll_interval_minutes)
        ).isoformat()
 
        task.pr_url = pr_url
        task.pr_state = PRState.OPEN
        task.pr_poll_next_at = next_poll
 
        try:
            self.queue.update(task)
        except Exception as e:
            logger.warning(
                "Failed to persist PR state for task [%s]: %s", task.id, e,
            )
 
        logger.info("PR created for task [%s]: %s", task.id, pr_url)
 
        try:
            from matrixmouse import comms as comms_module
            m = comms_module.get_manager()
            if m:
                m.emit("pr_created", {
                    "task_id":    task.id,
                    "task_title": task.title,
                    "pr_url":     pr_url,
                    "base":       parent_branch,
                })
        except Exception as e:
            logger.warning("Failed to emit pr_created: %s", e)
 
        return True, pr_url
 

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
        existing_manager_task_id = self._ws_state_repo.get_stale_clarification_task(
            task_id
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
            self._ws_state_repo.clear_stale_clarification_task(task_id)

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
            self._ws_state_repo.register_stale_clarification_task(
                task_id, manager_task.id
            )

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

        # --- Upfront budget check ---
        # If the backend for this task is known-exhausted this cycle, move
        # the task to WAITING immediately without doing any git or agent work.
        # The backend calculates the precise wait_until from the usage window.
        if self._budget_tracker is not None:
            parsed = self._router.parsed_model_for_role(task.role)
            if parsed.is_remote:
                try:
                    self._budget_tracker.check_budget(
                        provider=parsed.backend,
                        model=parsed.model,
                    )
                except TokenBudgetExceededError as e:
                    self._handle_budget_exhausted(task, e)
                    return

        if task.branch and task.repo:
            repo_root = self.paths.workspace_root / task.repo[0]
            if repo_root.exists():
                # Step 1: ensure branch exists locally (recreate from mirror if missing)
                ok, err = ensure_branch_from_mirror(
                    task.branch, MIRROR_REMOTE, repo_root
                )
                if not ok:
                    logger.error(
                        "Cannot resume task [%s] — branch '%s' missing and "
                        "recreation from mirror failed: %s. "
                        "Blocking for human intervention.",
                        task.id, task.branch, err,
                    )
                    self._request_human_intervention(
                        task, None,
                        reason=(
                            f"Branch '{task.branch}' not found locally and "
                            f"could not be recreated from mirror: {err}"
                        ),
                    )
                    return

                # Step 2: checkout the branch — no-op if already on it,
                # but required for context switches between tasks.
                # Failure here is catastrophic: the agent would work in
                # the wrong branch. Block immediately.
                ok, err = _git(["checkout", task.branch], cwd=repo_root)
                if not ok:
                    logger.error(
                        "Cannot start task [%s] — git checkout of branch '%s' "
                        "failed: %s. Blocking for human intervention.",
                        task.id, task.branch, err,
                    )
                    self._request_human_intervention(
                        task, None,
                        reason=(
                            f"git checkout of branch '{task.branch}' failed: {err}. "
                            f"Workspace may be in an inconsistent state — "
                            f"manual intervention required."
                        ),
                    )
                    return
            else:
                logger.warning(
                    "Repo root '%s' does not exist for task [%s] — "
                    "skipping branch verification and checkout.",
                    repo_root, task.id,
                )

        # --- Build ProjectAnalyzer for this task ---
        # Graph is built fresh on every task start/resume after branch checkout.
        # Not persisted, not shared — discarded when _run_task() returns.
        repo_root = self.paths.workspace_root / task.repo[0] if task.repo else None
        if repo_root and repo_root.exists():
            try:
                logger.debug("Building ProjectAnalyzer for %s...", repo_root.name)
                graph = analyze_project(str(repo_root))
                logger.debug(
                    "  %s: %d functions, %d symbols",
                    repo_root.name,
                    len(graph.functions),
                    len(graph.symbols),
                )
            except Exception as e:
                logger.warning(
                    "ProjectAnalyzer failed for %s: %s. Continuing without graph.",
                    repo_root.name, e,
                )
                graph = None
        else:
            graph = None

        ctx = TaskRunContext(task=task, graph=graph)  # type: ignore[arg-type]


        agent = agent_for_role(task.role)

        # --- Branch setup for non-manager tasks
        # If a task is created as a non-manager role and it doesn't have a 
        # branch, generate a blocking Manager task to remedy this.
        # TODO: This shouldn't happen once all top-level tasks are created as Manager 
        # role by default via interjections
        if (task.role != AgentRole.MANAGER
            and not task.branch):
            _build_set_branch_task(task, self.queue)
            return

        # --- Session mode: BRANCH_SETUP ---
        # Manager tasks with no branch assigned enter a restricted session
        # where they can only read task info and call set_branch.
        if (task.role == AgentRole.MANAGER
                and not task.branch
                and task.status != TaskStatus.PENDING):
            existing_ctx = self._ws_state_repo.get_session_context(task.id)
            if existing_ctx is None or existing_ctx.mode == SessionMode.NORMAL:
                self._ws_state_repo.set_session_context(
                    task.id,
                    SessionContext(
                        mode=SessionMode.BRANCH_SETUP,
                        allowed_tools=set(BRANCH_SETUP_TOOLS),
                        system_prompt_addendum=(
                            "\n\n--- BRANCH SETUP REQUIRED ---\n"
                            "This task has no git branch assigned yet. "
                            "Before doing any other work:\n"
                            "1. Use get_task_info to understand the task intent.\n"
                            "2. Choose a short, descriptive branch slug "
                            "(e.g. 'refactor/foobar' or 'fix/login-timeout').\n"
                            "3. Call set_branch(task_id, slug) to create the branch.\n"
                            "Once the branch is set, call declare_complete — "
                            "the task will resume normally in the next turn.\n"
                            "--- END BRANCH SETUP ---"
                        ),
                    ),
                )

        messages = self._load_or_build_messages(task, agent)

        self._update_status(
            role=task.role.value,
            model=self._router.model_for_role(task.role),
            turns=0,
            context_messages=messages,
        )

        reconfigure_for_task(task.repo, self.paths.workspace_root)

        try:
            run_result = self._run_agent(ctx, agent, messages)
        except TokenBudgetExceededError as e:
            self._handle_budget_exhausted(task, e)
            return
        
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

        # --- Decision required ---
        if result.exit_reason == LoopExitReason.DECISION:
            self._handle_decision(task, result)
            return

        # --- Error ---
        if result.exit_reason == LoopExitReason.ERROR:
            self._request_human_intervention(
                task, result, reason="Unrecoverable loop error."
            )
            return

    def _run_agent(
        self, ctx: TaskRunContext, agent, messages: list
    ) -> RunResult:
        """
        Construct and run the AgentLoop for a task.

        Args:
            ctx: TaskRunContext with task and graph.
            agent: Agent instance for the task's role.
            messages: Initial message history.

        Returns:
            RunResult with loop outcome and stuck detector.
        """
        task = ctx.task
        from matrixmouse.tools import task_tools, tools_for_role_list
        from matrixmouse.tools import comms_tools
        from matrixmouse.comms import poll_interjection, get_manager
        from matrixmouse import memory

        comms_tools.configure(self.config)

        # --- Check for active session context ---
        session_ctx = self._ws_state_repo.get_session_context(task.id)

        cwd = None
        if task.repo:
            repo_root = self.paths.workspace_root / task.repo[0]
            if repo_root.exists():
                cwd = repo_root

        task_tools.configure(
            self.queue, task.id, self.config,
            cwd=cwd, ws_state_repo=self._ws_state_repo
        )

        comms_tools.configure(self.config)

        # Configure merge tools for MERGE role
        if task.role == AgentRole.MERGE:
            from matrixmouse.tools.merge_tools import (
                configure as configure_merge_tools,
                get_conflicted_files,
            )
            # Re-run the merge to reproduce conflict state
            if cwd and task.branch:
                parent_branch = self._get_merge_target(task)
                if parent_branch:
                    from matrixmouse.tools.git_tools import _git
                    _git(["checkout", parent_branch], cwd=cwd)
                    _git(
                        ["merge", "--no-ff", task.branch,
                         "-m", f"Merge: {task.title} ({task.id[:8]})"],
                        cwd=cwd,
                    )
                    conflicted = get_conflicted_files(cwd)
                else:
                    conflicted = []
            else:
                conflicted = []

            # Replay prior decisions silently
            if task.merge_resolution_decisions and cwd:
                self._replay_merge_decisions(task, cwd)
                # Refresh conflict list after replay
                if cwd:
                    conflicted = get_conflicted_files(cwd)

            configure_merge_tools(
                cwd=cwd,
                conflicted_files=conflicted,
                task_id=task.id,
                queue=self.queue,
            )

        # Select model — merge resolution always uses the top model
        if task.role == AgentRole.MERGE:
            merge_model = (
                self.config.merge_resolution_model
                or self._router.model_for_role(AgentRole.CODER)
            )
            model = merge_model
        else:
            model = self._router.model_for_role(task.role)

        wip_commit_fn = None
        if cwd is not None and task.branch:
            from matrixmouse.tools.git_tools import wip_commit_and_push
            push_to_origin = self.config.push_wip_to_remote

            def _wip_commit() -> None:
                ok, msg = wip_commit_and_push(
                    branch=task.branch,
                    mirror_remote=MIRROR_REMOTE,
                    cwd=cwd,
                    push_to_origin=push_to_origin,
                )
                if not ok:
                    logger.error(
                        "WIP commit failed for task [%s]: %s",
                        task.id, msg,
                    )
                else:
                    logger.debug(
                        "WIP commit for task [%s]: %s", task.id, msg
                    )

            wip_commit_fn = _wip_commit

        def _persist_messages(messages: list) -> None:
            """Write context_messages back to the task and persist to database"""
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
        
        # Determine tool list — session context overrides role default
        if session_ctx and session_ctx.mode != SessionMode.NORMAL:
            tools = tools_for_names(session_ctx.allowed_tools)
        else:
            tools = tools_for_role_list(task.role)

        # Determine system prompt — inject addendum if session active
        system_prompt_addendum = (
            session_ctx.system_prompt_addendum
            if session_ctx and session_ctx.system_prompt_addendum
            else ""
        )
        # Append system prompt addendum
        if system_prompt_addendum and messages:
            first = messages[0]
            if isinstance(first, dict) and first.get("role") == "system":
                messages[0] = {
                    **first,
                    "content": first["content"] + system_prompt_addendum,
                }

        current_repo = task.repo[0] if task.repo else None
        scoped_comms = functools.partial(
            poll_interjection, current_repo=current_repo
        )

        repo_paths: RepoPaths | None = None
        if current_repo:
            repo_paths = self.paths.repo_paths(current_repo)
            memory.configure(repo_paths.agent_notes)
        else:
            memory.configure(self.paths.agent_notes)

        detector = StuckDetector(role=task.role)
        context_manager = ContextManager(
            config=self.config,
            paths=repo_paths or self.paths,
            coder_model=self._router.parsed_model_for_role(task.role).model,
            coder_backend=self._router.backend_for_role(task.role),
            summarizer_backend=self._router.backend_for_role(task.role),
            summarizer_model=parse_model_string(self.config.summarizer_model).model,
        )
        comms_manager = get_manager()

        def _persist_pending_calls(calls: list[dict]) -> None:
            task.pending_tool_calls = list(calls)
            try:
                self.queue.update(task)
            except Exception as e:
                logger.warning(
                    "Failed to persist pending_tool_calls for task [%s]: %s",
                    task.id, e,
                )

        loop = AgentLoop(
            model=self._router.parsed_model_for_role(task.role).model,
            messages=messages,
            tools=tools,
            allowed_tools=agent.allowed_tools,
            config=self.config,
            paths=repo_paths or self.paths,
            context_manager=context_manager,
            stuck_detector=detector,
            comms=scoped_comms,
            emit=comms_manager.emit if comms_manager else lambda t, d: None,
            persist=_persist_messages,
            persist_pending=_persist_pending_calls,
            wip_commit=wip_commit_fn,
            should_yield=_should_yield_now,
            stream=self._router.stream_for_role(task.role),
            think=self._router.think_for_role(task.role),
            current_repo=current_repo,
            task_turn_limit=task.turn_limit,
            backend=OllamaBackend(),         # TODO: Have this injected
        )

        # If the task has pending tool calls from an interrupted turn
        # (resumed after a DECISION), replay them before starting the loop.
        # The loop's first action will be to dispatch the pending calls
        # rather than making a new inference call.
        if task.pending_tool_calls:
            logger.info(
                "Task [%s] resuming with %d pending tool call(s) — replaying.",
                task.id, len(task.pending_tool_calls),
            )
            replay_result = loop._dispatch_tools(
                tool_blocks=[],
                pending_tool_calls=list(task.pending_tool_calls),
            )
            if replay_result is not None:
                # Replay itself hit another exit condition
                self._update_status(turns=replay_result.turns_taken)
                return RunResult(loop_result=replay_result, detector=detector)
            # Replay completed cleanly — proceed with normal loop

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

        For Critic tasks: approve() triggers merge-up, deny() task state is 
        handled by task_tools.

        For Merge tasks: mark COMPLETE directly once merge is successful.
        """
        from matrixmouse.repository.workspace_state_repository import SessionMode

        # --- Clear any active session context ---
        session_ctx = self._ws_state_repo.get_session_context(task.id)
        if session_ctx and session_ctx.mode == SessionMode.PLANNING:
            try:
                transitioned = self.queue.commit_pending_subtree(task.id)
                logger.info(
                    "PLANNING commit: %d task(s) transitioned for [%s].",
                    len(transitioned), task.id,
                )
            except Exception as e:
                logger.error(
                    "Failed to commit PLANNING subtree for [%s]: %s",
                    task.id, e,
                )
        if session_ctx:
            self._ws_state_repo.clear_session_context(task.id)

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
            if task.title.startswith("[Manager Review]"):
                self._on_manager_review_complete(
                    result.completion_summary or ""
                )
            logger.info("Manager task [%s] complete.", task.id)
            return

        if task.role == AgentRole.CRITIC:
            self._handle_critic_complete(task, result)
            return

        if task.role == AgentRole.MERGE:
            self._handle_merge_complete(task, result)
            return

        logger.warning(
            "Task [%s] has unknown role %r — marking complete directly.",
            task.id, task.role,
        )
        self.queue.mark_complete(task.id)
        self._notify_task_complete(task)


    def _handle_critic_complete(
        self, task: Task, result: LoopResult
    ) -> None:
        """
        Handle Critic task completion — run merge-up on the reviewed task.

        The reviewed task stays BLOCKED_BY_TASK until the merge succeeds.
        On clean merge: mark reviewed task COMPLETE.
        On conflict: transition reviewed task to MERGE role.
        On no merge target: block reviewed task for human input.
        """
        logger.info("Critic task [%s] complete.", task.id)

        if not task.reviews_task_id:
            logger.warning(
                "Critic task [%s] has no reviews_task_id — nothing to merge.",
                task.id,
            )
            return

        reviewed_task = self.queue.get(task.reviews_task_id)
        if reviewed_task is None:
            logger.error(
                "Reviewed task '%s' not found for Critic [%s].",
                task.reviews_task_id, task.id,
            )
            return

        # Determine merge target
        parent_branch = self._get_merge_target(reviewed_task)

        if parent_branch is None:
            # No merge target — block for human
            self._handle_no_merge_target(reviewed_task)
            return

        # Check for protected branch — require PR approval before merge
        repo_name = reviewed_task.repo[0] if reviewed_task.repo else ""
        if self._is_protected_branch(parent_branch, repo_name):
            logger.info(
                "Parent branch '%s' is protected — requesting PR approval "
                "for task [%s].",
                parent_branch, reviewed_task.id,
            )
            self.queue.mark_blocked_by_human(
                reviewed_task.id,
                reason=f"Merge target '{parent_branch}' is protected. PR approval required.",
            )
            try:
                from matrixmouse import comms as comms_module
                m = comms_module.get_manager()
                if m:
                    m.emit("pr_approval_required", {
                        "task_id":       reviewed_task.id,
                        "task_title":    reviewed_task.title,
                        "branch":        reviewed_task.branch,
                        "parent_branch": parent_branch,
                        "repo":          repo_name,
                        "choices": [
                            {
                                "value": "approve",
                                "label": "Push branch and open PR",
                                "description": (
                                    f"Push '{reviewed_task.branch}' to the remote "
                                    f"and open a pull request targeting "
                                    f"'{parent_branch}'."
                                ),
                            },
                            {
                                "value": "reject",
                                "label": "Block for manual resolution",
                                "description": (
                                    "Keep the task blocked. No PR will be created. "
                                    "Resolve manually."
                                ),
                            },
                        ],
                    })
            except Exception as e:
                logger.warning("Failed to emit pr_approval_required: %s", e)
            return

        # Get repo root
        if not reviewed_task.repo:
            logger.error(
                "Reviewed task [%s] has no repo — cannot merge.",
                reviewed_task.id,
            )
            self._request_human_intervention(
                reviewed_task, None,
                reason="Task has no repo configured — cannot determine merge location.",
            )
            return

        repo_root = self.paths.workspace_root / reviewed_task.repo[0]
        if not repo_root.exists():
            self._request_human_intervention(
                reviewed_task, None,
                reason=f"Repo root '{repo_root}' does not exist.",
            )
            return

        # Run merge-up
        success, info = self._run_merge_up(reviewed_task, parent_branch, repo_root)

        if success:
            # Clean merge — mark reviewed task complete
            # remove_dependency was already called by approve() in task_tools
            # so reviewed_task should now be READY — just mark complete
            self.queue.mark_complete(reviewed_task.id)
            self._notify_task_complete(reviewed_task)
            logger.info(
                "Task [%s] merged and marked COMPLETE.", reviewed_task.id
            )
            return

        if info == "QUEUED":
            # Lock busy — task stays BLOCKED_BY_TASK, will be unblocked
            # when the lock is released and granted to this task
            logger.info(
                "Task [%s] queued for merge into '%s'.",
                reviewed_task.id, parent_branch,
            )
            return

        if info.startswith("CONFLICT:"):
            files_str = info[len("CONFLICT:"):]
            conflicted_files = [f for f in files_str.split(",") if f]
            self._transition_to_merge_agent(
                reviewed_task, parent_branch, repo_root, conflicted_files
            )
            return

        # Other failure (checkout failed, etc.)
        self._ws_state_repo.release_merge_lock(parent_branch, reviewed_task.id)
        self._request_human_intervention(
            reviewed_task, None,
            reason=f"Merge failed: {info}",
        )


    def _handle_merge_complete(
        self, task: Task, result: LoopResult
    ) -> None:
        """
        Handle MergeAgent task completion.

        The MergeAgent called declare_complete after resolving all conflicts
        and git merge --continue was called automatically by resolve_conflict.
        Release the merge lock, push the parent branch to mirror, and mark
        the task COMPLETE.
        """
        logger.info("Merge task [%s] complete.", task.id)

        parent_branch = self._get_merge_target(task)
        if parent_branch:
            repo_root = (
                self.paths.workspace_root / task.repo[0]
                if task.repo else None
            )
            if repo_root and repo_root.exists():
                from matrixmouse.tools.git_tools import push_to_remote
                push_ok, push_err = push_to_remote(
                    parent_branch, MIRROR_REMOTE, repo_root
                )
                if not push_ok:
                    logger.warning(
                        "Post-merge push failed for '%s': %s",
                        parent_branch, push_err,
                    )
            self._ws_state_repo.release_merge_lock(parent_branch, task.id)
            logger.info(
                "Merge lock released on '%s' by task [%s].",
                parent_branch, task.id,
            )

        self.queue.mark_complete(task.id)
        self._notify_task_complete(task)


    def _get_merge_target(self, task: Task) -> str | None:
        """
        Determine the merge target branch for a task.

        Returns the parent task's branch if the task has a parent,
        the configured default_merge_target if set, or None.

        Args:
            task: The task to find a merge target for.

        Returns:
            Branch name to merge into, or None if no target is configured.
        """
        if task.parent_task_id:
            parent = self.queue.get(task.parent_task_id)
            if parent and parent.branch:
                return parent.branch

        default_target = self.config.default_merge_target
        if default_target:
            return default_target

        return None


    def _is_protected_branch(self, branch: str, repo_name: str = "") -> bool:
        """
        Return True if branch is protected.

        Check order:
            1. config.protected_branches list (fast, no I/O)
            2. Cached protected branches in repo_metadata (no API call if fresh)
            3. Live API call via GitRemoteProvider (updates cache on miss)

        Falls back gracefully at each step — if no provider is configured or
        the API call fails, the config list result is returned.

        Args:
            branch:    Branch name to check.
            repo_name: Repo root name (e.g. "MatrixMouse"). Used to look up
                    repo_metadata for cache and provider. Optional — if
                    empty, only the config list is checked.
        """
        # Step 1: config list
        if branch in self.config.protected_branches:
            return True

        if not repo_name:
            return False

        # Step 2: check cache (respects branch_protection_cache_ttl_minutes)
        try:
            result = self._ws_state_repo.get_protected_branches_cached(repo_name)
            print(f"DEBUG: {result}")
            if result is not None:
                branches, cache_timestamp = result
                if cache_timestamp:
                    from datetime import datetime, timezone, timedelta
                    try:
                        cached_at = datetime.fromisoformat(cache_timestamp)
                        if cached_at.tzinfo is None:
                            cached_at = cached_at.replace(tzinfo=timezone.utc)
                        ttl = timedelta(
                            minutes=self.config.branch_protection_cache_ttl_minutes
                        )
                        if datetime.now(timezone.utc) - cached_at < ttl:
                            return branch in branches
                        # Cache expired — fall through to live API call
                    except (ValueError, TypeError):
                        pass
        except Exception as e:
            logger.warning(
                "Failed to read branch protection cache for '%s': %s",
                repo_name, e,
            )

        # Step 3: live API call
        provider = self._get_provider(repo_name)
        if provider is None:
            return False

        try:
            metadata = self._ws_state_repo.get_repo_metadata(repo_name)
            owner_repo = _parse_owner_repo(
                metadata.get("remote_url", "") if metadata else ""
            )
            if not owner_repo:
                return False

            is_protected = provider.is_branch_protected(owner_repo, branch)

            # Update cache with all protected branches for this repo so
            # subsequent checks on sibling branches also hit the cache.
            # If the broader fetch fails, skip — cache update is best-effort.
            try:
                from matrixmouse.git.github_provider import GitHubProvider
                if isinstance(provider, GitHubProvider):
                    branches_data = provider._get(
                        f"/repos/{owner_repo}/branches?protected=true&per_page=100"
                    )
                    protected_names = [
                        b["name"] for b in branches_data if isinstance(b, dict)
                    ]
                    self._ws_state_repo.set_protected_branches_cached(
                        repo_name,
                        protected_names,
                    )
            except Exception:
                pass

            return is_protected

        except Exception as e:
            logger.warning(
                "Branch protection API check failed for '%s'/'%s': %s. "
                "Falling back to config list.",
                repo_name, branch, e,
            )
            return False

    def _get_provider(self, repo_name: str):
        """
        Return a GitRemoteProvider for the named repo, or None.

        Looks up repo_metadata to determine provider type and remote URL.
        Returns None if no provider is configured or the token is missing.

        Args:
            repo_name: Repo root name (e.g. "MatrixMouse").

        Returns:
            GitRemoteProvider instance, or None.
        """
        try:
            metadata = self._ws_state_repo.get_repo_metadata(repo_name)
            if not metadata:
                return None
            provider_type = metadata.get("provider", "")
            if provider_type == "github":
                import os
                from matrixmouse.git.github_provider import GitHubProvider
                token = os.environ.get("GITHUB_TOKEN", "")
                if not token:
                    logger.warning(
                        "GITHUB_TOKEN not set — cannot create GitHubProvider "
                        "for repo '%s'.", repo_name,
                    )
                    return None
                return GitHubProvider(token=token)
            # Future: elif provider_type == "gitlab": ...
            return None
        except Exception as e:
            logger.warning(
                "Failed to get provider for repo '%s': %s", repo_name, e,
            )
            return None
                                                                                

    def _run_merge_up(
        self,
        task: Task,
        parent_branch: str,
        repo_root: Path,
    ) -> tuple[bool, str]:
        """
        Attempt to merge task.branch into parent_branch.

        Acquires the merge lock for parent_branch, runs git merge --no-ff,
        and returns (success, error_or_conflict_info).

        On clean merge: releases lock, pushes parent to mirror, returns (True, "").
        On conflict:    leaves lock held, returns (False, conflicted_files_str).
        On lock busy:   enqueues task and returns (False, "QUEUED").

        Args:
            task:          The task whose branch is being merged.
            parent_branch: The branch to merge into.
            repo_root:     Repository root path.

        Returns:
            (True, "")              — clean merge succeeded
            (False, "QUEUED")       — lock busy, task enqueued
            (False, "CONFLICT:...")  — merge conflict, files listed after colon
        """
        from matrixmouse.tools.git_tools import _git, push_to_remote

        # --- Acquire merge lock ---
        acquired = self._ws_state_repo.acquire_merge_lock(
            parent_branch, task.id
        )
        if not acquired:
            logger.info(
                "Merge lock on '%s' is held — enqueuing task [%s].",
                parent_branch, task.id,
            )
            self._ws_state_repo.enqueue_merge_waiter(parent_branch, task.id)
            return False, "QUEUED"

        logger.info(
            "Merge lock acquired on '%s' for task [%s].",
            parent_branch, task.id,
        )

        # --- Checkout parent branch ---
        ok, err = _git(["checkout", parent_branch], cwd=repo_root)
        if not ok:
            self._ws_state_repo.release_merge_lock(parent_branch, task.id)
            return False, f"CHECKOUT_FAILED:{err}"

        # --- Run merge ---
        ok, output = _git(
            ["merge", "--no-ff", task.branch,
            "-m", f"Merge: {task.title} ({task.id[:8]})"],
            cwd=repo_root,
        )

        if ok:
            # Clean merge — push parent to mirror, release lock
            push_ok, push_err = push_to_remote(
                parent_branch, MIRROR_REMOTE, repo_root
            )
            if not push_ok:
                logger.warning(
                    "Post-merge push to mirror failed for '%s': %s",
                    parent_branch, push_err,
                )
            self._ws_state_repo.release_merge_lock(parent_branch, task.id)
            logger.info(
                "Clean merge of '%s' into '%s' for task [%s].",
                task.branch, parent_branch, task.id,
            )
            return True, ""

        # --- Conflict detected ---
        from matrixmouse.tools.merge_tools import get_conflicted_files
        conflicted = get_conflicted_files(repo_root)

        # Abort the merge — it will be re-run when MergeAgent takes over
        _git(["merge", "--abort"], cwd=repo_root)

        # Checkout back to task branch so the workspace is clean
        _git(["checkout", task.branch], cwd=repo_root)

        logger.info(
            "Merge conflict detected for task [%s]. "
            "Conflicted files: %s. Lock held.",
            task.id, conflicted,
        )
        # Lock is intentionally NOT released — held until MergeAgent resolves
        return False, f"CONFLICT:{','.join(conflicted)}"

    def _replay_merge_decisions(
        self, task: Task, repo_root: Path
    ) -> None:
        """
        Silently re-apply stored merge resolution decisions.

        Called at the start of a resumed MERGE session to fast-forward
        the conflict state to where the agent left off. Decisions are
        applied without adding new messages to context — the agent's
        existing context_messages already document the session history.

        Args:
            task:      The MERGE task with stored decisions.
            repo_root: Repository root.
        """
        import subprocess
        for decision in task.merge_resolution_decisions:
            file = decision.get("file")
            resolution = decision.get("resolution")
            content = decision.get("content")

            if not file or not resolution:
                continue

            try:
                if resolution == "ours":
                    subprocess.run(
                        ["git", "checkout", "--ours", "--", file],
                        cwd=repo_root, capture_output=True,
                    )
                elif resolution == "theirs":
                    subprocess.run(
                        ["git", "checkout", "--theirs", "--", file],
                        cwd=repo_root, capture_output=True,
                    )
                elif resolution == "manual" and content:
                    (repo_root / file).write_text(content, encoding="utf-8")

                subprocess.run(
                    ["git", "add", "--", file],
                    cwd=repo_root, capture_output=True,
                )
                logger.debug(
                    "Replayed merge decision for '%s' (%s) on task [%s].",
                    file, resolution, task.id,
                )
            except Exception as e:
                logger.warning(
                    "Failed to replay merge decision for '%s' on task [%s]: %s",
                    file, task.id, e,
                )

    def _handle_no_merge_target(self, task: Task) -> None:
        """
        Handle a completed task with no merge target.

        Called when a top-level task has no parent branch and no
        default_merge_target is configured. Blocks the task and prompts
        the operator to specify a merge target or create a PR.
        """
        self.queue.mark_blocked_by_human(
            task.id,
            reason=(
                "Task complete but no merge target configured. "
                "Specify a target branch or create a PR via the UI."
            ),
        )
        try:
            from matrixmouse import comms as comms_module
            m = comms_module.get_manager()
            if m:
                m.notify_blocked(
                    f"Task [{task.id}] needs a merge target: {task.title}"
                )
                m.emit("merge_target_required", {
                    "task_id":     task.id,
                    "task_title":  task.title,
                    "branch":      task.branch,
                    "options": [
                        {
                            "value": "specify_target",
                            "label": "Specify merge target",
                            "description": "Choose a branch to merge this work into.",
                        },
                        {
                            "value": "create_pr",
                            "label": "Create pull request",
                            "description": "Push and open a PR on the remote provider.",
                        },
                    ],
                })
        except Exception as e:
            logger.warning("Failed to emit merge_target_required: %s", e)


    def _transition_to_merge_agent(
        self,
        task: Task,
        parent_branch: str,
        repo_root: Path,
        conflicted_files: list[str],
    ) -> None:
        """
        Mutate task to MERGE role and re-queue for conflict resolution.

        Called when _run_merge_up returns a CONFLICT result. Appends a
        conflict notification to context_messages, sets role=MERGE and
        preemptable=False, and transitions task to READY so the scheduler
        picks it up.

        Args:
            task:             The task with merge conflicts.
            parent_branch:    The branch the merge was targeting.
            repo_root:        Repository root path.
            conflicted_files: List of files with conflicts.
        """
        file_list = "\n".join(f"  - {f}" for f in conflicted_files)
        task.context_messages.append({
            "role":    "user",
            "content": (
                f"[Merge Conflict Detected]\n"
                f"Task has been transitioned to Merge Agent for conflict "
                f"resolution.\n\n"
                f"Merging: {task.branch} → {parent_branch}\n\n"
                f"Conflicted files:\n{file_list}\n\n"
                f"Use show_conflict(file) to inspect each conflict, then "
                f"resolve_conflict(file, resolution) to apply your decision. "
                f"The merge will be finalised automatically when all conflicts "
                f"are resolved."
            ),
        })
        task.role = AgentRole.MERGE
        task.preemptable = False

        try:
            self.queue.update(task)
            self.queue.mark_ready(task.id)
        except Exception as e:
            logger.error(
                "Failed to transition task [%s] to MERGE role: %s",
                task.id, e,
            )
            self._ws_state_repo.release_merge_lock(parent_branch, task.id)
            self._request_human_intervention(
                task, None,
                reason=f"Failed to transition to merge resolution: {e}",
            )
            return

        logger.info(
            "Task [%s] transitioned to MERGE role. "
            "Conflicts: %s",
            task.id, conflicted_files,
        )

        try:
            from matrixmouse import comms as comms_module
            m = comms_module.get_manager()
            if m:
                m.emit("merge_conflict_detected", {
                    "task_id":         task.id,
                    "task_title":      task.title,
                    "parent_branch":   parent_branch,
                    "conflicted_files": conflicted_files,
                })
        except Exception as e:
            logger.warning("Failed to emit merge_conflict_detected: %s", e)
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

        try:
            self.queue.add_dependency(critic_task.id, task.id)
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
    # Decision handling
    # -----------------------------------------------------------------------

    def _handle_decision(self, task: Task, result: LoopResult) -> None:
        """
        Handle a DECISION exit from the agent loop.

        Dispatches to the appropriate handler based on result.decision_type.
        All decision types result in the task being BLOCKED_BY_HUMAN until
        the human responds via POST /tasks/{task_id}/decision.

        Args:
            task:   The task that needs a decision.
            result: LoopResult with decision_type and decision_payload.
        """
        dt = result.decision_type

        if dt == "turn_limit_reached":
            self._handle_turn_limit_decision(task, result)
        elif dt == "decomposition_confirmation_required":
            self._handle_decomposition_decision(task, result)
        else:
            # Unknown decision type — block for human with context
            logger.warning(
                "Unknown decision_type '%s' for task [%s] — blocking for human.",
                dt, task.id,
            )
            self._request_human_intervention(
                task, result,
                reason=f"Unknown decision required: {dt}",
            )

    def _handle_turn_limit_decision(
        self, task: Task, result: LoopResult
    ) -> None:
        """
        Handle a turn_limit_reached decision.

        Blocks the task and emits the appropriate modal event based on
        the task's role. Mirrors the previous _handle_turn_limit logic
        exactly — only the entry point has changed.
        """
        self.queue.mark_blocked_by_human(
            task.id,
            reason=(
                f"Turn limit reached "
                f"({result.decision_payload.get('turns_taken', '?')} turns)."
            ),
        )
        self._update_status(blocked=True)

        turns_taken = result.decision_payload.get("turns_taken", result.turns_taken)
        logger.warning(
            "Turn limit reached — Task [%s] %s | %d turns | Role: %s",
            task.id, task.title, turns_taken, task.role.value,
        )

        try:
            from matrixmouse import comms as comms_module
            m = comms_module.get_manager()
            if m:
                m.notify_blocked(
                    f"Task [{task.id}] hit turn limit "
                    f"({turns_taken} turns): {task.title}"
                )

                session_ctx = self._ws_state_repo.get_session_context(task.id)
                if (session_ctx
                        and session_ctx.mode == SessionMode.PLANNING
                        and task.role == AgentRole.MANAGER):
                    try:
                        transitioned = self.queue.commit_pending_subtree(task.id)
                        logger.info(
                            "Planning turn limit: committed %d pending task(s) "
                            "for [%s].",
                            len(transitioned), task.id,
                        )
                    except Exception as e:
                        logger.error(
                            "Failed to commit partial plan for [%s]: %s",
                            task.id, e,
                        )
                    self._ws_state_repo.clear_session_context(task.id)
                    m.emit("planning_turn_limit_reached", {
                        "task_id":     task.id,
                        "task_title":  task.title,
                        "turns_taken": turns_taken,
                        "choices": [
                            {
                                "value": "extend",
                                "label": "Give Manager more planning turns",
                                "description": (
                                    f"Allow the Manager another "
                                    f"{self.config.manager_planning_max_turns} "
                                    f"turns to complete the plan."
                                ),
                            },
                            {
                                "value": "commit",
                                "label": "Commit plan as-is",
                                "description": (
                                    "Accept the partial plan and move all "
                                    "created tasks to the scheduler."
                                ),
                            },
                            {
                                "value": "cancel",
                                "label": "Cancel planning task",
                                "description": (
                                    "Cancel the Manager task and discard "
                                    "the partial plan."
                                ),
                            },
                        ],
                    })
                    return

                if task.role == AgentRole.MERGE:
                    parent_branch = self._get_merge_target(task)
                    if task.repo:
                        repo_root = self.paths.workspace_root / task.repo[0]
                        if repo_root.exists():
                            from matrixmouse.tools.git_tools import _git
                            _git(["merge", "--abort"], cwd=repo_root)
                            _git(["checkout", task.branch], cwd=repo_root)

                    m.emit("merge_conflict_resolution_turn_limit_reached", {
                        "task_id":         task.id,
                        "task_title":      task.title,
                        "turns_taken":     turns_taken,
                        "parent_branch":   parent_branch or "",
                        "resolved_so_far": task.merge_resolution_decisions,
                        "choices": [
                            {
                                "value": "extend",
                                "label": "Give Merge Agent more turns",
                                "description": (
                                    f"Allow another "
                                    f"{self.config.merge_conflict_max_turns} "
                                    f"turns. Previously resolved conflicts will "
                                    f"be automatically re-applied."
                                ),
                            },
                            {
                                "value": "abort",
                                "label": "Abort merge",
                                "description": (
                                    "Cancel the merge. Task stays complete on "
                                    "its own branch. Manual merge required."
                                ),
                            },
                        ],
                    })
                    return

                if task.role == AgentRole.CRITIC:
                    reviewed_task_id = task.reviews_task_id or ""
                    m.emit("critic_turn_limit_reached", {
                        "task_id":          task.id,
                        "task_title":       task.title,
                        "reviewed_task_id": reviewed_task_id,
                        "turns_taken":      turns_taken,
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
                    return

                m.emit("turn_limit_reached", {
                    "task_id":     task.id,
                    "task_title":  task.title,
                    "role":        task.role.value,
                    "turns_taken": turns_taken,
                    "turn_limit":  task.turn_limit or self.config.agent_max_turns,
                })

        except Exception as e:
            logger.warning("Failed to send turn limit notification: %s", e)

    def _handle_decomposition_decision(
        self, task: Task, result: LoopResult
    ) -> None:
        """
        Handle a decomposition_confirmation_required decision.

        Blocks the task and emits the event so the human can approve or
        deny further decomposition. On approval, the orchestrator increments
        decomposition_confirmed_depth and unblocks the task — the pending
        split_task call replays automatically from pending_tool_calls.

        Args:
            task:   The Manager task that hit the depth limit.
            result: LoopResult carrying the decision_payload from split_task.
        """
        payload = result.decision_payload

        self.queue.mark_blocked_by_human(
            task.id,
            reason=(
                f"Decomposition depth limit reached at depth "
                f"{payload.get('current_depth', '?')}. "
                f"Human confirmation required."
            ),
        )
        self._update_status(blocked=True)

        logger.info(
            "Decomposition depth limit — Task [%s] blocked at depth %d.",
            task.id, payload.get("current_depth", 0),
        )

        try:
            from matrixmouse import comms as comms_module
            m = comms_module.get_manager()
            if m:
                m.notify_blocked(
                    f"Task [{task.id}] needs decomposition approval: {task.title}"
                )
                depth_limit = getattr(self.config, "decomposition_depth_limit", 3)
                m.emit("decomposition_confirmation_required", {
                    "task_id":           task.id,
                    "task_title":        task.title,
                    "current_depth":     payload.get("current_depth", 0),
                    "allowed_depth":     payload.get("allowed_depth", depth_limit),
                    "proposed_subtasks": payload.get("proposed_subtasks", []),
                    "choices": [
                        {
                            "value": "allow",
                            "label": "Allow further decomposition",
                            "description": (
                                f"Grant another {depth_limit} levels of "
                                f"decomposition depth for this task."
                            ),
                        },
                        {
                            "value": "deny",
                            "label": "Do not decompose further",
                            "description": (
                                "The Manager must complete the task within "
                                "the current depth. The pending split will "
                                "be cancelled."
                            ),
                        },
                    ],
                })
        except Exception as e:
            logger.warning(
                "Failed to emit decomposition_confirmation_required: %s", e
            )


    # -----------------------------------------------------------------------
    # Time slice and preemption
    # -----------------------------------------------------------------------

    def _should_yield(self, task: Task) -> bool:
        """
        Return True if the orchestrator should yield this task back to
        the scheduler after the current inference boundary.
        Respects task.preemptable: non-preemptable tasks never yield.
        """
        if not task.preemptable:
            return False

        if self._scheduler.time_slice_expired(task):
            logger.debug("Time slice expired for task [%s].", task.id)
            return True

        preempting = [
            t for t in self.queue.active_tasks()
            if t.preempt
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
                m.notify(f"Task complete: {task.title}", f"{task.description[:80]}...")
                m.emit("complete", {
                    "task_id":    task.id,
                    "task_title": task.title,
                })
        except Exception as e:
            logger.warning("Failed to send completion notification: %s", e)

    
    
    def _handle_budget_exhausted(
        self,
        task: "Task",
        exc: "TokenBudgetExceededError",
    ) -> None:
        """Move a task to WAITING after a budget exhaustion event.
 
        Calculates wait_until from the exception\'s retry_after field
        (which already incorporates both our tracker\'s window calculation
        and any API-supplied Retry-After hint).
 
        Emits a one-time notification so the operator knows a task is
        waiting on budget, then marks the backend as exhausted for the
        current scheduling cycle so other tasks on the same backend are
        not retried needlessly.
 
        Args:
            task: The task whose inference was blocked by budget exhaustion.
            exc:  The TokenBudgetExceededError carrying provider and wait_until.
        """
        wait_until_dt = exc.retry_after
        wait_until_iso = wait_until_dt.isoformat() if wait_until_dt else None
 
        task.wait_until = wait_until_iso
        task.wait_reason = f"budget:{exc.provider}"
        task.status = TaskStatus.WAITING
        self.queue.update(task)
 
        self._mark_backend_exhausted(exc.provider)
 
        logger.warning(
            "Task [%s] waiting on %s budget exhaustion. "
            "wait_until=%s",
            task.id, exc.provider, wait_until_iso or "unknown",
        )
        from matrixmouse import comms as comms_module
        m = comms_module.get_manager()
        if m:
            try:
                m.notify(
                    title=f"Task [{task.id}] waiting — {exc.provider} budget exhausted",
                    message=(
                        f"Task: {task.title}\\n"
                        f"Provider: {exc.provider}\\n"
                        f"Earliest retry: {wait_until_iso or 'unknown'}"
                    ),
                )
                m.emit("task_waiting_on_budget", {
                    "task_id":    task.id,
                    "task_title": task.title,
                    "provider":   exc.provider,
                    "wait_until": wait_until_iso,
                })
            except Exception as notify_err:
                logger.warning(
                    "Failed to emit budget exhaustion notification: %s",
                    notify_err,
                )
 
    def _maybe_promote_waiting_tasks(self) -> int:
        """Promote WAITING tasks whose wait_until has passed back to READY.
 
        Called at the top of each main scheduling cycle. Scans all WAITING
        tasks and moves any whose wait_until is in the past (or has no
        wait_until set) back to READY so the scheduler can pick them up.
 
        Returns:
            Number of tasks promoted to READY.
        """
        now = datetime.now(timezone.utc)
        promoted = 0
 
        for task in self.queue.all_tasks():
            if task.status != TaskStatus.WAITING:
                continue
 
            should_promote = False
 
            if task.wait_until is None:
                # No time gate — promote immediately
                should_promote = True
            else:
                try:
                    wait_until_dt = datetime.fromisoformat(task.wait_until)
                    if wait_until_dt.tzinfo is None:
                        wait_until_dt = wait_until_dt.replace(tzinfo=timezone.utc)
                    if now >= wait_until_dt:
                        should_promote = True
                except (ValueError, TypeError):
                    # Unparseable wait_until — promote and log
                    logger.warning(
                        "Task [%s] has unparseable wait_until %r — "
                        "promoting to READY.",
                        task.id, task.wait_until,
                    )
                    should_promote = True
 
            if should_promote:
                task.status = TaskStatus.READY
                task.wait_until = None
                task.wait_reason = ""
                self.queue.update(task)
                promoted += 1
                logger.info(
                    "Task [%s] promoted from WAITING to READY "
                    "(wait_reason was: %r).",
                    task.id, task.wait_reason or "(none)",
                )
 
        return promoted
 
    def _mark_backend_exhausted(self, backend: str) -> None:
        """Mark a backend as exhausted for the current scheduling cycle.
 
        Thread-safe. Called by worker threads when a budget error occurs.
        The scheduling thread reads and clears this set at the top of each
        cycle via _get_and_clear_exhausted_backends.
 
        Args:
            backend: Provider name, e.g. ``"anthropic"``.
        """
        with self._exhausted_backends_lock:
            self._exhausted_backends.add(backend)
 
    def _get_and_clear_exhausted_backends(self) -> set[str]:
        """Return and clear the set of exhausted backends for this cycle.
 
        Thread-safe. Called by the scheduling thread at the top of each
        cycle to get a snapshot of which backends hit budget limits since
        the last cycle, then clears the set for the next cycle.
 
        Returns:
            Snapshot of exhausted backend names.
        """
        with self._exhausted_backends_lock:
            exhausted = set(self._exhausted_backends)
            self._exhausted_backends.clear()
        return exhausted
    

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
            "aging_rate":        self.config.priority_aging_rate,
            "max_aging_bonus":   self.config.priority_max_aging_bonus,
            "importance_weight": self.config.priority_importance_weight,
            "urgency_weight":    self.config.priority_urgency_weight,
        }
    