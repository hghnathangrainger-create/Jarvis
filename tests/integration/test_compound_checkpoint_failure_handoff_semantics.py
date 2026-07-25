"""
test_compound_checkpoint_failure_handoff_semantics.py

Real, on-disk-database integration tests proving the exact handoff-
and progress-level semantics required by the Phase 98, Batch 2
acceptance correction (docs/phase_98_live_compound_reentry_plan.md,
"Checkpoint-Failure Handoff and Terminal Semantics"): a checkpoint
infrastructure failure must never advance the durable approval handoff
toward CONSUMED, must never fabricate a VerificationOutcome, and must
leave the workflow reconcilable by compound-specific startup recovery
afterward.

These go one level beyond test_workflow_engine_compound_checkpoints.py
(which proves the engine's own WorkflowResult/paused-state contract in
isolation): here, a real PendingApprovalStore row is durably CLAIMED
first (mirroring exactly what a live claim-before-resume attempt would
have done), then a checkpoint failure is induced, and the *handoff's*
own durable state is inspected directly - proving CLAIMED never
silently becomes CONSUMED, and that resume_claimed_compound_workflow()
can still make real progress on the row afterward.
"""

from __future__ import annotations

from pathlib import Path

import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")

from approval.approval_manager import ApprovalManager  # noqa: E402
from approval.approval_models import PendingApprovalHandoffStatus  # noqa: E402
from approval.pending_approval_store import PendingApprovalStore  # noqa: E402
from core.compound_workflow import (  # noqa: E402
    CompoundClaimedOutcome,
    establish_compound_progress_or_isolate,
    resume_claimed_compound_workflow,
)
from intelligence.capability_catalog import CAPABILITY_CATALOG  # noqa: E402
from intelligence.planning import (  # noqa: E402
    _build_phase_update_verify_show_workflow_plan,
)
from planner.plan_models import Plan  # noqa: E402
from project_state.project_state_store import ProjectStateStore  # noqa: E402
from security.security_manager import SecurityManager  # noqa: E402
from storage.database import create_session_factory, initialize_database  # noqa: E402
from tools.base_tool import BaseTool, ToolRequest, ToolResult  # noqa: E402
from tools.builtin.project_state_show_tool import ProjectStateShowTool  # noqa: E402
from tools.builtin.project_state_update_tool import ProjectStateUpdateTool  # noqa: E402
from tools.builtin.project_state_verify_tool import ProjectStateVerifyTool  # noqa: E402
from tools.executor import ToolExecutor  # noqa: E402
from tools.registry import ToolRegistry  # noqa: E402
from workflow.compound_progress_observer import CompoundStepObserver  # noqa: E402
from workflow.compound_workflow_progress_store import (  # noqa: E402
    CompoundOverallStatus,
    CompoundStepStatus,
    CompoundVerificationOutcome,
    CompoundWorkflowProgressStore,
)
from workflow.engine import CompoundCheckpointError, WorkflowEngine  # noqa: E402
from workflow.paused_workflow_store import PausedWorkflowStore  # noqa: E402
from workflow.workflow_history_store import WorkflowHistoryStore  # noqa: E402


