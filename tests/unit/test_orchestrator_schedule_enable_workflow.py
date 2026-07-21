"""
test_orchestrator_schedule_enable_workflow.py

Unit tests for the explicit "ask jarvis to: enable schedule <id>"
write-and-verify workflow (Phase 94, Batch 2 -
docs/phase_94_implementation_plan.md, Sections 10/13/14), mirroring
test_orchestrator_update_focus_workflow.py's own established pattern
exactly for the second real, trusted verified write workflow:
CommandRouter.match_ask_jarvis_to() ->
JarvisOrchestrator._handle_ask_jarvis_to_request() ->
intelligence.planning.select_tool() (EXECUTABLE_WORKFLOW) ->
WorkflowEngine.run()/resume() -> JarvisOrchestrator.execute_approved().

Uses real Planner, SecurityManager, CommandRouter, ToolRegistry,
ToolExecutor, ApprovalManager, WorkflowEngine, MemoryManager (over a
real in-memory SQLite EpisodicMemoryStore), real ScheduleStore, the
real ScheduleEnableTool/ScheduleListTool/ScheduleVerifyEnabledStateTool,
real ContextAssembler, and a real AIRouter wired to a real
PromptBuilder and a fake, in-memory AIProvider - no live Claude API
call is ever made, no real network call is ever made.

sqlalchemy-dependent imports are guarded by a try/except ImportError,
mirroring test_orchestrator_update_focus_workflow.py's own established
pattern.

Run with:
    pytest tests/unit/test_orchestrator_schedule_enable_workflow.py
"""

from __future__ import annotations

import ast
import inspect
import json
from pathlib import Path

import pytest

try:
    from sqlalchemy import create_engine

    from ai.prompt_builder import PromptBuilder
    from ai.providers.base import AIProvider, AIRequest, AIResponse
    from ai.response_validator import ResponseValidator
    from ai.router import AIRouter
    from approval.approval_manager import ApprovalError, ApprovalManager
    from approval.pending_approval_store import PendingApprovalStore
    from config.settings import Settings
    from core.command_router import CommandRouter
    from core.orchestrator import JarvisOrchestrator
    from intelligence.context import ContextAssembler
    from memory.episodic_memory import EpisodicMemoryStore
    from memory.memory_manager import MemoryManager
    from planner.planner import Planner
    from project_state.project_state_store import ProjectStateStore
    from scheduling.schedule_store import ScheduleStore
    from security.security_manager import SecurityManager
    from storage.database import create_session_factory, initialize_database
    from tools.builtin.project_state_show_tool import ProjectStateShowTool
    from tools.builtin.project_state_update_tool import ProjectStateUpdateTool
    from tools.builtin.project_state_verify_tool import ProjectStateVerifyTool
    from tools.builtin.schedule_enable_tool import ScheduleEnableTool
    from tools.builtin.schedule_list_tool import ScheduleListTool
    from tools.builtin.schedule_verify_enabled_state_tool import (
        ScheduleVerifyEnabledStateTool,
    )
    from tools.executor import ToolExecutor
    from tools.registry import ToolRegistry
    from workflow.engine import WorkflowEngine
    from workflow.paused_workflow_store import PausedWorkflowStore

    _SQLALCHEMY_AVAILABLE = True
except ImportError:
    _SQLALCHEMY_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not _SQLALCHEMY_AVAILABLE, reason="sqlalchemy not installed"
)


# --- Test doubles --------------------------------------------------------------


class _RecordingLogger:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def emit(self, **kwargs: object) -> str:
        self.calls.append(kwargs)
        return str(len(self.calls))


class _FakeAIProvider(AIProvider):
    def __init__(self, text: str, *, available: bool = True) -> None:
        self._text = text
        self._available = available
        self.received_requests: list[AIRequest] = []

    @property
    def name(self) -> str:
        return "fake"

    def generate(self, request: AIRequest) -> AIResponse:
        self.received_requests.append(request)
        return AIResponse(text=self._text, model="fake-model", provider="fake")

    def is_available(self) -> bool:
        return self._available


def _settings() -> Settings:
    return Settings(
        anthropic_api_key="test-key-not-real",
        ai_model="test-model",
        ai_max_tokens=1024,
        database_path=Path("unused.db"),
        log_level="INFO",
        approval_timeout_seconds=60,
        debug=False,
        ai_reasoning_enabled=True,
    )


def _router(text: str) -> tuple[AIRouter, _FakeAIProvider]:
    provider = _FakeAIProvider(text)
    router = AIRouter(
        provider=provider,
        prompt_builder=PromptBuilder(),
        validator=ResponseValidator(),
        logger=_RecordingLogger(),  # type: ignore[arg-type]
        settings=_settings(),
    )
    return router, provider


def _schedule_enable_text(schedule_id: int) -> str:
    return json.dumps(
        {
            "decision": "execute",
            "capability_id": "schedule_enable",
            "arguments": {"schedule_id": schedule_id},
        }
    )


