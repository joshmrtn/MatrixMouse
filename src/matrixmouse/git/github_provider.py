"""
matrixmouse/git/github_provider.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
GitHub implementation of GitRemoteProvider.

Authentication:
    Reads GITHUB_TOKEN from the environment.  The token is loaded into
    os.environ by _service.py before this module is ever imported, so
    callers can construct GitHubProvider() with no arguments and the token
    will be present.

    A token may also be passed explicitly for testing or one-off use:
        provider = GitHubProvider(token="ghp_...")

API base:
    Defaults to https://api.github.com.  Pass api_base to target GitHub
    Enterprise:
        provider = GitHubProvider(api_base="https://github.example.com/api/v3")

Review comment types:
    get_pr_feedback() renders inline comments with a bracketed tag:

        [Comment]    — plain line comment, no replacement proposed
        [Suggestion] — reviewer proposed an exact replacement, rendered as
                       a unified diff so the agent can apply it directly

    The review-level state (APPROVED, CHANGES_REQUESTED, COMMENTED) appears
    in the review header and comes directly from the GitHub API — it is the
    reviewer's explicit submission choice, not derived from comment content.

    Inline comments are grouped by file.  General review body text (not
    attached to any line) is emitted under "General comments:".
"""

from __future__ import annotations

import os
import re
from typing import Any

import requests

from matrixmouse.git.git_remote_provider import (
    AuthenticationError,
    GitRemoteProvider,
    ProviderAPIError,
)

_DEFAULT_API_BASE = "https://api.github.com"

# Matches GitHub suggestion fences inside a review comment body:
#   ```suggestion
#   replacement line(s)
#   ```
_SUGGESTION_RE = re.compile(
    r"```suggestion\r?\n(.*?)```",
    re.DOTALL,
)


