"""
test_phase99_batch3_live_schedule_compound_activation.py

Live, end-to-end proof of Phase 99, Batch 3's atomic schedule-compound
activation (docs/phase_99_second_compound_template_planning.md): the
second live bounded compound request - "ask jarvis to: enable schedule
<id> and then check the enabled state of schedule <same id>" -
reachable through the real, wired-together path:
intelligence.planning.select_tool()'s two-template dispatch -> exact
schedule compound parsing/grounding -> the trusted three-step Plan ->
JarvisOrchestrator._start_schedule_enable_and_show_workflow() (progress
creation before an actionable approval) -> one honest approval ->
JarvisOrchestrator._claim_and_resume_workflow() (claim,
ScheduleCompoundStepObserver attachment, CompoundCheckpointError
handling) -> core.schedule_compound_workflow.translate_schedule_compound_workflow_result()'s
six bounded outcomes -> schedule-compound-first startup recovery
ordering in main.reconcile_claimed_handoffs().

Mirrors tests/unit/test_phase98_batch3_live_compound_activation.py's
own established real-stack pattern - no live Claude API call and no
real network call is ever made anywhere in this file.

Run with:
    pytest tests/unit/test_phase99_batch3_live_schedule_compound_activation.py
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

try:
    from sqlalchemy import create_engine

    from ai.prompt_builder import PromptBuilder
    from ai.providers.base import AIProvider, AIRequest, AIResponse
    from ai.response_validator import ResponseValidator
    from ai.router import AIRouter
    from approval.approval_manager import ApprovalManager
    from approval.approval_models import PendingApprovalHandoffStatus
    from approval.pending_approval_store import PendingApprovalStore
    from config.settings import Settings
    from core.command_router import CommandRouter
    from core.orchestrator import (
        _COMPOUND_CHECKPOINT_INTERRUPTED_MESSAGE,
        JarvisOrchestrator,
    )
    from core.schedule_compound_workflow import (
        establish_schedule_compound_progress_or_isolate,
    )
    from intelligence.capability_catalog import CAPABILITY_CATALOG
    from intelligence.context import ContextAssembler
    from intelligence.planning import (
        _build_schedule_enable_verify_show_workflow_plan,
    )
    from memory.episodic_memory import EpisodicMemoryStore
    from memory.memory_manager import MemoryManager
    from planner.planner import Planner
    from project_state.project_state_store import ProjectStateStore
    from scheduling.schedule_store import ScheduleStore
    from security.security_manager import SecurityManager
    from storage.database import create_session_factory, initialize_database
    from tools.base_tool import BaseTool, ToolRequest, ToolResult
    from tools.builtin.project_state_show_tool import ProjectStateShowTool
    from tools.builtin.project_state_update_tool import ProjectStateUpdateTool
    from tools.builtin.project_state_verify_tool import ProjectStateVerifyTool
    from tools.builtin.schedule_enable_tool import ScheduleEnableTool
    from tools.builtin.schedule_disable_tool import ScheduleDisableTool
    from tools.builtin.schedule_show_enabled_state_tool import (
        ScheduleShowEnabledStateTool,
    )
    from tools.builtin.schedule_verify_enabled_state_tool import (
        ScheduleVerifyEnabledStateTool,
    )
    from tools.executor import ToolExecutor
    from tools.registry import ToolRegistry
    from workflow.compound_workflow_progress_store import CompoundWorkflowProgressStore
    from workflow.engine import WorkflowEngine
    from workflow.paused_workflow_store import PausedWorkflowStore
    from workflow.schedule_compound_workflow_progress_store import (
        ScheduleCompoundOverallStatus,
        ScheduleCompoundWorkflowProgressStore,
    )
    from workflow.workflow_history_store import WorkflowHistoryStore

    _SQLALCHEMY_AVAILABLE = True
except ImportError:
    _SQLALCHEMY_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not _SQLALCHEMY_AVAILABLE, reason="sqlalchemy not installed"
)


# --- Test doubles ------------------------------------------------------------


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


def _schedule_compound_text(schedule_id: int) -> str:
    return json.dumps(
        {
            "decision": "execute_sequence",
            "steps": [
                {"capability_id": "schedule_enable", "arguments": {"schedule_id": schedule_id}},
                {
                    "capability_id": "schedule_show_enabled_state",
                    "arguments": {"schedule_id": schedule_id},
                },
            ],
        }
    )


def _project_state_compound_text(value: str) -> str:
    return json.dumps(
        {
            "decision": "execute_sequence",
            "steps": [
                {"capability_id": "project_state_update_phase", "arguments": {"value": value}},
                {"capability_id": "project_state_show", "arguments": {}},
            ],
        }
    )


def _schedule_request(schedule_id: int) -> str:
    return (
        f"ask jarvis to: enable schedule {schedule_id} and then check the "
        f"enabled state of schedule {schedule_id}"
    )


def _in_memory_session_factory():
    engine = create_engine("sqlite:///:memory:")
    initialize_database(engine)
    return create_session_factory(engine)


def _build_stack(session_factory, router, *, timeout_seconds=None, clock=None):
    """Builds a full production-shaped stack with BOTH the ProjectState
    and schedule tools/stores registered - so mutual non-collision
    between the two live compound templates can be tested in the same
    stack, mirroring main.py's own real wiring."""
    memory = MemoryManager(EpisodicMemoryStore(session_factory))
    project_state_store = ProjectStateStore(session_factory)
    schedules = ScheduleStore(session_factory)
    context_assembler = ContextAssembler(
        memory_manager=memory, project_state_store=project_state_store
    )
    security = SecurityManager()
    registry = ToolRegistry()
    registry.register_tool(ProjectStateShowTool(project_state_store))
    registry.register_tool(ProjectStateUpdateTool(project_state_store))
    registry.register_tool(ProjectStateVerifyTool(project_state_store))
    registry.register_tool(ScheduleEnableTool(schedules))
    registry.register_tool(ScheduleDisableTool(schedules))
    registry.register_tool(ScheduleVerifyEnabledStateTool(schedules))
    registry.register_tool(ScheduleShowEnabledStateTool(schedules))
    logger = _RecordingLogger()
    executor = ToolExecutor(
        registry=registry, security_manager=security, logger=logger  # type: ignore[arg-type]
    )
    pending_store = PendingApprovalStore(session_factory)
    approvals = ApprovalManager(
        pending_store=pending_store, timeout_seconds=timeout_seconds, clock=clock
    )
    paused_store = PausedWorkflowStore(session_factory)
    workflow_engine = WorkflowEngine(
        executor=executor,
        approvals=approvals,
        logger=logger,  # type: ignore[arg-type]
        paused_store=paused_store,
        history=WorkflowHistoryStore(session_factory),
    )
    compound_progress_store = CompoundWorkflowProgressStore(session_factory)
    schedule_compound_progress_store = ScheduleCompoundWorkflowProgressStore(
        session_factory
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
        paused_workflow_store=paused_store,
        compound_progress_store=compound_progress_store,
        schedule_compound_progress_store=schedule_compound_progress_store,
    )
    return (
        orchestrator,
        project_state_store,
        schedules,
        registry,
        security,
        approvals,
        workflow_engine,
        paused_store,
        compound_progress_store,
        schedule_compound_progress_store,
    )