def _build_stack(
    session_factory,
    router: AIRouter,
    *,
    durable: bool = False,
    timeout_seconds: int | None = None,
    clock=None,
):
    memory = MemoryManager(EpisodicMemoryStore(session_factory))
    project_state_store = ProjectStateStore(session_factory)
    schedule_store = ScheduleStore(session_factory)
    context_assembler = ContextAssembler(
        memory_manager=memory, project_state_store=project_state_store
    )
    security = SecurityManager()
    registry = ToolRegistry()
    registry.register_tool(ScheduleListTool(schedule_store))
    registry.register_tool(ScheduleEnableTool(schedule_store))
    registry.register_tool(ScheduleVerifyEnabledStateTool(schedule_store))
    logger = _RecordingLogger()
    executor = ToolExecutor(
        registry=registry, security_manager=security, logger=logger  # type: ignore[arg-type]
    )
    pending_store = PendingApprovalStore(session_factory) if durable else None
    approvals = ApprovalManager(
        pending_store=pending_store, timeout_seconds=timeout_seconds, clock=clock
    )
    paused_store = PausedWorkflowStore(session_factory) if durable else None
    workflow_engine = WorkflowEngine(
        executor=executor,
        approvals=approvals,
        logger=logger,  # type: ignore[arg-type]
        paused_store=paused_store,
    )
    orchestrator = JarvisOrchestrator(
        planner=Planner(security),
        executor=executor,
        registry=registry,
        command_router=CommandRouter(registry),
        security_manager=security,
        memory_manager=memory,
        logger=logger,  # type: ignore[arg-type]
        context_assembler=context_assembler,
        tool_selection_router=router,
        workflow_engine=workflow_engine,
        approval_manager=approvals,
    )
    return orchestrator, schedule_store, registry, security, approvals, workflow_engine


def _in_memory_session_factory():
    engine = create_engine("sqlite:///:memory:")
    initialize_database(engine)
    return create_session_factory(engine)


def _seed_disabled_schedule(schedule_store: ScheduleStore) -> int:
    record = schedule_store.create(query="daily digest search", time_of_day="09:00")
    schedule_store.disable(record.id)
    return record.id


def _seed_enabled_schedule(schedule_store: ScheduleStore) -> int:
    record = schedule_store.create(query="daily digest search", time_of_day="09:00")
    return record.id


def _request_for(schedule_id: int) -> str:
    return f"ask jarvis to: enable schedule {schedule_id}"


# --- E. Approval tests -----------------------------------------------------------


def test_schedule_enable_cannot_execute_without_approval() -> None:
    session_factory = _in_memory_session_factory()
    schedule_store = ScheduleStore(session_factory)
    schedule_id = _seed_disabled_schedule(schedule_store)
    router, provider = _router(_schedule_enable_text(schedule_id))
    orchestrator, schedule_store, *_ = _build_stack(session_factory, router)

    response = orchestrator.handle_request(_request_for(schedule_id))

    assert response.success is False
    assert response.requires_confirmation is True
    assert schedule_store.get(schedule_id).enabled is False


def test_initial_request_creates_a_real_pending_approval() -> None:
    session_factory = _in_memory_session_factory()
    schedule_store = ScheduleStore(session_factory)
    schedule_id = _seed_disabled_schedule(schedule_store)
    router, _ = _router(_schedule_enable_text(schedule_id))
    orchestrator, *_rest, approvals, _ = _build_stack(session_factory, router)

    response = orchestrator.handle_request(_request_for(schedule_id))

    assert response.approval_request is not None
    assert approvals.has_pending(response.approval_request.request_id)
    assert response.approval_request.security_tier.name == "YELLOW"


def test_store_unchanged_while_pending() -> None:
    session_factory = _in_memory_session_factory()
    schedule_store = ScheduleStore(session_factory)
    schedule_id = _seed_disabled_schedule(schedule_store)
    router, _ = _router(_schedule_enable_text(schedule_id))
    orchestrator, *_ = _build_stack(session_factory, router)

    orchestrator.handle_request(_request_for(schedule_id))

    assert schedule_store.get(schedule_id).enabled is False


def test_verifier_does_not_execute_while_pending() -> None:
    session_factory = _in_memory_session_factory()
    schedule_store = ScheduleStore(session_factory)
    schedule_id = _seed_disabled_schedule(schedule_store)
    router, _ = _router(_schedule_enable_text(schedule_id))
    orchestrator, *_ = _build_stack(session_factory, router)

    response = orchestrator.handle_request(_request_for(schedule_id))

    assert response.tool_result is not None
    assert response.tool_result.tool_name == "schedule_enable"
    assert response.tool_result.requires_confirmation is True


def test_approval_executes_the_workflow_exactly_once() -> None:
    session_factory = _in_memory_session_factory()
    schedule_store = ScheduleStore(session_factory)
    schedule_id = _seed_disabled_schedule(schedule_store)
    router, _ = _router(_schedule_enable_text(schedule_id))
    orchestrator, *_rest, approvals, _ = _build_stack(session_factory, router)

    response = orchestrator.handle_request(_request_for(schedule_id))
    decision = approvals.approve(response.approval_request.request_id, decided_by="test")
    final = orchestrator.execute_approved(response, decision)

    assert final.success is True
    assert schedule_store.get(schedule_id).enabled is True


