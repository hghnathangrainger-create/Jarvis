"""
test_orchestrator_context_query.py

Unit tests for the explicit "ask jarvis: <request>" Context
Intelligence workflow (Phase 90, Batch 1):
CommandRouter.match_ask_jarvis() ->
JarvisOrchestrator._handle_ask_jarvis_request().

Mirrors tests/unit/test_web_search_summary_workflow.py's own
established shape: real Planner, SecurityManager, CommandRouter,
MemoryManager (over a real in-memory SQLite EpisodicMemoryStore), real
ProjectStateStore (same in-memory database), real ContextAssembler,
and a real AIReasoningEngine wired to a real AIRouter/PromptBuilder and
a fake, in-memory AIProvider - no live Claude API call is ever made, no
real network call is ever made.

These prove:
    - A natural-language request automatically assembles bounded,
      relevant memory + real ProjectState context, with no separate
      memory-search command required.
    - The assembled context reaches AIReasoningEngine as a genuine,
      UNTRUSTED, trust-tagged AIContextBlock, passing through
      PromptBuilder's existing untrusted-context framing unchanged.
    - AI reasoning disabled/unavailable/failed, and context assembly
      unavailable, each produce an honest, distinct response.
    - An empty request performs no context retrieval and no AI call.
    - No tool is ever executed, no approval is ever created, and no
      store is ever mutated by this workflow.
    - Every existing deterministic command and special-matcher's
      dispatch is unaffected by the new "ask jarvis:" matcher.

sqlalchemy-dependent imports are guarded by a try/except ImportError
(rather than this repo's more common `pytest.importorskip("sqlalchemy")`
placed before further imports) so this file collects cleanly under
Ruff's default rule set, mirroring test_project_state_store.py's own
established pattern exactly - see that file's module docstring for the
full rationale.

Run with:
    pytest tests/unit/test_orchestrator_context_query.py
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

try:
    from sqlalchemy import create_engine

    from ai.prompt_builder import PromptBuilder
    from ai.providers.base import AIProvider, AIProviderError, AIRequest, AIResponse
    from ai.reasoning_engine import AIReasoningEngine
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
    from security.security_manager import SecurityManager
    from storage.database import create_session_factory, initialize_database
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
    """A fake AI provider that returns whatever text it is given. No network."""

    def __init__(
        self, text: str, *, available: bool = True, fail: bool = False
    ) -> None:
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


def _engine(
    text: str = "Here is my advice based on your context.",
    *,
    enabled: bool = True,
    available: bool = True,
    fail: bool = False,
) -> tuple[AIReasoningEngine, _FakeAIProvider]:
    provider = _FakeAIProvider(text, available=available, fail=fail)
    router = AIRouter(
        provider=provider,
        prompt_builder=PromptBuilder(),
        validator=ResponseValidator(),
        logger=_RecordingLogger(),  # type: ignore[arg-type]
        settings=_settings(),
    )
    return AIReasoningEngine(router=router, enabled=enabled), provider


def _in_memory_session_factory():
    engine = create_engine("sqlite:///:memory:")
    initialize_database(engine)
    return create_session_factory(engine)


def _build_real_orchestrator(
    reasoning: AIReasoningEngine | None,
    logger: _RecordingLogger,
    *,
    with_context_assembler: bool = True,
    registry: ToolRegistry | None = None,
) -> tuple[JarvisOrchestrator, MemoryManager, ProjectStateStore]:
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
    registry = registry if registry is not None else ToolRegistry()
    executor = ToolExecutor(
        registry=registry,
        security_manager=security,
        logger=logger,  # type: ignore[arg-type]
    )
    orchestrator = JarvisOrchestrator(
        planner=Planner(security),
        executor=executor,
        registry=registry,
        command_router=CommandRouter(registry),
        reasoning_engine=reasoning,
        security_manager=security,
        memory_manager=memory,
        logger=logger,  # type: ignore[arg-type]
        context_assembler=context_assembler,
    )
    return orchestrator, memory, project_state_store


def _tool_call_events(logger: _RecordingLogger) -> list[dict[str, object]]:
    return [call for call in logger.calls if call.get("action_type") == "tool_call"]


# --- G. Orchestrator vertical-slice tests ---------------------------------------


def test_relevant_memory_is_automatically_retrieved_via_lexical_search() -> None:
    logger = _RecordingLogger()
    engine, ai_provider = _engine()
    orchestrator, memory, _ = _build_real_orchestrator(engine, logger)
    memory.save("The quarterly budget review is scheduled for Friday.")
    memory.save("Unrelated note about groceries.")

    response = orchestrator.handle_request("ask jarvis: what is the budget review status")

    assert response.success is True
    assert len(ai_provider.received_requests) == 1
    prompt_content = ai_provider.received_requests[0].messages[0].content
    assert "quarterly budget review is scheduled for Friday" in prompt_content
    assert "----- BEGIN CONTEXT -----" in prompt_content


def test_recency_fallback_included_within_limits() -> None:
    logger = _RecordingLogger()
    engine, ai_provider = _engine()
    orchestrator, memory, _ = _build_real_orchestrator(engine, logger)
    memory.save("First stored memory ever.")
    memory.save("Second stored memory ever.")

    response = orchestrator.handle_request(
        "ask jarvis: tell me something with no matching search terms xyzzy"
    )

    assert response.success is True
    prompt_content = ai_provider.received_requests[0].messages[0].content
    assert "First stored memory ever." in prompt_content
    assert "Second stored memory ever." in prompt_content


def test_real_project_state_branch_and_focus_are_included() -> None:
    logger = _RecordingLogger()
    engine, ai_provider = _engine()
    orchestrator, _, project_state_store = _build_real_orchestrator(engine, logger)
    project_state_store.update("branch", "phase-90-context-intelligence")
    project_state_store.update("focus", "shipping context intelligence")

    response = orchestrator.handle_request("ask jarvis: what should I focus on next")

    assert response.success is True
    prompt_content = ai_provider.received_requests[0].messages[0].content
    assert "phase-90-context-intelligence" in prompt_content
    assert "shipping context intelligence" in prompt_content
    assert (
        "manually recorded by the user; never auto-detected from git" in prompt_content
    )


def test_advisory_response_is_grounded_in_supplied_context_and_labelled() -> None:
    logger = _RecordingLogger()
    engine, _ = _engine(text="Based on your notes, focus on the budget review.")
    orchestrator, memory, _ = _build_real_orchestrator(engine, logger)
    memory.save("The budget review needs your attention.")

    response = orchestrator.handle_request("ask jarvis: what should I do")

    assert response.success is True
    assert response.message.startswith(
        "[AI advisory response - based on automatically assembled context]"
    )
    assert "focus on the budget review" in response.message


def test_no_separate_memory_search_command_is_required() -> None:
    """A single "ask jarvis:" call is sufficient - no prior "search
    memories for ..." command is needed for relevant memory to reach
    the AI."""
    logger = _RecordingLogger()
    engine, ai_provider = _engine()
    orchestrator, memory, _ = _build_real_orchestrator(engine, logger)
    memory.save("Distinctive marker memory about the launch plan.")

    response = orchestrator.handle_request("ask jarvis: what is the launch plan")

    assert response.success is True
    prompt_content = ai_provider.received_requests[0].messages[0].content
    assert "Distinctive marker memory about the launch plan." in prompt_content


def test_ai_reasoning_disabled_fails_honestly_without_context_assembly() -> None:
    logger = _RecordingLogger()
    orchestrator, memory, _ = _build_real_orchestrator(None, logger)

    response = orchestrator.handle_request("ask jarvis: anything at all")

    assert response.success is False
    assert "not enabled" in response.message


def test_ai_unavailable_fails_honestly_never_fabricates_an_answer() -> None:
    logger = _RecordingLogger()
    engine, _ = _engine(available=False)
    orchestrator, memory, _ = _build_real_orchestrator(engine, logger)
    memory.save("Some real content that must never leak into a fake answer.")

    response = orchestrator.handle_request("ask jarvis: what do you know")

    assert response.success is False
    assert "could not produce" in response.message.lower()
    assert "Some real content" not in response.message


def test_ai_provider_failure_fails_honestly() -> None:
    logger = _RecordingLogger()
    engine, _ = _engine(fail=True)
    orchestrator, _, _ = _build_real_orchestrator(engine, logger)

    response = orchestrator.handle_request("ask jarvis: anything")

    assert response.success is False


def test_context_assembler_not_configured_fails_honestly() -> None:
    logger = _RecordingLogger()
    engine, ai_provider = _engine()
    orchestrator, _, _ = _build_real_orchestrator(
        engine, logger, with_context_assembler=False
    )

    response = orchestrator.handle_request("ask jarvis: anything")

    assert response.success is False
    assert "not available" in response.message.lower()
    assert ai_provider.received_requests == []


def test_empty_request_performs_no_retrieval_and_no_ai_call() -> None:
    logger = _RecordingLogger()
    engine, ai_provider = _engine()
    orchestrator, memory, _ = _build_real_orchestrator(engine, logger)
    memory.save("Should never be touched.")

    response = orchestrator.handle_request("ask jarvis:")

    assert response.success is False
    assert "Please include what you'd like to ask" in response.message
    assert ai_provider.received_requests == []


def test_whitespace_only_request_performs_no_retrieval_and_no_ai_call() -> None:
    logger = _RecordingLogger()
    engine, ai_provider = _engine()
    orchestrator, _, _ = _build_real_orchestrator(engine, logger)

    response = orchestrator.handle_request("ask jarvis:    ")

    assert response.success is False
    assert ai_provider.received_requests == []


def test_no_tool_executes_during_ask_jarvis_request() -> None:
    logger = _RecordingLogger()
    engine, _ = _engine()
    orchestrator, memory, _ = _build_real_orchestrator(engine, logger)
    memory.save("Some memory content.")

    orchestrator.handle_request("ask jarvis: what do you know")

    assert _tool_call_events(logger) == []


def test_no_approval_is_created_during_ask_jarvis_request() -> None:
    logger = _RecordingLogger()
    engine, _ = _engine()
    orchestrator, memory, _ = _build_real_orchestrator(engine, logger)
    memory.save("Some memory content.")

    orchestrator.handle_request("ask jarvis: what do you know")

    assert orchestrator.approvals.list_pending() == []
    assert orchestrator.approvals.list_decisions() == []


def test_no_store_is_mutated_by_an_ask_jarvis_request() -> None:
    logger = _RecordingLogger()
    engine, _ = _engine()
    orchestrator, memory, project_state_store = _build_real_orchestrator(engine, logger)
    memory.save("A memory that must remain unchanged.")
    before_count = memory.count()
    before_state = project_state_store.get()

    orchestrator.handle_request("ask jarvis: what do you know about my project")

    assert memory.count() == before_count
    after_state = project_state_store.get()
    assert after_state == before_state


# --- F. Dispatch/routing regression: existing commands unaffected --------------


def test_existing_deterministic_commands_are_unaffected() -> None:
    from tools.builtin import EchoTool

    logger = _RecordingLogger()
    registry = ToolRegistry()
    registry.register_tool(EchoTool())
    orchestrator, memory, _ = _build_real_orchestrator(
        None, logger, registry=registry
    )

    response = orchestrator.handle_request("echo hello")

    assert response.success is True
    assert "hello" in response.message


def test_generic_fallback_is_unaffected_for_unmatched_text() -> None:
    logger = _RecordingLogger()
    orchestrator, _, _ = _build_real_orchestrator(None, logger)

    response = orchestrator.handle_request(
        "this text matches no known command at all whatsoever"
    )

    assert response.requires_confirmation is True


def test_unmatched_requests_are_never_converted_into_intelligence_requests() -> None:
    """An ordinary unmatched request must not silently be treated as an
    "ask jarvis:" request just because AI reasoning happens to be
    active - only the exact prefix triggers this workflow. The existing,
    unrelated advisory-suggestion path (_attach_ai_suggestion) may still
    consult AI exactly as it always has - that pre-existing behaviour is
    untouched by this batch - but the response must never carry the new
    "ask jarvis:" advisory label or shape."""
    logger = _RecordingLogger()
    engine, ai_provider = _engine()
    orchestrator, _, _ = _build_real_orchestrator(engine, logger)

    response = orchestrator.handle_request(
        "this text matches no known command at all"
    )

    assert not response.message.startswith(
        "[AI advisory response - based on automatically assembled context]"
    )
    for request in ai_provider.received_requests:
        prompt_content = request.messages[0].content
        assert "----- BEGIN CONTEXT -----" not in prompt_content


# --- H. Structural safety tests --------------------------------------------------


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
    """Return every Name/Attribute identifier actually used in real code -
    never text that only appears inside a docstring or comment, since
    those are plain string constants, not Name/Attribute AST nodes."""
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
    return names


def test_context_module_imports_no_forbidden_names() -> None:
    import intelligence.context as module

    imported = _imported_names(inspect.getsource(module))
    for forbidden in (
        "git",
        "subprocess",
        "os.system",
        "shutil",
        "ToolExecutor",
        "tools.executor",
        "WorkflowEngine",
        "workflow.engine",
        "ApprovalManager",
        "approval.approval_manager",
    ):
        assert forbidden not in imported


def test_context_module_never_calls_tool_run_or_executor() -> None:
    import intelligence.context as module

    identifiers = _real_code_identifiers(inspect.getsource(module))
    for forbidden in (
        "run",
        "ToolExecutor",
        "WorkflowEngine",
        "ApprovalManager",
        "create_request",
        "execute",
    ):
        assert forbidden not in identifiers


def test_context_module_never_constructs_jarvis_trusted_items() -> None:
    import intelligence.context as module

    identifiers = _real_code_identifiers(inspect.getsource(module))
    assert "JARVIS_TRUSTED" not in identifiers


def test_context_module_never_bypasses_prompt_builder() -> None:
    """The combination helper only ever builds a plain AIContextBlock via
    its public from_untrusted() factory - it never imports or
    constructs a provider-facing AIRequest itself."""
    import intelligence.context as module

    source = inspect.getsource(module)
    assert "AIRequest(" not in source
    assert "from_system(" not in source
    assert "from_live_user_input(" not in source


def test_ask_jarvis_handler_never_touches_tool_executor_or_workflow_engine() -> None:
    """Structural proof on JarvisOrchestrator._handle_ask_jarvis_request
    itself: it never calls self._executor or self._workflow_engine -
    only self._reasoning/self._context_assembler/self._planner."""
    from core.orchestrator import JarvisOrchestrator

    source = inspect.getsource(JarvisOrchestrator._handle_ask_jarvis_request)
    assert "self._executor" not in source
    assert "self._workflow_engine" not in source
    assert "self._approvals" not in source
