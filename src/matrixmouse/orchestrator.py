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

    Returns an empty string if the diff cannot be retrieved — the
    Critic will note the absence and use get_git_diff directly.

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
        self._scheduler = Scheduler(config)

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
            2. Ask the scheduler for the next task
            3. If a task is ready — run it
            4. If nothing is ready — wait on the condition variable
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
        result  = run_result.loop_result
        detector = run_result.detector

        # --- Yield (time slice expired or preemption) ---
        if result.exit_reason == LoopExitReason.YIELD:
            logger.info(
                "Task [%s] yielding. Returning to READY.", task.id
            )
            self.queue.mark_ready(task.id)
            return

        # --- Complete ---
        if result.exit_reason == LoopExitReason.COMPLETE:
            self._handle_complete(task, result)
            return

        # --- Escalate (Coder cascade) ---
        # TODO: currently escalates recursively; make this iterative for concurrency when multi-threaded model is applied
        if result.exit_reason == LoopExitReason.ESCALATE:
            if task.role == AgentRole.CODER:
                escalated, new_model = self._router.escalate(detector)
                if escalated:
                    logger.info(
                        "Task [%s] escalating to %s.",
                        task.id, new_model,
                    )
                    # Build handoff messages and re-enter immediately
                    handoff_messages = self._router.build_handoff(
                        detector, result.messages
                    )
                    task.context_messages = handoff_messages
                    self.queue.update(task)
                    self._run_task(task)
                    return
            # At ceiling or non-escalatable role
            logger.warning(
                "Task [%s] at cascade ceiling or non-escalatable role — "
                "human needed.", task.id,
            )
            self._request_human_intervention(
                task, result,
                reason="At top of model cascade, still stuck.",
            )
            return

        # --- Max turns ---
        if result.exit_reason == LoopExitReason.MAX_TURNS:
            self._request_human_intervention(
                task, result, reason="Turn limit reached."
            )
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

        Wires all subsystems (task tools, comms, memory, context
        manager, persist, yield check) and runs the loop to completion
        or yield.

        Args:
            task:     The task being executed.
            agent:    The concrete BaseAgent instance for this task's role.
            messages: The starting message list (fresh or resumed).

        Returns:
            RunResult with the loop outcome and stuck detector state.
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
        task that blocks the original task. The original task will only
        be marked COMPLETE after the Critic calls approve().

        For Manager tasks: mark COMPLETE directly. Manager review
        summaries are stored in last_review_summary for the next cycle.

        For Critic tasks: the approve()/deny() tools handle task state
        directly in task_tools.py. By the time the loop exits COMPLETE
        here, approve() has already marked the reviewed task and this
        Critic task COMPLETE. Nothing further to do.

        Args:
            task:   The task whose loop exited with COMPLETE.
            result: The LoopResult from the agent loop.
        """
        if task.role in (AgentRole.CODER, AgentRole.WRITER):
            self._create_critic_review(task, result)
            return

        if task.role == AgentRole.MANAGER:
            # Store review summary for the next review cycle
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
            logger.info("Manager task [%s] complete.", task.id)
            return

        if task.role == AgentRole.CRITIC:
            # approve()/deny() in task_tools already updated task states.
            # The Critic task itself was marked COMPLETE there.
            # Just log and update status.
            logger.info("Critic task [%s] complete.", task.id)
            return

        # Unknown role — mark complete and log
        logger.warning(
            "Task [%s] has unknown role %r — marking complete directly.",
            task.id, task.role,
        )
        self.queue.mark_complete(task.id)
        self._notify_task_complete(task)

    def _create_critic_review(self, task: Task, result: LoopResult) -> None:
        """
        Create a Critic review task for a completed Coder or Writer task.

        The original task is set to BLOCKED_BY_TASK until the Critic
        approves or denies. The Critic task is given the reviewed task's
        full context, diff, and definition of done as its description.

        Args:
            task:   The Coder/Writer task that called declare_complete.
            result: The LoopResult containing the completion summary.
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

        # Block the original task on the Critic review
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

        Args:
            task:  The task being executed.
            agent: The concrete BaseAgent instance for this task's role.

        Returns:
            list: Message list ready to pass to AgentLoop.
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