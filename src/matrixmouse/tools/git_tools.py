"""
matrixmouse/tools/git_tools.py

Git operations for MatrixMouse task execution.

Two layers:

    Internal functions (not agent tools):
        branch_exists         — check if a branch exists locally
        create_branch         — create a branch from a base
        push_to_remote        — push a branch to a named remote
        get_head_hash         — get current HEAD commit hash
        squash_wip_commits    — squash AUTO-WIP commits since a baseline
        wip_commit_and_push   — stage, WIP-commit, and push to mirror

    Agent-facing tools:
        git_commit            — stage all and commit with agent message
        get_git_diff          — diff against task baseline (wip_commit_hash)
        get_git_log           — recent commits, WIP commits filtered out
        get_git_status        — working tree status
        push_branch           — push current branch to origin
        clone_repo            — clone a remote repo into the workspace

configure(task) must be called at task start so agent tools use the
correct baseline and branch context.

Do not add file, navigation, or AST tools here.

TODO: Manager should be able to create and init a new git repo as part of
a workspace-scoped interjection response (e.g. "make me a new project").
clone_repo is the foundation; a future init_repo tool would create an
empty repo and register it with the workspace.
"""

import logging
import os
import subprocess
from pathlib import Path
from typing import Optional

from matrixmouse.task import Task
from matrixmouse.tools._safety import project_root
from matrixmouse import config as config_module

logger = logging.getLogger(__name__)

# WIP commit prefix — used for filtering and squashing
WIP_PREFIX = "AUTO-WIP:"

# Mirror remote name — must match MIRROR_REMOTE in init.py
MIRROR_REMOTE = "mm-mirror"


# ---------------------------------------------------------------------------
# Module-level state — set by configure()
# ---------------------------------------------------------------------------

_active_wip_commit_hash: Optional[str] = None
_active_branch: Optional[str] = None
_active_cwd: Optional[Path] = None


def configure(task: Task, cwd: Path) -> None:
    """
    Configure git tools for the active task.

    Called by the orchestrator at task start, alongside task_tools.configure().
    Stores the task's wip_commit_hash and branch so agent-facing tools can
    use the correct baseline without requiring the agent to supply them.

    Args:
        task: The task being executed.
        cwd:  Working directory (repo root) for all git operations.
    """
    global _active_wip_commit_hash, _active_branch, _active_cwd
    _active_wip_commit_hash = task.wip_commit_hash or None
    _active_branch = task.branch or None
    _active_cwd = cwd
    logger.debug(
        "git_tools configured. branch=%s wip_hash=%s cwd=%s",
        _active_branch, _active_wip_commit_hash, cwd,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _require_ssh_key() -> Path:
    """
    Return the absolute path to the MatrixMouse SSH private key.
    Raises FileNotFoundError if the key file is missing. 
    """
    cfg = getattr(config_module, "_loaded_config", None)
    if not cfg:
        raise AttributeError("Configuration not found")
    secrets_dir = Path("/etc/matrixmouse/secrets")
    key_path = secrets_dir / cfg.gh_ssh_key_file

    if not key_path.is_file():
        raise FileNotFoundError(
            f"SSH key not found at {key_path}. "
            "Create it or fix gh_ssh_key_file in your config."
        )
    return key_path


def _git_env() -> dict:
    """
    Build the environment for git subprocess calls.
    Injects SSH key and agent git identity from config.
    """
    key_path = _require_ssh_key()
    env = os.environ.copy()
    cfg = getattr(config_module, "_loaded_config", None)

    env["GIT_SSH_COMMAND"] = (
        f"ssh -i {key_path} "
        f"-o IdentitiesOnly=yes "
        f"-o StrictHostKeyChecking=accept-new"
    )
    env["GIT_AUTHOR_NAME"]     = cfg.agent_git_name
    env["GIT_AUTHOR_EMAIL"]    = cfg.agent_git_email
    env["GIT_COMMITTER_NAME"]  = cfg.agent_git_name
    env["GIT_COMMITTER_EMAIL"] = cfg.agent_git_email
    return env


def _git(args: list[str], cwd: Path) -> tuple[bool, str]:
    """
    Run a git command in the given directory.

    Args:
        args: git subcommand and arguments.
        cwd:  Working directory — always required, no global fallback.

    Returns:
        (success: bool, output: str)
    """
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=cwd,
            capture_output=True,
            text=True,
            env=_git_env(),
        )
        if result.returncode != 0:
            return False, result.stderr.strip() or result.stdout.strip()
        return True, result.stdout.strip()
    except FileNotFoundError:
        return False, "git is not installed or not in PATH."
    except Exception as e:
        return False, f"Unexpected error running git: {e}"