def test_already_enabled_schedule_preserves_existing_tool_behavior() -> None:
    """ScheduleEnableTool's real behavior is to set enabled=True
    unconditionally - it never fails or reports a special "already
    enabled" state. Approving/executing against an already-enabled
    schedule succeeds normally, and verification still confirms True."""
    session_factory = _in_memory_session_factory()
    schedule_store = ScheduleStore(session_factory)
    schedule_id = _seed_enabled_schedule(schedule_store)
    assert schedule_store.get(schedule_id).enabled is True
    router, _ = _router(_schedule_enable_text(schedule_id))
    orchestrator, *_rest, approvals, _ = _build_stack(session_factory, router)

    response = orchestrator.handle_request(_request_for(schedule_id))
    decision = approvals.approve(response.approval_request.request_id, decided_by="test")
    final = orchestrator.execute_approved(response, decision)

    assert final.success is True
    assert schedule_store.get(schedule_id).enabled is True
    assert "Verification succeeded" in final.message


def test_decline_executes_zero_enables() -> None:
    session_factory = _in_memory_session_factory()
    schedule_store = ScheduleStore(session_factory)
    schedule_id = _seed_disabled_schedule(schedule_store)
    router, _ = _router(_schedule_enable_text(schedule_id))
    orchestrator, *_rest, approvals, _ = _build_stack(session_factory, router)

    response = orchestrator.handle_request(_request_for(schedule_id))
    decision = approvals.decline(response.approval_request.request_id, decided_by="test")
    final = orchestrator.execute_approved(response, decision)

    assert final.success is False
    assert schedule_store.get(schedule_id).enabled is False
    assert final.intelligence_trace == (
        "Step 1/2: enable did not execute; no verification attempted.",
    )


def test_cancellation_has_no_distinct_mechanism_and_is_the_decline_path() -> None:
    """Phase 94, Batch 3 architecture note: this repository has no
    separate "cancellation" lifecycle for a pending approval or a
    paused workflow - ui/approval_prompt.py's own _DECLINE_INPUTS
    frozenset accepts the literal word "cancel" as one of several
    inputs that all resolve to the identical ApprovalManager.decline()
    call (alongside "n"/"no"/"decline"). There is no
    ApprovalStatus.CANCELLED, no ApprovalManager.cancel() method, and
    no separate audit/history status distinct from "declined" anywhere
    in the codebase (confirmed by direct inspection of
    approval/approval_manager.py, approval/approval_models.py, and
    ui/approval_prompt.py during this closure pass). This test proves
    that fact directly, rather than merely asserting it in prose:
    "cancel" is recognised as a decline input at the UI layer, and the
    resulting zero-execution/zero-verification/unchanged-durable-state
    evidence is therefore identical to test_decline_executes_zero_enables
    above - never a separate code path to test."""
    from ui.approval_prompt import _DECLINE_INPUTS

    assert "cancel" in _DECLINE_INPUTS
    assert "decline" in _DECLINE_INPUTS

    session_factory = _in_memory_session_factory()
    schedule_store = ScheduleStore(session_factory)
    schedule_id = _seed_disabled_schedule(schedule_store)
    router, _ = _router(_schedule_enable_text(schedule_id))
    orchestrator, *_rest, approvals, _ = _build_stack(session_factory, router)

    response = orchestrator.handle_request(_request_for(schedule_id))
    # "cancel" is not a distinct ApprovalManager verb - the real
    # decision it produces is always decline().
    decision = approvals.decline(response.approval_request.request_id, decided_by="test")
    final = orchestrator.execute_approved(response, decision)

    assert final.success is False
    assert schedule_store.get(schedule_id).enabled is False
    assert final.intelligence_trace == (
        "Step 1/2: enable did not execute; no verification attempted.",
    )
    # A cancelled/declined workflow cannot be resumed a second time.
    second = orchestrator.execute_approved(response, decision)
    assert second.tool_result is None
    assert schedule_store.get(schedule_id).enabled is False


class _FakeClock:
    """A settable clock, matching test_workflow_engine.py's own
    established convention, so elapsed approval-timeout windows can be
    simulated exactly and deterministically."""

    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


def test_expiry_performs_zero_execution_and_zero_verification() -> None:
    """Real ApprovalManager YELLOW-timeout expiry (Phase 27), exercised
    end-to-end for the schedule-enable-and-verify workflow, mirroring
    test_workflow_engine.py's test_expired_approval_is_reaped_and_
    unblocks_a_new_run/test_has_paused_reports_false_once_approval_
    expires patterns exactly: a fake, settable clock plus a real
    positive timeout_seconds proves the approval window elapsing is a
    genuinely distinct lifecycle event from a decline - never
    reachable by pretending a decline occurred."""
    from datetime import datetime, timedelta, timezone

    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    fake_clock = _FakeClock(start)
    session_factory = _in_memory_session_factory()
    schedule_store = ScheduleStore(session_factory)
    schedule_id = _seed_disabled_schedule(schedule_store)
    router, _ = _router(_schedule_enable_text(schedule_id))
    orchestrator, schedule_store, _, _, approvals, workflow_engine = _build_stack(
        session_factory, router, durable=True, timeout_seconds=60, clock=fake_clock
    )

    response = orchestrator.handle_request(_request_for(schedule_id))
    request_id = response.approval_request.request_id
    assert approvals.has_pending(request_id) is True

    paused_store = PausedWorkflowStore(session_factory)
    persisted_rows = paused_store.list_all()
    assert len(persisted_rows) == 1
    workflow_id = persisted_rows[0].workflow_id
    assert workflow_engine.has_paused(workflow_id) is True

    # Advance time past the 60-second YELLOW window without ever
    # approving, declining, or resuming.
    fake_clock.now = start + timedelta(seconds=61)

    # Expiry is lazily swept on the next read - never a background
    # thread, never automatic execution of anything.
    assert approvals.has_pending(request_id) is False
    assert workflow_engine.has_paused(workflow_id) is False
    assert schedule_store.get(schedule_id).enabled is False

    # An expired approval can never be approved or declined after the
    # fact - it is genuinely gone, not silently still actionable.
    with pytest.raises(ApprovalError):
        approvals.approve(request_id, decided_by="test")
    with pytest.raises(ApprovalError):
        approvals.decline(request_id, decided_by="test")

    # The durable schedule state never changed as a result of expiry.
    assert schedule_store.get(schedule_id).enabled is False


