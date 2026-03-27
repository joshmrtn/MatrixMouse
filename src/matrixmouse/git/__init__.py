"""
matrixmouse/git/__init__.py

Git remote provider adapters.

Exports the ABC and exception hierarchy. Concrete implementations
(GitHubProvider, etc.) are imported directly from their modules to
avoid pulling in provider-specific dependencies at package import time.
"""

from matrixmouse.git.git_remote_provider import (
    GitRemoteProvider,
    GitRemoteError,
    AuthenticationError,
    ProviderAPIError,
)

__all__ = [
    "GitRemoteProvider",
    "GitRemoteError",
    "AuthenticationError",
    "ProviderAPIError",
]
