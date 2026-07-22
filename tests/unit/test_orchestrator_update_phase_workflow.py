"""
test_orchestrator_update_phase_workflow.py

Unit tests for the explicit "ask jarvis to: update my project phase to
X" write-and-verify workflow (Phase 96 -
docs/phase_96_implementation_plan.md), mirroring
test_orchestrator_update_focus_workflow.py's own established pattern
exactly for the fourth real, trusted verified write workflow:
CommandRouter.match_ask_jarvis_to() ->
JarvisOrchestrator._handle_ask_jarvis_to_request() ->
intelligence.planning.select_tool() (EXECUTABLE_WORKFLOW) ->
WorkflowEngine.run()/resume() -> JarvisOrchestrator.execute_approved().

PROJECT_STATE_UPDATE_PHASE reuses the identical internal verifier
(PROJECT_STATE_VERIFY_FOCUS/ProjectStateVerifyTool, and the real
project_state_update/project_state_verify tools) that
PROJECT_STATE_UPDATE_FOCUS already uses - the only differences are the
trusted, fixed "field": "phase" literal (never model-supplied) and the
distinct verification_strategy_id/verifier_id.

Uses real Planner, SecurityManager, CommandRouter, ToolRegistry,
ToolExecutor, ApprovalManager, WorkflowEngine, MemoryManager (over a
real in-memory SQLite EpisodicMemoryStore), real ProjectStateStore, the
real ProjectStateUpdateTool/ProjectStateVerifyTool, real
ContextAssembler, and a real AIRouter wired to a real PromptBuilder and
a fake, in-memory AIProvider - no live Claude API call is ever made, no
real network call is ever made.

sqlalchemy-dependent imports are guarded by a try/except ImportError,
mirroring test_orchestrator_update_focus_workflow.py's own established
pattern.

Run with:
    pytest tests/unit/test_orchestrator_update_phase_workflow.py
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
    from security.security_manager import SecurityManager
    from storage.database import create_session_factory, initialize_database
    from tools.builtin.project_state_show_tool import ProjectStateShowTool
    from tools.builtin.project_state_update_tool import ProjectStateUpdateTool
    from tools.builtin.project_state_verify_tool import ProjectStateVerifyTool
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


def _update_phase_text(value: str) -> str:
    return json.dumps(
        {
            "decision": "execute",
            "capability_id": "project_state_update_phase",
            "arguments": {"value": value},
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
    context_assembler = ContextAssembler(
        memory_manager=memory, project_state_store=project_state_store
    )
    security = SecurityManager()
    registry = ToolRegistry()
    registry.register_tool(ProjectStateShowTool(project_state_store))
    registry.register_tool(ProjectStateUpdateTool(project_state_store))
    registry.register_tool(ProjectStateVerifyTool(project_state_store))
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
    return orchestrator, project_state_store, registry, security, approvals, workflow_engine


def _in_memory_session_factory():
    engine = create_engine("sqlite:///:memory:")
    initialize_database(engine)
    return create_session_factory(engine)


_REQUEST = "ask jarvis to: update my project phase to Phase 96"


# --- E. Approval tests -----------------------------------------------------------


def test_update_phase_cannot_execute_without_approval() -> None:
    router, _ = _router(_update_phase_text("Phase 96"))
    orchestrator, project_state_store, *_ = _build_stack(
        _in_memory_session_factory(), router
    )

    response = orchestrator.handle_request(_REQUEST)

    assert response.success is False
    assert response.requires_confirmation is True
    assert project_state_store.get() is None


def test_initial_request_creates_a_real_pending_approval() -> None:
    router, _ = _router(_update_phase_text("Phase 96"))
    orchestrator, *_rest, approvals, _ = _build_stack(
        _in_memory_session_factory(), router
    )

    response = orchestrator.handle_request(_REQUEST)

    assert response.approval_request is not None
    assert approvals.has_pending(response.approval_request.request_id)
    assert response.approval_request.security_tier.name == "YELLOW"


def test_store_unchanged_while_pending() -> None:
    router, _ = _router(_update_phase_text("Phase 96"))
    orchestrator, project_state_store, *_ = _build_stack(
        _in_memory_session_factory(), router
    )

    orchestrator.handle_request(_REQUEST)

    assert project_state_store.get() is None


def test_verifier_does_not_execute_while_pending() -> None:
    router, _ = _router(_update_phase_text("Phase 96"))
    orchestrator, _, _, _, _, _ = _build_stack(_in_memory_session_factory(), router)

    response = orchestrator.handle_request(_REQUEST)

    assert response.tool_result is not None
    assert response.tool_result.tool_name == "project_state_update"
    assert response.tool_result.requires_confirmation is True


def test_approval_executes_the_workflow_exactly_once() -> None:
    router, _ = _router(_update_phase_text("Phase 96"))
    orchestrator, project_state_store, _, _, approvals, _ = _build_stack(
        _in_memory_session_factory(), router
    )

    response = orchestrator.handle_request(_REQUEST)
    decision = approvals.approve(response.approval_request.request_id, decided_by="test")
    final = orchestrator.execute_approved(response, decision)

    assert final.success is True
    assert project_state_store.get().phase == "Phase 96"


def test_already_matching_phase_preserves_existing_tool_behavior() -> None:
    """ProjectStateUpdateTool's real update() is unconditional - setting
    the phase field to a value it already holds succeeds normally, and
    verification still confirms the exact match honestly."""
    router, _ = _router(_update_phase_text("Phase 96"))
    orchestrator, project_state_store, _, _, approvals, _ = _build_stack(
        _in_memory_session_factory(), router
    )
    project_state_store.update("phase", "Phase 96")
    assert project_state_store.get().phase == "Phase 96"

    response = orchestrator.handle_request(_REQUEST)
    decision = approvals.approve(response.approval_request.request_id, decided_by="test")
    final = orchestrator.execute_approved(response, decision)

    assert final.success is True
    assert project_state_store.get().phase == "Phase 96"
    assert "Verification succeeded" in final.message


def test_missing_state_before_execution_is_created_not_failed() -> None:
    """ProjectStateStore.update() always creates the singleton row on
    first write - it never fails due to "no record yet". This test
    documents that real, existing behavior rather than inventing a new
    failure mode: there is no genuine "missing ProjectState at
    execution time" failure case - approving a phase update against a
    never-yet-written store succeeds and creates the row."""
    router, _ = _router(_update_phase_text("Phase 96"))
    orchestrator, project_state_store, _, _, approvals, _ = _build_stack(
        _in_memory_session_factory(), router
    )
    assert project_state_store.get() is None

    response = orchestrator.handle_request(_REQUEST)
    decision = approvals.approve(response.approval_request.request_id, decided_by="test")
    final = orchestrator.execute_approved(response, decision)

    assert final.success is True
    assert project_state_store.get() is not None
    assert project_state_store.get().phase == "Phase 96"


def test_decline_executes_zero_writes() -> None:
    router, _ = _router(_update_phase_text("Phase 96"))
    orchestrator, project_state_store, _, _, approvals, _ = _build_stack(
        _in_memory_session_factory(), router
    )

    response = orchestrator.handle_request(_REQUEST)
    decision = approvals.decline(response.approval_request.request_id, decided_by="test")
    final = orchestrator.execute_approved(response, decision)

    assert final.success is False
    assert project_state_store.get() is None
    assert final.intelligence_trace == (
        "Step 1/2: update did not execute; no verification attempted.",
    )


def test_cancellation_has_no_distinct_mechanism_and_is_the_decline_path() -> None:
    """This repository has no separate "cancellation" lifecycle for a
    pending approval or a paused workflow - ui/approval_prompt.py's own
    _DECLINE_INPUTS frozenset accepts the literal word "cancel" as one
    of several inputs that all resolve to the identical
    ApprovalManager.decline() call. This test proves that fact
    directly and confirms the resulting evidence is identical to plain
    decline."""
    from ui.approval_prompt import _DECLINE_INPUTS

    assert "cancel" in _DECLINE_INPUTS
    assert "decline" in _DECLINE_INPUTS

    router, _ = _router(_update_phase_text("Phase 96"))
    orchestrator, project_state_store, _, _, approvals, _ = _build_stack(
        _in_memory_session_factory(), router
    )

    response = orchestrator.handle_request(_REQUEST)
    decision = approvals.decline(response.approval_request.request_id, decided_by="test")
    final = orchestrator.execute_approved(response, decision)

    assert final.success is False
    assert project_state_store.get() is None
    second = orchestrator.execute_approved(response, decision)
    assert second.tool_result is None


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
    end-to-end for the update-phase-and-verify workflow, mirroring
    test_workflow_engine.py's own established fake-clock pattern."""
    from datetime import datetime, timedelta, timezone

    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    fake_clock = _FakeClock(start)
    session_factory = _in_memory_session_factory()
    router, _ = _router(_update_phase_text("Phase 96"))
    orchestrator, project_state_store, _, _, approvals, workflow_engine = _build_stack(
        session_factory, router, durable=True, timeout_seconds=60, clock=fake_clock
    )

    response = orchestrator.handle_request(_REQUEST)
    request_id = response.approval_request.request_id
    assert approvals.has_pending(request_id) is True

    paused_store = PausedWorkflowStore(session_factory)
    persisted_rows = paused_store.list_all()
    assert len(persisted_rows) == 1
    workflow_id = persisted_rows[0].workflow_id
    assert workflow_engine.has_paused(workflow_id) is True

    fake_clock.now = start + timedelta(seconds=61)

    assert approvals.has_pending(request_id) is False
    assert workflow_engine.has_paused(workflow_id) is False
    assert project_state_store.get() is None

    with pytest.raises(ApprovalError):
        approvals.approve(request_id, decided_by="test")
    with pytest.raises(ApprovalError):
        approvals.decline(request_id, decided_by="test")

    assert project_state_store.get() is None


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

    router, _ = _router(_update_phase_text("Phase 96"))
    orchestrator, project_state_store, *_ = _build_stack(
        session_factory, router, durable=True
    )

    response = orchestrator.handle_request(_REQUEST)
    assert response.approval_request is not None

    # Reconstruct every service fresh, over the same durable session
    # factory, simulating a real process restart.
    logger2 = _RecordingLogger()
    pending_store2 = PendingApprovalStore(session_factory)
    approvals2 = ApprovalManager(pending_store=pending_store2)
    paused_store2 = PausedWorkflowStore(session_factory)
    memory2 = MemoryManager(EpisodicMemoryStore(session_factory))
    project_state_store2 = ProjectStateStore(session_factory)
    context_assembler2 = ContextAssembler(
        memory_manager=memory2, project_state_store=project_state_store2
    )
    security2 = SecurityManager()
    registry2 = ToolRegistry()
    registry2.register_tool(ProjectStateShowTool(project_state_store2))
    registry2.register_tool(ProjectStateUpdateTool(project_state_store2))
    registry2.register_tool(ProjectStateVerifyTool(project_state_store2))
    executor2 = ToolExecutor(
        registry=registry2, security_manager=security2, logger=logger2  # type: ignore[arg-type]
    )
    workflow_engine2 = WorkflowEngine(
        executor=executor2,
        approvals=approvals2,
        logger=logger2,  # type: ignore[arg-type]
        paused_store=paused_store2,
    )

    persisted_rows = paused_store2.list_all()
    assert len(persisted_rows) == 1
    assert len(persisted_rows[0].plan_steps) == 2
    assert persisted_rows[0].plan_steps[0]["tool_input"]["field"] == "phase"
    assert persisted_rows[0].plan_steps[0]["tool_input"]["value"] == "Phase 96"

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
    assert "Phase 96" in final.message
    assert project_state_store2.get().phase == "Phase 96"


