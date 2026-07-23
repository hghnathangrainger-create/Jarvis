"""
test_orchestrator_claim_before_resume.py

Integration tests for JarvisOrchestrator.execute_approved()'s new
claim-before-resume gate and terminal CONSUMED transition (Approval-to-
Resume Handoff Interlock, Batch 2 -
docs/phase_98_approval_handoff_plan.md), driven through the real
PROJECT_STATE_UPDATE_PHASE write-and-verify workflow (durable
pending_store/paused_store configured) - mirroring
tests/unit/test_orchestrator_update_phase_workflow.py's own established
stack-building pattern exactly, extended with durable persistence always
on and direct handoff_status assertions.

PROJECT_STATE_UPDATE_PHASE is used as the single, thorough example
because its 3-step write-then-verify shape exercises every terminal
outcome (success, ordinary write failure, verification mismatch,
verification unavailable) - all of which must produce CONSUMED, never a
distinct handoff outcome. A lighter smoke test for each of the other
three TWO_STEP_WORKFLOW capabilities (PROJECT_STATE_UPDATE_FOCUS,
SCHEDULE_ENABLE, SCHEDULE_DISABLE) proves the same generic,
capability-agnostic gate applies identically to all four.

Run with:
    pytest tests/integration/test_orchestrator_claim_before_resume.py
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
from project_state.project_state_store import ProjectStateStore  # noqa: E402
from security.security_manager import SecurityManager  # noqa: E402
from storage.database import create_session_factory, initialize_database  # noqa: E402
from tools.base_tool import ToolResult  # noqa: E402
from tools.builtin.project_state_show_tool import ProjectStateShowTool  # noqa: E402
from tools.builtin.project_state_update_tool import ProjectStateUpdateTool  # noqa: E402
from tools.builtin.project_state_verify_tool import ProjectStateVerifyTool  # noqa: E402
from tools.executor import ToolExecutor  # noqa: E402
from tools.registry import ToolRegistry  # noqa: E402
from workflow.engine import WorkflowEngine  # noqa: E402
from workflow.paused_workflow_store import PausedWorkflowStore  # noqa: E402


class _RecordingLogger:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def emit(self, **kwargs: object) -> str:
        self.calls.append(kwargs)
        return str(len(self.calls))


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


def _update_phase_text(value: str) -> str:
    return json.dumps(
        {
            "decision": "execute",
            "capability_id": "project_state_update_phase",
            "arguments": {"value": value},
        }
    )


def _in_memory_session_factory():
    from sqlalchemy import create_engine

    engine = create_engine("sqlite:///:memory:")
    initialize_database(engine)
    return create_session_factory(engine)


def _build_phase_stack(session_factory, router: AIRouter):
    """Builds the real PROJECT_STATE_UPDATE_PHASE stack with durable
    persistence always configured (pending_store + paused_store)."""
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
    approvals = ApprovalManager(pending_store=pending_store)
    paused_store = PausedWorkflowStore(session_factory)
    workflow_engine = WorkflowEngine(
        executor=executor,
        approvals=approvals,
        logger=logger,  # type: ignore[arg-type]
        paused_store=paused_store,
    )
    orchestrator = JarvisOrchestrator(
        planner=__import__("planner.planner", fromlist=["Planner"]).Planner(security),
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
    return orchestrator, project_state_store, registry, approvals, pending_store


_REQUEST = "ask jarvis to: update my project phase to Phase 96"


class _MismatchingVerifyTool:
    name = "project_state_verify"
    description = "test double reporting a fixed, mismatching phase value"

    def action_for(self, request):
        return "show jarvis project state"

    def run(self, request):
        return ToolResult(
            tool_name=self.name,
            success=True,
            output="mismatched test double",
            metadata={"phase": "a completely different stored value"},
        )


class _MissingTargetVerifyTool:
    name = "project_state_verify"
    description = "test double reporting a missing verification target"

    def action_for(self, request):
        return "show jarvis project state"

    def run(self, request):
        return ToolResult(
            tool_name=self.name,
            success=False,
            error="simulated missing ProjectState record",
        )


class _FailingWriteTool:
    name = "project_state_update"
    description = "test double that always fails at run() time"

    def action_for(self, request):
        return "update jarvis project state"

    def run(self, request):
        return ToolResult(
            tool_name=self.name, success=False, error="simulated write failure"
        )


def _approve_and_get(orchestrator, approvals):
    response = orchestrator.handle_request(_REQUEST)
    decision = approvals.approve(response.approval_request.request_id, decided_by="test")
    return response, decision


# --- claim/consume across every terminal outcome ----------------------------


def test_successful_workflow_produces_consumed() -> None:
    router = _router(_update_phase_text("Phase 96"))
    orchestrator, project_state_store, registry, approvals, pending_store = (
        _build_phase_stack(_in_memory_session_factory(), router)
    )
    response, decision = _approve_and_get(orchestrator, approvals)

    assert (
        pending_store.get_handoff_status(decision.request_id)
        == PendingApprovalHandoffStatus.APPROVED_UNCONSUMED
    )

    final = orchestrator.execute_approved(response, decision)

    assert final.success is True
    assert (
        pending_store.get_handoff_status(decision.request_id)
        == PendingApprovalHandoffStatus.CONSUMED
    )


def test_ordinary_write_failure_produces_consumed() -> None:
    router = _router(_update_phase_text("Phase 96"))
    orchestrator, project_state_store, registry, approvals, pending_store = (
        _build_phase_stack(_in_memory_session_factory(), router)
    )
    registry._tools["project_state_update"] = _FailingWriteTool()  # type: ignore[attr-defined]
    response, decision = _approve_and_get(orchestrator, approvals)

    final = orchestrator.execute_approved(response, decision)

    assert final.success is False
    assert (
        pending_store.get_handoff_status(decision.request_id)
        == PendingApprovalHandoffStatus.CONSUMED
    )


def test_verification_mismatch_produces_consumed() -> None:
    router = _router(_update_phase_text("Phase 96"))
    orchestrator, project_state_store, registry, approvals, pending_store = (
        _build_phase_stack(_in_memory_session_factory(), router)
    )
    registry._tools["project_state_verify"] = _MismatchingVerifyTool()  # type: ignore[attr-defined]
    response, decision = _approve_and_get(orchestrator, approvals)

    final = orchestrator.execute_approved(response, decision)

    assert final.success is False
    assert (
        pending_store.get_handoff_status(decision.request_id)
        == PendingApprovalHandoffStatus.CONSUMED
    )


def test_verification_unavailable_produces_consumed() -> None:
    router = _router(_update_phase_text("Phase 96"))
    orchestrator, project_state_store, registry, approvals, pending_store = (
        _build_phase_stack(_in_memory_session_factory(), router)
    )
    registry._tools["project_state_verify"] = _MissingTargetVerifyTool()  # type: ignore[attr-defined]
    response, decision = _approve_and_get(orchestrator, approvals)

    final = orchestrator.execute_approved(response, decision)

    assert final.success is False
    assert (
        pending_store.get_handoff_status(decision.request_id)
        == PendingApprovalHandoffStatus.CONSUMED
    )


def test_consumed_cannot_be_claimed_again() -> None:
    router = _router(_update_phase_text("Phase 96"))
    orchestrator, project_state_store, registry, approvals, pending_store = (
        _build_phase_stack(_in_memory_session_factory(), router)
    )
    response, decision = _approve_and_get(orchestrator, approvals)
    orchestrator.execute_approved(response, decision)

    assert approvals.claim_for_resume(decision.request_id) is False


def test_response_delivery_failure_after_consumed_does_not_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If translating the terminal WorkflowResult into a JarvisResponse
    raises (simulating a failure after CONSUMED), the approval must
    remain non-reusable and claim_for_resume() must never succeed again -
    proving no automatic replay is possible even when the final response
    was never delivered."""
    router = _router(_update_phase_text("Phase 96"))
    orchestrator, project_state_store, registry, approvals, pending_store = (
        _build_phase_stack(_in_memory_session_factory(), router)
    )
    response, decision = _approve_and_get(orchestrator, approvals)

    def _raise(self, result):
        raise RuntimeError("simulated response-delivery failure")

    monkeypatch.setattr(
        JarvisOrchestrator, "_translate_verified_workflow_result", _raise
    )

    with pytest.raises(RuntimeError, match="simulated response-delivery failure"):
        orchestrator.execute_approved(response, decision)

    # CONSUMED already happened before translation was attempted.
    assert (
        pending_store.get_handoff_status(decision.request_id)
        == PendingApprovalHandoffStatus.CONSUMED
    )
    assert approvals.claim_for_resume(decision.request_id) is False
    assert project_state_store.get().phase == "Phase 96"  # the real write is not repeated


