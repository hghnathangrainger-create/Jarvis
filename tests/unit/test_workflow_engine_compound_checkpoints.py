"""
test_workflow_engine_compound_checkpoints.py

Unit tests for WorkflowEngine's optional, trusted per-step lifecycle
observer (Phase 98, Batch 2, Foundation E -
docs/phase_98_live_compound_reentry_plan.md): the _CompoundStepObserver
Protocol's attachment point (resume()/_run_from() only, never run()),
exact per-step checkpoint ordering, fail-closed behaviour on both a
returned reason and a raised exception, peek_paused_plan(), and
reconstruct_claimed_compound_plan().

Uses a fake, trace-recording observer (not the concrete
CompoundStepObserver, which has its own dedicated tests) so these tests
exercise only the engine's own contract with any observer, exactly
mirroring test_workflow_engine.py's own established fake-tool
convention.
"""

from __future__ import annotations

import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")

from approval.approval_manager import ApprovalManager  # noqa: E402
from approval.pending_approval_store import PendingApprovalStore  # noqa: E402
from config.constants import SecurityTier, StepStatus  # noqa: E402
from planner.plan_models import Plan, PlanStep  # noqa: E402
from security.security_manager import SecurityManager  # noqa: E402
from storage.database import create_session_factory, initialize_database  # noqa: E402
from tools.base_tool import BaseTool, ToolRequest, ToolResult  # noqa: E402
from tools.executor import ToolExecutor  # noqa: E402
from tools.registry import ToolRegistry  # noqa: E402
from workflow.engine import CompoundCheckpointError, WorkflowEngine  # noqa: E402
from workflow.paused_workflow_store import PausedWorkflowStore  # noqa: E402
from workflow.workflow_history_store import WorkflowHistoryStore  # noqa: E402


class _RecordingTool(BaseTool):
    def __init__(self, name: str, *, tier_action: str, metadata: dict[str, object] | None = None):
        self._name = name
        self._tier_action = tier_action
        self._metadata = metadata or {}
        self.calls: list[ToolRequest] = []

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return "A fake tool for compound-checkpoint tests."

    def action_for(self, request: ToolRequest) -> str:
        return self._tier_action

    def run(self, request: ToolRequest) -> ToolResult:
        self.calls.append(request)
        return ToolResult(
            tool_name=self.name, success=True, output="ok", metadata=dict(self._metadata)
        )


def _three_step_plan() -> Plan:
    return Plan(
        user_request="write then verify then show",
        steps=(
            PlanStep(
                number=1,
                description="write",
                action="delete something",  # classified YELLOW
                tier=SecurityTier.YELLOW,
                reason="needs approval",
                tool_name="write_tool",
                tool_input={"value": "target-value"},
            ),
            PlanStep(
                number=2,
                description="verify",
                action="read something",  # classified GREEN
                tier=SecurityTier.GREEN,
                reason="ok",
                tool_name="verify_tool",
                tool_input={},
            ),
            PlanStep(
                number=3,
                description="show",
                action="read something",
                tier=SecurityTier.GREEN,
                reason="ok",
                tool_name="show_tool",
                tool_input={},
                requires_verified_predecessor=True,
                verification_field_name="phase",
                verification_expected_value="target-value",
            ),
        ),
    )


class _TracingObserver:
    """A fake, trace-recording _CompoundStepObserver-shaped test double."""

    def __init__(self, trace: list, *, before_failures=None, after_failures=None, raise_on=None):
        self.trace = trace
        self._before_failures = before_failures or {}
        self._after_failures = after_failures or {}
        self._raise_on = raise_on or set()

    def before_step(self, workflow_id: str, step_index: int) -> str | None:
        if ("before", step_index) in self._raise_on:
            raise RuntimeError("simulated observer failure")
        self.trace.append(("before", step_index))
        return self._before_failures.get(step_index)

    def after_step(self, workflow_id: str, step_index: int, tool_result: ToolResult) -> str | None:
        if ("after", step_index) in self._raise_on:
            raise RuntimeError("simulated observer failure")
        self.trace.append(("after", step_index, tool_result.success))
        return self._after_failures.get(step_index)


def _session_factory():
    from sqlalchemy import create_engine

    engine = create_engine("sqlite:///:memory:")
    initialize_database(engine)
    return create_session_factory(engine)