def test_no_fabricated_approval_is_ever_created_by_intelligence_code() -> None:
    import intelligence.planning as module

    tree = ast.parse(inspect.getsource(module))
    identifiers: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            identifiers.add(node.id)
        elif isinstance(node, ast.Attribute):
            identifiers.add(node.attr)

    assert "ApprovalManager" not in identifiers
    assert "create_request" not in identifiers


# --- F. Restart tests --------------------------------------------------------------


def test_durable_restart_end_to_end() -> None:
    engine = create_engine("sqlite:///:memory:")
    initialize_database(engine)
    session_factory = create_session_factory(engine)
    schedule_store_for_seed = ScheduleStore(session_factory)
    schedule_id = _seed_disabled_schedule(schedule_store_for_seed)

    router, _ = _router(_schedule_enable_text(schedule_id))
    orchestrator, schedule_store, *_ = _build_stack(
        session_factory, router, durable=True
    )

    response = orchestrator.handle_request(_request_for(schedule_id))
    assert response.approval_request is not None

    # Reconstruct every service fresh, over the same durable session
    # factory, simulating a real process restart.
    logger2 = _RecordingLogger()
    pending_store2 = PendingApprovalStore(session_factory)
    approvals2 = ApprovalManager(pending_store=pending_store2)
    paused_store2 = PausedWorkflowStore(session_factory)
    memory2 = MemoryManager(EpisodicMemoryStore(session_factory))
    project_state_store2 = ProjectStateStore(session_factory)
    schedule_store2 = ScheduleStore(session_factory)
    context_assembler2 = ContextAssembler(
        memory_manager=memory2, project_state_store=project_state_store2
    )
    security2 = SecurityManager()
    registry2 = ToolRegistry()
    registry2.register_tool(ScheduleListTool(schedule_store2))
    registry2.register_tool(ScheduleEnableTool(schedule_store2))
    registry2.register_tool(ScheduleVerifyEnabledStateTool(schedule_store2))
    executor2 = ToolExecutor(
        registry=registry2, security_manager=security2, logger=logger2  # type: ignore[arg-type]
    )
    workflow_engine2 = WorkflowEngine(
        executor=executor2,
        approvals=approvals2,
        logger=logger2,  # type: ignore[arg-type]
        paused_store=paused_store2,
    )

    # Confirm the durable paused plan really contains both steps and the
    # exact schedule id, before any reload logic runs.
    persisted_rows = paused_store2.list_all()
    assert len(persisted_rows) == 1
    assert len(persisted_rows[0].plan_steps) == 2
    assert persisted_rows[0].plan_steps[0]["tool_input"]["schedule_id"] == schedule_id

    approvals2.reload_pending(registry=registry2, security_manager=security2)
    reload_report = workflow_engine2.reload_paused(
        registry=registry2, security_manager=security2
    )
    assert reload_report.resumed == 1
    assert reload_report.invalidated == 0

    orchestrator2 = JarvisOrchestrator(
        planner=Planner(security2),
        executor=executor2,
        registry=registry2,
        command_router=CommandRouter(registry2),
        security_manager=security2,
        memory_manager=memory2,
        logger=logger2,  # type: ignore[arg-type]
        context_assembler=context_assembler2,
        tool_selection_router=router,
        workflow_engine=workflow_engine2,
        approval_manager=approvals2,
    )

    decision = approvals2.approve(response.approval_request.request_id, decided_by="test")
    final = orchestrator2.execute_approved(response, decision)

    assert final.success is True
    assert schedule_store2.get(schedule_id).enabled is True


# --- G. Verification tests (integration) --------------------------------------


class _MismatchingScheduleVerifyTool:
    """A test double for schedule_verify_enabled_state that always
    reports enabled=False, regardless of the real durable state - used
    only to exercise a genuine FAILED-verification path, since the real
    enable-then-verify pair always agrees in the ordinary flow."""

    name = "schedule_verify_enabled_state"
    description = "test double reporting a fixed, mismatching enabled state"

    def action_for(self, request):
        return "show schedule enabled state"

    def run(self, request):
        from tools.base_tool import ToolResult

        return ToolResult(
            tool_name=self.name,
            success=True,
            output="mismatched test double",
            metadata={"schedule_id": request.input_data.get("schedule_id"), "enabled": False},
        )


