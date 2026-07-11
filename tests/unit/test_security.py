"""
test_security.py

Unit tests for the Jarvis Security Manager (security/security_manager.py).

The Security Manager is rule-based and makes no network or AI calls, so these
tests run fast and require no database or external services.

Run with:
    pytest tests/unit/test_security.py
"""

from __future__ import annotations

import pytest

from config.constants import SecurityTier
from security.security_manager import SecurityDecision, SecurityManager


@pytest.fixture()
def manager() -> SecurityManager:
    """Return a fresh SecurityManager for each test."""
    return SecurityManager()


# --- Required examples -------------------------------------------------------


@pytest.mark.parametrize(
    ("action", "expected_tier"),
    [
        ("search memories", SecurityTier.GREEN),
        ("list files", SecurityTier.GREEN),
        ("read file report.txt", SecurityTier.GREEN),
        ("send email to Alex", SecurityTier.YELLOW),
        ("install software package", SecurityTier.YELLOW),
        ("delete file report.txt", SecurityTier.YELLOW),
        ("delete all files", SecurityTier.RED),
        ("format drive C", SecurityTier.RED),
        ("disable antivirus", SecurityTier.RED),
        ("steal password from browser", SecurityTier.RED),
    ],
)
def test_required_examples(
    manager: SecurityManager, action: str, expected_tier: SecurityTier
) -> None:
    """Each documented example is classified into its expected tier."""
    decision = manager.classify_action(action)
    assert decision.tier is expected_tier


# --- Tier precedence ---------------------------------------------------------


def test_most_dangerous_tier_wins(manager: SecurityManager) -> None:
    """When dangerous and sensitive keywords co-occur, RED wins."""
    decision = manager.classify_action("format drive C then delete temp")
    assert decision.tier is SecurityTier.RED


def test_delete_all_is_red_not_yellow(manager: SecurityManager) -> None:
    """'delete all' is bulk deletion (RED), not a single delete (YELLOW)."""
    decision = manager.classify_action("delete all files in folder")
    assert decision.tier is SecurityTier.RED


# --- Default behaviour -------------------------------------------------------


def test_unknown_action_defaults_to_yellow(manager: SecurityManager) -> None:
    """An action matching no rule is treated as sensitive (YELLOW)."""
    decision = manager.classify_action("do a barrel roll")
    assert decision.tier is SecurityTier.YELLOW
    assert decision.matched_keyword is None


# --- Reasons and metadata ----------------------------------------------------


def test_decision_includes_reason(manager: SecurityManager) -> None:
    """Every decision carries a non-empty, human-readable reason."""
    decision = manager.classify_action("format drive")
    assert decision.reason
    assert isinstance(decision.reason, str)


def test_matched_keyword_is_reported(manager: SecurityManager) -> None:
    """A matched decision reports which keyword triggered it."""
    decision = manager.classify_action("send email to the team")
    assert decision.matched_keyword == "send email"


# --- Case sensitivity --------------------------------------------------------


def test_classification_is_case_insensitive(manager: SecurityManager) -> None:
    """Matching ignores case."""
    assert manager.classify_action("FORMAT DRIVE").tier is SecurityTier.RED
    assert manager.classify_action("Search Memories").tier is SecurityTier.GREEN


# --- Decision helper properties ----------------------------------------------


def test_green_decision_is_allowed_automatically(manager: SecurityManager) -> None:
    decision = manager.classify_action("search memories")
    assert decision.is_allowed_automatically
    assert not decision.requires_confirmation
    assert not decision.is_blocked


def test_yellow_decision_requires_confirmation(manager: SecurityManager) -> None:
    decision = manager.classify_action("send email")
    assert decision.requires_confirmation
    assert not decision.is_allowed_automatically
    assert not decision.is_blocked


def test_red_decision_is_blocked(manager: SecurityManager) -> None:
    decision = manager.classify_action("format drive")
    assert decision.is_blocked
    assert not decision.is_allowed_automatically
    assert not decision.requires_confirmation


# --- Phase 21: schedule management classification -----------------------------


def test_schedule_web_search_requires_confirmation(manager: SecurityManager) -> None:
    """Creating a scheduled action commits Jarvis to running it
    unattended, so it is YELLOW - with its own specific, honest reason
    rather than the generic default-fallback message."""
    decision = manager.classify_action("schedule web search")
    assert decision.requires_confirmation
    assert not decision.is_allowed_automatically
    assert not decision.is_blocked
    assert "unattended" in decision.reason.lower()


def test_enable_schedule_requires_confirmation(manager: SecurityManager) -> None:
    decision = manager.classify_action("enable schedule")
    assert decision.requires_confirmation
    assert "unattended" in decision.reason.lower()


def test_disable_schedule_requires_confirmation(manager: SecurityManager) -> None:
    decision = manager.classify_action("disable schedule")
    assert decision.requires_confirmation
    assert "confirmed" in decision.reason.lower()


def test_list_schedules_is_green(manager: SecurityManager) -> None:
    """Read-only, via the existing, unchanged "list" rule - no new rule
    was needed or added for listing."""
    decision = manager.classify_action("list schedules")
    assert decision.is_allowed_automatically
    assert not decision.requires_confirmation
    assert not decision.is_blocked


def test_schedule_rules_do_not_affect_unrelated_existing_classifications(
    manager: SecurityManager,
) -> None:
    """Regression: every pre-existing classification this phase does not
    touch remains exactly as it was."""
    assert manager.classify_action("search the web for jarvis").is_allowed_automatically
    assert manager.classify_action("delete file notes.txt").requires_confirmation
    assert manager.classify_action("format drive").is_blocked


# --- Input validation --------------------------------------------------------


def test_empty_action_raises(manager: SecurityManager) -> None:
    """An empty or whitespace-only action raises ValueError."""
    with pytest.raises(ValueError):
        manager.classify_action("   ")


def test_decision_preserves_original_action(manager: SecurityManager) -> None:
    """The decision records the original (stripped) action text."""
    decision = manager.classify_action("  delete file notes.txt  ")
    assert decision.action == "delete file notes.txt"