"""
test_schedule_compound_progress_observer.py

Unit tests for ScheduleCompoundStepObserver (Phase 99, Batch 2 -
docs/phase_99_second_compound_template_planning.md), the second,
dormant concrete implementation of workflow.engine's
_CompoundStepObserver Protocol.

Unlike workflow.compound_progress_observer.CompoundStepObserver (which
has no dedicated direct-construction test file of its own - it is only
ever exercised indirectly through the live orchestrator's Batch 3
integration tests), this file constructs ScheduleCompoundStepObserver
directly against real collaborators (a real ScheduleStore, real
schedule tools, a real ToolExecutor, and a real
ScheduleCompoundWorkflowProgressStore) - a cleaner, fully-isolated
approach that needs no orchestrator wiring at all, matching this
batch's own "dormant, never wired" requirement.

No live wiring exists anywhere in this file - this observer is never
constructed or attached by any live request path in Batch 2.
"""

from __future__ import annotations

import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")

from approval.approval_models import ApprovalDecision  # noqa: E402
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
from workflow.schedule_compound_progress_observer import (  # noqa: E402
    ScheduleCompoundPlanMismatchError,
    ScheduleCompoundStepObserver,
)
from workflow.schedule_compound_workflow_progress_store import (  # noqa: E402
    ALLOWED_SCHEDULE_TEMPLATE_ID,
    ScheduleCompoundOverallStatus,
    ScheduleCompoundStepStatus,
    ScheduleCompoundVerificationOutcome,
    ScheduleCompoundWorkflowProgressStore,
)


@pytest.fixture()
def engine():
    from sqlalchemy import create_engine

    eng = create_engine("sqlite:///:memory:")
    initialize_database(eng)
    return eng


@pytest.fixture()
def session_factory(engine):
    return create_session_factory(engine)


@pytest.fixture()
def schedules(session_factory) -> ScheduleStore:
    return ScheduleStore(session_factory)


@pytest.fixture()
def progress_store(session_factory) -> ScheduleCompoundWorkflowProgressStore:
    return ScheduleCompoundWorkflowProgressStore(session_factory)


@pytest.fixture()
def tool_registry(schedules) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register_tool(ScheduleEnableTool(schedules))
    registry.register_tool(ScheduleVerifyEnabledStateTool(schedules))
    registry.register_tool(ScheduleShowEnabledStateTool(schedules))
    return registry


@pytest.fixture()
def security_manager() -> SecurityManager:
    return SecurityManager()


@pytest.fixture()
def tool_executor(tool_registry, security_manager) -> ToolExecutor:
    return ToolExecutor(registry=tool_registry, security_manager=security_manager, logger=None)


def _plan(tool_registry, security_manager, schedule_id: int):
    plan = _build_schedule_enable_verify_show_workflow_plan(
        "ask jarvis to: enable schedule and then check its enabled state",
        approved_schedule_id=schedule_id,
        tool_registry=tool_registry,
        security_manager=security_manager,
        session_id=None,
        catalog=CAPABILITY_CATALOG,
    )
    assert not isinstance(plan, str), plan
    return plan


def _progress_row(progress_store, workflow_id: str, schedule_id: int):
    return progress_store.create(
        workflow_id=workflow_id,
        template_id=ALLOWED_SCHEDULE_TEMPLATE_ID,
        request_id="req-1",
        schedule_id=schedule_id,
    )


def _approved_decision(request_id: str = "req-1") -> ApprovalDecision:
    """SCHEDULE_ENABLE is a YELLOW tool - ToolExecutor.execute() only
    runs it with an explicit approved ApprovalDecision, exactly as it
    would when WorkflowEngine.resume() supplies its own real decision."""
    return ApprovalDecision(request_id=request_id, approved=True, decided_by="test")


class TestConstructionRejectsUnrecognizedPlans:
    def test_accepts_the_exact_trusted_plan(
        self, tool_registry, security_manager, schedules, progress_store, tool_executor
    ) -> None:
        record = schedules.create(query="q", time_of_day="09:00")
        plan = _plan(tool_registry, security_manager, record.id)
        observer = ScheduleCompoundStepObserver(
            plan=plan, progress_store=progress_store, executor=tool_executor
        )
        assert observer.plan is plan

    def test_rejects_a_plan_with_wrong_step_count(
        self, tool_registry, security_manager, schedules, progress_store, tool_executor
    ) -> None:
        from planner.plan_models import Plan

        bad_plan = Plan(user_request="x", steps=())
        with pytest.raises(ScheduleCompoundPlanMismatchError):
            ScheduleCompoundStepObserver(
                plan=bad_plan, progress_store=progress_store, executor=tool_executor
            )

    def test_rejects_a_plan_with_differing_schedule_ids(
        self, tool_registry, security_manager, schedules, progress_store, tool_executor
    ) -> None:
        from dataclasses import replace

        record = schedules.create(query="q", time_of_day="09:00")
        plan = _plan(tool_registry, security_manager, record.id)
        tampered_step3 = replace(
            plan.steps[2], tool_input={"schedule_id": record.id + 999}
        )
        tampered_plan = replace(plan, steps=(plan.steps[0], plan.steps[1], tampered_step3))
        with pytest.raises(ScheduleCompoundPlanMismatchError):
            ScheduleCompoundStepObserver(
                plan=tampered_plan, progress_store=progress_store, executor=tool_executor
            )


