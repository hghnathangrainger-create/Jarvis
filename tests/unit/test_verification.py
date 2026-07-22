"""
test_verification.py

Unit tests for intelligence/verification.py: exact, deterministic
verification for the update-focus-and-verify workflow (Phase 90,
Batch 3), the schedule-enable/disable workflows (Phase 94, Batch 2;
Phase 95), and the update-phase-and-verify workflow (Phase 96), which
reuses the original focus verifier function - genericized, never
duplicated - via field_name="phase" and its own distinct verifier_id.

Run with:
    pytest tests/unit/test_verification.py
"""

from __future__ import annotations

import dataclasses

import pytest

from intelligence.verification import (
    FOCUS_EXACT_MATCH_VERIFIER_ID,
    PROJECT_STATE_PHASE_EXACT_MATCH_VERIFIER_ID,
    VerificationOutcome,
    VerificationResult,
    verify_project_state_field,
)
from tools.base_tool import ToolResult


def _tool_result(*, success: bool, field_name: str, value: str | None) -> ToolResult:
    metadata = {} if value is None else {field_name: value}
    return ToolResult(
        tool_name="project_state_verify", success=success, metadata=metadata
    )


# --- Focus field (field_name="focus", unchanged behavior) -------------------


def test_exact_match_is_verified() -> None:
    result = verify_project_state_field(
        field_name="focus",
        expected_value="new focus",
        verifier_id=FOCUS_EXACT_MATCH_VERIFIER_ID,
        verify_tool_result=_tool_result(
            success=True, field_name="focus", value="new focus"
        ),
    )
    assert result.outcome is VerificationOutcome.VERIFIED
    assert result.verifier_id == FOCUS_EXACT_MATCH_VERIFIER_ID
    assert result.evidence == "new focus"
    assert result.detail is None


def test_exact_mismatch_is_failed() -> None:
    result = verify_project_state_field(
        field_name="focus",
        expected_value="new focus",
        verifier_id=FOCUS_EXACT_MATCH_VERIFIER_ID,
        verify_tool_result=_tool_result(
            success=True, field_name="focus", value="a different value"
        ),
    )
    assert result.outcome is VerificationOutcome.FAILED
    assert result.evidence == "a different value"
    assert result.detail is not None


def test_verifier_none_is_unavailable() -> None:
    result = verify_project_state_field(
        field_name="focus",
        expected_value="new focus",
        verifier_id=FOCUS_EXACT_MATCH_VERIFIER_ID,
        verify_tool_result=None,
    )
    assert result.outcome is VerificationOutcome.UNAVAILABLE
    assert result.evidence == ""


def test_verifier_tool_result_failure_is_unavailable() -> None:
    result = verify_project_state_field(
        field_name="focus",
        expected_value="new focus",
        verifier_id=FOCUS_EXACT_MATCH_VERIFIER_ID,
        verify_tool_result=_tool_result(
            success=False, field_name="focus", value="new focus"
        ),
    )
    assert result.outcome is VerificationOutcome.UNAVAILABLE


def test_missing_focus_metadata_is_unavailable() -> None:
    result = verify_project_state_field(
        field_name="focus",
        expected_value="new focus",
        verifier_id=FOCUS_EXACT_MATCH_VERIFIER_ID,
        verify_tool_result=_tool_result(success=True, field_name="focus", value=None),
    )
    assert result.outcome is VerificationOutcome.UNAVAILABLE


def test_empty_actual_focus_is_a_real_mismatch_not_unavailable() -> None:
    """An empty string is a present, real (if surprising) value - never
    "malformed" - so it goes through ordinary comparison and correctly
    produces FAILED against any non-empty expected value."""
    result = verify_project_state_field(
        field_name="focus",
        expected_value="new focus",
        verifier_id=FOCUS_EXACT_MATCH_VERIFIER_ID,
        verify_tool_result=_tool_result(success=True, field_name="focus", value=""),
    )
    assert result.outcome is VerificationOutcome.FAILED


def test_evidence_is_bounded_to_200_characters() -> None:
    long_focus = "x" * 500
    result = verify_project_state_field(
        field_name="focus",
        expected_value="new focus",
        verifier_id=FOCUS_EXACT_MATCH_VERIFIER_ID,
        verify_tool_result=_tool_result(
            success=True, field_name="focus", value=long_focus
        ),
    )
    assert len(result.evidence) == 200


# --- Phase field (field_name="phase", Phase 96) ------------------------------


