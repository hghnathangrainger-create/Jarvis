"""
test_orchestrator_ask_jarvis_to.py

Unit tests for the explicit "ask jarvis to: <request>" tool-selection
workflow (Phase 90, Batch 2):
CommandRouter.match_ask_jarvis_to() ->
JarvisOrchestrator._handle_ask_jarvis_to_request().

Mirrors tests/unit/test_orchestrator_context_query.py's own
established shape: real Planner, SecurityManager, CommandRouter,
MemoryManager (over a real in-memory SQLite EpisodicMemoryStore), real
ProjectStateStore, real ContextAssembler, a real ToolExecutor/
ToolRegistry, and a real AIRouter wired to a real PromptBuilder and a
fake, in-memory AIProvider - no live Claude API call is ever made, no
real network call is ever made.

sqlalchemy-dependent imports are guarded by a try/except ImportError,
mirroring test_orchestrator_context_query.py's own established pattern,
so this file collects cleanly under Ruff's default rule set.

Run with:
    pytest tests/unit/test_orchestrator_ask_jarvis_to.py
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
    from ai.providers.base import AIProvider, AIProviderError, AIRequest, AIResponse
    from ai.response_validator import ResponseValidator
    from ai.router import AIRouter
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
    from tools.base_tool import BaseTool, ToolRequest, ToolResult
    from tools.builtin.project_state_show_tool import ProjectStateShowTool
    from tools.executor import ToolExecutor
    from tools.registry import ToolRegistry

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
    def __init__(self, text: str, *, available: bool = True, fail: bool = False) -> None:
        self._text = text
        self._available = available
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
        return self._available


class _DivergingTool(BaseTool):
    """Registered under the real "project_state_show" name: classifies
    GREEN on its first action_for() call (the preflight) and YELLOW on
    every subsequent call (real execution) - a genuine, self-contained
    way to exercise execution-time classification divergence without
    patching any module-level state."""

    def __init__(self) -> None:
        self._calls = 0

    @property
    def name(self) -> str:
        return "project_state_show"

    @property
    def description(self) -> str:
        return "test double for execution-time divergence"

    def action_for(self, request: ToolRequest) -> str:
        self._calls += 1
        if self._calls == 1:
            return "show jarvis project state"
        return "delete file something.txt"

    def run(self, request: ToolRequest) -> ToolResult:
        return self.ok("should never actually run")


class _AlwaysBlockedDivergingTool(BaseTool):
    """Same idea as _DivergingTool, but diverges to a RED action on its
    second call, forcing an execution-time block instead of a
    confirmation-required withholding."""

    def __init__(self) -> None:
        self._calls = 0

    @property
    def name(self) -> str:
        return "project_state_show"

    @property
    def description(self) -> str:
        return "test double for execution-time RED divergence"

    def action_for(self, request: ToolRequest) -> str:
        self._calls += 1
        if self._calls == 1:
            return "show jarvis project state"
        return "forget all memories"

    def run(self, request: ToolRequest) -> ToolResult:
        return self.ok("should never actually run")


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


def _router(
    text: str = "", *, available: bool = True, fail: bool = False
) -> tuple[AIRouter, _FakeAIProvider, _RecordingLogger]:
    logger = _RecordingLogger()
    provider = _FakeAIProvider(text, available=available, fail=fail)
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


def _build_real_orchestrator(
    tool_selection_router: AIRouter | None,
    logger: _RecordingLogger,
    *,
    with_context_assembler: bool = True,
    registry: ToolRegistry | None = None,
) -> tuple[JarvisOrchestrator, MemoryManager, ProjectStateStore, ToolRegistry]:
    session_factory = _in_memory_session_factory()
    memory = MemoryManager(EpisodicMemoryStore(session_factory))
    project_state_store = ProjectStateStore(session_factory)
    context_assembler = (
        ContextAssembler(
            memory_manager=memory, project_state_store=project_state_store
        )
        if with_context_assembler
        else None
    )

    security = SecurityManager()
    if registry is None:
        registry = ToolRegistry()
        registry.register_tool(ProjectStateShowTool(project_state_store))
    executor = ToolExecutor(
        registry=registry, security_manager=security, logger=logger  # type: ignore[arg-type]
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
        tool_selection_router=tool_selection_router,
    )
    return orchestrator, memory, project_state_store, registry


def _tool_call_events(logger: _RecordingLogger) -> list[dict[str, object]]:
    return [call for call in logger.calls if call.get("action_type") == "tool_call"]


_EXECUTE_TEXT = json.dumps(
    {"decision": "execute", "capability_id": "project_state_show", "arguments": {}}
)
_UNSUPPORTED_TEXT = json.dumps(
    {"decision": "unsupported", "capability_id": None, "arguments": {}}
)
_HEALTH_CHECK_EXECUTE_TEXT = json.dumps(
    {"decision": "execute", "capability_id": "health_check", "arguments": {}}
)
_SCHEDULE_LIST_EXECUTE_TEXT = json.dumps(
    {"decision": "execute", "capability_id": "schedule_list", "arguments": {}}
)
_MEMORY_LIST_RECENT_EXECUTE_TEXT = json.dumps(
    {"decision": "execute", "capability_id": "memory_list_recent", "arguments": {}}
)


# --- Phase 91, Batch 1: zero-argument GREEN read-only capabilities ---------------


def _build_real_orchestrator_with_phase_91_batch_1_tools(
    tool_selection_router: AIRouter | None, logger: _RecordingLogger
) -> tuple[JarvisOrchestrator, MemoryManager, ScheduleStore]:
    """Builds a real orchestrator wired with the real, production
    HealthCheckTool, ScheduleListTool, and MemoryTool - each backed by
    real, isolated in-memory SQLite stores (never a mock/fake store),
    the same shape main.py's own build_orchestrator() uses. Every
    capability's execution here goes through the exact same real
    ToolExecutor/SecurityManager path as any other tool call."""
    from approval.approval_history_store import ApprovalHistoryStore
    from inbox.inbox_store import InboxStore
    from quarantine.quarantine_store import QuarantineStore
    from tools.builtin.health_check_tool import HealthCheckTool
    from tools.builtin.memory_tool import MemoryTool
    from tools.builtin.schedule_list_tool import ScheduleListTool
    from workflow.workflow_history_store import WorkflowHistoryStore

    session_factory = _in_memory_session_factory()
    memory = MemoryManager(EpisodicMemoryStore(session_factory))
    project_state_store = ProjectStateStore(session_factory)
    schedule_store = ScheduleStore(session_factory)
    inbox_store = InboxStore(session_factory)
    quarantine_store = QuarantineStore(session_factory)
    approval_history = ApprovalHistoryStore(session_factory)
    workflow_history = WorkflowHistoryStore(session_factory)

    context_assembler = ContextAssembler(
        memory_manager=memory, project_state_store=project_state_store
    )
    security = SecurityManager()

    registry = ToolRegistry()
    registry.register_tool(ProjectStateShowTool(project_state_store))
    registry.register_tool(ScheduleListTool(schedule_store))
    registry.register_tool(MemoryTool(memory))
    registry.register_tool(
        HealthCheckTool(
            registry=registry,
            settings=_settings(),
            inbox_store=inbox_store,
            schedule_store=schedule_store,
            quarantine_store=quarantine_store,
            security_manager=security,
            memory_manager=memory,
            approval_history_store=approval_history,
            workflow_history_store=workflow_history,
        )
    )

    executor = ToolExecutor(
        registry=registry, security_manager=security, logger=logger  # type: ignore[arg-type]
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
        tool_selection_router=tool_selection_router,
    )
    return orchestrator, memory, schedule_store


def test_health_check_executes_through_real_tool_executor_and_grounds_response() -> None:
    router, provider, logger = _router(_HEALTH_CHECK_EXECUTE_TEXT)
    orchestrator, _, _ = _build_real_orchestrator_with_phase_91_batch_1_tools(
        router, logger
    )

    response = orchestrator.handle_request("ask jarvis to: check jarvis's health")

    assert response.success is True
    assert response.message.startswith("[Jarvis tool result]")
    assert "Jarvis health check:" in response.message
    assert response.tool_result is not None
    assert response.tool_result.tool_name == "health_check"
    assert response.tool_result.success is True
    assert len(provider.received_requests) == 1
    assert len(_tool_call_events(logger)) == 1


def test_schedule_list_executes_through_real_tool_executor_and_grounds_response() -> None:
    router, provider, logger = _router(_SCHEDULE_LIST_EXECUTE_TEXT)
    orchestrator, _, schedule_store = _build_real_orchestrator_with_phase_91_batch_1_tools(
        router, logger
    )
    schedule_store.create(query="jarvis phase 91 news", time_of_day="09:00", name="daily digest")

    response = orchestrator.handle_request("ask jarvis to: show my schedules")

    assert response.success is True
    assert response.message.startswith("[Jarvis tool result]")
    assert "jarvis phase 91 news" in response.message
    assert "daily digest" in response.message
    assert response.tool_result is not None
    assert response.tool_result.tool_name == "schedule_list"
    assert len(provider.received_requests) == 1
    assert len(_tool_call_events(logger)) == 1


def test_memory_list_recent_executes_through_real_tool_executor_and_grounds_response() -> None:
    router, provider, logger = _router(_MEMORY_LIST_RECENT_EXECUTE_TEXT)
    orchestrator, memory, _ = _build_real_orchestrator_with_phase_91_batch_1_tools(
        router, logger
    )
    memory.save("Phase 91 Batch 1 vertical slice memory.")

    response = orchestrator.handle_request(
        "ask jarvis to: what have I asked you to remember recently"
    )

    assert response.success is True
    assert response.message.startswith("[Jarvis tool result]")
    assert "Phase 91 Batch 1 vertical slice memory." in response.message
    assert response.tool_result is not None
    assert response.tool_result.tool_name == "memory"
    assert len(provider.received_requests) == 1
    assert len(_tool_call_events(logger)) == 1


def test_memory_list_recent_never_reaches_the_save_operation() -> None:
    """A structural, behavioural proof that memory_list_recent can only
    ever read: saving a memory through this capability is impossible,
    since the real MemoryTool.run() only ever receives
    operation="list" - never a model-supplied value - for this
    capability."""
    router, _, logger = _router(_MEMORY_LIST_RECENT_EXECUTE_TEXT)
    orchestrator, memory, _ = _build_real_orchestrator_with_phase_91_batch_1_tools(
        router, logger
    )
    before_count = memory.count()

    orchestrator.handle_request(
        "ask jarvis to: remember that Phase 91 introduced new capabilities"
    )

    assert memory.count() == before_count


def test_health_check_and_schedule_list_and_memory_list_recent_reject_extra_arguments() -> None:
    """Each Batch 1 zero-argument capability, plus Batch 2's
    memory_search (which declares only "value"), rejects any
    unrecognised "arguments" key via the existing, strict parser before
    any preflight or execution is attempted."""
    for capability_id in (
        "health_check",
        "schedule_list",
        "memory_list_recent",
        "memory_search",
    ):
        stray_argument_text = json.dumps(
            {
                "decision": "execute",
                "capability_id": capability_id,
                "arguments": {"unexpected": "value"},
            }
        )
        router, provider, logger = _router(stray_argument_text)
        orchestrator, _, _ = _build_real_orchestrator_with_phase_91_batch_1_tools(
            router, logger
        )

        response = orchestrator.handle_request("ask jarvis to: do something")

        assert response.success is False
        assert "could not safely process" in response.message.lower()
        assert len(_tool_call_events(logger)) == 0


def test_wrongly_typed_arguments_container_is_rejected_for_new_capabilities() -> None:
    """"arguments" must be a JSON object - an array, string, null,
    number, or boolean is rejected outright, for every capability."""
    for malformed_arguments in ('"not an object"', "[]", "null", "42", "true"):
        malformed_text = (
            '{"decision": "execute", "capability_id": "health_check", '
            f'"arguments": {malformed_arguments}}}'
        )
        router, _, logger = _router(malformed_text)
        orchestrator, _, _ = _build_real_orchestrator_with_phase_91_batch_1_tools(
            router, logger
        )

        response = orchestrator.handle_request("ask jarvis to: check jarvis's health")

        assert response.success is False
        assert len(_tool_call_events(logger)) == 0


def test_unsupported_capability_name_remains_rejected_alongside_new_capabilities() -> None:
    unsupported_name_text = json.dumps(
        {
            "decision": "execute",
            "capability_id": "delete_everything",
            "arguments": {},
        }
    )
    router, _, logger = _router(unsupported_name_text)
    orchestrator, _, _ = _build_real_orchestrator_with_phase_91_batch_1_tools(
        router, logger
    )

    response = orchestrator.handle_request("ask jarvis to: do something unsafe")

    assert response.success is False
    assert len(_tool_call_events(logger)) == 0


def test_only_one_capability_executes_per_request() -> None:
    """A structured decision names at most one capability_id - there is
    no mechanism anywhere in the schema or the execution path for more
    than one tool to execute per "ask jarvis to:" request."""
    router, _, logger = _router(_HEALTH_CHECK_EXECUTE_TEXT)
    orchestrator, _, _ = _build_real_orchestrator_with_phase_91_batch_1_tools(
        router, logger
    )

    orchestrator.handle_request("ask jarvis to: check jarvis's health")

    assert len(_tool_call_events(logger)) == 1


def test_project_state_show_behavior_is_unaffected_by_new_capabilities() -> None:
    router, provider, logger = _router(_EXECUTE_TEXT)
    orchestrator, _, _ = _build_real_orchestrator_with_phase_91_batch_1_tools(
        router, logger
    )

    response = orchestrator.handle_request("ask jarvis to: show my project state")

    assert response.success is True
    assert response.message.startswith("[Jarvis tool result]")
    assert response.tool_result.tool_name == "project_state_show"


_MEMORY_SEARCH_EXECUTE_TEXT = json.dumps(
    {
        "decision": "execute",
        "capability_id": "memory_search",
        "arguments": {"value": "deployment checklist"},
    }
)


def test_memory_search_executes_through_real_tool_executor_and_grounds_response() -> None:
    router, provider, logger = _router(_MEMORY_SEARCH_EXECUTE_TEXT)
    orchestrator, memory, _ = _build_real_orchestrator_with_phase_91_batch_1_tools(
        router, logger
    )
    memory.save("Remember to review the deployment checklist before release.")
    memory.save("An unrelated memory about lunch plans.")

    response = orchestrator.handle_request(
        "ask jarvis to: search my memories for deployment checklist"
    )

    assert response.success is True
    assert response.message.startswith("[Jarvis tool result]")
    assert "Remember to review the deployment checklist before release." in response.message
    assert "An unrelated memory about lunch plans." not in response.message
    assert response.tool_result is not None
    assert response.tool_result.tool_name == "memory"
    assert response.tool_result.success is True
    assert len(provider.received_requests) == 1
    assert len(_tool_call_events(logger)) == 1


def test_memory_search_real_no_results_grounds_the_response() -> None:
    router, provider, logger = _router(_MEMORY_SEARCH_EXECUTE_TEXT)
    orchestrator, memory, _ = _build_real_orchestrator_with_phase_91_batch_1_tools(
        router, logger
    )
    memory.save("An unrelated memory that will never match the query.")

    response = orchestrator.handle_request(
        "ask jarvis to: search my memories for deployment checklist"
    )

    assert response.success is True
    assert response.tool_result is not None
    assert response.tool_result.success is True
    assert "none found" in response.message.lower()


def test_memory_search_never_reaches_the_save_operation() -> None:
    """A structural, behavioural proof that memory_search can only ever
    read: the real MemoryTool.run() only ever receives
    operation="search" for this capability - never a model-supplied
    value - so saving a memory through it is impossible."""
    router, _, logger = _router(_MEMORY_SEARCH_EXECUTE_TEXT)
    orchestrator, memory, _ = _build_real_orchestrator_with_phase_91_batch_1_tools(
        router, logger
    )
    before_count = memory.count()

    orchestrator.handle_request(
        "ask jarvis to: remember that Phase 91 Batch 2 introduced memory search"
    )

    assert memory.count() == before_count


# --- Real execution / grounded response -----------------------------------------


def test_real_execution_through_real_tool_executor_grounds_the_response() -> None:
    router, provider, logger = _router(_EXECUTE_TEXT)
    orchestrator, _, project_state_store, _ = _build_real_orchestrator(router, logger)
    project_state_store.update("branch", "phase-90-batch2")
    project_state_store.update("focus", "tool selection")

    response = orchestrator.handle_request("ask jarvis to: show my project state")

    assert response.success is True
    assert response.message.startswith("[Jarvis tool result]")
    assert "phase-90-batch2" in response.message
    assert "tool selection" in response.message
    assert response.tool_result is not None
    assert response.tool_result.success is True
    assert len(provider.received_requests) == 1


def test_no_second_ai_call_after_execution() -> None:
    router, provider, logger = _router(_EXECUTE_TEXT)
    orchestrator, _, _, _ = _build_real_orchestrator(router, logger)

    orchestrator.handle_request("ask jarvis to: show my project state")

    assert len(provider.received_requests) == 1


def test_exactly_one_tool_executor_call_maximum() -> None:
    router, _, logger = _router(_EXECUTE_TEXT)
    orchestrator, _, _, _ = _build_real_orchestrator(router, logger)

    orchestrator.handle_request("ask jarvis to: show my project state")

    assert len(_tool_call_events(logger)) == 1


# --- Unsupported ------------------------------------------------------------------


def test_unsupported_decision_returns_the_fixed_honest_message() -> None:
    router, provider, logger = _router(_UNSUPPORTED_TEXT)
    orchestrator, memory, _, _ = _build_real_orchestrator(router, logger)
    memory.save("Some unrelated stored memory.")

    response = orchestrator.handle_request("ask jarvis to: book me a flight to paris")

    assert response.success is True
    assert response.message == (
        "Jarvis could not find an allowlisted capability that can safely "
        "complete that request."
    )
    assert response.tool_result is None
    assert len(_tool_call_events(logger)) == 0


def test_unsupported_decision_never_falls_back_to_batch_1_or_generic() -> None:
    router, _, logger = _router(_UNSUPPORTED_TEXT)
    orchestrator, _, _, _ = _build_real_orchestrator(router, logger)

    response = orchestrator.handle_request("ask jarvis to: book me a flight")

    assert not response.message.startswith(
        "[AI advisory response - based on automatically assembled context]"
    )
    assert "does not yet have a tool to carry it out" not in response.message


# --- AI enablement gate -----------------------------------------------------------


def test_ai_reasoning_disabled_causes_zero_router_calls() -> None:
    logger = _RecordingLogger()
    orchestrator, _, _, _ = _build_real_orchestrator(None, logger)

    response = orchestrator.handle_request("ask jarvis to: show my project state")

    assert response.success is False
    assert "not enabled" in response.message


def test_provider_unavailable_is_distinguished_from_disabled() -> None:
    router, provider, logger = _router(_EXECUTE_TEXT, available=False)
    orchestrator, _, _, _ = _build_real_orchestrator(router, logger)

    response = orchestrator.handle_request("ask jarvis to: show my project state")

    assert response.success is False
    assert "not available" in response.message.lower()
    assert "not enabled" not in response.message
    assert provider.received_requests == []


def test_provider_failure_is_distinguished_from_unavailable_and_disabled() -> None:
    router, provider, logger = _router(_EXECUTE_TEXT, fail=True)
    orchestrator, _, _, _ = _build_real_orchestrator(router, logger)

    response = orchestrator.handle_request("ask jarvis to: show my project state")

    assert response.success is False
    assert "could not process" in response.message.lower()
    assert "not enabled" not in response.message
    assert len(provider.received_requests) == 1


def test_malformed_output_is_distinguished_as_invalid_not_unavailable() -> None:
    router, _, logger = _router("not valid json")
    orchestrator, _, _, _ = _build_real_orchestrator(router, logger)

    response = orchestrator.handle_request("ask jarvis to: show my project state")

    assert response.success is False
    assert "could not safely process" in response.message.lower()


def test_context_assembler_not_configured_fails_honestly() -> None:
    router, provider, logger = _router(_EXECUTE_TEXT)
    orchestrator, _, _, _ = _build_real_orchestrator(
        router, logger, with_context_assembler=False
    )

    response = orchestrator.handle_request("ask jarvis to: show my project state")

    assert response.success is False
    assert "not available" in response.message.lower()
    assert provider.received_requests == []


# --- Empty request -----------------------------------------------------------------


def test_empty_request_performs_no_retrieval_no_ai_call_no_execution() -> None:
    router, provider, logger = _router(_EXECUTE_TEXT)
    orchestrator, memory, _, _ = _build_real_orchestrator(router, logger)
    memory.save("Should never be touched.")

    response = orchestrator.handle_request("ask jarvis to:")

    assert response.success is False
    assert response.message == (
        "Please include what you'd like Jarvis to do after 'ask jarvis to:'"
    )
    assert provider.received_requests == []
    assert len(_tool_call_events(logger)) == 0


def test_whitespace_only_request_performs_no_retrieval_no_ai_call() -> None:
    router, provider, logger = _router(_EXECUTE_TEXT)
    orchestrator, _, _, _ = _build_real_orchestrator(router, logger)

    response = orchestrator.handle_request("ask jarvis to:    ")

    assert response.success is False
    assert provider.received_requests == []


# --- Execution-time classification divergence --------------------------------------


def test_execution_time_confirmation_required_divergence_is_refused_honestly() -> None:
    registry = ToolRegistry()
    registry.register_tool(_DivergingTool())
    router, _, logger = _router(_EXECUTE_TEXT)
    orchestrator, _, _, _ = _build_real_orchestrator(router, logger, registry=registry)

    response = orchestrator.handle_request("ask jarvis to: show my project state")

    assert response.success is False
    assert response.blocked is False
    assert "confirmation" in response.message.lower()
    assert response.approval_request is None


def test_execution_time_blocked_divergence_is_refused_honestly() -> None:
    registry = ToolRegistry()
    registry.register_tool(_AlwaysBlockedDivergingTool())
    router, _, logger = _router(_EXECUTE_TEXT)
    orchestrator, _, _, _ = _build_real_orchestrator(router, logger, registry=registry)

    response = orchestrator.handle_request("ask jarvis to: show my project state")

    assert response.success is False
    assert response.blocked is True
    assert response.approval_request is None


def test_no_approval_created_on_execution_time_divergence() -> None:
    registry = ToolRegistry()
    registry.register_tool(_DivergingTool())
    router, _, logger = _router(_EXECUTE_TEXT)
    orchestrator, _, _, _ = _build_real_orchestrator(router, logger, registry=registry)

    orchestrator.handle_request("ask jarvis to: show my project state")

    assert orchestrator.approvals.list_pending() == []
    assert orchestrator.approvals.list_decisions() == []


def test_execution_time_divergence_never_claims_success() -> None:
    registry = ToolRegistry()
    registry.register_tool(_DivergingTool())
    router, _, logger = _router(_EXECUTE_TEXT)
    orchestrator, _, _, _ = _build_real_orchestrator(router, logger, registry=registry)

    response = orchestrator.handle_request("ask jarvis to: show my project state")

    assert response.success is False


# --- Catalog/registry rejection ----------------------------------------------------


def test_catalogued_but_unregistered_tool_is_rejected_honestly() -> None:
    router, _, logger = _router(_EXECUTE_TEXT)
    orchestrator, _, _, _ = _build_real_orchestrator(
        router, logger, registry=ToolRegistry()
    )

    response = orchestrator.handle_request("ask jarvis to: show my project state")

    assert response.success is False
    assert "could not safely process" in response.message.lower()


# --- No approval / no store mutation -----------------------------------------------


def test_no_store_is_mutated_by_an_ask_jarvis_to_request() -> None:
    router, _, logger = _router(_EXECUTE_TEXT)
    orchestrator, memory, project_state_store, _ = _build_real_orchestrator(
        router, logger
    )
    memory.save("A memory that must remain unchanged.")
    before_count = memory.count()
    before_state = project_state_store.get()

    orchestrator.handle_request("ask jarvis to: show my project state")

    assert memory.count() == before_count
    assert project_state_store.get() == before_state


def test_no_approval_created_for_a_successful_execution() -> None:
    router, _, logger = _router(_EXECUTE_TEXT)
    orchestrator, _, _, _ = _build_real_orchestrator(router, logger)

    orchestrator.handle_request("ask jarvis to: show my project state")

    assert orchestrator.approvals.list_pending() == []


# --- Dispatch/routing regression: existing commands unaffected --------------------


def test_ask_jarvis_advisory_command_remains_unaffected() -> None:
    ai_engine_router, _, logger = _router(_EXECUTE_TEXT)
    orchestrator, memory, _, _ = _build_real_orchestrator(ai_engine_router, logger)
    memory.save("A relevant memory for the advisory path.")

    # ask jarvis: (Batch 1) has no reasoning_engine wired in this
    # fixture (only tool_selection_router), so it fails honestly and
    # distinctly from ask jarvis to: - proving the two commands are
    # dispatched to genuinely separate handlers, not a shared one.
    response = orchestrator.handle_request("ask jarvis: what is my focus")

    assert response.success is False
    assert "AI reasoning is not enabled" in response.message


def test_existing_deterministic_commands_are_unaffected() -> None:
    from tools.builtin import EchoTool

    registry = ToolRegistry()
    registry.register_tool(EchoTool())
    logger = _RecordingLogger()
    orchestrator, _, _, _ = _build_real_orchestrator(None, logger, registry=registry)

    response = orchestrator.handle_request("echo hello")

    assert response.success is True
    assert "hello" in response.message


def test_generic_fallback_is_unaffected_for_unmatched_text() -> None:
    logger = _RecordingLogger()
    orchestrator, _, _, _ = _build_real_orchestrator(None, logger)

    response = orchestrator.handle_request(
        "this text matches no known command at all whatsoever"
    )

    assert response.requires_confirmation is True


def test_unmatched_requests_never_trigger_ask_jarvis_to() -> None:
    router, provider, logger = _router(_EXECUTE_TEXT)
    orchestrator, _, _, _ = _build_real_orchestrator(router, logger)

    orchestrator.handle_request("this text matches no known command at all")

    assert provider.received_requests == []


# --- Structural safety tests --------------------------------------------------------


def _imported_names(source: str) -> set[str]:
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.update(alias.name for alias in node.names)
            if node.module:
                names.add(node.module)
    return names


def _real_code_identifiers(source: str) -> set[str]:
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
    return names


def test_planning_module_imports_no_forbidden_names() -> None:
    import intelligence.planning as module

    imported = _imported_names(inspect.getsource(module))
    for forbidden in (
        "git",
        "subprocess",
        "shutil",
        "WorkflowEngine",
        "workflow.engine",
        "ApprovalManager",
        "approval.approval_manager",
    ):
        assert forbidden not in imported


def test_structured_output_module_imports_no_forbidden_names() -> None:
    import intelligence.structured_output as module

    imported = _imported_names(inspect.getsource(module))
    for forbidden in ("git", "subprocess", "shutil", "ToolExecutor", "tools.executor"):
        assert forbidden not in imported


def test_capability_catalog_module_imports_no_forbidden_names() -> None:
    import intelligence.capability_catalog as module

    imported = _imported_names(inspect.getsource(module))
    for forbidden in ("git", "subprocess", "shutil", "ToolExecutor", "tools.executor"):
        assert forbidden not in imported


def test_planning_module_never_creates_an_approval() -> None:
    import intelligence.planning as module

    identifiers = _real_code_identifiers(inspect.getsource(module))
    assert "create_request" not in identifiers
    assert "ApprovalManager" not in identifiers


def test_planning_module_never_constructs_jarvis_trusted_context_items() -> None:
    import intelligence.planning as module

    identifiers = _real_code_identifiers(inspect.getsource(module))
    assert "JARVIS_TRUSTED" not in identifiers


def test_ask_jarvis_to_handler_never_touches_workflow_engine_or_approvals() -> None:
    from core.orchestrator import JarvisOrchestrator

    source = inspect.getsource(JarvisOrchestrator._handle_ask_jarvis_to_request)
    assert "self._workflow_engine" not in source
    assert "self._approvals" not in source
    assert "os.system" not in source
    assert "subprocess" not in source
