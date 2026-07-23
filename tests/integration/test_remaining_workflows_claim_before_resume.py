"""
test_remaining_workflows_claim_before_resume.py

Smoke tests proving JarvisOrchestrator.execute_approved()'s claim-
before-resume gate and terminal CONSUMED transition (Approval-to-Resume
Handoff Interlock, Batch 2 - docs/phase_98_approval_handoff_plan.md)
apply identically to the three TWO_STEP_WORKFLOW capabilities not
already covered exhaustively by
tests/integration/test_orchestrator_claim_before_resume.py's own
PROJECT_STATE_UPDATE_PHASE tests: PROJECT_STATE_UPDATE_FOCUS,
SCHEDULE_ENABLE, SCHEDULE_DISABLE.

The gate itself (core.orchestrator.JarvisOrchestrator.execute_approved())
has no capability-specific branch - it triggers purely on whether
_paused_workflow_id_for() resolves a workflow_id at all, which is true
for every TWO_STEP_WORKFLOW capability alike. These tests exist to prove
that claim, in practice, for the three remaining real capabilities -
not to re-prove every terminal-outcome permutation already covered for
PROJECT_STATE_UPDATE_PHASE.

Run with:
    pytest tests/integration/test_remaining_workflows_claim_before_resume.py
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


def _session_factory():
    from sqlalchemy import create_engine

    engine = create_engine("sqlite:///:memory:")
    initialize_database(engine)
    return create_session_factory(engine)


def _build_orchestrator(session_factory, registry: ToolRegistry, router: AIRouter):
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
    paused_store = PausedWorkflowStore(session_factory)
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
    return orchestrator, approvals, pending_store


def _approve_and_execute(orchestrator, approvals, request_text: str):
    response = orchestrator.handle_request(request_text)
    decision = approvals.approve(response.approval_request.request_id, decided_by="test")
    final = orchestrator.execute_approved(response, decision)
    return final, decision


def test_project_state_update_focus_claims_before_resume() -> None:
    session_factory = _session_factory()
    project_state_store = ProjectStateStore(session_factory)
    registry = ToolRegistry()
    registry.register_tool(ProjectStateShowTool(project_state_store))
    registry.register_tool(ProjectStateUpdateTool(project_state_store))
    registry.register_tool(ProjectStateVerifyTool(project_state_store))

    router = _router(
        json.dumps(
            {
                "decision": "execute",
                "capability_id": "project_state_update_focus",
                "arguments": {"value": "batch 2 verification"},
            }
        )
    )
    orchestrator, approvals, pending_store = _build_orchestrator(
        session_factory, registry, router
    )

    final, decision = _approve_and_execute(
        orchestrator, approvals, "ask jarvis to: update my project focus to batch 2 verification"
    )

    assert final.success is True
    assert (
        pending_store.get_handoff_status(decision.request_id)
        == PendingApprovalHandoffStatus.CONSUMED
    )
    assert approvals.claim_for_resume(decision.request_id) is False


def test_schedule_enable_claims_before_resume() -> None:
    session_factory = _session_factory()
    schedule_store = ScheduleStore(session_factory)
    schedule = schedule_store.create(query="test query", time_of_day="09:00")

    registry = ToolRegistry()
    registry.register_tool(ScheduleListTool(schedule_store))
    registry.register_tool(ScheduleEnableTool(schedule_store))
    registry.register_tool(ScheduleVerifyEnabledStateTool(schedule_store))

    router = _router(
        json.dumps(
            {
                "decision": "execute",
                "capability_id": "schedule_enable",
                "arguments": {"schedule_id": schedule.id},
            }
        )
    )
    orchestrator, approvals, pending_store = _build_orchestrator(
        session_factory, registry, router
    )

    final, decision = _approve_and_execute(
        orchestrator, approvals, f"ask jarvis to: enable schedule {schedule.id}"
    )

    assert final.success is True
    assert (
        pending_store.get_handoff_status(decision.request_id)
        == PendingApprovalHandoffStatus.CONSUMED
    )
    assert approvals.claim_for_resume(decision.request_id) is False


def test_schedule_disable_claims_before_resume() -> None:
    session_factory = _session_factory()
    schedule_store = ScheduleStore(session_factory)
    schedule = schedule_store.create(query="test query", time_of_day="09:00")

    registry = ToolRegistry()
    registry.register_tool(ScheduleListTool(schedule_store))
    registry.register_tool(ScheduleDisableTool(schedule_store))
    registry.register_tool(ScheduleVerifyEnabledStateTool(schedule_store))

    router = _router(
        json.dumps(
            {
                "decision": "execute",
                "capability_id": "schedule_disable",
                "arguments": {"schedule_id": schedule.id},
            }
        )
    )
    orchestrator, approvals, pending_store = _build_orchestrator(
        session_factory, registry, router
    )

    final, decision = _approve_and_execute(
        orchestrator, approvals, f"ask jarvis to: disable schedule {schedule.id}"
    )

    assert final.success is True
    assert (
        pending_store.get_handoff_status(decision.request_id)
        == PendingApprovalHandoffStatus.CONSUMED
    )
    assert approvals.claim_for_resume(decision.request_id) is False
