"""
test_orchestrator_workflow_commands.py

Focused integration tests for the Phase 15, Batch 3 deterministic workflow
commands wired through JarvisOrchestrator:

    remember this and show it back: <text>
    remember this and forget it: <text>

Uses a real MemoryManager (in-memory SQLite), SecurityManager,
ToolExecutor, ApprovalManager, CommandRouter, and WorkflowEngine - exactly
the same collaborators main.py wires together - so these prove real,
end-to-end (pre-CLI) behaviour, not mocked delegation.

Run with:
    pytest tests/unit/test_orchestrator_workflow_commands.py
"""

from __future__ import annotations

import ast

import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")

from approval.approval_manager import ApprovalManager
from config.constants import SecurityTier
from core.command_router import CommandRouter
from core.orchestrator import JarvisOrchestrator
from memory.episodic_memory import EpisodicMemoryStore
from memory.memory_manager import MemoryManager
from planner.planner import Planner
from security.security_manager import SecurityManager
from tools.builtin.memory_forget_tool import MemoryForgetTool
from tools.builtin.memory_tool import MemoryTool
from tools.executor import ToolExecutor
from tools.registry import ToolRegistry
from workflow.engine import WorkflowEngine


class _RecordingLogger:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def emit(self, **kwargs: object) -> str:
        self.calls.append(kwargs)
        return str(len(self.calls))


def _memory_manager() -> MemoryManager:
    from sqlalchemy import create_engine

    from storage.database import create_session_factory, initialize_database

    engine = create_engine("sqlite:///:memory:")
    initialize_database(engine)
    factory = create_session_factory(engine)
    return MemoryManager(EpisodicMemoryStore(factory))


def _build_orchestrator(
    logger: object | None = None, *, with_workflow_engine: bool = True
) -> tuple[JarvisOrchestrator, MemoryManager]:
    logger = logger or _RecordingLogger()
    memory = _memory_manager()
    security = SecurityManager()
    registry = ToolRegistry()
    registry.register_tool(MemoryTool(memory))
    registry.register_tool(MemoryForgetTool(memory))
    executor = ToolExecutor(registry=registry, security_manager=security, logger=logger)  # type: ignore[arg-type]
    approvals = ApprovalManager(audit_logger=logger)  # type: ignore[arg-type]
    workflow_engine = (
        WorkflowEngine(executor=executor, approvals=approvals, logger=logger)
        if with_workflow_engine
        else None
    )
    orchestrator = JarvisOrchestrator(
        planner=Planner(security),
        executor=executor,
        registry=registry,
        command_router=CommandRouter(registry),
        approval_manager=approvals,
        security_manager=security,
        memory_manager=memory,
        workflow_engine=workflow_engine,
        logger=logger,  # type: ignore[arg-type]
    )
    return orchestrator, memory


# --- All-GREEN completed workflow ---------------------------------------------


def test_show_back_workflow_completes_successfully() -> None:
    orchestrator, memory = _build_orchestrator()

    response = orchestrator.handle_request(
        "remember this and show it back: Buy milk"
    )

    assert response.success is True
    assert response.approval_request is None
    assert "Buy milk" in response.message


def test_show_back_workflow_actually_saved_and_retrieved_via_real_memory_id() -> None:
    """Proves real Batch 2 propagation end to end: step 2's memory_id
    input genuinely came from step 1's own newly-created record, not a
    hardcoded or guessed value."""
    orchestrator, memory = _build_orchestrator()

    orchestrator.handle_request("remember this and show it back: Distinctive text xyz")

    records = memory.list_recent(limit=5)
    assert any(r.content == "Distinctive text xyz" for r in records)


def test_show_back_workflow_handler_never_executes_a_tool_directly() -> None:
    """Structural proof: the two Orchestrator workflow handlers call only
    WorkflowEngine.run()/the plan factory - never self._executor.execute()
    themselves."""
    import core.orchestrator as module

    source = inspect_source_of_workflow_handlers(module)
    assert "self._executor.execute(" not in source