def test_phase_exact_match_is_verified() -> None:
    result = verify_project_state_field(
        field_name="phase",
        expected_value="Phase 96",
        verifier_id=PROJECT_STATE_PHASE_EXACT_MATCH_VERIFIER_ID,
        verify_tool_result=_tool_result(
            success=True, field_name="phase", value="Phase 96"
        ),
    )
    assert result.outcome is VerificationOutcome.VERIFIED
    assert result.verifier_id == PROJECT_STATE_PHASE_EXACT_MATCH_VERIFIER_ID
    assert result.evidence == "Phase 96"
    assert result.detail is None


def test_phase_exact_mismatch_is_failed() -> None:
    result = verify_project_state_field(
        field_name="phase",
        expected_value="Phase 96",
        verifier_id=PROJECT_STATE_PHASE_EXACT_MATCH_VERIFIER_ID,
        verify_tool_result=_tool_result(
            success=True, field_name="phase", value="Phase 95"
        ),
    )
    assert result.outcome is VerificationOutcome.FAILED
    assert result.evidence == "Phase 95"
    assert result.verifier_id == PROJECT_STATE_PHASE_EXACT_MATCH_VERIFIER_ID


def test_phase_verifier_none_is_unavailable() -> None:
    result = verify_project_state_field(
        field_name="phase",
        expected_value="Phase 96",
        verifier_id=PROJECT_STATE_PHASE_EXACT_MATCH_VERIFIER_ID,
        verify_tool_result=None,
    )
    assert result.outcome is VerificationOutcome.UNAVAILABLE


def test_phase_verifier_tool_result_failure_is_unavailable() -> None:
    result = verify_project_state_field(
        field_name="phase",
        expected_value="Phase 96",
        verifier_id=PROJECT_STATE_PHASE_EXACT_MATCH_VERIFIER_ID,
        verify_tool_result=_tool_result(
            success=False, field_name="phase", value="Phase 96"
        ),
    )
    assert result.outcome is VerificationOutcome.UNAVAILABLE


def test_missing_phase_metadata_is_unavailable() -> None:
    result = verify_project_state_field(
        field_name="phase",
        expected_value="Phase 96",
        verifier_id=PROJECT_STATE_PHASE_EXACT_MATCH_VERIFIER_ID,
        verify_tool_result=_tool_result(success=True, field_name="phase", value=None),
    )
    assert result.outcome is VerificationOutcome.UNAVAILABLE


def test_focus_and_phase_verifier_ids_are_distinct() -> None:
    """The two fields never share a verifier_id, even though they
    share the identical underlying comparison function."""
    assert FOCUS_EXACT_MATCH_VERIFIER_ID != PROJECT_STATE_PHASE_EXACT_MATCH_VERIFIER_ID


def test_phase_verification_never_reads_focus_metadata_or_vice_versa() -> None:
    """A ToolResult carrying only "focus" metadata is UNAVAILABLE when
    verified against field_name="phase", and vice versa - the two
    fields are never confused with one another."""
    focus_only_result = _tool_result(success=True, field_name="focus", value="x")
    phase_only_result = _tool_result(success=True, field_name="phase", value="y")

    assert (
        verify_project_state_field(
            field_name="phase",
            expected_value="y",
            verifier_id=PROJECT_STATE_PHASE_EXACT_MATCH_VERIFIER_ID,
            verify_tool_result=focus_only_result,
        ).outcome
        is VerificationOutcome.UNAVAILABLE
    )
    assert (
        verify_project_state_field(
            field_name="focus",
            expected_value="x",
            verifier_id=FOCUS_EXACT_MATCH_VERIFIER_ID,
            verify_tool_result=phase_only_result,
        ).outcome
        is VerificationOutcome.UNAVAILABLE
    )


def test_no_retry_or_replan_mechanism_exists() -> None:
    """Structural sanity: this module exposes exactly the two real
    verifier functions (the genericized ProjectState field verifier,
    shared by focus and phase, and the schedule-enabled-state
    verifier, shared by enable and disable) and each performs a single
    comparison - there is no loop, no retry parameter, and no replan
    concept anywhere in its API."""
    import inspect

    import intelligence.verification as module

    functions = [
        name
        for name, obj in vars(module).items()
        if inspect.isfunction(obj) and obj.__module__ == module.__name__
    ]
    assert set(functions) == {
        "verify_project_state_field",
        "verify_schedule_enabled_state",
    }


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