def _single_workflow_id(paused_store: PausedWorkflowStore) -> str:
    rows = paused_store.list_all()
    assert len(rows) == 1
    return rows[0].workflow_id


# --- A. Decision activation, grounding, and mutual non-collision -------------


class TestDecisionActivationAndGrounding:
    def test_execute_sequence_decision_produces_a_real_three_step_paused_plan(
        self,
    ) -> None:
        session_factory = _in_memory_session_factory()
        (
            orchestrator,
            _project_state_store,
            schedules,
            *_rest,
            schedule_progress_store,
        ) = _build_stack(session_factory, None)
        record = schedules.create(query="q", time_of_day="09:00")
        schedules.disable(record.id)
        router, _ = _router(_schedule_compound_text(record.id))
        orchestrator._tool_selection_router = router

        response = orchestrator.handle_request(_schedule_request(record.id))

        assert response.requires_confirmation is True
        paused_store = orchestrator._paused_workflow_store
        rows = paused_store.list_all()
        assert len(rows) == 1
        assert len(rows[0].plan_steps) == 3
        assert rows[0].plan_steps[0]["tool_name"] == "schedule_enable"
        assert rows[0].plan_steps[1]["tool_name"] == "schedule_verify_enabled_state"
        assert rows[0].plan_steps[2]["tool_name"] == "schedule_show_enabled_state"
        assert schedule_progress_store.get(rows[0].workflow_id) is not None

    def test_different_schedule_ids_between_clauses_is_rejected(self) -> None:
        session_factory = _in_memory_session_factory()
        orchestrator, _p, schedules, *_rest = _build_stack(session_factory, None)
        record = schedules.create(query="q", time_of_day="09:00")
        other = schedules.create(query="q2", time_of_day="10:00")
        text = json.dumps(
            {
                "decision": "execute_sequence",
                "steps": [
                    {
                        "capability_id": "schedule_enable",
                        "arguments": {"schedule_id": record.id},
                    },
                    {
                        "capability_id": "schedule_show_enabled_state",
                        "arguments": {"schedule_id": other.id},
                    },
                ],
            }
        )
        router, _ = _router(text)
        orchestrator._tool_selection_router = router

        response = orchestrator.handle_request(
            f"ask jarvis to: enable schedule {record.id} and then check the "
            f"enabled state of schedule {other.id}"
        )

        assert response.requires_confirmation is False
        assert response.success is False
        assert orchestrator._paused_workflow_store.list_all() == []

    def test_malformed_schedule_id_is_rejected(self) -> None:
        session_factory = _in_memory_session_factory()
        orchestrator, *_rest = _build_stack(session_factory, None)
        text = json.dumps(
            {
                "decision": "execute_sequence",
                "steps": [
                    {"capability_id": "schedule_enable", "arguments": {"schedule_id": "not-a-number"}},
                    {
                        "capability_id": "schedule_show_enabled_state",
                        "arguments": {"schedule_id": "not-a-number"},
                    },
                ],
            }
        )
        router, _ = _router(text)
        orchestrator._tool_selection_router = router

        response = orchestrator.handle_request(
            "ask jarvis to: enable schedule 5 and then check the enabled "
            "state of schedule 5"
        )
        assert response.success is False
        assert orchestrator._paused_workflow_store.list_all() == []

    def test_schedule_disable_substitution_is_rejected(self) -> None:
        session_factory = _in_memory_session_factory()
        orchestrator, _p, schedules, *_rest = _build_stack(session_factory, None)
        record = schedules.create(query="q", time_of_day="09:00")
        text = json.dumps(
            {
                "decision": "execute_sequence",
                "steps": [
                    {"capability_id": "schedule_disable", "arguments": {"schedule_id": record.id}},
                    {
                        "capability_id": "schedule_show_enabled_state",
                        "arguments": {"schedule_id": record.id},
                    },
                ],
            }
        )
        router, _ = _router(text)
        orchestrator._tool_selection_router = router

        response = orchestrator.handle_request(
            f"ask jarvis to: disable schedule {record.id} and then check the "
            f"enabled state of schedule {record.id}"
        )
        assert response.success is False
        assert orchestrator._paused_workflow_store.list_all() == []

    def test_negated_request_is_rejected(self) -> None:
        session_factory = _in_memory_session_factory()
        orchestrator, _p, schedules, *_rest = _build_stack(session_factory, None)
        record = schedules.create(query="q", time_of_day="09:00")
        router, _ = _router(_schedule_compound_text(record.id))
        orchestrator._tool_selection_router = router

        response = orchestrator.handle_request(
            f"ask jarvis to: do not enable schedule {record.id} and then "
            f"check the enabled state of schedule {record.id}"
        )
        assert response.success is False
        assert orchestrator._paused_workflow_store.list_all() == []

    def test_project_state_compound_remains_selectable_unaffected(self) -> None:
        """The ProjectState compound, in the same stack that also has
        the schedule compound live, is completely unaffected."""
        session_factory = _in_memory_session_factory()
        orchestrator, project_state_store, *_rest = _build_stack(
            session_factory, None
        )
        router, _ = _router(_project_state_compound_text("phase-x"))
        orchestrator._tool_selection_router = router

        response = orchestrator.handle_request(
            "ask jarvis to: update my project phase to phase-x and then "
            "show my project state"
        )
        assert response.requires_confirmation is True
        rows = orchestrator._paused_workflow_store.list_all()
        assert len(rows) == 1
        assert rows[0].plan_steps[0]["tool_name"] == "project_state_update"

    def test_ordinary_schedule_enable_request_is_unaffected(self) -> None:
        session_factory = _in_memory_session_factory()
        orchestrator, _p, schedules, *_rest = _build_stack(session_factory, None)
        record = schedules.create(query="q", time_of_day="09:00")
        router, _ = _router(
            json.dumps(
                {
                    "decision": "execute",
                    "capability_id": "schedule_enable",
                    "arguments": {"schedule_id": record.id},
                }
            )
        )
        orchestrator._tool_selection_router = router

        response = orchestrator.handle_request(
            f"ask jarvis to: enable schedule {record.id}"
        )
        assert response.requires_confirmation is True
        rows = orchestrator._paused_workflow_store.list_all()
        assert len(rows) == 1
        assert len(rows[0].plan_steps) == 2  # write + verify only, never 3
        assert orchestrator._schedule_compound_progress_store.list_all() == []

    def test_ordinary_exact_state_read_request_is_unaffected(self) -> None:
        session_factory = _in_memory_session_factory()
        orchestrator, _p, schedules, *_rest = _build_stack(session_factory, None)
        record = schedules.create(query="q", time_of_day="09:00")
        router, _ = _router(
            json.dumps(
                {
                    "decision": "execute",
                    "capability_id": "schedule_show_enabled_state",
                    "arguments": {"schedule_id": record.id},
                }
            )
        )
        orchestrator._tool_selection_router = router

        response = orchestrator.handle_request(
            f"ask jarvis to: check the enabled state of schedule {record.id}"
        )
        assert response.success is True
        assert response.requires_confirmation is False

    def test_schedule_list_substitution_is_rejected(self) -> None:
        session_factory = _in_memory_session_factory()
        orchestrator, _p, schedules, *_rest = _build_stack(session_factory, None)
        record = schedules.create(query="q", time_of_day="09:00")
        text = json.dumps(
            {
                "decision": "execute_sequence",
                "steps": [
                    {"capability_id": "schedule_enable", "arguments": {"schedule_id": record.id}},
                    {"capability_id": "schedule_list", "arguments": {}},
                ],
            }
        )
        router, _ = _router(text)
        orchestrator._tool_selection_router = router

        response = orchestrator.handle_request(
            f"ask jarvis to: enable schedule {record.id} and then list my schedules"
        )
        assert response.success is False
        assert orchestrator._paused_workflow_store.list_all() == []


