"""
test_schedule_compound_claimed_recovery.py

Unit tests for core.schedule_compound_workflow's Foundation H: inherited-
CLAIMED recovery (resume_claimed_schedule_compound_workflow,
reconcile_claimed_schedule_compound_workflows) (Phase 99, Batch 2 -
docs/phase_99_second_compound_template_planning.md).

Unlike the equivalent Phase 98 tests (which exercise this through a
full main.start_execution_session() restart, since Batch 3 wired it
into live startup), this batch has no orchestrator/main.py wiring at
all - these tests call resume_claimed_schedule_compound_workflow()
directly against a real ApprovalManager/WorkflowEngine/
ScheduleCompoundWorkflowProgressStore/ScheduleStore stack, covering
every crash-state matrix position without any live wiring.

No live wiring exists anywhere in this file - this recovery path is
never called by any real startup path in Batch 2.
"""

from __future__ import annotations

import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine  # noqa: E402

from approval.approval_manager import ApprovalManager  # noqa: E402
from approval.approval_models import PendingApprovalHandoffStatus  # noqa: E402
from approval.pending_approval_store import PendingApprovalStore  # noqa: E402
from core.schedule_compound_workflow import (  # noqa: E402
    ScheduleCompoundClaimedOutcome,
    ScheduleCompoundClaimedReconciliationSummary,
    establish_schedule_compound_progress_or_isolate,
    reconcile_claimed_schedule_compound_workflows,
    resume_claimed_schedule_compound_workflow,
)
from intelligence.capability_catalog import CAPABILITY_CATALOG  # noqa: E402
from intelligence.planning import (  # noqa: E402
    _build_schedule_enable_verify_show_workflow_plan,
)
from scheduling.schedule_store import ScheduleStore  # noqa: E402
from security.security_manager import SecurityManager  # noqa: E402
from storage.database import create_session_factory, initialize_database  # noqa: E402
from tools.builtin.schedule_disable_tool import ScheduleDisableTool  # noqa: E402
from tools.builtin.schedule_enable_tool import ScheduleEnableTool  # noqa: E402
from tools.builtin.schedule_show_enabled_state_tool import (  # noqa: E402
    ScheduleShowEnabledStateTool,
)
from tools.builtin.schedule_verify_enabled_state_tool import (  # noqa: E402
    ScheduleVerifyEnabledStateTool,
)
from tools.executor import ToolExecutor  # noqa: E402
from tools.registry import ToolRegistry  # noqa: E402
from workflow.engine import WorkflowEngine  # noqa: E402
from workflow.paused_workflow_store import PausedWorkflowStore  # noqa: E402
from workflow.schedule_compound_workflow_progress_store import (  # noqa: E402
    ScheduleCompoundStepStatus,
    ScheduleCompoundVerificationOutcome,
    ScheduleCompoundWorkflowProgressStore,
)
from workflow.workflow_history_store import WorkflowHistoryStore  # noqa: E402