def _build():
    """Builds one full, real-persistence stack (real PendingApprovalStore,
    PausedWorkflowStore, WorkflowHistoryStore, all backed by a real,
    in-memory SQLite database) so checkpoint-failure tests can prove,
    for real, that paused state is retained and no terminal history is
    written - not merely that the returned WorkflowResult looks a
    certain way."""
    session_factory = _session_factory()
    security = SecurityManager()
    registry = ToolRegistry()
    write_tool = _RecordingTool("write_tool", tier_action="delete something")
    verify_tool = _RecordingTool(
        "verify_tool", tier_action="read something", metadata={"phase": "target-value"}
    )
    show_tool = _RecordingTool("show_tool", tier_action="read something")
    registry.register_tool(write_tool)
    registry.register_tool(verify_tool)
    registry.register_tool(show_tool)
    executor = ToolExecutor(registry=registry, security_manager=security, logger=None)

    pending_store = PendingApprovalStore(session_factory)
    approvals = ApprovalManager(pending_store=pending_store)
    paused_store = PausedWorkflowStore(session_factory)
    history = WorkflowHistoryStore(session_factory)
    engine = WorkflowEngine(
        executor=executor, approvals=approvals, paused_store=paused_store, history=history
    )
    return engine, approvals, write_tool, verify_tool, show_tool, paused_store, history


def _assert_no_terminal_history(history: WorkflowHistoryStore, workflow_id: str) -> None:
    """A checkpoint infrastructure failure alone must never create
    positive terminal evidence (workflow_completed/workflow_stopped) -
    the exact two statuses the generic interlock's own
    latest_status_for()-based reconciliation treats as proof a workflow
    reached a known terminal state. Ordinary, non-terminal history
    entries (workflow_started/workflow_step_started/workflow_step_waiting,
    already written before any checkpoint failure could occur) are
    expected and harmless - this only asserts neither terminal status
    was ever additionally recorded."""
    latest = history.latest_status_for(workflow_id)
    if latest is not None:
        assert latest.status not in ("workflow_completed", "workflow_stopped")


def _run_and_approve(engine, approvals):
    plan = _three_step_plan()
    result = engine.run(plan)
    assert result.overall_status is StepStatus.WAITING
    request_id = result.pending_approval_request.request_id
    decision = approvals.approve(request_id)
    return result.workflow_id, decision


class TestObserverNeverAttachedToRun:
    def test_run_pauses_without_ever_calling_before_step_or_after_step(self) -> None:
        engine, approvals, write_tool, verify_tool, show_tool, *_ = _build()
        plan = _three_step_plan()
        trace: list = []
        # run() itself accepts no step_observer parameter at all - this
        # test proves the *behavioural* consequence: nothing about a
        # hypothetical observer could ever fire during run(), since
        # write_tool.run() is never even reached (YELLOW, unapproved).
        result = engine.run(plan)
        assert result.overall_status is StepStatus.WAITING
        assert write_tool.calls == []
        assert trace == []


class TestExactCheckpointOrdering:
    def test_before_and_after_fire_in_strict_per_step_order(self) -> None:
        engine, approvals, write_tool, verify_tool, show_tool, *_ = _build()
        workflow_id, decision = _run_and_approve(engine, approvals)

        trace: list = []
        observer = _TracingObserver(trace)
        result = engine.resume(workflow_id, decision, step_observer=observer)

        assert result.overall_status is StepStatus.COMPLETED
        assert trace == [
            ("before", 0),
            ("after", 0, True),
            ("before", 1),
            ("after", 1, True),
            ("before", 2),
            ("after", 2, True),
        ]
        assert len(write_tool.calls) == 1
        assert len(verify_tool.calls) == 1
        assert len(show_tool.calls) == 1

    def test_before_step_fires_before_the_tool_is_invoked(self) -> None:
        """A before_step failure for step 0 must prevent the write
        tool from ever being called at all, and (Phase 98, Batch 2
        acceptance correction) must raise CompoundCheckpointError -
        never an ordinary FAILED WorkflowResult."""
        engine, approvals, write_tool, verify_tool, show_tool, paused_store, history = _build()
        workflow_id, decision = _run_and_approve(engine, approvals)

        trace: list = []
        observer = _TracingObserver(trace, before_failures={0: "checkpoint unavailable"})
        with pytest.raises(CompoundCheckpointError):
            engine.resume(workflow_id, decision, step_observer=observer)

        assert write_tool.calls == []
        assert verify_tool.calls == []
        # before_step itself still recorded the attempt; only the tool
        # call and any subsequent after_step never happen.
        assert trace == [("before", 0)]
        # No terminal history was written, and the paused workflow's
        # durable row is retained, exactly as it was before resume().
        _assert_no_terminal_history(history, workflow_id)
        assert paused_store.get(workflow_id) is not None
        assert engine.has_paused(workflow_id) is True