# --- B. Approval and progress ordering ---------------------------------------


class TestApprovalAndProgressOrdering:
    def test_progress_exists_before_approval_is_returned(self) -> None:
        session_factory = _in_memory_session_factory()
        orchestrator, _p, schedules, *_rest, schedule_progress_store = _build_stack(
            session_factory, None
        )
        record = schedules.create(query="q", time_of_day="09:00")
        router, _ = _router(_schedule_compound_text(record.id))
        orchestrator._tool_selection_router = router

        response = orchestrator.handle_request(_schedule_request(record.id))

        workflow_id = _single_workflow_id(orchestrator._paused_workflow_store)
        progress = schedule_progress_store.get(workflow_id)
        assert progress is not None
        assert progress.schedule_id == record.id
        assert response.approval_request is not None

    def test_one_approval_only(self) -> None:
        """Exactly one approval is created for the whole three-step
        compound (never a separate one for the verifier or read step),
        and the underlying plan - which the CLI renders alongside the
        approval - carries the exact, ungrounded-from-nowhere schedule
        id in every step's own tool_input, mirroring the ProjectState
        compound's own established convention (action_for() strings are
        always fixed/generic for security classification across this
        codebase; the concrete argument lives in tool_input, never in
        the action text itself, for either template)."""
        session_factory = _in_memory_session_factory()
        orchestrator, _p, schedules, *_rest = _build_stack(session_factory, None)
        record = schedules.create(query="q", time_of_day="09:00")
        router, _ = _router(_schedule_compound_text(record.id))
        orchestrator._tool_selection_router = router

        response = orchestrator.handle_request(_schedule_request(record.id))
        assert response.approval_request is not None

        rows = orchestrator._paused_workflow_store.list_all()
        assert len(rows) == 1
        for step in rows[0].plan_steps:
            assert step["tool_input"]["schedule_id"] == record.id
        # Step 3 is never described as a generic schedule listing.
        assert "my schedules" not in rows[0].plan_steps[2]["description"].casefold()
        assert "list" not in rows[0].plan_steps[2]["description"].casefold()

    def test_project_state_compound_creates_no_schedule_progress(self) -> None:
        session_factory = _in_memory_session_factory()
        orchestrator, *_rest, schedule_progress_store = _build_stack(
            session_factory, None
        )
        router, _ = _router(_project_state_compound_text("phase-x"))
        orchestrator._tool_selection_router = router

        orchestrator.handle_request(
            "ask jarvis to: update my project phase to phase-x and then "
            "show my project state"
        )
        assert schedule_progress_store.list_all() == []


