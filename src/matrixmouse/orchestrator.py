"""
matrixmouse/orchestrator.py

Task and Phase Manager. The outermost control loop.

Responsible for:
    - Fetching tasks from a task queue (local file queue for now;
      GitHub/Gitea support to be added later without changing this module)
    - Scoping each task: identifying relevant files, design documents,
      and prior notes
    - Managing the SDLC phase state machine:
          design → critique → implement → test → review → done
    - Deciding which agent role (designer, implementer, critic) handles
      each phase
    - Routing escalated or blocked tasks to the human via comms
    - Ensuring no phase is skipped; implementation only begins after
      design is approved
    - Batching tasks by type to minimise model-switching overhead

Phase transition rules:
    - design → critique:    design document written, no code exists yet
    - critique → implement: design document status set to `approved`
    - implement → test:     at least one write tool called successfully
    - test → review:        test suite passes
    - review → done:        human approves PR, or auto-approved if
                            confidence threshold met

Do not add inference logic here. That belongs to loop.py.
Do not add model selection logic here. That belongs to router.py.
"""

from __future__ import annotations

import json
import logging
import uuid
import functools
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, auto
from pathlib import Path
from typing import Optional

from matrixmouse.config import MatrixMouseConfig, MatrixMousePaths
from matrixmouse.context import ContextManager
from matrixmouse.loop import AgentLoop, LoopExitReason, LoopResult
from matrixmouse.phases import Phase, PHASE_SEQUENCE, next_phase
from matrixmouse.router import Router
from matrixmouse.stuck import StuckDetector
from matrixmouse.tools._safety import reconfigure_for_task
from matrixmouse.utils.file_lock import locked_json, LockTimeoutError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# PhaseResult — bundles loop outcome with stuck diagnostics
# ---------------------------------------------------------------------------

@dataclass
class PhaseResult:
    """
    The outcome of a single phase run.
    Bundles the LoopResult with the StuckDetector so _run_task can
    access diagnostics when handling escalation.
    """
    loop_result: LoopResult
    detector: StuckDetector

# ---------------------------------------------------------------------------
# TaskStatus
# ---------------------------------------------------------------------------

class TaskStatus(Enum):
    PENDING          = "pending"           # created, not yet started
    ACTIVE           = "active"            # currently being worked on
    BLOCKED_BY_TASK  = "blocked_by_task"   # waiting on dependent tasks
    BLOCKED_BY_HUMAN = "blocked_by_human"  # waiting on human input
    COMPLETE         = "complete"          # terminal — success
    CANCELLED        = "cancelled"         # terminal — abandoned

    @property
    def is_terminal(self) -> bool:
        return self in (TaskStatus.COMPLETE, TaskStatus.CANCELLED)

    @property
    def is_blocked(self) -> bool:
        return self in (TaskStatus.BLOCKED_BY_TASK, TaskStatus.BLOCKED_BY_HUMAN)


# ---------------------------------------------------------------------------
# Task model
# ---------------------------------------------------------------------------