def _fmt(success: bool, output: str, context: str = "") -> str:
    """Format a git result as a tool response string."""
    if success:
        return output if output else "OK"
    prefix = f"ERROR ({context}): " if context else "ERROR: "
    return prefix + output


def _require_cwd(cwd: Optional[Path]) -> Path:
    """Return cwd if provided, else fall back to configured cwd."""
    if cwd is not None:
        return cwd
    if _active_cwd is not None:
        return _active_cwd
    raise RuntimeError(
        "git_tools not configured. "
        "Call git_tools.configure(task, cwd) at task start."
    )


# ---------------------------------------------------------------------------
# Internal functions (not agent-facing tools)
# ---------------------------------------------------------------------------

def branch_exists(branch_name: str, cwd: Path) -> bool:
    """
    Return True if the branch exists locally.

    Args:
        branch_name: Full branch name to check.
        cwd:         Repository root.
    """
    success, output = _git(
        ["branch", "--list", branch_name],
        cwd=cwd,
    )
    return success and bool(output.strip())

def ensure_branch_from_mirror(
    branch_name: str,
    mirror_remote: str,
    cwd: Path,
) -> tuple[bool, str]:
    """
    Ensure a branch exists locally, recreating from mirror if missing.

    Called at task startup (resume after service restart, or first run
    on a new worker). If the branch already exists locally, this is a
    no-op. If it is missing, it is recreated by fetching from the mirror
    and checking out a local tracking branch.

    Args:
        branch_name:   Full branch name to verify/recreate.
        mirror_remote: Remote name for the local mirror (e.g. 'mm-mirror').
        cwd:           Repository root.

    Returns:
        (True, branch_name) if the branch exists or was recreated.
        (False, error_message) if recreation failed.
    """
    if branch_exists(branch_name, cwd):
        logger.debug("Branch '%s' exists locally — no action needed.", branch_name)
        return True, branch_name

    logger.info(
        "Branch '%s' not found locally — attempting to recreate from mirror.",
        branch_name,
    )

    # Fetch the branch from the mirror
    ok, err = _git(["fetch", mirror_remote, branch_name], cwd=cwd)
    if not ok:
        return False, (
            f"Failed to fetch '{branch_name}' from mirror '{mirror_remote}': {err}"
        )

    # Create a local tracking branch from the fetched ref
    ok, err = _git(
        ["checkout", "-b", branch_name,
         f"{mirror_remote}/{branch_name}"],
        cwd=cwd,
    )
    if not ok:
        return False, (
            f"Failed to create local branch '{branch_name}' "
            f"from '{mirror_remote}/{branch_name}': {err}"
        )

    logger.info(
        "Branch '%s' recreated from mirror '%s'.",
        branch_name, mirror_remote,
    )
    return True, branch_name

def create_branch(
    branch_name: str,
    base_branch: str,
    cwd: Path,
) -> tuple[bool, str]:
    """
    Create a new branch from base_branch and check it out.

    Args:
        branch_name: Name of the new branch.
        base_branch: Branch to base the new branch on.
        cwd:         Repository root.

    Returns:
        (success, message)
    """
    success, output = _git(
        ["checkout", "-b", branch_name, base_branch],
        cwd=cwd,
    )
    if success:
        logger.info("Created branch '%s' from '%s'", branch_name, base_branch)
    return success, output


def push_to_remote(
    branch_name: str,
    remote: str,
    cwd: Path,
    force: bool = False,
) -> tuple[bool, str]:
    """
    Push a branch to a named remote.

    Args:
        branch_name: Branch to push.
        remote:      Remote name (e.g. 'mm-mirror', 'origin').
        cwd:         Repository root.
        force:       If True, use --force-with-lease for safe force push.

    Returns:
        (success, message)
    """
    args = ["push", remote, branch_name]
    if force:
        args.append("--force-with-lease")
    return _git(args, cwd=cwd)