class TestNormalProgression:
    def test_full_success_progression_checkpoints_every_step(
        self, tool_registry, security_manager, schedules, progress_store, tool_executor
    ) -> None:
        record = schedules.create(query="q", time_of_day="09:00")
        schedules.disable(record.id)  # start disabled so enable is a real change
        plan = _plan(tool_registry, security_manager, record.id)
        _progress_row(progress_store, "wf-full", record.id)
        observer = ScheduleCompoundStepObserver(
            plan=plan, progress_store=progress_store, executor=tool_executor
        )

        assert observer.before_step("wf-full", 0) is None
        row = progress_store.get("wf-full")
        assert row.pre_execution_enabled is False
        assert row.step_1_status is ScheduleCompoundStepStatus.IN_PROGRESS

        write_result = tool_executor.execute(
            "schedule_enable",
            {"schedule_id": record.id},
            approval_decision=_approved_decision(),
        )
        assert write_result.success is True
        assert observer.after_step("wf-full", 0, write_result) is None
        assert progress_store.get("wf-full").step_1_status is (
            ScheduleCompoundStepStatus.COMPLETED
        )

        assert observer.before_step("wf-full", 1) is None
        assert progress_store.get("wf-full").step_2_status is (
            ScheduleCompoundStepStatus.IN_PROGRESS
        )

        verify_result = tool_executor.execute(
            "schedule_verify_enabled_state", {"schedule_id": record.id}
        )
        assert verify_result.metadata["enabled_str"] == "true"
        assert observer.after_step("wf-full", 1, verify_result) is None
        row = progress_store.get("wf-full")
        assert row.step_2_verification_outcome is (
            ScheduleCompoundVerificationOutcome.VERIFIED
        )

        assert observer.before_step("wf-full", 2) is None
        show_result = tool_executor.execute(
            "schedule_show_enabled_state", {"schedule_id": record.id}
        )
        assert observer.after_step("wf-full", 2, show_result) is None
        row = progress_store.get("wf-full")
        assert row.step_3_status is ScheduleCompoundStepStatus.COMPLETED
        assert row.overall_status is ScheduleCompoundOverallStatus.COMPLETED


class TestFailureModes:
    def test_step_1_tool_failure_marks_step_1_failed(
        self, tool_registry, security_manager, schedules, progress_store, tool_executor
    ) -> None:
        record = schedules.create(query="q", time_of_day="09:00")
        plan = _plan(tool_registry, security_manager, record.id)
        _progress_row(progress_store, "wf-fail1", record.id)
        observer = ScheduleCompoundStepObserver(
            plan=plan, progress_store=progress_store, executor=tool_executor
        )
        observer.before_step("wf-fail1", 0)

        from tools.base_tool import ToolResult

        failed_result = ToolResult(
            tool_name="schedule_enable", success=False, output="", error="boom"
        )
        assert observer.after_step("wf-fail1", 0, failed_result) is None
        row = progress_store.get("wf-fail1")
        assert row.step_1_status is ScheduleCompoundStepStatus.FAILED
        assert row.overall_status is ScheduleCompoundOverallStatus.FAILED

    def test_verification_mismatch_marks_overall_failed(
        self, tool_registry, security_manager, schedules, progress_store, tool_executor
    ) -> None:
        record = schedules.create(query="q", time_of_day="09:00")
        plan = _plan(tool_registry, security_manager, record.id)
        _progress_row(progress_store, "wf-verifyfail", record.id)
        observer = ScheduleCompoundStepObserver(
            plan=plan, progress_store=progress_store, executor=tool_executor
        )
        observer.before_step("wf-verifyfail", 0)
        write_result = tool_executor.execute(
            "schedule_enable",
            {"schedule_id": record.id},
            approval_decision=_approved_decision(),
        )
        observer.after_step("wf-verifyfail", 0, write_result)
        observer.before_step("wf-verifyfail", 1)

        from tools.base_tool import ToolResult

        mismatched = ToolResult(
            tool_name="schedule_verify_enabled_state",
            success=True,
            output="",
            metadata={"schedule_id": record.id, "enabled": False, "enabled_str": "false"},
        )
        assert observer.after_step("wf-verifyfail", 1, mismatched) is None
        row = progress_store.get("wf-verifyfail")
        assert row.step_2_verification_outcome is (
            ScheduleCompoundVerificationOutcome.FAILED
        )
        assert row.overall_status is ScheduleCompoundOverallStatus.FAILED

    def test_exact_read_failure_marks_step_3_failed(
        self, tool_registry, security_manager, schedules, progress_store, tool_executor
    ) -> None:
        record = schedules.create(query="q", time_of_day="09:00")
        plan = _plan(tool_registry, security_manager, record.id)
        _progress_row(progress_store, "wf-showfail", record.id)
        observer = ScheduleCompoundStepObserver(
            plan=plan, progress_store=progress_store, executor=tool_executor
        )
        observer.before_step("wf-showfail", 0)
        write_result = tool_executor.execute(
            "schedule_enable",
            {"schedule_id": record.id},
            approval_decision=_approved_decision(),
        )
        observer.after_step("wf-showfail", 0, write_result)
        observer.before_step("wf-showfail", 1)
        verify_result = tool_executor.execute(
            "schedule_verify_enabled_state", {"schedule_id": record.id}
        )
        observer.after_step("wf-showfail", 1, verify_result)
        observer.before_step("wf-showfail", 2)

        from tools.base_tool import ToolResult

        failed_show = ToolResult(
            tool_name="schedule_show_enabled_state", success=False, output="", error="boom"
        )
        assert observer.after_step("wf-showfail", 2, failed_show) is None
        row = progress_store.get("wf-showfail")
        assert row.step_3_status is ScheduleCompoundStepStatus.FAILED
        assert row.overall_status is ScheduleCompoundOverallStatus.FAILED
        # Genuine partial completion is preserved - the enable and its
        # verification already durably succeeded.
        assert row.step_1_status is ScheduleCompoundStepStatus.COMPLETED
        assert row.step_2_verification_outcome is (
            ScheduleCompoundVerificationOutcome.VERIFIED
        )