@dataclass
class Task:
    """
    A unit of work for the agent to complete.

    Designed to be source-agnostic and repo-agnostic. The `repo` field
    is a list to support cross-repo tasks, but most tasks will have a
    single entry. Path safety is widened to all named repos when a task
    spans multiple repos.

    Dependency graph:
        blocked_by: task IDs that must be COMPLETE before this can start.
        blocking:   task IDs that cannot start until this is COMPLETE.
        parent_task: ID of the task this was decomposed from, if any.
        subtasks:   IDs of tasks this was decomposed into, if any.

    Priority:
        importance and urgency are floats 0.0-1.0.
        priority_score() combines them with an aging bonus.
        Scheduling always picks the highest-scoring unblocked task.
    """
    # Identity
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    title: str = ""
    description: str = ""

    # Repo scope — list to support cross-repo tasks
    # Most tasks will have exactly one entry
    repo: list[str] = field(default_factory=list)

    # SDLC state
    phase: "Phase" = None   # imported from phases.py at runtime to avoid circular
    status: TaskStatus = TaskStatus.PENDING
    target_files: list[str] = field(default_factory=list)
    notes: str = ""

    # Dependency graph
    blocked_by: list[str] = field(default_factory=list)   # task IDs
    blocking: list[str] = field(default_factory=list)     # task IDs
    parent_task: Optional[str] = None                     # task ID
    subtasks: list[str] = field(default_factory=list)     # task IDs

    # Priority (Eisenhower matrix)
    importance: float = 0.5    # 0.0-1.0
    urgency: float = 0.5       # 0.0-1.0

    # Timestamps
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    started_at: Optional[str] = None
    completed_at: Optional[str] = None

    # Source
    source: str = "local"   # "local" | "github" | "gitea"

    def priority_score(self, aging_rate: float = 0.01, max_aging_bonus: float = 0.3) -> float:
        """
        Compute a priority score for scheduling.

        Base score: importance weighted at 60%, urgency at 40%.
        Aging bonus: increases by aging_rate per day, capped at max_aging_bonus.
        This prevents starvation of low-priority tasks.

        Args:
            aging_rate:       Priority increase per day of age.
            max_aging_bonus:  Maximum bonus from aging (caps at this value).

        Returns:
            Float 0.0-1.0, higher means schedule sooner.
        """
        base = (self.importance * 0.6) + (self.urgency * 0.4)
        try:
            created = datetime.fromisoformat(self.created_at)
            age_days = (datetime.now(timezone.utc) - created).days
            aging_bonus = min(age_days * aging_rate, max_aging_bonus)
        except (ValueError, TypeError):
            aging_bonus = 0.0
        return min(base + aging_bonus, 1.0)

    def is_ready(self, completed_ids: set[str]) -> bool:
        """
        Return True if all tasks in blocked_by are complete.

        Args:
            completed_ids: Set of task IDs with terminal status.
        """
        return all(dep in completed_ids for dep in self.blocked_by)

    def to_dict(self) -> dict:
        """Serialise to a JSON-compatible dict."""
        from matrixmouse.phases import Phase
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "repo": self.repo,
            "phase": self.phase.name if self.phase else None,
            "status": self.status.value,
            "target_files": self.target_files,
            "notes": self.notes,
            "blocked_by": self.blocked_by,
            "blocking": self.blocking,
            "parent_task": self.parent_task,
            "subtasks": self.subtasks,
            "importance": self.importance,
            "urgency": self.urgency,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Task":
        """Deserialise from a dict loaded from tasks.json."""
        from matrixmouse.phases import Phase
        phase_str = data.get("phase")
        phase = Phase[phase_str] if phase_str else Phase.DESIGN

        status_str = data.get("status", "pending")
        try:
            status = TaskStatus(status_str)
        except ValueError:
            # Handle legacy tasks.json with done:true/false
            done = data.get("done", False)
            status = TaskStatus.COMPLETE if done else TaskStatus.PENDING

        return cls(
            id=data.get("id", str(uuid.uuid4())[:8]),
            title=data.get("title", ""),
            description=data.get("description", ""),
            repo=data.get("repo", []),
            phase=phase,
            status=status,
            target_files=data.get("target_files", []),
            notes=data.get("notes", ""),
            blocked_by=data.get("blocked_by", []),
            blocking=data.get("blocking", []),
            parent_task=data.get("parent_task"),
            subtasks=data.get("subtasks", []),
            importance=data.get("importance", 0.5),
            urgency=data.get("urgency", 0.5),
            created_at=data.get("created_at", datetime.now(timezone.utc).isoformat()),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            source=data.get("source", "local"),
        )

# ---------------------------------------------------------------------------
# TaskQueue
# ---------------------------------------------------------------------------