class TestCheckpointFailureRaisesAndPreservesRecovery:
    """Phase 98, Batch 2 acceptance correction
    (docs/phase_98_live_compound_reentry_plan.md, "Checkpoint-Failure
    Handoff and Terminal Semantics"): a checkpoint infrastructure
    failure must never be converted into an ordinary, known FAILED
    WorkflowResult via _stop() - it must raise CompoundCheckpointError,
    write no workflow_stopped/workflow_completed terminal history, and
    leave the paused workflow (durable and in-memory) exactly as it was
    before this resume() attempt, so compound-specific startup
    reconciliation remains reachable."""

    def test_before_step_failure_on_step_2_stops_before_the_verifier_runs(self) -> None:
        engine, approvals, write_tool, verify_tool, show_tool, paused_store, history = _build()
        workflow_id, decision = _run_and_approve(engine, approvals)

        trace: list = []
        observer = _TracingObserver(trace, before_failures={1: "cannot mark step 2 active"})
        with pytest.raises(CompoundCheckpointError, match="cannot mark step 2 active"):
            engine.resume(workflow_id, decision, step_observer=observer)

        assert len(write_tool.calls) == 1  # step 1 did run
        assert verify_tool.calls == []  # step 2 never invoked
        assert show_tool.calls == []
        assert trace == [("before", 0), ("after", 0, True), ("before", 1)]
        _assert_no_terminal_history(history, workflow_id)
        assert paused_store.get(workflow_id) is not None
        assert engine.has_paused(workflow_id) is True

    def test_after_step_failure_on_step_1_success_stops_without_advancing(self) -> None:
        """The tool itself succeeded, but its checkpoint could not be
        recorded - the engine must never silently advance to Step 2,
        and must never mark this a known terminal result."""
        engine, approvals, write_tool, verify_tool, show_tool, paused_store, history = _build()
        workflow_id, decision = _run_and_approve(engine, approvals)

        trace: list = []
        observer = _TracingObserver(trace, after_failures={0: "durable write failed"})
        with pytest.raises(CompoundCheckpointError, match="durable write failed"):
            engine.resume(workflow_id, decision, step_observer=observer)

        assert len(write_tool.calls) == 1
        assert verify_tool.calls == []  # never reached
        _assert_no_terminal_history(history, workflow_id)
        assert paused_store.get(workflow_id) is not None
        assert engine.has_paused(workflow_id) is True

    def test_after_step_failure_mid_workflow_stops_before_final_step(self) -> None:
        engine, approvals, write_tool, verify_tool, show_tool, paused_store, history = _build()
        workflow_id, decision = _run_and_approve(engine, approvals)

        trace: list = []
        observer = _TracingObserver(trace, after_failures={1: "verification checkpoint failed"})
        with pytest.raises(CompoundCheckpointError):
            engine.resume(workflow_id, decision, step_observer=observer)

        assert len(verify_tool.calls) == 1
        assert show_tool.calls == []  # step 3 never reached
        _assert_no_terminal_history(history, workflow_id)
        assert paused_store.get(workflow_id) is not None

    def test_after_step_failure_on_step_3_success_never_repeats_step_1(self) -> None:
        engine, approvals, write_tool, verify_tool, show_tool, paused_store, history = _build()
        workflow_id, decision = _run_and_approve(engine, approvals)

        trace: list = []
        observer = _TracingObserver(trace, after_failures={2: "overall terminal checkpoint failed"})
        with pytest.raises(CompoundCheckpointError):
            engine.resume(workflow_id, decision, step_observer=observer)

        assert len(write_tool.calls) == 1  # Step 1 ran exactly once
        assert len(verify_tool.calls) == 1
        assert len(show_tool.calls) == 1
        _assert_no_terminal_history(history, workflow_id)
        assert paused_store.get(workflow_id) is not None

    def test_raising_before_step_is_the_same_nonterminal_path_as_a_returned_reason(
        self,
    ) -> None:
        engine, approvals, write_tool, verify_tool, show_tool, paused_store, history = _build()
        workflow_id, decision = _run_and_approve(engine, approvals)

        observer = _TracingObserver([], raise_on={("before", 0)})
        with pytest.raises(CompoundCheckpointError):
            engine.resume(workflow_id, decision, step_observer=observer)

        assert write_tool.calls == []
        _assert_no_terminal_history(history, workflow_id)
        assert paused_store.get(workflow_id) is not None

    def test_raising_after_step_is_the_same_nonterminal_path_as_a_returned_reason(
        self,
    ) -> None:
        engine, approvals, write_tool, verify_tool, show_tool, paused_store, history = _build()
        workflow_id, decision = _run_and_approve(engine, approvals)

        observer = _TracingObserver([], raise_on={("after", 0)})
        with pytest.raises(CompoundCheckpointError):
            engine.resume(workflow_id, decision, step_observer=observer)

        assert len(write_tool.calls) == 1
        assert verify_tool.calls == []
        _assert_no_terminal_history(history, workflow_id)
        assert paused_store.get(workflow_id) is not None

    def test_checkpoint_failure_never_marks_handoff_consumable_state(self) -> None:
        """A checkpoint failure must never allow the caller to observe
        a real, well-defined WorkflowResult it could mistake for a
        known terminal outcome - resume() must raise instead."""
        engine, approvals, write_tool, verify_tool, show_tool, paused_store, history = _build()
        workflow_id, decision = _run_and_approve(engine, approvals)

        observer = _TracingObserver([], after_failures={0: "db unavailable"})
        try:
            engine.resume(workflow_id, decision, step_observer=observer)
            raised = False
        except CompoundCheckpointError:
            raised = True
        assert raised is True


