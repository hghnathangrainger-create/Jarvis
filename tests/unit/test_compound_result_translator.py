"""
test_compound_result_translator.py

Unit tests for core.compound_workflow.translate_compound_workflow_result()
(Phase 98, Batch 2, Foundation I -
docs/phase_98_live_compound_reentry_plan.md): the dormant translator
for the exact six outcomes a compound WorkflowResult may produce.

Dormant: never wired into any live user path in Batch 2 (see
test_phase98_batch2_dormant_isolation.py) - these tests exercise it
directly with hand-built WorkflowResult/WorkflowStepOutcome objects.
"""

from __future__ import annotations

from approval.approval_models import ApprovalRequest
from config.constants import SecurityTier, StepStatus
from core.compound_workflow import CompoundResultKind, translate_compound_workflow_result
from planner.plan_models import Plan, PlanStep
from tools.base_tool import ToolResult
from workflow.workflow_models import WorkflowResult, WorkflowStepOutcome

_WRITE_STEP = PlanStep(
    number=1,
    description="write",
    action="delete something",
    tier=SecurityTier.YELLOW,
    reason="needs approval",
    tool_name="project_state_update",
    tool_input={"field": "phase", "value": "target-value"},
)
_VERIFY_STEP = PlanStep(
    number=2,
    description="verify",
    action="read something",
    tier=SecurityTier.GREEN,
    reason="ok",
    tool_name="project_state_verify",
    tool_input={},
)
_SHOW_STEP = PlanStep(
    number=3,
    description="show",
    action="read something",
    tier=SecurityTier.GREEN,
    reason="ok",
    tool_name="project_state_show",
    tool_input={},
    requires_verified_predecessor=True,
    verification_field_name="phase",
    verification_expected_value="target-value",
)
_PLAN = Plan(user_request="update phase and then show", steps=(_WRITE_STEP, _VERIFY_STEP, _SHOW_STEP))


def _result(*outcomes: WorkflowStepOutcome) -> WorkflowResult:
    return WorkflowResult(plan=_PLAN, workflow_id="wf-1", step_outcomes=outcomes)


def _completed(step: PlanStep, tool_result: ToolResult) -> WorkflowStepOutcome:
    return WorkflowStepOutcome(step=step, status=StepStatus.COMPLETED, tool_result=tool_result)


def _failed(step: PlanStep, tool_result: ToolResult) -> WorkflowStepOutcome:
    return WorkflowStepOutcome(step=step, status=StepStatus.FAILED, tool_result=tool_result)


class TestFullSuccess:
    def test_all_three_steps_completed_and_verified(self) -> None:
        write_result = ToolResult(tool_name="project_state_update", success=True, output="ok")
        verify_result = ToolResult(
            tool_name="project_state_verify",
            success=True,
            output="ok",
            metadata={"phase": "target-value"},
        )
        show_result = ToolResult(
            tool_name="project_state_show", success=True, output="Jarvis Project State: ..."
        )
        result = _result(
            _completed(_WRITE_STEP, write_result),
            _completed(_VERIFY_STEP, verify_result),
            _completed(_SHOW_STEP, show_result),
        )
        response, kind = translate_compound_workflow_result(result)
        assert kind is CompoundResultKind.FULL_SUCCESS
        assert response.success is True
        assert "target-value" in response.message
        assert "Jarvis Project State" in response.message


