"""
test_workflow_models.py

Focused unit tests for the Phase 15, Batch 1 workflow runtime models
(workflow/workflow_models.py): WorkflowStepOutcome and WorkflowResult.

These are models only - no WorkflowEngine, CommandRouter, or CLI test is
included here (Phase 15 Batch 1 scope).

Run with:
    pytest tests/unit/test_workflow_models.py
"""

from __future__ import annotations

import dataclasses

import pytest

from approval.approval_models import ApprovalRequest
from config.constants import SecurityTier, StepStatus
from planner.plan_models import Plan, PlanStep
from tools.base_tool import ToolResult
from workflow.workflow_models import WorkflowResult, WorkflowStepOutcome


def _step(number: int = 1, tool_name: str = "memory") -> PlanStep:
    return PlanStep(
        number=number,
        description="A workflow step.",
        action="save memory",
        tier=SecurityTier.GREEN,
        reason="Saving a memory is safe.",
        tool_name=tool_name,
        tool_input={"operation": "save", "content": "Buy milk"},
    )


def _success_result() -> ToolResult:
    return ToolResult(
        tool_name="memory",
        success=True,
        output="Saved to memory under 'general': Buy milk",
        metadata={"operation": "save", "memory_id": "1"},
    )


def _failure_result() -> ToolResult:
    return ToolResult(tool_name="memory", success=False, error="Something went wrong.")


def _blocked_result() -> ToolResult:
    return ToolResult(
        tool_name="memory_forget",
        success=False,
        error="Action blocked: bulk forgetting is not allowed.",
        blocked=True,
    )


def _needs_confirmation_result() -> ToolResult:
    return ToolResult(
        tool_name="memory_forget",
        success=False,
        error="Confirmation required before running this tool.",
        requires_confirmation=True,
    )


def _approval_request() -> ApprovalRequest:
    return ApprovalRequest(
        action="forget memory",
        reason="Forgetting a memory requires confirmation.",
        security_tier=SecurityTier.YELLOW,
    )


# --- WorkflowStepOutcome: valid states ---------------------------------------


def test_pending_outcome_carries_nothing() -> None:
    outcome = WorkflowStepOutcome(step=_step(), status=StepStatus.PENDING)
    assert outcome.tool_result is None
    assert outcome.approval_request is None


def test_running_outcome_carries_nothing() -> None:
    outcome = WorkflowStepOutcome(step=_step(), status=StepStatus.RUNNING)
    assert outcome.tool_result is None
    assert outcome.approval_request is None


def test_completed_outcome_requires_successful_result() -> None:
    outcome = WorkflowStepOutcome(
        step=_step(),
        status=StepStatus.COMPLETED,
        tool_result=_success_result(),
    )
    assert outcome.tool_result.success is True
    assert outcome.approval_request is None


def test_failed_outcome_requires_unsuccessful_result() -> None:
    outcome = WorkflowStepOutcome(
        step=_step(),
        status=StepStatus.FAILED,
        tool_result=_failure_result(),
    )
    assert outcome.tool_result.success is False


def test_failed_outcome_represents_blocked_via_tool_result_not_new_status() -> None:
    """RED-blocking uses the existing ToolResult.blocked flag - no
    StepStatus.BLOCKED value is added."""
    outcome = WorkflowStepOutcome(
        step=_step(),
        status=StepStatus.FAILED,
        tool_result=_blocked_result(),
    )
    assert outcome.tool_result.blocked is True
    assert outcome.status is StepStatus.FAILED


def test_waiting_outcome_requires_confirmation_result_and_approval_request() -> None:
    outcome = WorkflowStepOutcome(
        step=_step(),
        status=StepStatus.WAITING,
        tool_result=_needs_confirmation_result(),
        approval_request=_approval_request(),
    )
    assert outcome.tool_result.requires_confirmation is True
    assert outcome.approval_request is not None


# --- WorkflowStepOutcome: rejected/contradictory states ----------------------


def test_pending_with_tool_result_is_rejected() -> None:
    with pytest.raises(ValueError):
        WorkflowStepOutcome(
            step=_step(), status=StepStatus.PENDING, tool_result=_success_result()
        )


def test_running_with_approval_request_is_rejected() -> None:
    with pytest.raises(ValueError):
        WorkflowStepOutcome(
            step=_step(),
            status=StepStatus.RUNNING,
            approval_request=_approval_request(),
        )


def test_completed_without_tool_result_is_rejected() -> None:
    with pytest.raises(ValueError):
        WorkflowStepOutcome(step=_step(), status=StepStatus.COMPLETED)


