"""
matrixmouse/task.py

Core task data model for MatrixMouse.

Contains:
    - AgentRole   — which agent type handles a task
    - TaskStatus  — lifecycle states (READY → RUNNING → COMPLETE etc.)
    - Task        — the unit of work

Task was previously in orchestrator.py. Extracted here so
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


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# AgentRole
# ---------------------------------------------------------------------------

class AgentRole(str, Enum):
    """Enumeration of roles an agent can take on for a task."""
    MANAGER = "manager"
    CODER   = "coder"
    WRITER  = "writer"
    CRITIC  = "critic"
    MERGE   = "merge"


# ---------------------------------------------------------------------------
# PRState
# ---------------------------------------------------------------------------

class PRState(str, Enum):
    """Enumeration of pull request states."""
    NONE   = ""        # no PR exists
    OPEN   = "open"    # PR created, awaiting review
    MERGED = "merged"  # PR merged, task can complete
    CLOSED = "closed"  # PR rejected, needs rework


# ---------------------------------------------------------------------------
# TaskStatus
# ---------------------------------------------------------------------------

class TaskStatus(Enum):
    """Enumeration of task lifecycle statuses."""
    PENDING          = "pending"
    READY            = "ready"
    RUNNING          = "running"
    BLOCKED_BY_TASK  = "blocked_by_task"
    BLOCKED_BY_HUMAN = "blocked_by_human"
    WAITING          = "waiting"          # paused until wait_until; resumes automatically
    COMPLETE         = "complete"
    CANCELLED        = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in (TaskStatus.COMPLETE, TaskStatus.CANCELLED)

    @property
    def is_blocked(self) -> bool:
        """True for statuses that require external intervention to clear."""
        return self in (TaskStatus.BLOCKED_BY_TASK, TaskStatus.BLOCKED_BY_HUMAN)

    @property
    def is_waiting(self) -> bool:
        """True for statuses that clear automatically after a time condition."""
        return self == TaskStatus.WAITING


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
        turn_limit                  — Per-task turn limit override. 0 means use
                                      config.agent_max_turns.
        preempt                     — transient flag set by orchestrator to preempt
                                      the currently running task
        wip_commit_hash             — hash of last real (non-WIP) commit at task
                                      start; used as baseline for git diff tooling
        reviews_task_id             — for CRITIC tasks: points at task under review
        last_review_summary         — for MANAGER review tasks: summary from the
                                      previous review cycle, used as front-loaded
                                      context when the next review task is created
        context_messages            — full conversation history; persisted after
                                      every inference call (not just phase transitions)
        last_modified               — ISO timestamp updated on every queue.update()
                                      call. Tracks task throughput and used for
                                      stale clarification detection. Falls back
                                      to created_at on load if absent.
        pending_question            — clarification question currently awaiting
                                      human response. Set by request_clarification(),
                                      cleared when answered. Empty string means
                                      no pending question.
        pr_url                      — GitHub/GitLab/Gitea PR URL once created.
                                      Empty string means no PR exists.
        pr_state                    — current state of the PR. See PRState enum.
        pr_poll_next_at             — ISO timestamp of next scheduled PR state
                                      poll. Empty string means no poll pending.
        wait_until                  — ISO timestamp; when WAITING, the earliest
                                      datetime at which the orchestrator may
                                      promote this task back to READY. None means
                                      no time gate (promote immediately on next
                                      poll if other conditions are met).
        wait_reason                 — machine-readable tag describing why the task
                                      is WAITING. Convention: "category:detail",
                                      e.g. "budget:anthropic", "budget:openai",
                                      "rate_limit:anthropic". Empty string when
                                      not WAITING.

    Removed vs the previous model:
        phase                       — replaced by role
        source                      — unused in practice
        blocking, blocked_by        — moved to task_dependencies table
                                      in the repository layer; query via
                                      repository.get_blocked_by() /
                                      repository.get_blocking()
        subtasks                    — made redundant by new
                                      repository.get_subtasks()

    Identity note: task_id is a 16-character hex string (16^16 possible values).
    Global uniqueness is enforced at creation time by TaskRepository.add(). For
    terminated tasks, the natural unique identifier is the composite of
    (id, created_at, completed_at)
    TODO: Implement archival strategy and retention policy for terminated tasks
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
    branch: str = field(default="")

    # --- Task tree ---
    parent_task_id: Optional[str] = None
    depth: int = 0
    decomposition_confirmed_depth: int = 0

    # --- Scheduling ---
    status: TaskStatus = TaskStatus.READY
    importance: float = 0.5
    urgency: float = 0.5
    time_slice_started: Optional[float] = None
    turn_limit: int = field(default=0)
    preempt: bool = field(default=False)
    preemptable: bool = field(default=True)

    # --- Waiting (time-gated pause, resumes automatically) ---
    wait_until: Optional[str] = field(default=None)   # ISO timestamp or None
    wait_reason: str = field(default="")              # e.g. "budget:anthropic"

    # --- Git ---
    wip_commit_hash: str = field(default="")
    merge_resolution_decisions: list[dict] = field(default_factory=list)

    # --- Pending tool calls (decision replay) ---
    pending_tool_calls: list[dict] = field(default_factory=list)

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
    last_modified: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    pending_question: str = field(default="")  # request_clarification questions land here

    # --- PR tracking ---
    pr_url:          str     = field(default="")
    pr_state:        PRState = field(default=PRState.NONE)
    pr_poll_next_at: str     = field(default="")  # ISO timestamp, "" = no poll pending

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
        """Compute a priority score for this task.

        Lower return value == higher priority (0.0 = most urgent).

        Base score is a weighted combination of importance and urgency,
        both in [0, 1] where 1.0 means most important/urgent. The base
        is therefore in [0, 1] with 1.0 = highest priority intent.

        We invert to get a score where 0.0 = highest priority, then subtract
        an aging bonus (so older tasks drift toward 0 over time, preventing
        starvation).

        Args:
            aging_rate: Daily priority increase for incomplete tasks.
            max_aging_bonus: Maximum priority bonus from aging.
            importance_weight: Weight for importance in [0, 1].
            urgency_weight: Weight for urgency in [0, 1].

        Returns:
            The calculated priority score clamped to [0.0, 1.0].
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
    # Serialisation
    # -----------------------------------------------------------------------

    def to_dict(self) -> dict:
        """Serialise the task to a dictionary for storage or API delivery.

        Returns:
            Dictionary containing all task fields.
        """
        return {
            "id":                           self.id,
            "title":                        self.title,
            "description":                  self.description,
            "role":                         self.role.value,
            "repo":                         self.repo,
            "branch":                       self.branch,
            "parent_task_id":               self.parent_task_id,
            "depth":                        self.depth,
            "decomposition_confirmed_depth": self.decomposition_confirmed_depth,
            "status":                       self.status.value,
            "importance":                   self.importance,
            "urgency":                      self.urgency,
            "time_slice_started":           self.time_slice_started,
            "turn_limit":                   self.turn_limit,
            "preempt":                      self.preempt,
            "preemptable":                  self.preemptable,
            "wait_until":                   self.wait_until,
            "wait_reason":                  self.wait_reason,
            "wip_commit_hash":              self.wip_commit_hash,
            "merge_resolution_decisions":   self.merge_resolution_decisions,
            "pending_tool_calls":           self.pending_tool_calls,
            "reviews_task_id":              self.reviews_task_id,
            "last_review_summary":          self.last_review_summary,
            "context_messages":             self.context_messages,
            "target_files":                 self.target_files,
            "notes":                        self.notes,
            "created_at":                   self.created_at,
            "started_at":                   self.started_at,
            "completed_at":                 self.completed_at,
            "last_modified":                self.last_modified,
            "pending_question":             self.pending_question,
            "pr_url":                       self.pr_url,
            "pr_state":                     self.pr_state.value,
            "pr_poll_next_at":              self.pr_poll_next_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Task":
        """Reconstruct a task from a dictionary.

        Args:
            data: Dictionary of task fields (e.g. from JSON or SQLite).

        Returns:
            A new Task instance.
        """
        # --- role ---
        role_str = data.get("role", "coder")
        try:
            role = AgentRole(role_str)
        except ValueError:
            logger.warning("Unknown role %r — defaulting to CODER.", role_str)
            role = AgentRole.CODER

        # --- status ---
        status_str = data.get("status", "ready")
        try:
            status = TaskStatus(status_str)
        except ValueError:
            logger.warning(
                "Unknown status %r — defaulting to PENDING.", status_str
            )
            status = TaskStatus.PENDING

        return cls(
            id=data.get("id", str(uuid.uuid4().hex[:16])),
            title=data.get("title", ""),
            description=data.get("description", ""),
            role=role,
            repo=data.get("repo", []),
            branch=data.get("branch", ""),
            parent_task_id=data.get("parent_task_id"),
            depth=data.get("depth", 0),
            decomposition_confirmed_depth=data.get(
                "decomposition_confirmed_depth", 0
            ),
            status=status,
            importance=data.get("importance", 0.5),
            urgency=data.get("urgency", 0.5),
            time_slice_started=data.get("time_slice_started"),
            turn_limit=data.get("turn_limit", 0),
            preempt=data.get("preempt") or False,
            preemptable=data.get("preemptable", True),
            wait_until=data.get("wait_until"),
            wait_reason=data.get("wait_reason", ""),
            wip_commit_hash=data.get("wip_commit_hash") or "",
            merge_resolution_decisions=data.get("merge_resolution_decisions", []),
            pending_tool_calls=data.get("pending_tool_calls", []),
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
            last_modified=data.get(
                "last_modified",
                data.get("created_at", datetime.now(timezone.utc).isoformat())
            ),
            pending_question=data.get("pending_question", ""),
            pr_url=data.get("pr_url", ""),
            pr_state=PRState(data.get("pr_state", "")),
            pr_poll_next_at=data.get("pr_poll_next_at", ""),
        )