class _Stack:
    def __init__(self, db_path: Path) -> None:
        from sqlalchemy import create_engine

        engine = create_engine(f"sqlite:///{db_path}")
        initialize_database(engine)
        self.session_factory = create_session_factory(engine)

        self.project_state_store = ProjectStateStore(self.session_factory)
        self.registry = ToolRegistry()
        self.registry.register_tool(ProjectStateShowTool(self.project_state_store))
        self.registry.register_tool(ProjectStateUpdateTool(self.project_state_store))
        self.registry.register_tool(ProjectStateVerifyTool(self.project_state_store))
        self.security = SecurityManager()
        self.executor = ToolExecutor(
            registry=self.registry, security_manager=self.security, logger=None
        )
        self.pending_store = PendingApprovalStore(self.session_factory)
        self.approvals = ApprovalManager(pending_store=self.pending_store)
        self.paused_store = PausedWorkflowStore(self.session_factory)
        self.progress_store = CompoundWorkflowProgressStore(self.session_factory)
        self.history = WorkflowHistoryStore(self.session_factory)
        self.workflow_engine = WorkflowEngine(
            executor=self.executor,
            approvals=self.approvals,
            paused_store=self.paused_store,
            history=self.history,
        )

    def build_plan(self, value: str) -> Plan:
        plan = _build_phase_update_verify_show_workflow_plan(
            f"update phase to {value} and then show project state",
            approved_phase_value=value,
            tool_registry=self.registry,
            security_manager=self.security,
            session_id=None,
            catalog=CAPABILITY_CATALOG,
        )
        assert isinstance(plan, Plan)
        return plan

    def pause_and_claim(self, plan: Plan) -> tuple[str, str]:
        """Run the plan to its first pause, establish progress, approve,
        and claim - mirroring exactly what a live claim-before-resume
        attempt would already have done before calling resume()."""
        pause_result = self.workflow_engine.run(plan)
        request_id = pause_result.pending_approval_request.request_id
        workflow_id = pause_result.workflow_id
        established = establish_compound_progress_or_isolate(
            plan=plan,
            workflow_id=workflow_id,
            request_id=request_id,
            progress_store=self.progress_store,
            approval_invalidator=self.approvals,
            paused_workflow_store=self.paused_store,
        )
        assert not isinstance(established, str)
        self.approvals.approve(request_id, decided_by="nathan")
        assert self.pending_store.claim_for_resume(request_id) is True
        return workflow_id, request_id

    def observer(self, plan: Plan) -> CompoundStepObserver:
        return CompoundStepObserver(
            plan=plan,
            progress_store=self.progress_store,
            executor=self.executor,
            session_id=None,
        )


class _FailingVerifyTool(BaseTool):
    """A registered replacement for project_state_verify that succeeds
    exactly once (mirroring the real, already-succeeded pre-execution
    observation read the observer's own before_step() already performed
    at Step 1) and genuinely fails on every subsequent call (Step 2's
    own real verification attempt) - used to prove an *ordinary*
    (non-checkpoint) verifier failure still produces a known terminal
    result."""

    def __init__(self) -> None:
        self._calls = 0

    @property
    def name(self) -> str:
        return "project_state_verify"

    @property
    def description(self) -> str:
        return "Succeeds once, then always fails."

    def action_for(self, request: ToolRequest) -> str:
        return "show jarvis project state"

    def run(self, request: ToolRequest) -> ToolResult:
        self._calls += 1
        if self._calls == 1:
            return ToolResult(
                tool_name=self.name,
                success=True,
                output="ok",
                metadata={"phase": "v5", "last_updated_at": None},
            )
        return ToolResult(tool_name=self.name, success=False, error="verifier genuinely failed")


class _FailingShowTool(BaseTool):
    """A registered replacement for project_state_show that always
    genuinely fails - used to prove an ordinary final-show failure
    still produces a known terminal result."""

    @property
    def name(self) -> str:
        return "project_state_show"

    @property
    def description(self) -> str:
        return "Always fails."

    def action_for(self, request: ToolRequest) -> str:
        return "show jarvis project state"

    def run(self, request: ToolRequest) -> ToolResult:
        return ToolResult(tool_name=self.name, success=False, error="show genuinely failed")


def _decision_for(stack: _Stack, request_id: str):
    from approval.approval_models import ApprovalDecision

    return ApprovalDecision(request_id=request_id, approved=True, decided_by="nathan")


