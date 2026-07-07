"""
test_security_unexpected_action.py

Unit tests for SecurityManager.evaluate_unexpected_action() and
UnexpectedActionDecision (Phase 7, Batch 4).

These prove:
    - An action already in the expected-actions set is never flagged: no
      decision is returned at all.
    - An unexpected GREEN action returns FLAG.
    - An unexpected YELLOW action returns ESCALATE.
    - An unexpected RED action returns BLOCK.
    - Every returned decision's tier and reason come from classify_action -
      the tier logic is reused, never duplicated or reimplemented.
    - Decisions are deterministic: the same input always produces the same
      verdict and tier.
    - evaluate_unexpected_action never executes, approves, or blocks
      anything itself - it only returns a verdict.

Run with:
    pytest tests/unit/test_security_unexpected_action.py
"""

from __future__ import annotations

import pytest

from config.constants import SecurityTier
from security.security_manager import (
    SecurityManager,
    UnexpectedActionDecision,
    UnexpectedActionVerdict,
)


@pytest.fixture()
def manager() -> SecurityManager:
    """Return a fresh SecurityManager for each test."""
    return SecurityManager()


# --- Expected actions are never flagged --------------------------------------


def test_action_in_expected_scope_returns_none(manager: SecurityManager) -> None:
    expected = frozenset({"search memories", "read file report.txt"})
    decision = manager.evaluate_unexpected_action("search memories", expected)
    assert decision is None


def test_expected_red_action_is_not_flagged_either(manager: SecurityManager) -> None:
    # Even a RED-tier action is not unexpected if the Planner already
    # produced it as part of this request's own plan.
    expected = frozenset({"format drive C"})
    decision = manager.evaluate_unexpected_action("format drive C", expected)
    assert decision is None


def test_empty_expected_scope_means_everything_is_unexpected(
    manager: SecurityManager,
) -> None:
    decision = manager.evaluate_unexpected_action("search memories", frozenset())
    assert decision is not None
    assert decision.verdict is UnexpectedActionVerdict.FLAG


# --- Unexpected GREEN -> FLAG -------------------------------------------------


def test_unexpected_green_action_is_flagged(manager: SecurityManager) -> None:
    decision = manager.evaluate_unexpected_action(
        "search memories", frozenset({"echo hello"})
    )
    assert decision is not None
    assert decision.verdict is UnexpectedActionVerdict.FLAG
    assert decision.tier is SecurityTier.GREEN


# --- Unexpected YELLOW -> ESCALATE --------------------------------------------


def test_unexpected_yellow_action_is_escalated(manager: SecurityManager) -> None:
    decision = manager.evaluate_unexpected_action(
        "send email to Alex", frozenset({"echo hello"})
    )
    assert decision is not None
    assert decision.verdict is UnexpectedActionVerdict.ESCALATE
    assert decision.tier is SecurityTier.YELLOW


# --- Unexpected RED -> BLOCK ---------------------------------------------------


def test_unexpected_red_action_is_blocked(manager: SecurityManager) -> None:
    decision = manager.evaluate_unexpected_action(
        "format drive C", frozenset({"echo hello"})
    )
    assert decision is not None
    assert decision.verdict is UnexpectedActionVerdict.BLOCK
    assert decision.tier is SecurityTier.RED


# --- classify_action remains the sole classification source ------------------


def test_decision_tier_and_reason_come_from_classify_action(
    manager: SecurityManager,
) -> None:
    classification = manager.classify_action("delete file report.txt")
    decision = manager.evaluate_unexpected_action(
        "delete file report.txt", frozenset({"echo hello"})
    )
    assert decision is not None
    assert decision.tier is classification.tier
    assert classification.reason in decision.reason


@pytest.mark.parametrize(
    ("action", "expected_tier", "expected_verdict"),
    [
        ("search memories", SecurityTier.GREEN, UnexpectedActionVerdict.FLAG),
        ("send email to Alex", SecurityTier.YELLOW, UnexpectedActionVerdict.ESCALATE),
        ("format drive C", SecurityTier.RED, UnexpectedActionVerdict.BLOCK),
    ],
)
def test_verdict_mapping_matches_classify_action_tier(
    manager: SecurityManager,
    action: str,
    expected_tier: SecurityTier,
    expected_verdict: UnexpectedActionVerdict,
) -> None:
    classification = manager.classify_action(action)
    assert classification.tier is expected_tier

    decision = manager.evaluate_unexpected_action(action, frozenset())
    assert decision is not None
    assert decision.tier is expected_tier
    assert decision.verdict is expected_verdict


# --- Deterministic decisions ---------------------------------------------------


def test_decision_is_deterministic_across_calls(manager: SecurityManager) -> None:
    expected = frozenset({"echo hello"})
    first = manager.evaluate_unexpected_action("delete file report.txt", expected)
    second = manager.evaluate_unexpected_action("delete file report.txt", expected)
    assert first == second


def test_decision_action_field_matches_stripped_input(manager: SecurityManager) -> None:
    decision = manager.evaluate_unexpected_action(
        "  search memories  ", frozenset({"echo hello"})
    )
    assert decision is not None
    assert decision.action == "search memories"


# --- Result type and structure -------------------------------------------------


def test_result_type_is_unexpected_action_decision(manager: SecurityManager) -> None:
    decision = manager.evaluate_unexpected_action(
        "search memories", frozenset({"echo hello"})
    )
    assert isinstance(decision, UnexpectedActionDecision)


# --- Policy only: never executes, approves, or blocks anything itself --------


def test_evaluate_unexpected_action_has_no_side_effects(
    manager: SecurityManager,
) -> None:
    # Calling it twice with a RED verdict must not raise, block, or otherwise
    # do anything beyond returning a value - it is a pure function of its
    # arguments and the (stateless) classify_action rules.
    expected = frozenset({"echo hello"})
    decision = manager.evaluate_unexpected_action("format drive C", expected)
    assert decision is not None
    assert decision.verdict is UnexpectedActionVerdict.BLOCK
    # No exception, no execution, no state mutated on the manager itself.
    assert manager.evaluate_unexpected_action("format drive C", expected) == decision