class _MissingTargetScheduleVerifyTool:
    """A test double simulating the schedule disappearing between
    execution and verification - reports a genuine missing-target
    failure, never a fabricated success."""

    name = "schedule_verify_enabled_state"
    description = "test double reporting a missing verification target"

    def action_for(self, request):
        return "show schedule enabled state"

    def run(self, request):
        from tools.base_tool import ToolResult

        schedule_id = request.input_data.get("schedule_id")
        return ToolResult(
            tool_name=self.name,
            success=False,
            error=f"No schedule found with id {schedule_id}.",
        )


class _FailingScheduleVerifyTool:
    """A test double simulating a genuine verifier-tool failure
    unrelated to the schedule's actual state."""

    name = "schedule_verify_enabled_state"
    description = "test double that always fails at run() time"

    def action_for(self, request):
        return "show schedule enabled state"

    def run(self, request):
        from tools.base_tool import ToolResult

        return ToolResult(
            tool_name=self.name, success=False, error="simulated verifier failure"
        )


class _FailingScheduleEnableTool:
    """A test double for schedule_enable that classifies exactly like
    the real tool (so it still pauses for approval) but always fails
    its own run(), for exercising "write failure -> verifier never
    runs"."""

    name = "schedule_enable"
    description = "test double that always fails at run() time"

    def action_for(self, request):
        return "enable schedule"

    def run(self, request):
        from tools.base_tool import ToolResult

        return ToolResult(
            tool_name=self.name, success=False, error="simulated write failure"
        )


def test_exact_mismatch_reports_failed_verification() -> None:
    session_factory = _in_memory_session_factory()
    schedule_store = ScheduleStore(session_factory)
    schedule_id = _seed_disabled_schedule(schedule_store)
    router, _ = _router(_schedule_enable_text(schedule_id))
    orchestrator, schedule_store, registry, _, approvals, _ = _build_stack(
        session_factory, router
    )
    registry._tools["schedule_verify_enabled_state"] = (  # type: ignore[attr-defined]
        _MismatchingScheduleVerifyTool()
    )

    response = orchestrator.handle_request(_request_for(schedule_id))
    decision = approvals.approve(response.approval_request.request_id, decided_by="test")
    final = orchestrator.execute_approved(response, decision)

    assert final.success is False
    assert "not confirmed" in final.message
    assert "reported success" in final.message
    assert final.intelligence_trace[1] == "Step 2/2: verification failed."
    # The real write itself still genuinely happened.
    assert schedule_store.get(schedule_id).enabled is True


def test_write_failure_means_verifier_never_runs() -> None:
    session_factory = _in_memory_session_factory()
    schedule_store = ScheduleStore(session_factory)
    schedule_id = _seed_disabled_schedule(schedule_store)
    router, _ = _router(_schedule_enable_text(schedule_id))
    orchestrator, schedule_store, registry, _, approvals, _ = _build_stack(
        session_factory, router
    )
    registry._tools["schedule_enable"] = _FailingScheduleEnableTool()  # type: ignore[attr-defined]

    response = orchestrator.handle_request(_request_for(schedule_id))
    decision = approvals.approve(response.approval_request.request_id, decided_by="test")
    final = orchestrator.execute_approved(response, decision)

    assert final.success is False
    assert final.intelligence_trace == (
        "Step 1/2: enable did not execute; no verification attempted.",
    )
    assert schedule_store.get(schedule_id).enabled is False


def test_missing_schedule_at_execution_time_reports_honest_failure() -> None:
    """A request naming a schedule id that never existed still passes
    grounding/preflight/approval (which never inspects store contents)
    - the real ScheduleEnableTool's own existing "No schedule found"
    failure is what honestly surfaces at execution time, and
    verification never runs."""
    session_factory = _in_memory_session_factory()
    nonexistent_id = 999999
    router, _ = _router(_schedule_enable_text(nonexistent_id))
    orchestrator, schedule_store, _, _, approvals, _ = _build_stack(
        session_factory, router
    )

    response = orchestrator.handle_request(_request_for(nonexistent_id))
    decision = approvals.approve(response.approval_request.request_id, decided_by="test")
    final = orchestrator.execute_approved(response, decision)

    assert final.success is False
    assert final.intelligence_trace == (
        "Step 1/2: enable did not execute; no verification attempted.",
    )


def test_schedule_disappearing_before_verification_is_reported_honestly() -> None:
    """A narrow test double simulates the schedule becoming
    unavailable exactly at verification time (never recreated, never
    retried) - an honest UNAVAILABLE-shaped failure, not a crash or a
    false VERIFIED."""
    session_factory = _in_memory_session_factory()
    schedule_store = ScheduleStore(session_factory)
    schedule_id = _seed_disabled_schedule(schedule_store)
    router, _ = _router(_schedule_enable_text(schedule_id))
    orchestrator, schedule_store, registry, _, approvals, _ = _build_stack(
        session_factory, router
    )
    registry._tools["schedule_verify_enabled_state"] = (  # type: ignore[attr-defined]
        _MissingTargetScheduleVerifyTool()
    )

    response = orchestrator.handle_request(_request_for(schedule_id))
    decision = approvals.approve(response.approval_request.request_id, decided_by="test")
    final = orchestrator.execute_approved(response, decision)

    assert final.success is False
    assert "could not be completed" in final.message
    assert final.intelligence_trace[1] == "Step 2/2: verification unavailable."