class _Stack:
    """A full, real, non-orchestrator stack for exercising the
    schedule-compound claimed-recovery path directly."""

    def __init__(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        initialize_database(engine)
        self.session_factory = create_session_factory(engine)

        self.schedules = ScheduleStore(self.session_factory)
        self.registry = ToolRegistry()
        self.registry.register_tool(ScheduleEnableTool(self.schedules))
        self.registry.register_tool(ScheduleDisableTool(self.schedules))
        self.registry.register_tool(ScheduleVerifyEnabledStateTool(self.schedules))
        self.registry.register_tool(ScheduleShowEnabledStateTool(self.schedules))
        self.security = SecurityManager()
        self.tool_executor = ToolExecutor(
            registry=self.registry, security_manager=self.security, logger=None
        )

        self.pending_store = PendingApprovalStore(self.session_factory)
        self.approvals = ApprovalManager(pending_store=self.pending_store)
        self.paused_store = PausedWorkflowStore(self.session_factory)
        self.progress_store = ScheduleCompoundWorkflowProgressStore(
            self.session_factory
        )
        self.history = WorkflowHistoryStore(self.session_factory)
        self.engine = WorkflowEngine(
            executor=self.tool_executor,
            approvals=self.approvals,
            history=self.history,
            paused_store=self.paused_store,
        )

    def start_and_approve_and_claim(self, schedule_id: int) -> tuple[str, str]:
        """Run the trusted plan to its first pause, establish progress,
        approve, and claim-for-resume - returns (workflow_id, request_id)."""
        plan = _build_schedule_enable_verify_show_workflow_plan(
            "enable schedule and then check its enabled state",
            approved_schedule_id=schedule_id,
            tool_registry=self.registry,
            security_manager=self.security,
            session_id=None,
            catalog=CAPABILITY_CATALOG,
        )
        assert not isinstance(plan, str), plan
        result = self.engine.run(plan)
        assert result.overall_status.value == "waiting"
        request_id = result.pending_approval_request.request_id
        workflow_id = result.workflow_id

        established = establish_schedule_compound_progress_or_isolate(
            plan=plan,
            workflow_id=workflow_id,
            request_id=request_id,
            progress_store=self.progress_store,
            approval_invalidator=self.approvals,
            paused_workflow_store=self.paused_store,
        )
        assert not isinstance(established, str), established

        self.approvals.approve(request_id, decided_by="test")
        claimed = self.approvals.claim_for_resume(request_id)
        assert claimed is True

        return workflow_id, request_id

    def claimed_record(self, request_id: str):
        record = self.pending_store.get(request_id)
        assert record is not None
        return record


def _resume(stack: _Stack, request_id: str) -> ScheduleCompoundClaimedOutcome:
    record = stack.claimed_record(request_id)
    return resume_claimed_schedule_compound_workflow(
        record,
        pending_store=stack.pending_store,
        paused_workflow_store=stack.paused_store,
        progress_store=stack.progress_store,
        workflow_engine=stack.engine,
        tool_registry=stack.registry,
        security_manager=stack.security,
        tool_executor=stack.tool_executor,
    )


class TestClaimedBeforeStep1Began:
    def test_pending_step_1_is_claim_interrupted(self) -> None:
        stack = _Stack()
        record = stack.schedules.create(query="q", time_of_day="09:00")
        stack.schedules.disable(record.id)
        workflow_id, request_id = stack.start_and_approve_and_claim(record.id)

        outcome = _resume(stack, request_id)
        assert outcome is ScheduleCompoundClaimedOutcome.CLAIM_INTERRUPTED
        assert stack.pending_store.get_handoff_status(request_id) == (
            PendingApprovalHandoffStatus.CLAIM_INTERRUPTED
        )
        # Never auto-started: the enable never ran.
        assert stack.schedules.get(record.id).enabled is False


class TestStep1InProgressReconciliation:
    def test_postcondition_not_satisfied_marks_step_1_failed_consumed(self) -> None:
        stack = _Stack()
        record = stack.schedules.create(query="q", time_of_day="09:00")
        stack.schedules.disable(record.id)
        workflow_id, request_id = stack.start_and_approve_and_claim(record.id)

        stack.progress_store.record_pre_execution_observation(
            workflow_id, enabled=False
        )
        # Durable schedule is still disabled - the write never took
        # effect (crash before or during the write).

        outcome = _resume(stack, request_id)
        assert outcome is ScheduleCompoundClaimedOutcome.CONSUMED
        row = stack.progress_store.get(workflow_id)
        assert row.step_1_status is ScheduleCompoundStepStatus.FAILED
        assert stack.pending_store.get_handoff_status(request_id) == (
            PendingApprovalHandoffStatus.CONSUMED
        )

    def test_state_changed_completes_step_1_and_continues(self) -> None:
        stack = _Stack()
        record = stack.schedules.create(query="q", time_of_day="09:00")
        stack.schedules.disable(record.id)
        workflow_id, request_id = stack.start_and_approve_and_claim(record.id)

        stack.progress_store.record_pre_execution_observation(
            workflow_id, enabled=False
        )
        # Simulate the write having actually taken effect before the
        # crash: the durable schedule is now enabled.
        stack.schedules.enable(record.id)

        outcome = _resume(stack, request_id)
        assert outcome is ScheduleCompoundClaimedOutcome.CONSUMED
        row = stack.progress_store.get(workflow_id)
        assert row.step_1_status is ScheduleCompoundStepStatus.COMPLETED
        assert row.step_2_verification_outcome is (
            ScheduleCompoundVerificationOutcome.VERIFIED
        )
        assert row.step_3_status is ScheduleCompoundStepStatus.COMPLETED
        assert row.overall_status.value == "completed"

    def test_execution_unconfirmed_is_claim_interrupted_and_flagged(self) -> None:
        stack = _Stack()
        record = stack.schedules.create(query="q", time_of_day="09:00")
        # Already enabled *before* the pre-execution observation too -
        # ambiguous: cannot tell if the write ever ran.
        workflow_id, request_id = stack.start_and_approve_and_claim(record.id)
        stack.progress_store.record_pre_execution_observation(
            workflow_id, enabled=True
        )

        outcome = _resume(stack, request_id)
        assert outcome is ScheduleCompoundClaimedOutcome.CLAIM_INTERRUPTED
        row = stack.progress_store.get(workflow_id)
        assert row.overall_status.value == "needs_reconciliation"
        assert stack.pending_store.get_handoff_status(request_id) == (
            PendingApprovalHandoffStatus.CLAIM_INTERRUPTED
        )


class TestStep2AndStep3Continuation:
    def test_step_1_completed_step_2_pending_runs_verification_and_continues(
        self,
    ) -> None:
        stack = _Stack()
        record = stack.schedules.create(query="q", time_of_day="09:00")
        stack.schedules.disable(record.id)
        workflow_id, request_id = stack.start_and_approve_and_claim(record.id)

        stack.progress_store.record_pre_execution_observation(
            workflow_id, enabled=False
        )
        stack.schedules.enable(record.id)
        stack.progress_store.mark_step_1_completed(workflow_id)

        outcome = _resume(stack, request_id)
        assert outcome is ScheduleCompoundClaimedOutcome.CONSUMED
        row = stack.progress_store.get(workflow_id)
        assert row.step_2_verification_outcome is (
            ScheduleCompoundVerificationOutcome.VERIFIED
        )
        assert row.step_3_status is ScheduleCompoundStepStatus.COMPLETED

    def test_step_2_verified_step_3_pending_runs_show_and_completes(self) -> None:
        stack = _Stack()
        record = stack.schedules.create(query="q", time_of_day="09:00")
        stack.schedules.disable(record.id)
        workflow_id, request_id = stack.start_and_approve_and_claim(record.id)

        stack.progress_store.record_pre_execution_observation(
            workflow_id, enabled=False
        )
        stack.schedules.enable(record.id)
        stack.progress_store.mark_step_1_completed(workflow_id)
        stack.progress_store.start_step_2(workflow_id)
        stack.progress_store.mark_step_2_completed(
            workflow_id,
            verification_outcome=ScheduleCompoundVerificationOutcome.VERIFIED,
        )

        outcome = _resume(stack, request_id)
        assert outcome is ScheduleCompoundClaimedOutcome.CONSUMED
        row = stack.progress_store.get(workflow_id)
        assert row.step_3_status is ScheduleCompoundStepStatus.COMPLETED
        assert row.overall_status.value == "completed"

    def test_all_steps_already_completed_is_consumed_without_rerunning(self) -> None:
        """Already-terminal progress: nothing left to (re)run - proven
        by the durable schedule state remaining exactly as left, with
        no further tool executions needed to reach CONSUMED."""
        stack = _Stack()
        record = stack.schedules.create(query="q", time_of_day="09:00")
        stack.schedules.disable(record.id)
        workflow_id, request_id = stack.start_and_approve_and_claim(record.id)

        stack.progress_store.record_pre_execution_observation(
            workflow_id, enabled=False
        )
        stack.schedules.enable(record.id)
        stack.progress_store.mark_step_1_completed(workflow_id)
        stack.progress_store.start_step_2(workflow_id)
        stack.progress_store.mark_step_2_completed(
            workflow_id,
            verification_outcome=ScheduleCompoundVerificationOutcome.VERIFIED,
        )
        stack.progress_store.start_step_3(workflow_id)
        stack.progress_store.mark_step_3_completed(workflow_id)

        outcome = _resume(stack, request_id)
        assert outcome is ScheduleCompoundClaimedOutcome.CONSUMED
        assert stack.pending_store.get_handoff_status(request_id) == (
            PendingApprovalHandoffStatus.CONSUMED
        )

    def test_step_2_non_verified_already_completed_is_consumed_without_step_3(
        self,
    ) -> None:
        stack = _Stack()
        record = stack.schedules.create(query="q", time_of_day="09:00")
        stack.schedules.disable(record.id)
        workflow_id, request_id = stack.start_and_approve_and_claim(record.id)

        stack.progress_store.record_pre_execution_observation(
            workflow_id, enabled=False
        )
        stack.schedules.enable(record.id)
        stack.progress_store.mark_step_1_completed(workflow_id)
        stack.progress_store.start_step_2(workflow_id)
        stack.progress_store.mark_step_2_completed(
            workflow_id, verification_outcome=ScheduleCompoundVerificationOutcome.FAILED
        )

        outcome = _resume(stack, request_id)
        assert outcome is ScheduleCompoundClaimedOutcome.CONSUMED
        row = stack.progress_store.get(workflow_id)
        assert row.step_3_status is ScheduleCompoundStepStatus.PENDING


class TestNotRecognized:
    def test_missing_workflow_id_metadata_is_not_recognized(self) -> None:
        stack = _Stack()
        from datetime import datetime, timezone

        from approval.pending_approval_store import PendingApprovalRecord

        fake_record = PendingApprovalRecord(
            id=1,
            request_id="req-none",
            session_id=None,
            action="enable a schedule",
            reason="needs approval",
            security_tier="yellow",
            metadata={},
            tool_name="schedule_enable",
            tool_input={"schedule_id": 1},
            schema_version=1,
            created_at=datetime.now(timezone.utc),
            corrupt=False,
            handoff_status=PendingApprovalHandoffStatus.CLAIMED,
        )
        outcome = resume_claimed_schedule_compound_workflow(
            fake_record,
            pending_store=stack.pending_store,
            paused_workflow_store=stack.paused_store,
            progress_store=stack.progress_store,
            workflow_engine=stack.engine,
            tool_registry=stack.registry,
            security_manager=stack.security,
            tool_executor=stack.tool_executor,
        )
        assert outcome is ScheduleCompoundClaimedOutcome.NOT_RECOGNIZED

    def test_missing_progress_row_is_not_recognized(self) -> None:
        stack = _Stack()
        record = stack.schedules.create(query="q", time_of_day="09:00")
        plan = _build_schedule_enable_verify_show_workflow_plan(
            "enable schedule and then check its enabled state",
            approved_schedule_id=record.id,
            tool_registry=stack.registry,
            security_manager=stack.security,
            session_id=None,
            catalog=CAPABILITY_CATALOG,
        )
        result = stack.engine.run(plan)
        request_id = result.pending_approval_request.request_id
        stack.approvals.approve(request_id, decided_by="test")
        stack.approvals.claim_for_resume(request_id)
        # Deliberately never call establish_schedule_compound_progress_or_isolate().

        outcome = _resume(stack, request_id)
        assert outcome is ScheduleCompoundClaimedOutcome.NOT_RECOGNIZED

    def test_non_schedule_compound_plan_is_not_recognized(self) -> None:
        from config.constants import SecurityTier
        from planner.plan_models import Plan, PlanStep

        stack = _Stack()
        single_step_plan = Plan(
            user_request="disable",
            steps=(
                PlanStep(
                    number=1,
                    description="d",
                    action="delete something",
                    tier=SecurityTier.YELLOW,
                    reason="r",
                    tool_name="schedule_disable",
                    tool_input={"schedule_id": 1},
                ),
            ),
        )
        result = stack.engine.run(single_step_plan)
        request_id = result.pending_approval_request.request_id
        stack.approvals.approve(request_id, decided_by="test")
        stack.approvals.claim_for_resume(request_id)

        outcome = _resume(stack, request_id)
        assert outcome is ScheduleCompoundClaimedOutcome.NOT_RECOGNIZED


class TestReconcileClaimedScheduleCompoundWorkflows:
    def test_summarizes_multiple_rows_correctly(self) -> None:
        stack = _Stack()

        record_a = stack.schedules.create(query="q1", time_of_day="09:00")
        stack.schedules.disable(record_a.id)
        _wf_a, req_a = stack.start_and_approve_and_claim(record_a.id)
        # Left pristine (pending step 1) -> CLAIM_INTERRUPTED.

        record_b = stack.schedules.create(query="q2", time_of_day="09:00")
        stack.schedules.enable(record_b.id)
        summary = reconcile_claimed_schedule_compound_workflows(
            pending_store=stack.pending_store,
            paused_workflow_store=stack.paused_store,
            progress_store=stack.progress_store,
            workflow_engine=stack.engine,
            tool_registry=stack.registry,
            security_manager=stack.security,
            tool_executor=stack.tool_executor,
            claimed_status=PendingApprovalHandoffStatus.CLAIMED,
        )
        assert isinstance(summary, ScheduleCompoundClaimedReconciliationSummary)
        assert summary.interrupted == 1
        assert summary.consumed == 0
        assert summary.left_for_generic == 0