def test_no_transient_planning_object_required_after_restart() -> None:
    import core.orchestrator as module

    source = inspect.getsource(module.JarvisOrchestrator.execute_approved)
    assert "StructuredPlan" not in source
    assert "PlanningOutcome" not in source


# --- G. Verification tests (integration) --------------------------------------


class _MismatchingVerifyTool:
    """A test double for project_state_verify that always reports a
    fixed phase value different from whatever was actually written -
    used only to exercise a genuine FAILED-verification path."""

    name = "project_state_verify"
    description = "test double reporting a fixed, mismatching phase value"

    def action_for(self, request):
        return "show jarvis project state"

    def run(self, request):
        from tools.base_tool import ToolResult

        return ToolResult(
            tool_name=self.name,
            success=True,
            output="mismatched test double",
            metadata={"phase": "a completely different stored value"},
        )


class _MissingTargetVerifyTool:
    """A test double simulating the ProjectState record disappearing
    between execution and verification - reports a genuine missing-
    target failure, never a fabricated success."""

    name = "project_state_verify"
    description = "test double reporting a missing verification target"

    def action_for(self, request):
        return "show jarvis project state"

    def run(self, request):
        from tools.base_tool import ToolResult

        return ToolResult(
            tool_name=self.name,
            success=False,
            error="simulated missing ProjectState record",
        )


