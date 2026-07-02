"""
test_ai_reasoning_models.py

Unit tests for the AI reasoning data models (Phase 4, Batch 1).

These are plain, immutable data classes. The tests confirm they construct,
carry their fields, apply sensible defaults, and are frozen. Nothing here
touches a provider, a tool, or the security path.

Run with:
    pytest tests/unit/test_ai_reasoning_models.py
"""

from __future__ import annotations

import dataclasses

import pytest

from ai.reasoning_models import (
    AIReasoningRequest,
    AIReasoningResult,
    AISuggestedAction,
)


# --- AIReasoningRequest ------------------------------------------------------


def test_reasoning_request_holds_fields() -> None:
    request = AIReasoningRequest(
        user_input="echo hello", context="tools available", session_id=7
    )
    assert request.user_input == "echo hello"
    assert request.context == "tools available"
    assert request.session_id == 7


def test_reasoning_request_defaults() -> None:
    request = AIReasoningRequest(user_input="hi")
    assert request.context == ""
    assert request.session_id is None


def test_reasoning_request_is_frozen() -> None:
    request = AIReasoningRequest(user_input="hi")
    with pytest.raises(dataclasses.FrozenInstanceError):
        request.user_input = "changed"  # type: ignore[misc]


# --- AISuggestedAction -------------------------------------------------------


def test_suggested_action_holds_fields() -> None:
    action = AISuggestedAction(description="use echo", suggested_tier="GREEN")
    assert action.description == "use echo"
    assert action.suggested_tier == "GREEN"


def test_suggested_action_defaults_to_unknown_tier() -> None:
    action = AISuggestedAction(description="do something")
    assert action.suggested_tier == "UNKNOWN"


def test_suggested_action_is_frozen() -> None:
    action = AISuggestedAction(description="x")
    with pytest.raises(dataclasses.FrozenInstanceError):
        action.description = "y"  # type: ignore[misc]


# --- AIReasoningResult -------------------------------------------------------


def test_reasoning_result_defaults() -> None:
    result = AIReasoningResult(summary="You want to echo text.")
    assert result.summary == "You want to echo text."
    assert result.suggested_actions == ()
    assert result.raw_text == ""
    assert result.provider_name == "none"
    assert result.has_suggestions is False


def test_reasoning_result_with_actions() -> None:
    actions = (
        AISuggestedAction(description="step one"),
        AISuggestedAction(description="step two"),
    )
    result = AIReasoningResult(
        summary="A two-step plan.",
        suggested_actions=actions,
        raw_text="raw",
        provider_name="fake",
    )
    assert result.has_suggestions is True
    assert len(result.suggested_actions) == 2
    assert result.provider_name == "fake"


def test_reasoning_result_is_frozen() -> None:
    result = AIReasoningResult(summary="x")
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.summary = "y"  # type: ignore[misc]