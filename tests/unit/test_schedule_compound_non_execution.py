"""
test_schedule_compound_non_execution.py

Unit tests for
core.schedule_compound_workflow.terminalize_declined_or_expired_schedule_compound_progress()
(Phase 99, Batch 2, Foundation D - docs/phase_99_second_compound_template_planning.md):
the honest, pre-execution non-execution terminalization path for a
declined or expired schedule-compound approval, mirroring
test_phase98_batch3_live_compound_activation.py's own decline/expiry
non-execution scenarios, adapted to call the function directly against
real stores (no orchestrator wiring exists for this template in Batch
2).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine  # noqa: E402

from approval.approval_manager import ApprovalManager  # noqa: E402
from approval.approval_models import PendingApprovalHandoffStatus  # noqa: E402
from approval.pending_approval_store import PendingApprovalStore  # noqa: E402
from config.constants import SecurityTier  # noqa: E402
from core.schedule_compound_workflow import (  # noqa: E402
    establish_schedule_compound_progress_or_isolate,
    terminalize_declined_or_expired_schedule_compound_progress,
)
from intelligence.capability_catalog import CAPABILITY_CATALOG  # noqa: E402
from intelligence.planning import (  # noqa: E402
    _build_schedule_enable_verify_show_workflow_plan,
)
from scheduling.schedule_store import ScheduleStore  # noqa: E402
from security.security_manager import SecurityManager  # noqa: E402
from storage.database import create_session_factory, initialize_database  # noqa: E402
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
    ScheduleCompoundOverallStatus,
    ScheduleCompoundStepStatus,
    ScheduleCompoundWorkflowProgressStore,
)


class _Stack:
    def __init__(self, *, timeout_seconds: int | None = None, clock=None) -> None:
        engine = create_engine("sqlite:///:memory:")
        initialize_database(engine)
        self.session_factory = create_session_factory(engine)

        self.schedules = ScheduleStore(self.session_factory)
        self.registry = ToolRegistry()
        self.registry.register_tool(ScheduleEnableTool(self.schedules))
        self.registry.register_tool(ScheduleVerifyEnabledStateTool(self.schedules))
        self.registry.register_tool(ScheduleShowEnabledStateTool(self.schedules))
        self.security = SecurityManager()
        self.tool_executor = ToolExecutor(
            registry=self.registry, security_manager=self.security, logger=None
        )

        self.pending_store = PendingApprovalStore(self.session_factory)
        self.approvals = ApprovalManager(
            pending_store=self.pending_store,
            timeout_seconds=timeout_seconds,
            clock=clock,
        )
        self.paused_store = PausedWorkflowStore(self.session_factory)
        self.progress_store = ScheduleCompoundWorkflowProgressStore(
            self.session_factory
        )
        self.engine = WorkflowEngine(
            executor=self.tool_executor,
            approvals=self.approvals,
            paused_store=self.paused_store,
        )

    def pause_and_establish(self, schedule_id: int) -> tuple[str, str]:
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
        return workflow_id, request_id


class TestDeclineNonExecution:
    def test_decline_terminalizes_as_not_executed_with_zero_execution(self) -> None:
        stack = _Stack()
        record = stack.schedules.create(query="q", time_of_day="09:00")
        stack.schedules.disable(record.id)
        workflow_id, request_id = stack.pause_and_establish(record.id)

        stack.approvals.decline(request_id, decided_by="test")

        terminalized = terminalize_declined_or_expired_schedule_compound_progress(
            pending_store=stack.pending_store,
            progress_store=stack.progress_store,
            declined_status=PendingApprovalHandoffStatus.DECLINED,
            expired_status=PendingApprovalHandoffStatus.EXPIRED,
        )
        assert terminalized == 1

        progress = stack.progress_store.get(workflow_id)
        assert progress.overall_status is ScheduleCompoundOverallStatus.NOT_EXECUTED
        assert progress.step_1_status is ScheduleCompoundStepStatus.PENDING
        assert progress.step_2_status is ScheduleCompoundStepStatus.PENDING
        assert progress.step_3_status is ScheduleCompoundStepStatus.PENDING
        assert progress.pre_execution_enabled is None

        # Zero execution: the schedule was never actually enabled.
        assert stack.schedules.get(record.id).enabled is False

    def test_idempotent_on_repeat_call(self) -> None:
        stack = _Stack()
        record = stack.schedules.create(query="q", time_of_day="09:00")
        workflow_id, request_id = stack.pause_and_establish(record.id)
        stack.approvals.decline(request_id, decided_by="test")

        first = terminalize_declined_or_expired_schedule_compound_progress(
            pending_store=stack.pending_store,
            progress_store=stack.progress_store,
            declined_status=PendingApprovalHandoffStatus.DECLINED,
            expired_status=PendingApprovalHandoffStatus.EXPIRED,
        )
        second = terminalize_declined_or_expired_schedule_compound_progress(
            pending_store=stack.pending_store,
            progress_store=stack.progress_store,
            declined_status=PendingApprovalHandoffStatus.DECLINED,
            expired_status=PendingApprovalHandoffStatus.EXPIRED,
        )
        assert first == 1
        assert second == 0

    def test_rejected_after_execution_has_started(self) -> None:
        """A row where step 1 already began (e.g. a race between decline
        and an in-flight resume) must never be silently overwritten as
        NOT_EXECUTED - mark_not_executed_before_start()'s own CAS
        precondition refuses, and this function silently skips it."""
        stack = _Stack()
        record = stack.schedules.create(query="q", time_of_day="09:00")
        workflow_id, request_id = stack.pause_and_establish(record.id)
        stack.progress_store.record_pre_execution_observation(
            workflow_id, enabled=True
        )
        stack.approvals.decline(request_id, decided_by="test")

        terminalized = terminalize_declined_or_expired_schedule_compound_progress(
            pending_store=stack.pending_store,
            progress_store=stack.progress_store,
            declined_status=PendingApprovalHandoffStatus.DECLINED,
            expired_status=PendingApprovalHandoffStatus.EXPIRED,
        )
        assert terminalized == 0
        progress = stack.progress_store.get(workflow_id)
        assert progress.overall_status is ScheduleCompoundOverallStatus.IN_PROGRESS


class TestExpiryNonExecution:
    def test_expiry_leaves_progress_pristine_until_the_repair_pass_runs(self) -> None:
        """Expiry never goes through resume() at all - the progress row
        is left exactly PENDING/pristine at the moment of expiry itself;
        only the repair pass, exercised below, ever terminalizes it."""
        start_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
        clock_box = {"now": start_time}
        stack = _Stack(timeout_seconds=60, clock=lambda: clock_box["now"])
        record = stack.schedules.create(query="q", time_of_day="09:00")
        workflow_id, request_id = stack.pause_and_establish(record.id)

        clock_box["now"] = start_time + timedelta(seconds=61)
        assert stack.approvals.has_pending(request_id) is False
        progress = stack.progress_store.get(workflow_id)
        assert progress.overall_status is ScheduleCompoundOverallStatus.PENDING

    def test_expiry_is_terminalized_by_the_repair_pass(self) -> None:
        start_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
        clock_box = {"now": start_time}
        stack = _Stack(timeout_seconds=60, clock=lambda: clock_box["now"])
        record = stack.schedules.create(query="q", time_of_day="09:00")
        workflow_id, request_id = stack.pause_and_establish(record.id)

        clock_box["now"] = start_time + timedelta(seconds=61)
        assert stack.approvals.has_pending(request_id) is False
        assert stack.approvals.handoff_status_for(request_id) == (
            PendingApprovalHandoffStatus.EXPIRED
        )

        terminalized = terminalize_declined_or_expired_schedule_compound_progress(
            pending_store=stack.pending_store,
            progress_store=stack.progress_store,
            declined_status=PendingApprovalHandoffStatus.DECLINED,
            expired_status=PendingApprovalHandoffStatus.EXPIRED,
        )
        assert terminalized == 1
        progress = stack.progress_store.get(workflow_id)
        assert progress.overall_status is ScheduleCompoundOverallStatus.NOT_EXECUTED


class TestUnrelatedRowsUntouched:
    def test_untouched_when_workflow_id_missing(self) -> None:
        stack = _Stack()
        stack.approvals.create_request(
            "some plain action", "needs approval", SecurityTier.YELLOW
        )
        request_id_list = list(
            stack.pending_store.list_by_handoff_status(
                PendingApprovalHandoffStatus.PENDING
            )
        )
        assert len(request_id_list) == 1
        stack.approvals.decline(request_id_list[0].request_id, decided_by="test")

        terminalized = terminalize_declined_or_expired_schedule_compound_progress(
            pending_store=stack.pending_store,
            progress_store=stack.progress_store,
            declined_status=PendingApprovalHandoffStatus.DECLINED,
            expired_status=PendingApprovalHandoffStatus.EXPIRED,
        )
        assert terminalized == 0

    def test_untouched_when_progress_row_missing(self) -> None:
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
        # Deliberately never establish progress.
        stack.approvals.decline(request_id, decided_by="test")

        terminalized = terminalize_declined_or_expired_schedule_compound_progress(
            pending_store=stack.pending_store,
            progress_store=stack.progress_store,
            declined_status=PendingApprovalHandoffStatus.DECLINED,
            expired_status=PendingApprovalHandoffStatus.EXPIRED,
        )
        assert terminalized == 0