class _FailingVerifyTool:
    """A test double simulating a genuine verifier-tool failure
    unrelated to the record's actual state."""

    name = "project_state_verify"
    description = "test double that always fails at run() time"

    def action_for(self, request):
        return "show jarvis project state"

    def run(self, request):
        from tools.base_tool import ToolResult

        return ToolResult(
            tool_name=self.name, success=False, error="simulated verifier failure"
        )


class _FailingWriteTool:
    """A test double for project_state_update that classifies exactly
    like the real tool (so it still pauses for approval) but always
    fails its own run(), for exercising "write failure -> verifier
    never runs"."""

    name = "project_state_update"
    description = "test double that always fails at run() time"

    def action_for(self, request):
        return "update jarvis project state"

    def run(self, request):
        from tools.base_tool import ToolResult

        return ToolResult(
            tool_name=self.name,
            success=False,
            error="simulated write failure",
        )


def test_exact_mismatch_reports_failed_verification() -> None:
    router, _ = _router(_update_phase_text("Phase 96"))
    orchestrator, project_state_store, registry, _, approvals, _ = _build_stack(
        _in_memory_session_factory(), router
    )
    registry._tools["project_state_verify"] = _MismatchingVerifyTool()  # type: ignore[attr-defined]

    response = orchestrator.handle_request(_REQUEST)
    decision = approvals.approve(response.approval_request.request_id, decided_by="test")
    final = orchestrator.execute_approved(response, decision)

    assert final.success is False
    assert "not confirmed" in final.message
    assert "reported success" in final.message
    assert final.intelligence_trace[1] == "Step 2/2: verification failed."
    # The real write itself still genuinely happened.
    assert project_state_store.get().phase == "Phase 96"