def get_head_hash(cwd: Path) -> Optional[str]:
    """
    Return the current HEAD commit hash, or None if the repo has no commits.

    Args:
        cwd: Repository root.
    """
    success, output = _git(["rev-parse", "HEAD"], cwd=cwd)
    return output if success and output else None


def squash_wip_commits(
    since_hash: str,
    message: str,
    cwd: Path,
) -> tuple[bool, str]:
    """
    Squash contiguous AUTO-WIP commits at the top of the log into one commit.

    Walks git log from HEAD back to since_hash. Collects any leading
    AUTO-WIP: commits. If found, resets softly to the last non-WIP commit
    and creates a new commit with the given message.

    Non-WIP commits in the history are never touched.

    Args:
        since_hash: Baseline hash (task.wip_commit_hash). Commits at or
                    before this hash are not examined.
        message:    Commit message for the squashed result.
        cwd:        Repository root.

    Returns:
        (success, message) — success is True even if nothing was squashed
        (no WIP commits found is a no-op, not an error).
    """
    # Get log from HEAD back to since_hash (exclusive)
    success, log_output = _git(
        ["log", f"{since_hash}..HEAD", "--format=%H %s"],
        cwd=cwd,
    )
    if not success:
        return False, f"Failed to read git log: {log_output}"

    if not log_output.strip():
        return True, "Nothing to squash — no commits since baseline."

    lines = log_output.strip().splitlines()
    # Collect contiguous WIP commits from the top (most recent first)
    wip_hashes = []
    last_non_wip_hash = since_hash

    for line in lines:
        parts = line.split(" ", 1)
        if len(parts) != 2:
            continue
        commit_hash, subject = parts
        if subject.startswith(WIP_PREFIX):
            wip_hashes.append(commit_hash)
        else:
            # First non-WIP commit — everything from here down is real history
            last_non_wip_hash = commit_hash
            break

    if not wip_hashes:
        return True, "Nothing to squash — no WIP commits at top of log."

    # Reset softly to the last non-WIP commit
    success, output = _git(
        ["reset", "--soft", last_non_wip_hash],
        cwd=cwd,
    )
    if not success:
        return False, f"Failed to reset before squash: {output}"

    # Commit with the provided message
    success, output = _git(
        ["commit", "-m", message],
        cwd=cwd,
    )
    if not success:
        return False, f"Failed to create squashed commit: {output}"

    logger.info(
        "Squashed %d WIP commit(s) into: %s",
        len(wip_hashes), message,
    )
    return True, output


def wip_commit_and_push(
    branch: str,
    mirror_remote: str,
    cwd: Path,
    push_to_origin: bool = False,
) -> tuple[bool, str]:
    """
    Stage all changes, create a WIP commit, and push to the local mirror.

    Called after every inference dispatch. If the working tree is clean,
    this is a no-op (no empty WIP commits created).

    Args:
        branch:          Current task branch name.
        mirror_remote:   Remote name for the local mirror (e.g. 'mm-mirror').
        cwd:             Repository root.
        push_to_origin:  If True, also push to 'origin' after mirror push.
                         Controlled by push_wip_to_remote config key.

    Returns:
        (success, message). Mirror push failure is a hard error.
        Origin push failure is logged as a warning but does not affect
        the return value.
    """
    from datetime import datetime, timezone

    # Check if working tree is dirty
    _, status = _git(["status", "--porcelain"], cwd=cwd)
    if not status:
        return True, "Working tree is clean — no WIP commit needed."

    # Stage everything
    success, output = _git(["add", "-A"], cwd=cwd)
    if not success:
        return False, f"Failed to stage changes: {output}"

    # WIP commit
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    wip_message = f"{WIP_PREFIX}{timestamp}"
    success, output = _git(["commit", "-m", wip_message], cwd=cwd)
    if not success:
        return False, f"Failed to create WIP commit: {output}"

    logger.debug("WIP commit created: %s", wip_message)

    # Push to local mirror — mandatory, hard error on failure
    success, output = push_to_remote(branch, mirror_remote, cwd)
    if not success:
        logger.error(
            "CRITICAL: Failed to push WIP commit to mirror '%s': %s. "
            "Local mirror is out of sync. Check mirror health.",
            mirror_remote, output,
        )
        return False, (
            f"Failed to push to local mirror '{mirror_remote}': {output}. "
            f"This is a critical error — mirror may be out of sync."
        )

    logger.debug("WIP commit pushed to %s", mirror_remote)

    # Push to remote origin — optional, warning only on failure
    if push_to_origin:
        ok, out = push_to_remote(branch, "origin", cwd)
        if not ok:
            logger.warning(
                "Failed to push WIP to remote origin: %s. "
                "Mirror is still in sync. Remote will be updated on next success.",
                out,
            )

    return True, wip_message


