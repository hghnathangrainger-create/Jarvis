"""
test_schedule_compound_result_translator.py

Unit tests for
core.schedule_compound_workflow.translate_schedule_compound_workflow_result()
(Phase 99, Batch 2, Foundation I -
docs/phase_99_second_compound_template_planning.md): the dormant
translator for the exact six outcomes a schedule-compound WorkflowResult
may produce, mirroring test_compound_result_translator.py's own
established pattern.

Dormant: never wired into any live user path in Batch 2 - these tests
exercise it directly with hand-built WorkflowResult/WorkflowStepOutcome
objects.
"""

from __future__ import annotations

from approval.approval_models import ApprovalRequest
from config.constants import SecurityTier, StepStatus
from core.schedule_compound_workflow import (
    ScheduleCompoundResultKind,
    translate_schedule_compound_workflow_result,
)
from planner.plan_models import Plan, PlanStep
from tools.base_tool import ToolResult
from workflow.workflow_models import WorkflowResult, WorkflowStepOutcome

_WRITE_STEP = PlanStep(
    number=1,
    description="write",
    action="delete something",
    tier=SecurityTier.YELLOW,
    reason="needs approval",
    tool_name="schedule_enable",
    tool_input={"schedule_id": 7},
)
_VERIFY_STEP = PlanStep(
    number=2,
    description="verify",
    action="read something",
    tier=SecurityTier.GREEN,
    reason="ok",
    tool_name="schedule_verify_enabled_state",
    tool_input={"schedule_id": 7},
)
_SHOW_STEP = PlanStep(
    number=3,
    description="show",
    action="read something",
    tier=SecurityTier.GREEN,
    reason="ok",
    tool_name="schedule_show_enabled_state",
    tool_input={"schedule_id": 7},
    requires_verified_predecessor=True,
    verification_field_name="enabled_str",
    verification_expected_value="true",
)
_PLAN = Plan(
    user_request="enable schedule and then show", steps=(_WRITE_STEP, _VERIFY_STEP, _SHOW_STEP)
)


def _result(*outcomes: WorkflowStepOutcome) -> WorkflowResult:
    return WorkflowResult(plan=_PLAN, workflow_id="wf-1", step_outcomes=outcomes)


def _completed(step: PlanStep, tool_result: ToolResult) -> WorkflowStepOutcome:
    return WorkflowStepOutcome(step=step, status=StepStatus.COMPLETED, tool_result=tool_result)


def _failed(step: PlanStep, tool_result: ToolResult) -> WorkflowStepOutcome:
    return WorkflowStepOutcome(step=step, status=StepStatus.FAILED, tool_result=tool_result)


class TestFullSuccess:
    def test_all_three_steps_completed_and_verified(self) -> None:
        write_result = ToolResult(tool_name="schedule_enable", success=True, output="ok")
        verify_result = ToolResult(
            tool_name="schedule_verify_enabled_state",
            success=True,
            output="ok",
            metadata={"schedule_id": 7, "enabled": True, "enabled_str": "true"},
        )
        show_result = ToolResult(
            tool_name="schedule_show_enabled_state",
            success=True,
            output="Schedule 7 is currently enabled.",
        )
        result = _result(
            _completed(_WRITE_STEP, write_result),
            _completed(_VERIFY_STEP, verify_result),
            _completed(_SHOW_STEP, show_result),
        )
        response, kind = translate_schedule_compound_workflow_result(result)
        assert kind is ScheduleCompoundResultKind.FULL_SUCCESS
        assert response.success is True
        assert "7" in response.message
        assert "Schedule 7 is currently enabled" in response.message