def test_write_failure_means_verifier_never_runs() -> None:
    router, _ = _router(_update_phase_text("Phase 96"))
    orchestrator, project_state_store, registry, _, approvals, _ = _build_stack(
        _in_memory_session_factory(), router
    )
    registry._tools["project_state_update"] = _FailingWriteTool()  # type: ignore[attr-defined]

    response = orchestrator.handle_request(_REQUEST)
    decision = approvals.approve(response.approval_request.request_id, decided_by="test")
    final = orchestrator.execute_approved(response, decision)

    assert final.success is False
    assert final.intelligence_trace == (
        "Step 1/2: update did not execute; no verification attempted.",
    )
    assert project_state_store.get() is None


def test_state_disappearing_before_verification_is_reported_honestly() -> None:
    """A narrow test double simulates the ProjectState record becoming
    unreadable exactly at verification time (never recreated, never
    retried) - an honest UNAVAILABLE-shaped failure, not a crash or a
    false VERIFIED."""
    router, _ = _router(_update_phase_text("Phase 96"))
    orchestrator, project_state_store, registry, _, approvals, _ = _build_stack(
        _in_memory_session_factory(), router
    )
    registry._tools["project_state_verify"] = _MissingTargetVerifyTool()  # type: ignore[attr-defined]

    response = orchestrator.handle_request(_REQUEST)
    decision = approvals.approve(response.approval_request.request_id, decided_by="test")
    final = orchestrator.execute_approved(response, decision)

    assert final.success is False
    assert "could not be completed" in final.message
    assert final.intelligence_trace[1] == "Step 2/2: verification unavailable."
    # The real write itself still genuinely happened.
    assert project_state_store.get().phase == "Phase 96"