# ---------------------------------------------------------------------------
# Agent-facing tools
# ---------------------------------------------------------------------------

def git_commit(message: str, cwd: Optional[Path] = None) -> str:
    """
    Stage all current changes and create a commit.

    Automatically squashes any preceding AUTO-WIP commits since the task
    baseline (wip_commit_hash) so the history stays clean. Only call this
    when the current state represents a logical unit of completed work —
    ideally after tests pass.

    Args:
        message: Commit message describing what was done.
                 Do not include an [agent] prefix — this is added automatically.

    Returns:
        Success message with the commit hash, or an error.
    """
    resolved_cwd = _require_cwd(cwd)

    # Stage everything first
    success, output = _git(["add", "-A"], cwd=resolved_cwd)
    if not success:
        return _fmt(success, output, "git_commit/add")

    # If we have a baseline, attempt squash first regardless of staging state.
    # There may be WIP commits to squash even if the working tree is clean.
    if _active_wip_commit_hash:
        sq_success, sq_output = squash_wip_commits(
            since_hash=_active_wip_commit_hash,
            message=f"[agent] {message}",
            cwd=resolved_cwd,
        )
        if not sq_success:
            return _fmt(False, sq_output, "git_commit/squash")
        if "Nothing to squash" not in sq_output:
            logger.info("git_commit: squashed WIP commits into agent commit")
            return f"OK: Committed (squashed WIP) — {sq_output}"

    # No WIP commits squashed — check if there's anything new to commit
    _, status = _git(["status", "--porcelain"], cwd=resolved_cwd)
    if not status:
        return "OK: Nothing to commit — working tree is clean."

    full_message = f"[agent] {message}"
    success, output = _git(["commit", "-m", full_message], cwd=resolved_cwd)
    if success:
        logger.info("Committed: %s", full_message)
        return f"OK: Committed — {output}"
    return _fmt(success, output, "git_commit/commit")


def get_git_diff(base: Optional[str] = None, cwd: Optional[Path] = None) -> str:
    """
    Show changes made during this task against the task baseline.

    By default, diffs against the task's wip_commit_hash — the HEAD of the
    parent branch at the time this task's branch was created. This shows
    everything the agent has done on this task, excluding WIP commit noise.

    AUTO-WIP commits are not shown — only the content changes matter.

    Args:
        base: Override the diff baseline. If omitted, uses wip_commit_hash.
              Use 'HEAD' to see only unstaged changes.

    Returns:
        Diff output as a string, or a message if there are no changes.
    """
    resolved_cwd = _require_cwd(cwd)
    baseline = base or _active_wip_commit_hash

    if baseline:
        args = ["diff", baseline]
    else:
        args = ["diff"]

    success, output = _git(args, cwd=resolved_cwd)
    if not success:
        return _fmt(success, output, "get_git_diff")
    if not output:
        if baseline:
            return f"No changes since baseline ({baseline[:8]})."
        return "No unstaged changes."
    return output