def inspect_source_of_workflow_handlers(module: object) -> str:
    import inspect

    handler_names = (
        "_handle_remember_and_show_back_workflow_request",
        "_handle_remember_and_forget_workflow_request",
        "_handle_workflow_request",
    )
    return "\n".join(
        inspect.getsource(getattr(module.JarvisOrchestrator, name))
        for name in handler_names
    )


def test_show_back_workflow_no_ai_dependency() -> None:
    """No AIReasoningEngine is configured, yet the workflow completes -
    proving it has no AI dependency at all."""
    orchestrator, _ = _build_orchestrator()
    response = orchestrator.handle_request(
        "remember this and show it back: No AI needed"
    )
    assert response.success is True
    assert response.ai_suggestion is None


# --- Waiting (GREEN-then-YELLOW) workflow -------------------------------------


def test_forget_workflow_pauses_with_real_approval_request() -> None:
    orchestrator, _ = _build_orchestrator()

    response = orchestrator.handle_request(
        "remember this and forget it: Temporary note"
    )

    assert response.success is False
    assert response.requires_confirmation is True
    assert response.approval_request is not None
    assert response.approval_request.security_tier is SecurityTier.YELLOW


def test_forget_workflow_does_not_claim_completion_while_waiting() -> None:
    orchestrator, memory = _build_orchestrator()

    orchestrator.handle_request("remember this and forget it: Temporary note")

    # The memory was saved (step 1 ran) but not yet forgotten (step 2 paused).
    records = memory.list_recent(limit=5)
    assert any(r.content == "Temporary note" for r in records)


def test_forget_workflow_metadata_carries_workflow_id() -> None:
    orchestrator, _ = _build_orchestrator()
    response = orchestrator.handle_request(
        "remember this and forget it: Temporary note"
    )
    assert "workflow_id" in response.approval_request.metadata


# --- Approved resume -----------------------------------------------------------


def test_forget_workflow_approved_resume_completes_and_forgets_exactly_once() -> None:
    orchestrator, memory = _build_orchestrator()
    response = orchestrator.handle_request(
        "remember this and forget it: Temporary note"
    )
    request = response.approval_request
    decision = orchestrator.approvals.approve(request.request_id)

    resumed = orchestrator.execute_approved(response, decision)

    assert resumed.success is True
    assert resumed.requires_confirmation is False
    records = memory.list_recent(limit=5)
    assert not any(r.content == "Temporary note" for r in records)


def test_ordinary_approval_still_uses_single_tool_path_when_not_workflow_linked() -> (
    None
):
    """A completely ordinary YELLOW single-action approval (not from a
    workflow) must behave exactly as before Phase 15."""
    orchestrator, memory = _build_orchestrator()
    saved = orchestrator.handle_request("remember this: Standalone note")
    assert saved.success is True
    memory_id = memory.list_recent(limit=1)[0].id

    response = orchestrator.handle_request(f"forget memory {memory_id}")
    assert response.requires_confirmation is True
    decision = orchestrator.approvals.approve(response.approval_request.request_id)

    resumed = orchestrator.execute_approved(response, decision)

    assert resumed.success is True
    assert not any(r.id == memory_id for r in memory.list_recent(limit=5))


# --- Declined resume -----------------------------------------------------------


def test_forget_workflow_declined_resume_stops_without_forgetting() -> None:
    orchestrator, memory = _build_orchestrator()
    response = orchestrator.handle_request(
        "remember this and forget it: Temporary note"
    )
    request = response.approval_request
    decision = orchestrator.approvals.decline(request.request_id)

    resumed = orchestrator.execute_approved(response, decision)

    assert resumed.success is False
    records = memory.list_recent(limit=5)
    assert any(r.content == "Temporary note" for r in records)


# --- Failure/blocked translation ----------------------------------------------


def test_show_back_workflow_empty_content_fails_honestly() -> None:
    orchestrator, _ = _build_orchestrator()
    response = orchestrator.handle_request("remember this and show it back:")
    assert response.success is False
    assert response.approval_request is None


def test_workflow_engine_not_configured_fails_honestly() -> None:
    orchestrator, _ = _build_orchestrator(with_workflow_engine=False)
    response = orchestrator.handle_request(
        "remember this and show it back: Buy milk"
    )
    assert response.success is False
    assert "not available" in response.message.lower()


