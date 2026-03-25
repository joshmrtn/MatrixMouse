"""
tests/git/test_github_provider.py

Unit tests for GitHubProvider implementation details.

These tests cover GitHub-specific behaviour: JSON shapes, feedback
formatting, suggestion rendering, reply threading, multi-line ranges,
helper functions, and exception mapping.  They complement the provider-
agnostic contract tests in test_git_remote_provider_contract.py.

All HTTP calls are intercepted via a mock requests.Session — no real
network calls are made.
"""

import os
from unittest.mock import MagicMock, patch

import pytest

from matrixmouse.git.git_remote_provider import AuthenticationError, ProviderAPIError
from matrixmouse.git.github_provider import (
    GitHubProvider,
    _classify_comment,
    _extract_source_line,
    _format_review,
    _pr_number_from_url,
    _raise_for_status,
)

from tests.git.conftest import make_response


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def session() -> MagicMock:
    return MagicMock()


@pytest.fixture
def provider(session: MagicMock) -> GitHubProvider:
    p = GitHubProvider(token="test-token")
    p._session = session
    return p


REPO = "joshmrtn/MatrixMouse"
PR_URL = "https://github.com/joshmrtn/MatrixMouse/pull/42"


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------

class TestConstructor:
    def test_uses_explicit_token(self):
        p = GitHubProvider(token="explicit-token")
        assert p._token == "explicit-token"

    def test_reads_token_from_env(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "env-token")
        p = GitHubProvider()
        assert p._token == "env-token"

    def test_empty_token_when_env_unset(self, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        p = GitHubProvider()
        assert p._token == ""

    def test_default_api_base(self):
        p = GitHubProvider(token="t")
        assert p._api_base == "https://api.github.com"

    def test_custom_api_base_trailing_slash_stripped(self):
        p = GitHubProvider(token="t", api_base="https://ghe.example.com/api/v3/")
        assert p._api_base == "https://ghe.example.com/api/v3"

    def test_auth_header_set(self):
        p = GitHubProvider(token="mytoken")
        assert p._session.headers["Authorization"] == "Bearer mytoken"

    def test_accept_header_set(self):
        p = GitHubProvider(token="t")
        assert "application/vnd.github+json" in str(p._session.headers["Accept"])


# ---------------------------------------------------------------------------
# _raise_for_status
# ---------------------------------------------------------------------------

class TestRaiseForStatus:
    def test_ok_response_does_not_raise(self):
        resp = make_response(status_code=200)
        _raise_for_status(resp, "/some/path")  # no exception

    def test_201_does_not_raise(self):
        resp = make_response(status_code=201)
        _raise_for_status(resp, "/some/path")

    def test_401_raises_authentication_error(self):
        resp = make_response(status_code=401)
        with pytest.raises(AuthenticationError):
            _raise_for_status(resp, "/repos/foo/bar")

    def test_403_raises_authentication_error(self):
        resp = make_response(status_code=403)
        with pytest.raises(AuthenticationError):
            _raise_for_status(resp, "/repos/foo/bar")

    def test_404_raises_provider_api_error(self):
        resp = make_response(status_code=404)
        with pytest.raises(ProviderAPIError):
            _raise_for_status(resp, "/repos/foo/bar")

    def test_500_raises_provider_api_error(self):
        resp = make_response(status_code=500, text="internal error")
        with pytest.raises(ProviderAPIError):
            _raise_for_status(resp, "/repos/foo/bar")

    def test_error_message_includes_path(self):
        resp = make_response(status_code=500, text="oops")
        with pytest.raises(ProviderAPIError, match="/repos/foo/bar"):
            _raise_for_status(resp, "/repos/foo/bar")

    def test_auth_error_message_mentions_token(self):
        resp = make_response(status_code=401)
        with pytest.raises(AuthenticationError, match="GITHUB_TOKEN"):
            _raise_for_status(resp, "/path")


# ---------------------------------------------------------------------------
# _pr_number_from_url
# ---------------------------------------------------------------------------

class TestPrNumberFromUrl:
    def test_extracts_number_from_standard_url(self):
        assert _pr_number_from_url("https://github.com/owner/repo/pull/42") == 42

    def test_extracts_number_with_trailing_slash(self):
        assert _pr_number_from_url("https://github.com/owner/repo/pull/7/") == 7

    def test_raises_on_non_numeric_suffix(self):
        with pytest.raises(ProviderAPIError):
            _pr_number_from_url("https://github.com/owner/repo/pull/abc")

    def test_raises_on_empty_string(self):
        with pytest.raises(ProviderAPIError):
            _pr_number_from_url("")


# ---------------------------------------------------------------------------
# _extract_source_line
# ---------------------------------------------------------------------------

class TestExtractSourceLine:
    def test_returns_last_line_of_hunk(self):
        hunk = "@@ -40,4 +40,4 @@\n context\n-old line\n+new line"
        assert _extract_source_line(hunk) == "new line"

    def test_strips_leading_plus_sigil(self):
        hunk = "@@ -1,1 +1,1 @@\n+with open(f) as fp:"
        assert _extract_source_line(hunk) == "with open(f) as fp:"

    def test_strips_leading_minus_sigil(self):
        hunk = "@@ -1,1 +1,1 @@\n-old code"
        assert _extract_source_line(hunk) == "old code"

    def test_strips_leading_space_sigil(self):
        hunk = "@@ -1,1 +1,1 @@\n context line"
        assert _extract_source_line(hunk) == "context line"

    def test_returns_empty_string_for_empty_hunk(self):
        assert _extract_source_line("") == ""


# ---------------------------------------------------------------------------
# _classify_comment
# ---------------------------------------------------------------------------

class TestClassifyComment:
    def test_plain_comment_tagged_as_comment(self):
        tag, _ = _classify_comment("add encoding='utf-8'")
        assert tag == "Comment"

    def test_plain_comment_body_preserved(self):
        body = "add encoding='utf-8'"
        _, rendered = _classify_comment(body)
        assert rendered == body

    def test_suggestion_fence_tagged_as_suggestion(self):
        body = "```suggestion\nwith open(f, encoding='utf-8') as fp:\n```"
        tag, _ = _classify_comment(body)
        assert tag == "Suggestion"

    def test_suggestion_rendered_with_plus_prefix(self):
        body = "```suggestion\nwith open(f, encoding='utf-8') as fp:\n```"
        _, rendered = _classify_comment(body)
        assert "+ with open(f, encoding='utf-8') as fp:" in rendered

    def test_suggestion_preamble_included(self):
        body = "use utf-8 encoding\n```suggestion\nwith open(f, encoding='utf-8') as fp:\n```"
        _, rendered = _classify_comment(body)
        assert "use utf-8 encoding" in rendered

    def test_suggestion_no_minus_line(self):
        """Original line is already shown above the caret — no duplication."""
        body = "```suggestion\nreplacement\n```"
        _, rendered = _classify_comment(body)
        assert "- " not in rendered


# ---------------------------------------------------------------------------
# _format_review
# ---------------------------------------------------------------------------

class TestFormatReview:
    def _make_review(self, state="CHANGES_REQUESTED", body="", author="reviewer"):
        return {"id": 1, "state": state, "body": body, "user": {"login": author}}

    def _make_comment(
        self,
        path="foo.py",
        line=42,
        body="fix this",
        start_line=None,
        comment_id=10,
        reply_to=None,
    ):
        c = {
            "id": comment_id,
            "path": path,
            "original_line": line,
            "start_original_line": start_line,
            "diff_hunk": f"@@ -40,4 +40,4 @@\n+source line {line}",
            "body": body,
            "pull_request_review_id": 1,
        }
        if reply_to is not None:
            c["in_reply_to_id"] = reply_to
        return c

    def test_review_header_contains_author(self):
        review = self._make_review(author="joshmrtn")
        result = _format_review(review, {})
        assert "joshmrtn" in result

    def test_review_header_contains_state(self):
        review = self._make_review(state="CHANGES_REQUESTED")
        result = _format_review(review, {})
        assert "CHANGES_REQUESTED" in result

    def test_general_comment_body_included(self):
        review = self._make_review(body="Overall looks good.")
        result = _format_review(review, {})
        assert "Overall looks good." in result

    def test_general_comments_label_present(self):
        review = self._make_review(body="Some feedback.")
        result = _format_review(review, {})
        assert "General comments:" in result

    def test_approved_no_body_returns_no_comments(self):
        review = self._make_review(state="APPROVED", body="")
        result = _format_review(review, {})
        assert "No comments." in result

    def test_approved_no_body_is_not_empty(self):
        review = self._make_review(state="APPROVED", body="")
        result = _format_review(review, {})
        assert result != ""

    def test_commented_no_body_no_inline_returns_empty(self):
        """A COMMENTED review with nothing to show is dropped."""
        review = self._make_review(state="COMMENTED", body="")
        result = _format_review(review, {})
        assert result == ""

    def test_inline_comment_file_path_present(self):
        review = self._make_review()
        comment = self._make_comment(path="foo.py", line=42)
        result = _format_review(review, {"foo.py": [comment]})
        assert "foo.py" in result

    def test_inline_comment_line_number_present(self):
        review = self._make_review()
        comment = self._make_comment(line=42)
        result = _format_review(review, {"foo.py": [comment]})
        assert "42" in result

    def test_inline_comment_caret_present(self):
        review = self._make_review()
        comment = self._make_comment(line=42)
        result = _format_review(review, {"foo.py": [comment]})
        assert "^" in result

    def test_inline_comment_tag_present(self):
        review = self._make_review()
        comment = self._make_comment(body="fix encoding", line=42)
        result = _format_review(review, {"foo.py": [comment]})
        assert "[Comment]" in result

    def test_suggestion_tag_present(self):
        review = self._make_review()
        comment = self._make_comment(
            body="```suggestion\nwith open(f, encoding='utf-8') as fp:\n```",
            line=42,
        )
        result = _format_review(review, {"foo.py": [comment]})
        assert "[Suggestion]" in result

    def test_multi_line_range_rendered(self):
        review = self._make_review()
        comment = self._make_comment(line=47, start_line=42)
        result = _format_review(review, {"foo.py": [comment]})
        assert "42-47" in result

    def test_single_line_not_rendered_as_range(self):
        review = self._make_review()
        comment = self._make_comment(line=42, start_line=42)
        result = _format_review(review, {"foo.py": [comment]})
        assert "42-42" not in result
        assert "42" in result

    def test_multiple_inline_comments_same_file(self):
        review = self._make_review()
        c1 = self._make_comment(line=10, body="first", comment_id=1)
        c2 = self._make_comment(line=20, body="second", comment_id=2)
        result = _format_review(review, {"foo.py": [c1, c2]})
        assert "first" in result
        assert "second" in result

    def test_multiple_files_both_present(self):
        review = self._make_review()
        c1 = self._make_comment(path="foo.py", line=10, comment_id=1)
        c2 = self._make_comment(path="bar.py", line=20, comment_id=2)
        result = _format_review(
            review, {"foo.py": [c1], "bar.py": [c2]}
        )
        assert "foo.py" in result
        assert "bar.py" in result

    def test_reply_thread_rendered_under_parent(self):
        review = self._make_review()
        parent = self._make_comment(line=42, body="fix this", comment_id=10)
        parent["_replies"] = [
            {
                "id": 11,
                "user": {"login": "joshmrtn"},
                "body": "utf-8-sig might be better",
            },
            {
                "id": 12,
                "user": {"login": "reviewer2"},
                "body": "agreed",
            },
        ]
        result = _format_review(review, {"foo.py": [parent]})
        assert "> joshmrtn: utf-8-sig might be better" in result
        assert "> reviewer2: agreed" in result

    def test_reply_order_preserved(self):
        review = self._make_review()
        parent = self._make_comment(line=42, comment_id=10)
        parent["_replies"] = [
            {"id": 11, "user": {"login": "a"}, "body": "first reply"},
            {"id": 12, "user": {"login": "b"}, "body": "second reply"},
        ]
        result = _format_review(review, {"foo.py": [parent]})
        assert result.index("first reply") < result.index("second reply")


# ---------------------------------------------------------------------------
# get_pr_feedback — integration of helpers via provider
# ---------------------------------------------------------------------------

class TestGetPrFeedbackIntegration:
    """
    Tests that exercise get_pr_feedback end-to-end through the provider,
    verifying that the API calls are made correctly and results assembled.
    """

    def test_pending_review_excluded_from_output(self, provider, session):
        session.get.side_effect = [
            make_response([
                {"id": 1, "state": "PENDING", "body": "draft", "user": {"login": "r"}},
                {"id": 2, "state": "CHANGES_REQUESTED", "body": "real feedback", "user": {"login": "r"}},
            ]),
            make_response([]),
        ]
        result = provider.get_pr_feedback(REPO, PR_URL)
        assert "draft" not in result
        assert "real feedback" in result

    def test_reply_not_duplicated_as_top_level_comment(self, provider, session):
        """Replies must not appear both as a top-level comment and as a thread entry."""
        parent_comment = {
            "id": 10,
            "pull_request_review_id": 1,
            "path": "foo.py",
            "original_line": 42,
            "start_original_line": None,
            "diff_hunk": "@@ -40,4 +40,4 @@\n+source line",
            "body": "fix encoding",
            "in_reply_to_id": None,
        }
        reply_comment = {
            "id": 11,
            "pull_request_review_id": 1,
            "path": "foo.py",
            "original_line": 42,
            "start_original_line": None,
            "diff_hunk": "@@ -40,4 +40,4 @@\n+source line",
            "body": "utf-8-sig is better",
            "in_reply_to_id": 10,
        }
        session.get.side_effect = [
            make_response([
                {"id": 1, "state": "CHANGES_REQUESTED", "body": "", "user": {"login": "r"}},
            ]),
            make_response([parent_comment, reply_comment]),
        ]
        result = provider.get_pr_feedback(REPO, PR_URL)
        # Reply appears as thread entry (> prefix), not as a standalone caret line
        assert "utf-8-sig is better" in result
        assert result.count("^ [Comment]: utf-8-sig") == 0

    def test_multiple_reviews_separated_by_blank_line(self, provider, session):
        session.get.side_effect = [
            make_response([
                {"id": 1, "state": "CHANGES_REQUESTED", "body": "first review", "user": {"login": "r1"}},
                {"id": 2, "state": "APPROVED", "body": "", "user": {"login": "r2"}},
            ]),
            make_response([]),
        ]
        result = provider.get_pr_feedback(REPO, PR_URL)
        assert "\n\n" in result

    def test_two_api_calls_made(self, provider, session):
        """Exactly two GET calls: /reviews and /comments."""
        session.get.side_effect = [
            make_response([]),
            make_response([]),
        ]
        provider.get_pr_feedback(REPO, PR_URL)
        assert session.get.call_count == 2

    def test_reviews_endpoint_called(self, provider, session):
        session.get.side_effect = [
            make_response([]),
            make_response([]),
        ]
        provider.get_pr_feedback(REPO, PR_URL)
        first_call_url = session.get.call_args_list[0][0][0]
        assert "/pulls/42/reviews" in first_call_url

    def test_comments_endpoint_called(self, provider, session):
        session.get.side_effect = [
            make_response([]),
            make_response([]),
        ]
        provider.get_pr_feedback(REPO, PR_URL)
        second_call_url = session.get.call_args_list[1][0][0]
        assert "/pulls/42/comments" in second_call_url


# ---------------------------------------------------------------------------
# is_branch_protected — GitHub-specific
# ---------------------------------------------------------------------------

class TestIsBranchProtectedGitHub:
    def test_correct_endpoint_called(self, provider, session):
        session.get.return_value = make_response({"protected": True})
        provider.is_branch_protected(REPO, "main")
        url = session.get.call_args[0][0]
        assert "/repos/joshmrtn/MatrixMouse/branches/main" in url

    def test_missing_protected_field_returns_false(self, provider, session):
        session.get.return_value = make_response({})
        result = provider.is_branch_protected(REPO, "main")
        assert result is False


# ---------------------------------------------------------------------------
# create_pull_request — GitHub-specific
# ---------------------------------------------------------------------------

class TestCreatePullRequestGitHub:
    def test_correct_endpoint_called(self, provider, session):
        session.post.return_value = make_response(
            {"html_url": "https://github.com/joshmrtn/MatrixMouse/pull/1"}
        )
        provider.create_pull_request(REPO, "mm/task", "main", "Title", "Body")
        url = session.post.call_args[0][0]
        assert "/repos/joshmrtn/MatrixMouse/pulls" in url

    def test_payload_contains_head_and_base(self, provider, session):
        session.post.return_value = make_response(
            {"html_url": "https://github.com/joshmrtn/MatrixMouse/pull/1"}
        )
        provider.create_pull_request(REPO, "mm/task", "main", "Title", "Body")
        payload = session.post.call_args[1]["json"]
        assert payload["head"] == "mm/task"
        assert payload["base"] == "main"

    def test_payload_contains_title_and_body(self, provider, session):
        session.post.return_value = make_response(
            {"html_url": "https://github.com/joshmrtn/MatrixMouse/pull/1"}
        )
        provider.create_pull_request(REPO, "mm/task", "main", "My Title", "My Body")
        payload = session.post.call_args[1]["json"]
        assert payload["title"] == "My Title"
        assert payload["body"] == "My Body"

    def test_returns_html_url(self, provider, session):
        expected = "https://github.com/joshmrtn/MatrixMouse/pull/55"
        session.post.return_value = make_response({"html_url": expected})
        result = provider.create_pull_request(REPO, "mm/t", "main", "T", "B")
        assert result == expected


# ---------------------------------------------------------------------------
# get_pr_state — GitHub-specific state mapping
# ---------------------------------------------------------------------------

class TestGetPrStateGitHub:
    def test_unknown_state_returns_empty_string(self, provider, session):
        session.get.return_value = make_response({"state": "unknown_value", "merged": False})
        result = provider.get_pr_state(REPO, PR_URL)
        assert result == ""

    def test_correct_endpoint_called(self, provider, session):
        session.get.return_value = make_response({"state": "open", "merged": False})
        provider.get_pr_state(REPO, PR_URL)
        url = session.get.call_args[0][0]
        assert "/pulls/42" in url
