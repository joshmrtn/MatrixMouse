"""
tests/git/conftest.py

Shared fixtures for git remote provider tests.

The ``all_providers`` fixture is parametrized over every concrete
GitRemoteProvider implementation.  Contract tests request it to run
automatically against all providers without modification.

Adding a new provider implementation:
    1. Import it here.
    2. Add a ``pytest.param`` entry to ``_PROVIDER_FACTORIES``.
    The contract tests in test_git_remote_provider_contract.py will
    pick it up automatically.
"""

import os
from collections.abc import Generator
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from matrixmouse.git.github_provider import GitHubProvider


# ---------------------------------------------------------------------------
# Provider factory registry
# ---------------------------------------------------------------------------
# Each entry is a (id_string, factory_fn) pair.  The factory receives a
# pre-configured requests.Session mock and returns a ready provider instance.
# ---------------------------------------------------------------------------

def _make_github(mock_session: MagicMock) -> GitHubProvider:
    provider = GitHubProvider(token="test-token")
    provider._session = mock_session
    return provider


_PROVIDER_FACTORIES: list[tuple[str, Any]] = [
    ("github", _make_github),
]


# ---------------------------------------------------------------------------
# HTTP mock helpers shared across test modules
# ---------------------------------------------------------------------------

def make_response(
    json_data: Any = None,
    status_code: int = 200,
    text: str = "",
) -> MagicMock:
    """
    Build a mock requests.Response with the given data.

    Args:
        json_data: Value returned by response.json().
        status_code: HTTP status code.
        text: Value of response.text (used in error messages).

    Returns:
        Configured MagicMock standing in for requests.Response.
    """
    resp = MagicMock()
    resp.status_code = status_code
    resp.ok = status_code < 400
    resp.json.return_value = json_data if json_data is not None else {}
    resp.text = text
    return resp


# ---------------------------------------------------------------------------
# Parametrized provider fixture
# ---------------------------------------------------------------------------

@pytest.fixture(
    params=[pytest.param(factory, id=name) for name, factory in _PROVIDER_FACTORIES]
)
def all_providers(request: pytest.FixtureRequest) -> tuple[Any, MagicMock]:
    """
    Yield (provider_instance, mock_session) for every registered provider.

    Contract tests should request this fixture.  The mock_session has
    .get and .post attributes that tests configure per-call using
    side_effect or return_value.

    Returns:
        Tuple of (provider, mock_session).
    """
    factory = request.param
    mock_session = MagicMock()
    provider = factory(mock_session)
    return provider, mock_session
