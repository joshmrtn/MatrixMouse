"""
matrixmouse/config.py

Configuration loading for MatrixMouse using pydantic-settings.

Config is loaded from five sources in order of increasing priority:
    1. Field defaults defined in MatrixMouseConfig below
    2. Global config          — /etc/matrixmouse/config.toml
    3. Workspace config       — <workspace_root>/.matrixmouse/config.toml
    4. Repo-local, tracked    — <repo_root>/.matrixmouse/config.toml
    5. Repo-local, untracked  — <workspace_root>/.matrixmouse/<repo>/config.toml

Each source overwrites keys from the previous. Keys not present in a
source are inherited unchanged.

To add a new config field:
    1. Add it to MatrixMouseConfig with a type, default, and description.
    2. That's it. generate_starter_config() is derived automatically.

Do not add runtime state or argument parsing here — config loading only.
"""

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from pydantic import Field
from pydantic_settings import BaseSettings


class MatrixMouseConfig(BaseSettings):
    """
    All configuration fields for a MatrixMouse session.

    Each field has a default, a type, and a description. The description
    is used to generate the starter config file, so write it as a
    human-readable comment for the end user.
    """

    # --- Agent git identity ---
    agent_git_name: str = Field(
        default="MatrixMouse Bot",
        description="Name used for git commits made by the agent.",
    )
    agent_git_email: str = Field(
        default="matrixmouse-bot@users.noreply.github.com",
        description="Email used for git commits made by the agent.",
    )

    # --- Agent secret credential files ---
    gh_ssh_key_file: str = Field(
        default="agent_ed25519",
        description="Filename of the agent's SSH key within /etc/matrixmouse/secrets/.",
    )
    gh_token_file: str = Field(
        default="github_token",
        description="Filename of the agent's GitHub token (PAT) within /etc/matrixmouse/secrets/.",
    )

    # --- Models ---
    local_only: bool = Field(
        default=True,
        description="Prevent non-local LLM inference if True, allows if False."
    )
    coder_model: str = Field(
        default="http://localhost:11434:ollama:qwen3.5:2b",
        description="Model for code generation and implementation tasks.",
    )
    writer_model: str = Field(
        default="http://localhost:11434:ollama:qwen3.5:2b",
        description="Model for prose generation tasks. (Not for source code).",
    )
    manager_model: str = Field(
        default="http://localhost:11434:ollama:qwen3.5:2b",
        description="Model for planning, design, and architectural decisions.",
    )
    critic_model: str = Field(
        default="http://localhost:11434:ollama:qwen3.5:2b",
        description="Model for critique, review, and stuck detection.",
    )
    summarizer_model: str = Field(
        default="http://localhost:11434:ollama:qwen3.5:2b",
        description="Model for context summarisation. Should be small and fast.",
    )
    agent_max_turns: int = Field(
        default=50,
        description=(
            "Maximum turns an agent may take on a single task before the "
            "task is moved to BLOCKED_BY_HUMAN. The operator can extend, "
            "respec, or cancel via the turn-limit response endpoint."
        ),
    )

    # --- Coder cascade ---
    coder_cascade: list[str] = Field(
        default=["http://localhost:11434:ollama:qwen3.5:4b", "http://localhost:11434:ollama:qwen3.5:9b", "http://localhost:11434:ollama:qwen3.5:27b"],
        description=(
            "Ordered list of models for the coder cascade, smallest to largest. "
            "If only one entry, no escalation occurs. "
            "Example: ['http://localhost:11434:ollama:qwen2.5-coder:7b', 'http://localhost:11434:ollama:qwen2.5-coder:14b', 'http://localhost:11434:ollama:qwen2.5-coder:30b']"
        ),
    )

    # --- Thinking and Streaming toggles ---
    coder_think: bool = Field(
        default=False,
        description="Enable extended thinking for the coder model. Increases quality but uses more context.",
    )
    writer_think: bool = Field(
        default=False,
        description="Enable extended thinking for the writer model. Increases quality but uses more context.",
    )
    manager_think: bool = Field(
        default=False,
        description="Enable extended thinking for the manager model.",
    )
    critic_think: bool = Field(
        default=False,
        description="Enable extended thinking for the critic model.",
    )
    summarizer_think: bool = Field(
        default=False,
        description="Enable extended thinking for the summarizer model.",
    )
    coder_stream: bool = Field(
        default=False,
        description="Stream coder model output token by token. Disable if the model misbehaves with streaming.",
    )
    writer_stream: bool = Field(
        default=False,
        description="Stream writer model output token by token. Disable if the model misbehaves with streaming.",
    )
    manager_stream: bool = Field(
        default=False,
        description="Stream manager model output token by token.",
    )
    critic_stream: bool = Field(
        default=False,
        description="Stream critic model output token by token.",
    )
    summarizer_stream: bool = Field(
        default=False,
        description="Stream summarizer model output token by token. Usually False — summaries don't need live display.",
    )

    # --- Logging ---
    log_level: str = Field(
        default="INFO",
        description="Logging level. One of: DEBUG, INFO, WARNING, ERROR.",
    )
    log_to_file: bool = Field(
        default=False,
        description=(
            "Write logs to <workspace>/.matrixmouse/<repo>/agent.log. "
            "Useful for post-mortem debugging."
        ),
    )

    # --- Agent behaviour ---
    context_soft_limit: int = Field(
        default=32000,
        description="Token limit before context compression is triggered.",
    )
    compress_threshold: float = Field(
        default=0.60,
        description=(
            "Fraction of context_soft_limit at which compression triggers (0.0-1.0)."
        ),
    )
    stuck_turn_window: int = Field(
        default=6,
        description="Number of recent turns to inspect when checking for stuck behaviour.",
    )
    keep_last_n_turns: int = Field(
        default=6,
        description="Number of recent turns to preserve during context compression.",
    )

    # --- Repo init behaviour ---
    # Both default to False: MatrixMouse writes nothing to your repo
    # without explicit opt-in. Enable per-repo via:
    #   matrixmouse config set create_design_docs true --repo <name>
    create_design_docs: bool = Field(
        default=False,
        description=(
            "Create docs/design/ in the repo on init, including template.md. "
            "Enables the design document tools for the agent. "
            "Off by default — MatrixMouse never writes to your repo without opt-in."
        ),
    )
    create_adr_docs: bool = Field(
        default=False,
        description=(
            "Create docs/adr/ in the repo on init, including template.md. "
            "Enables the ADR tools for the agent. "
            "Off by default — MatrixMouse never writes to your repo without opt-in."
        ),
    )

    # --- Comms ---
    ntfy_url: str = Field(
        default="",
        description="ntfy server URL, e.g. https://ntfy.sh",
    )
    ntfy_topic: str = Field(
        default="matrixmouse",
        description="ntfy topic name.",
    )
    web_ui_url: str = Field(
        default="",
        description="Public URL of the MatrixMouse web UI, e.g. https://mm.example.com. Used to add a link to ntfy notifications.",
    )
    clarification_grace_period_minutes: int = Field(
        default=10,
        description="Number of minutes to wait after a request_clarification for human input. After this time elapses, the scheduler moves on to another task.",
    )
    clarification_timeout_minutes: int = Field(
        default=60,
        description="Minutes to wait before creating a stale clarification task for the Manager, so it can attempt to answer the question."
    )

    # --- Server ---
    server_port: int = Field(
        default=8080,
        description="Port for the web UI and HTTP API.",
    )

    # --- Priority scheduling ---
    priority_aging_rate: float = Field(
        default=0.01,
        description="Daily priority increase for incomplete tasks. Prevents starvation.",
    )
    priority_max_aging_bonus: float = Field(
        default=0.3,
        description="Maximum priority bonus from aging (caps at this value).",
    )
    
    # --- Priority weights ---
    priority_importance_weight: float = Field(
        default=0.6,
        description="Weight applied to importance when calculating priority score (0.0-1.0).",
    )
    priority_urgency_weight: float = Field(
        default=0.4,
        description="Weight applied to urgency when calculating priority score (0.0-1.0). importance_weight + urgency_weight should sum to 1.0.",
    )

    # --- Scheduler ---
    scheduler_p1_threshold: float = Field(
        default=0.35,
        description="Priority score below which a task enters the P1 (highest) queue.",
    )
    scheduler_p2_threshold: float = Field(
        default=0.65,
        description="Priority score below which a task enters the P2 queue. Scores at or above this enter P3.",
    )
    scheduler_p1_slice_minutes: float = Field(
        default=120.0,
        description="Time slice in minutes for P1 tasks.",
    )
    scheduler_p2_slice_minutes: float = Field(
        default=90.0,
        description="Time slice in minutes for P2 tasks.",
    )
    scheduler_p3_slice_minutes: float = Field(
        default=60.0,
        description="Time slice in minutes for P3 tasks.",
    )
    scheduler_adaptive: bool = Field(
        default=False,
        description="Enable adaptive time slice adjustment based on observed context switch overhead.",
    )
    scheduler_adaptive_step_minutes: float = Field(
        default=10.0,
        description="Step size in minutes for adaptive slice adjustments.",
    )
    scheduler_adaptive_min_pct: float = Field(
        default=0.05,
        description="If switch overhead is below this fraction of the slice, decrease the slice.",
    )
    scheduler_adaptive_max_pct: float = Field(
        default=0.15,
        description="If switch overhead exceeds this fraction of the slice, increase the slice.",
    )
    scheduler_adaptive_min_slice_minutes: float = Field(
        default=30.0,
        description="Floor for adaptive slice adjustment. Slices will never be reduced below this.",
    )

    # --- Manager review schedule ---
    manager_review_schedule: str = Field(
        default="0 9 * * *",
        description="Cron expression for the Manager's daily review task. Default: 9am daily.",
    )
    manager_review_upcoming_tasks: int = Field(
        default=20,
        description="Maximum number of upcoming tasks the Manager will review during daily review. Default 20."
    )

    # --- Decomposition ---
    decomposition_depth_limit: int = Field(
        default=3,
        description="Maximum task decomposition depth before human confirmation is required.",
    )

    # --- Critic ---
    critic_max_turns: int = Field(
        default=5,
        description="Maximum turns the Critic agent takes before escalating to human review.",
    )

    # --- Branch management ---
    agent_branch_prefix: str = Field(
        default="mm",
        description=(
            "Prefix for all MatrixMouse-owned git branches. "
            "All agent-created branches will be named <prefix>/<slug>. "
            "Change this if 'mm/' conflicts with your existing branch conventions. "
            "Common alternatives: 'bot', 'agent', 'matrixmouse'."
        ),
    )
    default_merge_target: str = Field(
        default="",
        description=(
            "Default branch to merge completed top-level tasks into when "
            "they have no parent task. Empty string means no automatic merge — "
            "the operator is prompted via modal to specify a target or create a PR."
        ),
    )
    protected_branches: list[str] = Field(
        default=["main", "master", "develop", "release"],
        description=(
            "Branch names that MatrixMouse will never merge into directly. "
            "When a task's parent branch matches one of these, a PR is created "
            "instead of a direct merge, and human approval is required. "
            "Add any branches you want to protect (e.g. 'staging', 'production')."
        ),
    )
    merge_conflict_max_turns: int = Field(
        default=5,
        description=(
            "Maximum turns an agent may take to resolve a merge conflict "
            "before the task is escalated to BLOCKED_BY_HUMAN."
        ),
    )
    merge_resolution_model: str = Field(
        default="",
        description=(
            "Model to use for merge conflict resolution. "
            "Empty string means use the last (largest) model in coder_cascade. "
            "Override to pin a specific model: e.g. 'qwen2.5-coder:32b'."
        ),
    )
    push_wip_to_remote: bool = Field(
        default=False,
        description=(
            "Push WIP commits to the configured remote origin after every "
            "inference call. Disabled by default to avoid noise on remote. "
            "Local mirror push always happens regardless of this setting."
        ),
    )
    branch_protection_cache_ttl_minutes: int = Field(
        default=60,
        description="Minutes to cache branch protection results from the remote API.",
    )
    pr_poll_interval_minutes: int = Field(
        default=10,
        description=(
            "How often to poll the remote provider for PR state changes "
            "(merged, closed, etc.)."
        ),
    )
    manager_planning_max_turns: int = Field(
        default=10,
        description=(
            "Maximum turns a Manager may spend in PLANNING session mode "
            "(decomposing tasks and wiring dependencies) before the planned "
            "graph is committed as-is and the Manager is blocked for human review."
        ),
    )

    # --- Start Paused (e.g., after an E-STOP) --- 
    start_paused: bool = Field(
        default=False,
        description=(
            "Start the orchestrator in a paused state. "
            "Tasks will not be picked up until manually resumed via CLI or web UI. "
            "Useful after an E-STOP reset to inspect state before resuming."
        ),
    )

    model_config = {"extra": "ignore"}  # silently ignore unknown keys from TOML