def test_verifier_tool_failure_is_reported_honestly() -> None:
    router, _ = _router(_update_phase_text("Phase 96"))
    orchestrator, project_state_store, registry, _, approvals, _ = _build_stack(
        _in_memory_session_factory(), router
    )
    registry._tools["project_state_verify"] = _FailingVerifyTool()  # type: ignore[attr-defined]

    response = orchestrator.handle_request(_REQUEST)
    decision = approvals.approve(response.approval_request.request_id, decided_by="test")
    final = orchestrator.execute_approved(response, decision)

    assert final.success is False
    assert final.intelligence_trace[1] == "Step 2/2: verification unavailable."
    assert project_state_store.get().phase == "Phase 96"


# --- H. Response/trace tests --------------------------------------------------------


def test_pending_response_says_not_executed() -> None:
    router, _ = _router(_update_phase_text("Phase 96"))
    orchestrator, *_ = _build_stack(_in_memory_session_factory(), router)

    response = orchestrator.handle_request(_REQUEST)

    assert response.success is False
    assert response.requires_confirmation is True
    assert len(response.intelligence_trace) == 1
    assert len(response.intelligence_trace[0]) <= 200


def test_approved_verified_response_is_grounded_in_real_values() -> None:
    router, _ = _router(_update_phase_text("Phase 96"))
    orchestrator, project_state_store, _, _, approvals, _ = _build_stack(
        _in_memory_session_factory(), router
    )

    response = orchestrator.handle_request(_REQUEST)
    decision = approvals.approve(response.approval_request.request_id, decided_by="test")
    final = orchestrator.execute_approved(response, decision)

    assert final.success is True
    assert "Phase 96" in final.message
    assert "Verification succeeded" in final.message
    assert len(final.intelligence_trace) == 2
    assert all(len(entry) <= 200 for entry in final.intelligence_trace)
    assert "verified" in final.intelligence_trace[1]


def test_response_documents_manual_recording() -> None:
    """The successful response honestly discloses ProjectState phase is
    manually recorded - never auto-detected from Git, a document, a
    commit, a test result, or the filesystem."""
    router, _ = _router(_update_phase_text("Phase 96"))
    orchestrator, _, _, _, approvals, _ = _build_stack(
        _in_memory_session_factory(), router
    )

    response = orchestrator.handle_request(_REQUEST)
    decision = approvals.approve(response.approval_request.request_id, decided_by="test")
    final = orchestrator.execute_approved(response, decision)

    assert "Manually recorded" in final.message
    assert "not auto-detected" in final.message


def test_declined_response_says_no_update_was_made() -> None:
    router, _ = _router(_update_phase_text("Phase 96"))
    orchestrator, project_state_store, _, _, approvals, _ = _build_stack(
        _in_memory_session_factory(), router
    )

    response = orchestrator.handle_request(_REQUEST)
    decision = approvals.decline(response.approval_request.request_id, decided_by="test")
    final = orchestrator.execute_approved(response, decision)

    assert final.success is False
    assert project_state_store.get() is None


def test_no_raw_dictionaries_in_intelligence_trace() -> None:
    router, _ = _router(_update_phase_text("Phase 96"))
    orchestrator, _, _, _, approvals, _ = _build_stack(
        _in_memory_session_factory(), router
    )

    response = orchestrator.handle_request(_REQUEST)
    decision = approvals.approve(response.approval_request.request_id, decided_by="test")
    final = orchestrator.execute_approved(response, decision)

    for entry in final.intelligence_trace:
        assert "{" not in entry
        assert "tool_input" not in entry


def test_no_second_ai_call_after_execution() -> None:
    router, provider = _router(_update_phase_text("Phase 96"))
    orchestrator, _, _, _, approvals, _ = _build_stack(
        _in_memory_session_factory(), router
    )

    response = orchestrator.handle_request(_REQUEST)
    assert len(provider.received_requests) == 1
    decision = approvals.approve(response.approval_request.request_id, decided_by="test")
    orchestrator.execute_approved(response, decision)

    assert len(provider.received_requests) == 1


# --- I. Routing/regression tests -----------------------------------------------------