class GitHubProvider(GitRemoteProvider):
    """
    GitRemoteProvider backed by the GitHub REST API v3.

    Args:
        token: GitHub personal access token or fine-grained token with
            repo scope.  Defaults to os.environ["GITHUB_TOKEN"].
        api_base: API root URL.  Override for GitHub Enterprise.
    """

    def __init__(
        self,
        token: str | None = None,
        api_base: str = _DEFAULT_API_BASE,
    ) -> None:
        self._token = token or os.environ.get("GITHUB_TOKEN", "")
        self._api_base = api_base.rstrip("/")
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {self._token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get(self, path: str, **kwargs: Any) -> Any:
        """
        Perform a GET request against the GitHub API.

        Args:
            path: API path, e.g. "/repos/owner/repo/branches/main/protection".
            **kwargs: Forwarded to requests.Session.get.

        Returns:
            Parsed JSON response body.

        Raises:
            AuthenticationError: On HTTP 401 or 403.
            ProviderAPIError: On any other non-2xx response or network error.
        """
        url = f"{self._api_base}{path}"
        try:
            resp = self._session.get(url, **kwargs)
        except requests.RequestException as exc:
            raise ProviderAPIError(f"GitHub GET {path} failed: {exc}") from exc
        _raise_for_status(resp, path)
        return resp.json()

    def _post(self, path: str, payload: dict[str, Any]) -> Any:
        """
        Perform a POST request against the GitHub API.

        Args:
            path: API path.
            payload: Request body serialised as JSON.

        Returns:
            Parsed JSON response body.

        Raises:
            AuthenticationError: On HTTP 401 or 403.
            ProviderAPIError: On any other non-2xx response or network error.
        """
        url = f"{self._api_base}{path}"
        try:
            resp = self._session.post(url, json=payload)
        except requests.RequestException as exc:
            raise ProviderAPIError(f"GitHub POST {path} failed: {exc}") from exc
        _raise_for_status(resp, path)
        return resp.json()

    # ------------------------------------------------------------------
    # Branch protection
    # ------------------------------------------------------------------

    def is_branch_protected(self, repo: str, branch: str) -> bool:
        """
        Return True if *branch* is protected on GitHub.

        Hits GET /repos/{repo}/branches/{branch} and inspects the
        "protected" field.  The orchestrator owns cache TTL logic; this
        method always makes a live API call.

        Args:
            repo: "owner/repo" identifier, e.g. "joshmrtn/MatrixMouse".
            branch: Branch name to check.

        Returns:
            True if the branch is marked protected, False otherwise.

        Raises:
            AuthenticationError: On HTTP 401 or 403.
            ProviderAPIError: On API or network failure.
        """
        data = self._get(f"/repos/{repo}/branches/{branch}")
        return bool(data.get("protected", False))

    # ------------------------------------------------------------------
    # Pull requests
    # ------------------------------------------------------------------

    def create_pull_request(
        self,
        repo: str,
        head: str,
        base: str,
        title: str,
        body: str,
    ) -> str:
        """
        Open a pull request and return its web URL.

        Args:
            repo: "owner/repo" identifier.
            head: Source branch (the task branch).
            base: Target branch (the protected branch).
            title: PR title.
            body: PR description.

        Returns:
            Canonical web URL of the created PR,
            e.g. "https://github.com/owner/repo/pull/42".

        Raises:
            AuthenticationError: On HTTP 401 or 403.
            ProviderAPIError: On API or network failure, or if the
                response does not contain an html_url field.
        """
        data = self._post(
            f"/repos/{repo}/pulls",
            {"title": title, "body": body, "head": head, "base": base},
        )
        pr_url: str | None = data.get("html_url")
        if not pr_url:
            raise ProviderAPIError(
                f"GitHub create PR response missing html_url: {data}"
            )
        return pr_url

    def get_pr_state(self, repo: str, pr_url: str) -> str:
        """
        Return the current state of a pull request as a PRState string value.

        Maps GitHub's state + merged flag to MatrixMouse PRState values:
            open   → "open"
            closed + merged → "merged"
            closed + not merged → "closed"
            anything else → ""

        Args:
            repo: "owner/repo" identifier.
            pr_url: Canonical PR URL as stored in task.pr_url.

        Returns:
            One of "open", "merged", "closed", or "" (unknown).

        Raises:
            AuthenticationError: On HTTP 401 or 403.
            ProviderAPIError: On API or network failure.
        """
        pr_number = _pr_number_from_url(pr_url)
        data = self._get(f"/repos/{repo}/pulls/{pr_number}")
        state: str = data.get("state", "")
        merged: bool = bool(data.get("merged", False))

        if state == "open":
            return "open"
        if state == "closed" and merged:
            return "merged"
        if state == "closed":
            return "closed"
        return ""

    def get_pr_feedback(self, repo: str, pr_url: str) -> str:
        """
        Return formatted review feedback for a pull request.

        Fetches all submitted reviews and their inline comments from the
        GitHub API, then formats them into a model-readable string ready
        for injection into an agent's context_messages.

        Each review is rendered as::

            Review by <author> (<STATE>):

            <file.py>:
              <line> | <source line>
                     ^ [<tag>]: <comment>

            General comments:
              <review body>

        <STATE> is the reviewer's explicit submission choice as returned
        by the GitHub API: APPROVED, CHANGES_REQUESTED, or COMMENTED.
        It is not derived from the content of inline comments.

        <tag> is one of:
            [Comment]    — plain line comment, no replacement proposed
            [Suggestion] — reviewer proposed an exact replacement,
                           rendered as a unified diff so the agent can
                           apply it directly

        When a comment spans multiple lines, <line> is rendered as a
        range: "42-47 | <last line of selection>".  Multiple comments
        on the same line appear as consecutive caret lines under the
        same file block.

        Multiple reviews are separated by a blank line.  Returns an empty
        string if there are no reviews.

        Args:
            repo: "owner/repo" identifier.
            pr_url: Canonical PR URL as stored in task.pr_url.

        Returns:
            Formatted feedback string, or "" if no reviews exist.

        Raises:
            AuthenticationError: On HTTP 401 or 403.
            ProviderAPIError: On API or network failure.
        """
        pr_number = _pr_number_from_url(pr_url)

        reviews = self._get(f"/repos/{repo}/pulls/{pr_number}/reviews")
        # Inline comments keyed by review id for joining
        inline_comments = self._get(
            f"/repos/{repo}/pulls/{pr_number}/comments"
        )

        # Index all comments by id for reply lookup.
        comments_by_id: dict[int, dict[str, Any]] = {
            c["id"]: c for c in inline_comments if "id" in c
        }

        # Group top-level inline comments by review_id → file.
        # Replies (in_reply_to_id set) are attached to their parent comment
        # rather than listed separately, preserving the full thread context.
        by_review: dict[int, dict[str, list[dict[str, Any]]]] = {}
        for comment in inline_comments:
            if comment.get("in_reply_to_id"):
                # Reply — attach to parent's "_replies" list
                parent = comments_by_id.get(comment["in_reply_to_id"])
                if parent is not None:
                    parent.setdefault("_replies", []).append(comment)
                continue
            review_id: int = comment.get("pull_request_review_id") or 0
            path: str = comment.get("path", "")
            by_review.setdefault(review_id, {}).setdefault(path, []).append(comment)

        blocks: list[str] = []
        for review in reviews:
            # GitHub emits PENDING reviews for the author's own drafts;
            # skip them — they have not been submitted.
            if review.get("state") == "PENDING":
                continue

            block = _format_review(review, by_review.get(review["id"], {}))
            if block:
                blocks.append(block)

        return "\n\n".join(blocks)


# ---------------------------------------------------------------------------
# Module-level helpers (not part of the public interface)
# ---------------------------------------------------------------------------


def _raise_for_status(resp: requests.Response, path: str) -> None:
    """
    Raise the appropriate GitRemoteError for a non-2xx response.

    Args:
        resp: The requests.Response to inspect.
        path: API path, included in error messages for context.

    Raises:
        AuthenticationError: On HTTP 401 or 403.
        ProviderAPIError: On any other non-2xx status.
    """
    if resp.status_code in (401, 403):
        raise AuthenticationError(
            f"GitHub {path} returned {resp.status_code}: check GITHUB_TOKEN"
        )
    if not resp.ok:
        raise ProviderAPIError(
            f"GitHub {path} returned {resp.status_code}: {resp.text[:200]}"
        )


def _pr_number_from_url(pr_url: str) -> int:
    """
    Extract the PR number from a GitHub PR URL.

    Args:
        pr_url: e.g. "https://github.com/owner/repo/pull/42"

    Returns:
        The integer PR number.

    Raises:
        ProviderAPIError: If the URL does not end with a valid PR number.
    """
    parts = pr_url.rstrip("/").split("/")
    try:
        return int(parts[-1])
    except (ValueError, IndexError) as exc:
        raise ProviderAPIError(
            f"Cannot extract PR number from URL: {pr_url!r}"
        ) from exc


def _format_review(
    review: dict[str, Any],
    inline_by_file: dict[str, list[dict[str, Any]]],
) -> str:
    """
    Format a single review dict into the canonical feedback string.

    Args:
        review: GitHub review object from the /reviews endpoint.
        inline_by_file: Inline comments for this review, keyed by file path.

    Returns:
        Formatted review block string, or "" if the review has no
        content worth emitting (e.g. a bare APPROVED with no body).
    """
    author: str = review.get("user", {}).get("login", "unknown")
    state: str = review.get("state", "")
    body: str = (review.get("body") or "").strip()

    lines: list[str] = [f"Review by {author} ({state}):"]
    has_content = False

    # Inline comments grouped by file
    for file_path, comments in sorted(inline_by_file.items()):
        lines.append(f"\n{file_path}:")
        for comment in comments:
            end_line: int = comment.get("original_line") or comment.get("line") or 0
            start_line: int = (
                comment.get("start_original_line")
                or comment.get("start_line")
                or end_line
            )
            line_label = (
                f"{start_line}-{end_line}" if start_line != end_line
                else str(end_line)
            )
            diff_hunk: str = comment.get("diff_hunk", "")
            source_line: str = _extract_source_line(diff_hunk)
            comment_body: str = (comment.get("body") or "").strip()

            tag, rendered_body = _classify_comment(comment_body)

            indent = "  "
            caret_pad = " " * (len(line_label) + 3)  # align ^ under |

            lines.append(f"{indent}{line_label} | {source_line}")
            lines.append(f"{indent}{caret_pad}^ [{tag}]: {rendered_body}")

            # Render reply thread collapsed under the parent comment
            for reply in comment.get("_replies", []):
                reply_author: str = reply.get("user", {}).get("login", "unknown")
                reply_body: str = (reply.get("body") or "").strip()
                lines.append(f"{indent}  > {reply_author}: {reply_body}")

            has_content = True

    # General review body
    if body:
        lines.append("\nGeneral comments:")
        for line in body.splitlines():
            lines.append(f"  {line}")
        has_content = True

    if not has_content:
        if state in ("APPROVED", "CHANGES_REQUESTED"):
            # Always emit the header for explicit review decisions even
            # when the reviewer left no written feedback.
            lines.append("  No comments.")
            return "\n".join(lines)
        # COMMENTED or DISMISSED with no body and no inline comments
        # adds no useful signal; drop it.
        return ""

    return "\n".join(lines)


def _extract_source_line(diff_hunk: str) -> str:
    """
    Extract the last added/context line from a GitHub diff hunk.

    GitHub provides the diff hunk surrounding the commented line.  The
    commented line is the last line of the hunk.

    Args:
        diff_hunk: Raw unified diff hunk string from GitHub.

    Returns:
        The source line text, stripped of leading diff sigils (+/-/ ).
        Returns "" if the hunk is empty or cannot be parsed.
    """
    if not diff_hunk:
        return ""
    last_line = diff_hunk.splitlines()[-1]
    # Strip leading diff sigil (+, -, space) and any CR
    return last_line.lstrip("+-").lstrip(" ").rstrip("\r")


def _classify_comment(body: str) -> tuple[str, str]:
    """
    Classify a review comment body and return (tag, rendered_body).

    GitHub encodes reviewer suggestions as a fenced code block with the
    language identifier "suggestion".  Everything else is a plain comment;
    the review-level state (CHANGES_REQUESTED vs. COMMENTED) determines
    whether we tag it as a Change Request or a Comment, but that
    distinction is on the review, not the individual comment.  At the
    comment level we only need to distinguish Suggestion from non-Suggestion
    because the tag on the review header already communicates intent.

    For suggestions, renders the replacement as a unified diff so the
    agent can see exactly what the reviewer proposes:

        [Suggestion]:
          - original line
          + suggested replacement

    Args:
        body: Raw comment body text.

    Returns:
        Tuple of (tag_string, rendered_body_string).
    """
    suggestion_match = _SUGGESTION_RE.search(body)
    if suggestion_match:
        suggested = suggestion_match.group(1).rstrip("\r\n")
        preamble = _SUGGESTION_RE.sub("", body).strip()
        diff_lines = [""]
        if preamble:
            diff_lines.append(f"  {preamble}")
        diff_lines.append(f"  + {suggested}")
        return "Suggestion", "\n".join(diff_lines)

    return "Comment", body
