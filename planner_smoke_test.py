"""
planner_smoke_test.py

A standalone smoke test for the Jarvis Planner.

Run this directly (no pytest needed) to see how a range of sample requests are
turned into structured plans, with each step's security tier and reason, plus
the plan-level confirmation and blocked flags.

Place this file in the project root and run it from PowerShell:

    poetry run python planner_smoke_test.py
"""

from __future__ import annotations

from config.constants import SecurityTier
from planner.plan_models import Plan
from planner.planner import Planner
from security.security_manager import SecurityManager

# A representative spread of requests across all three tiers, plus an
# unrecognised request to show the cautious default.
_SAMPLE_REQUESTS: tuple[str, ...] = (
    "search memories for trading notes",
    "list files in the project",
    "read file report.txt",
    "summarise the meeting notes",
    "send email to Alex",
    "install software package",
    "delete file old_report.txt",
    "rename the project folder",
    "delete all files in the temp folder",
    "format drive C",
    "disable antivirus",
    "steal password from browser",
    "do something completely unusual",
)

_TIER_SYMBOL = {
    SecurityTier.GREEN: "[GREEN ]",
    SecurityTier.YELLOW: "[YELLOW]",
    SecurityTier.RED: "[RED   ]",
}


def _print_plan(plan: Plan) -> None:
    """Print a single plan in a readable form.

    Args:
        plan: The plan to print.
    """
    print(f"Request: {plan.user_request}")
    for step in plan.steps:
        symbol = _TIER_SYMBOL[step.tier]
        print(f"  Step {step.number}: {symbol} {step.description}")
        print(f"           action: {step.action}")
        print(f"           reason: {step.reason}")
    print(
        f"  -> requires_confirmation={plan.requires_confirmation}, "
        f"has_blocked_steps={plan.has_blocked_steps}, "
        f"highest_tier={plan.highest_tier.name}"
    )
    print()


def main() -> None:
    """Build and print a plan for each sample request."""
    planner = Planner(SecurityManager())

    print("Jarvis Planner - sample plans")
    print("=" * 70)
    print()

    for request in _SAMPLE_REQUESTS:
        _print_plan(planner.create_plan(request))

    print("=" * 70)
    print("GREEN  = allowed automatically")
    print("YELLOW = requires user confirmation")
    print("RED    = blocked by default")
    print()
    print("Note: the Planner only creates plans. It does not execute anything.")


if __name__ == "__main__":
    main()