def test_verifier_tool_failure_is_reported_honestly() -> None:
    session_factory = _in_memory_session_factory()
    schedule_store = ScheduleStore(session_factory)
    schedule_id = _seed_disabled_schedule(schedule_store)
    router, _ = _router(_schedule_enable_text(schedule_id))
    orchestrator, schedule_store, registry, _, approvals, _ = _build_stack(
        session_factory, router
    )
    registry._tools["schedule_verify_enabled_state"] = (  # type: ignore[attr-defined]
        _FailingScheduleVerifyTool()
    )

    response = orchestrator.handle_request(_request_for(schedule_id))
    decision = approvals.approve(response.approval_request.request_id, decided_by="test")
    final = orchestrator.execute_approved(response, decision)

    assert final.success is False
    assert final.intelligence_trace[1] == "Step 2/2: verification unavailable."
    # The real write itself still genuinely happened - verifier
    # failure never implies the write itself failed.
    assert schedule_store.get(schedule_id).enabled is True


# --- H. Response/trace tests --------------------------------------------------------


def test_pending_response_says_not_executed() -> None:
    session_factory = _in_memory_session_factory()
    schedule_store = ScheduleStore(session_factory)
    schedule_id = _seed_disabled_schedule(schedule_store)
    router, _ = _router(_schedule_enable_text(schedule_id))
    orchestrator, *_ = _build_stack(session_factory, router)

    response = orchestrator.handle_request(_request_for(schedule_id))

    assert response.success is False
    assert response.requires_confirmation is True
    assert len(response.intelligence_trace) == 1
    assert len(response.intelligence_trace[0]) <= 200


def test_approved_verified_response_is_grounded_in_real_values() -> None:
    session_factory = _in_memory_session_factory()
    schedule_store = ScheduleStore(session_factory)
    schedule_id = _seed_disabled_schedule(schedule_store)
    router, _ = _router(_schedule_enable_text(schedule_id))
    orchestrator, *_rest, approvals, _ = _build_stack(session_factory, router)

    response = orchestrator.handle_request(_request_for(schedule_id))
    decision = approvals.approve(response.approval_request.request_id, decided_by="test")
    final = orchestrator.execute_approved(response, decision)

    assert final.success is True
    assert str(schedule_id) in final.message
    assert "Verification succeeded" in final.message
    assert len(final.intelligence_trace) == 2
    assert all(len(entry) <= 200 for entry in final.intelligence_trace)
    assert "verified" in final.intelligence_trace[1]


def test_declined_response_says_no_enable_was_made() -> None:
    session_factory = _in_memory_session_factory()
    schedule_store = ScheduleStore(session_factory)
    schedule_id = _seed_disabled_schedule(schedule_store)
    router, _ = _router(_schedule_enable_text(schedule_id))
    orchestrator, *_rest, approvals, _ = _build_stack(session_factory, router)

    response = orchestrator.handle_request(_request_for(schedule_id))
    decision = approvals.decline(response.approval_request.request_id, decided_by="test")
    final = orchestrator.execute_approved(response, decision)

    assert final.success is False
    assert schedule_store.get(schedule_id).enabled is False


def test_no_raw_dictionaries_in_intelligence_trace() -> None:
    session_factory = _in_memory_session_factory()
    schedule_store = ScheduleStore(session_factory)
    schedule_id = _seed_disabled_schedule(schedule_store)
    router, _ = _router(_schedule_enable_text(schedule_id))
    orchestrator, *_rest, approvals, _ = _build_stack(session_factory, router)

    response = orchestrator.handle_request(_request_for(schedule_id))
    decision = approvals.approve(response.approval_request.request_id, decided_by="test")
    final = orchestrator.execute_approved(response, decision)

    for entry in final.intelligence_trace:
        assert "{" not in entry
        assert "tool_input" not in entry


def test_no_second_ai_call_after_execution() -> None:
    session_factory = _in_memory_session_factory()
    schedule_store = ScheduleStore(session_factory)
    schedule_id = _seed_disabled_schedule(schedule_store)
    router, provider = _router(_schedule_enable_text(schedule_id))
    orchestrator, *_rest, approvals, _ = _build_stack(session_factory, router)

    response = orchestrator.handle_request(_request_for(schedule_id))
    assert len(provider.received_requests) == 1
    decision = approvals.approve(response.approval_request.request_id, decided_by="test")
    orchestrator.execute_approved(response, decision)

    assert len(provider.received_requests) == 1


# --- I. Routing/regression tests -----------------------------------------------------


def test_ask_jarvis_advisory_remains_unaffected_by_schedule_enable_addition() -> None:
    router, _ = _router(_schedule_enable_text(1))
    orchestrator, *_ = _build_stack(_in_memory_session_factory(), router)

    response = orchestrator.handle_request("ask jarvis: what is my focus")

    assert response.success is False
    assert "AI reasoning is not enabled" in response.message


