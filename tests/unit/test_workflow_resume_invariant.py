"""
test_workflow_resume_invariant.py

Phase 28: proves the request-id invariant added to WorkflowEngine.resume().

Phase 27 disclosed, but deliberately did not fix, a pre-existing Phase 15
caller contract: resume() never verified that a supplied
ApprovalDecision.request_id actually matched the specific paused workflow
being resumed - it trusted the caller (in practice, always
core.orchestrator.execute_approved(), which already supplies a matching
pair by construction) to get this right. Phase 28 closes that gap with a
narrow, additive guard: resume() now fails closed - raising
WorkflowError, executing nothing - if decision.request_id does not match
the paused workflow's own recorded request_id.

These tests prove: a genuine cross-workflow mismatch fails closed with
no execution and no state mutation; a matching decision still works
exactly as before (including after a Phase 27 reload); and the one real
production caller (core.orchestrator.execute_approved) continues to
supply a matching pair by construction, so ordinary behaviour is
completely unaffected.

Run with:
    pytest tests/unit/test_workflow_resume_invariant.py
"""

from __future__ import annotations

import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")

from approval.approval_manager import ApprovalManager
from approval.pending_approval_store import PendingApprovalStore
from config.constants import SecurityTier, StepStatus
from core.command_router import CommandRouter
from core.orchestrator import JarvisOrchestrator
from planner.planner import Planner
from planner.plan_models import Plan, PlanStep
from security.security_manager import SecurityManager
from storage.database import create_session_factory, initialize_database
from tools.base_tool import BaseTool, ToolRequest, ToolResult
from tools.executor import ToolExecutor
from tools.registry import ToolRegistry
from workflow.engine import WorkflowEngine, WorkflowError, WorkflowReloadReport
from workflow.paused_workflow_store import PausedWorkflowStore
from workflow.workflow_history_store import WorkflowHistoryStore


class _SpyLogger:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def emit(self, **kwargs: object) -> str:
        self.events.append(kwargs)
        return str(len(self.events))


class _GreenTool(BaseTool):
    def __init__(self, name: str = "green_tool") -> None:
        self._name = name
        self.calls: list[ToolRequest] = []

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return "green"

    def action_for(self, request: ToolRequest) -> str:
        return "read something"

    def run(self, request: ToolRequest) -> ToolResult:
        self.calls.append(request)
        return ToolResult(tool_name=self.name, success=True, output="ok")


class _YellowTool(BaseTool):
    def __init__(self, name: str = "yellow_tool") -> None:
        self._name = name
        self.calls: list[ToolRequest] = []

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return "yellow"

    def action_for(self, request: ToolRequest) -> str:
        return "delete something"

    def run(self, request: ToolRequest) -> ToolResult:
        self.calls.append(request)
        return ToolResult(tool_name=self.name, success=True, output="deleted")


def _two_step_plan(user_request: str = "do a thing") -> Plan:
    return Plan(
        user_request=user_request,
        steps=(
            PlanStep(
                number=1, description="green", action="read something",
                tier=SecurityTier.GREEN, reason="ok", tool_name="green_tool",
                tool_input={},
            ),
            PlanStep(
                number=2, description="yellow", action="delete something",
                tier=SecurityTier.YELLOW, reason="needs approval",
                tool_name="yellow_tool", tool_input={"target": "x"},
            ),
        ),
    )


@pytest.fixture()
def session_factory():
    from sqlalchemy import create_engine

    engine = create_engine("sqlite:///:memory:")
    initialize_database(engine)
    return create_session_factory(engine)


def _build_stack(session_factory=None, *, with_history: bool = False):
    security = SecurityManager()
    registry = ToolRegistry()
    green = _GreenTool()
    yellow = _YellowTool()
    registry.register_tool(green)
    registry.register_tool(yellow)
    logger = _SpyLogger()
    executor = ToolExecutor(registry=registry, security_manager=security, logger=logger)
    pending_store = PendingApprovalStore(session_factory) if session_factory else None
    paused_store = PausedWorkflowStore(session_factory) if session_factory else None
    history_store = WorkflowHistoryStore(session_factory) if (with_history and session_factory) else None
    approvals = ApprovalManager(audit_logger=logger, pending_store=pending_store)
    engine = WorkflowEngine(
        executor=executor, approvals=approvals, logger=logger,
        paused_store=paused_store, history=history_store,
    )
    return registry, executor, approvals, engine, green, yellow


