"""
matrixmouse/git/git_remote_provider.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Abstract base class for git remote provider adapters.

Each concrete implementation (GitHubProvider, GitLabProvider, GiteaProvider,
…) targets one hosting platform.  The orchestrator and repository layer
program only against this interface.

Exception hierarchy
-------------------
    GitRemoteError          — base; catch this for all provider failures
        AuthenticationError — 401/403; bad or missing token
        ProviderAPIError    — any other non-2xx response or network error

Format contract for get_pr_feedback()
--------------------------------------
Returns a human- and model-readable string.  Inline review comments are
grouped by file; each comment renders as:

    Review by <author> (<state>):

    <file.py>:
      <line> | <source line text>
             ^ <comment body>

    General comments:
      <review body text, if any>

If a review carries no inline comments, only the "General comments" block
is emitted.  An approved review with no body renders as:

    Review by <author> (APPROVED):
      No comments.

Multiple reviews are separated by a blank line.

TODO: Future extension points (not yet on the ABC — added when issue-assignment
feature lands in a later branch):
    list_issues(repo, state) -> list[dict]
    get_issue(repo, issue_number) -> dict
    assign_issue(repo, issue_number, assignee) -> None
"""

from __future__ import annotations

from abc import ABC, abstractmethod


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class GitRemoteError(Exception):
    """Base exception for all git remote provider failures."""


class AuthenticationError(GitRemoteError):
    """
    Raised when the provider rejects credentials (HTTP 401 or 403).

    Typically means the token is missing, expired, or lacks the required
    scope for the requested operation.
    """


class ProviderAPIError(GitRemoteError):
    """
    Raised for any other provider-side failure.

    Covers non-2xx responses not related to authentication, network errors,
    unexpected response shapes, and rate-limit exhaustion.  The message
    should include enough context for the caller to log meaningfully
    (provider name, HTTP status if available, endpoint).
    """


# ---------------------------------------------------------------------------
# ABC
# ---------------------------------------------------------------------------


class GitRemoteProvider(ABC):
    """
    Interface for interacting with a git remote hosting provider.

    All methods are synchronous.  Implementations are responsible for
    token retrieval (typically via os.environ), HTTP session management,
    and formatting provider responses into the contracts described below.

    Parameter conventions
    ---------------------
    repo: str
        The repository root name as stored on the Task (e.g. "MatrixMouse").
        The implementation resolves owner/org and API base URL from
        repo_metadata (remote_url field).  Callers never construct
        provider-specific identifiers.

    Raises:
        AuthenticationError: When the provider returns 401 or 403.
        ProviderAPIError: For all other provider-side or network failures.
    """

    # ------------------------------------------------------------------
    # Branch protection
    # ------------------------------------------------------------------

    @abstractmethod
    def is_branch_protected(self, repo: str, branch: str) -> bool:
        """
        Return True if *branch* is protected on the remote.

        Implementations should consult the caller-managed cache
        (WorkspaceStateRepository.get_protected_branches_cached) before
        making a network request, and update the cache on a miss.

        The cache TTL is owned by the orchestrator/repository layer, not
        the provider.  The provider only answers "is this branch protected
        right now?" when a live check is needed.

        Args:
            repo (str): the repo name from Task.repo
            branch (str): the remote branch to check

        Returns:
            True if branch is protected, False if not.
        """

    # ------------------------------------------------------------------
    # Pull requests
    # ------------------------------------------------------------------

    @abstractmethod
    def create_pull_request(
        self,
        repo: str,
        head: str,
        base: str,
        title: str,
        body: str,
    ) -> str:
        """
        Open a pull request and return its URL.

        Args:
            repo (str): repository root name (see class docstring)
            head (str): source branch (the task branch being merged)
            base (str): target branch (the protected branch)
            title (str): PR title; callers typically use the task title
            body (str): PR description; callers typically use the task description

        Returns:
            str: The canonical web URL of the newly created PR 
            (e.g. "https://github.com/owner/repo/pull/42"). Stored directly in 
            task.pr_url.
        """

    @abstractmethod
    def get_pr_state(self, repo: str, pr_url: str) -> str:
        """
        Return the current state of a pull request.

        Returns one of the PRState string values: "open", "merged",
        "closed", or "" (unknown/not found).  Returning a plain string
        keeps this layer free of Task-model imports; the orchestrator maps
        the value to PRState.

        Args:
            repo (str): repository root name
            pr_url (str): URL as stored in task.pr_url

        Returns:
            String representing the current PR state ("open", "merged", 
            "closed", or "")
        """

    @abstractmethod
    def get_pr_feedback(self, repo: str, pr_url: str) -> str:
        """
        Return formatted review feedback for a pull request.

        Intended for injection directly into an agent's context_messages
        when a PR is closed with CHANGES_REQUESTED or similar.  The
        provider formats all reviews into the canonical multi-review
        string described in this module's docstring.

        Args:
            repo (str): repository root name
            pr_url (str): URL as stored in task.pr_url

        Returns:
            Formatted review feedback ready for context injection.
            Returns an empty string if there are no reviews.
        """