class TestUpdateFailure:
    def test_write_step_failed(self) -> None:
        write_result = ToolResult(
            tool_name="project_state_update", success=False, error="db error"
        )
        result = _result(_failed(_WRITE_STEP, write_result))
        response, kind = translate_compound_workflow_result(result)
        assert kind is CompoundResultKind.UPDATE_FAILURE
        assert response.success is False
        assert "did not complete" in response.message

    def test_no_outcomes_at_all(self) -> None:
        result = _result()
        response, kind = translate_compound_workflow_result(result)
        assert kind is CompoundResultKind.UPDATE_FAILURE
        assert response.success is False

    def test_still_pending_approval_never_claims_success(self) -> None:
        pending_result = ToolResult(
            tool_name="project_state_update",
            success=False,
            requires_confirmation=True,
            error="This action requires your confirmation.",
        )
        outcome = WorkflowStepOutcome(
            step=_WRITE_STEP,
            status=StepStatus.WAITING,
            tool_result=pending_result,
            approval_request=ApprovalRequest(
                action="a", reason="r", security_tier=SecurityTier.YELLOW
            ),
        )
        result = _result(outcome)
        response, kind = translate_compound_workflow_result(result)
        assert kind is CompoundResultKind.UPDATE_FAILURE
        assert response.success is False


class TestVerificationMismatch:
    def test_verifier_ran_but_value_differs(self) -> None:
        write_result = ToolResult(tool_name="project_state_update", success=True, output="ok")
        verify_result = ToolResult(
            tool_name="project_state_verify",
            success=True,
            output="ok",
            metadata={"phase": "a-different-value"},
        )
        result = _result(
            _completed(_WRITE_STEP, write_result), _completed(_VERIFY_STEP, verify_result)
        )
        response, kind = translate_compound_workflow_result(result)
        assert kind is CompoundResultKind.VERIFICATION_MISMATCH
        assert response.success is False
        assert "not confirmed" in response.message


class TestVerificationUnavailable:
    def test_verifier_tool_itself_failed(self) -> None:
        write_result = ToolResult(tool_name="project_state_update", success=True, output="ok")
        # verify_outcome absent entirely (workflow stopped right after
        # the write, before a verify outcome was ever recorded).
        result = _result(_completed(_WRITE_STEP, write_result))
        response, kind = translate_compound_workflow_result(result)
        assert kind is CompoundResultKind.VERIFICATION_UNAVAILABLE
        assert response.success is False

    def test_verifier_returned_no_usable_phase_value(self) -> None:
        write_result = ToolResult(tool_name="project_state_update", success=True, output="ok")
        verify_result = ToolResult(
            tool_name="project_state_verify", success=True, output="ok", metadata={}
        )
        result = _result(
            _completed(_WRITE_STEP, write_result), _completed(_VERIFY_STEP, verify_result)
        )
        response, kind = translate_compound_workflow_result(result)
        assert kind is CompoundResultKind.VERIFICATION_UNAVAILABLE


class TestFinalShowFailure:
    def test_verified_but_show_failed(self) -> None:
        write_result = ToolResult(tool_name="project_state_update", success=True, output="ok")
        verify_result = ToolResult(
            tool_name="project_state_verify",
            success=True,
            output="ok",
            metadata={"phase": "target-value"},
        )
        show_result = ToolResult(
            tool_name="project_state_show", success=False, error="read failed"
        )
        result = _result(
            _completed(_WRITE_STEP, write_result),
            _completed(_VERIFY_STEP, verify_result),
            _failed(_SHOW_STEP, show_result),
        )
        response, kind = translate_compound_workflow_result(result)
        assert kind is CompoundResultKind.FINAL_SHOW_FAILURE
        assert response.success is False
        assert "verified" in response.message.casefold()
        assert "final project-state read failed" in response.message


class TestInterrupted:
    def test_no_workflow_result_reports_interrupted_honestly(self) -> None:
        response, kind = translate_compound_workflow_result(None)
        assert kind is CompoundResultKind.INTERRUPTED
        assert response.success is False
        assert "replay was prohibited" in response.message
        assert "Traceback" not in response.message


class TestNoUnrestrictedContentLeaks:
    def test_response_never_contains_raw_stack_trace_markers(self) -> None:
        for candidate_result in (
            None,
            _result(_failed(_WRITE_STEP, ToolResult(tool_name="x", success=False, error="e"))),
        ):
            response, _kind = translate_compound_workflow_result(candidate_result)
            assert "Traceback (most recent call last)" not in response.message