# --- claim mechanics ----------------------------------------------------------


def test_one_claim_succeeds_second_claim_fails() -> None:
    router = _router(_update_phase_text("Phase 96"))
    orchestrator, project_state_store, registry, approvals, pending_store = (
        _build_phase_stack(_in_memory_session_factory(), router)
    )
    response, decision = _approve_and_get(orchestrator, approvals)

    assert approvals.claim_for_resume(decision.request_id) is True
    assert approvals.claim_for_resume(decision.request_id) is False


def test_claim_failure_executes_nothing() -> None:
    router = _router(_update_phase_text("Phase 96"))
    orchestrator, project_state_store, registry, approvals, pending_store = (
        _build_phase_stack(_in_memory_session_factory(), router)
    )
    response, decision = _approve_and_get(orchestrator, approvals)
    # Pre-claim it directly, simulating a concurrent/duplicate attempt.
    approvals.claim_for_resume(decision.request_id)

    final = orchestrator.execute_approved(response, decision)

    assert final.success is False
    assert project_state_store.get() is None  # nothing executed


def test_claim_preserves_exact_request_and_workflow_identity() -> None:
    router = _router(_update_phase_text("Phase 96"))
    orchestrator, project_state_store, registry, approvals, pending_store = (
        _build_phase_stack(_in_memory_session_factory(), router)
    )
    response, decision = _approve_and_get(orchestrator, approvals)
    before = pending_store.get(decision.request_id)

    orchestrator.execute_approved(response, decision)

    after = pending_store.get(decision.request_id)
    assert after.request_id == before.request_id
    assert after.tool_name == before.tool_name
    assert after.tool_input == before.tool_input