class TaskQueue:
    """
    Workspace-level task queue backed by <workspace>/.matrixmouse/tasks.json.

    All tasks for all repos live here. The scheduler reads from this queue
    and selects the next task to work on based on priority and dependencies.

    The file is read on construction and saved after every mutation.
    Last-write-wins — concurrent access is not safe, enforced by the
    workspace-level PID lockfile.
    """

    def __init__(self, tasks_file: Path):
        self.tasks_file = tasks_file
        self._tasks: dict[str, Task] = {}
        self._load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------


    def _load(self) -> None:
        """Load tasks from the queue file. Creates an empty queue if missing."""
        if not self.tasks_file.exists():
            logger.info(
                "No task queue found at %s. Starting with empty queue.",
                self.tasks_file,
            )
            return
        try:
            with locked_json(self.tasks_file) as (raw_list, _):
                for raw in raw_list:
                    task = Task.from_dict(raw)
                    self._tasks[task.id] = task
            logger.info(
                "Loaded %d tasks from %s", len(self._tasks), self.tasks_file
            )
        except LockTimeoutError as e:
            logger.error("Failed to load tasks: %s", e)
            raise

    def _save(self) -> None:
        """Persist current task list to the queue file."""
        try:
            with locked_json(self.tasks_file) as (_, save):
                save([t.to_dict() for t in self._tasks.values()])
        except LockTimeoutError as e:
            logger.error("Failed to save tasks: %s", e)
            raise


    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def get(self, task_id: str) -> Optional[Task]:
        """Return a task by ID, or None if not found."""
        return self._tasks.get(task_id)

    def all_tasks(self) -> list[Task]:
        """Return all tasks."""
        return list(self._tasks.values())

    def active_tasks(self) -> list[Task]:
        """Return all non-terminal tasks."""
        return [t for t in self._tasks.values() if not t.status.is_terminal]

    def completed_ids(self) -> set[str]:
        """Return the set of IDs for all terminal tasks."""
        return {t.id for t in self._tasks.values() if t.status.is_terminal}

    def is_empty(self) -> bool:
        """Return True if there are no non-terminal tasks."""
        return len(self.active_tasks()) == 0

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def add(self, task: Task) -> Task:
        """
        Add a new task to the queue.

        Args:
            task: Task to add. ID is auto-generated if not set.

        Returns:
            The added task (with ID assigned).
        """
        self._tasks[task.id] = task
        self._save()
        logger.info("Task %s added: %s", task.id, task.title)
        return task

    def update(self, task: Task) -> None:
        """Persist changes to an existing task."""
        if task.id not in self._tasks:
            raise KeyError(f"Task {task.id} not found in queue.")
        self._tasks[task.id] = task
        self._save()

    def mark_active(self, task_id: str) -> None:
        """Mark a task as actively being worked on."""
        task = self._require(task_id)
        task.status = TaskStatus.ACTIVE
        task.started_at = datetime.now(timezone.utc).isoformat()
        self.update(task)

    def mark_complete(self, task_id: str) -> None:
        """Mark a task complete and unblock any tasks waiting on it."""
        task = self._require(task_id)
        task.status = TaskStatus.COMPLETE
        task.completed_at = datetime.now(timezone.utc).isoformat()
        self.update(task)
        self._unblock_dependents(task_id)
        logger.info("Task %s complete.", task_id)

    def mark_blocked_by_human(self, task_id: str, reason: str = "") -> None:
        """Mark a task as blocked pending human input."""
        task = self._require(task_id)
        task.status = TaskStatus.BLOCKED_BY_HUMAN
        if reason:
            task.notes = (task.notes + f"\n[BLOCKED] {reason}").strip()
        self.update(task)
        logger.warning("Task %s blocked by human. Reason: %s", task_id, reason)

    def add_subtask(
        self,
        parent_id: str,
        title: str,
        description: str,
        repo: list[str] | None = None,
        target_files: list[str] | None = None,
        importance: float = 0.5,
        urgency: float = 0.5,
    ) -> Task:
        """
        Create a subtask of an existing task with dependency links
        set up automatically.

        The subtask inherits the parent's repo by default. The parent
        is automatically added to the subtask's blocked_by list, and
        the subtask is added to the parent's subtasks list. The parent's
        status is set to BLOCKED_BY_TASK.

        Args:
            parent_id:    ID of the parent task being decomposed.
            title:        Subtask title.
            description:  Subtask description.
            repo:         Override repo list. Defaults to parent's repo.
            target_files: Files the subtask focuses on.
            importance:   Priority importance score.
            urgency:      Priority urgency score.

        Returns:
            The newly created subtask.
        """
        from matrixmouse.phases import Phase

        parent = self._require(parent_id)

        subtask = Task(
            title=title,
            description=description,
            repo=repo if repo is not None else list(parent.repo),
            phase=Phase.DESIGN,
            status=TaskStatus.PENDING,
            target_files=target_files or [],
            blocked_by=[],         # subtask is not blocked by parent —
            blocking=[parent_id],  # it blocks the parent
            parent_task=parent_id,
            importance=importance,
            urgency=urgency,
            source=parent.source,
        )
        self.add(subtask)

        # Update parent
        parent.subtasks.append(subtask.id)
        parent.blocked_by.append(subtask.id)
        parent.status = TaskStatus.BLOCKED_BY_TASK
        self.update(parent)

        # Check for cycles immediately
        cycle = self._find_cycle(subtask.id)
        if cycle:
            # Roll back the subtask rather than leave the queue in a bad state
            self._tasks.pop(subtask.id)
            parent.subtasks.remove(subtask.id)
            parent.blocked_by.remove(subtask.id)
            if not parent.blocked_by:
                parent.status = TaskStatus.PENDING
            self.update(parent)
            self._save()
            raise ValueError(
                f"Dependency cycle detected. Adding this subtask would create "
                f"a cycle: {' → '.join(cycle)}. The subtask was not created."
            )

        logger.info(
            "Subtask %s created under parent %s: %s",
            subtask.id, parent_id, title
        )
        return subtask

    def detect_cycles(self) -> list[list[str]]:
        """
        Find all dependency cycles in the task graph.

        Returns:
            List of cycles, each cycle is a list of task IDs forming
            the cycle. Empty list means no cycles.
        """
        cycles = []
        visited = set()

        for task_id in self._tasks:
            if task_id not in visited:
                cycle = self._find_cycle(task_id, visited)
                if cycle:
                    cycles.append(cycle)

        return cycles

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _require(self, task_id: str) -> Task:
        task = self._tasks.get(task_id)
        if task is None:
            raise KeyError(f"Task '{task_id}' not found in queue.")
        return task

    def _unblock_dependents(self, completed_task_id: str) -> None:
        """
        After a task completes, check all tasks that were blocked by it.
        If all their dependencies are now complete, set them back to PENDING.
        """
        completed = self.completed_ids()
        for task in self._tasks.values():
            if (
                task.status == TaskStatus.BLOCKED_BY_TASK
                and completed_task_id in task.blocked_by
                and task.is_ready(completed)
            ):
                task.status = TaskStatus.PENDING
                self.update(task)
                logger.info(
                    "Task %s unblocked after %s completed.",
                    task.id, completed_task_id
                )

    def _find_cycle(
        self,
        start_id: str,
        visited: set[str] | None = None,
        path: list[str] | None = None,
        ) -> list[str] | None:
        """
        DFS cycle detection from start_id through the blocked_by graph.
        Returns the cycle as a list of IDs if found, None otherwise.
        """
        if visited is None:
            visited = set()
        if path is None:
            path = []

        visited.add(start_id)
        path.append(start_id)

        task = self._tasks.get(start_id)
        if task:
            for dep_id in task.blocked_by:
                if dep_id in path:
                    # Found a cycle — return the cycle portion of the path
                    cycle_start = path.index(dep_id)
                    return path[cycle_start:] + [dep_id]
                if dep_id not in visited:
                    result = self._find_cycle(dep_id, visited, path)
                    if result:
                        return result

        path.pop()
        return None


