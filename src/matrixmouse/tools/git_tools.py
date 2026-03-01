"""
matrixmouse/tools/git_tools.py

Tools for interacting with the git repository.
All operations run against the project root configured in _safety.py.

Tools exposed:
    create_task_branch  — create and checkout a new agent working branch
    commit_progress     — stage all changes and commit with an agent prefix
    get_git_diff        — show unstaged or staged changes
    get_git_log         — show recent commit history
    get_git_status      — show working tree status
    push_branch         — push current branch to origin
    open_pull_request   — open a PR via GitHub/Gitea API (NOT YET IMPLEMENTED)

Do not add file, navigation, or AST tools here.
"""

import logging
import subprocess
from matrixmouse.tools._safety import project_root

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------

def _git(args: list[str]) -> tuple[bool, str]:
    """
    Run a git command in the project root.

    Args:
        args: git subcommand and arguments, e.g. ["log", "-5", "--oneline"]

    Returns:
        (success: bool, output: str) where output is stdout on success
        or stderr on failure.
    """
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=project_root(),
            capture_output=True,
            text=True,
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


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

def create_task_branch(branch_name: str) -> str:
    """
    Create and checkout a new branch for the current task.
    Branch is created under the agent/ namespace to keep agent work
    separate from human branches.

    The branch name is sanitised automatically — spaces become hyphens
    and the result is truncated to 50 characters.

    Args:
        branch_name: Descriptive name for the branch, e.g. "add input validation".

    Returns:
        Success message with the full branch name, or an error.
    """
    safe = branch_name.lower().strip().replace(" ", "-").replace("/", "-")
    safe = "".join(c for c in safe if c.isalnum() or c in "-_")[:50]
    full_name = f"agent/{safe}"

    success, output = _git(["checkout", "-b", full_name])
    if success:
        logger.info("Created branch: %s", full_name)
        return f"OK: Created and checked out branch '{full_name}'."
    return _fmt(success, output, "create_task_branch")


def commit_progress(message: str) -> str:
    """
    Stage all current changes and create a commit.
    Commit message is prefixed with [agent] to distinguish agent commits
    from human commits in the log.

    Only call this when the current state is worth preserving — ideally
    after tests pass or a logical unit of work is complete.

    Args:
        message: Commit message describing what was done.

    Returns:
        Success message with the commit hash, or an error.
    """
    # Stage everything
    success, output = _git(["add", "-A"])
    if not success:
        return _fmt(success, output, "commit_progress/add")

    # Check if there's anything to commit
    _, status = _git(["status", "--porcelain"])
    if not status:
        return "OK: Nothing to commit — working tree is clean."

    full_message = f"[agent] {message}"
    success, output = _git(["commit", "-m", full_message])
    if success:
        logger.info("Committed: %s", full_message)
        return f"OK: Committed — {output}"
    return _fmt(success, output, "commit_progress/commit")


def get_git_diff(staged: bool = False) -> str:
    """
    Show the current diff of uncommitted changes.

    Use this to review what has changed before committing, or to
    verify that a str_replace made the expected change.

    Args:
        staged: If True, show staged (indexed) changes.
                If False (default), show unstaged working tree changes.

    Returns:
        Diff output as a string, or a message if there are no changes.
    """
    args = ["diff"]
    if staged:
        args.append("--staged")

    success, output = _git(args)
    if not success:
        return _fmt(success, output, "get_git_diff")
    if not output:
        label = "staged" if staged else "unstaged"
        return f"No {label} changes."
    return output


def get_git_log(n: int = 10) -> str:
    """
    Show recent commit history for the current branch.

    Use this to understand what has been done recently, or to verify
    that a commit was recorded correctly.

    Args:
        n: Number of commits to show. Defaults to 10.

    Returns:
        Formatted log with hash, author, relative date, and subject.
    """
    n = max(1, min(n, 50))  # clamp to a sane range
    success, output = _git([
        "log", f"-{n}",
        "--format=%h  %<(20)%an  %ar  %s",
    ])
    if not success:
        return _fmt(success, output, "get_git_log")
    if not output:
        return "No commits yet."
    return output


def get_git_status() -> str:
    """
    Show the working tree status — which files are modified, staged,
    untracked, or in conflict.

    Use this to get an overview of the current state before committing
    or to check whether previous edits were saved.

    Returns:
        Short-format git status output.
    """
    success, output = _git(["status", "--short"])
    if not success:
        return _fmt(success, output, "get_git_status")
    if not output:
        return "Working tree is clean."
    return output


def push_branch() -> str:
    """
    Push the current branch to origin.

    Call this after committing a completed task and before requesting
    human review. Requires a configured remote named 'origin'.

    Returns:
        Success message, or an error if the push failed.
    """
    # Get current branch name
    success, branch = _git(["rev-parse", "--abbrev-ref", "HEAD"])
    if not success:
        return _fmt(success, branch, "push_branch/get-branch")

    if branch == "HEAD":
        return "ERROR: Detached HEAD state — cannot push. Checkout a named branch first."

    success, output = _git(["push", "--set-upstream", "origin", branch])
    if success:
        logger.info("Pushed branch: %s", branch)
        return f"OK: Branch '{branch}' pushed to origin."
    return _fmt(success, output, "push_branch")


def open_pull_request(title: str, body: str, base: str = "main") -> str:
    """
    Open a pull request on GitHub or Gitea.

    Call this after pushing a completed branch to request human review.

    Args:
        title: PR title.
        body:  PR description summarising what was done and why.
        base:  Target branch to merge into. Defaults to 'main'.

    Returns:
        URL of the created PR, or an error message.
    """
    # TODO: implement with PyGithub or httpx once a GitHub/Gitea token
    # is configured. 
    #
    # Implementation sketch:
    #   from github import Github
    #   g = Github(config.github_token)
    #   repo = g.get_repo(config.github_repo)
    #   pr = repo.create_pull(title=title, body=body, head=current_branch, base=base)
    #   return f"OK: PR opened at {pr.html_url}"

    success, branch = _git(["rev-parse", "--abbrev-ref", "HEAD"])
    branch_info = f" (current branch: {branch})" if success else ""

    return (
        f"PR creation is not yet implemented{branch_info}. "
        f"To open a PR manually: push the branch with push_branch(), "
        f"then open a PR on GitHub/Gitea from '{branch}' into '{base}'."
    )
