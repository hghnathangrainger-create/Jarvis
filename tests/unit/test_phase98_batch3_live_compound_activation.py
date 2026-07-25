"""
test_phase98_batch3_live_compound_activation.py

Live, end-to-end proof of Phase 98, Batch 3's atomic compound
activation (docs/phase_98_live_compound_reentry_plan.md): the first
live bounded compound request - "ask jarvis to: update my project
phase to X and then show my project state" - reachable through the
real, wired-together path: intelligence.planning.select_tool()'s
discriminator -> exact compound parsing/grounding -> the trusted
three-step Plan -> JarvisOrchestrator._start_compound_update_phase_and_
show_workflow() (progress creation before an actionable approval) ->
one honest approval -> JarvisOrchestrator._claim_and_resume_workflow()
(claim, CompoundStepObserver attachment, CompoundCheckpointError
handling) -> core.compound_workflow.translate_compound_workflow_result()
's six bounded outcomes -> compound-first startup recovery ordering in
main.reconcile_claimed_handoffs().

Mirrors tests/unit/test_orchestrator_update_phase_workflow.py's own
established real-stack pattern (real Planner, SecurityManager,
CommandRouter, ToolRegistry, ToolExecutor, ApprovalManager,
WorkflowEngine, MemoryManager over a real in-memory SQLite
EpisodicMemoryStore, real ProjectStateStore, real
ProjectStateUpdateTool/ProjectStateVerifyTool/ProjectStateShowTool,
real ContextAssembler, and a real AIRouter wired to a real
PromptBuilder and a fake, in-memory AIProvider) for Sections A-E, and
tests/unit/test_crash_window_proof.py's own hermetic on-disk-database
pattern (main.start_execution_session()/main.reconcile_claimed_handoffs())
for Section F's restart/crash-recovery proofs - no live Claude API
call and no real network call is ever made anywhere in this file.

Run with:
    pytest tests/unit/test_phase98_batch3_live_compound_activation.py
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
    from core.compound_workflow import establish_compound_progress_or_isolate
    from core.orchestrator import (
        _COMPOUND_CHECKPOINT_INTERRUPTED_MESSAGE,
        JarvisOrchestrator,
    )
    from intelligence.capability_catalog import CAPABILITY_CATALOG
    from intelligence.context import ContextAssembler
    from intelligence.planning import _build_phase_update_verify_show_workflow_plan
    from memory.episodic_memory import EpisodicMemoryStore
    from memory.memory_manager import MemoryManager
    from planner.planner import Planner
    from project_state.project_state_store import ProjectStateStore
    from security.security_manager import SecurityManager
    from storage.database import create_session_factory, initialize_database
    from tools.base_tool import BaseTool, ToolRequest, ToolResult
    from tools.builtin.project_state_show_tool import ProjectStateShowTool
    from tools.builtin.project_state_update_tool import ProjectStateUpdateTool
    from tools.builtin.project_state_verify_tool import ProjectStateVerifyTool
    from tools.executor import ToolExecutor
    from tools.registry import ToolRegistry
    from workflow.compound_workflow_progress_store import CompoundWorkflowProgressStore
    from workflow.engine import WorkflowEngine
    from workflow.paused_workflow_store import PausedWorkflowStore
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


def _compound_text(value: str) -> str:
    return json.dumps(
        {
            "decision": "execute_sequence",
            "steps": [
                {
                    "capability_id": "project_state_update_phase",
                    "arguments": {"value": value},
                },
                {"capability_id": "project_state_show", "arguments": {}},
            ],
        }
    )


_PHASE_VALUE = "Phase 98 Batch 3"
_REQUEST = (
    f"ask jarvis to: update my project phase to {_PHASE_VALUE} and then "
    "show my project state"
)


def _build_stack(session_factory, router, *, timeout_seconds=None, clock=None):
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
    )
    return (
        orchestrator,
        project_state_store,
        registry,
        security,
        approvals,
        workflow_engine,
        paused_store,
        compound_progress_store,
    )


def _in_memory_session_factory():
    engine = create_engine("sqlite:///:memory:")
    initialize_database(engine)
    return create_session_factory(engine)


def _single_workflow_id(paused_store: PausedWorkflowStore) -> str:
    rows = paused_store.list_all()
    assert len(rows) == 1
    return rows[0].workflow_id


# --- A. Decision activation ---------------------------------------------------


class TestDecisionActivation:
    def test_execute_sequence_decision_produces_a_real_three_step_paused_plan(
        self,
    ) -> None:
        router, _ = _router(_compound_text(_PHASE_VALUE))
        orchestrator, *_rest, paused_store, progress_store = _build_stack(
            _in_memory_session_factory(), router
        )

        response = orchestrator.handle_request(_REQUEST)

        assert response.requires_confirmation is True
        rows = paused_store.list_all()
        assert len(rows) == 1
        assert len(rows[0].plan_steps) == 3
        assert rows[0].plan_steps[0]["tool_name"] == "project_state_update"
        assert rows[0].plan_steps[1]["tool_name"] == "project_state_verify"
        assert rows[0].plan_steps[2]["tool_name"] == "project_state_show"
        assert progress_store.get(rows[0].workflow_id) is not None

    def test_single_capability_show_request_is_unaffected_by_compound_wiring(
        self,
    ) -> None:
        router, _ = _router(
            json.dumps(
                {
                    "decision": "execute",
                    "capability_id": "project_state_show",
                    "arguments": {},
                }
            )
        )
        orchestrator, *_rest, paused_store, _progress = _build_stack(
            _in_memory_session_factory(), router
        )

        response = orchestrator.handle_request("ask jarvis to: show my project state")

        assert response.success is True
        assert response.requires_confirmation is False
        assert paused_store.list_all() == []

    def test_malformed_step_count_is_rejected_never_falls_back(self) -> None:
        malformed = json.dumps(
            {
                "decision": "execute_sequence",
                "steps": [
                    {
                        "capability_id": "project_state_update_phase",
                        "arguments": {"value": _PHASE_VALUE},
                    }
                ],
            }
        )
        router, _ = _router(malformed)
        orchestrator, project_state_store, _, _, approvals, _, paused_store, _ = (
            _build_stack(_in_memory_session_factory(), router)
        )

        response = orchestrator.handle_request(_REQUEST)

        assert response.success is False
        assert response.requires_confirmation is False
        assert approvals.list_pending() == []
        assert paused_store.list_all() == []
        assert project_state_store.get() is None

    def test_reversed_pair_is_rejected_never_falls_back(self) -> None:
        reversed_pair = json.dumps(
            {
                "decision": "execute_sequence",
                "steps": [
                    {"capability_id": "project_state_show", "arguments": {}},
                    {
                        "capability_id": "project_state_update_phase",
                        "arguments": {"value": _PHASE_VALUE},
                    },
                ],
            }
        )
        router, _ = _router(reversed_pair)
        orchestrator, project_state_store, _, _, approvals, _, paused_store, _ = (
            _build_stack(_in_memory_session_factory(), router)
        )

        response = orchestrator.handle_request(_REQUEST)

        assert response.success is False
        assert approvals.list_pending() == []
        assert paused_store.list_all() == []
        assert project_state_store.get() is None

    def test_disallowed_capability_pair_is_rejected_never_falls_back(self) -> None:
        disallowed_pair = json.dumps(
            {
                "decision": "execute_sequence",
                "steps": [
                    {"capability_id": "schedule_enable", "arguments": {"schedule_id": 1}},
                    {"capability_id": "schedule_disable", "arguments": {"schedule_id": 1}},
                ],
            }
        )
        router, _ = _router(disallowed_pair)
        orchestrator, project_state_store, _, _, approvals, _, paused_store, _ = (
            _build_stack(_in_memory_session_factory(), router)
        )

        response = orchestrator.handle_request(
            "ask jarvis to: enable schedule 1 and then disable schedule 1"
        )

        assert response.success is False
        assert approvals.list_pending() == []
        assert paused_store.list_all() == []
        assert project_state_store.get() is None

    def test_ungrounded_compound_request_creates_no_approval_and_no_write(self) -> None:
        """The model declares the one trusted pair, but the live request
        text does not actually contain the fixed " and then " connector
        joining the right clauses - refused before any preflight,
        approval, or execution (mirrors the single-capability grounding
        refusal tests in test_orchestrator_update_phase_workflow.py)."""
        router, provider = _router(_compound_text(_PHASE_VALUE))
        orchestrator, project_state_store, _, _, approvals, _, paused_store, _ = (
            _build_stack(_in_memory_session_factory(), router)
        )

        response = orchestrator.handle_request(
            "ask jarvis to: update my project phase to "
            f"{_PHASE_VALUE} then show my project state"
        )

        assert response.success is False
        assert response.requires_confirmation is False
        assert approvals.list_pending() == []
        assert paused_store.list_all() == []
        assert project_state_store.get() is None
        assert len(provider.received_requests) == 1


# --- B. Approval and progress creation ----------------------------------------


class TestApprovalAndProgressCreation:
    def test_project_state_store_unchanged_while_compound_pending(self) -> None:
        router, _ = _router(_compound_text(_PHASE_VALUE))
        orchestrator, project_state_store, *_ = _build_stack(
            _in_memory_session_factory(), router
        )

        orchestrator.handle_request(_REQUEST)

        assert project_state_store.get() is None

    def test_validate_pending_approval_for_transition_allows_a_recognized_valid_compound_approval(
        self,
    ) -> None:
        router, _ = _router(_compound_text(_PHASE_VALUE))
        orchestrator, *_rest = _build_stack(_in_memory_session_factory(), router)

        response = orchestrator.handle_request(_REQUEST)

        assert (
            orchestrator.validate_pending_approval_for_transition(
                response.approval_request
            )
            is None
        )

    def test_validate_pending_approval_for_transition_is_a_noop_for_non_compound_approval(
        self,
    ) -> None:
        router, _ = _router(
            json.dumps(
                {
                    "decision": "execute",
                    "capability_id": "project_state_update_focus",
                    "arguments": {"value": "unrelated"},
                }
            )
        )
        orchestrator, *_rest = _build_stack(_in_memory_session_factory(), router)

        response = orchestrator.handle_request(
            "ask jarvis to: update my project focus to unrelated"
        )

        assert (
            orchestrator.validate_pending_approval_for_transition(
                response.approval_request
            )
            is None
        )

    def test_validate_pending_approval_for_transition_refuses_when_progress_row_missing(
        self,
    ) -> None:
        """Bypasses the AI-driven request path to construct the exact
        trusted three-step Plan and pause it directly through the real
        WorkflowEngine, deliberately never calling
        establish_compound_progress_or_isolate() - simulating a paused
        compound plan whose progress row was never (or no longer)
        created."""
        session_factory = _in_memory_session_factory()
        router, _ = _router(_compound_text(_PHASE_VALUE))
        orchestrator, _, registry, security, _, workflow_engine, *_ = _build_stack(
            session_factory, router
        )

        compound_plan = _build_phase_update_verify_show_workflow_plan(
            _REQUEST,
            approved_phase_value=_PHASE_VALUE,
            tool_registry=registry,
            security_manager=security,
            session_id=None,
            catalog=CAPABILITY_CATALOG,
        )
        result = workflow_engine.run(compound_plan)
        assert result.overall_status.value == "waiting"

        reason = orchestrator.validate_pending_approval_for_transition(
            result.pending_approval_request
        )

        assert reason is not None
        assert "no compound progress row exists" in reason


# --- C. Normal execution end-to-end -------------------------------------------


class TestNormalExecutionEndToEnd:
    def test_full_success_updates_verifies_and_shows(self) -> None:
        router, _ = _router(_compound_text(_PHASE_VALUE))
        orchestrator, project_state_store, *_ = _build_stack(
            _in_memory_session_factory(), router
        )

        response = orchestrator.handle_request(_REQUEST)
        decision = orchestrator.approvals.approve(
            response.approval_request.request_id, decided_by="test"
        )
        final = orchestrator.execute_approved(response, decision)

        assert final.success is True
        assert project_state_store.get().phase == _PHASE_VALUE
        assert _PHASE_VALUE in final.message
        assert "Verification succeeded" in final.message
        assert "Jarvis Project State" in final.message or "phase" in final.message.lower()

    def test_duplicate_resume_does_not_duplicate_the_write(self) -> None:
        router, _ = _router(_compound_text(_PHASE_VALUE))
        orchestrator, project_state_store, *_ = _build_stack(
            _in_memory_session_factory(), router
        )

        response = orchestrator.handle_request(_REQUEST)
        decision = orchestrator.approvals.approve(
            response.approval_request.request_id, decided_by="test"
        )
        first = orchestrator.execute_approved(response, decision)
        assert first.success is True

        second = orchestrator.execute_approved(response, decision)

        assert project_state_store.get().phase == _PHASE_VALUE
        assert second.tool_result is None

    def test_no_second_ai_call_after_compound_execution(self) -> None:
        router, provider = _router(_compound_text(_PHASE_VALUE))
        orchestrator, *_rest = _build_stack(_in_memory_session_factory(), router)

        response = orchestrator.handle_request(_REQUEST)
        assert len(provider.received_requests) == 1
        decision = orchestrator.approvals.approve(
            response.approval_request.request_id, decided_by="test"
        )
        orchestrator.execute_approved(response, decision)

        assert len(provider.received_requests) == 1

    def test_decline_leaves_no_write_and_reports_update_did_not_complete(self) -> None:
        router, _ = _router(_compound_text(_PHASE_VALUE))
        orchestrator, project_state_store, *_ = _build_stack(
            _in_memory_session_factory(), router
        )

        response = orchestrator.handle_request(_REQUEST)
        decision = orchestrator.approvals.decline(
            response.approval_request.request_id, decided_by="test"
        )
        final = orchestrator.execute_approved(response, decision)

        assert final.success is False
        assert project_state_store.get() is None
        assert "did not complete" in final.message


# --- D. Six-outcome translation -------------------------------------------------


class _FailingUpdateTool(BaseTool):
    @property
    def name(self) -> str:
        return "project_state_update"

    @property
    def description(self) -> str:
        return "test double that always fails at run() time"

    def action_for(self, request: ToolRequest) -> str:
        return "update jarvis project state"

    def run(self, request: ToolRequest) -> ToolResult:
        return ToolResult(tool_name=self.name, success=False, error="simulated write failure")


class _MismatchingVerifyTool(BaseTool):
    @property
    def name(self) -> str:
        return "project_state_verify"

    @property
    def description(self) -> str:
        return "test double reporting a fixed, mismatching phase value"

    def action_for(self, request: ToolRequest) -> str:
        return "show jarvis project state"

    def run(self, request: ToolRequest) -> ToolResult:
        return ToolResult(
            tool_name=self.name,
            success=True,
            output="mismatched test double",
            metadata={"phase": "a completely different stored value"},
        )


class _VerifyFailsOnSecondCallTool(BaseTool):
    """A test double for project_state_verify that succeeds on its
    first call and fails on every call after that.

    The real CompoundStepObserver calls this same registered tool
    twice for two different reasons: once for its own pre-execution
    observation read (before_step(0), before the write even runs), and
    once as Step 2's actual verification (after_step(1), after the
    write succeeds). A double that always fails would fail the
    pre-execution read too, producing a real CompoundCheckpointError
    before Step 1 ever runs - masking the intended "verification itself
    is unavailable at Step 2" outcome this test exists to exercise.
    Failing only from the second call onward instead models a
    realistic scenario (the same tool becoming unavailable strictly
    between those two calls), reaching the intended live outcome
    through the real observer, not a fake one."""

    def __init__(self) -> None:
        self._call_count = 0

    @property
    def name(self) -> str:
        return "project_state_verify"

    @property
    def description(self) -> str:
        return "test double that fails from its second call onward"

    def action_for(self, request: ToolRequest) -> str:
        return "show jarvis project state"

    def run(self, request: ToolRequest) -> ToolResult:
        self._call_count += 1
        if self._call_count == 1:
            return ToolResult(
                tool_name=self.name,
                success=True,
                output="ok",
                metadata={"phase": "pre-existing phase", "last_updated_at": None},
            )
        return ToolResult(tool_name=self.name, success=False, error="simulated verifier failure")


class _FailingShowTool(BaseTool):
    @property
    def name(self) -> str:
        return "project_state_show"

    @property
    def description(self) -> str:
        return "test double that always fails at run() time"

    def action_for(self, request: ToolRequest) -> str:
        return "show jarvis project state"

    def run(self, request: ToolRequest) -> ToolResult:
        return ToolResult(tool_name=self.name, success=False, error="simulated show failure")


class TestSixOutcomeTranslation:
    def test_update_failure_outcome(self) -> None:
        router, _ = _router(_compound_text(_PHASE_VALUE))
        orchestrator, project_state_store, registry, *_ = _build_stack(
            _in_memory_session_factory(), router
        )
        registry._tools["project_state_update"] = _FailingUpdateTool()  # type: ignore[attr-defined]

        response = orchestrator.handle_request(_REQUEST)
        decision = orchestrator.approvals.approve(
            response.approval_request.request_id, decided_by="test"
        )
        final = orchestrator.execute_approved(response, decision)

        assert final.success is False
        assert "did not complete" in final.message
        assert project_state_store.get() is None

    def test_verification_mismatch_outcome(self) -> None:
        router, _ = _router(_compound_text(_PHASE_VALUE))
        orchestrator, project_state_store, registry, *_ = _build_stack(
            _in_memory_session_factory(), router
        )
        registry._tools["project_state_verify"] = _MismatchingVerifyTool()  # type: ignore[attr-defined]

        response = orchestrator.handle_request(_REQUEST)
        decision = orchestrator.approvals.approve(
            response.approval_request.request_id, decided_by="test"
        )
        final = orchestrator.execute_approved(response, decision)

        assert final.success is False
        assert "different value than requested" in final.message
        # The real write itself still genuinely happened.
        assert project_state_store.get().phase == _PHASE_VALUE

    def test_verification_unavailable_outcome(self) -> None:
        router, _ = _router(_compound_text(_PHASE_VALUE))
        orchestrator, project_state_store, registry, *_ = _build_stack(
            _in_memory_session_factory(), router
        )
        registry._tools["project_state_verify"] = _VerifyFailsOnSecondCallTool()  # type: ignore[attr-defined]

        response = orchestrator.handle_request(_REQUEST)
        decision = orchestrator.approvals.approve(
            response.approval_request.request_id, decided_by="test"
        )
        final = orchestrator.execute_approved(response, decision)

        assert final.success is False
        assert "could not be completed" in final.message
        assert project_state_store.get().phase == _PHASE_VALUE

    def test_final_show_failure_outcome(self) -> None:
        router, _ = _router(_compound_text(_PHASE_VALUE))
        orchestrator, project_state_store, registry, *_ = _build_stack(
            _in_memory_session_factory(), router
        )
        registry._tools["project_state_show"] = _FailingShowTool()  # type: ignore[attr-defined]

        response = orchestrator.handle_request(_REQUEST)
        decision = orchestrator.approvals.approve(
            response.approval_request.request_id, decided_by="test"
        )
        final = orchestrator.execute_approved(response, decision)

        assert final.success is False
        assert "final project-state read failed" in final.message
        # The update itself was verified before the final read failed.
        assert project_state_store.get().phase == _PHASE_VALUE


# --- E. CompoundCheckpointError handling ----------------------------------------


class TestCompoundCheckpointErrorHandling:
    def test_checkpoint_conflict_returns_bounded_message_never_marks_consumed_or_interrupted(
        self,
    ) -> None:
        """Directly forces a real CAS conflict inside the durable
        CompoundWorkflowProgressStore (simulating an earlier, now-lost
        resume attempt having already advanced the checkpoint state) so
        the real CompoundStepObserver's before_step(0) genuinely fails
        its own real record_pre_execution_observation() call - proving
        the live CompoundCheckpointError path end-to-end, not with a
        fake observer."""
        router, _ = _router(_compound_text(_PHASE_VALUE))
        (
            orchestrator,
            project_state_store,
            _registry,
            _security,
            approvals,
            workflow_engine,
            paused_store,
            progress_store,
        ) = _build_stack(_in_memory_session_factory(), router)

        response = orchestrator.handle_request(_REQUEST)
        request_id = response.approval_request.request_id
        workflow_id = _single_workflow_id(paused_store)

        # Force the checkpoint conflict: advance the durable progress
        # row past PENDING before resume() ever gets a chance to.
        progress_store.record_pre_execution_observation(
            workflow_id, phase_value="pre-existing-crash-value", last_updated=None
        )

        decision = approvals.approve(request_id, decided_by="test")
        final = orchestrator.execute_approved(response, decision)

        assert final.success is False
        assert final.message == _COMPOUND_CHECKPOINT_INTERRUPTED_MESSAGE
        assert approvals.handoff_status_for(request_id) == PendingApprovalHandoffStatus.CLAIMED
        assert project_state_store.get() is None
        assert workflow_engine.has_paused(workflow_id) is True
        assert paused_store.get(workflow_id) is not None

    def test_checkpoint_failure_message_is_bounded_and_never_leaks_exception_text(
        self,
    ) -> None:
        assert "Traceback" not in _COMPOUND_CHECKPOINT_INTERRUPTED_MESSAGE
        assert "durable checkpoint" in _COMPOUND_CHECKPOINT_INTERRUPTED_MESSAGE.casefold()
        # A short, fixed, honest sentence - never a raw exception
        # string or stack trace, though not held to an arbitrary
        # character cap.
        assert len(_COMPOUND_CHECKPOINT_INTERRUPTED_MESSAGE) <= 400


# --- F. Decline and expiry: dedicated non-execution terminalization ------------


class _CountingToolWrapper(BaseTool):
    """Wraps a real, already-registered tool, counting real run() calls
    - used to prove a declined/expired compound workflow invokes
    ToolExecutor/the verifier/the final show step exactly zero times,
    not merely that the ProjectState store happens to be unwritten."""

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
    """Phase 98, Batch 3: for an exact, recognized compound workflow
    that is declined or expired, CompoundStepObserver is never
    attached at all - the existing, generic WorkflowEngine decline/
    expiry contract runs completely unaffected - and the compound
    progress row is instead terminalized separately, honestly, as
    NOT_EXECUTED (never FAILED, which would falsely imply a write was
    attempted)."""

    def test_decline_terminalizes_progress_as_not_executed_with_zero_execution(
        self,
    ) -> None:
        from workflow.compound_workflow_progress_store import (
            CompoundOverallStatus,
            CompoundStepStatus,
        )

        router, _ = _router(_compound_text(_PHASE_VALUE))
        orchestrator, project_state_store, registry, *_rest, paused_store, progress_store = (
            _build_stack(_in_memory_session_factory(), router)
        )
        write_wrapper = _CountingToolWrapper(registry.get_tool("project_state_update"))
        verify_wrapper = _CountingToolWrapper(registry.get_tool("project_state_verify"))
        show_wrapper = _CountingToolWrapper(registry.get_tool("project_state_show"))
        registry._tools["project_state_update"] = write_wrapper  # type: ignore[attr-defined]
        registry._tools["project_state_verify"] = verify_wrapper  # type: ignore[attr-defined]
        registry._tools["project_state_show"] = show_wrapper  # type: ignore[attr-defined]

        response = orchestrator.handle_request(_REQUEST)
        workflow_id = _single_workflow_id(paused_store)
        decision = orchestrator.approvals.decline(
            response.approval_request.request_id, decided_by="test"
        )
        final = orchestrator.execute_approved(response, decision)

        assert final.success is False
        assert "did not complete" in final.message

        # Zero observer step events, zero execution of any of the
        # three real tools.
        assert write_wrapper.call_count == 0
        assert verify_wrapper.call_count == 0
        assert show_wrapper.call_count == 0
        assert project_state_store.get() is None

        # Honest, terminal, non-execution progress state - never
        # FAILED, and every step still exactly PENDING (before_step()
        # was never called, so nothing was ever marked in progress).
        progress = progress_store.get(workflow_id)
        assert progress.overall_status is CompoundOverallStatus.NOT_EXECUTED
        assert progress.step_1_status is CompoundStepStatus.PENDING
        assert progress.step_2_status is CompoundStepStatus.PENDING
        assert progress.step_3_status is CompoundStepStatus.PENDING
        assert progress.pre_execution_phase_value is None

    def test_decline_generic_workflow_engine_behavior_is_unaffected(self) -> None:
        """The paused workflow row is removed and a genuine
        "workflow_stopped" terminal history entry is written - exactly
        the same generic decline contract every other workflow already
        gets, proving the observer's absence changed nothing about it."""
        session_factory = _in_memory_session_factory()
        router, _ = _router(_compound_text(_PHASE_VALUE))
        orchestrator, _, _, _, approvals, workflow_engine, paused_store, _ = _build_stack(
            session_factory, router
        )
        workflow_history = WorkflowHistoryStore(session_factory)

        response = orchestrator.handle_request(_REQUEST)
        workflow_id = _single_workflow_id(paused_store)
        decision = approvals.decline(
            response.approval_request.request_id, decided_by="test"
        )
        orchestrator.execute_approved(response, decision)

        assert workflow_engine.has_paused(workflow_id) is False
        assert paused_store.get(workflow_id) is None
        latest = workflow_history.latest_status_for(workflow_id)
        assert latest is not None
        assert latest.status == "workflow_stopped"

    def test_declined_terminalization_is_idempotent(self) -> None:
        """A second call (e.g. a startup repair pass finding a row a
        live decline already terminalized) is a safe no-op."""
        router, _ = _router(_compound_text(_PHASE_VALUE))
        orchestrator, *_rest, paused_store, progress_store = _build_stack(
            _in_memory_session_factory(), router
        )

        response = orchestrator.handle_request(_REQUEST)
        workflow_id = _single_workflow_id(paused_store)
        decision = orchestrator.approvals.decline(
            response.approval_request.request_id, decided_by="test"
        )
        orchestrator.execute_approved(response, decision)

        # Calling the underlying store method again directly must not
        # raise, and must leave the record unchanged.
        second = progress_store.mark_not_executed_before_start(workflow_id)
        from workflow.compound_workflow_progress_store import CompoundOverallStatus

        assert second.overall_status is CompoundOverallStatus.NOT_EXECUTED

    def test_expiry_never_executes_and_leaves_a_pristine_progress_row_live(
        self,
    ) -> None:
        """Expiry never goes through resume() at all (WorkflowEngine's
        own lazy _reap_stale_paused() silently discards the paused
        workflow) - so, unlike decline, there is no live terminalization
        hook: the progress row is left exactly PENDING/pristine at the
        moment of expiry itself. This is by design (see
        terminalize_declined_or_expired_compound_progress()'s own
        docstring) - the startup repair pass, exercised separately
        below, is the sole mechanism that ever terminalizes it."""
        from workflow.compound_workflow_progress_store import CompoundOverallStatus

        start_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
        fake_clock = _FakeClock(start_time)
        session_factory = _in_memory_session_factory()
        router, _ = _router(_compound_text(_PHASE_VALUE))
        orchestrator, project_state_store, registry, *_rest, paused_store, progress_store = (
            _build_stack(session_factory, router, timeout_seconds=60, clock=fake_clock)
        )
        write_wrapper = _CountingToolWrapper(registry.get_tool("project_state_update"))
        registry._tools["project_state_update"] = write_wrapper  # type: ignore[attr-defined]

        response = orchestrator.handle_request(_REQUEST)
        workflow_id = _single_workflow_id(paused_store)
        request_id = response.approval_request.request_id
        assert orchestrator.approvals.has_pending(request_id) is True

        fake_clock.now = start_time + timedelta(seconds=61)

        assert orchestrator.approvals.has_pending(request_id) is False
        assert write_wrapper.call_count == 0
        assert project_state_store.get() is None
        progress = progress_store.get(workflow_id)
        assert progress.overall_status is CompoundOverallStatus.PENDING

    def test_expiry_is_terminalized_by_the_repair_pass(self) -> None:
        """The startup repair pass (terminalize_declined_or_expired_compound_progress(),
        wired live into main.reconcile_claimed_handoffs() - see Section
        G) is the sole mechanism that ever marks an expired compound
        workflow's progress row NOT_EXECUTED. Exercised directly here
        against the real stores, without a full hermetic restart."""
        from workflow.compound_workflow_progress_store import CompoundOverallStatus

        start_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
        fake_clock = _FakeClock(start_time)
        session_factory = _in_memory_session_factory()
        router, _ = _router(_compound_text(_PHASE_VALUE))
        orchestrator, _, _, _, approvals, _, paused_store, progress_store = _build_stack(
            session_factory, router, timeout_seconds=60, clock=fake_clock
        )

        response = orchestrator.handle_request(_REQUEST)
        workflow_id = _single_workflow_id(paused_store)
        request_id = response.approval_request.request_id

        fake_clock.now = start_time + timedelta(seconds=61)
        assert approvals.has_pending(request_id) is False
        assert (
            approvals.handoff_status_for(request_id)
            == PendingApprovalHandoffStatus.EXPIRED
        )

        from core.compound_workflow import terminalize_declined_or_expired_compound_progress

        terminalized = terminalize_declined_or_expired_compound_progress(
            pending_store=PendingApprovalStore(session_factory),
            progress_store=progress_store,
            declined_status=PendingApprovalHandoffStatus.DECLINED,
            expired_status=PendingApprovalHandoffStatus.EXPIRED,
        )

        assert terminalized == 1
        progress = progress_store.get(workflow_id)
        assert progress.overall_status is CompoundOverallStatus.NOT_EXECUTED


