"""
tests/git/test_git_remote_provider_contract.py

Parametric contract tests for all GitRemoteProvider implementations.

Every test in this module runs against all providers registered in
conftest._PROVIDER_FACTORIES via the ``all_providers`` fixture.  Tests
assert only on the ABC contract — return types, exception types, and
invariants — not on provider-specific behaviour or HTTP details.

When a new provider is added, no changes are needed here.
"""

import pytest

from matrixmouse.git.git_remote_provider import (
    AuthenticationError,
    GitRemoteError,
    GitRemoteProvider,
    ProviderAPIError,
)

from tests.git.conftest import make_response


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REPO = "joshmrtn/MatrixMouse"
PR_URL = "https://github.com/joshmrtn/MatrixMouse/pull/42"
BRANCH = "main"


# ---------------------------------------------------------------------------
# ABC conformance
# ---------------------------------------------------------------------------

class TestABCConformance:
    def test_is_subclass_of_abc(self, all_providers):
        provider, _ = all_providers
        assert isinstance(provider, GitRemoteProvider)


# ---------------------------------------------------------------------------
# is_branch_protected
# ---------------------------------------------------------------------------

class TestIsBranchProtected:
    def test_returns_true_when_branch_is_protected(self, all_providers):
        provider, session = all_providers
        session.get.return_value = make_response({"protected": True})

        result = provider.is_branch_protected(REPO, BRANCH)

        assert result is True

    def test_returns_false_when_branch_is_not_protected(self, all_providers):
        provider, session = all_providers
        session.get.return_value = make_response({"protected": False})

        result = provider.is_branch_protected(REPO, BRANCH)

        assert result is False

    def test_returns_bool_not_truthy(self, all_providers):
        """Return value must be a strict bool, not a truthy/falsy value."""
        provider, session = all_providers
        session.get.return_value = make_response({"protected": True})

        result = provider.is_branch_protected(REPO, BRANCH)

        assert type(result) is bool

    def test_raises_authentication_error_on_401(self, all_providers):
        provider, session = all_providers
        session.get.return_value = make_response(status_code=401)

        with pytest.raises(AuthenticationError):
            provider.is_branch_protected(REPO, BRANCH)

    def test_raises_authentication_error_on_403(self, all_providers):
        provider, session = all_providers
        session.get.return_value = make_response(status_code=403)

        with pytest.raises(AuthenticationError):
            provider.is_branch_protected(REPO, BRANCH)

    def test_raises_provider_api_error_on_500(self, all_providers):
        provider, session = all_providers
        session.get.return_value = make_response(status_code=500, text="server error")

        with pytest.raises(ProviderAPIError):
            provider.is_branch_protected(REPO, BRANCH)

    def test_authentication_error_is_git_remote_error(self, all_providers):
        provider, session = all_providers
        session.get.return_value = make_response(status_code=401)

        with pytest.raises(GitRemoteError):
            provider.is_branch_protected(REPO, BRANCH)

    def test_provider_api_error_is_git_remote_error(self, all_providers):
        provider, session = all_providers
        session.get.return_value = make_response(status_code=500)

        with pytest.raises(GitRemoteError):
            provider.is_branch_protected(REPO, BRANCH)


# ---------------------------------------------------------------------------
# create_pull_request
# ---------------------------------------------------------------------------

class TestCreatePullRequest:
    def test_returns_string_url(self, all_providers):
        provider, session = all_providers
        session.post.return_value = make_response(
            {"html_url": "https://github.com/joshmrtn/MatrixMouse/pull/99"}
        )

        result = provider.create_pull_request(
            REPO, "mm/my-task", "main", "My task", "Description"
        )

        assert isinstance(result, str)

    def test_returned_url_is_nonempty(self, all_providers):
        provider, session = all_providers
        session.post.return_value = make_response(
            {"html_url": "https://github.com/joshmrtn/MatrixMouse/pull/99"}
        )

        result = provider.create_pull_request(
            REPO, "mm/my-task", "main", "My task", "Description"
        )

        assert result != ""

    def test_raises_authentication_error_on_401(self, all_providers):
        provider, session = all_providers
        session.post.return_value = make_response(status_code=401)

        with pytest.raises(AuthenticationError):
            provider.create_pull_request(
                REPO, "mm/my-task", "main", "My task", "Description"
            )

    def test_raises_provider_api_error_on_500(self, all_providers):
        provider, session = all_providers
        session.post.return_value = make_response(status_code=500)

        with pytest.raises(ProviderAPIError):
            provider.create_pull_request(
                REPO, "mm/my-task", "main", "My task", "Description"
            )

    def test_raises_provider_api_error_when_url_missing(self, all_providers):
        provider, session = all_providers
        # Response is 2xx but html_url is absent
        session.post.return_value = make_response({"number": 99})

        with pytest.raises(ProviderAPIError):
            provider.create_pull_request(
                REPO, "mm/my-task", "main", "My task", "Description"
            )


