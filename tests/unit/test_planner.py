"""
test_planner.py

Unit tests for the Jarvis Planner (planner/planner.py and plan_models.py).

The Planner is rule-based and uses the real Security Manager for
classification. No AI calls, database, or external services are involved, so
these tests run fast and in isolation.

Run with:
    pytest tests/unit/test_planner.py
"""

from __future__ import annotations

import pytest

from config.constants import SecurityTier
from planner.plan_models import Plan, PlanStep
from planner.planner import Planner
from security.security_manager import SecurityManager


@pytest.fixture()
def planner() -> Planner:
    """Return a Planner wired to a real Security Manager."""
    return Planner(SecurityManager())


# --- Required example mappings -----------------------------------------------


@pytest.mark.parametrize(
    ("request_text", "expected_tier"),
    [
        ("search memories for trading notes", SecurityTier.GREEN),
        ("list files in the project", SecurityTier.GREEN),
        ("read file report.txt", SecurityTier.GREEN),
        ("send email to Alex", SecurityTier.YELLOW),
        ("install software package", SecurityTier.YELLOW),
        ("delete file old.txt", SecurityTier.YELLOW),
        ("rename the project folder", SecurityTier.YELLOW),
        ("format drive C", SecurityTier.RED),
        ("disable antivirus", SecurityTier.RED),
        ("steal password from browser", SecurityTier.RED),
        ("do something unusual", SecurityTier.YELLOW),  # unknown -> cautious default
    ],
)
def test_first_step_tier_matches_expectation(
    planner: Planner, request_text: str, expected_tier: SecurityTier
) -> None:
    """The planned step receives the tier the Security Manager assigns."""
    plan = planner.create_plan(request_text)
    assert plan.steps[0].tier is expected_tier


# --- Plan structure ----------------------------------------------------------


def test_plan_preserves_original_request(planner: Planner) -> None:
    """The plan stores the original (stripped) request."""
    plan = planner.create_plan("  Search Memories  ")
    assert plan.user_request == "Search Memories"


def test_plan_has_at_least_one_step(planner: Planner) -> None:
    """Every plan produced from a non-empty request has at least one step."""
    plan = planner.create_plan("read file report.txt")
    assert not plan.is_empty
    assert len(plan.steps) >= 1


def test_step_has_all_fields(planner: Planner) -> None:
    """Each step carries number, description, action, tier, and reason."""
    plan = planner.create_plan("delete file old.txt")
    step = plan.steps[0]
    assert step.number == 1
    assert step.description
    assert step.action
    assert isinstance(step.tier, SecurityTier)
    assert step.reason


def test_step_numbers_are_sequential(planner: Planner) -> None:
    """Step numbers start at one and increase by one."""
    plan = planner.create_plan("read file report.txt")
    for index, step in enumerate(plan.steps, start=1):
        assert step.number == index


# --- Plan-level flags --------------------------------------------------------


def test_green_plan_needs_no_confirmation(planner: Planner) -> None:
    """A plan whose steps are all GREEN requires no confirmation."""
    plan = planner.create_plan("search memories")
    assert plan.requires_confirmation is False
    assert plan.has_blocked_steps is False
    assert plan.highest_tier is SecurityTier.GREEN


def test_yellow_plan_requires_confirmation(planner: Planner) -> None:
    """A plan with a YELLOW step requires confirmation but is not blocked."""
    plan = planner.create_plan("send email to Bob")
    assert plan.requires_confirmation is True
    assert plan.has_blocked_steps is False
    assert plan.highest_tier is SecurityTier.YELLOW


def test_red_plan_has_blocked_steps(planner: Planner) -> None:
    """A plan with a RED step is reported as containing blocked steps."""
    plan = planner.create_plan("format drive C")
    assert plan.has_blocked_steps is True
    assert plan.highest_tier is SecurityTier.RED


# --- Step helper properties --------------------------------------------------


def test_step_helper_properties(planner: Planner) -> None:
    """PlanStep convenience flags reflect the assigned tier."""
    green = planner.create_plan("search memories").steps[0]
    yellow = planner.create_plan("send email").steps[0]
    red = planner.create_plan("format drive").steps[0]

    assert not green.is_blocked and not green.requires_confirmation
    assert yellow.requires_confirmation and not yellow.is_blocked
    assert red.is_blocked and not red.requires_confirmation


# --- Input validation --------------------------------------------------------


def test_empty_request_raises(planner: Planner) -> None:
    """An empty or whitespace-only request raises ValueError."""
    with pytest.raises(ValueError):
        planner.create_plan("   ")


# --- The Planner does not execute --------------------------------------------


def test_planner_does_not_execute_anything(planner: Planner) -> None:
    """Creating a plan returns a Plan and performs no side effects.

    This is a behavioural guard: a RED 'delete' request must still produce a
    plan object rather than attempting the deletion. The Planner only plans.
    """
    plan = planner.create_plan("delete all files in folder")
    assert isinstance(plan, Plan)
    assert plan.has_blocked_steps is True