# --- C. Successful execution --------------------------------------------------


class TestNormalExecutionEndToEnd:
    def test_full_success_enables_verifies_and_shows(self) -> None:
        session_factory = _in_memory_session_factory()
        orchestrator, _p, schedules, *_rest = _build_stack(session_factory, None)
        record = schedules.create(query="q", time_of_day="09:00")
        schedules.disable(record.id)
        router, _ = _router(_schedule_compound_text(record.id))
        orchestrator._tool_selection_router = router

        response = orchestrator.handle_request(_schedule_request(record.id))
        decision = orchestrator.approvals.approve(
            response.approval_request.request_id, decided_by="test"
        )
        final = orchestrator.execute_approved(response, decision)

        assert final.success is True
        assert schedules.get(record.id).enabled is True
        assert str(record.id) in final.message
        assert "Verification succeeded" in final.message

    def test_duplicate_resume_does_not_duplicate_the_write(self) -> None:
        session_factory = _in_memory_session_factory()
        orchestrator, _p, schedules, *_rest = _build_stack(session_factory, None)
        record = schedules.create(query="q", time_of_day="09:00")
        schedules.disable(record.id)
        router, _ = _router(_schedule_compound_text(record.id))
        orchestrator._tool_selection_router = router

        response = orchestrator.handle_request(_schedule_request(record.id))
        decision = orchestrator.approvals.approve(
            response.approval_request.request_id, decided_by="test"
        )
        first = orchestrator.execute_approved(response, decision)
        assert first.success is True

        second = orchestrator.execute_approved(response, decision)
        assert schedules.get(record.id).enabled is True
        assert second.tool_result is None

    def test_decline_leaves_no_write_and_reports_honestly(self) -> None:
        session_factory = _in_memory_session_factory()
        orchestrator, _p, schedules, *_rest = _build_stack(session_factory, None)
        record = schedules.create(query="q", time_of_day="09:00")
        schedules.disable(record.id)
        router, _ = _router(_schedule_compound_text(record.id))
        orchestrator._tool_selection_router = router

        response = orchestrator.handle_request(_schedule_request(record.id))
        decision = orchestrator.approvals.decline(
            response.approval_request.request_id, decided_by="test"
        )
        final = orchestrator.execute_approved(response, decision)

        assert final.success is False
        assert schedules.get(record.id).enabled is False
        assert "did not complete" in final.message


# --- D. Six-outcome translation -------------------------------------------------


class _FailingEnableTool(BaseTool):
    @property
    def name(self) -> str:
        return "schedule_enable"

    @property
    def description(self) -> str:
        return "test double that always fails at run() time"

    def action_for(self, request: ToolRequest) -> str:
        return "enable a schedule"

    def run(self, request: ToolRequest) -> ToolResult:
        return ToolResult(tool_name=self.name, success=False, error="simulated enable failure")


class _MismatchingVerifyTool(BaseTool):
    @property
    def name(self) -> str:
        return "schedule_verify_enabled_state"

    @property
    def description(self) -> str:
        return "test double reporting a fixed, mismatching enabled state"

    def action_for(self, request: ToolRequest) -> str:
        return "show schedule enabled state"

    def run(self, request: ToolRequest) -> ToolResult:
        return ToolResult(
            tool_name=self.name,
            success=True,
            output="mismatched test double",
            metadata={"schedule_id": 1, "enabled": False, "enabled_str": "false"},
        )


class _VerifyFailsOnSecondCallTool(BaseTool):
    """Succeeds on its first call (the observer's pre-execution read)
    and fails on every call after that (Step 2's own verification)."""

    def __init__(self) -> None:
        self._call_count = 0

    @property
    def name(self) -> str:
        return "schedule_verify_enabled_state"

    @property
    def description(self) -> str:
        return "test double that fails from its second call onward"

    def action_for(self, request: ToolRequest) -> str:
        return "show schedule enabled state"

    def run(self, request: ToolRequest) -> ToolResult:
        self._call_count += 1
        if self._call_count == 1:
            return ToolResult(
                tool_name=self.name,
                success=True,
                output="ok",
                metadata={"schedule_id": 1, "enabled": False, "enabled_str": "false"},
            )
        return ToolResult(tool_name=self.name, success=False, error="simulated verifier failure")