def test_completed_with_failed_result_is_rejected() -> None:
    """Contradictory completed+error state."""
    with pytest.raises(ValueError):
        WorkflowStepOutcome(
            step=_step(), status=StepStatus.COMPLETED, tool_result=_failure_result()
        )


def test_failed_with_successful_result_is_rejected() -> None:
    """Contradictory failed+success-result state."""
    with pytest.raises(ValueError):
        WorkflowStepOutcome(
            step=_step(), status=StepStatus.FAILED, tool_result=_success_result()
        )


def test_failed_without_tool_result_is_rejected() -> None:
    with pytest.raises(ValueError):
        WorkflowStepOutcome(step=_step(), status=StepStatus.FAILED)


def test_completed_with_approval_request_is_rejected() -> None:
    """Invalid approval linkage on a non-waiting state."""
    with pytest.raises(ValueError):
        WorkflowStepOutcome(
            step=_step(),
            status=StepStatus.COMPLETED,
            tool_result=_success_result(),
            approval_request=_approval_request(),
        )


def test_failed_with_approval_request_is_rejected() -> None:
    """Invalid approval linkage on a non-waiting state."""
    with pytest.raises(ValueError):
        WorkflowStepOutcome(
            step=_step(),
            status=StepStatus.FAILED,
            tool_result=_failure_result(),
            approval_request=_approval_request(),
        )


def test_waiting_without_approval_request_is_rejected() -> None:
    with pytest.raises(ValueError):
        WorkflowStepOutcome(
            step=_step(),
            status=StepStatus.WAITING,
            tool_result=_needs_confirmation_result(),
        )


def test_waiting_with_plain_success_result_is_rejected() -> None:
    with pytest.raises(ValueError):
        WorkflowStepOutcome(
            step=_step(),
            status=StepStatus.WAITING,
            tool_result=_success_result(),
            approval_request=_approval_request(),
        )


def test_paused_status_is_rejected_in_phase_15() -> None:
    with pytest.raises(ValueError):
        WorkflowStepOutcome(step=_step(), status=StepStatus.PAUSED)


def test_skipped_status_is_rejected_in_phase_15() -> None:
    with pytest.raises(ValueError):
        WorkflowStepOutcome(step=_step(), status=StepStatus.SKIPPED)


# --- WorkflowResult: ordering, derivation -------------------------------------


def _plan(*steps: PlanStep) -> Plan:
    return Plan(user_request="remember this and show it back: Buy milk", steps=steps)


def test_all_completed_outcomes_yield_completed_overall_status() -> None:
    outcomes = (
        WorkflowStepOutcome(
            step=_step(1), status=StepStatus.COMPLETED, tool_result=_success_result()
        ),
        WorkflowStepOutcome(
            step=_step(2), status=StepStatus.COMPLETED, tool_result=_success_result()
        ),
    )
    result = WorkflowResult(
        plan=_plan(_step(1), _step(2)),
        workflow_id="wf-1",
        step_outcomes=outcomes,
    )
    assert result.overall_status is StepStatus.COMPLETED
    assert result.step_outcomes == outcomes
    assert result.pending_approval_request is None


def test_waiting_last_outcome_yields_waiting_overall_status() -> None:
    approval = _approval_request()
    outcomes = (
        WorkflowStepOutcome(
            step=_step(1), status=StepStatus.COMPLETED, tool_result=_success_result()
        ),
        WorkflowStepOutcome(
            step=_step(2),
            status=StepStatus.WAITING,
            tool_result=_needs_confirmation_result(),
            approval_request=approval,
        ),
    )
    result = WorkflowResult(
        plan=_plan(_step(1), _step(2)), workflow_id="wf-2", step_outcomes=outcomes
    )
    assert result.overall_status is StepStatus.WAITING
    assert result.pending_approval_request is approval


def test_failed_last_outcome_yields_failed_overall_status() -> None:
    outcomes = (
        WorkflowStepOutcome(
            step=_step(1), status=StepStatus.COMPLETED, tool_result=_success_result()
        ),
        WorkflowStepOutcome(
            step=_step(2), status=StepStatus.FAILED, tool_result=_failure_result()
        ),
    )
    result = WorkflowResult(
        plan=_plan(_step(1), _step(2)), workflow_id="wf-3", step_outcomes=outcomes
    )
    assert result.overall_status is StepStatus.FAILED
    assert result.pending_approval_request is None