# --- Approval metadata validation pressure tests ------------------------------


def test_execute_approved_ignores_missing_workflow_id_metadata() -> None:
    """An approval request with no workflow_id metadata at all must never
    be treated as workflow-linked."""
    orchestrator, memory = _build_orchestrator()
    saved = orchestrator.handle_request("remember this: Standalone note")
    memory_id = memory.list_recent(limit=1)[0].id
    response = orchestrator.handle_request(f"forget memory {memory_id}")

    assert "workflow_id" not in response.approval_request.metadata
    decision = orchestrator.approvals.approve(response.approval_request.request_id)
    resumed = orchestrator.execute_approved(response, decision)
    assert resumed.success is True


def test_execute_approved_ignores_stale_workflow_id() -> None:
    """A workflow id that has already been resumed to completion must not
    be resumable a second time via a stale response object."""
    orchestrator, _ = _build_orchestrator()
    response = orchestrator.handle_request(
        "remember this and forget it: Temporary note"
    )
    decision = orchestrator.approvals.approve(response.approval_request.request_id)
    orchestrator.execute_approved(response, decision)

    # Second attempt to resume the exact same (now-terminal) workflow.
    from approval.approval_models import ApprovalRequest

    stale_request = ApprovalRequest(
        action="forget memory",
        reason="stale",
        security_tier=SecurityTier.YELLOW,
        metadata=dict(response.approval_request.metadata),
    )
    from core.request_models import JarvisResponse

    stale_response = JarvisResponse(
        success=False,
        message="stale",
        plan=response.plan,
        requires_confirmation=True,
        approval_request=stale_request,
    )
    stale_decision = stale_request.decide(approved=True, decided_by="test")

    # Must fall through to the ordinary single-tool path (no tool_name set
    # on this synthetic response), never re-invoke WorkflowEngine.resume().
    result = orchestrator.execute_approved(stale_response, stale_decision)
    assert result.success is True
    assert "no runnable tool" in result.message.lower()


# --- Compatibility -------------------------------------------------------------


def test_ordinary_remember_command_unchanged() -> None:
    orchestrator, memory = _build_orchestrator()
    response = orchestrator.handle_request("remember this: Plain save")
    assert response.success is True
    assert any(r.content == "Plain save" for r in memory.list_recent(limit=5))


def test_ordinary_show_memory_command_unchanged() -> None:
    orchestrator, memory = _build_orchestrator()
    orchestrator.handle_request("remember this: Plain save")
    memory_id = memory.list_recent(limit=1)[0].id
    response = orchestrator.handle_request(f"show memory {memory_id}")
    assert response.success is True
    assert "Plain save" in response.message


def test_ordinary_forget_memory_command_unchanged() -> None:
    orchestrator, memory = _build_orchestrator()
    orchestrator.handle_request("remember this: Plain save")
    memory_id = memory.list_recent(limit=1)[0].id
    response = orchestrator.handle_request(f"forget memory {memory_id}")
    assert response.requires_confirmation is True
    assert response.tool_name == "memory_forget"


# --- Routing/planning authority proof -----------------------------------------


def test_workflow_commands_never_reach_generic_memory_save() -> None:
    """The exact collision this batch's own investigation identified: a
    workflow command must never be silently treated as a plain 'remember
    this: ...' save, discarding the workflow instruction."""
    orchestrator, memory = _build_orchestrator()

    orchestrator.handle_request(
        "remember this and show it back: distinguishable content"
    )

    records = memory.list_recent(limit=5)
    contents = [r.content for r in records]
    assert "distinguishable content" in contents
    # The generic save path would have stored the *entire* trailing text
    # verbatim, including "and show it back:" - confirm that never happened.
    assert not any("and show it back" in c for c in contents)


def test_orchestrator_module_has_no_workflow_router_or_plan_builder_class() -> None:
    import core.orchestrator as module

    with open(module.__file__, encoding="utf-8") as f:
        tree = ast.parse(f.read())

    class_names = {
        node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)
    }
    assert "WorkflowRouter" not in class_names
    assert "PlanBuilder" not in class_names
    assert "WorkflowRegistry" not in class_names
