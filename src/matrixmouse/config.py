"""
matrixmouse/config.py

Configuration loading for MatrixMouse using pydantic-settings.

Config is loaded from three sources in order of increasing priority:
    1. Field defaults defined in MatrixMouseConfig below
    2. Global config    — ~/.config/matrixmouse/config.toml
    3. Repo-local config — <repo_root>/.matrixmouse/config.toml

Each source overwrites keys from the previous. Keys not present in a
source are inherited unchanged.

To add a new config field:
    1. Add it to MatrixMouseConfig with a type, default, and description.
    2. That's it. DEFAULTS and STARTER_CONFIG are derived automatically.

Do not add runtime state or argument parsing here — config loading only.
"""

import tomllib
from pathlib import Path
from typing import Any

from pydantic import Field
from pydantic_settings import BaseSettings

from dataclasses import dataclass


class MatrixMouseConfig(BaseSettings):
    """
    All configuration fields for a MatrixMouse session.

    Each field has a default, a type, and a description. The description
    is used to generate the starter config file, so write it as a
    human-readable comment for the end user.
    """

    # --- Models ---
    coder: str = Field(
            default="qwen3:8b",
        description="Model for code generation and implementation tasks.",
    )
    planner: str = Field(
        default="qwen3:8b",
        description="Model for planning, design, and architectural decisions.",
    )
    judge: str = Field(
        default="qwen3:8b",
        description="Model for critique, review, and stuck detection.",
    )
    summarizer: str = Field(
        default="qwen3:4b",
        description="Model for context summarisation. Should be small and fast.",
    )

    # --- Logging ---
    log_level: str = Field(
        default="INFO",
        description="Logging level. One of: DEBUG, INFO, WARNING, ERROR.",
    )
    log_to_file: bool = Field(
        default=False,
        description="Write logs to .matrixmouse/agent.log. Disable inside Docker.",
    )

    # --- Agent behaviour ---
    context_soft_limit: int = Field(
        default=32000,
        description="Token limit before context compression is triggered.",
    )
    compress_threshold: float = Field(
        default=0.60,
        description="Fraction of context_soft_limit at which compression triggers (0.0-1.0).",
    )
    stuck_turn_window: int = Field(
        default=6,
        description="Number of recent turns to inspect when checking for stuck behaviour.",
    )
    keep_last_n_turns: int = Field(
        default=6,
        description="Number of recent turns to preserve during context compression.",
    )

    model_config = {"extra": "ignore"}  # silently ignore unknown keys from TOML


GLOBAL_CONFIG_PATH = Path.home() / ".config" / "matrixmouse" / "config.toml"


def load_config(repo_root: Path) -> MatrixMouseConfig:
    """
    Load and merge configuration from all sources.

    Reads the global config and then the repo-local config, with each
    layer overwriting keys from the previous. Returns a validated,
    typed MatrixMouseConfig instance.

    Args:
        repo_root: Root directory of the repo being worked on.

    Returns:
        A fully merged and validated MatrixMouseConfig instance.
    """
    merged: dict[str, Any] = {}

    for config_path in (GLOBAL_CONFIG_PATH, repo_root / ".matrixmouse" / "config.toml"):
        if config_path.exists():
            with open(config_path, "rb") as f:
                merged.update(tomllib.load(f))

    return MatrixMouseConfig(**merged)


def generate_starter_config() -> str:
    """
    Generate the contents of a starter config.toml from MatrixMouseConfig field metadata.
    All fields are commented out so the file documents available options without
    overriding any defaults.

    Returns:
        A TOML-formatted string ready to write to disk.
    """
    lines = [
        "# MatrixMouse repo-local configuration",
        "# Any values set here override your global config at ~/.config/matrixmouse/config.toml",
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
    """Resolved filesystem paths for a MatrixMouse session.

    Built once in main.py from repo_root and passed to subsystems 
    that need filesystem access. Avoids passing repo_root through 
    multiple layers just to reconstruct the same paths repeatedly.

    All paths are absolute and resolved at construction time.
    """
    repo_root: Path
    config_dir: Path
    log_file: Path
    agent_notes: Path
    design_docs: Path