def test_ask_jarvis_advisory_remains_unaffected_by_update_phase_addition() -> None:
    router, _ = _router(_update_phase_text("x"))
    orchestrator, *_ = _build_stack(_in_memory_session_factory(), router)

    response = orchestrator.handle_request("ask jarvis: what is my focus")

    assert response.success is False
    assert "AI reasoning is not enabled" in response.message


def test_existing_deterministic_command_remains_unaffected() -> None:
    router, _ = _router(_update_phase_text("x"))
    orchestrator, *_ = _build_stack(_in_memory_session_factory(), router)

    response = orchestrator.handle_request("show jarvis project state")

    assert response.success is True
    assert "Jarvis Project State" in response.message


def test_deterministic_update_project_state_phase_field_remains_unaffected() -> None:
    """Deterministic "update jarvis project state: phase=<value>" still
    runs through the plain, single-step YELLOW path - never the
    AI-facing two-step workflow."""
    router, _ = _router(_update_phase_text("Phase 96"))
    orchestrator, project_state_store, *_ = _build_stack(
        _in_memory_session_factory(), router
    )

    response = orchestrator.handle_request(
        "update jarvis project state: phase=Phase 95 deterministic"
    )

    assert response.requires_confirmation is True
    assert response.tool_name == "project_state_update"
    assert project_state_store.get() is None


# --- J. Structural tests --------------------------------------------------------------


def test_planning_module_never_calls_project_state_store_update_directly() -> None:
    import intelligence.planning as module

    source = inspect.getsource(module)
    assert "ProjectStateStore" not in source
    assert ".update(" not in source


def test_orchestrator_update_phase_response_translator_never_bypasses_workflow_engine() -> (
    None
):
    from core.orchestrator import JarvisOrchestrator

    source = inspect.getsource(
        JarvisOrchestrator._project_state_update_phase_workflow_result_to_response
    )
    assert "self._executor.execute(" not in source
    assert "ProjectStateStore" not in source


def test_no_direct_tool_run_or_store_mutation_was_introduced_for_update_phase() -> None:
    from core.orchestrator import JarvisOrchestrator

    translator_source = inspect.getsource(
        JarvisOrchestrator._project_state_update_phase_workflow_result_to_response
    )
    dispatcher_source = inspect.getsource(
        JarvisOrchestrator._translate_verified_workflow_result
    )
    for source in (translator_source, dispatcher_source):
        assert ".run(" not in source
        assert "ProjectStateStore(" not in source


# --- K. Grounding refusal zero-side-effect tests ---------------------------------


def test_ungrounded_update_phase_value_creates_no_approval_and_no_write() -> None:
    router, provider = _router(_update_phase_text("an entirely fabricated value"))
    orchestrator, project_state_store, _, _, approvals, _ = _build_stack(
        _in_memory_session_factory(), router
    )

    response = orchestrator.handle_request(_REQUEST)

    assert response.success is False
    assert response.requires_confirmation is False
    assert response.approval_request is None
    assert approvals.list_pending() == []
    assert project_state_store.get() is None
    assert len(provider.received_requests) == 1


def test_negated_update_phase_request_creates_no_approval_and_no_write() -> None:
    router, _ = _router(_update_phase_text("Phase 96"))
    orchestrator, project_state_store, _, _, approvals, _ = _build_stack(
        _in_memory_session_factory(), router
    )

    response = orchestrator.handle_request(
        "ask jarvis to: do not update my project phase to Phase 96"
    )

    assert response.success is False
    assert response.requires_confirmation is False
    assert approvals.list_pending() == []
    assert project_state_store.get() is None


def test_ungrounded_update_phase_never_reaches_workflow_engine() -> None:
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


def test_ungrounded_update_phase_response_message_never_leaks_the_candidate_value() -> (
    None
):
    router, _ = _router(_update_phase_text("an entirely fabricated value"))
    orchestrator, *_ = _build_stack(_in_memory_session_factory(), router)

    response = orchestrator.handle_request(_REQUEST)

    assert "an entirely fabricated value" not in response.message
    assert response.plan is not None


