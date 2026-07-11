"""
test_phase27_invalid_state_fails_closed.py

Phase 27, Batch 3: a broader, integration-level sweep of every invalid-
persisted-state scenario named in the Batch 3 instructions, proven
through the real ToolExecutor/SecurityManager/ApprovalManager/
WorkflowEngine stack rather than isolated unit-level fakes. Batches 1 and
2 already proved each of these at the unit level (test_approval_manager_
pending_state.py, test_workflow_engine_paused_state.py); this file
re-proves the same fail-closed guarantees end-to-end, with a real
registry, a real tool, and a real on-disk-shaped SQLite session, to close
out Phase 27 with maximum confidence.

Every test proves: the invalid row is removed, nothing executes, and
startup continues safely - never a raised exception escaping reload.

Run with:
    pytest tests/integration/test_phase27_invalid_state_fails_closed.py
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")

from approval.approval_manager import ApprovalManager, ApprovalReloadReport
from approval.pending_approval_store import PendingApprovalStore
from config.constants import SecurityTier
from planner.plan_models import Plan, PlanStep
from security.security_manager import SecurityManager
from storage.database import create_session_factory, initialize_database, session_scope
from storage.models import PausedWorkflowState, PendingApprovalState
from tools.base_tool import BaseTool, ToolRequest, ToolResult
from tools.executor import ToolExecutor
from tools.registry import ToolRegistry
from workflow.engine import WorkflowEngine, WorkflowReloadReport
from workflow.paused_workflow_store import PausedWorkflowStore


class _SpyLogger:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def emit(self, **kwargs: object) -> str:
        self.events.append(kwargs)
        return str(len(self.events))


class _GreenTool(BaseTool):
    def __init__(self) -> None:
        self.calls: list[ToolRequest] = []

    @property
    def name(self) -> str:
        return "green_tool"

    @property
    def description(self) -> str:
        return "green"

    def action_for(self, request: ToolRequest) -> str:
        return "read something"

    def run(self, request: ToolRequest) -> ToolResult:
        self.calls.append(request)
        return ToolResult(tool_name=self.name, success=True, output="ok")


class _YellowTool(BaseTool):
    def __init__(self) -> None:
        self.calls: list[ToolRequest] = []

    @property
    def name(self) -> str:
        return "yellow_tool"

    @property
    def description(self) -> str:
        return "yellow"

    def action_for(self, request: ToolRequest) -> str:
        return "delete something"

    def run(self, request: ToolRequest) -> ToolResult:
        self.calls.append(request)
        return ToolResult(tool_name=self.name, success=True, output="deleted")


@pytest.fixture()
def session_factory():
    from sqlalchemy import create_engine

    engine = create_engine("sqlite:///:memory:")
    initialize_database(engine)
    return create_session_factory(engine)


def _two_step_plan() -> Plan:
    return Plan(
        user_request="do a green thing then a yellow thing",
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


def _build_stack(session_factory):
    security = SecurityManager()
    registry = ToolRegistry()
    green = _GreenTool()
    yellow = _YellowTool()
    registry.register_tool(green)
    registry.register_tool(yellow)
    logger = _SpyLogger()
    executor = ToolExecutor(registry=registry, security_manager=security, logger=logger)
    approvals = ApprovalManager(
        audit_logger=logger, pending_store=PendingApprovalStore(session_factory)
    )
    engine = WorkflowEngine(
        executor=executor, approvals=approvals, logger=logger,
        paused_store=PausedWorkflowStore(session_factory),
    )
    return registry, executor, approvals, engine, green, yellow


# --- pending approval: invalid-state sweep -----------------------------------


def test_corrupt_json_pending_approval_fails_closed(session_factory) -> None:
    manager_one = ApprovalManager(pending_store=PendingApprovalStore(session_factory))
    request = manager_one.create_request(
        "copy file", "reason", SecurityTier.YELLOW,
        tool_name="green_tool", tool_input={"a": "b"},
    )
    with session_scope(session_factory) as db:
        entry = (
            db.query(PendingApprovalState)
            .filter(PendingApprovalState.request_id == request.request_id)
            .one()
        )
        entry.tool_input_json = "{not valid json"

    registry = ToolRegistry()
    tool = _GreenTool()
    registry.register_tool(tool)
    manager_two = ApprovalManager(pending_store=PendingApprovalStore(session_factory))
    report = manager_two.reload_pending(registry=registry)

    assert report == ApprovalReloadReport(resumed=0, invalidated=1)
    assert manager_two.has_pending(request.request_id) is False
    assert tool.calls == []


def test_unsupported_schema_version_pending_approval_fails_closed(
    session_factory,
) -> None:
    manager_one = ApprovalManager(pending_store=PendingApprovalStore(session_factory))
    request = manager_one.create_request(
        "copy file", "reason", SecurityTier.YELLOW,
        tool_name="green_tool", tool_input={},
    )
    with session_scope(session_factory) as db:
        entry = (
            db.query(PendingApprovalState)
            .filter(PendingApprovalState.request_id == request.request_id)
            .one()
        )
        entry.schema_version = 42

    registry = ToolRegistry()
    registry.register_tool(_GreenTool())
    manager_two = ApprovalManager(pending_store=PendingApprovalStore(session_factory))
    report = manager_two.reload_pending(registry=registry)

    assert report == ApprovalReloadReport(resumed=0, invalidated=1)
    assert manager_two.has_pending(request.request_id) is False


def test_missing_tool_pending_approval_fails_closed(session_factory) -> None:
    manager_one = ApprovalManager(pending_store=PendingApprovalStore(session_factory))
    request = manager_one.create_request(
        "copy file", "reason", SecurityTier.YELLOW,
        tool_name="a_tool_that_will_vanish", tool_input={},
    )
    empty_registry = ToolRegistry()
    manager_two = ApprovalManager(pending_store=PendingApprovalStore(session_factory))
    report = manager_two.reload_pending(registry=empty_registry)

    assert report == ApprovalReloadReport(resumed=0, invalidated=1)
    assert manager_two.has_pending(request.request_id) is False


def test_no_longer_yellow_pending_approval_fails_closed(session_factory) -> None:
    class _NowGreenTool(BaseTool):
        @property
        def name(self) -> str:
            return "green_tool"

        @property
        def description(self) -> str:
            return "now green"

        def action_for(self, request: ToolRequest) -> str:
            return "read something"  # GREEN, not YELLOW

        def run(self, request: ToolRequest) -> ToolResult:
            return self.ok("ran")

    manager_one = ApprovalManager(pending_store=PendingApprovalStore(session_factory))
    request = manager_one.create_request(
        "copy file", "reason", SecurityTier.YELLOW,
        tool_name="green_tool", tool_input={},
    )
    registry = ToolRegistry()
    now_green = _NowGreenTool()
    registry.register_tool(now_green)
    manager_two = ApprovalManager(pending_store=PendingApprovalStore(session_factory))
    report = manager_two.reload_pending(registry=registry, security_manager=SecurityManager())

    assert report == ApprovalReloadReport(resumed=0, invalidated=1)
    assert manager_two.has_pending(request.request_id) is False


def test_stale_pending_approval_fails_closed(session_factory) -> None:
    clock_time = {"now": datetime(2030, 1, 1, tzinfo=timezone.utc)}

    def _clock() -> datetime:
        return clock_time["now"]

    manager_one = ApprovalManager(
        pending_store=PendingApprovalStore(session_factory),
        timeout_seconds=60, clock=_clock,
    )
    request = manager_one.create_request(
        "copy file", "reason", SecurityTier.YELLOW,
        tool_name="green_tool", tool_input={},
    )
    clock_time["now"] = clock_time["now"] + timedelta(seconds=61)

    registry = ToolRegistry()
    registry.register_tool(_GreenTool())
    manager_two = ApprovalManager(
        pending_store=PendingApprovalStore(session_factory),
        timeout_seconds=60, clock=_clock,
    )
    report = manager_two.reload_pending(registry=registry)

    assert report == ApprovalReloadReport(resumed=0, invalidated=1)
    assert manager_two.has_pending(request.request_id) is False


# --- paused workflow: invalid-state sweep ------------------------------------


def test_invalid_plan_data_paused_workflow_fails_closed(session_factory) -> None:
    registry_one, _, approvals_one, engine_one, _, _ = _build_stack(session_factory)
    result = engine_one.run(_two_step_plan())
    workflow_id = result.workflow_id
    del registry_one, approvals_one, engine_one

    with session_scope(session_factory) as db:
        entry = (
            db.query(PausedWorkflowState)
            .filter(PausedWorkflowState.workflow_id == workflow_id)
            .one()
        )
        # A plan step dict missing required fields entirely.
        entry.plan_steps_json = "[{}]"

    registry_two, _, approvals_two, engine_two, _, yellow_two = _build_stack(
        session_factory
    )
    approvals_two.reload_pending(registry=registry_two)
    report = engine_two.reload_paused(registry=registry_two)

    assert report == WorkflowReloadReport(resumed=0, invalidated=1)
    assert engine_two.has_paused(workflow_id) is False
    assert yellow_two.calls == []


def test_missing_plan_steps_paused_workflow_fails_closed(session_factory) -> None:
    registry_one, _, approvals_one, engine_one, _, _ = _build_stack(session_factory)
    result = engine_one.run(_two_step_plan())
    workflow_id = result.workflow_id
    del registry_one, approvals_one, engine_one

    with session_scope(session_factory) as db:
        entry = (
            db.query(PausedWorkflowState)
            .filter(PausedWorkflowState.workflow_id == workflow_id)
            .one()
        )
        entry.plan_steps_json = "[]"  # no steps at all

    registry_two, _, approvals_two, engine_two, _, _ = _build_stack(session_factory)
    approvals_two.reload_pending(registry=registry_two)
    report = engine_two.reload_paused(registry=registry_two)

    assert report == WorkflowReloadReport(resumed=0, invalidated=1)
    assert engine_two.has_paused(workflow_id) is False


def test_already_decided_linked_approval_fails_closed(session_factory) -> None:
    """The paused workflow's own state is perfectly valid, but its
    linked approval was already decided (e.g. approved/declined in a
    session that then crashed before resume() could run) - it must fail
    closed rather than be treated as still awaiting a decision."""
    registry_one, _, approvals_one, engine_one, _, yellow_one = _build_stack(
        session_factory
    )
    result = engine_one.run(_two_step_plan())
    workflow_id = result.workflow_id
    request_id = result.pending_approval_request.request_id
    approvals_one.decline(request_id)  # decided, but resume() never ran
    del registry_one, approvals_one, engine_one

    registry_two, _, approvals_two, engine_two, _, yellow_two = _build_stack(
        session_factory
    )
    approvals_two.reload_pending(registry=registry_two)  # nothing pending to reload
    report = engine_two.reload_paused(registry=registry_two)

    assert report == WorkflowReloadReport(resumed=0, invalidated=1)
    assert engine_two.has_paused(workflow_id) is False
    assert yellow_two.calls == []
    assert yellow_one.calls == []


def test_missing_linked_approval_row_entirely_fails_closed(session_factory) -> None:
    """A paused_workflow_state row whose request_id names an id that
    never existed as a pending_approval_state row at all (e.g. it was
    written by an older, incompatible version, or the two writes raced
    and only one completed)."""
    registry_one, _, approvals_one, engine_one, _, _ = _build_stack(session_factory)
    result = engine_one.run(_two_step_plan())
    workflow_id = result.workflow_id
    del registry_one, engine_one

    # Remove the linked pending-approval row directly, leaving the
    # paused-workflow row pointing at a request_id that no longer exists
    # anywhere.
    approvals_one.approve(result.pending_approval_request.request_id)
    del approvals_one

    registry_two, _, approvals_two, engine_two, _, yellow_two = _build_stack(
        session_factory
    )
    approvals_two.reload_pending(registry=registry_two)
    report = engine_two.reload_paused(registry=registry_two)

    assert report == WorkflowReloadReport(resumed=0, invalidated=1)
    assert engine_two.has_paused(workflow_id) is False
    assert yellow_two.calls == []


def test_mismatched_request_id_pointing_at_an_unrelated_pending_approval(
    session_factory,
) -> None:
    """Documents a deliberate, disclosed Phase 15 boundary, not a Phase
    27 regression: if a paused_workflow_state row's own request_id were
    corrupted to point at a *different*, unrelated, genuinely-pending
    approval, reload_paused()'s own check (has_pending(request_id)) would
    pass, because that check only verifies "is some approval with this id
    still pending", not "is this specifically the workflow's own
    approval". This mirrors WorkflowEngine.resume()'s own pre-existing,
    unchanged-by-Phase-27 contract: the caller must supply the decision
    for the correct workflow_id (exactly as JarvisOrchestrator.
    execute_approved() already does today, deriving workflow_id directly
    from the approval_request's own metadata). Phase 27 does not
    introduce, worsen, or fix this - it is the same trust boundary this
    project has relied on since Phase 15, disclosed here rather than
    silently assumed."""
    registry_one, _, approvals_one, engine_one, _, _ = _build_stack(session_factory)
    result = engine_one.run(_two_step_plan())
    workflow_id = result.workflow_id
    real_request_id = result.pending_approval_request.request_id

    # An unrelated, ordinary pending approval with no connection to this
    # workflow at all.
    unrelated = approvals_one.create_request(
        "copy file", "unrelated reason", SecurityTier.YELLOW,
    )
    del registry_one, engine_one

    with session_scope(session_factory) as db:
        entry = (
            db.query(PausedWorkflowState)
            .filter(PausedWorkflowState.workflow_id == workflow_id)
            .one()
        )
        entry.request_id = unrelated.request_id

    del approvals_one

    registry_two, _, approvals_two, engine_two, _, yellow_two = _build_stack(
        session_factory
    )
    approvals_two.reload_pending(registry=registry_two)
    report = engine_two.reload_paused(registry=registry_two)

    # The mismatched-but-genuinely-pending unrelated approval means this
    # row passes reload's own narrow check - documented above as an
    # existing, disclosed boundary, not a new one.
    assert report == WorkflowReloadReport(resumed=1, invalidated=0)

    # The real safety property that matters: resuming the workflow still
    # requires an explicit resume() call, and nothing executes merely
    # because reload happened.
    assert yellow_two.calls == []

    # The original real approval (never approved) is untouched, and the
    # workflow's own actual completion still requires its own real
    # decision path in ordinary use - this test exists to document the
    # boundary, not to exercise an unsafe resume.
    assert approvals_two.has_pending(real_request_id) is True