# ---------------------------------------------------------------------------
# get_pr_state
# ---------------------------------------------------------------------------

class TestGetPrState:
    _VALID_STATES = {"open", "merged", "closed", ""}

    def test_returns_string(self, all_providers):
        provider, session = all_providers
        session.get.return_value = make_response({"state": "open", "merged": False})

        result = provider.get_pr_state(REPO, PR_URL)

        assert isinstance(result, str)

    def test_open_pr_returns_open(self, all_providers):
        provider, session = all_providers
        session.get.return_value = make_response({"state": "open", "merged": False})

        assert provider.get_pr_state(REPO, PR_URL) == "open"

    def test_merged_pr_returns_merged(self, all_providers):
        provider, session = all_providers
        session.get.return_value = make_response({"state": "closed", "merged": True})

        assert provider.get_pr_state(REPO, PR_URL) == "merged"

    def test_closed_pr_returns_closed(self, all_providers):
        provider, session = all_providers
        session.get.return_value = make_response({"state": "closed", "merged": False})

        assert provider.get_pr_state(REPO, PR_URL) == "closed"

    def test_returns_value_in_valid_set(self, all_providers):
        provider, session = all_providers
        session.get.return_value = make_response({"state": "open", "merged": False})

        result = provider.get_pr_state(REPO, PR_URL)

        assert result in self._VALID_STATES

    def test_raises_authentication_error_on_403(self, all_providers):
        provider, session = all_providers
        session.get.return_value = make_response(status_code=403)

        with pytest.raises(AuthenticationError):
            provider.get_pr_state(REPO, PR_URL)

    def test_raises_provider_api_error_on_404(self, all_providers):
        provider, session = all_providers
        session.get.return_value = make_response(status_code=404)

        with pytest.raises(ProviderAPIError):
            provider.get_pr_state(REPO, PR_URL)


# ---------------------------------------------------------------------------
# get_pr_feedback
# ---------------------------------------------------------------------------

class TestGetPrFeedback:
    def test_returns_string(self, all_providers):
        provider, session = all_providers
        session.get.side_effect = [
            make_response([]),  # reviews
            make_response([]),  # inline comments
        ]

        result = provider.get_pr_feedback(REPO, PR_URL)

        assert isinstance(result, str)

    def test_returns_empty_string_when_no_reviews(self, all_providers):
        provider, session = all_providers
        session.get.side_effect = [
            make_response([]),
            make_response([]),
        ]

        result = provider.get_pr_feedback(REPO, PR_URL)

        assert result == ""

    def test_nonempty_when_review_has_body(self, all_providers):
        provider, session = all_providers
        session.get.side_effect = [
            make_response([{
                "id": 1,
                "state": "CHANGES_REQUESTED",
                "body": "Please fix the encoding issue.",
                "user": {"login": "reviewer"},
            }]),
            make_response([]),
        ]

        result = provider.get_pr_feedback(REPO, PR_URL)

        assert result != ""

    def test_pending_reviews_excluded(self, all_providers):
        provider, session = all_providers
        session.get.side_effect = [
            make_response([{
                "id": 1,
                "state": "PENDING",
                "body": "Draft comment not submitted yet.",
                "user": {"login": "reviewer"},
            }]),
            make_response([]),
        ]

        result = provider.get_pr_feedback(REPO, PR_URL)

        assert result == ""

    def test_reviewer_name_present_in_output(self, all_providers):
        provider, session = all_providers
        session.get.side_effect = [
            make_response([{
                "id": 1,
                "state": "APPROVED",
                "body": "",
                "user": {"login": "joshmrtn"},
            }]),
            make_response([]),
        ]

        result = provider.get_pr_feedback(REPO, PR_URL)

        assert "joshmrtn" in result

    def test_review_state_present_in_output(self, all_providers):
        provider, session = all_providers
        session.get.side_effect = [
            make_response([{
                "id": 1,
                "state": "CHANGES_REQUESTED",
                "body": "Fix things.",
                "user": {"login": "reviewer"},
            }]),
            make_response([]),
        ]

        result = provider.get_pr_feedback(REPO, PR_URL)

        assert "CHANGES_REQUESTED" in result

    def test_raises_authentication_error_on_401(self, all_providers):
        provider, session = all_providers
        session.get.return_value = make_response(status_code=401)

        with pytest.raises(AuthenticationError):
            provider.get_pr_feedback(REPO, PR_URL)

    def test_raises_provider_api_error_on_500(self, all_providers):
        provider, session = all_providers
        session.get.return_value = make_response(status_code=500)

        with pytest.raises(ProviderAPIError):
            provider.get_pr_feedback(REPO, PR_URL)
            