# ---------------------------------------------------------------------------
# System prompts per phase
# ---------------------------------------------------------------------------
# TODO: Move these to configurable prompt templates in docs/ or .matrixmouse/
#       once the system is stable enough to warrant it.

def _build_system_prompt(phase: Phase, task: Task) -> str:
    """
    Build the system prompt for the agent based on the current phase.
    Each phase gets a role-appropriate framing and a clear statement of
    what done looks like.
    """
    base = (
        "You are MatrixMouse, an autonomous coding agent. "
        "Work carefully and incrementally. "
        "Use tools to explore before making changes. "
        "Do not guess at file contents — read them first. "
        "When you have completed your goal, call declare_complete with a summary.\n\n"
        f"Task: {task.title}\n"
        f"Description: {task.description}\n"
    )

    if task.target_files:
        base += f"Focus files: {', '.join(task.target_files)}\n"

    phase_instructions = {
        Phase.DESIGN: (
            "Your role is DESIGNER. "
            "Do not write any code. "
            "Produce a design document for this task using the template at docs/design/template.md. "
            "Write it to docs/design/<module_name>.md. "
            "The document must have no Open Questions before you declare complete."
        ),
        Phase.CRITIQUE: (
            "Your role is CRITIC. "
            "Read the design document for this task. "
            "Identify any gaps, ambiguities, missing error handling, or interface problems. "
            "Update the Open Questions section with any issues found. "
            "If the design is sound, set status to `approved` in the frontmatter and declare complete."
        ),
        Phase.IMPLEMENT: (
            "Your role is IMPLEMENTER. "
            "Read the approved design document before writing any code. "
            "Implement exactly what the design specifies — no more, no less. "
            "Run tests after each logical unit of work. "
            "Commit your progress when tests pass."
        ),
        Phase.TEST: (
            "Your role is TESTER. "
            "Run the full test suite. "
            "If tests fail, diagnose and fix the failures. "
            "Do not add new features — only make failing tests pass. "
            "Declare complete only when all tests pass."
        ),
        Phase.REVIEW: (
            "Your role is REVIEWER. "
            "Read the design document and the implementation. "
            "Verify the implementation matches the design. "
            "Check for obvious issues: missing error handling, unclear naming, "
            "undocumented public functions. "
            "Note any issues as comments. Declare complete when satisfied."
        ),
    }

    instruction = phase_instructions.get(phase, "Complete your assigned role and declare done.")
    return base + "\n" + instruction


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

