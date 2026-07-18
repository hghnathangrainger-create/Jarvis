"""
test_verification.py

Unit tests for intelligence/verification.py (Phase 90, Batch 3): exact,
deterministic verification for the update-focus-and-verify workflow.

Run with:
    pytest tests/unit/test_verification.py
"""

from __future__ import annotations

import dataclasses

import pytest

from intelligence.verification import (
    FOCUS_EXACT_MATCH_VERIFIER_ID,
    VerificationOutcome,
    VerificationResult,
    verify_focus_update,
)
from tools.base_tool import ToolResult


def _tool_result(*, success: bool, focus: str | None) -> ToolResult:
    metadata = {} if focus is None else {"focus": focus}
    return ToolResult(
        tool_name="project_state_verify", success=success, metadata=metadata
    )


def test_exact_match_is_verified() -> None:
    result = verify_focus_update(
        expected_value="new focus",
        verify_tool_result=_tool_result(success=True, focus="new focus"),
    )
    assert result.outcome is VerificationOutcome.VERIFIED
    assert result.verifier_id == FOCUS_EXACT_MATCH_VERIFIER_ID
    assert result.evidence == "new focus"
    assert result.detail is None


def test_exact_mismatch_is_failed() -> None:
    result = verify_focus_update(
        expected_value="new focus",
        verify_tool_result=_tool_result(success=True, focus="a different value"),
    )
    assert result.outcome is VerificationOutcome.FAILED
    assert result.evidence == "a different value"
    assert result.detail is not None


def test_verifier_none_is_unavailable() -> None:
    result = verify_focus_update(expected_value="new focus", verify_tool_result=None)
    assert result.outcome is VerificationOutcome.UNAVAILABLE
    assert result.evidence == ""


def test_verifier_tool_result_failure_is_unavailable() -> None:
    result = verify_focus_update(
        expected_value="new focus",
        verify_tool_result=_tool_result(success=False, focus="new focus"),
    )
    assert result.outcome is VerificationOutcome.UNAVAILABLE


def test_missing_focus_metadata_is_unavailable() -> None:
    result = verify_focus_update(
        expected_value="new focus",
        verify_tool_result=_tool_result(success=True, focus=None),
    )
    assert result.outcome is VerificationOutcome.UNAVAILABLE


def test_empty_actual_focus_is_a_real_mismatch_not_unavailable() -> None:
    """An empty string is a present, real (if surprising) value - never
    "malformed" - so it goes through ordinary comparison and correctly
    produces FAILED against any non-empty expected value."""
    result = verify_focus_update(
        expected_value="new focus",
        verify_tool_result=_tool_result(success=True, focus=""),
    )
    assert result.outcome is VerificationOutcome.FAILED


def test_evidence_is_bounded_to_200_characters() -> None:
    long_focus = "x" * 500
    result = verify_focus_update(
        expected_value="new focus",
        verify_tool_result=_tool_result(success=True, focus=long_focus),
    )
    assert len(result.evidence) == 200


def test_no_retry_or_replan_mechanism_exists() -> None:
    """Structural sanity: this module exposes exactly one function and
    performs a single comparison - there is no loop, no retry
    parameter, and no replan concept anywhere in its API."""
    import inspect

    import intelligence.verification as module

    functions = [
        name
        for name, obj in vars(module).items()
        if inspect.isfunction(obj) and obj.__module__ == module.__name__
    ]
    assert functions == ["verify_focus_update"]


# --- Contract shape tests ----------------------------------------------------


def test_verification_outcome_has_exactly_four_members() -> None:
    assert {member.value for member in VerificationOutcome} == {
        "verified",
        "failed",
        "unavailable",
        "not_required",
    }


def test_verification_result_is_frozen_and_slotted() -> None:
    result = VerificationResult(
        outcome=VerificationOutcome.VERIFIED,
        verifier_id=FOCUS_EXACT_MATCH_VERIFIER_ID,
        evidence="x",
        detail=None,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.evidence = "changed"  # type: ignore[misc]
    assert not hasattr(result, "__dict__")


def test_verification_result_has_exact_fields() -> None:
    field_names = {f.name for f in dataclasses.fields(VerificationResult)}
    assert field_names == {"outcome", "verifier_id", "evidence", "detail"}