# Global config path — owned by the matrixmouse service user.
# Written by install.sh. Never under a user's home directory.
GLOBAL_CONFIG_PATH = Path("/etc/matrixmouse/config.toml")


def load_config(
    repo_root: Optional[Path],
    workspace_root: Optional[Path] = None,
) -> MatrixMouseConfig:
    """
    Load and merge configuration from all sources in order of
    increasing priority:
        1. Field defaults
        2. /etc/matrixmouse/config.toml                         global
        3. <workspace>/.matrixmouse/config.toml                 workspace-wide
        4. <repo_root>/.matrixmouse/config.toml                 repo-local, tracked
        5. <workspace>/.matrixmouse/<repo_name>/config.toml     repo-local, untracked

    repo_root may be None at service startup (workspace-level context).
    Layers 4 and 5 are both skipped in that case.

    Args:
        repo_root:       Root directory of the repo, or None.
        workspace_root:  Root of the MatrixMouse workspace. Falls back to
                         the WORKSPACE_PATH environment variable if None.

    Returns:
        A fully merged and validated MatrixMouseConfig instance.
    """
    import os

    merged: dict[str, Any] = {}

    if workspace_root is None:
        # Fall back to WORKSPACE_PATH env var - set in systemd unit file
        # or overriden via `Environment=` for non-default workspace locations.
        env_workspace = os.environ.get("WORKSPACE_PATH")
        if env_workspace:
            workspace_root = Path(env_workspace)
        else:
            # Default - matches install.sh
            workspace_root = Path("/var/lib/matrixmouse-workspace")

    # Layer 1 defaults are provided by MatrixMouseConfig field defaults.
    # Layers 2-5 are loaded in order, each overwriting the previous.
    config_paths: list[Path] = [GLOBAL_CONFIG_PATH]  # layer 2

    if workspace_root is not None:
        # Layer 3 — workspace-wide
        config_paths.append(workspace_root / ".matrixmouse" / "config.toml")

    if repo_root is not None:
        # Layer 4 — repo-local, tracked (inside the git tree)
        config_paths.append(repo_root / ".matrixmouse" / "config.toml")


    if workspace_root is not None and repo_root is not None:
        # Layer 5 — repo-local, untracked (workspace state dir)
        repo_name = Path(repo_root).resolve().name
        config_paths.append(
            workspace_root / ".matrixmouse" / repo_name / "config.toml"
        )

    for config_path in config_paths:
        if config_path.exists():
            with open(config_path, "rb") as f:
                layer = tomllib.load(f)
                merged.update(layer)

    return MatrixMouseConfig(**merged)