def test_existing_deterministic_command_remains_unaffected() -> None:
    session_factory = _in_memory_session_factory()
    schedule_store = ScheduleStore(session_factory)
    schedule_id = _seed_disabled_schedule(schedule_store)
    router, _ = _router(_schedule_enable_text(schedule_id))
    orchestrator, *_ = _build_stack(session_factory, router)

    response = orchestrator.handle_request("show schedules")

    assert response.success is True
    assert str(schedule_id) in response.message


# --- J. Structural tests --------------------------------------------------------------


def test_planning_module_never_calls_schedule_store_update_directly() -> None:
    import intelligence.planning as module

    source = inspect.getsource(module)
    assert "ScheduleStore" not in source
    assert ".enable(" not in source
    assert ".disable(" not in source


def test_orchestrator_schedule_enable_response_translator_never_bypasses_workflow_engine() -> (
    None
):
    from core.orchestrator import JarvisOrchestrator

    source = inspect.getsource(
        JarvisOrchestrator._schedule_enable_workflow_result_to_response
    )
    assert "self._executor.execute(" not in source
    assert "ScheduleStore" not in source


# --- K. Phase 94, Batch 2: grounding refusal zero-side-effect tests ---------------


def test_ungrounded_schedule_enable_value_creates_no_approval_and_no_write() -> None:
    session_factory = _in_memory_session_factory()
    schedule_store = ScheduleStore(session_factory)
    schedule_id = _seed_disabled_schedule(schedule_store)
    wrong_id = schedule_id + 1000
    router, provider = _router(_schedule_enable_text(wrong_id))
    orchestrator, schedule_store, _, _, approvals, _ = _build_stack(
        session_factory, router
    )

    response = orchestrator.handle_request(_request_for(schedule_id))

    assert response.success is False
    assert response.requires_confirmation is False
    assert response.approval_request is None
    assert approvals.list_pending() == []
    assert schedule_store.get(schedule_id).enabled is False
    assert len(provider.received_requests) == 1


def test_negated_schedule_enable_request_creates_no_approval_and_no_write() -> None:
    session_factory = _in_memory_session_factory()
    schedule_store = ScheduleStore(session_factory)
    schedule_id = _seed_disabled_schedule(schedule_store)
    router, _ = _router(_schedule_enable_text(schedule_id))
    orchestrator, schedule_store, _, _, approvals, _ = _build_stack(
        session_factory, router
    )

    response = orchestrator.handle_request(
        f"ask jarvis to: do not enable schedule {schedule_id}"
    )

    assert response.success is False
    assert response.requires_confirmation is False
    assert approvals.list_pending() == []
    assert schedule_store.get(schedule_id).enabled is False


def test_ungrounded_schedule_enable_never_reaches_workflow_engine() -> None:
    import textwrap

    from core.orchestrator import JarvisOrchestrator

    source = inspect.getsource(JarvisOrchestrator._handle_ask_jarvis_to_request)
    tree = ast.parse(textwrap.dedent(source))

    ungrounded_branch_calls_start_workflow = False
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            test_source = ast.unparse(node.test)
            if "UNGROUNDED_SELECTION" in test_source:
                branch_source = ast.unparse(node)
                if "_start_update_focus_workflow" in branch_source:
                    ungrounded_branch_calls_start_workflow = True

    assert ungrounded_branch_calls_start_workflow is False


def test_ungrounded_schedule_enable_response_message_never_leaks_the_candidate_id() -> (
    None
):
    session_factory = _in_memory_session_factory()
    schedule_store = ScheduleStore(session_factory)
    schedule_id = _seed_disabled_schedule(schedule_store)
    wrong_id = schedule_id + 1000
    router, _ = _router(_schedule_enable_text(wrong_id))
    orchestrator, *_ = _build_stack(session_factory, router)

    response = orchestrator.handle_request(_request_for(schedule_id))

    assert str(wrong_id) not in response.message
    assert response.plan is not None


def test_capability_mismatch_for_schedule_enable_executes_neither_tool() -> None:
    """A request that uniquely grounds schedule_list, while the model
    instead selects schedule_enable, is refused as
    selected_capability_not_unique_match - neither tool executes, and
    the enable workflow is never even attempted."""
    session_factory = _in_memory_session_factory()
    schedule_store = ScheduleStore(session_factory)
    schedule_id = _seed_disabled_schedule(schedule_store)
    router, _ = _router(_schedule_enable_text(schedule_id))
    orchestrator, schedule_store, _, _, approvals, _ = _build_stack(
        session_factory, router
    )

    response = orchestrator.handle_request("ask jarvis to: show my schedules")

    assert response.success is False
    assert response.tool_result is None
    assert response.requires_confirmation is False
    assert approvals.list_pending() == []
    assert schedule_store.get(schedule_id).enabled is False


# --- L. Duplicate-execution and argument-immutability tests -----------------------