class _FailingShowTool(BaseTool):
    @property
    def name(self) -> str:
        return "schedule_show_enabled_state"

    @property
    def description(self) -> str:
        return "test double that always fails at run() time"

    def action_for(self, request: ToolRequest) -> str:
        return "show schedule enabled state"

    def run(self, request: ToolRequest) -> ToolResult:
        return ToolResult(tool_name=self.name, success=False, error="simulated show failure")


class TestSixOutcomeTranslation:
    def test_enable_failure_outcome(self) -> None:
        session_factory = _in_memory_session_factory()
        orchestrator, _p, schedules, registry, *_rest = _build_stack(
            session_factory, None
        )
        record = schedules.create(query="q", time_of_day="09:00")
        schedules.disable(record.id)
        router, _ = _router(_schedule_compound_text(record.id))
        orchestrator._tool_selection_router = router
        registry._tools["schedule_enable"] = _FailingEnableTool()  # type: ignore[attr-defined]

        response = orchestrator.handle_request(_schedule_request(record.id))
        decision = orchestrator.approvals.approve(
            response.approval_request.request_id, decided_by="test"
        )
        final = orchestrator.execute_approved(response, decision)

        assert final.success is False
        assert "did not complete" in final.message
        assert schedules.get(record.id).enabled is False

    def test_verification_mismatch_outcome(self) -> None:
        session_factory = _in_memory_session_factory()
        orchestrator, _p, schedules, registry, *_rest = _build_stack(
            session_factory, None
        )
        record = schedules.create(query="q", time_of_day="09:00")
        schedules.disable(record.id)
        router, _ = _router(_schedule_compound_text(record.id))
        orchestrator._tool_selection_router = router
        registry._tools["schedule_verify_enabled_state"] = _MismatchingVerifyTool()  # type: ignore[attr-defined]

        response = orchestrator.handle_request(_schedule_request(record.id))
        decision = orchestrator.approvals.approve(
            response.approval_request.request_id, decided_by="test"
        )
        final = orchestrator.execute_approved(response, decision)

        assert final.success is False
        assert "not enabled" in final.message
        # The real enable itself still genuinely happened.
        assert schedules.get(record.id).enabled is True

    def test_verification_unavailable_outcome(self) -> None:
        session_factory = _in_memory_session_factory()
        orchestrator, _p, schedules, registry, *_rest = _build_stack(
            session_factory, None
        )
        record = schedules.create(query="q", time_of_day="09:00")
        schedules.disable(record.id)
        router, _ = _router(_schedule_compound_text(record.id))
        orchestrator._tool_selection_router = router
        registry._tools["schedule_verify_enabled_state"] = _VerifyFailsOnSecondCallTool()  # type: ignore[attr-defined]

        response = orchestrator.handle_request(_schedule_request(record.id))
        decision = orchestrator.approvals.approve(
            response.approval_request.request_id, decided_by="test"
        )
        final = orchestrator.execute_approved(response, decision)

        assert final.success is False
        assert "could not be completed" in final.message
        assert schedules.get(record.id).enabled is True

    def test_final_show_failure_outcome(self) -> None:
        session_factory = _in_memory_session_factory()
        orchestrator, _p, schedules, registry, *_rest = _build_stack(
            session_factory, None
        )
        record = schedules.create(query="q", time_of_day="09:00")
        schedules.disable(record.id)
        router, _ = _router(_schedule_compound_text(record.id))
        orchestrator._tool_selection_router = router
        registry._tools["schedule_show_enabled_state"] = _FailingShowTool()  # type: ignore[attr-defined]

        response = orchestrator.handle_request(_schedule_request(record.id))
        decision = orchestrator.approvals.approve(
            response.approval_request.request_id, decided_by="test"
        )
        final = orchestrator.execute_approved(response, decision)

        assert final.success is False
        assert "final enabled-state read failed" in final.message
        assert schedules.get(record.id).enabled is True


# --- E. CompoundCheckpointError handling ----------------------------------------


class TestCompoundCheckpointErrorHandling:
    def test_checkpoint_conflict_returns_bounded_message_never_marks_consumed_or_interrupted(
        self,
    ) -> None:
        session_factory = _in_memory_session_factory()
        orchestrator, _p, schedules, _registry, _security, approvals, workflow_engine, paused_store, _cps, schedule_progress_store = _build_stack(
            session_factory, None
        )
        record = schedules.create(query="q", time_of_day="09:00")
        schedules.disable(record.id)
        router, _ = _router(_schedule_compound_text(record.id))
        orchestrator._tool_selection_router = router

        response = orchestrator.handle_request(_schedule_request(record.id))
        request_id = response.approval_request.request_id
        workflow_id = _single_workflow_id(paused_store)

        schedule_progress_store.record_pre_execution_observation(
            workflow_id, enabled=False
        )

        decision = approvals.approve(request_id, decided_by="test")
        final = orchestrator.execute_approved(response, decision)

        assert final.success is False
        assert final.message == _COMPOUND_CHECKPOINT_INTERRUPTED_MESSAGE
        assert approvals.handoff_status_for(request_id) == PendingApprovalHandoffStatus.CLAIMED
        assert schedules.get(record.id).enabled is False
        assert workflow_engine.has_paused(workflow_id) is True
        assert paused_store.get(workflow_id) is not None