class TestGenericStopUnaffectedByCheckpointCorrection:
    """Proves the generic, non-compound _stop() path (no step_observer
    attached) is completely unchanged: it still writes workflow_stopped
    and returns an ordinary FAILED WorkflowResult for a genuinely known
    outcome."""

    def test_ordinary_tool_failure_without_observer_still_stops_normally(self) -> None:
        engine, approvals, write_tool, verify_tool, show_tool, paused_store, history = _build()

        class _AlwaysFailsTool(BaseTool):
            @property
            def name(self) -> str:
                return "write_tool"

            @property
            def description(self) -> str:
                return "fails"

            def action_for(self, request: ToolRequest) -> str:
                return "delete something"

            def run(self, request: ToolRequest) -> ToolResult:
                return ToolResult(tool_name=self.name, success=False, error="genuine failure")

        engine._executor._registry._tools["write_tool"] = _AlwaysFailsTool()
        workflow_id, decision = _run_and_approve(engine, approvals)

        result = engine.resume(workflow_id, decision)  # no step_observer at all

        assert result.overall_status is StepStatus.FAILED
        assert result.step_outcomes[-1].tool_result.error == "genuine failure"
        latest = history.latest_status_for(workflow_id)
        assert latest is not None
        assert latest.status == "workflow_stopped"
        assert paused_store.get(workflow_id) is None  # correctly removed - a known outcome


class TestDeclineNeverInvokesBeforeStep:
    def test_decline_calls_after_step_but_never_before_step(self) -> None:
        engine, approvals, write_tool, verify_tool, show_tool, *_ = _build()
        plan = _three_step_plan()
        result = engine.run(plan)
        request_id = result.pending_approval_request.request_id
        decision = approvals.decline(request_id)

        trace: list = []
        observer = _TracingObserver(trace)
        outcome = engine.resume(result.workflow_id, decision, step_observer=observer)

        assert outcome.overall_status is StepStatus.FAILED
        assert write_tool.calls == []
        assert trace == [("after", 0, False)]


class TestExistingWorkflowsUnaffectedByOmittedObserver:
    def test_omitting_step_observer_behaves_exactly_as_before(self) -> None:
        engine, approvals, write_tool, verify_tool, show_tool, *_ = _build()
        workflow_id, decision = _run_and_approve(engine, approvals)
        result = engine.resume(workflow_id, decision)
        assert result.overall_status is StepStatus.COMPLETED