class TestStep1SuccessCheckpointFailureHandoffSemantics:
    def test_handoff_remains_claimed_never_consumed(self, tmp_path: Path) -> None:
        stack = _Stack(tmp_path / "step1_checkpoint_failure.db")
        plan = stack.build_plan("v1")
        workflow_id, request_id = stack.pause_and_claim(plan)
        decision = _decision_for(stack, request_id)

        # Corrupt the progress row's own identity immediately before
        # Step 1's own completion checkpoint would need to write to it -
        # a genuine, real database-level mismatch (mark_step_1_completed
        # requires step_1_status=IN_PROGRESS, which will already be true
        # from before_step's own successful pre-execution checkpoint;
        # instead, simulate an infrastructure failure by deleting the
        # progress row entirely right after pre-execution observation
        # would have run, forcing the *completion* checkpoint to fail).
        original_mark_completed = stack.progress_store.mark_step_1_completed

        def _failing_mark_completed(workflow_id_arg):
            from workflow.compound_workflow_progress_store import (
                CompoundWorkflowProgressError,
            )

            raise CompoundWorkflowProgressError("simulated database error")

        stack.progress_store.mark_step_1_completed = _failing_mark_completed  # type: ignore[method-assign]

        with pytest.raises(CompoundCheckpointError):
            stack.workflow_engine.resume(
                workflow_id, decision, step_observer=stack.observer(plan)
            )

        stack.progress_store.mark_step_1_completed = original_mark_completed  # restore

        # The handoff must remain exactly CLAIMED - never CONSUMED.
        assert (
            stack.pending_store.get_handoff_status(request_id)
            == PendingApprovalHandoffStatus.CLAIMED
        )
        # The write itself really did happen (real tool executed) -
        # but the progress row's own checkpoint never confirmed it.
        assert stack.project_state_store.get().phase == "v1"
        record = stack.progress_store.get(workflow_id)
        assert record.step_1_status is CompoundStepStatus.IN_PROGRESS

    def test_remains_reconcilable_by_compound_recovery_afterward(
        self, tmp_path: Path
    ) -> None:
        """Directly proves item 7 of the required tests: after a
        Step-1-success/checkpoint-failure, the exact same row can still
        be safely processed by resume_claimed_compound_workflow() -
        never stuck, never requiring a second claim."""
        stack = _Stack(tmp_path / "step1_checkpoint_recoverable.db")
        plan = stack.build_plan("v2")
        workflow_id, request_id = stack.pause_and_claim(plan)
        decision = _decision_for(stack, request_id)

        class _OneShotFailingObserver:
            def __init__(self, real: CompoundStepObserver) -> None:
                self._real = real

            def before_step(self, wf_id: str, step_index: int) -> str | None:
                return self._real.before_step(wf_id, step_index)

            def after_step(self, wf_id: str, step_index: int, tool_result) -> str | None:
                if step_index == 0:
                    return "simulated checkpoint failure"
                return self._real.after_step(wf_id, step_index, tool_result)

        with pytest.raises(CompoundCheckpointError):
            stack.workflow_engine.resume(
                workflow_id,
                decision,
                step_observer=_OneShotFailingObserver(stack.observer(plan)),
            )

        assert (
            stack.pending_store.get_handoff_status(request_id)
            == PendingApprovalHandoffStatus.CLAIMED
        )

        # Compound-specific startup recovery now runs, using only
        # durable state - real reconcile_phase_update() classification,
        # never a second claim.
        record = stack.pending_store.get(request_id)
        outcome = resume_claimed_compound_workflow(
            record,
            pending_store=stack.pending_store,
            paused_workflow_store=stack.paused_store,
            progress_store=stack.progress_store,
            workflow_engine=stack.workflow_engine,
            tool_registry=stack.registry,
            security_manager=stack.security,
            tool_executor=stack.executor,
        )

        assert outcome is CompoundClaimedOutcome.CONSUMED
        final_record = stack.progress_store.get(workflow_id)
        assert final_record.step_1_status is CompoundStepStatus.COMPLETED
        assert final_record.overall_status is CompoundOverallStatus.COMPLETED
        assert (
            stack.pending_store.get_handoff_status(request_id)
            == PendingApprovalHandoffStatus.CONSUMED
        )


class TestVerificationCheckpointFailureSemantics:
    def test_does_not_fabricate_verified_and_handoff_stays_claimed(
        self, tmp_path: Path
    ) -> None:
        stack = _Stack(tmp_path / "verification_checkpoint_failure.db")
        plan = stack.build_plan("v3")
        workflow_id, request_id = stack.pause_and_claim(plan)
        decision = _decision_for(stack, request_id)

        real_observer = stack.observer(plan)

        class _FailStep2AfterObserver:
            def before_step(self, wf_id: str, step_index: int) -> str | None:
                return real_observer.before_step(wf_id, step_index)

            def after_step(self, wf_id: str, step_index: int, tool_result) -> str | None:
                if step_index == 1:
                    return "verification checkpoint infrastructure failure"
                return real_observer.after_step(wf_id, step_index, tool_result)

        with pytest.raises(CompoundCheckpointError):
            stack.workflow_engine.resume(
                workflow_id, decision, step_observer=_FailStep2AfterObserver()
            )

        record = stack.progress_store.get(workflow_id)
        # Step 2 was never durably marked completed with any outcome -
        # never fabricated as VERIFIED.
        assert record.step_2_status is not CompoundStepStatus.COMPLETED
        assert record.step_2_verification_outcome is None
        assert record.step_3_status is CompoundStepStatus.PENDING
        assert (
            stack.pending_store.get_handoff_status(request_id)
            == PendingApprovalHandoffStatus.CLAIMED
        )