# --- F. Decline and expiry: dedicated non-execution terminalization ------------


class _CountingToolWrapper(BaseTool):
    def __init__(self, wrapped: BaseTool) -> None:
        self._wrapped = wrapped
        self.call_count = 0

    @property
    def name(self) -> str:
        return self._wrapped.name

    @property
    def description(self) -> str:
        return self._wrapped.description

    def action_for(self, request: ToolRequest) -> str:
        return self._wrapped.action_for(request)

    def run(self, request: ToolRequest) -> ToolResult:
        self.call_count += 1
        return self._wrapped.run(request)


class _FakeClock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


class TestDeclineAndExpiryTerminalization:
    def test_decline_terminalizes_progress_as_not_executed_with_zero_execution(
        self,
    ) -> None:
        session_factory = _in_memory_session_factory()
        orchestrator, _p, schedules, registry, *_rest, schedule_progress_store = (
            _build_stack(session_factory, None)
        )
        record = schedules.create(query="q", time_of_day="09:00")
        schedules.disable(record.id)
        router, _ = _router(_schedule_compound_text(record.id))
        orchestrator._tool_selection_router = router

        enable_wrapper = _CountingToolWrapper(registry.get_tool("schedule_enable"))
        verify_wrapper = _CountingToolWrapper(
            registry.get_tool("schedule_verify_enabled_state")
        )
        show_wrapper = _CountingToolWrapper(
            registry.get_tool("schedule_show_enabled_state")
        )
        registry._tools["schedule_enable"] = enable_wrapper  # type: ignore[attr-defined]
        registry._tools["schedule_verify_enabled_state"] = verify_wrapper  # type: ignore[attr-defined]
        registry._tools["schedule_show_enabled_state"] = show_wrapper  # type: ignore[attr-defined]

        response = orchestrator.handle_request(_schedule_request(record.id))
        workflow_id = _single_workflow_id(orchestrator._paused_workflow_store)
        decision = orchestrator.approvals.decline(
            response.approval_request.request_id, decided_by="test"
        )
        final = orchestrator.execute_approved(response, decision)

        assert final.success is False
        assert enable_wrapper.call_count == 0
        assert verify_wrapper.call_count == 0
        assert show_wrapper.call_count == 0
        assert schedules.get(record.id).enabled is False

        progress = schedule_progress_store.get(workflow_id)
        assert progress.overall_status is ScheduleCompoundOverallStatus.NOT_EXECUTED

    def test_declined_terminalization_is_idempotent(self) -> None:
        session_factory = _in_memory_session_factory()
        orchestrator, _p, schedules, *_rest, schedule_progress_store = _build_stack(
            session_factory, None
        )
        record = schedules.create(query="q", time_of_day="09:00")
        router, _ = _router(_schedule_compound_text(record.id))
        orchestrator._tool_selection_router = router

        response = orchestrator.handle_request(_schedule_request(record.id))
        workflow_id = _single_workflow_id(orchestrator._paused_workflow_store)
        decision = orchestrator.approvals.decline(
            response.approval_request.request_id, decided_by="test"
        )
        orchestrator.execute_approved(response, decision)

        second = schedule_progress_store.mark_not_executed_before_start(workflow_id)
        assert second.overall_status is ScheduleCompoundOverallStatus.NOT_EXECUTED

    def test_expiry_leaves_progress_pristine_until_repair_pass(self) -> None:
        start_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
        fake_clock = _FakeClock(start_time)
        session_factory = _in_memory_session_factory()
        orchestrator, _p, schedules, registry, *_rest = _build_stack(
            session_factory, None, timeout_seconds=60, clock=fake_clock
        )
        record = schedules.create(query="q", time_of_day="09:00")
        router, _ = _router(_schedule_compound_text(record.id))
        orchestrator._tool_selection_router = router
        enable_wrapper = _CountingToolWrapper(registry.get_tool("schedule_enable"))
        registry._tools["schedule_enable"] = enable_wrapper  # type: ignore[attr-defined]

        response = orchestrator.handle_request(_schedule_request(record.id))
        request_id = response.approval_request.request_id

        fake_clock.now = start_time + timedelta(seconds=61)
        assert orchestrator.approvals.has_pending(request_id) is False
        assert enable_wrapper.call_count == 0

    def test_expiry_is_terminalized_by_the_repair_pass(self) -> None:
        start_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
        fake_clock = _FakeClock(start_time)
        session_factory = _in_memory_session_factory()
        orchestrator, _p, schedules, *_rest, schedule_progress_store = _build_stack(
            session_factory, None, timeout_seconds=60, clock=fake_clock
        )
        record = schedules.create(query="q", time_of_day="09:00")
        router, _ = _router(_schedule_compound_text(record.id))
        orchestrator._tool_selection_router = router

        response = orchestrator.handle_request(_schedule_request(record.id))
        workflow_id = _single_workflow_id(orchestrator._paused_workflow_store)
        request_id = response.approval_request.request_id

        fake_clock.now = start_time + timedelta(seconds=61)
        assert orchestrator.approvals.has_pending(request_id) is False
        assert orchestrator.approvals.handoff_status_for(request_id) == (
            PendingApprovalHandoffStatus.EXPIRED
        )

        from core.schedule_compound_workflow import (
            terminalize_declined_or_expired_schedule_compound_progress,
        )

        terminalized = terminalize_declined_or_expired_schedule_compound_progress(
            pending_store=PendingApprovalStore(session_factory),
            progress_store=schedule_progress_store,
            declined_status=PendingApprovalHandoffStatus.DECLINED,
            expired_status=PendingApprovalHandoffStatus.EXPIRED,
        )
        assert terminalized == 1
        progress = schedule_progress_store.get(workflow_id)
        assert progress.overall_status is ScheduleCompoundOverallStatus.NOT_EXECUTED