class TestPeekPausedPlan:
    def test_returns_the_paused_plan_for_a_known_workflow(self) -> None:
        engine, approvals, *_ = _build()
        plan = _three_step_plan()
        result = engine.run(plan)
        peeked = engine.peek_paused_plan(result.workflow_id)
        assert peeked is not None
        assert peeked.steps[0].tool_name == "write_tool"

    def test_returns_none_for_an_unknown_workflow(self) -> None:
        engine, *_ = _build()
        assert engine.peek_paused_plan("no-such-workflow") is None

    def test_never_mutates_paused_state(self) -> None:
        engine, approvals, *_ = _build()
        plan = _three_step_plan()
        result = engine.run(plan)
        engine.peek_paused_plan(result.workflow_id)
        assert engine.has_paused(result.workflow_id) is True


class TestReconstructClaimedCompoundPlan:
    def _paused_store(self):
        from sqlalchemy import create_engine

        engine = create_engine("sqlite:///:memory:")
        initialize_database(engine)
        return PausedWorkflowStore(create_session_factory(engine))

    def _saved_record(self, paused_store, plan: Plan, *, workflow_id: str = "wf-x"):
        paused_store.save(
            workflow_id=workflow_id,
            session_id=None,
            request_id="req-x",
            user_request=plan.user_request,
            plan_steps=[WorkflowEngine._plan_step_to_dict(s) for s in plan.steps],
            completed_outcomes=[],
            waiting_step_index=0,
            resolved_tool_input=dict(plan.steps[0].tool_input),
        )
        return paused_store.get(workflow_id)

    def test_reconstructs_a_valid_persisted_plan(self) -> None:
        engine, approvals, *_ = _build()
        paused_store = self._paused_store()
        record = self._saved_record(paused_store, _three_step_plan())

        security = SecurityManager()
        plan, reason = engine.reconstruct_claimed_compound_plan(
            record, registry=engine._executor._registry, security_manager=security
        )
        assert reason is None
        assert plan is not None
        assert len(plan.steps) == 3

    def test_never_adds_to_in_memory_paused_state(self) -> None:
        engine, approvals, *_ = _build()
        paused_store = self._paused_store()
        record = self._saved_record(paused_store, _three_step_plan())
        engine.reconstruct_claimed_compound_plan(
            record, registry=engine._executor._registry, security_manager=SecurityManager()
        )
        assert engine.has_paused("wf-x") is False

    def test_unregistered_tool_fails_closed(self) -> None:
        engine, approvals, *_ = _build()
        paused_store = self._paused_store()
        record = self._saved_record(paused_store, _three_step_plan())

        empty_registry = ToolRegistry()
        plan, reason = engine.reconstruct_claimed_compound_plan(
            record, registry=empty_registry, security_manager=SecurityManager()
        )
        assert plan is None
        assert reason is not None
        assert "no longer registered" in reason

    def test_no_longer_yellow_action_fails_closed(self) -> None:
        """If the waiting step's own tool now reclassifies as GREEN
        (e.g. a live SecurityManager rule change since this row was
        persisted), this must fail closed rather than trust the stale
        persisted tier. Reclassification always asks the live,
        currently-registered tool's own action_for() afresh - never
        the persisted PlanStep.action text - so the registered tool
        itself is swapped out here to simulate that change."""
        _engine, _approvals, *_ = _build()
        paused_store = self._paused_store()
        record = self._saved_record(paused_store, _three_step_plan())

        reclassified_registry = ToolRegistry()
        reclassified_registry.register_tool(
            _RecordingTool("write_tool", tier_action="read something")
        )
        plan_out, reason = _engine.reconstruct_claimed_compound_plan(
            record, registry=reclassified_registry, security_manager=SecurityManager()
        )
        assert plan_out is None
        assert reason is not None
        assert "YELLOW" in reason

    def test_corrupt_record_fails_closed(self) -> None:
        engine, approvals, *_ = _build()
        paused_store = self._paused_store()
        record = self._saved_record(paused_store, _three_step_plan())
        corrupt_record = record.__class__(
            id=record.id,
            workflow_id=record.workflow_id,
            session_id=record.session_id,
            request_id=record.request_id,
            user_request=record.user_request,
            plan_steps=None,
            completed_outcomes=None,
            waiting_step_index=record.waiting_step_index,
            resolved_tool_input=None,
            schema_version=record.schema_version,
            created_at=record.created_at,
            corrupt=True,
        )
        plan_out, reason = engine.reconstruct_claimed_compound_plan(
            corrupt_record,
            registry=engine._executor._registry,
            security_manager=SecurityManager(),
        )
        assert plan_out is None
        assert reason is not None