# --- the core invariant -------------------------------------------------------


def test_resume_rejects_a_decision_for_a_different_workflow() -> None:
    """Two entirely separate, genuinely paused workflows, each with its
    own real, uncorrupted approval - resuming one with the other's
    decision must fail closed."""
    _, _, approvals, engine, _, yellow = _build_stack()

    result_a = engine.run(_two_step_plan("workflow A"))
    # Only one workflow may be paused at a time (Phase 15's own
    # contract), so decide workflow A's step first to free the engine up
    # for workflow B, then re-pause a fresh one for the actual test.
    decision_a_first = approvals.approve(result_a.pending_approval_request.request_id)
    engine.resume(result_a.workflow_id, decision_a_first)
    assert len(yellow.calls) == 1

    result_b = engine.run(_two_step_plan("workflow B"))
    workflow_b_id = result_b.workflow_id

    # A genuinely real, separately-approved decision that has nothing to
    # do with workflow B.
    unrelated_request = approvals.create_request(
        "copy file", "unrelated", SecurityTier.YELLOW
    )
    unrelated_decision = approvals.approve(unrelated_request.request_id)

    with pytest.raises(WorkflowError):
        engine.resume(workflow_b_id, unrelated_decision)

    # No second execution happened - only workflow A's single approved
    # yellow-step run from above.
    assert len(yellow.calls) == 1


def test_no_tool_executes_on_mismatch() -> None:
    _, _, approvals, engine, green, yellow = _build_stack()
    result = engine.run(_two_step_plan())
    unrelated = approvals.create_request("copy file", "unrelated", SecurityTier.YELLOW)
    unrelated_decision = approvals.approve(unrelated.request_id)

    with pytest.raises(WorkflowError):
        engine.resume(result.workflow_id, unrelated_decision)

    assert yellow.calls == []
    assert len(green.calls) == 1  # only the original, legitimate green step ran


def test_mismatch_is_terminal_not_retryable() -> None:
    """The workflow is not left pending for a later, correctly-matched
    resume() attempt - this prevents probing for a matching id."""
    _, _, approvals, engine, _, yellow = _build_stack()
    result = engine.run(_two_step_plan())
    workflow_id = result.workflow_id
    real_request_id = result.pending_approval_request.request_id

    unrelated = approvals.create_request("copy file", "unrelated", SecurityTier.YELLOW)
    unrelated_decision = approvals.approve(unrelated.request_id)

    with pytest.raises(WorkflowError):
        engine.resume(workflow_id, unrelated_decision)

    assert engine.has_paused(workflow_id) is False

    # Even the correct, real decision can no longer resume it - the
    # workflow was terminally closed by the mismatch, not merely
    # rejected-and-still-open.
    real_decision = approvals.approve(real_request_id)
    with pytest.raises(WorkflowError):
        engine.resume(workflow_id, real_decision)
    assert yellow.calls == []


def test_workflow_history_records_an_honest_mismatch_entry(session_factory) -> None:
    _, _, approvals, engine, _, _ = _build_stack(session_factory, with_history=True)
    result = engine.run(_two_step_plan())
    workflow_id = result.workflow_id

    unrelated = approvals.create_request("copy file", "unrelated", SecurityTier.YELLOW)
    unrelated_decision = approvals.approve(unrelated.request_id)

    with pytest.raises(WorkflowError):
        engine.resume(workflow_id, unrelated_decision)

    history = WorkflowHistoryStore(session_factory)
    entries = history.list_for_workflow(workflow_id)
    stopped = [e for e in entries if e.status == "workflow_stopped"]
    assert len(stopped) == 1
    assert "different" in (stopped[0].detail or "").lower()


