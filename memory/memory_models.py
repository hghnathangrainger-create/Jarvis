"""
memory_models.py

Small, safe value types for the Jarvis memory system (Phase 5, Batch 1).

This module defines the vocabulary of memory categories and a helper to
normalise a category safely. It has no behaviour beyond that: it stores no data,
calls no provider, and makes no decisions about safety. Categories are an
organisational label only - they never affect how an action is classified,
approved, or executed.

Design note:
    Categories are intentionally permissive. An unknown or blank category is not
    an error; it simply falls back to the default, "general". This keeps memory
    saving robust and beginner-friendly: a mistyped category can only mis-file a
    memory, never break anything.
"""

from __future__ import annotations

#: The default category applied when none is given or the given one is unknown.
DEFAULT_CATEGORY = "general"

#: The recognised memory categories. These are the labels Jarvis suggests and
#: filters on. Any other value normalises to DEFAULT_CATEGORY.
GENERAL = "general"
PERSONAL = "personal"
PROJECT = "project"
PREFERENCE = "preference"
NOTE = "note"

#: The full set of known categories, used for validation and for listing the
#: available categories to the user.
KNOWN_CATEGORIES: tuple[str, ...] = (
    GENERAL,
    PERSONAL,
    PROJECT,
    PREFERENCE,
    NOTE,
)


def normalize_category(category: str | None) -> str:
    """Return a safe, known category for any input.

    The input is trimmed and lower-cased. If the result is one of the known
    categories, it is returned; otherwise the default category ("general") is
    returned. A None or blank input also yields the default.

    Args:
        category: The raw category value, which may be None, blank, mixed-case,
            or unknown.

    Returns:
        A known category string. Never raises.
    """
    if category is None:
        return DEFAULT_CATEGORY
    cleaned = category.strip().lower()
    if not cleaned:
        return DEFAULT_CATEGORY
    if cleaned in KNOWN_CATEGORIES:
        return cleaned
    return DEFAULT_CATEGORY


def is_known_category(category: str | None) -> bool:
    """Report whether a category is one of the known categories.

    Args:
        category: The raw category value to check.

    Returns:
        True if the trimmed, lower-cased value is a known category, else False.
    """
    if category is None:
        return False
    return category.strip().lower() in KNOWN_CATEGORIES