class TestOverallTerminalCheckpointFailureSemantics:
    def test_does_not_mark_consumed_early(self, tmp_path: Path) -> None:
        stack = _Stack(tmp_path / "overall_terminal_checkpoint_failure.db")
        plan = stack.build_plan("v4")
        workflow_id, request_id = stack.pause_and_claim(plan)
        decision = _decision_for(stack, request_id)

        real_observer = stack.observer(plan)

        class _FailStep3AfterObserver:
            def before_step(self, wf_id: str, step_index: int) -> str | None:
                return real_observer.before_step(wf_id, step_index)

            def after_step(self, wf_id: str, step_index: int, tool_result) -> str | None:
                if step_index == 2:
                    return "overall terminal checkpoint infrastructure failure"
                return real_observer.after_step(wf_id, step_index, tool_result)

        with pytest.raises(CompoundCheckpointError):
            stack.workflow_engine.resume(
                workflow_id, decision, step_observer=_FailStep3AfterObserver()
            )

        record = stack.progress_store.get(workflow_id)
        assert record.step_1_status is CompoundStepStatus.COMPLETED
        assert record.step_2_verification_outcome is CompoundVerificationOutcome.VERIFIED
        assert record.step_3_status is not CompoundStepStatus.COMPLETED
        assert record.overall_status is not CompoundOverallStatus.COMPLETED
        assert (
            stack.pending_store.get_handoff_status(request_id)
            == PendingApprovalHandoffStatus.CLAIMED
        )
        latest = stack.history.latest_status_for(workflow_id)
        if latest is not None:
            assert latest.status not in ("workflow_completed", "workflow_stopped")


class TestOrdinaryFailuresStillProduceKnownTerminalResults:
    """Proves the correction did not weaken any *genuine* outcome - a
    real tool failure, with the observer able to durably checkpoint it,
    must still flow through _stop() normally and reach a known,
    terminal, CONSUMED-eligible result."""

    def test_ordinary_verifier_failure_still_stops_normally(self, tmp_path: Path) -> None:
        stack = _Stack(tmp_path / "ordinary_verifier_failure.db")
        plan = stack.build_plan("v5")
        workflow_id, request_id = stack.pause_and_claim(plan)
        decision = _decision_for(stack, request_id)

        stack.registry._tools["project_state_verify"] = _FailingVerifyTool()

        result = stack.workflow_engine.resume(
            workflow_id, decision, step_observer=stack.observer(plan)
        )
        from config.constants import StepStatus

        assert result.overall_status is StepStatus.FAILED
        record = stack.progress_store.get(workflow_id)
        assert record.step_2_verification_outcome is CompoundVerificationOutcome.UNAVAILABLE
        assert record.overall_status is CompoundOverallStatus.FAILED
        latest = stack.history.latest_status_for(workflow_id)
        assert latest is not None
        assert latest.status == "workflow_stopped"

    def test_ordinary_show_failure_still_stops_normally(self, tmp_path: Path) -> None:
        stack = _Stack(tmp_path / "ordinary_show_failure.db")
        plan = stack.build_plan("v6")
        workflow_id, request_id = stack.pause_and_claim(plan)
        decision = _decision_for(stack, request_id)

        stack.registry._tools["project_state_show"] = _FailingShowTool()

        result = stack.workflow_engine.resume(
            workflow_id, decision, step_observer=stack.observer(plan)
        )
        from config.constants import StepStatus

        assert result.overall_status is StepStatus.FAILED
        record = stack.progress_store.get(workflow_id)
        assert record.step_2_verification_outcome is CompoundVerificationOutcome.VERIFIED
        assert record.step_3_status is CompoundStepStatus.FAILED
        assert record.overall_status is CompoundOverallStatus.FAILED
        latest = stack.history.latest_status_for(workflow_id)
        assert latest is not None
        assert latest.status == "workflow_stopped"
