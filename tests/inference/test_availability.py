"""
tests/inference/test_availability.py

Tests for BackendAvailabilityCache — Issue #32.

All tests use InMemoryWorkspaceStateRepository.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from matrixmouse.inference.availability import BackendAvailabilityCache
from matrixmouse.repository.memory_workspace_state_repository import (
    InMemoryWorkspaceStateRepository,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_cache(
    initial: int = 30,
    maximum: int = 600,
) -> tuple[BackendAvailabilityCache, InMemoryWorkspaceStateRepository]:
    """Create a fresh cache + repo pair."""
    repo = InMemoryWorkspaceStateRepository()
    cache = BackendAvailabilityCache(
        ws_state_repo=repo,
        initial_cooldown_seconds=initial,
        max_cooldown_seconds=maximum,
    )
    return cache, repo


# ---------------------------------------------------------------------------
# Basic availability
# ---------------------------------------------------------------------------

class TestAvailabilityBasic:
    def test_is_available_no_record(self):
        """True with no history."""
        cache, _ = make_cache()
        assert cache.is_available("anthropic") is True

    def test_is_available_during_cooldown(self):
        """Record failure, immediately check → False."""
        cache, _ = make_cache()
        cache.record_failure("anthropic")
        assert cache.is_available("anthropic") is False

    def test_is_available_after_cooldown_expires(self):
        """Mock datetime.now past cooldown_until → True."""
        cache, _ = make_cache()
        cache.record_failure("anthropic")
        # Move time far into the future
        with patch(
            "matrixmouse.inference.availability.datetime",
        ) as mock_dt:
            mock_dt.now.return_value = datetime.now(timezone.utc) + timedelta(hours=1)
            mock_dt.side_effect = lambda *a, **k: datetime(*a, **k)
            assert cache.is_available("anthropic") is True

    def test_record_success_clears_state(self):
        """Failures then success → is_available True, consecutive_failures 0."""
        cache, repo = make_cache()
        cache.record_failure("anthropic")
        assert cache.is_available("anthropic") is False
        cache.record_success("anthropic")
        assert cache.is_available("anthropic") is True
        record = repo.get("backend_availability:anthropic")
        assert record is not None
        assert record["consecutive_failures"] == 0

    def test_record_success_no_record_is_noop(self):
        """No exception when no record exists."""
        cache, _ = make_cache()
        cache.record_success("anthropic")  # should not raise
        assert cache.is_available("anthropic") is True


# ---------------------------------------------------------------------------
# Failure recording and backoff
# ---------------------------------------------------------------------------

class TestFailureRecording:
    def test_record_failure_first(self):
        """First failure: consecutive_failures=1, cooldown ~= initial."""
        cache, repo = make_cache(initial=30)
        cache.record_failure("anthropic")
        record = repo.get("backend_availability:anthropic")
        assert record is not None
        assert record["consecutive_failures"] == 1
        assert record["cooldown_until"] is not None

    def test_record_failure_exponential_backoff(self):
        """Failures 1..5 produce 30, 60, 120, 240, 480s.
        Failure #6 would be 960 but is capped at 600s (max)."""
        cache, _ = make_cache(initial=30, maximum=600)
        base = datetime(2026, 4, 2, 0, 0, 0, tzinfo=timezone.utc)
        durations = []
        for i in range(1, 6):
            with patch(
                "matrixmouse.inference.availability.datetime",
            ) as mock_dt:
                mock_dt.now.return_value = base
                mock_dt.side_effect = lambda *a, **k: datetime(*a, **k)
                mock_dt.fromisoformat = datetime.fromisoformat
                cache.record_failure("anthropic")
            record = cache._repo.get("backend_availability:anthropic")
            cooldown_until = datetime.fromisoformat(record["cooldown_until"])
            durations.append((cooldown_until - base).total_seconds())

        expected = [30, 60, 120, 240, 480]
        for i, (actual, exp) in enumerate(zip(durations, expected), 1):
            assert actual == pytest.approx(exp, abs=2), (
                f"Failure #{i}: expected ~{exp}s, got {actual}s"
            )

    def test_record_failure_cap_does_not_exceed_max(self):
        """6 failures: 30*2^5=960, capped at 600s."""
        cache, _ = make_cache(initial=30, maximum=600)
        base = datetime(2026, 4, 2, 0, 0, 0, tzinfo=timezone.utc)
        for _ in range(6):
            with patch(
                "matrixmouse.inference.availability.datetime",
            ) as mock_dt:
                mock_dt.now.return_value = base
                mock_dt.side_effect = lambda *a, **k: datetime(*a, **k)
                mock_dt.fromisoformat = datetime.fromisoformat
                cache.record_failure("anthropic")
        record = cache._repo.get("backend_availability:anthropic")
        cooldown_until = datetime.fromisoformat(record["cooldown_until"])
        assert (cooldown_until - base).total_seconds() == pytest.approx(600, abs=2)

    def test_stale_cooldown_resets_before_increment(self):
        """Record 3 failures (long cooldown), mock time past cooldown_until,
        record another failure → consecutive_failures is 1 (reset to 0
        then incremented), not 4."""
        cache, _ = make_cache(initial=30, maximum=600)
        base = datetime(2026, 4, 2, 0, 0, 0, tzinfo=timezone.utc)

        # Record 3 failures → cooldown = 120s
        for _ in range(3):
            with patch(
                "matrixmouse.inference.availability.datetime",
            ) as mock_dt:
                mock_dt.now.return_value = base
                mock_dt.side_effect = lambda *a, **k: datetime(*a, **k)
                mock_dt.fromisoformat = datetime.fromisoformat
                cache.record_failure("anthropic")

        record = cache._repo.get("backend_availability:anthropic")
        cooldown_until = datetime.fromisoformat(record["cooldown_until"])

        # Move past the cooldown
        new_time = cooldown_until + timedelta(seconds=10)
        with patch(
            "matrixmouse.inference.availability.datetime",
        ) as mock_dt:
            mock_dt.now.return_value = new_time
            mock_dt.side_effect = lambda *a, **k: datetime(*a, **k)
            mock_dt.fromisoformat = datetime.fromisoformat
            cache.record_failure("anthropic")

        record = cache._repo.get("backend_availability:anthropic")
        assert record["consecutive_failures"] == 1