# --- valid resume behaviour is unaffected -------------------------------------


def test_valid_matching_resume_still_works() -> None:
    _, _, approvals, engine, _, yellow = _build_stack()
    result = engine.run(_two_step_plan())
    decision = approvals.approve(result.pending_approval_request.request_id)

    resumed = engine.resume(result.workflow_id, decision)

    assert resumed.overall_status is StepStatus.COMPLETED
    assert len(yellow.calls) == 1


def test_valid_matching_resume_after_reload_still_works(session_factory) -> None:
    registry_one, _, approvals_one, engine_one, _, _ = _build_stack(session_factory)
    result = engine_one.run(_two_step_plan())
    workflow_id = result.workflow_id
    request_id = result.pending_approval_request.request_id
    del registry_one, approvals_one, engine_one

    registry_two, _, approvals_two, engine_two, _, yellow_two = _build_stack(
        session_factory
    )
    approvals_two.reload_pending(registry=registry_two)
    report = engine_two.reload_paused(registry=registry_two)
    assert report == WorkflowReloadReport(resumed=1, invalidated=0)

    decision = approvals_two.approve(request_id)
    resumed = engine_two.resume(workflow_id, decision)

    assert resumed.overall_status is StepStatus.COMPLETED
    assert len(yellow_two.calls) == 1


def test_declined_matching_resume_still_works() -> None:
    """A correctly-matched decision that happens to be a decline is not
    a mismatch - it must still be honoured as an ordinary decline, not
    rejected as an invariant violation."""
    _, _, approvals, engine, _, yellow = _build_stack()
    result = engine.run(_two_step_plan())
    decision = approvals.decline(result.pending_approval_request.request_id)

    resumed = engine.resume(result.workflow_id, decision)

    assert resumed.overall_status is StepStatus.FAILED
    assert yellow.calls == []


# --- the one real production caller supplies a matching pair by construction --


def test_production_orchestrator_path_always_supplies_matching_ids(
    tmp_path,
) -> None:
    """core.orchestrator.JarvisOrchestrator.execute_approved() derives
    workflow_id from response.approval_request.metadata and obtains
    decision by approving that exact same approval_request.request_id -
    structurally guaranteeing they always match. This is not a
    hypothetical: it is the only real caller of resume() in this
    codebase."""
    workspace = tmp_path
    security = SecurityManager()
    registry = ToolRegistry()
    from tools.builtin import MemoryTool, MemoryForgetTool
    from memory.memory_manager import MemoryManager
    from memory.episodic_memory import EpisodicMemoryStore
    from sqlalchemy import create_engine

    engine_db = create_engine(f"sqlite:///{workspace / 'test.db'}")
    initialize_database(engine_db)
    session_factory = create_session_factory(engine_db)
    memory = MemoryManager(EpisodicMemoryStore(session_factory))
    registry.register_tool(MemoryTool(memory))
    registry.register_tool(MemoryForgetTool(memory))

    logger = _SpyLogger()
    executor = ToolExecutor(registry=registry, security_manager=security, logger=logger)
    approvals = ApprovalManager(audit_logger=logger)
    workflow_engine = WorkflowEngine(executor=executor, approvals=approvals, logger=logger)
    orchestrator = JarvisOrchestrator(
        planner=Planner(security),
        executor=executor,
        registry=registry,
        command_router=CommandRouter(registry),
        approval_manager=approvals,
        workflow_engine=workflow_engine,
    )

    response = orchestrator.handle_request(
        "remember this and forget it: a secret to forget"
    )
    assert response.requires_confirmation is True
    request_id_used_for_workflow_lookup = response.approval_request.metadata.get(
        "workflow_id"
    )
    assert request_id_used_for_workflow_lookup is not None

    decision = approvals.approve(response.approval_request.request_id)
    # The decision's own request_id is, by construction, the exact same
    # id execute_approved() will use to look up the paused workflow.
    executed = orchestrator.execute_approved(response, decision)

    assert executed.success is True