def test_duplicate_resume_does_not_duplicate_the_enable() -> None:
    session_factory = _in_memory_session_factory()
    schedule_store = ScheduleStore(session_factory)
    schedule_id = _seed_disabled_schedule(schedule_store)
    router, _ = _router(_schedule_enable_text(schedule_id))
    orchestrator, schedule_store, _, _, approvals, _ = _build_stack(
        session_factory, router
    )

    response = orchestrator.handle_request(_request_for(schedule_id))
    decision = approvals.approve(response.approval_request.request_id, decided_by="test")
    first = orchestrator.execute_approved(response, decision)

    assert first.success is True
    assert schedule_store.get(schedule_id).enabled is True

    second = orchestrator.execute_approved(response, decision)

    assert schedule_store.get(schedule_id).enabled is True
    assert second.tool_result is None


def test_approved_schedule_id_is_immutable_between_approval_and_execution() -> None:
    session_factory = _in_memory_session_factory()
    schedule_store = ScheduleStore(session_factory)
    schedule_id = _seed_disabled_schedule(schedule_store)
    other_id = _seed_disabled_schedule(schedule_store)
    router, provider = _router(_schedule_enable_text(schedule_id))
    orchestrator, schedule_store, _, _, approvals, _ = _build_stack(
        session_factory, router
    )

    response = orchestrator.handle_request(_request_for(schedule_id))
    decision = approvals.approve(response.approval_request.request_id, decided_by="test")

    # Simulate a would-be-different value becoming available from the
    # same fake provider after approval - this must have zero effect,
    # since the already-built, already-approved Plan/PlanStep.tool_input
    # is what resume() actually executes, never a freshly re-derived one.
    provider._text = _schedule_enable_text(other_id)  # type: ignore[attr-defined]

    final = orchestrator.execute_approved(response, decision)

    assert final.success is True
    assert schedule_store.get(schedule_id).enabled is True
    assert schedule_store.get(other_id).enabled is False


# --- M. Coexistence of both trusted verified workflows -----------------------------


def test_both_verified_workflows_coexist_without_dispatch_ambiguity() -> None:
    """A single real orchestrator instance, wired with both real
    verified workflows' tools, correctly dispatches each real request
    to its own capability-specific response translator - proving the
    Batch 1 foundation genuinely supports two trusted workflow
    definitions at once, never confusing one for the other."""
    session_factory = _in_memory_session_factory()
    memory = MemoryManager(EpisodicMemoryStore(session_factory))
    project_state_store = ProjectStateStore(session_factory)
    schedule_store = ScheduleStore(session_factory)
    schedule_id = _seed_disabled_schedule(schedule_store)
    context_assembler = ContextAssembler(
        memory_manager=memory, project_state_store=project_state_store
    )
    security = SecurityManager()
    registry = ToolRegistry()
    registry.register_tool(ProjectStateShowTool(project_state_store))
    registry.register_tool(ProjectStateUpdateTool(project_state_store))
    registry.register_tool(ProjectStateVerifyTool(project_state_store))
    registry.register_tool(ScheduleListTool(schedule_store))
    registry.register_tool(ScheduleEnableTool(schedule_store))
    registry.register_tool(ScheduleVerifyEnabledStateTool(schedule_store))
    logger = _RecordingLogger()
    executor = ToolExecutor(
        registry=registry, security_manager=security, logger=logger  # type: ignore[arg-type]
    )
    approvals = ApprovalManager(pending_store=None)
    workflow_engine = WorkflowEngine(
        executor=executor, approvals=approvals, logger=logger  # type: ignore[arg-type]
    )

    # First: the focus-update workflow, using its own fake router.
    focus_router, _ = _router(
        json.dumps(
            {
                "decision": "execute",
                "capability_id": "project_state_update_focus",
                "arguments": {"value": "coexistence check"},
            }
        )
    )
    orchestrator = JarvisOrchestrator(
        planner=Planner(security),
        executor=executor,
        registry=registry,
        command_router=CommandRouter(registry),
        security_manager=security,
        memory_manager=memory,
        logger=logger,  # type: ignore[arg-type]
        context_assembler=context_assembler,
        tool_selection_router=focus_router,
        workflow_engine=workflow_engine,
        approval_manager=approvals,
    )
    focus_response = orchestrator.handle_request(
        "ask jarvis to: update my project focus to coexistence check"
    )
    focus_decision = approvals.approve(
        focus_response.approval_request.request_id, decided_by="test"
    )
    focus_final = orchestrator.execute_approved(focus_response, focus_decision)

    assert focus_final.success is True
    assert "coexistence check" in focus_final.message
    assert project_state_store.get().focus == "coexistence check"
    assert schedule_store.get(schedule_id).enabled is False  # unaffected

    # Then: the schedule-enable workflow, on the same orchestrator/
    # registry/executor/approvals/workflow_engine instances, using a
    # freshly re-pointed router (the orchestrator's own router
    # attribute is swapped exactly like main.py would for a real
    # follow-up request).
    schedule_router, _ = _router(_schedule_enable_text(schedule_id))
    orchestrator._tool_selection_router = schedule_router  # type: ignore[attr-defined]
    schedule_response = orchestrator.handle_request(_request_for(schedule_id))
    schedule_decision = approvals.approve(
        schedule_response.approval_request.request_id, decided_by="test"
    )
    schedule_final = orchestrator.execute_approved(schedule_response, schedule_decision)

    assert schedule_final.success is True
    assert schedule_store.get(schedule_id).enabled is True
    assert "coexistence check" not in schedule_final.message
    assert project_state_store.get().focus == "coexistence check"  # unaffected
