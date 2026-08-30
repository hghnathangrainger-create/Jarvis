"""
cost_tracking_tool.py

GREEN-tier tool for monitoring and managing AI provider costs.

Provides actions:
  - summary: Show daily/monthly costs and cost by provider
  - history: Show cost history for last N days
  - budget: Show remaining budget (if limits set)
  - set_budget: YELLOW, set daily/monthly limits
"""

from __future__ import annotations

from typing import Any

from ai.cost_tracker import CostTracker
from tools.base_tool import BaseTool, ToolRequest, ToolResult


class CostTrackingTool(BaseTool):
    """Tool for monitoring and managing AI API costs."""

    @property
    def name(self) -> str:
        return "cost_tracking"

    @property
    def description(self) -> str:
        return "Monitor and manage AI provider costs, budgets, and usage"

    tier = "GREEN"

    def __init__(self, cost_tracker: CostTracker | None = None) -> None:
        """Initialise the cost tracking tool.

        Args:
            cost_tracker: Optional CostTracker instance for querying costs.
        """
        self._cost_tracker = cost_tracker

    def run(self, request: ToolRequest) -> ToolResult:
        """Execute a cost tracking action.

        Args:
            request: The tool request with input_data containing action, days, etc.

        Returns:
            ToolResult with cost information.
        """
        kwargs = request.input_data
        action = kwargs.get("action", "summary")

        if self._cost_tracker is None:
            return self.fail("Cost tracker is not available. Please configure a database path.")

        try:
            if action == "summary":
                return self._handle_summary()
            elif action == "history":
                days = kwargs.get("days", 7)
                return self._handle_history(days)
            elif action == "budget":
                return self._handle_budget()
            elif action == "set_budget":
                daily = kwargs.get("daily_budget")
                monthly = kwargs.get("monthly_budget")
                return self._handle_set_budget(daily, monthly)
            else:
                return self.fail(f"Unknown action: {action}. Supported: summary, history, budget, set_budget")
        except Exception as e:
            return self.fail(f"Error: {e}")

    def _handle_summary(self) -> ToolResult:
        """Handle the summary action."""
        daily = self._cost_tracker.get_daily_cost()
        monthly = self._cost_tracker.get_monthly_cost()
        by_provider = self._cost_tracker.get_cost_by_provider()

        lines = [
            "=== AI Cost Summary ===",
            "",
            f"  Today:      ${daily:.4f}",
            f"  This Month: ${monthly:.4f}",
            "",
        ]

        if by_provider:
            lines.append("By Provider:")
            for provider, cost in sorted(by_provider.items(), key=lambda x: -x[1]):
                lines.append(f"  {provider:20s} ${cost:.4f}")
            lines.append("")

        return self.ok("\n".join(lines))

    def _handle_history(self, days: int) -> ToolResult:
        """Handle the history action."""
        history = self._cost_tracker.get_cost_history(days=days)

        lines = [
            f"=== Cost History (last {days} days) ===",
            "",
        ]

        if not history:
            lines.append("  No cost data available for this period.")
        else:
            for entry in history:
                date_str = entry.get("date", "unknown")
                cost = entry.get("cost_usd", 0.0)
                lines.append(f"  {date_str}: ${cost:.4f}")

        lines.append("")
        return self.ok("\n".join(lines))

    def _handle_budget(self) -> ToolResult:
        """Handle the budget action."""
        daily_budget = self._cost_tracker._daily_budget
        monthly_budget = self._cost_tracker._monthly_budget
        daily_used = self._cost_tracker.get_daily_cost()
        monthly_used = self._cost_tracker.get_monthly_cost()

        lines = [
            "=== Budget Status ===",
            "",
        ]

        if daily_budget is not None:
            remaining = max(0, daily_budget - daily_used)
            pct = (daily_used / daily_budget * 100) if daily_budget > 0 else 0
            lines.append(f"  Daily:   ${daily_used:.4f} / ${daily_budget:.2f} ({pct:.1f}%)")
            lines.append(f"           Remaining: ${remaining:.4f}")
        else:
            lines.append(f"  Daily:   ${daily_used:.4f} (no budget set)")

        if monthly_budget is not None:
            remaining = max(0, monthly_budget - monthly_used)
            pct = (monthly_used / monthly_budget * 100) if monthly_budget > 0 else 0
            lines.append(f"  Monthly: ${monthly_used:.4f} / ${monthly_budget:.2f} ({pct:.1f}%)")
            lines.append(f"           Remaining: ${remaining:.4f}")
        else:
            lines.append(f"  Monthly: ${monthly_used:.4f} (no budget set)")

        lines.append("")
        return self.ok("\n".join(lines))

    def _handle_set_budget(self, daily: float | None, monthly: float | None) -> ToolResult:
        """Handle the set_budget action."""
        if daily is not None:
            self._cost_tracker._daily_budget = daily
        if monthly is not None:
            self._cost_tracker._monthly_budget = monthly

        lines = ["Budget updated:"]
        if daily is not None:
            lines.append(f"  Daily: ${daily:.2f}")
        if monthly is not None:
            lines.append(f"  Monthly: ${monthly:.2f}")

        if daily is None and monthly is None:
            lines.append("  No budget changes specified.")

        return self.ok("\n".join(lines))