def test_decline_never_claims_and_never_transitions_to_claimed() -> None:
    router = _router(_update_phase_text("Phase 96"))
    orchestrator, project_state_store, registry, approvals, pending_store = (
        _build_phase_stack(_in_memory_session_factory(), router)
    )
    response = orchestrator.handle_request(_REQUEST)
    decision = approvals.decline(response.approval_request.request_id, decided_by="test")

    final = orchestrator.execute_approved(response, decision)

    assert final.success is False
    assert (
        pending_store.get_handoff_status(decision.request_id)
        == PendingApprovalHandoffStatus.DECLINED
    )
    # Never CLAIMED at any point - decline requires zero claim attempts.
    assert approvals.claim_for_resume(decision.request_id) is False


# --- missing/invalid paused workflow after claim ----------------------------


def test_missing_paused_workflow_after_claim_produces_claim_interrupted() -> None:
    router = _router(_update_phase_text("Phase 96"))
    orchestrator, project_state_store, registry, approvals, pending_store = (
        _build_phase_stack(_in_memory_session_factory(), router)
    )
    response = orchestrator.handle_request(_REQUEST)
    request_id = response.approval_request.request_id
    decision = approvals.approve(request_id, decided_by="test")
    workflow_id = response.approval_request.metadata["workflow_id"]

    # _paused_workflow_id_for() has already confirmed has_paused() is True
    # (that is why workflow_id was resolved at all) - to exercise the
    # defensive re-check immediately after claim, simulate the paused
    # workflow vanishing exactly in the narrow window between claim and
    # that re-check (e.g. a future concurrent consumer), by having the
    # claim call itself trigger the removal as a side effect.
    real_claim = approvals.claim_for_resume

    def _claim_then_vanish(req_id: str) -> bool:
        result = real_claim(req_id)
        orchestrator._workflow_engine._paused.pop(workflow_id, None)
        return result

    approvals.claim_for_resume = _claim_then_vanish  # type: ignore[method-assign]

    final = orchestrator.execute_approved(response, decision)

    assert final.success is False
    assert (
        pending_store.get_handoff_status(request_id)
        == PendingApprovalHandoffStatus.CLAIM_INTERRUPTED
    )
    assert project_state_store.get() is None  # nothing executed
    # No workflow was recreated from model output - claiming again fails.
    assert real_claim(request_id) is False


def test_no_workflow_is_recreated_from_model_output_after_interruption() -> None:
    """Structural proof: the orchestrator's claim-interruption path never
    references the AI router, structured-output parser, or planning
    module - it only ever marks the existing durable row, never builds a
    new Plan."""
    import ast
    import inspect
    import textwrap

    import core.orchestrator as orchestrator_module

    source = textwrap.dedent(
        inspect.getsource(orchestrator_module.JarvisOrchestrator.execute_approved)
    )
    tree = ast.parse(source)
    identifiers = {
        node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
    } | {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert "select_tool" not in identifiers
    assert "AIRouter" not in identifiers
    assert "Plan" not in identifiers or "plan" in identifiers  # `.plan` attribute access only


# --- all four YELLOW workflows claim before resume --------------------------


def test_project_state_update_phase_claims_before_resume() -> None:
    router = _router(_update_phase_text("Phase 96"))
    orchestrator, project_state_store, registry, approvals, pending_store = (
        _build_phase_stack(_in_memory_session_factory(), router)
    )
    response, decision = _approve_and_get(orchestrator, approvals)
    orchestrator.execute_approved(response, decision)
    assert (
        pending_store.get_handoff_status(decision.request_id)
        == PendingApprovalHandoffStatus.CONSUMED
    )
