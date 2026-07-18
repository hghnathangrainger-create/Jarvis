"""
verification.py

Exact, deterministic verification for Jarvis's one Batch 3 write
workflow: "ask jarvis to: update my project focus to X and confirm
it" (Phase 90, Batch 3; contracts fixed by
docs/phase_90_implementation_plan.md, Sections 24.C.15/C.16 and the
Batch 3 planning prompt).

Responsibilities:
    - Define VerificationOutcome (VERIFIED/FAILED/UNAVAILABLE/
      NOT_REQUIRED) and VerificationResult - the only verification
      contracts Batch 3 actually consumes.
    - Compare the write step's real, expected focus value against the
      verify step's real, structured ToolResult.metadata["focus"] -
      exact string equality only, never a substring, fuzzy match, or
      AI judgement call.

Does NOT:
    - Parse any tool's human-readable output text. Verification reads
      only ToolResult.metadata, which
      tools/builtin/project_state_verify_tool.py already populates
      with real, structured fields.
    - Call ToolExecutor, WorkflowEngine, or any AI provider. This
      module is a pure function of two already-real values to a
      VerificationResult.
    - Retry, replan, or re-run anything. A single call answers a
      single question once; the caller (core/orchestrator.py) decides
      what to do with the answer, and never calls this twice for the
      same workflow attempt.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from tools.base_tool import ToolResult

#: The one verifier this phase defines. Fixed, not derived from any
#: model output or configuration.
FOCUS_EXACT_MATCH_VERIFIER_ID = "project_state_focus_exact_match"

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
        verifier_id: Which verifier produced this result - always
            FOCUS_EXACT_MATCH_VERIFIER_ID for Batch 3's one workflow.
        evidence: A short, real, bounded (<=200 chars) string - the
            real focus value when relevant and already safe to show
            (it is the same value the ordinary response already
            names), or empty. Never fabricated, never a raw dict.
        detail: An optional short, human-readable explanation, or None.
    """

    outcome: VerificationOutcome
    verifier_id: str
    evidence: str
    detail: str | None = None


def verify_focus_update(
    *, expected_value: str, verify_tool_result: ToolResult | None
) -> VerificationResult:
    """Compare the real expected focus value against the real,
    structured verify-step result.

    Args:
        expected_value: The write step's own, already-durable
            PlanStep.tool_input["value"] - the value Nathan's request
            asked to set.
        verify_tool_result: The verify step's real ToolResult, or None
            if the verify step never ran at all (e.g. the write step
            itself failed and the workflow stopped before step 2).

    Returns:
        VERIFIED if the verify step ran successfully and its
        metadata["focus"] exactly equals expected_value. FAILED if the
        verify step ran successfully but the values genuinely differ.
        UNAVAILABLE if the verify step did not run, its ToolResult was
        not a success, or its metadata carried no usable "focus" key.
    """
    if verify_tool_result is None or not verify_tool_result.success:
        return VerificationResult(
            outcome=VerificationOutcome.UNAVAILABLE,
            verifier_id=FOCUS_EXACT_MATCH_VERIFIER_ID,
            evidence="",
            detail="the verification step did not complete successfully",
        )

    actual = verify_tool_result.metadata.get("focus")
    if actual is None or not isinstance(actual, str):
        return VerificationResult(
            outcome=VerificationOutcome.UNAVAILABLE,
            verifier_id=FOCUS_EXACT_MATCH_VERIFIER_ID,
            evidence="",
            detail="the verification step returned no usable focus value",
        )

    evidence = actual[:_MAX_EVIDENCE_CHARS]
    if actual == expected_value:
        return VerificationResult(
            outcome=VerificationOutcome.VERIFIED,
            verifier_id=FOCUS_EXACT_MATCH_VERIFIER_ID,
            evidence=evidence,
            detail=None,
        )

    return VerificationResult(
        outcome=VerificationOutcome.FAILED,
        verifier_id=FOCUS_EXACT_MATCH_VERIFIER_ID,
        evidence=evidence,
        detail="the stored value does not match the requested value",
    )
