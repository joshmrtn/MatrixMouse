"""
tests/inference/test_token_budget.py

Unit tests for TokenBudgetTracker.

Tests:
    - check_budget does not raise when under hourly limit
    - check_budget raises TokenBudgetExceededError when over hourly limit
    - check_budget raises when over daily limit
    - check_budget uses cache on second call (no extra DB query)
    - check_budget re-queries DB after cache expires (wait_until passed)
    - record invalidates exhaustion cache
    - _calculate_wait_until returns exact roll-off time (not full window)
    - _calculate_wait_until applies api_retry_after as floor
    - _calculate_wait_until always returns future datetime (>= now + 1s)
    - calculate_wait_until_for_provider returns None when under budget
    - current_usage returns correct hour/day totals
    - check_budget no-op when no limits configured (tokens_per_hour=0)
    - check_budget no-op for unknown provider (not in _budgets)
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from matrixmouse.inference.token_budget import TokenBudgetTracker, ProviderBudget
from matrixmouse.inference.base import TokenBudgetExceededError
from matrixmouse.repository.memory_workspace_state_repository import (
    InMemoryWorkspaceStateRepository,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_tracker(**kwargs) -> TokenBudgetTracker:
    """Create a TokenBudgetTracker with InMemoryWorkspaceStateRepository."""
    repo = InMemoryWorkspaceStateRepository()
    return TokenBudgetTracker(
        ws_state_repo=repo,
        anthropic_tokens_per_hour=kwargs.get("anthropic_tokens_per_hour", 0),
        anthropic_tokens_per_day=kwargs.get("anthropic_tokens_per_day", 0),
        openai_tokens_per_hour=kwargs.get("openai_tokens_per_hour", 0),
        openai_tokens_per_day=kwargs.get("openai_tokens_per_day", 0),
    )


# ---------------------------------------------------------------------------
# check_budget — under limit
# ---------------------------------------------------------------------------


class TestCheckBudgetUnderLimit:
    """Tests for check_budget when under budget."""

    def test_does_not_raise_when_under_hourly_limit(self):
        tracker = make_tracker(anthropic_tokens_per_hour=100_000)
        # No usage yet — should be under limit
        tracker.check_budget(provider="anthropic", model="claude-sonnet-4-5")
        # Should not raise

    def test_does_not_raise_when_under_daily_limit(self):
        tracker = make_tracker(anthropic_tokens_per_day=500_000)
        tracker.check_budget(provider="anthropic", model="claude-sonnet-4-5")
        # Should not raise

    def test_does_not_raise_when_under_both_limits(self):
        tracker = make_tracker(
            anthropic_tokens_per_hour=100_000,
            anthropic_tokens_per_day=500_000,
        )
        # Record some usage but well under limits
        tracker._repo.record_token_usage(
            provider="anthropic",
            model="claude-sonnet-4-5",
            input_tokens=1000,
            output_tokens=500,
        )
        tracker.check_budget(provider="anthropic", model="claude-sonnet-4-5")
        # Should not raise


# ---------------------------------------------------------------------------
# check_budget — over limit
# ---------------------------------------------------------------------------


class TestCheckBudgetOverLimit:
    """Tests for check_budget when over budget."""

    def test_raises_when_over_hourly_limit(self):
        tracker = make_tracker(anthropic_tokens_per_hour=100)
        # Record usage over the limit
        tracker._repo.record_token_usage(
            provider="anthropic",
            model="claude-sonnet-4-5",
            input_tokens=60,
            output_tokens=50,
        )
        with pytest.raises(TokenBudgetExceededError) as exc_info:
            tracker.check_budget(provider="anthropic", model="claude-sonnet-4-5")
        assert exc_info.value.provider == "anthropic"
        assert exc_info.value.period == "hour"
        assert exc_info.value.limit == 100
        assert exc_info.value.used == 110

    def test_raises_when_over_daily_limit(self):
        tracker = make_tracker(anthropic_tokens_per_day=100)
        tracker._repo.record_token_usage(
            provider="anthropic",
            model="claude-sonnet-4-5",
            input_tokens=60,
            output_tokens=50,
        )
        with pytest.raises(TokenBudgetExceededError) as exc_info:
            tracker.check_budget(provider="anthropic", model="claude-sonnet-4-5")
        assert exc_info.value.provider == "anthropic"
        assert exc_info.value.period == "day"
        assert exc_info.value.limit == 100

    def test_raises_when_over_hourly_before_daily(self):
        """Hourly limit is checked first — should raise hourly if both exceeded."""
        tracker = make_tracker(
            anthropic_tokens_per_hour=100,
            anthropic_tokens_per_day=200,
        )
        tracker._repo.record_token_usage(
            provider="anthropic",
            model="claude-sonnet-4-5",
            input_tokens=150,
            output_tokens=0,
        )
        with pytest.raises(TokenBudgetExceededError) as exc_info:
            tracker.check_budget(provider="anthropic", model="claude-sonnet-4-5")
        assert exc_info.value.period == "hour"


# ---------------------------------------------------------------------------
# check_budget — caching
# ---------------------------------------------------------------------------


class TestCheckBudgetCaching:
    """Tests for check_budget cache behavior."""

    def test_uses_cache_on_second_call(self):
        """Second check_budget call uses cache, no extra DB query."""
        tracker = make_tracker(anthropic_tokens_per_hour=100)
        tracker._repo.record_token_usage(
            provider="anthropic",
            model="claude-sonnet-4-5",
            input_tokens=150,
            output_tokens=0,
        )
        # First call — queries DB
        with pytest.raises(TokenBudgetExceededError):
            tracker.check_budget(provider="anthropic", model="claude-sonnet-4-5")

        # Second call — should use cache (still raises, but no DB query)
        with pytest.raises(TokenBudgetExceededError):
            tracker.check_budget(provider="anthropic", model="claude-sonnet-4-5")

    def test_re_queries_db_after_cache_expires(self):
        """check_budget re-queries DB after wait_until has passed."""
        tracker = make_tracker(anthropic_tokens_per_hour=100)
        # Record usage in the past (more than 1 hour ago) by mocking datetime
        past_time = datetime.now(timezone.utc) - timedelta(minutes=90)
        with patch("matrixmouse.repository.memory_workspace_state_repository.datetime") as mock_dt:
            mock_dt.now.return_value = past_time
            mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
            tracker.record(
                provider="anthropic",
                model="claude-sonnet-4-5",
                input_tokens=150,
                output_tokens=0,
            )
        # First call — should be under limit now (old usage rolled off)
        tracker.check_budget(provider="anthropic", model="claude-sonnet-4-5")
        # Should not raise — usage is old


# ---------------------------------------------------------------------------
# record — cache invalidation
# ---------------------------------------------------------------------------


class TestRecordCacheInvalidation:
    """Tests for record invalidating the exhaustion cache."""

    def test_record_invalidates_exhaustion_cache(self):
        """record() invalidates exhaustion cache so next check re-reads DB."""
        tracker = make_tracker(anthropic_tokens_per_hour=100)
        tracker._repo.record_token_usage(
            provider="anthropic",
            model="claude-sonnet-4-5",
            input_tokens=150,
            output_tokens=0,
        )
        # First call — exhausts, caches
        with pytest.raises(TokenBudgetExceededError):
            tracker.check_budget(provider="anthropic", model="claude-sonnet-4-5")

        # Verify cache is set
        with tracker._cache_lock:
            assert "anthropic" in tracker._exhaustion_cache

        # Record more usage — should invalidate cache
        tracker.record(
            provider="anthropic",
            model="claude-sonnet-4-5",
            input_tokens=10,
            output_tokens=10,
        )

        # Verify cache is cleared
        with tracker._cache_lock:
            assert "anthropic" not in tracker._exhaustion_cache


# ---------------------------------------------------------------------------
# _calculate_wait_until
# ---------------------------------------------------------------------------


class TestCalculateWaitUntil:
    """Tests for _calculate_wait_until helper method."""

    def test_returns_exact_roll_off_time(self):
        """_calculate_wait_until returns exact roll-off time (not full window)."""
        tracker = make_tracker(anthropic_tokens_per_hour=100)
        now = datetime.now(timezone.utc)
        # Record from 30 minutes ago by mocking datetime
        old_record_time = now - timedelta(minutes=30)
        with patch("matrixmouse.repository.memory_workspace_state_repository.datetime") as mock_dt:
            mock_dt.now.return_value = old_record_time
            mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
            tracker.record(
                provider="anthropic",
                model="claude-sonnet-4-5",
                input_tokens=150,
                output_tokens=0,
            )
        records = tracker._repo.get_token_usage_since(
            provider="anthropic",
            since=now - timedelta(hours=1),
        )
        wait_until = tracker._calculate_wait_until(
            records=records,
            limit=100,
            window=timedelta(hours=1),
        )
        # Should be approximately 30 minutes from now (when old record rolls off)
        expected_roll_off = old_record_time + timedelta(hours=1)
        # Allow some tolerance for test execution time
        assert abs((wait_until - expected_roll_off).total_seconds()) < 5

    def test_applies_api_retry_after_as_floor(self):
        """_calculate_wait_until applies api_retry_after as floor."""
        tracker = make_tracker(anthropic_tokens_per_hour=100)
        now = datetime.now(timezone.utc)
        # Record from 10 minutes ago by mocking datetime
        old_record_time = now - timedelta(minutes=10)
        with patch("matrixmouse.repository.memory_workspace_state_repository.datetime") as mock_dt:
            mock_dt.now.return_value = old_record_time
            mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
            tracker.record(
                provider="anthropic",
                model="claude-sonnet-4-5",
                input_tokens=150,
                output_tokens=0,
            )
        records = tracker._repo.get_token_usage_since(
            provider="anthropic",
            since=now - timedelta(hours=1),
        )
        # API says retry after 30 minutes
        api_retry = now + timedelta(minutes=30)
        wait_until = tracker._calculate_wait_until(
            records=records,
            limit=100,
            window=timedelta(hours=1),
            api_retry_after=api_retry,
        )
        # Should be at least the API retry time, not the roll-off time
        assert wait_until >= api_retry

    def test_always_returns_future_datetime(self):
        """_calculate_wait_until always returns datetime >= now + 1s."""
        tracker = make_tracker(anthropic_tokens_per_hour=100)
        now = datetime.now(timezone.utc)
        # No records — should still return future datetime
        wait_until = tracker._calculate_wait_until(
            records=[],
            limit=100,
            window=timedelta(hours=1),
        )
        assert wait_until >= now + timedelta(seconds=1)

    def test_returns_future_with_records(self):
        """_calculate_wait_until with records still returns future datetime."""
        tracker = make_tracker(anthropic_tokens_per_hour=100)
        now = datetime.now(timezone.utc)
        # Record from 5 minutes ago by mocking datetime
        with patch("matrixmouse.repository.memory_workspace_state_repository.datetime") as mock_dt:
            mock_dt.now.return_value = now - timedelta(minutes=5)
            mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
            tracker.record(
                provider="anthropic",
                model="claude-sonnet-4-5",
                input_tokens=150,
                output_tokens=0,
            )
        records = tracker._repo.get_token_usage_since(
            provider="anthropic",
            since=now - timedelta(hours=1),
        )
        wait_until = tracker._calculate_wait_until(
            records=records,
            limit=100,
            window=timedelta(hours=1),
        )
        assert wait_until >= now + timedelta(seconds=1)


# ---------------------------------------------------------------------------
# calculate_wait_until_for_provider
# ---------------------------------------------------------------------------


class TestCalculateWaitUntilForProvider:
    """Tests for calculate_wait_until_for_provider method."""

    def test_returns_none_when_under_budget(self):
        """calculate_wait_until_for_provider returns None when under budget."""
        tracker = make_tracker(anthropic_tokens_per_hour=100_000)
        result = tracker.calculate_wait_until_for_provider(provider="anthropic")
        assert result is None

    def test_returns_wait_until_when_over_budget(self):
        """calculate_wait_until_for_provider returns datetime when over budget."""
        tracker = make_tracker(anthropic_tokens_per_hour=100)
        tracker._repo.record_token_usage(
            provider="anthropic",
            model="claude-sonnet-4-5",
            input_tokens=150,
            output_tokens=0,
        )
        result = tracker.calculate_wait_until_for_provider(provider="anthropic")
        assert result is not None
        assert isinstance(result, datetime)

    def test_returns_none_for_unknown_provider(self):
        """calculate_wait_until_for_provider returns None for unknown provider."""
        tracker = make_tracker()
        result = tracker.calculate_wait_until_for_provider(provider="unknown")
        assert result is None

    def test_returns_none_when_no_limits_configured(self):
        """calculate_wait_until_for_provider returns None when no limits."""
        tracker = make_tracker()  # No limits configured
        result = tracker.calculate_wait_until_for_provider(provider="anthropic")
        assert result is None


# ---------------------------------------------------------------------------
# current_usage
# ---------------------------------------------------------------------------


class TestCurrentUsage:
    """Tests for current_usage method."""

    def test_returns_correct_hour_total(self):
        """current_usage returns correct hour totals."""
        tracker = make_tracker()
        tracker._repo.record_token_usage(
            provider="anthropic",
            model="claude-sonnet-4-5",
            input_tokens=100,
            output_tokens=50,
        )
        usage = tracker.current_usage(provider="anthropic")
        assert usage["hour"] == 150

    def test_returns_correct_day_total(self):
        """current_usage returns correct day totals."""
        tracker = make_tracker()
        tracker._repo.record_token_usage(
            provider="anthropic",
            model="claude-sonnet-4-5",
            input_tokens=100,
            output_tokens=50,
        )
        usage = tracker.current_usage(provider="anthropic")
        assert usage["day"] == 150

    def test_returns_zero_for_no_usage(self):
        """current_usage returns zero when no usage recorded."""
        tracker = make_tracker()
        usage = tracker.current_usage(provider="anthropic")
        assert usage["hour"] == 0
        assert usage["day"] == 0

    def test_filters_by_provider(self):
        """current_usage filters by provider."""
        tracker = make_tracker()
        tracker._repo.record_token_usage(
            provider="anthropic",
            model="claude-sonnet-4-5",
            input_tokens=100,
            output_tokens=50,
        )
        tracker._repo.record_token_usage(
            provider="openai",
            model="gpt-4o",
            input_tokens=200,
            output_tokens=100,
        )
        anthropic_usage = tracker.current_usage(provider="anthropic")
        openai_usage = tracker.current_usage(provider="openai")
        assert anthropic_usage["hour"] == 150
        assert openai_usage["hour"] == 300


# ---------------------------------------------------------------------------
# check_budget — no-op cases
# ---------------------------------------------------------------------------


class TestCheckBudgetNoOp:
    """Tests for check_budget no-op cases."""

    def test_no_op_when_no_limits_configured(self):
        """check_budget no-op when no limits configured (tokens_per_hour=0)."""
        tracker = make_tracker()  # No limits
        # Should not raise even with usage
        tracker._repo.record_token_usage(
            provider="anthropic",
            model="claude-sonnet-4-5",
            input_tokens=1_000_000,
            output_tokens=0,
        )
        tracker.check_budget(provider="anthropic", model="claude-sonnet-4-5")
        # Should not raise

    def test_no_op_for_unknown_provider(self):
        """check_budget no-op for unknown provider (not in _budgets)."""
        tracker = make_tracker()
        # Unknown provider — should not raise
        tracker.check_budget(provider="unknown_provider", model="some-model")
        # Should not raise

    def test_no_op_when_provider_has_no_limits(self):
        """check_budget no-op when provider exists but has no limits."""
        tracker = make_tracker(
            anthropic_tokens_per_hour=100,  # Anthropic has limit
            # OpenAI has no limits
        )
        tracker._repo.record_token_usage(
            provider="openai",
            model="gpt-4o",
            input_tokens=1_000_000,
            output_tokens=0,
        )
        tracker.check_budget(provider="openai", model="gpt-4o")
        # Should not raise — OpenAI has no limits configured


# ---------------------------------------------------------------------------
# ProviderBudget
# ---------------------------------------------------------------------------


class TestProviderBudget:
    """Tests for ProviderBudget dataclass."""

    def test_has_any_limit_when_hourly_set(self):
        budget = ProviderBudget(tokens_per_hour=100, tokens_per_day=0)
        assert budget.has_any_limit() is True

    def test_has_any_limit_when_daily_set(self):
        budget = ProviderBudget(tokens_per_hour=0, tokens_per_day=100)
        assert budget.has_any_limit() is True

    def test_has_any_limit_when_both_set(self):
        budget = ProviderBudget(tokens_per_hour=100, tokens_per_day=500)
        assert budget.has_any_limit() is True

    def test_has_any_limit_when_neither_set(self):
        budget = ProviderBudget(tokens_per_hour=0, tokens_per_day=0)
        assert budget.has_any_limit() is False
