"""matrixmouse/inference/token_budget.py

Rolling-window token budget enforcement for remote inference providers.

TokenBudgetTracker is injected into remote LLM adapters (AnthropicBackend,
OpenAIBackend) and the orchestrator. It provides two services:

    1. Recording usage after each successful inference call.
    2. Checking whether a provider is within budget before a call starts,
       and raising TokenBudgetExceededError with a precise wait_until if not.

Rolling window
--------------
Budgets are enforced over a rolling window (not a calendar reset). An hourly
budget of 100k tokens means: the sum of tokens used in the last 60 minutes
must not exceed 100k. This is stricter than a calendar-hour reset but fairer
to long-running tasks that span hour boundaries.

Precise wait_until calculation
-------------------------------
Rather than "wait an hour/day," the tracker calculates the exact earliest
moment at which enough tokens will have rolled off the window to bring usage
below the budget limit. It walks through the usage records oldest-first,
subtracting each record's tokens from the running total until the total drops
below the limit. The timestamp at which that record rolls off the window is
the wait_until.

This means a task might only need to wait 3 minutes if most of the usage
was from a burst at the start of the window. The API's Retry-After header
(if present) is used as a floor: wait_until = max(calculated, api_retry_after).

Thread safety
-------------
TokenBudgetTracker is safe for concurrent use. All state is in the repository
layer (SQLite WAL mode, per-thread connections) or in a threading.Lock-
protected in-memory cache. The cache stores the last known exhaustion state
per provider to avoid redundant DB reads on every pre-call check.

Usage
-----
    tracker = TokenBudgetTracker(
        ws_state_repo=ws_state_repo,
        anthropic_tokens_per_hour=100_000,
        anthropic_tokens_per_day=500_000,
        openai_tokens_per_hour=100_000,
        openai_tokens_per_day=500_000,
    )

    # Before inference (upfront check):
    tracker.check_budget(provider="anthropic", model="claude-sonnet-4-5")
    # Raises TokenBudgetExceededError if over budget.

    # After successful inference:
    tracker.record(
        provider="anthropic",
        model="claude-sonnet-4-5",
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
    )
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from matrixmouse.inference.base import TokenBudgetExceededError

if TYPE_CHECKING:
    from matrixmouse.repository.workspace_state_repository import (
        WorkspaceStateRepository,
        TokenUsageRecord,
    )

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Budget configuration per provider
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ProviderBudget:
    """Token budget limits for a single provider.

    Attributes:
        tokens_per_hour: Maximum tokens (input + output) per rolling hour.
            0 means no hourly limit.
        tokens_per_day:  Maximum tokens (input + output) per rolling day.
            0 means no daily limit.
    """
    tokens_per_hour: int = 0
    tokens_per_day:  int = 0

    def has_any_limit(self) -> bool:
        """True if at least one limit is configured."""
        return self.tokens_per_hour > 0 or self.tokens_per_day > 0


# ---------------------------------------------------------------------------
# TokenBudgetTracker
# ---------------------------------------------------------------------------

class TokenBudgetTracker:
    """Rolling-window token budget tracker for remote inference providers.

    Injected into AnthropicBackend, OpenAIBackend, and the orchestrator.
    All state is persisted via WorkspaceStateRepository so budgets survive
    service restarts.

    Args:
        ws_state_repo:            Repository for persisting usage records.
        anthropic_tokens_per_hour: Hourly token budget for Anthropic. 0 = unlimited.
        anthropic_tokens_per_day:  Daily token budget for Anthropic. 0 = unlimited.
        openai_tokens_per_hour:    Hourly token budget for OpenAI. 0 = unlimited.
        openai_tokens_per_day:     Daily token budget for OpenAI. 0 = unlimited.
    """

    def __init__(
        self,
        ws_state_repo: WorkspaceStateRepository,
        anthropic_tokens_per_hour: int = 0,
        anthropic_tokens_per_day:  int = 0,
        openai_tokens_per_hour:    int = 0,
        openai_tokens_per_day:     int = 0,
    ) -> None:
        self._repo = ws_state_repo
        self._budgets: dict[str, ProviderBudget] = {
            "anthropic": ProviderBudget(
                tokens_per_hour=anthropic_tokens_per_hour,
                tokens_per_day=anthropic_tokens_per_day,
            ),
            "openai": ProviderBudget(
                tokens_per_hour=openai_tokens_per_hour,
                tokens_per_day=openai_tokens_per_day,
            ),
        }
        # Cache: provider → (is_exhausted, wait_until) — protected by lock.
        # Avoids a DB read on every pre-call check when we know the budget
        # is exhausted and wait_until hasn't passed yet.
        self._exhaustion_cache: dict[str, tuple[bool, datetime | None]] = {}
        self._cache_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def record(
        self,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        api_retry_after: datetime | None = None,
    ) -> None:
        """Record token usage after a successful inference call.

        Also clears the exhaustion cache entry for this provider so the
        next check_budget call re-evaluates from the DB.

        Args:
            provider:        Provider name, e.g. ``"anthropic"``.
            model:           Backend-local model identifier.
            input_tokens:    Prompt tokens consumed.
            output_tokens:   Completion tokens produced.
            api_retry_after: If the API indicated a rate limit alongside
                             the response, pass the reset datetime here.
                             Stored for use in wait_until calculation.
        """
        total = input_tokens + output_tokens
        if total <= 0:
            return

        self._repo.record_token_usage(
            provider=provider,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

        # Invalidate cache so the next check re-reads from DB
        with self._cache_lock:
            self._exhaustion_cache.pop(provider, None)

        logger.debug(
            "TokenBudgetTracker: recorded %d tokens for %s/%s.",
            total, provider, model,
        )

    def check_budget(
        self,
        provider: str,
        model: str,
        api_retry_after: datetime | None = None,
    ) -> None:
        """Check whether the provider is within budget.

        Raises TokenBudgetExceededError with a precise wait_until if the
        rolling-window usage exceeds any configured limit.

        Args:
            provider:        Provider name, e.g. ``"anthropic"``.
            model:           Backend-local model identifier (for error messages).
            api_retry_after: If the API has already indicated a reset time
                             (e.g. from a previous 429), pass it here as a
                             floor for the wait_until calculation.

        Raises:
            TokenBudgetExceededError: If any configured budget is exhausted.
        """
        budget = self._budgets.get(provider)
        if budget is None or not budget.has_any_limit():
            return  # no limits configured for this provider

        # Fast path: check cache first
        with self._cache_lock:
            cached = self._exhaustion_cache.get(provider)
        if cached is not None:
            is_exhausted, cached_wait_until = cached
            if is_exhausted:
                now = datetime.now(timezone.utc)
                if cached_wait_until is None or cached_wait_until > now:
                    # Still exhausted per cache
                    self._raise_exceeded(
                        provider=provider,
                        model=model,
                        budget=budget,
                        wait_until=cached_wait_until,
                        api_retry_after=api_retry_after,
                    )
                else:
                    # Cache says exhausted but wait_until has passed — re-check DB
                    with self._cache_lock:
                        self._exhaustion_cache.pop(provider, None)

        # Slow path: query DB and evaluate both windows
        now = datetime.now(timezone.utc)
        exceeded_period: str | None = None
        exceeded_limit:  int = 0
        exceeded_used:   int = 0
        wait_until:      datetime | None = None

        if budget.tokens_per_hour > 0:
            window_start = now - timedelta(hours=1)
            records = self._repo.get_token_usage_since(provider, window_start)
            used = sum(r.input_tokens + r.output_tokens for r in records)
            if used >= budget.tokens_per_hour:
                exceeded_period = "hour"
                exceeded_limit  = budget.tokens_per_hour
                exceeded_used   = used
                wait_until = self._calculate_wait_until(
                    records=records,
                    limit=budget.tokens_per_hour,
                    window=timedelta(hours=1),
                    api_retry_after=api_retry_after,
                )

        if exceeded_period is None and budget.tokens_per_day > 0:
            window_start = now - timedelta(days=1)
            records = self._repo.get_token_usage_since(provider, window_start)
            used = sum(r.input_tokens + r.output_tokens for r in records)
            if used >= budget.tokens_per_day:
                exceeded_period = "day"
                exceeded_limit  = budget.tokens_per_day
                exceeded_used   = used
                wait_until = self._calculate_wait_until(
                    records=records,
                    limit=budget.tokens_per_day,
                    window=timedelta(days=1),
                    api_retry_after=api_retry_after,
                )

        if exceeded_period is not None:
            # Update cache
            with self._cache_lock:
                self._exhaustion_cache[provider] = (True, wait_until)
            self._raise_exceeded(
                provider=provider,
                model=model,
                budget=budget,
                wait_until=wait_until,
                api_retry_after=api_retry_after,
                period=exceeded_period,
                limit=exceeded_limit,
                used=exceeded_used,
            )

        # Within budget — cache as not exhausted (short TTL: don't cache
        # "OK" state; just clear any stale exhaustion entry)
        with self._cache_lock:
            self._exhaustion_cache.pop(provider, None)

    def current_usage(
        self,
        provider: str,
    ) -> dict[str, int]:
        """Return current rolling-window usage totals for a provider.

        Useful for the web UI's usage metrics dashboard and for logging.

        Args:
            provider: Provider name, e.g. ``"anthropic"``.

        Returns:
            Dict with keys ``"hour"`` and ``"day"`` containing total tokens
            (input + output) used in each rolling window.
        """
        now = datetime.now(timezone.utc)

        hour_records = self._repo.get_token_usage_since(
            provider, now - timedelta(hours=1)
        )
        day_records = self._repo.get_token_usage_since(
            provider, now - timedelta(days=1)
        )

        return {
            "hour": sum(r.input_tokens + r.output_tokens for r in hour_records),
            "day":  sum(r.input_tokens + r.output_tokens for r in day_records),
        }

    def calculate_wait_until_for_provider(
        self,
        provider: str,
        api_retry_after: datetime | None = None,
    ) -> datetime | None:
        """Calculate the earliest time the provider's budget will be available.

        Returns None if the provider is currently within budget (no wait
        needed) or if no limits are configured.

        Called by the orchestrator when setting task.wait_until after catching
        TokenBudgetExceededError.

        Args:
            provider:        Provider name.
            api_retry_after: API-supplied reset time floor.

        Returns:
            Earliest datetime at which the provider will be under budget,
            or None if no wait is needed.
        """
        budget = self._budgets.get(provider)
        if budget is None or not budget.has_any_limit():
            return None

        now = datetime.now(timezone.utc)
        wait_until: datetime | None = None

        if budget.tokens_per_hour > 0:
            records = self._repo.get_token_usage_since(
                provider, now - timedelta(hours=1)
            )
            used = sum(r.input_tokens + r.output_tokens for r in records)
            if used >= budget.tokens_per_hour:
                wu = self._calculate_wait_until(
                    records=records,
                    limit=budget.tokens_per_hour,
                    window=timedelta(hours=1),
                    api_retry_after=api_retry_after,
                )
                if wu is not None:
                    wait_until = wu if wait_until is None else min(wait_until, wu)

        if budget.tokens_per_day > 0:
            records = self._repo.get_token_usage_since(
                provider, now - timedelta(days=1)
            )
            used = sum(r.input_tokens + r.output_tokens for r in records)
            if used >= budget.tokens_per_day:
                wu = self._calculate_wait_until(
                    records=records,
                    limit=budget.tokens_per_day,
                    window=timedelta(days=1),
                    api_retry_after=api_retry_after,
                )
                if wu is not None:
                    wait_until = wu if wait_until is None else max(wait_until, wu)

        return wait_until

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _calculate_wait_until(
        self,
        records: list,
        limit: int,
        window: timedelta,
        api_retry_after: datetime | None = None,
    ) -> datetime:
        """Calculate the earliest time usage will drop below limit.

        Walks through records oldest-first. For each record, subtracts its
        token count from the running total. When the total drops below limit,
        the wait_until is the timestamp at which that record rolls off the
        window (record.recorded_at + window).

        Args:
            records:         Usage records in the window, oldest first.
            limit:           Token budget limit.
            window:          Rolling window size (1 hour or 1 day).
            api_retry_after: API-supplied reset time; used as a floor.

        Returns:
            Earliest datetime at which usage will be under the limit.
            Always at least 1 second in the future.
        """
        now = datetime.now(timezone.utc)
        total = sum(r.input_tokens + r.output_tokens for r in records)

        calculated: datetime | None = None

        for record in records:
            total -= (record.input_tokens + record.output_tokens)
            if total < limit:
                # This record rolling off is the turning point
                roll_off = record.recorded_at + window
                calculated = roll_off
                break

        if calculated is None:
            # All records need to roll off — wait for the full window
            if records:
                calculated = records[0].recorded_at + window
            else:
                # No records but somehow over budget — safety net
                calculated = now + window

        # Apply API-supplied retry_after as a floor
        if api_retry_after is not None:
            calculated = max(calculated, api_retry_after)

        # Always at least 1 second in the future to prevent immediate retry
        min_future = now + timedelta(seconds=1)
        return max(calculated, min_future)

    def _raise_exceeded(
        self,
        provider: str,
        model: str,
        budget: ProviderBudget,
        wait_until: datetime | None,
        api_retry_after: datetime | None = None,
        period: str = "hour",
        limit: int = 0,
        used: int = 0,
    ) -> None:
        """Raise TokenBudgetExceededError with full diagnostic context.

        Args:
            provider:        Provider name.
            model:           Model identifier.
            budget:          ProviderBudget for this provider.
            wait_until:      Calculated earliest retry datetime.
            api_retry_after: API-supplied reset time (already folded into
                             wait_until but included for the error for logging).
            period:          ``"hour"`` or ``"day"``.
            limit:           The configured limit that was exceeded.
            used:            Tokens used in the window.
        """
        effective_limit = limit or (
            budget.tokens_per_hour if period == "hour"
            else budget.tokens_per_day
        )
        logger.warning(
            "TokenBudgetTracker: %s budget exhausted for %s/%s. "
            "Used %d/%d tokens in rolling %s window. "
            "Earliest retry: %s.",
            period, provider, model, used, effective_limit, period,
            wait_until.isoformat() if wait_until else "unknown",
        )
        raise TokenBudgetExceededError(
            provider=provider,
            period=period,
            limit=effective_limit,
            used=used,
            retry_after=wait_until,
        )
    