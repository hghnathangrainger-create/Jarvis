"""
test_orchestrator_update_focus_workflow.py

Unit tests for the explicit "ask jarvis to: update my project focus to
X" write-and-verify workflow (Phase 90, Batch 3; the historical "and
confirm it" trailing clause was dropped from _REQUEST in Phase 92,
Batch 1 - see intelligence/grounding.py and
docs/phase_92_implementation_plan.md, Section 20.7 - since it had no
real functional or documented significance and only existed to
preserve this file's own original illustrative wording):
CommandRouter.match_ask_jarvis_to() ->
JarvisOrchestrator._handle_ask_jarvis_to_request() ->
intelligence.planning.select_tool() (EXECUTABLE_WORKFLOW) ->
WorkflowEngine.run()/resume() -> JarvisOrchestrator.execute_approved().

Uses real Planner, SecurityManager, CommandRouter, ToolRegistry,
ToolExecutor, ApprovalManager, WorkflowEngine, MemoryManager (over a
real in-memory SQLite EpisodicMemoryStore), real ProjectStateStore,
the real ProjectStateUpdateTool/ProjectStateVerifyTool, real
ContextAssembler, and a real AIRouter wired to a real PromptBuilder and
a fake, in-memory AIProvider - no live Claude API call is ever made, no
real network call is ever made.

sqlalchemy-dependent imports are guarded by a try/except ImportError,
mirroring test_orchestrator_ask_jarvis_to.py's own established pattern.

Run with:
    pytest tests/unit/test_orchestrator_update_focus_workflow.py
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
    from approval.approval_manager import ApprovalManager
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


def _update_focus_text(value: str) -> str:
    return json.dumps(
        {
            "decision": "execute",
            "capability_id": "project_state_update_focus",
            "arguments": {"value": value},
        }
    )


def _build_stack(session_factory, router: AIRouter, *, durable: bool = False):
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
    approvals = ApprovalManager(pending_store=pending_store)
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


_REQUEST = "ask jarvis to: update my project focus to batch 3 verification"


# --- E. Approval tests -----------------------------------------------------------


def test_update_focus_cannot_execute_without_approval() -> None:
    router, provider = _router(_update_focus_text("batch 3 verification"))
    session_factory = _in_memory_session_factory()
    orchestrator, project_state_store, *_ = _build_stack(session_factory, router)

    response = orchestrator.handle_request(_REQUEST)

    assert response.success is False
    assert response.requires_confirmation is True
    assert project_state_store.get() is None


def test_initial_request_creates_a_real_pending_approval() -> None:
    router, _ = _router(_update_focus_text("batch 3 verification"))
    orchestrator, *_rest, approvals, _ = _build_stack(
        _in_memory_session_factory(), router
    )

    response = orchestrator.handle_request(_REQUEST)

    assert response.approval_request is not None
    assert approvals.has_pending(response.approval_request.request_id)
    assert response.approval_request.security_tier.name == "YELLOW"


def test_store_unchanged_while_pending() -> None:
    router, _ = _router(_update_focus_text("batch 3 verification"))
    orchestrator, project_state_store, *_ = _build_stack(
        _in_memory_session_factory(), router
    )

    orchestrator.handle_request(_REQUEST)

    assert project_state_store.get() is None


def test_verifier_does_not_execute_while_pending() -> None:
    router, _ = _router(_update_focus_text("batch 3 verification"))
    orchestrator, _, _, _, _, _ = _build_stack(_in_memory_session_factory(), router)

    response = orchestrator.handle_request(_REQUEST)

    # The only tool_result present is the write step's own
    # confirmation-required result - the verifier is never reached.
    assert response.tool_result is not None
    assert response.tool_result.tool_name == "project_state_update"
    assert response.tool_result.requires_confirmation is True


def test_approval_executes_the_workflow_exactly_once() -> None:
    router, _ = _router(_update_focus_text("batch 3 verification"))
    orchestrator, project_state_store, _, _, approvals, _ = _build_stack(
        _in_memory_session_factory(), router
    )

    response = orchestrator.handle_request(_REQUEST)
    decision = approvals.approve(response.approval_request.request_id, decided_by="test")
    final = orchestrator.execute_approved(response, decision)

    assert final.success is True
    assert project_state_store.get().focus == "batch 3 verification"


def test_duplicate_resume_does_not_duplicate_the_write() -> None:
    """Phase 94, Batch 1 foundation check: calling execute_approved() a
    second time with the same already-executed response/decision never
    performs a second real write. The real, unmodified
    _paused_workflow_id_for() only returns a workflow id for a workflow
    the real WorkflowEngine instance still actually has paused - since
    the first call already consumed it, the second call finds none and
    falls through to the existing, unmodified "no runnable tool for
    this action" honest response, never a second resume() or a second
    direct ToolExecutor.execute() call."""
    router, _ = _router(_update_focus_text("batch 3 verification"))
    orchestrator, project_state_store, _, _, approvals, _ = _build_stack(
        _in_memory_session_factory(), router
    )

    response = orchestrator.handle_request(_REQUEST)
    decision = approvals.approve(response.approval_request.request_id, decided_by="test")
    first = orchestrator.execute_approved(response, decision)

    assert first.success is True
    assert project_state_store.get().focus == "batch 3 verification"

    second = orchestrator.execute_approved(response, decision)

    # The durable value is still exactly the one real write - never
    # duplicated, never reverted, never re-applied a second time -
    # regardless of what the second, already-consumed call itself
    # reports.
    assert project_state_store.get().focus == "batch 3 verification"
    assert second.tool_result is None


def test_approved_arguments_are_immutable_between_approval_and_execution() -> None:
    """The paused Plan's own PlanStep.tool_input - not a fresh,
    re-derived value - is what actually executes: proven by mutating
    the *original* AI response text after the approval request already
    exists (simulating a hypothetically-compromised/late-changing
    input source) and confirming the durably-approved value, not any
    later value, is what gets written."""
    router, provider = _router(_update_focus_text("batch 3 verification"))
    orchestrator, project_state_store, _, _, approvals, _ = _build_stack(
        _in_memory_session_factory(), router
    )

    response = orchestrator.handle_request(_REQUEST)
    decision = approvals.approve(response.approval_request.request_id, decided_by="test")

    # Simulate a would-be-different value becoming available from the
    # same fake provider after approval - this must have zero effect,
    # since the already-built, already-approved Plan/PlanStep.tool_input
    # is what resume() actually executes, never a freshly re-derived one.
    provider._text = _update_focus_text("a completely different value")  # type: ignore[attr-defined]

    final = orchestrator.execute_approved(response, decision)

    assert final.success is True
    assert project_state_store.get().focus == "batch 3 verification"
    assert "a completely different value" not in final.message


def test_decline_executes_zero_writes() -> None:
    router, _ = _router(_update_focus_text("batch 3 verification"))
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


def test_no_fabricated_approval_is_ever_created_by_intelligence_code() -> None:
    """Structural proof: intelligence/planning.py never imports or
    calls ApprovalManager - WorkflowEngine is the sole approval
    authority. Uses real-code-identifier extraction (Name/Attribute AST
    nodes only) so a docstring merely mentioning "ApprovalManager" in
    prose never produces a false positive."""
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


def test_batch_2_show_remains_approval_free() -> None:
    show_text = json.dumps(
        {"decision": "execute", "capability_id": "project_state_show", "arguments": {}}
    )
    router, _ = _router(show_text)
    orchestrator, _, _, _, approvals, _ = _build_stack(
        _in_memory_session_factory(), router
    )

    response = orchestrator.handle_request("ask jarvis to: show my project state")

    assert response.requires_confirmation is False
    assert approvals.list_pending() == []


# --- F. Restart tests --------------------------------------------------------------


def test_durable_restart_end_to_end() -> None:
    engine = create_engine("sqlite:///:memory:")
    initialize_database(engine)
    session_factory = create_session_factory(engine)

    router, _ = _router(_update_focus_text("batch 3 verification"))
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

    # Confirm the durable paused plan really contains both steps and the
    # expected value, before any reload logic runs.
    persisted_rows = paused_store2.list_all()
    assert len(persisted_rows) == 1
    assert len(persisted_rows[0].plan_steps) == 2
    assert persisted_rows[0].plan_steps[0]["tool_input"]["value"] == (
        "batch 3 verification"
    )

    # Reload order: pending approvals before paused workflows.
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
    assert "batch 3 verification" in final.message
    assert project_state_store2.get().focus == "batch 3 verification"


def test_no_transient_planning_object_required_after_restart() -> None:
    """The reconstructed orchestrator (orchestrator2 above) never held a
    reference to the original StructuredPlan/PlanningOutcome/AI
    response - resume() succeeds using only the real, durable
    PausedWorkflowStore/PendingApprovalStore rows. This is proven
    structurally by test_durable_restart_end_to_end itself never
    passing any such object into orchestrator2's construction or into
    execute_approved() (only the original `response`/`decision`, both
    of which are plain, already-durable-shaped data)."""
    import core.orchestrator as module

    source = inspect.getsource(module.JarvisOrchestrator.execute_approved)
    assert "StructuredPlan" not in source
    assert "PlanningOutcome" not in source


# --- G. Verification tests (integration, beyond test_verification.py) --------------


class _MismatchingVerifyTool:
    """A test double for project_state_verify that always reports a
    fixed focus value different from whatever was actually written -
    used only to exercise a genuine FAILED-verification path, since the
    real update-then-verify pair always agrees in the ordinary flow."""

    name = "project_state_verify"
    description = "test double reporting a fixed, mismatching focus value"

    def action_for(self, request):
        return "show jarvis project state"

    def run(self, request):
        from tools.base_tool import ToolResult

        return ToolResult(
            tool_name=self.name,
            success=True,
            output="mismatched test double",
            metadata={"focus": "a completely different stored value"},
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
    router, _ = _router(_update_focus_text("batch 3 verification"))
    orchestrator, project_state_store, registry, _, approvals, _ = _build_stack(
        _in_memory_session_factory(), router
    )
    # Swap in a verifier double that always reports a different value,
    # so the real write succeeds but the real comparison genuinely
    # differs - the only way to exercise FAILED without patching
    # intelligence/verification.py's own already-unit-tested logic.
    registry._tools["project_state_verify"] = _MismatchingVerifyTool()  # type: ignore[attr-defined]

    response = orchestrator.handle_request(_REQUEST)
    decision = approvals.approve(response.approval_request.request_id, decided_by="test")
    final = orchestrator.execute_approved(response, decision)

    assert final.success is False
    assert "not confirmed" in final.message
    assert "reported success" in final.message
    assert final.intelligence_trace[1] == "Step 2/2: verification failed."
    # The real write itself still genuinely happened.
    assert project_state_store.get().focus == "batch 3 verification"


def test_write_failure_means_verifier_never_runs() -> None:
    router, _ = _router(_update_focus_text("batch 3 verification"))
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


# --- H. Response/trace tests --------------------------------------------------------


def test_pending_response_says_not_executed() -> None:
    router, _ = _router(_update_focus_text("batch 3 verification"))
    orchestrator, *_ = _build_stack(_in_memory_session_factory(), router)

    response = orchestrator.handle_request(_REQUEST)

    assert response.success is False
    assert response.requires_confirmation is True
    assert len(response.intelligence_trace) == 1
    assert len(response.intelligence_trace[0]) <= 200


def test_approved_verified_response_is_grounded_in_real_values() -> None:
    router, _ = _router(_update_focus_text("batch 3 verification"))
    orchestrator, project_state_store, _, _, approvals, _ = _build_stack(
        _in_memory_session_factory(), router
    )

    response = orchestrator.handle_request(_REQUEST)
    decision = approvals.approve(response.approval_request.request_id, decided_by="test")
    final = orchestrator.execute_approved(response, decision)

    assert final.success is True
    assert "batch 3 verification" in final.message
    assert "Verification succeeded" in final.message
    assert len(final.intelligence_trace) == 2
    assert all(len(entry) <= 200 for entry in final.intelligence_trace)
    assert "verified" in final.intelligence_trace[1]


def test_declined_response_says_no_update_was_made() -> None:
    router, _ = _router(_update_focus_text("batch 3 verification"))
    orchestrator, project_state_store, _, _, approvals, _ = _build_stack(
        _in_memory_session_factory(), router
    )

    response = orchestrator.handle_request(_REQUEST)
    decision = approvals.decline(response.approval_request.request_id, decided_by="test")
    final = orchestrator.execute_approved(response, decision)

    assert final.success is False
    assert project_state_store.get() is None


def test_no_raw_dictionaries_in_intelligence_trace() -> None:
    router, _ = _router(_update_focus_text("batch 3 verification"))
    orchestrator, _, _, _, approvals, _ = _build_stack(
        _in_memory_session_factory(), router
    )

    response = orchestrator.handle_request(_REQUEST)
    decision = approvals.approve(response.approval_request.request_id, decided_by="test")
    final = orchestrator.execute_approved(response, decision)

    for entry in final.intelligence_trace:
        assert "{" not in entry
        assert "tool_input" not in entry


def test_existing_jarvis_response_callers_retain_empty_default_trace() -> None:
    from core.request_models import JarvisResponse

    response = JarvisResponse(success=True, message="ok")
    assert response.intelligence_trace == ()


def test_no_second_ai_call_after_execution() -> None:
    router, provider = _router(_update_focus_text("batch 3 verification"))
    orchestrator, _, _, _, approvals, _ = _build_stack(
        _in_memory_session_factory(), router
    )

    response = orchestrator.handle_request(_REQUEST)
    assert len(provider.received_requests) == 1
    decision = approvals.approve(response.approval_request.request_id, decided_by="test")
    orchestrator.execute_approved(response, decision)

    assert len(provider.received_requests) == 1


# --- I. Routing/regression tests -----------------------------------------------------


def test_ask_jarvis_advisory_remains_unaffected_by_update_focus_addition() -> None:
    router, _ = _router(_update_focus_text("x"))
    orchestrator, *_ = _build_stack(_in_memory_session_factory(), router)

    response = orchestrator.handle_request("ask jarvis: what is my focus")

    assert response.success is False
    assert "AI reasoning is not enabled" in response.message


def test_existing_deterministic_command_remains_unaffected() -> None:
    router, _ = _router(_update_focus_text("x"))
    orchestrator, *_ = _build_stack(_in_memory_session_factory(), router)

    response = orchestrator.handle_request("show jarvis project state")

    assert response.success is True
    assert "Jarvis Project State" in response.message


# --- J. Structural tests --------------------------------------------------------------


def test_planning_module_never_calls_project_state_store_update_directly() -> None:
    import intelligence.planning as module

    source = inspect.getsource(module)
    assert "ProjectStateStore" not in source
    assert ".update(" not in source


def test_orchestrator_update_focus_methods_never_bypass_workflow_engine() -> None:
    from core.orchestrator import JarvisOrchestrator

    for method in (
        JarvisOrchestrator._start_update_focus_workflow,
        JarvisOrchestrator._update_focus_workflow_result_to_response,
    ):
        source = inspect.getsource(method)
        assert "self._executor.execute(" not in source
        assert ".run(" not in source or "tool.run(" not in source


def test_no_forbidden_imports_in_verification_module() -> None:
    import intelligence.verification as module

    tree = ast.parse(inspect.getsource(module))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.update(alias.name for alias in node.names)
            if node.module:
                imported.add(node.module)
    for forbidden in (
        "git",
        "subprocess",
        "shutil",
        "ToolExecutor",
        "WorkflowEngine",
        "ApprovalManager",
    ):
        assert forbidden not in imported


# --- K. Phase 92, Batch 1: grounding refusal zero-side-effect tests -----------------


def test_ungrounded_update_focus_value_creates_no_approval_and_no_write() -> None:
    """A structurally valid update-focus decision whose argument value
    has no relationship to the live request is refused by
    intelligence.grounding.ground_decision() before _preflight_capability()
    ever runs - so no YELLOW approval is ever created and the store is
    never touched, unlike the ordinary pending-approval path exercised
    above by test_initial_request_creates_a_real_pending_approval."""
    router, provider = _router(_update_focus_text("an entirely fabricated value"))
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


def test_negated_update_focus_request_creates_no_approval_and_no_write() -> None:
    """A request that explicitly negates the update ("do not ... ")
    is refused by the negation gate - the very first check inside
    ground_decision() - before any signature, argument, preflight, or
    approval logic runs."""
    router, _ = _router(_update_focus_text("batch 3 verification"))
    orchestrator, project_state_store, _, _, approvals, _ = _build_stack(
        _in_memory_session_factory(), router
    )

    response = orchestrator.handle_request(
        "ask jarvis to: do not update my project focus to batch 3 verification"
    )

    assert response.success is False
    assert response.requires_confirmation is False
    assert approvals.list_pending() == []
    assert project_state_store.get() is None


def test_ungrounded_update_focus_never_reaches_workflow_engine() -> None:
    """Structural proof, complementing the behavioural proofs above:
    the UNGROUNDED_SELECTION branch in
    JarvisOrchestrator._handle_ask_jarvis_to_request() returns directly
    and never calls _start_update_focus_workflow() (the only path that
    can reach WorkflowEngine.run())."""
    import textwrap

    import core.orchestrator as module

    source = inspect.getsource(module.JarvisOrchestrator._handle_ask_jarvis_to_request)
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


def test_ungrounded_update_focus_response_message_never_leaks_the_candidate_value() -> None:
    """The refusal message is one of the two fixed, generic Phase 92,
    Batch 2 public messages - it never echoes the fabricated/rejected
    argument value back to the caller, unlike the real success message
    which does (see test_approved_verified_response_is_grounded_in_real_values)."""
    router, _ = _router(_update_focus_text("an entirely fabricated value"))
    orchestrator, *_ = _build_stack(_in_memory_session_factory(), router)

    response = orchestrator.handle_request(_REQUEST)

    assert "an entirely fabricated value" not in response.message
    assert response.plan is not None


# --- L. Phase 92, Batch 2: public refusal-message mapping and end-to-end proofs -----


def test_ungrounded_update_focus_argument_mismatch_returns_exact_request_message() -> None:
    """An argument-value mismatch is one of the "exact-request" reasons
    (§ Batch 2 mapping) - the public message asks for a direct,
    exact restatement, never naming the mismatch mechanism."""
    from core.orchestrator import _ASK_JARVIS_TO_EXACT_REQUEST_REFUSAL_MESSAGE

    router, _ = _router(_update_focus_text("an entirely fabricated value"))
    orchestrator, *_ = _build_stack(_in_memory_session_factory(), router)

    response = orchestrator.handle_request(_REQUEST)

    assert response.message == _ASK_JARVIS_TO_EXACT_REQUEST_REFUSAL_MESSAGE


def test_negated_update_focus_returns_exact_request_message() -> None:
    """Negation is also an "exact-request" reason - same public
    message as an argument mismatch, never a distinct seventh wording."""
    from core.orchestrator import _ASK_JARVIS_TO_EXACT_REQUEST_REFUSAL_MESSAGE

    router, _ = _router(_update_focus_text("batch 3 verification"))
    orchestrator, *_ = _build_stack(_in_memory_session_factory(), router)

    response = orchestrator.handle_request(
        "ask jarvis to: do not update my project focus to batch 3 verification"
    )

    assert response.message == _ASK_JARVIS_TO_EXACT_REQUEST_REFUSAL_MESSAGE


def test_update_focus_argument_mismatch_creates_no_durable_pending_workflow() -> None:
    """Beyond the in-memory ApprovalManager proof already given by
    test_ungrounded_update_focus_value_creates_no_approval_and_no_write,
    this proves the durable PausedWorkflowStore itself is never written
    to on a refusal - a real, separately-constructed store instance
    over the same session factory reads back zero rows."""
    session_factory = _in_memory_session_factory()
    router, _ = _router(_update_focus_text("an entirely fabricated value"))
    orchestrator, project_state_store, *_ = _build_stack(
        session_factory, router, durable=True
    )

    response = orchestrator.handle_request(_REQUEST)

    assert response.success is False
    assert PausedWorkflowStore(session_factory).list_all() == []
    assert project_state_store.get() is None


def test_capability_mismatch_for_update_focus_executes_neither_tool() -> None:
    """A request that uniquely grounds project_state_show (a read),
    while the model instead selects project_state_update_focus (a
    write) with a fabricated value, is refused as
    selected_capability_not_unique_match - neither the correct tool
    (project_state_show, which the model never asked for) nor the
    incorrectly selected one (project_state_update_focus) executes,
    and the update-focus workflow is never even attempted."""
    from core.orchestrator import _ASK_JARVIS_TO_ACTION_SELECTION_REFUSAL_MESSAGE

    router, _ = _router(_update_focus_text("an entirely fabricated focus"))
    orchestrator, project_state_store, _, _, approvals, _ = _build_stack(
        _in_memory_session_factory(), router
    )

    response = orchestrator.handle_request("ask jarvis to: show my project state")

    assert response.success is False
    assert response.message == _ASK_JARVIS_TO_ACTION_SELECTION_REFUSAL_MESSAGE
    assert response.tool_result is None
    assert response.requires_confirmation is False
    assert approvals.list_pending() == []
    assert project_state_store.get() is None