def get_git_log(n: int = 10, cwd: Optional[Path] = None) -> str:
    """
    Show recent commit history for the current branch.

    AUTO-WIP commits are filtered out — you only see real commits made
    by you or by humans. This keeps the log readable during long tasks.

    Args:
        n: Number of real commits to show. Defaults to 10.
           The tool may inspect more commits internally to filter WIP entries.

    Returns:
        Formatted log with hash, author, relative date, and subject.
    """
    resolved_cwd = _require_cwd(cwd)
    n = max(1, min(n, 50))

    # Fetch more commits than requested to account for WIP filtering
    fetch_n = n * 4
    success, output = _git(
        ["log", f"-{fetch_n}", "--format=%H\t%<(20)%an\t%ar\t%s"],
        cwd=resolved_cwd,
    )
    if not success:
        return _fmt(success, output, "get_git_log")
    if not output:
        return "No commits yet."

    lines = output.splitlines()
    real_lines = []
    for line in lines:
        parts = line.split("\t", 3)
        if len(parts) == 4:
            _, author, date, subject = parts
            if subject.startswith(WIP_PREFIX):
                continue
            real_lines.append(
                f"{parts[0][:8]}  {author.strip():<20}  {date.strip():<16}  {subject}"
            )
        if len(real_lines) >= n:
            break

    if not real_lines:
        return "No real commits yet (only WIP commits exist)."
    return "\n".join(real_lines)


def get_git_status(cwd: Optional[Path] = None) -> str:
    """
    Show the working tree status — modified, staged, untracked, or conflicted files.

    Use this before committing to verify your changes are what you expect.

    Returns:
        Short-format git status output.
    """
    resolved_cwd = _require_cwd(cwd)
    success, output = _git(["status", "--short"], cwd=resolved_cwd)
    if not success:
        return _fmt(success, output, "get_git_status")
    if not output:
        return "Working tree is clean."
    return output


def push_branch(cwd: Optional[Path] = None) -> str:
    """
    Push the current branch to origin.

    Call this after committing completed work and before the task is
    declared complete. Used when you want to share work-in-progress with
    the remote before the full merge-up-to-parent flow runs.

    Returns:
        Success message, or an error if the push failed.
    """
    resolved_cwd = _require_cwd(cwd)
    success, branch = _git(
        ["rev-parse", "--abbrev-ref", "HEAD"],
        cwd=resolved_cwd,
    )
    if not success:
        return _fmt(success, branch, "push_branch/get-branch")

    if branch == "HEAD":
        return (
            "ERROR: Detached HEAD state — cannot push. "
            "Checkout a named branch first."
        )

    success, output = _git(
        ["push", "--set-upstream", "origin", branch],
        cwd=resolved_cwd,
    )
    if success:
        logger.info("Pushed branch: %s", branch)
        return f"OK: Branch '{branch}' pushed to origin."
    return _fmt(success, output, "push_branch")


def clone_repo(remote_url: str, directory: Optional[str] = None) -> str:
    """
    Clone a remote repository into the MatrixMouse workspace.

    The repo is cloned into <workspace_root>/<directory>. After cloning,
    run `matrixmouse init --repo <directory>` to register it.

    Args:
        remote_url: The remote URL to clone.
        directory:  Subdirectory name. Defaults to the repo name from the URL.

    Returns:
        Success message with the clone path, or an error.
    """
    if not directory:
        directory = remote_url.rstrip("/").rsplit("/", 1)[-1]
        if directory.endswith(".git"):
            directory = directory[:-4]

    if not directory:
        return (
            "ERROR: Could not infer directory name from URL. "
            "Pass directory explicitly."
        )

    if ".." in directory or "/" in directory:
        return "ERROR: Directory name must not contain '..' or '/'."

    workspace = os.environ.get("WORKSPACE_PATH")
    if not workspace:
        workspace = str(project_root().parent)

    workspace_path = Path(workspace)
    clone_path = workspace_path / directory

    if clone_path.exists():
        return (
            f"ERROR: Directory '{clone_path}' already exists. "
            "Remove it first or choose a different directory name."
        )

    logger.info("Cloning %s into %s", remote_url, clone_path)
    success, output = _git(
        ["clone", remote_url, str(clone_path)],
        cwd=workspace_path,
    )

    if success:
        logger.info("Cloned %s to %s", remote_url, clone_path)
        return (
            f"OK: Cloned '{remote_url}' to '{clone_path}'.\n"
            f"Next: run 'matrixmouse init --repo {directory}' to register it."
        )
    return _fmt(success, output, "clone_repo")