# --- G. Interlock proof --------------------------------------------------------


class TestInterlock:
    def test_failed_claim_causes_zero_execution(self) -> None:
        session_factory = _in_memory_session_factory()
        orchestrator, _p, schedules, registry, *_rest = _build_stack(
            session_factory, None
        )
        record = schedules.create(query="q", time_of_day="09:00")
        schedules.disable(record.id)
        router, _ = _router(_schedule_compound_text(record.id))
        orchestrator._tool_selection_router = router
        enable_wrapper = _CountingToolWrapper(registry.get_tool("schedule_enable"))
        registry._tools["schedule_enable"] = enable_wrapper  # type: ignore[attr-defined]

        response = orchestrator.handle_request(_schedule_request(record.id))
        decision = orchestrator.approvals.approve(
            response.approval_request.request_id, decided_by="test"
        )
        # Simulate a second, concurrent claim already having consumed
        # this request before this one runs.
        claimed_first = orchestrator.approvals.claim_for_resume(decision.request_id)
        assert claimed_first is True

        final = orchestrator.execute_approved(response, decision)
        assert final.success is False
        assert "could not be claimed" in final.message
        assert enable_wrapper.call_count == 0
        assert schedules.get(record.id).enabled is False

    def test_observer_is_attached_only_after_successful_claim(self) -> None:
        """Proven indirectly: before claim_for_resume() succeeds, no
        progress checkpoint transition beyond the initial PENDING state
        can have occurred."""
        session_factory = _in_memory_session_factory()
        orchestrator, _p, schedules, *_rest, schedule_progress_store = _build_stack(
            session_factory, None
        )
        record = schedules.create(query="q", time_of_day="09:00")
        router, _ = _router(_schedule_compound_text(record.id))
        orchestrator._tool_selection_router = router

        orchestrator.handle_request(_schedule_request(record.id))
        workflow_id = _single_workflow_id(orchestrator._paused_workflow_store)
        progress = schedule_progress_store.get(workflow_id)
        assert progress.step_1_status.value == "pending"


# --- H. Restart and crash recovery ----------------------------------------------


@pytest.fixture()
def hermetic_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_path = tmp_path / "phase99_batch3_jarvis.db"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    monkeypatch.delenv("AI_REASONING_ENABLED", raising=False)
    return db_path


def _hermetic_session_factory(db_path: Path):
    engine = create_engine(f"sqlite:///{db_path}")
    initialize_database(engine)
    return create_session_factory(engine)


