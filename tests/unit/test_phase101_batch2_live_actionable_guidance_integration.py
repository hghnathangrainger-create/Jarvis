"""
test_phase101_batch2_live_actionable_guidance_integration.py

Live integration tests for Phase 101, Batch 2 - Actionable Required-
Argument Guidance
(docs/phase_101_actionable_ambiguity_planning.md). Exercises the real
JarvisOrchestrator._handle_ask_jarvis_to_request() end to end: a real
CommandRouter/SecurityManager/ToolExecutor/WorkflowEngine/
ApprovalManager over real, isolated in-memory SQLite stores, and a
real AIRouter/PromptBuilder wired to a fake, in-memory AIProvider - no
live Claude API call is ever made.

Proves: the same user mistake produces identical guidance regardless
of which of the three model-dependent failure paths
(INVALID_OUTPUT/UNGROUNDED_SELECTION/UNSUPPORTED) it happens to take;
the binding independent-current-request-evidence safety rule; the
missing-versus-invalid contract; zero side effects from any actionable
response; statelessness (no bare follow-up is ever bound to a prior
incomplete request); Verified Action Context isolation; and that every
valid request and every compound request remains behaviourally
unchanged.

Run with:
    pytest tests/unit/test_phase101_batch2_live_actionable_guidance_integration.py
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

try:
    from sqlalchemy import create_engine

    from ai.prompt_builder import PromptBuilder
    from ai.providers.base import AIProvider, AIProviderError, AIRequest, AIResponse
    from ai.response_validator import ResponseValidator
    from ai.router import AIRouter
    from approval.approval_manager import ApprovalManager
    from approval.pending_approval_store import PendingApprovalStore
    from config.settings import Settings
    from core.command_router import CommandRouter
    from core.orchestrator import JarvisOrchestrator
    from intelligence.context import ContextAssembler
    from intelligence.verified_action_context import VerifiedActionContextBuilder
    from memory.episodic_memory import EpisodicMemoryStore
    from memory.memory_manager import MemoryManager
    from planner.planner import Planner
    from project_state.project_state_store import ProjectStateStore
    from scheduling.schedule_store import ScheduleStore
    from security.security_manager import SecurityManager
    from storage.database import create_session_factory, initialize_database
    from tools.builtin.memory_tool import MemoryTool
    from tools.builtin.project_state_show_tool import ProjectStateShowTool
    from tools.builtin.project_state_update_tool import ProjectStateUpdateTool
    from tools.builtin.project_state_verify_tool import ProjectStateVerifyTool
    from tools.builtin.schedule_disable_tool import ScheduleDisableTool
    from tools.builtin.schedule_enable_tool import ScheduleEnableTool
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
        ScheduleCompoundWorkflowProgressStore,
    )

    _SQLALCHEMY_AVAILABLE = True
except ImportError:
    _SQLALCHEMY_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not _SQLALCHEMY_AVAILABLE, reason="sqlalchemy not installed"
)


# --------------------------------------------------------------------------
# Test doubles and fixtures
# --------------------------------------------------------------------------


class _RecordingLogger:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def emit(self, **kwargs: object) -> str:
        self.calls.append(kwargs)
        return str(len(self.calls))


class _FakeAIProvider(AIProvider):
    def __init__(self, text: str, *, fail: bool = False) -> None:
        self._text = text
        self._fail = fail
        self.received_requests: list[AIRequest] = []

    @property
    def name(self) -> str:
        return "fake"

    def generate(self, request: AIRequest) -> AIResponse:
        self.received_requests.append(request)
        if self._fail:
            raise AIProviderError("simulated provider failure")
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


def _router(text: str) -> tuple[AIRouter, _FakeAIProvider, _RecordingLogger]:
    logger = _RecordingLogger()
    provider = _FakeAIProvider(text)
    router = AIRouter(
        provider=provider,
        prompt_builder=PromptBuilder(),
        validator=ResponseValidator(),
        logger=logger,  # type: ignore[arg-type]
        settings=_settings(),
    )
    return router, provider, logger


def _in_memory_session_factory():
    engine = create_engine("sqlite:///:memory:")
    initialize_database(engine)
    return create_session_factory(engine)


class _Stack:
    def __init__(
        self,
        orchestrator: JarvisOrchestrator,
        schedule_store: ScheduleStore,
        project_state_store: ProjectStateStore,
        pending_store: PendingApprovalStore,
        paused_store: PausedWorkflowStore,
        compound_progress_store: CompoundWorkflowProgressStore,
        schedule_compound_progress_store: ScheduleCompoundWorkflowProgressStore,
    ) -> None:
        self.orchestrator = orchestrator
        self.schedule_store = schedule_store
        self.project_state_store = project_state_store
        self.pending_store = pending_store
        self.paused_store = paused_store
        self.compound_progress_store = compound_progress_store
        self.schedule_compound_progress_store = schedule_compound_progress_store

    def assert_zero_side_effects(self) -> None:
        assert self.pending_store.list_all() == []
        assert self.paused_store.list_all() == []
        assert self.compound_progress_store.list_all() == []
        assert self.schedule_compound_progress_store.list_all() == []


def _build_stack(
    router: AIRouter, *, verified_action_context: bool = False
) -> _Stack:
    session_factory = _in_memory_session_factory()
    memory = MemoryManager(EpisodicMemoryStore(session_factory))
    project_state_store = ProjectStateStore(session_factory)
    schedule_store = ScheduleStore(session_factory)

    compound_progress_store = CompoundWorkflowProgressStore(session_factory)
    schedule_compound_progress_store = ScheduleCompoundWorkflowProgressStore(
        session_factory
    )
    pending_store = PendingApprovalStore(session_factory)

    verified_action_context_builder = (
        VerifiedActionContextBuilder(
            project_state_progress_store=compound_progress_store,
            schedule_progress_store=schedule_compound_progress_store,
            pending_approval_store=pending_store,
        )
        if verified_action_context
        else None
    )
    context_assembler = ContextAssembler(
        memory_manager=memory,
        project_state_store=project_state_store,
        verified_action_context_builder=verified_action_context_builder,
    )

    security = SecurityManager()
    registry = ToolRegistry()
    registry.register_tool(ScheduleEnableTool(schedule_store))
    registry.register_tool(ScheduleDisableTool(schedule_store))
    registry.register_tool(ScheduleShowEnabledStateTool(schedule_store))
    registry.register_tool(ScheduleVerifyEnabledStateTool(schedule_store))
    registry.register_tool(MemoryTool(memory))
    registry.register_tool(ProjectStateShowTool(project_state_store))
    registry.register_tool(ProjectStateUpdateTool(project_state_store))
    registry.register_tool(ProjectStateVerifyTool(project_state_store))

    logger = _RecordingLogger()
    executor = ToolExecutor(
        registry=registry, security_manager=security, logger=logger  # type: ignore[arg-type]
    )
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
        paused_workflow_store=paused_store,
        compound_progress_store=compound_progress_store,
        schedule_compound_progress_store=schedule_compound_progress_store,
    )
    return _Stack(
        orchestrator,
        schedule_store,
        project_state_store,
        pending_store,
        paused_store,
        compound_progress_store,
        schedule_compound_progress_store,
    )


def _ask_jarvis_to(orchestrator: JarvisOrchestrator, request: str):
    return orchestrator.handle_request(f"ask jarvis to: {request}")


# --------------------------------------------------------------------------
# Exact expected live messages
# --------------------------------------------------------------------------

_SCHEDULE_ENABLE_MISSING = (
    "I need the schedule ID before I can prepare this action. "
    "Try: ask jarvis to: enable schedule <schedule id>. "
    "Enabling a schedule will still require approval."
)
_SCHEDULE_ENABLE_INVALID = (
    "The schedule ID must be a whole number. "
    "Try: ask jarvis to: enable schedule <schedule id>. "
    "Enabling a schedule will still require approval."
)
_SCHEDULE_DISABLE_MISSING = (
    "I need the schedule ID before I can prepare this action. "
    "Try: ask jarvis to: disable schedule <schedule id>. "
    "Disabling a schedule will still require approval."
)
_SCHEDULE_SHOW_MISSING = (
    "I need the schedule ID before I can prepare this action. "
    "Try: ask jarvis to: check the enabled state of schedule <schedule id>."
)
_MEMORY_SEARCH_MISSING = (
    "I need the search text before I can prepare this action. "
    "Try: ask jarvis to: search memories for <search text>."
)
_PROJECT_STATE_PHASE_MISSING = (
    "I need the phase value before I can prepare this action. "
    "Try: ask jarvis to: update my project phase to <phase value>. "
    "Updating the project phase will still require approval."
)


# --------------------------------------------------------------------------
# A. Same mistake through three model outcomes
# --------------------------------------------------------------------------


class TestSameMistakeThroughThreeModelOutcomes:
    def test_schedule_enable_missing_id_via_missing_argument_parse_output(self) -> None:
        router, _, _ = _router(
            json.dumps(
                {"decision": "execute", "capability_id": "schedule_enable", "arguments": {}}
            )
        )
        stack = _build_stack(router)
        response = _ask_jarvis_to(stack.orchestrator, "enable schedule")
        assert response.message == _SCHEDULE_ENABLE_MISSING

    def test_schedule_enable_missing_id_via_hallucinated_argument_rejected(self) -> None:
        router, _, _ = _router(
            json.dumps(
                {
                    "decision": "execute",
                    "capability_id": "schedule_enable",
                    "arguments": {"schedule_id": 999},
                }
            )
        )
        stack = _build_stack(router)
        response = _ask_jarvis_to(stack.orchestrator, "enable schedule")
        assert response.message == _SCHEDULE_ENABLE_MISSING

    def test_schedule_enable_missing_id_via_unsupported_decision(self) -> None:
        router, _, _ = _router(
            json.dumps({"decision": "unsupported", "capability_id": None, "arguments": {}})
        )
        stack = _build_stack(router)
        response = _ask_jarvis_to(stack.orchestrator, "enable schedule")
        assert response.message == _SCHEDULE_ENABLE_MISSING

    def test_memory_search_missing_text_via_missing_argument_parse_output(self) -> None:
        router, _, _ = _router(
            json.dumps(
                {"decision": "execute", "capability_id": "memory_search", "arguments": {}}
            )
        )
        stack = _build_stack(router)
        response = _ask_jarvis_to(stack.orchestrator, "search memories for")
        assert response.message == _MEMORY_SEARCH_MISSING

    def test_memory_search_missing_text_via_hallucinated_argument_rejected(self) -> None:
        router, _, _ = _router(
            json.dumps(
                {
                    "decision": "execute",
                    "capability_id": "memory_search",
                    "arguments": {"value": "budget"},
                }
            )
        )
        stack = _build_stack(router)
        response = _ask_jarvis_to(stack.orchestrator, "search memories for")
        assert response.message == _MEMORY_SEARCH_MISSING

    def test_memory_search_missing_text_via_unsupported_decision(self) -> None:
        router, _, _ = _router(
            json.dumps({"decision": "unsupported", "capability_id": None, "arguments": {}})
        )
        stack = _build_stack(router)
        response = _ask_jarvis_to(stack.orchestrator, "search memories for")
        assert response.message == _MEMORY_SEARCH_MISSING


# --------------------------------------------------------------------------
# B. All five capabilities
# --------------------------------------------------------------------------


class TestAllFiveCapabilitiesLive:
    def test_schedule_enable(self) -> None:
        router, _, _ = _router(
            json.dumps({"decision": "unsupported", "capability_id": None, "arguments": {}})
        )
        stack = _build_stack(router)
        response = _ask_jarvis_to(stack.orchestrator, "enable schedule")
        assert response.message == _SCHEDULE_ENABLE_MISSING

    def test_schedule_disable(self) -> None:
        router, _, _ = _router(
            json.dumps({"decision": "unsupported", "capability_id": None, "arguments": {}})
        )
        stack = _build_stack(router)
        response = _ask_jarvis_to(stack.orchestrator, "disable schedule")
        assert response.message == _SCHEDULE_DISABLE_MISSING

    def test_schedule_show_enabled_state(self) -> None:
        router, _, _ = _router(
            json.dumps({"decision": "unsupported", "capability_id": None, "arguments": {}})
        )
        stack = _build_stack(router)
        response = _ask_jarvis_to(stack.orchestrator, "check the enabled state of schedule")
        assert response.message == _SCHEDULE_SHOW_MISSING

    def test_memory_search(self) -> None:
        router, _, _ = _router(
            json.dumps({"decision": "unsupported", "capability_id": None, "arguments": {}})
        )
        stack = _build_stack(router)
        response = _ask_jarvis_to(stack.orchestrator, "search memories for")
        assert response.message == _MEMORY_SEARCH_MISSING

    def test_project_state_update_phase(self) -> None:
        router, _, _ = _router(
            json.dumps({"decision": "unsupported", "capability_id": None, "arguments": {}})
        )
        stack = _build_stack(router)
        response = _ask_jarvis_to(stack.orchestrator, "update my project phase to")
        assert response.message == _PROJECT_STATE_PHASE_MISSING


# --------------------------------------------------------------------------
# C. Integer invalid format
# --------------------------------------------------------------------------


class TestIntegerInvalidFormatLive:
    def test_word_number(self) -> None:
        router, _, _ = _router(
            json.dumps({"decision": "unsupported", "capability_id": None, "arguments": {}})
        )
        stack = _build_stack(router)
        response = _ask_jarvis_to(stack.orchestrator, "enable schedule twelve")
        assert response.message == _SCHEDULE_ENABLE_INVALID

    def test_decimal(self) -> None:
        router, _, _ = _router(
            json.dumps({"decision": "unsupported", "capability_id": None, "arguments": {}})
        )
        stack = _build_stack(router)
        response = _ask_jarvis_to(stack.orchestrator, "disable schedule 4.5")
        assert response.message == _SCHEDULE_DISABLE_MISSING.replace(
            "I need the schedule ID before I can prepare this action.",
            "The schedule ID must be a whole number.",
        )

    def test_negative(self) -> None:
        router, _, _ = _router(
            json.dumps({"decision": "unsupported", "capability_id": None, "arguments": {}})
        )
        stack = _build_stack(router)
        response = _ask_jarvis_to(
            stack.orchestrator, "check the enabled state of schedule -5"
        )
        assert response.message == _SCHEDULE_SHOW_MISSING.replace(
            "I need the schedule ID before I can prepare this action.",
            "The schedule ID must be a whole number.",
        )

    def test_mixed_malformed_span(self) -> None:
        router, _, _ = _router(
            json.dumps({"decision": "unsupported", "capability_id": None, "arguments": {}})
        )
        stack = _build_stack(router)
        response = _ask_jarvis_to(stack.orchestrator, "enable schedule abc")
        assert response.message == _SCHEDULE_ENABLE_INVALID


# --------------------------------------------------------------------------
# D. Safety
# --------------------------------------------------------------------------


class TestSafetyLive:
    def test_negation_gets_generic_message(self) -> None:
        router, _, _ = _router(
            json.dumps({"decision": "unsupported", "capability_id": None, "arguments": {}})
        )
        stack = _build_stack(router)
        response = _ask_jarvis_to(stack.orchestrator, "do not enable schedule")
        assert response.message != _SCHEDULE_ENABLE_MISSING
        assert "<schedule id>" not in response.message

    def test_conflict_gets_generic_message(self) -> None:
        router, _, _ = _router(
            json.dumps({"decision": "unsupported", "capability_id": None, "arguments": {}})
        )
        stack = _build_stack(router)
        response = _ask_jarvis_to(stack.orchestrator, "enable and disable schedule 5")
        assert "<schedule id>" not in response.message

    def test_ambiguity_gets_generic_message(self) -> None:
        router, _, _ = _router(
            json.dumps({"decision": "unsupported", "capability_id": None, "arguments": {}})
        )
        stack = _build_stack(router)
        response = _ask_jarvis_to(
            stack.orchestrator, "enable schedule and disable schedule"
        )
        assert "<schedule id>" not in response.message

    def test_vague_wording_gets_generic_message(self) -> None:
        router, _, _ = _router(
            json.dumps({"decision": "unsupported", "capability_id": None, "arguments": {}})
        )
        stack = _build_stack(router)
        response = _ask_jarvis_to(stack.orchestrator, "do something with my schedules")
        assert response.message == (
            "Jarvis could not find an allowlisted capability that can "
            "safely complete that request."
        )

    def test_model_request_disagreement_gets_generic_invalid_output_message(self) -> None:
        # Model claims schedule_enable, but the current request text
        # names memory_search's own action - grounding/probing must
        # never let the model's own claim substitute for independent
        # evidence.
        router, _, _ = _router(
            json.dumps(
                {"decision": "execute", "capability_id": "schedule_enable", "arguments": {}}
            )
        )
        stack = _build_stack(router)
        response = _ask_jarvis_to(stack.orchestrator, "search memories for")
        assert "<schedule id>" not in response.message
        assert "<search text>" not in response.message

    def test_non_allowlisted_capability_gets_generic_message(self) -> None:
        router, _, _ = _router(
            json.dumps({"decision": "unsupported", "capability_id": None, "arguments": {}})
        )
        stack = _build_stack(router)
        response = _ask_jarvis_to(stack.orchestrator, "show my project state")
        assert response.message == (
            "Jarvis could not find an allowlisted capability that can "
            "safely complete that request."
        )

    def test_compound_request_gets_generic_message(self) -> None:
        router, _, _ = _router(
            json.dumps({"decision": "unsupported", "capability_id": None, "arguments": {}})
        )
        stack = _build_stack(router)
        response = _ask_jarvis_to(
            stack.orchestrator,
            "enable schedule and then check the enabled state of schedule",
        )
        assert "<schedule id>" not in response.message

    def test_malformed_provider_output_gets_generic_message(self) -> None:
        router, _, _ = _router("not even json{{{")
        stack = _build_stack(router)
        response = _ask_jarvis_to(stack.orchestrator, "enable schedule")
        assert response.success is False
        assert "<schedule id>" not in response.message
        assert "not even json" not in response.message

    def test_internal_provider_failure_gets_generic_message(self) -> None:
        logger = _RecordingLogger()
        provider = _FakeAIProvider("", fail=True)
        router = AIRouter(
            provider=provider,
            prompt_builder=PromptBuilder(),
            validator=ResponseValidator(),
            logger=logger,  # type: ignore[arg-type]
            settings=_settings(),
        )
        stack = _build_stack(router)
        response = _ask_jarvis_to(stack.orchestrator, "enable schedule")
        assert "<schedule id>" not in response.message


# --------------------------------------------------------------------------
# E. Side effects
# --------------------------------------------------------------------------


class TestZeroSideEffects:
    @pytest.mark.parametrize(
        "request_text",
        [
            "enable schedule",
            "disable schedule",
            "check the enabled state of schedule",
            "search memories for",
            "update my project phase to",
            "enable schedule twelve",
        ],
    )
    def test_actionable_response_creates_no_durable_state(self, request_text) -> None:
        router, _, _ = _router(
            json.dumps({"decision": "unsupported", "capability_id": None, "arguments": {}})
        )
        stack = _build_stack(router)
        response = _ask_jarvis_to(stack.orchestrator, request_text)
        assert "<" in response.message  # confirms guidance was actually rendered
        stack.assert_zero_side_effects()

    def test_no_tool_call_log_event(self) -> None:
        router, _, logger = _router(
            json.dumps({"decision": "unsupported", "capability_id": None, "arguments": {}})
        )
        stack = _build_stack(router)
        _ask_jarvis_to(stack.orchestrator, "enable schedule")
        tool_calls = [c for c in logger.calls if c.get("action_type") == "tool_call"]
        assert tool_calls == []


# --------------------------------------------------------------------------
# F. Stateless retry
# --------------------------------------------------------------------------


class TestStatelessRetry:
    def test_first_incomplete_request_returns_guidance(self) -> None:
        router, _, _ = _router(
            json.dumps({"decision": "unsupported", "capability_id": None, "arguments": {}})
        )
        stack = _build_stack(router)
        response = _ask_jarvis_to(stack.orchestrator, "enable schedule")
        assert response.message == _SCHEDULE_ENABLE_MISSING

    def test_later_bare_number_is_not_bound_to_the_first_request(self) -> None:
        router, provider, _ = _router(
            json.dumps({"decision": "unsupported", "capability_id": None, "arguments": {}})
        )
        stack = _build_stack(router)
        _ask_jarvis_to(stack.orchestrator, "enable schedule")
        stack.assert_zero_side_effects()

        # A later, independent request of just "12" - the fake provider
        # still returns the same fixed "unsupported" text (a real
        # model would see no matching signature either); the key proof
        # is that nothing in the pipeline treats this as completing
        # the prior request - no schedule is enabled, no approval
        # exists, and the response is never phrased as confirming or
        # continuing anything.
        response = _ask_jarvis_to(stack.orchestrator, "12")
        assert "enable" not in response.message.lower()
        stack.assert_zero_side_effects()

    def test_later_complete_request_follows_the_ordinary_pipeline(self) -> None:
        router, _, _ = _router("")  # placeholder, replaced per-call below
        stack = _build_stack(router)
        record = stack.schedule_store.create(query="q", time_of_day="09:00")

        complete_router, _, _ = _router(
            json.dumps(
                {
                    "decision": "execute",
                    "capability_id": "schedule_enable",
                    "arguments": {"schedule_id": record.id},
                }
            )
        )
        stack.orchestrator._tool_selection_router = complete_router  # type: ignore[attr-defined]
        response = _ask_jarvis_to(
            stack.orchestrator, f"enable schedule {record.id}"
        )
        # A complete, valid, grounded YELLOW request reaches the
        # ordinary approval-gated workflow path - never actionable
        # guidance.
        assert "<schedule id>" not in response.message
        assert stack.pending_store.list_all() != []


# --------------------------------------------------------------------------
# G. Context isolation
# --------------------------------------------------------------------------


class TestContextIsolationLive:
    def test_historical_schedule_id_never_appears_in_live_guidance(self) -> None:
        router, _, _ = _router(
            json.dumps({"decision": "unsupported", "capability_id": None, "arguments": {}})
        )
        stack = _build_stack(router, verified_action_context=True)

        # Create verified historical evidence for schedule 12.
        workflow_id = "wf-historical"
        request_id = "req-historical"
        stack.pending_store.save(
            request_id=request_id,
            action="enable schedule",
            reason="Enabling a schedule creates new state.",
            security_tier="yellow",
            tool_name="schedule_enable",
            tool_input={"schedule_id": 12},
        )
        stack.schedule_compound_progress_store.create(
            workflow_id=workflow_id,
            template_id="schedule_enable_then_show_enabled_state",
            request_id=request_id,
            schedule_id=12,
        )
        stack.schedule_compound_progress_store.record_pre_execution_observation(
            workflow_id, enabled=False
        )
        stack.schedule_compound_progress_store.mark_step_1_completed(workflow_id)
        stack.schedule_compound_progress_store.start_step_2(workflow_id)
        from workflow.schedule_compound_workflow_progress_store import (
            ScheduleCompoundVerificationOutcome,
        )

        stack.schedule_compound_progress_store.mark_step_2_completed(
            workflow_id, verification_outcome=ScheduleCompoundVerificationOutcome.VERIFIED
        )
        stack.schedule_compound_progress_store.start_step_3(workflow_id)
        stack.schedule_compound_progress_store.mark_step_3_completed(workflow_id)

        response = _ask_jarvis_to(stack.orchestrator, "enable schedule")
        assert response.message == _SCHEDULE_ENABLE_MISSING
        assert "12" not in response.message

    def test_historical_project_state_phase_never_fills_placeholder(self) -> None:
        router, _, _ = _router(
            json.dumps({"decision": "unsupported", "capability_id": None, "arguments": {}})
        )
        stack = _build_stack(router, verified_action_context=True)

        workflow_id = "wf-ps-historical"
        request_id = "req-ps-historical"
        stack.pending_store.save(
            request_id=request_id,
            action="update project phase",
            reason="Updating project phase creates new state.",
            security_tier="yellow",
            tool_name="project_state_update",
            tool_input={"phase": "Phase 100"},
        )
        stack.compound_progress_store.create(
            workflow_id=workflow_id,
            template_id="project_state_update_phase_then_show",
            request_id=request_id,
            approved_phase_value="Phase 100",
        )
        stack.compound_progress_store.record_pre_execution_observation(
            workflow_id, phase_value="old", last_updated=None
        )
        stack.compound_progress_store.mark_step_1_completed(workflow_id)
        stack.compound_progress_store.start_step_2(workflow_id)
        from workflow.compound_workflow_progress_store import CompoundVerificationOutcome

        stack.compound_progress_store.mark_step_2_completed(
            workflow_id, verification_outcome=CompoundVerificationOutcome.VERIFIED
        )
        stack.compound_progress_store.start_step_3(workflow_id)
        stack.compound_progress_store.mark_step_3_completed(workflow_id)

        response = _ask_jarvis_to(stack.orchestrator, "update my project phase to")
        assert response.message == _PROJECT_STATE_PHASE_MISSING
        assert "Phase 100" not in response.message


# --------------------------------------------------------------------------
# H. Formatter (exact live message / approval policy / determinism)
# --------------------------------------------------------------------------


class TestFormatterLive:
    def test_green_capability_has_no_approval_clause_live(self) -> None:
        router, _, _ = _router(
            json.dumps({"decision": "unsupported", "capability_id": None, "arguments": {}})
        )
        stack = _build_stack(router)
        response = _ask_jarvis_to(stack.orchestrator, "search memories for")
        assert "approval" not in response.message.lower()

    def test_yellow_capability_has_approval_clause_live(self) -> None:
        router, _, _ = _router(
            json.dumps({"decision": "unsupported", "capability_id": None, "arguments": {}})
        )
        stack = _build_stack(router)
        response = _ask_jarvis_to(stack.orchestrator, "enable schedule")
        assert "still require approval" in response.message

    def test_deterministic_repeated_live_response(self) -> None:
        router1, _, _ = _router(
            json.dumps({"decision": "unsupported", "capability_id": None, "arguments": {}})
        )
        router2, _, _ = _router(
            json.dumps({"decision": "unsupported", "capability_id": None, "arguments": {}})
        )
        stack1 = _build_stack(router1)
        stack2 = _build_stack(router2)
        response1 = _ask_jarvis_to(stack1.orchestrator, "enable schedule")
        response2 = _ask_jarvis_to(stack2.orchestrator, "enable schedule")
        assert response1.message == response2.message


# --------------------------------------------------------------------------
# I. Valid single-capability regression
# --------------------------------------------------------------------------


class TestValidRequestsUnchanged:
    def test_enable_schedule_valid(self) -> None:
        router, _, _ = _router("")
        stack = _build_stack(router)
        record = stack.schedule_store.create(query="q", time_of_day="09:00")
        valid_router, _, _ = _router(
            json.dumps(
                {
                    "decision": "execute",
                    "capability_id": "schedule_enable",
                    "arguments": {"schedule_id": record.id},
                }
            )
        )
        stack.orchestrator._tool_selection_router = valid_router  # type: ignore[attr-defined]
        response = _ask_jarvis_to(stack.orchestrator, f"enable schedule {record.id}")
        # A valid, grounded YELLOW request reaches the existing,
        # unchanged awaiting-approval response (success=False here is
        # this workflow's own pre-existing convention, not a Phase 101
        # error) - never actionable guidance.
        assert "Confirmation required" in response.message
        assert "<schedule id>" not in response.message
        assert stack.pending_store.list_all() != []

    def test_disable_schedule_valid(self) -> None:
        router, _, _ = _router("")
        stack = _build_stack(router)
        record = stack.schedule_store.create(query="q", time_of_day="09:00")
        valid_router, _, _ = _router(
            json.dumps(
                {
                    "decision": "execute",
                    "capability_id": "schedule_disable",
                    "arguments": {"schedule_id": record.id},
                }
            )
        )
        stack.orchestrator._tool_selection_router = valid_router  # type: ignore[attr-defined]
        response = _ask_jarvis_to(stack.orchestrator, f"disable schedule {record.id}")
        assert "Confirmation required" in response.message
        assert "<schedule id>" not in response.message
        assert stack.pending_store.list_all() != []

    def test_schedule_show_enabled_state_valid(self) -> None:
        router, _, _ = _router("")
        stack = _build_stack(router)
        record = stack.schedule_store.create(query="q", time_of_day="09:00")
        valid_router, _, _ = _router(
            json.dumps(
                {
                    "decision": "execute",
                    "capability_id": "schedule_show_enabled_state",
                    "arguments": {"schedule_id": record.id},
                }
            )
        )
        stack.orchestrator._tool_selection_router = valid_router  # type: ignore[attr-defined]
        response = _ask_jarvis_to(
            stack.orchestrator, f"check the enabled state of schedule {record.id}"
        )
        assert response.success is True
        assert "<schedule id>" not in response.message

    def test_memory_search_valid(self) -> None:
        router, _, _ = _router(
            json.dumps(
                {
                    "decision": "execute",
                    "capability_id": "memory_search",
                    "arguments": {"value": "jarvis"},
                }
            )
        )
        stack = _build_stack(router)
        response = _ask_jarvis_to(stack.orchestrator, "search memories for jarvis")
        assert response.success is True
        assert "<search text>" not in response.message

    def test_update_project_phase_valid(self) -> None:
        router, _, _ = _router(
            json.dumps(
                {
                    "decision": "execute",
                    "capability_id": "project_state_update_phase",
                    "arguments": {"value": "Phase 101"},
                }
            )
        )
        stack = _build_stack(router)
        response = _ask_jarvis_to(
            stack.orchestrator, "update my project phase to Phase 101"
        )
        assert response.success is False  # awaiting approval, not yet an error
        assert "<phase value>" not in response.message
        assert stack.pending_store.list_all() != []


# --------------------------------------------------------------------------
# J. Compound regression
# --------------------------------------------------------------------------


class TestCompoundRegressionUnchanged:
    def test_schedule_compound_missing_ids_gets_no_actionable_guidance(self) -> None:
        router, _, _ = _router(
            json.dumps({"decision": "unsupported", "capability_id": None, "arguments": {}})
        )
        stack = _build_stack(router)
        response = _ask_jarvis_to(
            stack.orchestrator,
            "enable schedule and then check the enabled state of schedule",
        )
        assert "<schedule id>" not in response.message

    def test_schedule_compound_different_ids_unchanged(self) -> None:
        router, _, _ = _router(
            json.dumps(
                {
                    "decision": "execute_sequence",
                    "steps": [
                        {
                            "capability_id": "schedule_enable",
                            "arguments": {"schedule_id": 5},
                        },
                        {
                            "capability_id": "schedule_show_enabled_state",
                            "arguments": {"schedule_id": 6},
                        },
                    ],
                }
            )
        )
        stack = _build_stack(router)
        response = _ask_jarvis_to(
            stack.orchestrator,
            "enable schedule 5 and then check the enabled state of schedule 6",
        )
        assert "<schedule id>" not in response.message
        stack.assert_zero_side_effects()

    def test_project_state_compound_valid_unchanged(self) -> None:
        router, _, _ = _router(
            json.dumps(
                {
                    "decision": "execute_sequence",
                    "steps": [
                        {
                            "capability_id": "project_state_update_phase",
                            "arguments": {"value": "Phase 101"},
                        },
                        {"capability_id": "project_state_show", "arguments": {}},
                    ],
                }
            )
        )
        stack = _build_stack(router)
        response = _ask_jarvis_to(
            stack.orchestrator,
            "update my project phase to Phase 101 and then show my project state",
        )
        assert "<phase value>" not in response.message
        assert stack.pending_store.list_all() != []