# ---------------------------------------------------------------------------
# earliest_available_at
# ---------------------------------------------------------------------------

class TestEarliestAvailable:
    def test_earliest_available_at_empty_list_returns_none(self):
        cache, _ = make_cache()
        assert cache.earliest_available_at([]) is None

    def test_earliest_available_at_any_available_returns_none(self):
        """One available, one not → None."""
        cache, _ = make_cache()
        cache.record_failure("anthropic")  # in cooldown
        assert cache.earliest_available_at(["anthropic", "openai"]) is None

    def test_earliest_available_at_all_in_cooldown_returns_minimum(self):
        """All backends in cooldown → return the earliest (minimum) time."""
        cache, _ = make_cache(initial=30, maximum=600)
        base = datetime(2026, 4, 2, 0, 0, 0, tzinfo=timezone.utc)

        # anthropic: 1 failure → 30s cooldown
        with patch(
            "matrixmouse.inference.availability.datetime",
        ) as mock_dt:
            mock_dt.now.return_value = base
            mock_dt.side_effect = lambda *a, **k: datetime(*a, **k)
            mock_dt.fromisoformat = datetime.fromisoformat
            cache.record_failure("anthropic")

        # openai: 2 failures → 60s cooldown
        with patch(
            "matrixmouse.inference.availability.datetime",
        ) as mock_dt:
            mock_dt.now.return_value = base
            mock_dt.side_effect = lambda *a, **k: datetime(*a, **k)
            mock_dt.fromisoformat = datetime.fromisoformat
            cache.record_failure("openai")
            cache.record_failure("openai")

        # Query with time still within cooldown
        with patch(
            "matrixmouse.inference.availability.datetime",
        ) as mock_dt:
            mock_dt.now.return_value = base + timedelta(seconds=10)
            mock_dt.side_effect = lambda *a, **k: datetime(*a, **k)
            mock_dt.fromisoformat = datetime.fromisoformat
            earliest = cache.earliest_available_at(["anthropic", "openai"])

        # anthropic has the shorter cooldown (30s vs 60s)
        assert earliest is not None
        earliest_dt = datetime.fromisoformat(earliest)
        # Should be ~30s after base
        assert (earliest_dt - base).total_seconds() == pytest.approx(30, abs=2)


# ---------------------------------------------------------------------------
# Backend independence
# ---------------------------------------------------------------------------

class TestBackendIndependence:
    def test_multiple_backends_independent(self):
        """Failure on 'anthropic' doesn't affect 'ollama'."""
        cache, _ = make_cache()
        cache.record_failure("anthropic")
        assert cache.is_available("anthropic") is False
        assert cache.is_available("ollama") is True

    def test_availability_cache_key_isolation(self):
        """Write a failure record for 'anthropic', confirm
        ws_state_repo.get('backend_availability:ollama') is None;
        tests that storage keys are properly namespaced."""
        cache, repo = make_cache()
        cache.record_failure("anthropic")
        assert repo.get("backend_availability:anthropic") is not None
        assert repo.get("backend_availability:ollama") is None


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

class TestPersistence:
    def test_persistence_across_instances(self):
        """Record failure, create new cache instance with same repo,
        is_available still False."""
        cache1, repo = make_cache()
        cache1.record_failure("anthropic")

        cache2 = BackendAvailabilityCache(
            ws_state_repo=repo,
            initial_cooldown_seconds=30,
            max_cooldown_seconds=600,
        )
        assert cache2.is_available("anthropic") is False

    def test_cooldown_cleared_after_success_across_instances(self):
        """Record 3 failures, record success, new instance shows available."""
        cache1, repo = make_cache()
        for _ in range(3):
            cache1.record_failure("anthropic")
        cache1.record_success("anthropic")

        cache2 = BackendAvailabilityCache(
            ws_state_repo=repo,
            initial_cooldown_seconds=30,
            max_cooldown_seconds=600,
        )
        assert cache2.is_available("anthropic") is True
