"""
verification.py

Exact, deterministic verification for Jarvis's verified write
workflows: the original Batch 3 workflow, "ask jarvis to: update my
project focus to X and confirm it" (Phase 90, Batch 3; contracts fixed
by docs/phase_90_implementation_plan.md, Sections 24.C.15/C.16 and the
Batch 3 planning prompt); the Phase 94, Batch 2 schedule-enable
workflow, "ask jarvis to: enable schedule <id>" (contracts fixed by
docs/phase_94_implementation_plan.md, Section 14); the Phase 95
schedule-disable workflow, "ask jarvis to: disable schedule <id>"
(contracts fixed by docs/phase_95_implementation_plan.md), which
reuses the schedule-enable verifier function unchanged, only with
expected_enabled=False and its own distinct verifier_id; and the
Phase 96 phase-update workflow, "ask jarvis to: update my project
phase to X" (contracts fixed by docs/phase_96_implementation_plan.md),
which reuses the original focus verifier function - genericized,
never duplicated - with field_name="phase" and its own distinct
verifier_id, while PROJECT_STATE_UPDATE_FOCUS's own call is completely
unaffected (field_name="focus", the same FOCUS_EXACT_MATCH_VERIFIER_ID
as always).

Responsibilities:
    - Define VerificationOutcome (VERIFIED/FAILED/UNAVAILABLE/
      NOT_REQUIRED) and VerificationResult - the only verification
      contracts any of the four workflows actually consumes.
    - Compare the write step's real, expected ProjectState field value
      (focus or phase) against the verify step's real, structured
      ToolResult.metadata[field_name] - exact string equality only,
      never a substring, fuzzy match, or AI judgement call.
    - Compare a fixed, trusted expected enabled state (True for
      enable, False for disable) against the verify step's real,
      structured ToolResult.metadata["enabled"] - exact boolean
      identity only, never a truthiness check or a comparison against
      anything model-supplied.

Does NOT:
    - Parse any tool's human-readable output text. Verification reads
      only ToolResult.metadata, which
      tools/builtin/project_state_verify_tool.py and
      tools/builtin/schedule_verify_enabled_state_tool.py already
      populate with real, structured fields.
    - Call ToolExecutor, WorkflowEngine, or any AI provider. This
      module is a pure function of already-real values to a
      VerificationResult, for any of the four workflows.
    - Retry, replan, or re-run anything. A single call answers a
      single question once; the caller (core/orchestrator.py) decides
      what to do with the answer, and never calls this twice for the
      same workflow attempt.
    - Accept a model-supplied expected value, field_name, or
      verifier_id for any verifier. The expected value/state is always
      a fixed literal supplied only by the trusted caller - never an
      argument a model output could influence.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from tools.base_tool import ToolResult

#: The one verifier Phase 90, Batch 3 defines. Fixed, not derived from
#: any model output or configuration.
FOCUS_EXACT_MATCH_VERIFIER_ID = "project_state_focus_exact_match"

#: The one verifier Phase 96 defines for the phase field. Fixed, not
#: derived from any model output or configuration - matches
#: CAPABILITY_CATALOG[CapabilityId.PROJECT_STATE_UPDATE_PHASE].verification_strategy_id
#: exactly. Reuses verify_project_state_field() unchanged in body -
#: only this distinct label, the trusted field_name="phase", and the
#: trusted expected value differ from PROJECT_STATE_UPDATE_FOCUS's own
#: call.
PROJECT_STATE_PHASE_EXACT_MATCH_VERIFIER_ID = "project_state_phase_exact_match"

#: The one verifier Phase 94, Batch 2 defines. Fixed, not derived from
#: any model output or configuration - matches
#: CAPABILITY_CATALOG[CapabilityId.SCHEDULE_ENABLE].verification_strategy_id
#: exactly.
SCHEDULE_ENABLED_EXACT_MATCH_VERIFIER_ID = "schedule_enabled_exact_match"

#: The one verifier Phase 95 defines. Fixed, not derived from any model
#: output or configuration - matches
#: CAPABILITY_CATALOG[CapabilityId.SCHEDULE_DISABLE].verification_strategy_id
#: exactly. Reuses verify_schedule_enabled_state() unchanged in body -
#: only this distinct label, and the trusted expected_enabled=False
#: literal, differ from SCHEDULE_ENABLE's own call.
SCHEDULE_DISABLED_EXACT_MATCH_VERIFIER_ID = "schedule_disabled_exact_match"

#: Evidence strings are bounded to this many characters - real, never
#: fabricated, and never a raw dictionary or secret value.
_MAX_EVIDENCE_CHARS = 200


class VerificationOutcome(Enum):
    """The four distinct verification outcomes Batch 3 can produce.

    Never collapsed into a bare boolean: FAILED (the verifier ran and
    the values genuinely differ) is a materially different fact from
    UNAVAILABLE (the verifier itself could not produce a real answer).
    """

    VERIFIED = "verified"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"
    NOT_REQUIRED = "not_required"


@dataclass(frozen=True, slots=True)
class VerificationResult:
    """The result of one verification attempt.

    Attributes:
        outcome: Which of the four VerificationOutcome values applies.
        verifier_id: Which verifier produced this result - always the
            caller's own fixed, catalog-declared verification_strategy_id
            (e.g. FOCUS_EXACT_MATCH_VERIFIER_ID,
            PROJECT_STATE_PHASE_EXACT_MATCH_VERIFIER_ID,
            SCHEDULE_ENABLED_EXACT_MATCH_VERIFIER_ID, or
            SCHEDULE_DISABLED_EXACT_MATCH_VERIFIER_ID).
        evidence: A short, real, bounded (<=200 chars) string - the
            real field value when relevant and already safe to show
            (it is the same value the ordinary response already
            names), or empty. Never fabricated, never a raw dict.
        detail: An optional short, human-readable explanation, or None.
    """

    outcome: VerificationOutcome
    verifier_id: str
    evidence: str
    detail: str | None = None


def verify_project_state_field(
    *,
    field_name: str,
    expected_value: str,
    verify_tool_result: ToolResult | None,
    verifier_id: str,
) -> VerificationResult:
    """Compare a trusted, expected ProjectState field value against the
    real, structured verify-step result (Phase 90, Batch 3's original
    "focus" verifier, genericized in Phase 96 - zero change to this
    function's own comparison logic - to also serve "phase").

    Shared verbatim by both PROJECT_STATE_UPDATE_FOCUS
    (field_name="focus") and PROJECT_STATE_UPDATE_PHASE
    (field_name="phase") - never a second near-duplicate function,
    mirroring how verify_schedule_enabled_state() already serves both
    SCHEDULE_ENABLE and SCHEDULE_DISABLE.

    Args:
        field_name: The trusted, static metadata key to read from the
            verify step's own ToolResult - always a fixed literal
            supplied by the caller (core/orchestrator.py's own
            capability-specific response-builder: "focus" or "phase"),
            never model-supplied, never inferred.
        expected_value: The write step's own, already-durable
            PlanStep.tool_input["value"] - the value Nathan's request
            asked to set.
        verify_tool_result: The verify step's real ToolResult, or None
            if the verify step never ran at all (e.g. the write step
            itself failed and the workflow stopped before step 2).
        verifier_id: The fixed, trusted verifier id to attach to the
            returned VerificationResult - always the caller's own
            catalog-declared verification_strategy_id
            (FOCUS_EXACT_MATCH_VERIFIER_ID or
            PROJECT_STATE_PHASE_EXACT_MATCH_VERIFIER_ID), never
            inferred from field_name or any other value.

    Returns:
        VERIFIED if the verify step ran successfully and its
        metadata[field_name] exactly equals expected_value. FAILED if
        the verify step ran successfully but the values genuinely
        differ. UNAVAILABLE if the verify step did not run, its
        ToolResult was not a success, or its metadata carried no usable
        value for field_name.
    """
    if verify_tool_result is None or not verify_tool_result.success:
        return VerificationResult(
            outcome=VerificationOutcome.UNAVAILABLE,
            verifier_id=verifier_id,
            evidence="",
            detail="the verification step did not complete successfully",
        )

    actual = verify_tool_result.metadata.get(field_name)
    if actual is None or not isinstance(actual, str):
        return VerificationResult(
            outcome=VerificationOutcome.UNAVAILABLE,
            verifier_id=verifier_id,
            evidence="",
            detail=f"the verification step returned no usable {field_name} value",
        )

    evidence = actual[:_MAX_EVIDENCE_CHARS]
    if actual == expected_value:
        return VerificationResult(
            outcome=VerificationOutcome.VERIFIED,
            verifier_id=verifier_id,
            evidence=evidence,
            detail=None,
        )

    return VerificationResult(
        outcome=VerificationOutcome.FAILED,
        verifier_id=verifier_id,
        evidence=evidence,
        detail="the stored value does not match the requested value",
    )


def verify_schedule_enabled_state(
    *,
    expected_enabled: bool,
    verify_tool_result: ToolResult | None,
    verifier_id: str,
) -> VerificationResult:
    """Compare a fixed, trusted expected enabled state against the
    real, structured verify-step result (Phase 94, Batch 2 -
    docs/phase_94_implementation_plan.md, Section 14; genericized over
    which boolean is expected in Phase 95 -
    docs/phase_95_implementation_plan.md - with zero change to this
    function's own comparison logic).

    Mirrors verify_focus_update()'s exact shape and outcome taxonomy,
    with the one deliberate difference the underlying field's own type
    requires: boolean identity comparison, never a string comparison.
    Shared verbatim by both SCHEDULE_ENABLE (expected_enabled=True) and
    SCHEDULE_DISABLE (expected_enabled=False) - never a second
    near-duplicate function.

    Args:
        expected_enabled: The fixed, trusted expected state - True for
            the enable workflow, False for the disable workflow. Never
            model-supplied; each caller (core/orchestrator.py's own
            capability-specific response-builder) always passes a
            fixed literal matching its own write capability's intent,
            never a value read from parsed model output.
        verify_tool_result: The verify step's real ToolResult, or None
            if the verify step never ran at all (e.g. the write step
            itself failed and the workflow stopped before step 2).
        verifier_id: The fixed, trusted verifier id to attach to the
            returned VerificationResult - always the caller's own
            catalog-declared verification_strategy_id
            (SCHEDULE_ENABLED_EXACT_MATCH_VERIFIER_ID or
            SCHEDULE_DISABLED_EXACT_MATCH_VERIFIER_ID), never inferred
            from expected_enabled or any other value.

    Returns:
        VERIFIED if the verify step ran successfully and its
        metadata["enabled"] is exactly expected_enabled. FAILED if the
        verify step ran successfully but the values genuinely differ
        (the schedule exists but is not in the expected state).
        UNAVAILABLE if the verify step did not run, its ToolResult was
        not a success (including a genuine missing-schedule failure),
        or its metadata carried no usable "enabled" key.
    """
    if verify_tool_result is None or not verify_tool_result.success:
        return VerificationResult(
            outcome=VerificationOutcome.UNAVAILABLE,
            verifier_id=verifier_id,
            evidence="",
            detail="the verification step did not complete successfully",
        )

    actual = verify_tool_result.metadata.get("enabled")
    if not isinstance(actual, bool):
        return VerificationResult(
            outcome=VerificationOutcome.UNAVAILABLE,
            verifier_id=verifier_id,
            evidence="",
            detail="the verification step returned no usable enabled state",
        )

    evidence = str(actual)
    if actual is expected_enabled:
        return VerificationResult(
            outcome=VerificationOutcome.VERIFIED,
            verifier_id=verifier_id,
            evidence=evidence,
            detail=None,
        )

    return VerificationResult(
        outcome=VerificationOutcome.FAILED,
        verifier_id=verifier_id,
        evidence=evidence,
        detail="the stored enabled state does not match the requested state",
    )