class TestCheckpointFailClosed:
    def test_before_step_returns_a_reason_when_no_progress_row_exists(
        self, tool_registry, security_manager, schedules, progress_store, tool_executor
    ) -> None:
        """No create() was ever called for this workflow_id - the
        checkpoint cannot be durably recorded, so before_step() must
        fail closed with a bounded reason, never raise."""
        record = schedules.create(query="q", time_of_day="09:00")
        plan = _plan(tool_registry, security_manager, record.id)
        observer = ScheduleCompoundStepObserver(
            plan=plan, progress_store=progress_store, executor=tool_executor
        )
        reason = observer.before_step("wf-missing-row", 0)
        assert reason is not None
        assert "checkpoint failed" in reason

    def test_duplicate_after_step_call_fails_closed_not_raises(
        self, tool_registry, security_manager, schedules, progress_store, tool_executor
    ) -> None:
        record = schedules.create(query="q", time_of_day="09:00")
        plan = _plan(tool_registry, security_manager, record.id)
        _progress_row(progress_store, "wf-dup-after", record.id)
        observer = ScheduleCompoundStepObserver(
            plan=plan, progress_store=progress_store, executor=tool_executor
        )
        observer.before_step("wf-dup-after", 0)
        write_result = tool_executor.execute(
            "schedule_enable",
            {"schedule_id": record.id},
            approval_decision=_approved_decision(),
        )
        assert observer.after_step("wf-dup-after", 0, write_result) is None
        # Calling after_step(0, ...) a second time must fail closed
        # (mark_step_1_completed's own CAS precondition no longer
        # holds), never silently duplicate or raise out of this method.
        second_reason = observer.after_step("wf-dup-after", 0, write_result)
        assert second_reason is not None

    def test_wrong_order_before_step_1_before_step_0_fails_closed(
        self, tool_registry, security_manager, schedules, progress_store, tool_executor
    ) -> None:
        record = schedules.create(query="q", time_of_day="09:00")
        plan = _plan(tool_registry, security_manager, record.id)
        _progress_row(progress_store, "wf-wrong-order", record.id)
        observer = ScheduleCompoundStepObserver(
            plan=plan, progress_store=progress_store, executor=tool_executor
        )
        # Skipping step 0 entirely: start_step_2's own CAS precondition
        # (step_1_status COMPLETED) does not hold.
        reason = observer.before_step("wf-wrong-order", 1)
        assert reason is not None

    def test_checkpoint_failure_does_not_advance_progress_state(
        self, tool_registry, security_manager, schedules, progress_store, tool_executor
    ) -> None:
        """A failed checkpoint must leave the durable row exactly as it
        was before the failed call - resumable, never silently
        advanced or synthetically terminalized."""
        record = schedules.create(query="q", time_of_day="09:00")
        plan = _plan(tool_registry, security_manager, record.id)
        _progress_row(progress_store, "wf-no-advance", record.id)
        before = progress_store.get("wf-no-advance")
        observer = ScheduleCompoundStepObserver(
            plan=plan, progress_store=progress_store, executor=tool_executor
        )
        # Illegal: step_2 checkpoint before step 1 ever started.
        observer.before_step("wf-no-advance", 1)
        after = progress_store.get("wf-no-advance")
        assert after.step_1_status == before.step_1_status
        assert after.step_2_status == before.step_2_status
        assert after.overall_status == before.overall_status