class TestEnableFailure:
    def test_write_step_failed(self) -> None:
        write_result = ToolResult(
            tool_name="schedule_enable", success=False, error="db error"
        )
        result = _result(_failed(_WRITE_STEP, write_result))
        response, kind = translate_schedule_compound_workflow_result(result)
        assert kind is ScheduleCompoundResultKind.ENABLE_FAILURE
        assert response.success is False
        assert "did not complete" in response.message

    def test_no_outcomes_at_all(self) -> None:
        result = _result()
        response, kind = translate_schedule_compound_workflow_result(result)
        assert kind is ScheduleCompoundResultKind.ENABLE_FAILURE
        assert response.success is False

    def test_still_pending_approval_never_claims_success(self) -> None:
        pending_result = ToolResult(
            tool_name="schedule_enable",
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
        response, kind = translate_schedule_compound_workflow_result(result)
        assert kind is ScheduleCompoundResultKind.ENABLE_FAILURE
        assert response.success is False


class TestVerificationMismatch:
    def test_verifier_ran_but_enabled_str_is_false(self) -> None:
        write_result = ToolResult(tool_name="schedule_enable", success=True, output="ok")
        verify_result = ToolResult(
            tool_name="schedule_verify_enabled_state",
            success=True,
            output="ok",
            metadata={"schedule_id": 7, "enabled": False, "enabled_str": "false"},
        )
        result = _result(
            _completed(_WRITE_STEP, write_result), _completed(_VERIFY_STEP, verify_result)
        )
        response, kind = translate_schedule_compound_workflow_result(result)
        assert kind is ScheduleCompoundResultKind.VERIFICATION_MISMATCH
        assert response.success is False
        assert "not confirmed" in response.message


class TestVerificationUnavailable:
    def test_verifier_tool_itself_failed(self) -> None:
        write_result = ToolResult(tool_name="schedule_enable", success=True, output="ok")
        result = _result(_completed(_WRITE_STEP, write_result))
        response, kind = translate_schedule_compound_workflow_result(result)
        assert kind is ScheduleCompoundResultKind.VERIFICATION_UNAVAILABLE
        assert response.success is False

    def test_verifier_returned_no_usable_enabled_str_value(self) -> None:
        write_result = ToolResult(tool_name="schedule_enable", success=True, output="ok")
        verify_result = ToolResult(
            tool_name="schedule_verify_enabled_state",
            success=True,
            output="ok",
            metadata={"schedule_id": 7, "enabled": True},
        )
        result = _result(
            _completed(_WRITE_STEP, write_result), _completed(_VERIFY_STEP, verify_result)
        )
        response, kind = translate_schedule_compound_workflow_result(result)
        assert kind is ScheduleCompoundResultKind.VERIFICATION_UNAVAILABLE


class TestFinalShowFailure:
    def test_verified_but_show_failed(self) -> None:
        write_result = ToolResult(tool_name="schedule_enable", success=True, output="ok")
        verify_result = ToolResult(
            tool_name="schedule_verify_enabled_state",
            success=True,
            output="ok",
            metadata={"schedule_id": 7, "enabled": True, "enabled_str": "true"},
        )
        show_result = ToolResult(
            tool_name="schedule_show_enabled_state", success=False, error="read failed"
        )
        result = _result(
            _completed(_WRITE_STEP, write_result),
            _completed(_VERIFY_STEP, verify_result),
            _failed(_SHOW_STEP, show_result),
        )
        response, kind = translate_schedule_compound_workflow_result(result)
        assert kind is ScheduleCompoundResultKind.FINAL_SHOW_FAILURE
        assert response.success is False
        assert "verified" in response.message.casefold()
        assert "final enabled-state read failed" in response.message


class TestInterrupted:
    def test_no_workflow_result_reports_interrupted_honestly(self) -> None:
        response, kind = translate_schedule_compound_workflow_result(None)
        assert kind is ScheduleCompoundResultKind.INTERRUPTED
        assert response.success is False
        assert "replay was prohibited" in response.message
        assert "Traceback" not in response.message


class TestNoUnrestrictedContentLeaks:
    def test_response_never_contains_raw_stack_trace_markers(self) -> None:
        for candidate_result in (
            None,
            _result(_failed(_WRITE_STEP, ToolResult(tool_name="x", success=False, error="e"))),
        ):
            response, _kind = translate_schedule_compound_workflow_result(candidate_result)
            assert "Traceback (most recent call last)" not in response.message


class TestNeverAssumesEnabledMerelyBecauseApproved:
    def test_verification_mismatch_message_does_not_claim_confirmed(self) -> None:
        """Explicit boundary: the translator must never assume the
        schedule is enabled merely because the user approved the
        request - only the real verifier's own durable evidence
        counts."""
        write_result = ToolResult(tool_name="schedule_enable", success=True, output="ok")
        verify_result = ToolResult(
            tool_name="schedule_verify_enabled_state",
            success=True,
            output="ok",
            metadata={"schedule_id": 7, "enabled": False, "enabled_str": "false"},
        )
        result = _result(
            _completed(_WRITE_STEP, write_result), _completed(_VERIFY_STEP, verify_result)
        )
        response, _kind = translate_schedule_compound_workflow_result(result)
        assert response.success is False
        assert "not confirmed" in response.message
        assert "not enabled" in response.message