def test_failed_middle_step_leaves_later_steps_absent() -> None:
    """Later steps are simply not present in step_outcomes - never
    synthesised as PENDING placeholders."""
    outcomes = (
        WorkflowStepOutcome(
            step=_step(1), status=StepStatus.COMPLETED, tool_result=_success_result()
        ),
        WorkflowStepOutcome(
            step=_step(2), status=StepStatus.FAILED, tool_result=_failure_result()
        ),
    )
    result = WorkflowResult(
        plan=_plan(_step(1), _step(2), _step(3)),
        workflow_id="wf-4",
        step_outcomes=outcomes,
    )
    assert len(result.step_outcomes) == 2
    assert len(result.plan.steps) == 3


def test_empty_step_outcomes_is_permitted_and_pending() -> None:
    result = WorkflowResult(plan=_plan(_step(1)), workflow_id="wf-5")
    assert result.step_outcomes == ()
    assert result.overall_status is StepStatus.PENDING
    assert result.pending_approval_request is None


def test_step_outcomes_are_not_sorted_or_deduplicated() -> None:
    """The model preserves exactly what was constructed - no reordering,
    no dedup - even a (contrived) repeated step number is passed through
    unchanged, since ordering/dedup validation belongs to a future
    WorkflowEngine, not this model."""
    outcomes = (
        WorkflowStepOutcome(
            step=_step(2), status=StepStatus.COMPLETED, tool_result=_success_result()
        ),
        WorkflowStepOutcome(
            step=_step(1), status=StepStatus.COMPLETED, tool_result=_success_result()
        ),
    )
    result = WorkflowResult(
        plan=_plan(_step(1), _step(2)), workflow_id="wf-6", step_outcomes=outcomes
    )
    assert result.step_outcomes[0].step.number == 2
    assert result.step_outcomes[1].step.number == 1


def test_non_final_waiting_outcome_is_rejected() -> None:
    """Contradictory result state: under STOP-only policy, only the last
    outcome may be non-COMPLETED."""
    outcomes = (
        WorkflowStepOutcome(
            step=_step(1),
            status=StepStatus.WAITING,
            tool_result=_needs_confirmation_result(),
            approval_request=_approval_request(),
        ),
        WorkflowStepOutcome(
            step=_step(2), status=StepStatus.COMPLETED, tool_result=_success_result()
        ),
    )
    with pytest.raises(ValueError):
        WorkflowResult(
            plan=_plan(_step(1), _step(2)), workflow_id="wf-7", step_outcomes=outcomes
        )


def test_non_final_failed_outcome_is_rejected() -> None:
    outcomes = (
        WorkflowStepOutcome(
            step=_step(1), status=StepStatus.FAILED, tool_result=_failure_result()
        ),
        WorkflowStepOutcome(
            step=_step(2), status=StepStatus.COMPLETED, tool_result=_success_result()
        ),
    )
    with pytest.raises(ValueError):
        WorkflowResult(
            plan=_plan(_step(1), _step(2)), workflow_id="wf-8", step_outcomes=outcomes
        )


def test_workflow_result_is_frozen() -> None:
    result = WorkflowResult(plan=_plan(_step(1)), workflow_id="wf-9")
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.workflow_id = "changed"  # type: ignore[misc]


def test_workflow_result_has_no_dashboard_persistence_or_scheduler_fields() -> None:
    fields = {f.name for f in dataclasses.fields(WorkflowResult)}
    assert fields == {
        "plan",
        "workflow_id",
        "step_outcomes",
        "session_id",
        "message",
    }


# --- Authority boundaries -----------------------------------------------------


def test_workflow_models_module_imports_no_executor_or_security_manager() -> None:
    """Structural proof, not just an assumption: workflow_models.py has no
    *import* of ToolExecutor, SecurityManager, or the AI reasoning types
    (the names may still appear in prose docstrings explaining what this
    model does not do)."""
    import ast

    import workflow.workflow_models as module

    with open(module.__file__, encoding="utf-8") as f:
        tree = ast.parse(f.read())

    imported_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported_names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            imported_names.update(alias.name for alias in node.names)

    assert "ToolExecutor" not in imported_names
    assert "SecurityManager" not in imported_names
    assert "AIReasoningResult" not in imported_names
    assert "AIReasoningEngine" not in imported_names


def test_plan_step_tier_has_no_bearing_on_workflow_models() -> None:
    """PlanStep.tier is carried through unchanged (display-only metadata);
    nothing in this module reads or branches on it."""
    red_step = dataclasses.replace(_step(), tier=SecurityTier.RED)
    outcome = WorkflowStepOutcome(
        step=red_step, status=StepStatus.COMPLETED, tool_result=_success_result()
    )
    # Constructible even though PlanStep.tier says RED - the model performs
    # no tier-based branching or validation at all.
    assert outcome.step.tier is SecurityTier.RED
    assert outcome.status is StepStatus.COMPLETED