# Module-level reference set by _service.py after startup.
# Other modules (e.g. git_tools) that need config outside the call stack
# can read this rather than re-loading from disk.
_loaded_config: Optional[MatrixMouseConfig] = None


def generate_starter_config() -> str:
    """
    Generate the contents of a starter config.toml from MatrixMouseConfig
    field metadata. All fields are commented out so the file documents
    available options without overriding any defaults.

    Returns:
        A TOML-formatted string ready to write to disk.
    """
    lines = [
        "# MatrixMouse repo-local configuration",
        "# Values set here override /etc/matrixmouse/config.toml and",
        "# <workspace>/.matrixmouse/config.toml for this repo only.",
        "# Remove the leading '#' from a line to activate that setting.",
        "",
    ]

    for name, field_info in MatrixMouseConfig.model_fields.items():
        if field_info.description:
            lines.append(f"# {field_info.description}")

        default = field_info.default
        if isinstance(default, bool):
            lines.append(f"# {name} = {str(default).lower()}")
        elif isinstance(default, str):
            lines.append(f'# {name} = "{default}"')
        else:
            lines.append(f"# {name} = {default}")

        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Path dataclasses
# ---------------------------------------------------------------------------

@dataclass
class MatrixMousePaths:
    """
    Workspace-scoped paths. Constructed once at service startup.

    This is the top-level paths object. It does not represent any specific
    repo — repo-scoped paths are built on demand via repo_paths(repo_name)
    when a task begins execution.

    Layout:

        <workspace_root>/
            .matrixmouse/
                config.toml                 workspace-level config overrides
                tasks.json                  task queue (all repos)
                repos.json                  registered repos
                agent.pid                   PID lockfile
                testrunner.image.sha256     upgrade hash
                ignore                      workspace-wide safety blacklist
                AGENT_NOTES.md              workspace-level agent notes
                                            (used by future workspace-scoped tasks
                                            e.g. Project Manager agent)
                matrixmouse.db              SQLite database - tasks, dependencies, 
                                            workspace state, stale clarification registry
                <repo_name>/                per-repo runtime state (not in git)
                    AGENT_NOTES.md          repo-scoped agent working memory
                    agent.log               repo-scoped session log
                    ignore                  repo-local safety blacklist (untracked)
                    config.toml             repo-local config overrides (untracked)

        <repo_root>/                        the git repo — minimal footprint
            .matrixmouse/                   only exists if user opted in
                config.toml                 repo-level config overrides (tracked)
                ignore                      team-shared safety blacklist (tracked)
            docs/
                design/                     only if create_design_docs=true
                adr/                        only if create_adr_docs=true
    """
    workspace_root: Path

    @property
    def mm_dir(self) -> Path:
        """<workspace_root>/.matrixmouse/"""
        return self.workspace_root / ".matrixmouse"

    @property
    def repos_file(self) -> Path:
        """<workspace_root>/.matrixmouse/repos.json"""
        return self.mm_dir / "repos.json"

    @property
    def pid_file(self) -> Path:
        """<workspace_root>/.matrixmouse/agent.pid"""
        return self.mm_dir / "agent.pid"

    @property
    def testrunner_hash_file(self) -> Path:
        """<workspace_root>/.matrixmouse/testrunner.image.sha256"""
        return self.mm_dir / "testrunner.image.sha256"

    @property
    def workspace_ignore(self) -> Path:
        """<workspace_root>/.matrixmouse/ignore — workspace-wide safety blacklist"""
        return self.mm_dir / "ignore"
    
    @property
    def db_file(self) -> Path:
        """<workspace_root>/.matrixmouse/matrixmouse.db — SQLite database"""
        return self.mm_dir / "matrixmouse.db"

    @property
    def agent_notes(self) -> Path:
        """
        Workspace-level agent notes.
        Used by workspace-scoped tasks (e.g. Project Manager agent).
        For repo-scoped notes, use repo_paths(repo_name).agent_notes.
        """
        return self.mm_dir / "AGENT_NOTES.md"
    
    @property
    def mirrors_dir(self) -> Path:
        """
        /var/lib/matrixmouse-mirrors/
        Base directory for all local repo mirrors.
        Created by install.sh and owned by the matrixmouse user.
        """
        return Path("/var/lib/matrixmouse-mirrors")

    def mirror_path(self, repo_name: str) -> Path:
        """
        /var/lib/matrixmouse-mirrors/<repo_name>.git
        Bare git mirror for the named repo.
        """
        return self.mirrors_dir / f"{repo_name}.git"

    def repo_paths(self, repo_name: str) -> "RepoPaths":
        """
        Build a RepoPaths for the named repo.

        Called by the orchestrator at task execution time, once the task's
        target repo is known. repo_name must match the directory name under
        workspace_root (i.e. the name registered in repos.json).

        Args:
            repo_name: Directory name of the repo under workspace_root.

        Returns:
            RepoPaths with all repo-scoped paths resolved.
        """
        repo_root = self.workspace_root / repo_name
        state_dir = self.mm_dir / repo_name
        return RepoPaths(
            workspace_root=self.workspace_root,
            repo_root=repo_root,
            repo_name=repo_name,
            state_dir=state_dir,
            agent_notes=state_dir / "AGENT_NOTES.md",
            log_file=state_dir / "agent.log",
            config_dir=repo_root / ".matrixmouse",
            design_docs=repo_root / "docs" / "design",
        )


@dataclass
class RepoPaths:
    """
    Repo-scoped paths for a single task execution.

    Built on demand by MatrixMousePaths.repo_paths(repo_name).
    Passed to AgentLoop, ContextManager, and init.setup_repo.

    Never constructed directly — always via MatrixMousePaths.repo_paths().
    """
    workspace_root: Path
    repo_root: Path
    repo_name: str
    state_dir: Path     # <workspace>/.matrixmouse/<repo_name>/
    agent_notes: Path   # <state_dir>/AGENT_NOTES.md
    log_file: Path      # <state_dir>/agent.log
    config_dir: Path    # <repo_root>/.matrixmouse/  (only if user opted in)
    design_docs: Path   # <repo_root>/docs/design/   (only if create_design_docs)

    @property
    def adr_docs(self) -> Path:
        """<repo_root>/docs/adr/"""
        return self.design_docs.parent / "adr"

    @property
    def repo_ignore(self) -> Path:
        """<repo_root>/.matrixmouse/ignore — team-shared, version controlled"""
        return self.config_dir / "ignore"

    @property
    def local_ignore(self) -> Path:
        """<state_dir>/ignore — machine-local, untracked"""
        return self.state_dir / "ignore"
