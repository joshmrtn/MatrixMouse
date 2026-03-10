"""
matrixmouse/task.py

Core task data model for MatrixMouse.

Contains:
    - AgentRole   — which agent type handles a task
    - TaskStatus  — lifecycle states (READY → RUNNING → COMPLETE etc.)
    - Task        — the unit of work
    - TaskQueue   — workspace-level task queue backed by tasks.json

TaskQueue and Task were previously in orchestrator.py. Extracted here so
api.py, scheduling.py, task_tools.py, and orchestrator.py can all import
from a single location without circular dependencies.

Priority convention: LOWER score == HIGHER priority.
    0.0 = maximum urgency
    1.0 = lowest urgency
This matches the conventional "Priority 1 means do this first" mental model
and maps cleanly onto the P1/P2/P3 queue levels in scheduling.py.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

from matrixmouse.utils.file_lock import locked_json, LockTimeoutError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# AgentRole
# ---------------------------------------------------------------------------

class AgentRole(str, Enum):
    MANAGER = "manager"
    CODER   = "coder"
    WRITER  = "writer"
    CRITIC  = "critic"


# ---------------------------------------------------------------------------
# TaskStatus
# ---------------------------------------------------------------------------

class TaskStatus(Enum):
    READY            = "ready"
    RUNNING          = "running"
    BLOCKED_BY_TASK  = "blocked_by_task"
    BLOCKED_BY_HUMAN = "blocked_by_human"
    COMPLETE         = "complete"
    CANCELLED        = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in (TaskStatus.COMPLETE, TaskStatus.CANCELLED)

    @property
    def is_blocked(self) -> bool:
        return self in (TaskStatus.BLOCKED_BY_TASK, TaskStatus.BLOCKED_BY_HUMAN)


# ---------------------------------------------------------------------------
# Task
# ---------------------------------------------------------------------------

@dataclass
class Task:
    """
    A unit of work for the agent to complete.

    Priority convention: lower score == higher priority (0.0 = most urgent).

    repo is a list to support cross-repo tasks. Most tasks have one entry.
    Path safety is widened to all named repos when a task spans multiple.

    New fields vs the previous model:
        role                        — replaces phase; which agent handles this task
        branch                      — git branch assigned to this task
        parent_task_id              — enables task tree traversal
        depth                       — distance from root task (0 = top-level)
        decomposition_confirmed_depth
                                    — number of human confirmation events granted
                                      on this branch's decomposition depth
        time_slice_started          — Unix timestamp when status became RUNNING
        wip_commit_hash             — hash of last real (non-WIP) commit at task
                                      start; used as baseline for git diff tooling
        reviews_task_id             — for CRITIC tasks: points at task under review
        last_review_summary         — for MANAGER review tasks: summary from the
                                      previous review cycle, used as front-loaded
                                      context when the next review task is created
        context_messages            — full conversation history; persisted after
                                      every inference call (not just phase transitions)

    Removed vs the previous model:
        phase                       — replaced by role
        source                      — unused in practice

    Identity note: task_id is a 16-character hex string (16^16 possible values).  
    Global uniqueness is enforced at creation time by TaskQueue.add(). For 
    terminated tasks, the natural unique identifier is the composite of 
    (id, created_at, completed_at) - relevant if/when we migrate from JSON to 
    database persistence.
    """

    # --- Identity ---
    id: str = field(
            default_factory=lambda: uuid.uuid4().hex[:16]
    )
    title: str = ""
    description: str = ""

    # --- Assignment ---
    role: AgentRole = AgentRole.CODER
    repo: list[str] = field(default_factory=list)
    branch: str = ""

    # --- Task tree ---
    parent_task_id: Optional[str] = None
    subtasks: list[str] = field(default_factory=list)
    depth: int = 0
    decomposition_confirmed_depth: int = 0

    # --- Scheduling ---
    status: TaskStatus = TaskStatus.READY
    importance: float = 0.5
    urgency: float = 0.5
    time_slice_started: Optional[float] = None

    # --- Dependency graph ---
    blocked_by: list[str] = field(default_factory=list)
    blocking: list[str] = field(default_factory=list)

    # --- Git ---
    wip_commit_hash: Optional[str] = None

    # --- Critic / review ---
    reviews_task_id: Optional[str] = None
    last_review_summary: Optional[str] = None

    # --- Context ---
    context_messages: list = field(default_factory=list)
    target_files: list[str] = field(default_factory=list)
    notes: str = ""

    # --- Timestamps ---
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    started_at: Optional[str] = None
    completed_at: Optional[str] = None

    # -----------------------------------------------------------------------
    # Priority
    # -----------------------------------------------------------------------

    def priority_score(
        self,
        aging_rate: float = 0.01,
        max_aging_bonus: float = 0.3,
        importance_weight: float = 0.6,
        urgency_weight: float = 0.4,
    ) -> float:
        """
        Compute a priority score for this task.

        Lower return value == higher priority (0.0 = most urgent).

        Base score is a weighted combination of importance and urgency,
        both in [0, 1] where 1.0 means most important/urgent. The base
        is therefore in [0, 1] with 1.0 = highest priority intent.

        We invert to get a score where 0.0 = highest priority, then subtract
        an aging bonus (so older tasks drift toward 0 over time, preventing
        starvation).

        Clamped to [0.0, 1.0].
        """
        base = (self.importance * importance_weight) + (self.urgency * urgency_weight)
        # base is in [0, 1]; higher = more important/urgent

        try:
            created = datetime.fromisoformat(self.created_at)
            age_days = (datetime.now(timezone.utc) - created).days
            aging_bonus = min(age_days * aging_rate, max_aging_bonus)
        except (ValueError, TypeError):
            aging_bonus = 0.0

        # Invert: 1.0 - base gives 0.0 for the most important tasks.
        # Subtract aging bonus so older tasks drift toward 0 (higher priority).
        score = (1.0 - base) - aging_bonus
        return max(0.0, score)

    # -----------------------------------------------------------------------
    # Readiness
    # -----------------------------------------------------------------------

    def is_ready(self, completed_ids: set[str]) -> bool:
        """True if all blocking dependencies are complete."""
        return all(dep in completed_ids for dep in self.blocked_by)

    # -----------------------------------------------------------------------
    # Serialisation
    # -----------------------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "id":                           self.id,
            "title":                        self.title,
            "description":                  self.description,
            "role":                         self.role.value,
            "repo":                         self.repo,
            "branch":                       self.branch,
            "parent_task_id":               self.parent_task_id,
            "subtasks":                     self.subtasks,
            "depth":                        self.depth,
            "decomposition_confirmed_depth": self.decomposition_confirmed_depth,
            "status":                       self.status.value,
            "importance":                   self.importance,
            "urgency":                      self.urgency,
            "time_slice_started":           self.time_slice_started,
            "blocked_by":                   self.blocked_by,
            "blocking":                     self.blocking,
            "wip_commit_hash":              self.wip_commit_hash,
            "reviews_task_id":              self.reviews_task_id,
            "last_review_summary":          self.last_review_summary,
            "context_messages":             self.context_messages,
            "target_files":                 self.target_files,
            "notes":                        self.notes,
            "created_at":                   self.created_at,
            "started_at":                   self.started_at,
            "completed_at":                 self.completed_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Task":
        # --- role ---
        role_str = data.get("role", "coder")
        try:
            role = AgentRole(role_str)
        except ValueError:
            logger.warning("Unknown role %r — defaulting to CODER.", role_str)
            role = AgentRole.CODER

        # --- status ---
        # Migrate legacy values from the old model:
        #   "pending" and "active" had different semantics; both map to READY
        #   since no tasks should be mid-flight across a restart.
        status_str = data.get("status", "ready")
        _legacy_map = {"pending": "ready", "active": "ready"}
        status_str = _legacy_map.get(status_str, status_str)
        try:
            status = TaskStatus(status_str)
        except ValueError:
            logger.warning(
                "Unknown status %r — defaulting to READY.", status_str
            )
            status = TaskStatus.READY

        return cls(
            id=data.get("id", str(uuid.uuid4())),
            title=data.get("title", ""),
            description=data.get("description", ""),
            role=role,
            repo=data.get("repo", []),
            branch=data.get("branch", ""),
            parent_task_id=data.get("parent_task_id"),
            subtasks=data.get("subtasks", []),
            depth=data.get("depth", 0),
            decomposition_confirmed_depth=data.get(
                "decomposition_confirmed_depth", 0
            ),
            status=status,
            importance=data.get("importance", 0.5),
            urgency=data.get("urgency", 0.5),
            time_slice_started=data.get("time_slice_started"),
            blocked_by=data.get("blocked_by", []),
            blocking=data.get("blocking", []),
            wip_commit_hash=data.get("wip_commit_hash"),
            reviews_task_id=data.get("reviews_task_id"),
            last_review_summary=data.get("last_review_summary"),
            context_messages=data.get("context_messages", []),
            target_files=data.get("target_files", []),
            notes=data.get("notes", ""),
            created_at=data.get(
                "created_at", datetime.now(timezone.utc).isoformat()
            ),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
        )


# ---------------------------------------------------------------------------
# TaskQueue
# ---------------------------------------------------------------------------

class TaskQueue:
    """
    Workspace-level task queue backed by tasks.json.

    All writes go through the API server, which serialises access via the
    HTTP layer. locked_json is used here as a belt-and-suspenders measure
    for the orchestrator's own reads and writes.

    Tasks are stored in memory as a dict keyed by task id. Disk is the
    source of truth — reload() re-reads the file at the top of each
    scheduling cycle so tasks added via the API are picked up without
    a service restart.
    """

    def __init__(self, tasks_file: Path):
        self.tasks_file = tasks_file
        self._tasks: dict[str, Task] = {}
        self._load()

    # -----------------------------------------------------------------------
    # Persistence
    # -----------------------------------------------------------------------

    def _load(self) -> None:
        if not self.tasks_file.exists():
            logger.info("No task queue at %s. Starting empty.", self.tasks_file)
            return
        try:
            with locked_json(self.tasks_file) as (raw_list, _):
                for raw in raw_list:
                    task = Task.from_dict(raw)
                    self._tasks[task.id] = task
            logger.info("Loaded %d task(s).", len(self._tasks))
        except LockTimeoutError as e:
            logger.error("Failed to load tasks: %s", e)
            raise

    def _save(self) -> None:
        try:
            with locked_json(self.tasks_file) as (_, save):
                save([t.to_dict() for t in self._tasks.values()])
        except LockTimeoutError as e:
            logger.error("Failed to save tasks: %s", e)
            raise

    def reload(self) -> None:
        """
        Re-read tasks.json from disk.
        Called at the top of each scheduler cycle so tasks added via
        the API are picked up without a restart.
        """
        self._tasks.clear()
        self._load()

    # -----------------------------------------------------------------------
    # Queries
    # -----------------------------------------------------------------------

    def get(self, task_id: str) -> Optional[Task]:
        return self._tasks.get(task_id)

    def all_tasks(self) -> list[Task]:
        return list(self._tasks.values())

    def active_tasks(self) -> list[Task]:
        return [t for t in self._tasks.values() if not t.status.is_terminal]

    def completed_ids(self) -> set[str]:
        return {t.id for t in self._tasks.values() if t.status.is_terminal}

    def is_empty(self) -> bool:
        return len(self.active_tasks()) == 0

    # -----------------------------------------------------------------------
    # Mutations
    # -----------------------------------------------------------------------

    def add(self, task: Task) -> Task:
        # Regenerate id on collision — cheap check, expensive to fix later.
        # Collisions are astronomically unlikely with 16-char hex (16^16 values)
        # but we check explicitly rather than rely on probability.
        while task.id in self._tasks:
            logger.warning(
                "Task id collision on %r — regenerating. "
                "This should essentially never happen.",
                task.id,
            )
            task.id = uuid.uuid4().hex[:16]
        self._tasks[task.id] = task
        self._save()
        logger.info("Task added: [%s] %s", task.id, task.title)
        return task

    def update(self, task: Task) -> None:
        if task.id not in self._tasks:
            raise KeyError(f"Task {task.id!r} not found.")
        self._tasks[task.id] = task
        self._save()

    def mark_running(self, task_id: str) -> None:
        import time
        task = self._require(task_id)
        task.status = TaskStatus.RUNNING
        task.time_slice_started = time.monotonic()
        if task.started_at is None:
            task.started_at = datetime.now(timezone.utc).isoformat()
        self.update(task)

    def mark_ready(self, task_id: str) -> None:
        """Return a RUNNING task to READY (time slice expired)."""
        task = self._require(task_id)
        task.status = TaskStatus.READY
        task.time_slice_started = None
        self.update(task)

    def mark_complete(self, task_id: str) -> None:
        task = self._require(task_id)
        task.status = TaskStatus.COMPLETE
        task.time_slice_started = None
        task.completed_at = datetime.now(timezone.utc).isoformat()
        self.update(task)
        self._unblock_dependents(task_id)
        logger.info("Task %s complete.", task_id)

    def mark_blocked_by_human(self, task_id: str, reason: str = "") -> None:
        task = self._require(task_id)
        task.status = TaskStatus.BLOCKED_BY_HUMAN
        task.time_slice_started = None
        if reason:
            task.notes = (task.notes + f"\n[BLOCKED] {reason}").strip()
        self.update(task)
        logger.warning("Task %s blocked by human: %s", task_id, reason)

    def add_subtask(
        self,
        parent_id: str,
        title: str,
        description: str,
        role: AgentRole = AgentRole.CODER,
        repo: list[str] | None = None,
        target_files: list[str] | None = None,
        importance: float = 0.5,
        urgency: float = 0.5,
    ) -> Task:
        parent = self._require(parent_id)

        subtask = Task(
            title=title,
            description=description,
            role=role,
            repo=repo if repo is not None else list(parent.repo),
            target_files=target_files or [],
            blocked_by=[],
            blocking=[parent_id],
            parent_task_id=parent_id,
            depth=parent.depth + 1,
            importance=importance,
            urgency=urgency,
        )
        self.add(subtask)

        parent.subtasks.append(subtask.id)
        parent.blocked_by.append(subtask.id)
        parent.status = TaskStatus.BLOCKED_BY_TASK
        self.update(parent)

        cycle = self._find_cycle(subtask.id)
        if cycle:
            self._tasks.pop(subtask.id)
            parent.subtasks.remove(subtask.id)
            parent.blocked_by.remove(subtask.id)
            if not parent.blocked_by:
                parent.status = TaskStatus.READY
            self.update(parent)
            self._save()
            raise ValueError(
                f"Dependency cycle detected: {' → '.join(cycle)}. "
                f"Subtask was not created."
            )

        logger.info("Subtask [%s] created under [%s].", subtask.id, parent_id)
        return subtask

    # -----------------------------------------------------------------------
    # Cycle detection
    # -----------------------------------------------------------------------

    def detect_cycles(self) -> list[list[str]]:
        cycles = []
        visited: set[str] = set()
        for task_id in self._tasks:
            if task_id not in visited:
                cycle = self._find_cycle(task_id, visited)
                if cycle:
                    cycles.append(cycle)
        return cycles

    def _find_cycle(
        self,
        start_id: str,
        visited: set[str] | None = None,
        path: list[str] | None = None,
    ) -> list[str] | None:
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
                    return path[path.index(dep_id):] + [dep_id]
                if dep_id not in visited:
                    result = self._find_cycle(dep_id, visited, path)
                    if result:
                        return result
        path.pop()
        return None

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    def _require(self, task_id: str) -> Task:
        task = self._tasks.get(task_id)
        if task is None:
            raise KeyError(f"Task {task_id!r} not found.")
        return task

    def _unblock_dependents(self, completed_task_id: str) -> None:
        completed = self.completed_ids()
        for task in self._tasks.values():
            if (
                task.status == TaskStatus.BLOCKED_BY_TASK
                and completed_task_id in task.blocked_by
                and task.is_ready(completed)
            ):
                task.status = TaskStatus.READY
                self.update(task)
                logger.info(
                    "Task [%s] unblocked after [%s] completed.",
                    task.id, completed_task_id,
                )
