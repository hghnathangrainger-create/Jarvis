"""
cost_tracker.py

Cost tracking for the Jarvis AI Operating System.

Responsibilities:
    - Record every AI API call with provider, model, tokens, and cost.
    - Provide daily, monthly, and per-provider cost aggregation.
    - Support budget limits with over-budget detection.
    - Persist cost data to SQLite.

Does NOT:
    - Implement provider logic (see ai/providers/).
    - Implement routing logic (see ai/router.py).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

# Cost rates per 1M tokens (USD).
COST_RATES: dict[str, dict[str, float]] = {
    # Claude models
    "claude-sonnet-4-6": {"input": 3.0, "output": 15.0},
    "claude-3-5-sonnet": {"input": 3.0, "output": 15.0},
    "claude-3-haiku": {"input": 0.25, "output": 1.25},
    "claude-3-5-haiku": {"input": 0.80, "output": 4.0},
    # OpenAI models
    "gpt-4o": {"input": 2.50, "output": 10.0},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4-turbo": {"input": 10.0, "output": 30.0},
    # Gemini models
    "gemini-2.0-flash": {"input": 0.075, "output": 0.30},
    "gemini-1.5-pro": {"input": 1.25, "output": 5.0},
    "gemini-1.5-flash": {"input": 0.075, "output": 0.30},
    # Ollama (local) — always free
    "ollama": {"input": 0.0, "output": 0.0},
}


def estimate_cost(
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> float:
    """Estimate the cost of an API call.

    Args:
        provider: The provider name (e.g. "claude", "openai", "ollama").
        model: The model identifier.
        input_tokens: Number of input tokens.
        output_tokens: Number of output tokens.

    Returns:
        Estimated cost in USD.
    """
    # Ollama is always free.
    if provider == "ollama":
        return 0.0

    # Look up rates by model name (try exact match, then prefix match).
    rates = COST_RATES.get(model)
    if rates is None:
        # Try to match by prefix (e.g. "claude-sonnet-4-6-20250514" -> "claude-sonnet-4-6").
        for known_model, known_rates in COST_RATES.items():
            if model.startswith(known_model):
                rates = known_rates
                break

    if rates is None:
        # Unknown model — conservatively estimate at GPT-4o rates.
        rates = COST_RATES.get("gpt-4o", {"input": 2.50, "output": 10.0})
        logger.warning("Unknown model '%s', using GPT-4o rate estimate", model)

    cost = (
        (input_tokens / 1_000_000) * rates["input"]
        + (output_tokens / 1_000_000) * rates["output"]
    )
    return round(cost, 6)


@dataclass
class CostRecord:
    """A single cost record for an API call.

    Attributes:
        provider: The provider name.
        model: The model identifier.
        input_tokens: Number of input tokens.
        output_tokens: Number of output tokens.
        cost_usd: Estimated cost in USD.
        timestamp: When the call was made (UTC).
    """

    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    timestamp: datetime


class CostTracker:
    """Tracks AI API costs and enforces budget limits.

    Records every API call, provides aggregation methods, and checks
    budget limits. Persists cost data via a provided store.

    Attributes:
        _store: The cost store for persistence.
        _daily_budget: Daily budget limit in USD, or None.
        _monthly_budget: Monthly budget limit in USD, or None.
    """

    def __init__(
        self,
        store: Any = None,
        daily_budget: float | None = None,
        monthly_budget: float | None = None,
    ) -> None:
        """Initialise the cost tracker.

        Args:
            store: An optional cost store for SQLite persistence.
            daily_budget: Daily budget limit in USD, or None for no limit.
            monthly_budget: Monthly budget limit in USD, or None for no limit.
        """
        self._store = store
        self._daily_budget = daily_budget
        self._monthly_budget = monthly_budget
        self._records: list[CostRecord] = []

    def record_call(
        self,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float | None = None,
    ) -> CostRecord:
        """Record an API call and its cost.

        Args:
            provider: The provider name.
            model: The model identifier.
            input_tokens: Number of input tokens.
            output_tokens: Number of output tokens.
            cost_usd: Pre-computed cost, or None to estimate.

        Returns:
            The CostRecord created.
        """
        if cost_usd is None:
            cost_usd = estimate_cost(provider, model, input_tokens, output_tokens)

        record = CostRecord(
            provider=provider,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
            timestamp=datetime.now(timezone.utc),
        )

        self._records.append(record)

        # Persist to store if available.
        if self._store is not None:
            try:
                self._store.record(record)
            except Exception as exc:
                logger.warning("Failed to persist cost record: %s", exc)

        return record

    def get_daily_cost(self, date: datetime | None = None) -> float:
        """Return total cost for a given day (default: today).

        Args:
            date: The date to check. Defaults to today UTC.

        Returns:
            Total cost in USD for that day.
        """
        if date is None:
            date = datetime.now(timezone.utc)

        day_start = date.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)

        total = sum(
            r.cost_usd for r in self._records
            if day_start <= r.timestamp < day_end
        )
        return round(total, 6)

    def get_monthly_cost(self, date: datetime | None = None) -> float:
        """Return total cost for the current month.

        Args:
            date: The reference date. Defaults to today UTC.

        Returns:
            Total cost in USD for that month.
        """
        if date is None:
            date = datetime.now(timezone.utc)

        month_start = date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if month_start.month == 12:
            month_end = month_start.replace(year=month_start.year + 1, month=1)
        else:
            month_end = month_start.replace(month=month_start.month + 1)

        total = sum(
            r.cost_usd for r in self._records
            if month_start <= r.timestamp < month_end
        )
        return round(total, 6)

    def get_cost_by_provider(self) -> dict[str, float]:
        """Return cost breakdown by provider.

        Returns:
            A dict mapping provider name to total cost in USD.
        """
        costs: dict[str, float] = {}
        for record in self._records:
            costs[record.provider] = costs.get(record.provider, 0.0) + record.cost_usd
        return {k: round(v, 6) for k, v in costs.items()}

    def get_cost_history(self, days: int = 30) -> list[dict]:
        """Return daily cost history for the last N days.

        Args:
            days: Number of days to look back.

        Returns:
            A list of dicts with date, cost, and call_count.
        """
        now = datetime.now(timezone.utc)
        history = []

        for i in range(days):
            day = now - timedelta(days=i)
            day_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = day_start + timedelta(days=1)

            day_records = [
                r for r in self._records
                if day_start <= r.timestamp < day_end
            ]

            history.append({
                "date": day_start.strftime("%Y-%m-%d"),
                "cost_usd": round(sum(r.cost_usd for r in day_records), 6),
                "call_count": len(day_records),
            })

        return list(reversed(history))

    def is_over_budget(self) -> tuple[bool, str]:
        """Check if the system is over budget.

        Returns:
            A tuple of (is_over, reason). is_over is True if any budget
            limit is exceeded.
        """
        if self._daily_budget is not None:
            daily = self.get_daily_cost()
            if daily >= self._daily_budget:
                return True, f"Daily budget exceeded: ${daily:.4f} / ${self._daily_budget:.2f}"

        if self._monthly_budget is not None:
            monthly = self.get_monthly_cost()
            if monthly >= self._monthly_budget:
                return True, f"Monthly budget exceeded: ${monthly:.4f} / ${self._monthly_budget:.2f}"

        return False, ""

    def get_budget_status(self) -> dict[str, Any]:
        """Return current budget status.

        Returns:
            A dict with daily/monthly costs, budgets, and remaining.
        """
        daily = self.get_daily_cost()
        monthly = self.get_monthly_cost()
        is_over, reason = self.is_over_budget()

        return {
            "daily_cost_usd": daily,
            "monthly_cost_usd": monthly,
            "daily_budget_usd": self._daily_budget,
            "monthly_budget_usd": self._monthly_budget,
            "daily_remaining_usd": (
                round(self._daily_budget - daily, 6)
                if self._daily_budget is not None
                else None
            ),
            "monthly_remaining_usd": (
                round(self._monthly_budget - monthly, 6)
                if self._monthly_budget is not None
                else None
            ),
            "is_over_budget": is_over,
            "budget_reason": reason,
        }

    def set_budget(
        self,
        daily: float | None = None,
        monthly: float | None = None,
    ) -> None:
        """Set budget limits.

        Args:
            daily: Daily budget in USD, or None to remove limit.
            monthly: Monthly budget in USD, or None to remove limit.
        """
        if daily is not None:
            self._daily_budget = daily
        if monthly is not None:
            self._monthly_budget = monthly