def test_capability_mismatch_for_update_phase_executes_neither_tool() -> None:
    """A request that uniquely grounds project_state_show, while the
    model instead selects project_state_update_phase, is refused as
    selected_capability_not_unique_match - neither tool executes, and
    the phase-update workflow is never even attempted."""
    router, _ = _router(_update_phase_text("an entirely fabricated phase"))
    orchestrator, project_state_store, _, _, approvals, _ = _build_stack(
        _in_memory_session_factory(), router
    )

    response = orchestrator.handle_request("ask jarvis to: show my project state")

    assert response.success is False
    assert response.tool_result is None
    assert response.requires_confirmation is False
    assert approvals.list_pending() == []
    assert project_state_store.get() is None


# --- L. Duplicate-execution and argument-immutability tests -----------------------


def test_duplicate_resume_does_not_duplicate_the_write() -> None:
    router, _ = _router(_update_phase_text("Phase 96"))
    orchestrator, project_state_store, _, _, approvals, _ = _build_stack(
        _in_memory_session_factory(), router
    )

    response = orchestrator.handle_request(_REQUEST)
    decision = approvals.approve(response.approval_request.request_id, decided_by="test")
    first = orchestrator.execute_approved(response, decision)

    assert first.success is True
    assert project_state_store.get().phase == "Phase 96"

    second = orchestrator.execute_approved(response, decision)

    assert project_state_store.get().phase == "Phase 96"
    assert second.tool_result is None


def test_approved_arguments_are_immutable_between_approval_and_execution() -> None:
    router, provider = _router(_update_phase_text("Phase 96"))
    orchestrator, project_state_store, _, _, approvals, _ = _build_stack(
        _in_memory_session_factory(), router
    )

    response = orchestrator.handle_request(_REQUEST)
    decision = approvals.approve(response.approval_request.request_id, decided_by="test")

    provider._text = _update_phase_text("a completely different value")  # type: ignore[attr-defined]

    final = orchestrator.execute_approved(response, decision)

    assert final.success is True
    assert project_state_store.get().phase == "Phase 96"
    assert "a completely different value" not in final.message


# --- M. Coexistence of all four trusted verified workflows ------------------------


def test_update_focus_and_update_phase_workflows_coexist_without_dispatch_ambiguity() -> (
    None
):
    """A single real orchestrator instance, wired with the shared
    project_state_update/project_state_verify tools, correctly
    dispatches a focus-update request and a phase-update request to
    their own distinct response translators - proving the Phase 96
    disambiguation fix (comparing the write step's own fixed "field"
    argument against trusted catalog data) genuinely keeps the two
    capabilities from being confused with one another, even though
    both share one identical write/verify tool-name pair."""
    session_factory = _in_memory_session_factory()
    memory = MemoryManager(EpisodicMemoryStore(session_factory))
    project_state_store = ProjectStateStore(session_factory)
    context_assembler = ContextAssembler(
        memory_manager=memory, project_state_store=project_state_store
    )
    security = SecurityManager()
    registry = ToolRegistry()
    registry.register_tool(ProjectStateShowTool(project_state_store))
    registry.register_tool(ProjectStateUpdateTool(project_state_store))
    registry.register_tool(ProjectStateVerifyTool(project_state_store))
    logger = _RecordingLogger()
    executor = ToolExecutor(
        registry=registry, security_manager=security, logger=logger  # type: ignore[arg-type]
    )
    approvals = ApprovalManager(pending_store=None)
    workflow_engine = WorkflowEngine(
        executor=executor, approvals=approvals, logger=logger  # type: ignore[arg-type]
    )

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
    assert project_state_store.get().focus == "coexistence check"
    assert project_state_store.get().phase is None

    phase_router, _ = _router(_update_phase_text("Phase 96"))
    orchestrator._tool_selection_router = phase_router  # type: ignore[attr-defined]
    phase_response = orchestrator.handle_request(_REQUEST)
    phase_decision = approvals.approve(
        phase_response.approval_request.request_id, decided_by="test"
    )
    phase_final = orchestrator.execute_approved(phase_response, phase_decision)

    assert phase_final.success is True
    assert project_state_store.get().phase == "Phase 96"
    assert project_state_store.get().focus == "coexistence check"  # unaffected
    assert "coexistence check" not in phase_final.message
    assert "Phase 96" not in focus_final.message
