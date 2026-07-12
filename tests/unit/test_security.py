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
from security.security_manager import SecurityManager


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


# --- Phase 33: webpage read classification ------------------------------------


def test_read_webpage_requires_confirmation(manager: SecurityManager) -> None:
    """Unlike "read file" (GREEN, local only), reading a webpage reaches
    an arbitrary external network target and displays that content, so
    it is YELLOW with its own specific, honest reason - never the
    generic GREEN "read" rule, and never the default-fallback message."""
    decision = manager.classify_action("read webpage")
    assert decision.requires_confirmation
    assert not decision.is_allowed_automatically
    assert not decision.is_blocked
    reason = decision.reason.lower()
    assert "external" in reason or "web" in reason or "network" in reason
    assert decision.matched_keyword == "read webpage"


def test_read_webpage_is_not_classified_by_the_generic_read_rule(
    manager: SecurityManager,
) -> None:
    """Without the explicit "read webpage" rule, this action would fall
    through to the generic GREEN "read" rule (it contains "read" as a
    substring) and be misclassified as automatically-safe - this proves
    that does not happen."""
    decision = manager.classify_action("read webpage")
    assert decision.matched_keyword != "read"


def test_read_webpage_classification_is_input_independent(
    manager: SecurityManager,
) -> None:
    """The fixed action string is always classified the same way,
    regardless of what URL a caller might have appended before
    classification (WebpageReadTool.action_for() never does this, but
    the rule itself must not depend on it either)."""
    decision = manager.classify_action(
        "read webpage http://169.254.169.254/latest/meta-data/"
    )
    assert decision.requires_confirmation
    assert decision.matched_keyword == "read webpage"


def test_read_file_remains_green_after_adding_read_webpage_rule(
    manager: SecurityManager,
) -> None:
    """Regression: the pre-existing "read file" GREEN rule (and the
    generic GREEN "read" rule) are unaffected by the new "read webpage"
    rule - they are checked in a different tier, and "read webpage"
    itself never matches "read file"."""
    assert manager.classify_action("read file").is_allowed_automatically
    assert manager.classify_action("read the file notes.txt").is_allowed_automatically


def test_webpage_read_rule_does_not_affect_unrelated_existing_classifications(
    manager: SecurityManager,
) -> None:
    """Regression: every pre-existing classification this phase does not
    touch remains exactly as it was."""
    assert manager.classify_action("search the web for jarvis").is_allowed_automatically
    assert manager.classify_action("download").requires_confirmation
    assert manager.classify_action("delete file notes.txt").requires_confirmation
    assert manager.classify_action("format drive").is_blocked


# --- Phase 35: file quarantine/delete classification --------------------------


def test_delete_file_requires_confirmation(manager: SecurityManager) -> None:
    """Confirms the pre-existing "delete file" YELLOW rule - already
    present before Phase 35 (added for the raw "delete file <path>"
    phrasing) - is exactly what FileDeleteTool.action_for() classifies
    against. No new SecurityManager rule was added or needed."""
    decision = manager.classify_action("delete file")
    assert decision.requires_confirmation
    assert not decision.is_allowed_automatically
    assert not decision.is_blocked
    reason = decision.reason.lower()
    assert "state" in reason or "delet" in reason or "confirm" in reason
    assert decision.matched_keyword == "delete file"


def test_delete_file_classification_is_input_independent(
    manager: SecurityManager,
) -> None:
    """The fixed action string is classified the same way regardless of
    what path a caller might have appended (FileDeleteTool.action_for()
    never does this, but the rule itself must not depend on it
    either)."""
    decision = manager.classify_action("delete file ../../../etc/passwd")
    assert decision.requires_confirmation
    assert decision.matched_keyword == "delete file"


def test_delete_file_rule_does_not_affect_unrelated_existing_classifications(
    manager: SecurityManager,
) -> None:
    """Regression: every pre-existing classification this phase does not
    touch remains exactly as it was."""
    assert manager.classify_action("search the web for jarvis").is_allowed_automatically
    assert manager.classify_action("read webpage").requires_confirmation
    assert manager.classify_action("move file a.txt to b.txt").requires_confirmation
    assert manager.classify_action("copy file a.txt to b.txt").requires_confirmation
    assert manager.classify_action("delete all files").is_blocked
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