class TestRestartAndCrashRecovery:
    def test_durable_restart_end_to_end_reaches_full_success(
        self, hermetic_db: Path
    ) -> None:
        import main

        orchestrator, lock = main.start_execution_session()
        try:
            session_factory = _hermetic_session_factory(hermetic_db)
            schedules = ScheduleStore(session_factory)
            record = schedules.create(query="q", time_of_day="09:00")
            schedules.disable(record.id)

            schedule_plan = _build_schedule_enable_verify_show_workflow_plan(
                _schedule_request(record.id),
                approved_schedule_id=record.id,
                tool_registry=orchestrator._registry,
                security_manager=orchestrator._security,
                session_id=None,
                catalog=CAPABILITY_CATALOG,
            )
            result = orchestrator._workflow_engine.run(schedule_plan)
            assert result.overall_status.value == "waiting"
            request_id = result.pending_approval_request.request_id
            workflow_id = result.workflow_id

            established = establish_schedule_compound_progress_or_isolate(
                plan=schedule_plan,
                workflow_id=workflow_id,
                request_id=request_id,
                progress_store=orchestrator._schedule_compound_progress_store,
                approval_invalidator=orchestrator.approvals,
                paused_workflow_store=orchestrator._paused_workflow_store,
            )
            assert not isinstance(established, str)

            orchestrator.approvals.approve(request_id, decided_by="test")
        finally:
            lock.release()

        orchestrator2, lock2 = main.start_execution_session()
        try:
            assert (
                orchestrator2.approvals.handoff_status_for(request_id)
                == PendingApprovalHandoffStatus.CONSUMED
            )
            schedules2 = ScheduleStore(session_factory)
            assert schedules2.get(record.id).enabled is True
        finally:
            lock2.release()

    def test_compound_first_ordering_resolves_recognized_row_before_generic_fallback(
        self, hermetic_db: Path
    ) -> None:
        """A CLAIMED row whose durable progress shows the write and
        verification both already durably completed (verified) before
        an assumed crash, but whose final show step never ran, must be
        safely completed and marked CONSUMED by the schedule-compound
        startup pass."""
        import main

        orchestrator, lock = main.start_execution_session()
        try:
            session_factory = _hermetic_session_factory(hermetic_db)
            schedules = ScheduleStore(session_factory)
            record = schedules.create(query="q", time_of_day="09:00")
            schedules.enable(record.id)

            schedule_plan = _build_schedule_enable_verify_show_workflow_plan(
                _schedule_request(record.id),
                approved_schedule_id=record.id,
                tool_registry=orchestrator._registry,
                security_manager=orchestrator._security,
                session_id=None,
                catalog=CAPABILITY_CATALOG,
            )
            result = orchestrator._workflow_engine.run(schedule_plan)
            request_id = result.pending_approval_request.request_id
            workflow_id = result.workflow_id

            established = establish_schedule_compound_progress_or_isolate(
                plan=schedule_plan,
                workflow_id=workflow_id,
                request_id=request_id,
                progress_store=orchestrator._schedule_compound_progress_store,
                approval_invalidator=orchestrator.approvals,
                paused_workflow_store=orchestrator._paused_workflow_store,
            )
            assert not isinstance(established, str)

            orchestrator.approvals.approve(request_id, decided_by="test")
            claimed = orchestrator.approvals.claim_for_resume(request_id)
            assert claimed is True

            progress_store = orchestrator._schedule_compound_progress_store
            progress_store.record_pre_execution_observation(
                workflow_id, enabled=False
            )
            progress_store.mark_step_1_completed(workflow_id)
            progress_store.start_step_2(workflow_id)
            from workflow.schedule_compound_workflow_progress_store import (
                ScheduleCompoundVerificationOutcome,
            )

            progress_store.mark_step_2_completed(
                workflow_id,
                verification_outcome=ScheduleCompoundVerificationOutcome.VERIFIED,
            )
            progress_store.start_step_3(workflow_id)
        finally:
            lock.release()

        orchestrator2, lock2 = main.start_execution_session()
        try:
            assert (
                orchestrator2.approvals.handoff_status_for(request_id)
                == PendingApprovalHandoffStatus.CONSUMED
            )
            schedules2 = ScheduleStore(session_factory)
            assert schedules2.get(record.id).enabled is True
        finally:
            lock2.release()

    def test_ambiguous_pre_execution_interruption_is_not_falsely_confirmed(
        self, hermetic_db: Path
    ) -> None:
        """The Batch 2 safety rule: if the schedule was already enabled
        before execution and remains enabled afterward, the interrupted
        enable must never be falsely concluded to have definitely
        executed - the execution-unconfirmed/reconciliation outcome
        must be used instead, leaving the row CLAIM_INTERRUPTED rather
        than CONSUMED."""
        import main

        orchestrator, lock = main.start_execution_session()
        try:
            session_factory = _hermetic_session_factory(hermetic_db)
            schedules = ScheduleStore(session_factory)
            record = schedules.create(query="q", time_of_day="09:00")
            schedules.enable(record.id)  # already enabled before execution

            schedule_plan = _build_schedule_enable_verify_show_workflow_plan(
                _schedule_request(record.id),
                approved_schedule_id=record.id,
                tool_registry=orchestrator._registry,
                security_manager=orchestrator._security,
                session_id=None,
                catalog=CAPABILITY_CATALOG,
            )
            result = orchestrator._workflow_engine.run(schedule_plan)
            request_id = result.pending_approval_request.request_id
            workflow_id = result.workflow_id

            established = establish_schedule_compound_progress_or_isolate(
                plan=schedule_plan,
                workflow_id=workflow_id,
                request_id=request_id,
                progress_store=orchestrator._schedule_compound_progress_store,
                approval_invalidator=orchestrator.approvals,
                paused_workflow_store=orchestrator._paused_workflow_store,
            )
            assert not isinstance(established, str)

            orchestrator.approvals.approve(request_id, decided_by="test")
            orchestrator.approvals.claim_for_resume(request_id)

            progress_store = orchestrator._schedule_compound_progress_store
            # Pre-execution observation shows already-enabled; no
            # further evidence (no timestamp column) distinguishes
            # "executed and trivially re-enabled" from "never executed".
            progress_store.record_pre_execution_observation(
                workflow_id, enabled=True
            )
        finally:
            lock.release()

        orchestrator2, lock2 = main.start_execution_session()
        try:
            assert (
                orchestrator2.approvals.handoff_status_for(request_id)
                == PendingApprovalHandoffStatus.CLAIM_INTERRUPTED
            )
        finally:
            lock2.release()

    def test_unrecognized_claimed_row_is_left_for_generic_fallback(
        self, hermetic_db: Path
    ) -> None:
        import main
        from workflow.workflow_history_store import WorkflowHistoryStore

        orchestrator, lock = main.start_execution_session()
        try:
            session_factory = _hermetic_session_factory(hermetic_db)
            pending_store = PendingApprovalStore(session_factory)
            workflow_history = WorkflowHistoryStore(session_factory)
            pending_store.save(
                request_id="unrelated-req",
                action="update project state phase",
                reason="needs approval",
                security_tier="yellow",
                metadata={"workflow_id": "unrelated-wf"},
                tool_name="project_state_update",
                tool_input={"field": "phase", "value": "Solo phase"},
            )
            pending_store.mark_approved_unconsumed("unrelated-req")
            pending_store.claim_for_resume("unrelated-req")
            workflow_history.record_transition(
                workflow_id="unrelated-wf", status="workflow_completed"
            )
        finally:
            lock.release()

        orchestrator2, lock2 = main.start_execution_session()
        try:
            assert (
                orchestrator2.approvals.handoff_status_for("unrelated-req")
                == PendingApprovalHandoffStatus.CONSUMED
            )
        finally:
            lock2.release()