# --- G. Restart and crash recovery ----------------------------------------------


@pytest.fixture()
def hermetic_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_path = tmp_path / "phase98_batch3_jarvis.db"
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
            compound_plan = _build_phase_update_verify_show_workflow_plan(
                _REQUEST,
                approved_phase_value=_PHASE_VALUE,
                tool_registry=orchestrator._registry,
                security_manager=orchestrator._security,
                session_id=None,
                catalog=CAPABILITY_CATALOG,
            )
            result = orchestrator._workflow_engine.run(compound_plan)
            assert result.overall_status.value == "waiting"
            request_id = result.pending_approval_request.request_id
            workflow_id = result.workflow_id

            established = establish_compound_progress_or_isolate(
                plan=compound_plan,
                workflow_id=workflow_id,
                request_id=request_id,
                progress_store=orchestrator._compound_progress_store,
                approval_invalidator=orchestrator.approvals,
                paused_workflow_store=orchestrator._paused_workflow_store,
            )
            assert not isinstance(established, str)

            orchestrator.approvals.approve(request_id, decided_by="test")
        finally:
            lock.release()

        # Simulate a real process restart: start_execution_session()
        # itself performs compound-first startup recovery internally
        # (build_orchestrator()'s own reload_paused()/reload_pending(),
        # then reconcile_claimed_handoffs()) - so the APPROVED_UNCONSUMED
        # row created above is continued automatically, with no
        # explicit resume call needed here at all.
        orchestrator2, lock2 = main.start_execution_session()
        try:
            assert (
                orchestrator2.approvals.handoff_status_for(request_id)
                == PendingApprovalHandoffStatus.CONSUMED
            )
            project_state_store2 = ProjectStateStore(session_factory)
            assert project_state_store2.get().phase == _PHASE_VALUE
        finally:
            lock2.release()

    def test_compound_first_ordering_resolves_recognized_row_before_generic_fallback(
        self, hermetic_db: Path
    ) -> None:
        """A CLAIMED row whose durable progress shows the write and
        verification both already durably completed (verified) before
        an assumed crash, but whose final show step never ran, must be
        safely completed and marked CONSUMED by the compound-specific
        startup pass - never left for the generic fallback to mark
        CLAIM_INTERRUPTED."""
        import main

        orchestrator, lock = main.start_execution_session()
        try:
            session_factory = _hermetic_session_factory(hermetic_db)
            project_state_store = ProjectStateStore(session_factory)
            project_state_store.update("phase", _PHASE_VALUE)

            compound_plan = _build_phase_update_verify_show_workflow_plan(
                _REQUEST,
                approved_phase_value=_PHASE_VALUE,
                tool_registry=orchestrator._registry,
                security_manager=orchestrator._security,
                session_id=None,
                catalog=CAPABILITY_CATALOG,
            )
            result = orchestrator._workflow_engine.run(compound_plan)
            request_id = result.pending_approval_request.request_id
            workflow_id = result.workflow_id

            established = establish_compound_progress_or_isolate(
                plan=compound_plan,
                workflow_id=workflow_id,
                request_id=request_id,
                progress_store=orchestrator._compound_progress_store,
                approval_invalidator=orchestrator.approvals,
                paused_workflow_store=orchestrator._paused_workflow_store,
            )
            assert not isinstance(established, str)

            orchestrator.approvals.approve(request_id, decided_by="test")
            claimed = orchestrator.approvals.claim_for_resume(request_id)
            assert claimed is True

            # Durably record that Steps 1/2 already completed (verified)
            # before the assumed crash - Step 3 (show) never ran.
            progress_store = orchestrator._compound_progress_store
            progress_store.record_pre_execution_observation(
                workflow_id, phase_value="previous phase", last_updated=None
            )
            progress_store.mark_step_1_completed(workflow_id)
            progress_store.start_step_2(workflow_id)
            from workflow.compound_workflow_progress_store import (
                CompoundVerificationOutcome,
            )

            progress_store.mark_step_2_completed(
                workflow_id, verification_outcome=CompoundVerificationOutcome.VERIFIED
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
            project_state_store2 = ProjectStateStore(session_factory)
            assert project_state_store2.get().phase == _PHASE_VALUE
        finally:
            lock2.release()

    def test_unrecognized_claimed_row_is_left_for_generic_fallback(
        self, hermetic_db: Path
    ) -> None:
        """An ordinary, non-compound CLAIMED row (a ProjectStateUpdate
        write with no linked compound progress) is completely
        unaffected by the new compound-first ordering - it still falls
        through to, and is resolved by, the existing, unchanged generic
        CLAIMED fallback."""
        import main
        from approval.pending_approval_store import PendingApprovalStore
        from workflow.workflow_history_store import WorkflowHistoryStore

        orchestrator, lock = main.start_execution_session()
        try:
            session_factory = _hermetic_session_factory(hermetic_db)
            pending_store = PendingApprovalStore(session_factory)
            workflow_history = WorkflowHistoryStore(session_factory)
            pending_store.save(
                request_id="req-noncompound-claimed",
                action="update project state phase",
                reason="needs approval",
                security_tier="yellow",
                metadata={"workflow_id": "wf-noncompound-claimed"},
                tool_name="project_state_update",
                tool_input={"field": "phase", "value": "Phase Solo"},
            )
            pending_store.mark_approved_unconsumed("req-noncompound-claimed")
            pending_store.claim_for_resume("req-noncompound-claimed")
            workflow_history.record_transition(
                workflow_id="wf-noncompound-claimed", status="workflow_completed"
            )
        finally:
            lock.release()

        orchestrator2, lock2 = main.start_execution_session()
        try:
            assert (
                orchestrator2.approvals.handoff_status_for("req-noncompound-claimed")
                == PendingApprovalHandoffStatus.CONSUMED
            )
        finally:
            lock2.release()


# --- G. Regression --------------------------------------------------------------


class TestRegression:
    def test_single_capability_phase_update_workflow_coexists_with_compound_wiring(
        self,
    ) -> None:
        """The pre-existing, single-capability "ask jarvis to: update
        my project phase to X" workflow (Phase 96) still works
        completely normally on the same orchestrator instance that also
        supports the new compound template."""
        router, _ = _router(
            json.dumps(
                {
                    "decision": "execute",
                    "capability_id": "project_state_update_phase",
                    "arguments": {"value": "Solo phase update"},
                }
            )
        )
        orchestrator, project_state_store, *_ = _build_stack(
            _in_memory_session_factory(), router
        )

        response = orchestrator.handle_request(
            "ask jarvis to: update my project phase to Solo phase update"
        )
        decision = orchestrator.approvals.approve(
            response.approval_request.request_id, decided_by="test"
        )
        final = orchestrator.execute_approved(response, decision)

        assert final.success is True
        assert project_state_store.get().phase == "Solo phase update"

    def test_ask_jarvis_advisory_remains_unaffected(self) -> None:
        """The advisory "ask jarvis:" command depends on a separate
        `reasoning_engine` collaborator this test's stack never
        constructs - its own honest "not enabled" refusal is unchanged
        by compound wiring, exactly mirroring
        test_orchestrator_update_phase_workflow.py's own equivalent
        regression test."""
        router, _ = _router(_compound_text(_PHASE_VALUE))
        orchestrator, *_rest = _build_stack(_in_memory_session_factory(), router)

        response = orchestrator.handle_request("ask jarvis: what is my focus")

        assert response.success is False
        assert "AI reasoning is not enabled" in response.message

    def test_deterministic_project_state_command_remains_unaffected(self) -> None:
        router, _ = _router(_compound_text(_PHASE_VALUE))
        orchestrator, *_rest = _build_stack(_in_memory_session_factory(), router)

        response = orchestrator.handle_request("show jarvis project state")

        assert response.success is True
        assert "Jarvis Project State" in response.message