class Orchestrator:
    """
    The outermost control loop. Drives tasks through the SDLC phase
    state machine by repeatedly invoking AgentLoop for each phase.

    Instantiated once in main.py and kept alive for the session.
    Call run() to start processing the task queue.
    """

    def __init__(
        self,
        config: MatrixMouseConfig,
        paths: MatrixMousePaths,
        graph=None,
    ):
        self.config = config
        self.paths = paths
        self.graph = graph

        queue_path = paths.workspace_root / ".matrixmouse" / "tasks.json"
        self.queue = TaskQueue(queue_path)
        self._router = Router(config)
        from matrixmouse.comms import get_manager
        self._comms = get_manager()

    def run(self) -> None:
        """
        Process tasks from the queue until it is empty or interrupted.
        Each task is driven through the full phase sequence before the
        next task begins.
        """
        logger.info("Orchestrator starting. Queue: %s", self.queue.queue_path)

        if self.queue.is_empty():
            logger.info("Task queue is empty. Nothing to do.")
            print("Task queue is empty. Add tasks to .matrixmouse/tasks.json to get started.")
            return

        while not self.queue.is_empty():
            task = self.queue.get_next()
            if task is None:
                break
            logger.info("Starting task: [%s] %s", task.id, task.title)
            self._run_task(task)

        logger.info("All tasks complete.")

    def _run_task(self, task: Task) -> None:
        """
        Drive a single task through all phases in sequence.
        Handles escalation and blocked tasks at each phase boundary.
        """
        # TODO: restore phase from checkpoint if task was interrupted
        current_phase = task.phase
        messages = self._build_initial_messages(task, current_phase)

        # Configure safety module to task
        reconfigure_for_task(task.repo, self.paths.workspace_root)

        while current_phase != Phase.DONE:
            logger.info("Task %s entering phase: %s", task.id, current_phase.name)

            phase_result = self._run_phase(task, current_phase, messages)
            result = phase_result.loop_result
            detector = phase_result.detector

            if result.exit_reason == LoopExitReason.COMPLETE:
                logger.info(
                    "Task %s phase %s complete. Summary: %s",
                    task.id, current_phase.name, result.completion_summary
                )

                # Record success toward de-escalation if this was a coding phase
                if current_phase in (Phase.IMPLEMENT, Phase.TEST):
                    self._router.record_success()

                advanced = next_phase(current_phase)
                if advanced is None or advanced == Phase.DONE:
                    self.queue.mark_complete(task.id)
                    logger.info("Task %s fully complete.", task.id)
                    return

                current_phase = advanced
                messages = self._splice_phase_prompt(result.messages, task, current_phase)

            elif result.exit_reason == LoopExitReason.ESCALATE:
                escalated, new_model = self._router.escalate(detector)

                if escalated:
                    logger.info(
                        "Task %s escalating to %s for phase %s.",
                        task.id, new_model, current_phase.name
                    )
                    # Build clean handoff context and retry the same phase
                    messages = self._router.build_handoff(detector, result.messages)
                    # Loop continues — same phase, new model via _router.model_for_phase()
                else:
                    # Already at top of cascade — needs human
                    logger.warning(
                        "Task %s at cascade ceiling during phase %s. "
                        "Human intervention required.",
                        task.id, current_phase.name
                    )
                    self._request_human_intervention(task, current_phase, result)
                    return

            elif result.exit_reason == LoopExitReason.MAX_TURNS:
                logger.error(
                    "Task %s hit turn limit during phase %s.",
                    task.id, current_phase.name
                )
                self._request_human_intervention(task, current_phase, result)
                return

            elif result.exit_reason == LoopExitReason.ERROR:
                logger.error(
                    "Task %s encountered an unrecoverable error during phase %s.",
                    task.id, current_phase.name
                )
                self._request_human_intervention(task, current_phase, result)
                return

    def _run_phase(self, task: Task, phase: Phase, messages: list) -> PhaseResult:
        """
        Instantiate and run an AgentLoop for a single phase of a task.
        Returns a PhaseResult containing both the loop outcome and the
        stuck detector so the caller can use diagnostics for escalation.
        """
        # configure task_tools with current task info
        from matrixmouse.tools import task_tools
        task_tools.configure(self.queue, task.id)

        # Bind current_repo into comms callable


        from matrixmouse.comms import poll_interjection
        current_repo = task.repo[0] if task.repo else None
        scoped_comms = functools.partial(poll_interjection, current_repo=current_repo)

        detector = StuckDetector(phase=phase)
        context_manager = ContextManager(
            config=self.config,
            paths=self.paths,
            coder_model=self._router.model_for_phase(phase),
        )
        loop = AgentLoop(
            model=self._router.model_for_phase(phase),
            messages=messages,
            config=self.config,
            paths=self.paths,
            context_manager=context_manager,
            stuck_detector=detector,
            comms=scoped_comms,
            current_repo=current_repo,
        )
        result = loop.run()

        if result.exit_reason == LoopExitReason.ESCALATE:
            logger.warning("Stuck summary: %s", detector.summary)

        return PhaseResult(loop_result=result, detector=detector)

    def _build_initial_messages(self, task: Task, phase: Phase) -> list:
        """
        Build the starting message history for a task and phase.
        Contains the system prompt and the initial user instruction.
        """
        return [
            {
                "role": "system",
                "content": _build_system_prompt(phase, task),
            },
            {
                "role": "user",
                "content": (
                    f"Please begin. Task ID: {task.id}\n"
                    f"{task.description}"
                ),
            },
        ]

    def _splice_phase_prompt(
        self, messages: list, task: Task, new_phase: Phase
    ) -> list:
        """
        Replace the system prompt in an existing message history with one
        appropriate for the next phase. Preserves the full conversation
        history so the agent has context for what was done in prior phases.
        """
        new_system = {
            "role": "system",
            "content": _build_system_prompt(new_phase, task),
        }
        return [new_system] + messages[1:]

    def _request_human_intervention(
        self, task: Task, phase: Phase, result: LoopResult
    ) -> None:
        """
        Signal that a task needs human attention and cannot proceed.

        TODO: wire into comms.py to send a push notification and
        surface the blocked task in the web UI.
        """
        logger.warning(
            "HUMAN INTERVENTION NEEDED\n"
            "  Task:   %s (%s)\n"
            "  Phase:  %s\n"
            "  Reason: %s\n"
            "  Turns:  %d\n"
            "  Action: Add a task to .matrixmouse/tasks.json or interject via comms.",
            task.id, task.title, phase.name,
            result.exit_reason.name, result.turns_taken
        )
