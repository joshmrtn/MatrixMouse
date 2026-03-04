"""
matrixmouse/config.py

Configuration loading for MatrixMouse using pydantic-settings.

Config is loaded from four sources in order of increasing priority:
    1. Field defaults defined in MatrixMouseConfig below
    2. Global config      — /etc/matrixmouse/config.toml
    3. Workspace config   — <workspace_root>/.matrixmouse/config.toml
    4. Repo-local config  — <repo_root>/.matrixmouse/config.toml

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

    # --- Models ---
    coder: str = Field(
        default="qwen3:4b",
        description="Model for code generation and implementation tasks.",
    )
    planner: str = Field(
        default="qwen3:4b",
        description="Model for planning, design, and architectural decisions.",
    )
    judge: str = Field(
        default="qwen3:4b",
        description="Model for critique, review, and stuck detection.",
    )
    summarizer: str = Field(
        default="qwen3:4b",
        description="Model for context summarisation. Should be small and fast.",
    )

    # --- Coder cascade ---
    coder_cascade: list[str] = Field(
        default=["qwen3:4b", "qwen3:8b", "qwen3:14b", "qwen3-coder:30b"],
        description=(
            "Ordered list of models for the coder cascade, smallest to largest. "
            "If only one entry, no escalation occurs. "
            "Example: ['qwen2.5-coder:7b', 'qwen2.5-coder:14b', 'qwen2.5-coder:30b']"
        ),
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
        4. <workspace>/.matrixmouse/<repo_name>/config.toml     repo-local, untracked
        5. <repo_root>/.matrixmouse/config.toml                 repo-local, tracked

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
        env_workspace = os.environ.get("WORKSPACE_PATH")
        if env_workspace:
            workspace_root = Path(env_workspace)

    # Layer 1 defaults are provided by MatrixMouseConfig field defaults.
    # Layers 2-5 are loaded in order, each overwriting the previous.
    config_paths: list[Path] = [GLOBAL_CONFIG_PATH]  # layer 2

    if workspace_root is not None:
        # Layer 3 — workspace-wide
        config_paths.append(workspace_root / ".matrixmouse" / "config.toml")

        if repo_root is not None:
            # Layer 4 — repo-local, untracked (workspace state dir)
            repo_name = Path(repo_root).resolve().name
            config_paths.append(
                workspace_root / ".matrixmouse" / repo_name / "config.toml"
            )

    if repo_root is not None:
        # Layer 5 — repo-local, tracked (inside the git tree)
        config_paths.append(repo_root / ".matrixmouse" / "config.toml")

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


@dataclass
class MatrixMousePaths:
    """
    Resolved filesystem paths for a MatrixMouse session.

    Built once at startup from workspace_root and repo_root.

    Layout:

        /etc/matrixmouse/                   service config + secrets

        <workspace_root>/
            .matrixmouse/
                config.toml                 workspace-level config overrides
                tasks.json                  task queue (all repos)
                repos.json                  registered repos
                agent.pid                   PID lockfile
                testrunner.image.sha256     upgrade hash
                ignore                      workspace-wide safety blacklist
                <repo_name>/                per-repo runtime state (not in git)
                    AGENT_NOTES.md          agent working memory
                    agent.log               session log
                    ignore                  per-repo local safety blacklist

        <repo_root>/                        the git repo — minimal footprint
            .matrixmouse/                   only exists if user opted in
                config.toml                 repo-level config overrides
                ignore                      team-shared safety blacklist
            docs/
                design/                     only if create_design_docs=true
                adr/                        only if create_adr_docs=true
    """
    workspace_root: Path
    repo_root: Path
    repo_name: str          # basename of repo_root; used for per-repo ws dir
    config_dir: Path        # <repo_root>/.matrixmouse/
    repo_state_dir: Path    # <workspace_root>/.matrixmouse/<repo_name>/
    agent_notes: Path       # <repo_state_dir>/AGENT_NOTES.md
    log_file: Path          # <repo_state_dir>/agent.log
    design_docs: Path       # <repo_root>/docs/design/
    tasks_file: Path        # <workspace_root>/.matrixmouse/tasks.json
