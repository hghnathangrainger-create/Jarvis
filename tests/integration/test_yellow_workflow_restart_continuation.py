"""
test_yellow_workflow_restart_continuation.py

Real, on-disk-database restart-continuation tests for every current
YELLOW workflow (Approval-to-Resume Handoff Interlock, Batch 3 -
docs/phase_98_approval_handoff_plan.md): PROJECT_STATE_UPDATE_FOCUS,
PROJECT_STATE_UPDATE_PHASE, SCHEDULE_ENABLE, SCHEDULE_DISABLE.

This is the end-to-end proof that the original system-wide bug (an
approved-but-not-yet-resumed workflow silently lost on a crash between
approval and resume) is now fixed: for each capability, "process one"
creates a real pending approval and paused workflow and approves it
(APPROVED_UNCONSUMED), then every in-memory object is discarded
(simulating a crash before ordinary resume). "Process two" is a wholly
separate stack bound only to the same real, temporary SQLite file on
disk (never :memory:, never in-memory object reuse) that reloads
durable state and calls main.continue_approved_unconsumed_workflows() -
the real, production startup-continuation function - directly.

Uses real Planner, SecurityManager, CommandRouter, ToolRegistry,
ToolExecutor, ApprovalManager, WorkflowEngine, MemoryManager,
ProjectStateStore/ScheduleStore, the real production tools, real
ContextAssembler, and a real AIRouter wired to a fake, in-memory
AIProvider - no live Claude API call is ever made (Anthropic acceptance
remains postponed pending API credits; handoff safety is proven through
deterministic and fake-provider tests only).

Run with:
    pytest tests/integration/test_yellow_workflow_restart_continuation.py
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")

from ai.prompt_builder import PromptBuilder  # noqa: E402
from ai.providers.base import AIProvider, AIRequest, AIResponse  # noqa: E402
from ai.response_validator import ResponseValidator  # noqa: E402
from ai.router import AIRouter  # noqa: E402
from approval.approval_manager import ApprovalManager  # noqa: E402
from approval.approval_models import PendingApprovalHandoffStatus  # noqa: E402
from approval.pending_approval_store import PendingApprovalStore  # noqa: E402
from config.settings import Settings  # noqa: E402
from core.command_router import CommandRouter  # noqa: E402
from core.orchestrator import JarvisOrchestrator  # noqa: E402
from intelligence.context import ContextAssembler  # noqa: E402
from main import ContinuationSummary, continue_approved_unconsumed_workflows  # noqa: E402
from memory.episodic_memory import EpisodicMemoryStore  # noqa: E402
from memory.memory_manager import MemoryManager  # noqa: E402
from planner.planner import Planner  # noqa: E402
from project_state.project_state_store import ProjectStateStore  # noqa: E402
from scheduling.schedule_store import ScheduleStore  # noqa: E402
from security.security_manager import SecurityManager  # noqa: E402
from storage.database import create_session_factory, initialize_database  # noqa: E402
from tools.builtin import (  # noqa: E402
    ProjectStateShowTool,
    ProjectStateUpdateTool,
    ProjectStateVerifyTool,
    ScheduleDisableTool,
    ScheduleEnableTool,
    ScheduleListTool,
    ScheduleVerifyEnabledStateTool,
)
from tools.executor import ToolExecutor  # noqa: E402
from tools.registry import ToolRegistry  # noqa: E402
from workflow.engine import WorkflowEngine  # noqa: E402
from workflow.paused_workflow_store import PausedWorkflowStore  # noqa: E402
from workflow.workflow_history_store import WorkflowHistoryStore  # noqa: E402


class _RecordingLogger:
    def emit(self, **kwargs: object) -> str:
        return "1"


class _FakeAIProvider(AIProvider):
    def __init__(self, text: str) -> None:
        self._text = text

    @property
    def name(self) -> str:
        return "fake"

    def generate(self, request: AIRequest) -> AIResponse:
        return AIResponse(text=self._text, model="fake-model", provider="fake")

    def is_available(self) -> bool:
        return True


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


def _router(text: str) -> AIRouter:
    return AIRouter(
        provider=_FakeAIProvider(text),
        prompt_builder=PromptBuilder(),
        validator=ResponseValidator(),
        logger=_RecordingLogger(),  # type: ignore[arg-type]
        settings=_settings(),
    )


def _session_factory_for(db_path: Path):
    from sqlalchemy import create_engine

    engine = create_engine(f"sqlite:///{db_path}")
    initialize_database(engine)
    return create_session_factory(engine)


def _build_full_stack(
    session_factory, registry: ToolRegistry, router: AIRouter, *, reload_paused: bool = True
):
    """Builds one full, independent, durable-persistence stack bound to
    the given session_factory - mirroring main.build_orchestrator()'s
    own composition order (pending approvals reloaded before paused
    workflows).

    reload_paused=False is used only by the multi-workflow ordering test
    to construct a *second*, independent approved-unconsumed workflow
    without first reconstructing an already-durable, unrelated one into
    this same instance's memory - Phase 15's own one-paused-workflow-at-
    a-time model would otherwise block run() for the second capability,
    exactly as it correctly would for two genuinely concurrent live
    workflows in one real process.
    """
    memory = MemoryManager(EpisodicMemoryStore(session_factory))
    project_state_store = ProjectStateStore(session_factory)
    context_assembler = ContextAssembler(
        memory_manager=memory, project_state_store=project_state_store
    )
    security = SecurityManager()
    logger = _RecordingLogger()
    executor = ToolExecutor(
        registry=registry, security_manager=security, logger=logger  # type: ignore[arg-type]
    )
    pending_store = PendingApprovalStore(session_factory)
    approvals = ApprovalManager(pending_store=pending_store)
    approvals.reload_pending(registry=registry, security_manager=security)

    paused_store = PausedWorkflowStore(session_factory)
    workflow_history = WorkflowHistoryStore(session_factory)
    workflow_engine = WorkflowEngine(
        executor=executor,
        approvals=approvals,
        logger=logger,  # type: ignore[arg-type]
        paused_store=paused_store,
        history=workflow_history,
    )
    if reload_paused:
        workflow_engine.reload_paused(registry=registry, security_manager=security)

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
    return orchestrator, pending_store, workflow_history


def _project_state_registry(project_state_store: ProjectStateStore) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register_tool(ProjectStateShowTool(project_state_store))
    registry.register_tool(ProjectStateUpdateTool(project_state_store))
    registry.register_tool(ProjectStateVerifyTool(project_state_store))
    return registry


def _schedule_registry(schedule_store: ScheduleStore) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register_tool(ScheduleListTool(schedule_store))
    registry.register_tool(ScheduleEnableTool(schedule_store))
    registry.register_tool(ScheduleDisableTool(schedule_store))
    registry.register_tool(ScheduleVerifyEnabledStateTool(schedule_store))
    return registry


# --- PROJECT_STATE_UPDATE_PHASE ---------------------------------------------


def test_phase_update_restart_continuation(tmp_path: Path) -> None:
    db_path = tmp_path / "phase_restart.db"
    session_factory = _session_factory_for(db_path)
    project_state_store = ProjectStateStore(session_factory)

    router = _router(
        json.dumps(
            {
                "decision": "execute",
                "capability_id": "project_state_update_phase",
                "arguments": {"value": "Phase 98 Batch 3"},
            }
        )
    )
    orchestrator_one, pending_store, _ = _build_full_stack(
        session_factory, _project_state_registry(project_state_store), router
    )
    response = orchestrator_one.handle_request(
        "ask jarvis to: update my project phase to Phase 98 Batch 3"
    )
    request_id = response.approval_request.request_id
    decision = orchestrator_one.approvals.approve(request_id, decided_by="nathan")
    assert (
        pending_store.get_handoff_status(request_id)
        == PendingApprovalHandoffStatus.APPROVED_UNCONSUMED
    )
    del orchestrator_one, response, decision  # simulate crash before ordinary resume

    assert project_state_store.get() is None  # nothing executed yet

    # --- "process two": fresh stack, same on-disk database file. --------
    orchestrator_two, pending_store_two, _ = _build_full_stack(
        session_factory, _project_state_registry(project_state_store), router
    )
    summary = continue_approved_unconsumed_workflows(orchestrator_two)

    assert summary == ContinuationSummary(continued=1, interrupted=0, left_pending=0)
    assert project_state_store.get().phase == "Phase 98 Batch 3"
    assert (
        pending_store_two.get_handoff_status(request_id)
        == PendingApprovalHandoffStatus.CONSUMED
    )
    # No new approval, no duplicate execution.
    assert orchestrator_two.approvals.claim_for_resume(request_id) is False


# --- PROJECT_STATE_UPDATE_FOCUS ---------------------------------------------


def test_focus_update_restart_continuation(tmp_path: Path) -> None:
    db_path = tmp_path / "focus_restart.db"
    session_factory = _session_factory_for(db_path)
    project_state_store = ProjectStateStore(session_factory)

    router = _router(
        json.dumps(
            {
                "decision": "execute",
                "capability_id": "project_state_update_focus",
                "arguments": {"value": "batch 3 verification"},
            }
        )
    )
    orchestrator_one, pending_store, _ = _build_full_stack(
        session_factory, _project_state_registry(project_state_store), router
    )
    response = orchestrator_one.handle_request(
        "ask jarvis to: update my project focus to batch 3 verification"
    )
    request_id = response.approval_request.request_id
    orchestrator_one.approvals.approve(request_id, decided_by="nathan")
    del orchestrator_one, response

    orchestrator_two, pending_store_two, _ = _build_full_stack(
        session_factory, _project_state_registry(project_state_store), router
    )
    summary = continue_approved_unconsumed_workflows(orchestrator_two)

    assert summary == ContinuationSummary(continued=1, interrupted=0, left_pending=0)
    assert project_state_store.get().focus == "batch 3 verification"
    assert (
        pending_store_two.get_handoff_status(request_id)
        == PendingApprovalHandoffStatus.CONSUMED
    )
    assert orchestrator_two.approvals.claim_for_resume(request_id) is False


# --- SCHEDULE_ENABLE ----------------------------------------------------------


def test_schedule_enable_restart_continuation(tmp_path: Path) -> None:
    db_path = tmp_path / "schedule_enable_restart.db"
    session_factory = _session_factory_for(db_path)
    schedule_store = ScheduleStore(session_factory)
    schedule = schedule_store.create(query="test query", time_of_day="09:00")

    router = _router(
        json.dumps(
            {
                "decision": "execute",
                "capability_id": "schedule_enable",
                "arguments": {"schedule_id": schedule.id},
            }
        )
    )
    orchestrator_one, pending_store, _ = _build_full_stack(
        session_factory, _schedule_registry(schedule_store), router
    )
    response = orchestrator_one.handle_request(
        f"ask jarvis to: enable schedule {schedule.id}"
    )
    request_id = response.approval_request.request_id
    orchestrator_one.approvals.approve(request_id, decided_by="nathan")
    del orchestrator_one, response

    orchestrator_two, pending_store_two, _ = _build_full_stack(
        session_factory, _schedule_registry(schedule_store), router
    )
    summary = continue_approved_unconsumed_workflows(orchestrator_two)

    assert summary == ContinuationSummary(continued=1, interrupted=0, left_pending=0)
    assert schedule_store.get(schedule.id).enabled is True
    assert (
        pending_store_two.get_handoff_status(request_id)
        == PendingApprovalHandoffStatus.CONSUMED
    )
    assert orchestrator_two.approvals.claim_for_resume(request_id) is False


# --- SCHEDULE_DISABLE ----------------------------------------------------------


def test_schedule_disable_restart_continuation(tmp_path: Path) -> None:
    db_path = tmp_path / "schedule_disable_restart.db"
    session_factory = _session_factory_for(db_path)
    schedule_store = ScheduleStore(session_factory)
    schedule = schedule_store.create(query="test query", time_of_day="09:00")
    assert schedule_store.get(schedule.id).enabled is True

    router = _router(
        json.dumps(
            {
                "decision": "execute",
                "capability_id": "schedule_disable",
                "arguments": {"schedule_id": schedule.id},
            }
        )
    )
    orchestrator_one, pending_store, _ = _build_full_stack(
        session_factory, _schedule_registry(schedule_store), router
    )
    response = orchestrator_one.handle_request(
        f"ask jarvis to: disable schedule {schedule.id}"
    )
    request_id = response.approval_request.request_id
    orchestrator_one.approvals.approve(request_id, decided_by="nathan")
    del orchestrator_one, response

    orchestrator_two, pending_store_two, _ = _build_full_stack(
        session_factory, _schedule_registry(schedule_store), router
    )
    summary = continue_approved_unconsumed_workflows(orchestrator_two)

    assert summary == ContinuationSummary(continued=1, interrupted=0, left_pending=0)
    assert schedule_store.get(schedule.id).enabled is False
    assert (
        pending_store_two.get_handoff_status(request_id)
        == PendingApprovalHandoffStatus.CONSUMED
    )
    assert orchestrator_two.approvals.claim_for_resume(request_id) is False


# --- multiple approved-unconsumed workflows: deterministic ordering ----------


def test_multiple_approved_unconsumed_workflows_continue_independently(
    tmp_path: Path,
) -> None:
    """Two independent PROJECT_STATE_UPDATE_PHASE-shaped approvals appear
    only one at a time in practice (Phase 15's own one-paused-workflow
    constraint), so this proves independence across capabilities
    instead: a phase-update and a schedule-enable, both left
    APPROVED_UNCONSUMED, are each claimed and consumed independently, in
    deterministic (oldest-first) order, with neither affecting the
    other's own inputs or identity."""
    db_path = tmp_path / "multi_restart.db"
    session_factory = _session_factory_for(db_path)
    project_state_store = ProjectStateStore(session_factory)
    schedule_store = ScheduleStore(session_factory)
    schedule = schedule_store.create(query="test query", time_of_day="09:00")

    registry = ToolRegistry()
    for tool in (
        ProjectStateShowTool(project_state_store),
        ProjectStateUpdateTool(project_state_store),
        ProjectStateVerifyTool(project_state_store),
        ScheduleListTool(schedule_store),
        ScheduleEnableTool(schedule_store),
        ScheduleVerifyEnabledStateTool(schedule_store),
    ):
        registry.register_tool(tool)

    router_phase = _router(
        json.dumps(
            {
                "decision": "execute",
                "capability_id": "project_state_update_phase",
                "arguments": {"value": "Phase 98 Batch 3 multi"},
            }
        )
    )
    orchestrator_one, pending_store, _ = _build_full_stack(
        session_factory, registry, router_phase
    )
    response_phase = orchestrator_one.handle_request(
        "ask jarvis to: update my project phase to Phase 98 Batch 3 multi"
    )
    phase_request_id = response_phase.approval_request.request_id
    orchestrator_one.approvals.approve(phase_request_id, decided_by="nathan")
    # Discarded, matching "process one" vanishing before ordinary resume.
    # The second approval is created via reload_paused=False (a fresh
    # instance that never reconstructs the phase workflow's own already-
    # durable row into memory) - otherwise Phase 15's own genuine
    # one-paused-workflow-at-a-time model would correctly block run()
    # here too, exactly as it would for two real concurrent live
    # workflows in one process.
    del orchestrator_one, response_phase

    router_schedule = _router(
        json.dumps(
            {
                "decision": "execute",
                "capability_id": "schedule_enable",
                "arguments": {"schedule_id": schedule.id},
            }
        )
    )
    orchestrator_mid, _, _ = _build_full_stack(
        session_factory, registry, router_schedule, reload_paused=False
    )
    response_schedule = orchestrator_mid.handle_request(
        f"ask jarvis to: enable schedule {schedule.id}"
    )
    schedule_request_id = response_schedule.approval_request.request_id
    orchestrator_mid.approvals.approve(schedule_request_id, decided_by="nathan")
    del orchestrator_mid, response_schedule

    # Deterministic ordering: list_approved_unconsumed() is oldest-first.
    orchestrator_two, pending_store_two, _ = _build_full_stack(
        session_factory, registry, router_phase
    )
    ordered = [
        r.request_id for r in orchestrator_two.approvals.list_approved_unconsumed()
    ]
    assert ordered == [phase_request_id, schedule_request_id]

    summary = continue_approved_unconsumed_workflows(orchestrator_two)

    assert summary == ContinuationSummary(continued=2, interrupted=0, left_pending=0)
    assert project_state_store.get().phase == "Phase 98 Batch 3 multi"
    assert schedule_store.get(schedule.id).enabled is True
    assert (
        pending_store_two.get_handoff_status(phase_request_id)
        == PendingApprovalHandoffStatus.CONSUMED
    )
    assert (
        pending_store_two.get_handoff_status(schedule_request_id)
        == PendingApprovalHandoffStatus.CONSUMED
    )
