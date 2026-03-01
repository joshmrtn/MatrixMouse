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

import json
import logging
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Optional

from matrixmouse.config import MatrixMouseConfig, MatrixMousePaths
from matrixmouse.loop import AgentLoop, LoopExitReason, LoopResult
from matrixmouse.stuck import StuckDetector

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Phase state machine
# ---------------------------------------------------------------------------

class Phase(Enum):
    """
    SDLC phases a task moves through in order.
    The orchestrator enforces that no phase is skipped.
    """
    DESIGN      = auto()
    CRITIQUE    = auto()
    IMPLEMENT   = auto()
    TEST        = auto()
    REVIEW      = auto()
    DONE        = auto()


PHASE_SEQUENCE = [
    Phase.DESIGN,
    Phase.CRITIQUE,
    Phase.IMPLEMENT,
    Phase.TEST,
    Phase.REVIEW,
    Phase.DONE,
]


def next_phase(current: Phase) -> Optional[Phase]:
    """Return the phase that follows current, or None if already DONE."""
    idx = PHASE_SEQUENCE.index(current)
    if idx + 1 < len(PHASE_SEQUENCE):
        return PHASE_SEQUENCE[idx + 1]
    return None


# ---------------------------------------------------------------------------
# Task model
# ---------------------------------------------------------------------------

@dataclass
class Task:
    """
    A unit of work for the agent to complete.

    Designed to be source-agnostic — the orchestrator doesn't care whether
    a task was loaded from a local file or fetched from a GitHub issue.
    """
    id: str                         # unique identifier, e.g. "task-001" or "issue-42"
    title: str                      # short human-readable description
    description: str                # full task specification handed to the agent
    phase: Phase = Phase.DESIGN     # current phase in the SDLC state machine
    target_files: list = field(default_factory=list)   # files the agent should focus on
    notes: str = ""                 # any scoping notes added by the orchestrator
    source: str = "local"           # "local" | "github" | "gitea"


# ---------------------------------------------------------------------------
# Task queue abstraction
# ---------------------------------------------------------------------------

class TaskQueue:
    """
    Abstraction over task sources. Currently backed by a local JSON file.

    The queue file lives at .matrixmouse/tasks.json and contains a list
    of task objects. Completed tasks are marked done in the file rather
    than deleted so there is a record of what was worked on.

    To add GitHub/Gitea support later: subclass or replace this with an
    implementation that fetches from the API. The orchestrator only calls
    get_next() and mark_complete(), so the source is fully swappable.

    Queue file format:
        [
          {
            "id": "task-001",
            "title": "Add input validation to parse_config",
            "description": "The parse_config function ...",
            "target_files": ["src/matrixmouse/config.py"],
            "done": false
          },
          ...
        ]
    """

    def __init__(self, queue_path: Path):
        self.queue_path = queue_path
        self._tasks: list[dict] = []
        self._load()

    def _load(self) -> None:
        """Load tasks from the queue file. Creates an empty queue if missing."""
        if not self.queue_path.exists():
            logger.info("No task queue found at %s. Starting with empty queue.", self.queue_path)
            self._tasks = []
            return
        with open(self.queue_path) as f:
            self._tasks = json.load(f)
        logger.info("Loaded %d tasks from %s", len(self._tasks), self.queue_path)

    def _save(self) -> None:
        """Persist current task list back to the queue file."""
        with open(self.queue_path, "w") as f:
            json.dump(self._tasks, f, indent=2)

    def get_next(self) -> Optional[Task]:
        """
        Return the next incomplete task, or None if the queue is empty.
        Tasks are returned in file order (top of file = highest priority).
        """
        for raw in self._tasks:
            if not raw.get("done", False):
                return Task(
                    id=raw["id"],
                    title=raw["title"],
                    description=raw["description"],
                    target_files=raw.get("target_files", []),
                    source="local",
                )
        return None

    def mark_complete(self, task_id: str) -> None:
        """Mark a task as done in the queue file."""
        for raw in self._tasks:
            if raw["id"] == task_id:
                raw["done"] = True
                break
        self._save()
        logger.info("Task %s marked complete.", task_id)

    def is_empty(self) -> bool:
        """Return True if there are no incomplete tasks remaining."""
        return all(t.get("done", False) for t in self._tasks)

    def add_task(self, task: Task) -> None:
        """
        Append a new task to the queue file.
        Useful for programmatic task creation and future GitHub integration.
        """
        self._tasks.append({
            "id": task.id,
            "title": task.title,
            "description": task.description,
            "target_files": task.target_files,
            "done": False,
        })
        self._save()
        logger.info("Task %s added to queue.", task.id)


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
        graph=None,             # ProjectAnalyzer instance, optional until graph.py is implemented
    ):
        self.config = config
        self.paths = paths
        self.graph = graph

        queue_path = paths.config_dir / "tasks.json"
        self.queue = TaskQueue(queue_path)

        # TODO: wire in router.py for model selection per phase/role
        # For now, all phases use the configured coder model
        self._model = config.coder

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

        while current_phase != Phase.DONE:
            logger.info("Task %s entering phase: %s", task.id, current_phase.name)

            result = self._run_phase(task, current_phase, messages)

            if result.exit_reason == LoopExitReason.COMPLETE:
                logger.info(
                    "Task %s phase %s complete. Summary: %s",
                    task.id, current_phase.name, result.completion_summary
                )
                advanced = next_phase(current_phase)
                if advanced is None or advanced == Phase.DONE:
                    self.queue.mark_complete(task.id)
                    logger.info("Task %s fully complete.", task.id)
                    return

                current_phase = advanced
                # Carry message history forward into the next phase with
                # an updated system prompt.
                messages = self._splice_phase_prompt(result.messages, task, current_phase)

            elif result.exit_reason == LoopExitReason.ESCALATE:
                # TODO: wire into router.py to try a larger model
                # For now, route to human and pause
                logger.warning(
                    "Task %s escalated during phase %s. Awaiting human input.",
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

    def _run_phase(self, task: Task, phase: Phase, messages: list) -> LoopResult:
        """
        Instantiate and run an AgentLoop for a single phase of a task.
        Returns the LoopResult for the orchestrator to act on.
        """
        detector = StuckDetector(phase=phase)
        context_manager = ContextManager(
            config=self.config,
            paths=self.paths,
            coder_model=self._model,
        )
        loop = AgentLoop(
            model=self._model,
            messages=messages,
            config=self.config,
            paths=self.paths,
            context_manager=context_manager,
            stuck_detector=detector,
        )
        result = loop.run()

        # Attach diagnostic summary for router.py to use later
        if result.exit_reason == LoopExitReason.ESCALATE:
            logger.warning("Stuck summary: %s", detector.summary)

        return result


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
        # Replace first message (system prompt) and keep everything else
        return [new_system] + messages[1:]

    def _request_human_intervention(
        self, task: Task, phase: Phase, result: LoopResult
    ) -> None:
        """
        Signal that a task needs human attention and cannot proceed.
        Logs the situation clearly.

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
